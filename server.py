#!/usr/bin/env python3
"""ZILL integrated demonstration platform. One origin, SQLite, server-enforced role and scope."""
from __future__ import annotations
import os, json, sqlite3, secrets, hashlib, hmac, time, re, sys, csv, io
from http.server import HTTPServer, ThreadingHTTPServer, BaseHTTPRequestHandler
from http.cookies import SimpleCookie
from urllib.parse import urlsplit, parse_qs, unquote
from pathlib import Path
from datetime import datetime, timezone, date, timedelta
from threading import Lock
from contextlib import contextmanager

ROOT=Path(__file__).resolve().parent

def load_env_file(path):
 try: lines=path.read_text(encoding='utf-8').splitlines()
 except OSError:return
 for line in lines:
  line=line.strip()
  if not line or line.startswith('#') or '=' not in line:continue
  key,value=line.split('=',1);key=key.strip();value=value.strip()
  if value[:1] in ('\"',"'") and value[-1:]==value[:1]:value=value[1:-1]
  if key and key not in os.environ:os.environ[key]=value

def env_path(key,default):
 value=Path(os.environ.get(key,str(default))).expanduser()
 return value if value.is_absolute() else (ROOT/value).resolve()

load_env_file(ROOT/'.env')
PUBLIC=ROOT/'public'
DB=env_path('ZILL_DB',ROOT/'zill.sqlite3')
PORT=int(os.environ.get('PORT','3000'))
HOST=os.environ.get('ZILL_HOST','127.0.0.1')
MODE=os.environ.get('ZILL_ENV','demo').lower()
DEMO_CREDENTIALS=os.environ.get('ZILL_DEMO_CREDENTIALS','local')
CROSS_SITE=os.environ.get('ZILL_COOKIE_CROSS_SITE','0')=='1'
SESSION_SECONDS=8*60*60
ROLES={'COMPANY_ADMINISTRATOR','SUPERVISOR','WORKER'}
LOGIN_USERS=[
 ('admin','مدير الشركة','COMPANY_ADMINISTRATOR','إدارة النطاق التنظيمي، المخزون والملخصات'),
 ('supervisor','مشرف الموقع','SUPERVISOR','فريق الموقع والتعيينات والتنبيهات'),
 ('wrk-001','عبدالرحمن العتيبي','WORKER','تعيين نشط · سترة ZT-DEMO-01'),
 ('wrk-002','نواف الحربي','WORKER','تعيين نشط · سترة ZT-DEMO-02'),
 ('wrk-003','سعود القحطاني','WORKER','تعيين نشط · سترة ZT-DEMO-03'),
 ('wrk-004','ماجد الغامدي','WORKER','تعيين منتهٍ · لا يوجد تعيين نشط'),
 ('wrk-005','فيصل الدوسري','WORKER','لا يوجد تعيين نشط'),
]
lock=Lock(); attempts={}

if MODE not in ('demo','development'):
 raise SystemExit('ZILL demonstration server refuses production mode.')
if DEMO_CREDENTIALS not in ('local','shared','off'):
 raise SystemExit('ZILL_DEMO_CREDENTIALS must be local, shared, or off')

def utcnow(): return datetime.now(timezone.utc)
def stamp(): return utcnow().isoformat(timespec='seconds')
@contextmanager
def db():
 c=sqlite3.connect(DB,timeout=12); c.row_factory=sqlite3.Row
 c.execute('PRAGMA foreign_keys=ON'); c.execute('PRAGMA busy_timeout=12000')
 try:
  with c: yield c
 finally:c.close()

def _pbkdf2(password,salt,rounds=150000):
 try:return hashlib.pbkdf2_hmac('sha256',password,salt,rounds,dklen=32)
 except (AttributeError,ValueError,RuntimeError):
  # Portable HMAC-SHA256 fallback for constrained WASM builds.
  u=hmac.new(password,salt+b'\x00\x00\x00\x01',hashlib.sha256).digest();out=bytearray(u)
  for _ in range(rounds-1):
   u=hmac.new(password,u,hashlib.sha256).digest()
   for i,b in enumerate(u):out[i]^=b
  return bytes(out)

def pw_hash(pw,salt=None):
 salt=salt or secrets.token_bytes(16);raw=pw.encode()
 try:return salt.hex()+':'+hashlib.scrypt(raw,salt=salt,n=16384,r=8,p=1,dklen=32).hex()
 except (AttributeError,ValueError,OSError,MemoryError):return 'pbkdf2$'+salt.hex()+'$'+_pbkdf2(raw,salt).hex()

def pw_valid(pw,encoded):
 try:
  if encoded.startswith('pbkdf2$'):
   _,salt,digest=encoded.split('$',2);salt=bytes.fromhex(salt)
   return hmac.compare_digest(_pbkdf2(pw.encode(),salt).hex(),digest)
  salt,_=encoded.split(':',1)
  return hmac.compare_digest(pw_hash(pw,bytes.fromhex(salt)),encoded)
 except (ValueError,TypeError,AttributeError):return False
def token_hash(s):return hashlib.sha256(s.encode()).hexdigest()
def audit(c,actor,action,entity,entity_id,detail=None):
 c.execute('INSERT INTO audit(actor_id,action,entity,entity_id,detail,created_at) VALUES(?,?,?,?,?,?)',(actor,action,entity,str(entity_id),json.dumps(detail or {},ensure_ascii=False),stamp()))
def credential_file():return env_path('ZILL_DEMO_CREDENTIAL_FILE',ROOT/'DEMO_ACCESS_LOCAL.txt')

def read_credentials():
 out={}
 try:
  for line in credential_file().read_text(encoding='utf-8').splitlines():
   try: row=json.loads(line)
   except Exception: continue
   if isinstance(row,dict) and row.get('username') and row.get('password') and row.get('role') in ROLES: out[row['username']]=row
 except OSError: pass
 return out

def init_db():
 DB.parent.mkdir(parents=True,exist_ok=True)
 with db() as c:
  c.executescript('''
  CREATE TABLE IF NOT EXISTS organization(id INTEGER PRIMARY KEY CHECK(id=1),name TEXT NOT NULL,created_at TEXT NOT NULL);
  CREATE TABLE IF NOT EXISTS sites(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL,code TEXT NOT NULL UNIQUE,region TEXT NOT NULL DEFAULT '',active INTEGER NOT NULL DEFAULT 1,created_at TEXT NOT NULL);
  CREATE TABLE IF NOT EXISTS teams(id INTEGER PRIMARY KEY AUTOINCREMENT,site_id INTEGER NOT NULL REFERENCES sites(id),name TEXT NOT NULL,code TEXT NOT NULL UNIQUE,active INTEGER NOT NULL DEFAULT 1,created_at TEXT NOT NULL,UNIQUE(site_id,name));
  CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY AUTOINCREMENT,username TEXT NOT NULL UNIQUE,employee_id TEXT NOT NULL UNIQUE,display_name TEXT,display_name_en TEXT,role TEXT NOT NULL CHECK(role IN ('WORKER','SUPERVISOR','COMPANY_ADMINISTRATOR')),password_hash TEXT NOT NULL,site_id INTEGER REFERENCES sites(id),team_id INTEGER REFERENCES teams(id),active INTEGER NOT NULL DEFAULT 1,created_at TEXT NOT NULL);
  CREATE TABLE IF NOT EXISTS vests(id INTEGER PRIMARY KEY AUTOINCREMENT,code TEXT NOT NULL UNIQUE,site_id INTEGER NOT NULL REFERENCES sites(id),status TEXT NOT NULL CHECK(status IN ('READY','MAINTENANCE','RETIRED')),created_at TEXT NOT NULL);
  CREATE TABLE IF NOT EXISTS assignments(id INTEGER PRIMARY KEY AUTOINCREMENT,worker_id INTEGER NOT NULL REFERENCES users(id),vest_id INTEGER NOT NULL REFERENCES vests(id),site_id INTEGER NOT NULL REFERENCES sites(id),team_id INTEGER NOT NULL REFERENCES teams(id),status TEXT NOT NULL CHECK(status IN ('ACTIVE','ENDED','EXPIRED')),start_date TEXT NOT NULL,end_date TEXT,created_by INTEGER REFERENCES users(id),created_at TEXT NOT NULL,ended_by INTEGER REFERENCES users(id));
  CREATE UNIQUE INDEX IF NOT EXISTS one_active_assignment_per_worker ON assignments(worker_id) WHERE status='ACTIVE';
  CREATE UNIQUE INDEX IF NOT EXISTS one_active_worker_per_vest ON assignments(vest_id) WHERE status='ACTIVE';
  CREATE TABLE IF NOT EXISTS alerts(id INTEGER PRIMARY KEY AUTOINCREMENT,site_id INTEGER NOT NULL REFERENCES sites(id),team_id INTEGER REFERENCES teams(id),title TEXT NOT NULL,description TEXT NOT NULL,severity TEXT NOT NULL CHECK(severity IN ('INFO','ATTENTION','URGENT')),source_class TEXT NOT NULL CHECK(source_class IN ('SIMULATED','USER_REPORTED')),status TEXT NOT NULL CHECK(status IN ('NEW','ACKNOWLEDGED','IN_PROGRESS','RESOLVED')),created_by INTEGER REFERENCES users(id),assigned_to INTEGER REFERENCES users(id),created_at TEXT NOT NULL,updated_at TEXT NOT NULL,resolved_at TEXT);
  CREATE TABLE IF NOT EXISTS alert_events(id INTEGER PRIMARY KEY AUTOINCREMENT,alert_id INTEGER NOT NULL REFERENCES alerts(id),actor_id INTEGER NOT NULL REFERENCES users(id),action TEXT NOT NULL,note TEXT NOT NULL DEFAULT '',created_at TEXT NOT NULL);
  CREATE TABLE IF NOT EXISTS worker_notifications(id INTEGER PRIMARY KEY AUTOINCREMENT,assignment_id INTEGER NOT NULL REFERENCES assignments(id),title TEXT NOT NULL,body TEXT NOT NULL,source_class TEXT NOT NULL CHECK(source_class IN ('SIMULATED','USER_REPORTED')),created_at TEXT NOT NULL);
  CREATE TABLE IF NOT EXISTS access_requests(id INTEGER PRIMARY KEY AUTOINCREMENT,worker_id INTEGER NOT NULL REFERENCES users(id),requested_by INTEGER NOT NULL REFERENCES users(id),reason TEXT NOT NULL,scope TEXT NOT NULL CHECK(scope IN ('PROFILE','ASSIGNMENT')),status TEXT NOT NULL CHECK(status IN ('PENDING','GRANTED','DENIED','REVOKED','EXPIRED')),requested_at TEXT NOT NULL,decided_at TEXT,expires_at TEXT);
  CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id),csrf TEXT NOT NULL,expires INTEGER NOT NULL,created_at TEXT NOT NULL);
  CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY AUTOINCREMENT,actor_id INTEGER REFERENCES users(id),action TEXT NOT NULL,entity TEXT NOT NULL,entity_id TEXT NOT NULL,detail TEXT NOT NULL,created_at TEXT NOT NULL);
  CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY,name TEXT NOT NULL,applied_at TEXT NOT NULL);
  ''')
  c.execute("INSERT OR IGNORE INTO schema_migrations(version,name,applied_at) VALUES(1,'baseline',?)",(stamp(),))
  cols={r['name'] for r in c.execute('PRAGMA table_info(users)')}
  if 'display_name_en' not in cols:c.execute('ALTER TABLE users ADD COLUMN display_name_en TEXT')
  c.execute("INSERT OR IGNORE INTO schema_migrations(version,name,applied_at) VALUES(2,'bilingual_user_names',?)",(stamp(),))
  access_cols={r['name'] for r in c.execute('PRAGMA table_info(access_requests)')}
  if 'scope' not in access_cols:c.execute("ALTER TABLE access_requests ADD COLUMN scope TEXT NOT NULL DEFAULT 'PROFILE'")
  if 'expires_at' not in access_cols:c.execute('ALTER TABLE access_requests ADD COLUMN expires_at TEXT')
  c.execute("INSERT OR IGNORE INTO schema_migrations(version,name,applied_at) VALUES(3,'scoped_worker_consents',?)",(stamp(),))
  if c.execute('SELECT 1 FROM organization WHERE id=1').fetchone() is None:
   c.execute('INSERT INTO organization VALUES(1,?,?)',('ظِل · منصة تجريبية','2026-11-18T00:00:00Z'))
  count=c.execute('SELECT count(*) n FROM users').fetchone()['n']
  if count==0:
   seed(c)
  else:
   # Migration-safe support for the demonstration notifications table after a partial restart.
   seed_notifications(c)

def seed(c):
 c.execute('INSERT INTO sites(name,code,region,active,created_at) VALUES(?,?,?,?,?)',('موقع الظل التجريبي','JED-01','جدة',1,stamp())); site=c.execute('SELECT last_insert_rowid()').fetchone()[0]
 c.execute('INSERT INTO teams(site_id,name,code,active,created_at) VALUES(?,?,?,?,?)',(site,'فريق العمليات الميدانية','OPS-01',1,stamp())); team=c.execute('SELECT last_insert_rowid()').fetchone()[0]
 users=[]; creds=[]
 for username,name,role,desc in LOGIN_USERS:
  employee=username.upper() if role=='WORKER' else username.upper()
  en_name={'wrk-001':'Abdulrahman Al-Otaibi','wrk-002':'Nawaf Al-Harbi','wrk-003':'Saud Al-Qahtani','wrk-004':'Majed Al-Ghamdi','wrk-005':'Faisal Al-Dosari'}.get(username,{'admin':'Company Administrator','supervisor':'Site Supervisor'}.get(username,name))
  password=secrets.token_urlsafe(15)
  cur=c.execute('INSERT INTO users(username,employee_id,display_name,display_name_en,role,password_hash,site_id,team_id,active,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)',(username,employee,name,en_name,role,pw_hash(password),site if role!='COMPANY_ADMINISTRATOR' else None,team if role in ('SUPERVISOR','WORKER') else None,1,stamp()))
  uid=cur.lastrowid; users.append((uid,username,role)); creds.append({'username':username,'password':password,'role':role,'name':name,'description':desc})
  audit(c,uid,'DEMO_SEED_ACCOUNT','USER',uid,{'role':role,'classification':'SIMULATED'})
 for i in range(1,6): c.execute('INSERT INTO vests(code,site_id,status,created_at) VALUES(?,?,?,?)',(f'ZT-DEMO-{i:02}',site,'READY',stamp()))
 ids={u:uid for uid,u,r in users}
 today=date.today()
 for i in range(1,4):
  vest=c.execute('SELECT id FROM vests WHERE code=?',(f'ZT-DEMO-{i:02}',)).fetchone()['id']
  cur=c.execute('INSERT INTO assignments(worker_id,vest_id,site_id,team_id,status,start_date,created_by,created_at) VALUES(?,?,?,?,?,?,?,?)',(ids[f'wrk-00{i}'],vest,site,team,'ACTIVE',(today-timedelta(days=7-i)).isoformat(),ids['supervisor'],stamp()))
  assignment=cur.lastrowid
  c.execute('INSERT INTO worker_notifications(assignment_id,title,body,source_class,created_at) VALUES(?,?,?,?,?)',(assignment,'إشعار تجريبي مرتبط بتعيين نشط','هذه رسالة توضيحية فقط. لا توجد أجهزة أو قياسات متصلة.','SIMULATED',stamp()))
 # A historical expired assignment is retained; this worker has no active assignment.
 vest4=c.execute('SELECT id FROM vests WHERE code=?',(f'ZT-DEMO-04',)).fetchone()['id']
 c.execute('INSERT INTO assignments(worker_id,vest_id,site_id,team_id,status,start_date,end_date,created_by,created_at,ended_by) VALUES(?,?,?,?,?,?,?,?,?,?)',(ids['wrk-004'],vest4,site,team,'EXPIRED',(today-timedelta(days=45)).isoformat(),(today-timedelta(days=30)).isoformat(),ids['supervisor'],stamp(),ids['supervisor']))
 for title,desc,severity,status in [
  ('مراجعة اتصال الموقع التجريبي','تنبيه توضيحي لتجربة سير العمل؛ لا يمثل قراءة جهاز.','ATTENTION','NEW'),
  ('تأكيد استلام متابعة الوردية','سجل تجريبي يوضح الفرق بين الإقرار والمعالجة.','INFO','ACKNOWLEDGED'),
  ('مراجعة بيانات تعيين منتهٍ','حالة تدريبية محفوظة في سجل الموقع.','INFO','RESOLVED')]:
  cur=c.execute('INSERT INTO alerts(site_id,team_id,title,description,severity,source_class,status,created_by,created_at,updated_at,resolved_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(site,team,title,desc,severity,'SIMULATED',status,ids['supervisor'],stamp(),stamp(),stamp() if status=='RESOLVED' else None))
  c.execute('INSERT INTO alert_events(alert_id,actor_id,action,note,created_at) VALUES(?,?,?,?,?)',(cur.lastrowid,ids['supervisor'],status,'سجل محاكاة لعرض سير العمل فقط.',stamp()))
  if status=='ACKNOWLEDGED': c.execute('UPDATE alerts SET assigned_to=? WHERE id=?',(ids['supervisor'],cur.lastrowid))
  audit(c,ids['supervisor'],'DEMO_ALERT_SEED','ALERT',cur.lastrowid,{'status':status,'classification':'SIMULATED'})
 c.commit()
 # Demo credentials are isolated; SQLite stores salted scrypt hashes with a portable PBKDF2 fallback.
 f=credential_file();f.parent.mkdir(parents=True,exist_ok=True);fd=os.open(f,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
 with os.fdopen(fd,'w',encoding='utf-8') as out:
  out.write('# DEMO ONLY — randomly generated. Do not use in production.\n')
  for row in creds: out.write(json.dumps(row,ensure_ascii=False)+'\n')

def seed_notifications(c):
 active=c.execute("SELECT a.id FROM assignments a WHERE a.status='ACTIVE' AND NOT EXISTS(SELECT 1 FROM worker_notifications n WHERE n.assignment_id=a.id)").fetchall()
 for row in active: c.execute('INSERT INTO worker_notifications(assignment_id,title,body,source_class,created_at) VALUES(?,?,?,?,?)',(row['id'],'إشعار تجريبي مرتبط بتعيين نشط','هذه رسالة توضيحية فقط؛ لا توجد قياسات متاحة.','SIMULATED',stamp()))

def allowed_demo(handler):
 if DEMO_CREDENTIALS=='off':return False
 if DEMO_CREDENTIALS=='shared':return True
 try:
  from ipaddress import ip_address
  return ip_address(handler.client_address[0]).is_loopback and handler.headers.get('Host','').split(':')[0] in ('localhost','127.0.0.1')
 except ValueError:return False

def active_consent(c,worker_id,scope='PROFILE'):
 return c.execute("SELECT 1 FROM access_requests WHERE worker_id=? AND scope=? AND status='GRANTED' AND expires_at>? ORDER BY id DESC LIMIT 1",(worker_id,scope,stamp())).fetchone() is not None

def rows(c,sql,args=()):return [dict(r) for r in c.execute(sql,args).fetchall()]
def new_password():return secrets.token_urlsafe(15)
def iso_date(s):
 try:return date.fromisoformat(s)
 except (ValueError,TypeError):return None

class Handler(BaseHTTPRequestHandler):
 server_version='ZILL'; sys_version=''
 def log_message(self,fmt,*args):pass
 def send(self,status,payload,ctype='application/json; charset=utf-8',extra=None):
  raw=json.dumps(payload,ensure_ascii=False,separators=(',',':')).encode() if ctype.startswith('application/json') else payload
  self.send_response(status); self.send_header('Content-Type',ctype); self.send_header('Content-Length',str(len(raw))); self.send_header('X-Content-Type-Options','nosniff'); self.send_header('Referrer-Policy','strict-origin-when-cross-origin'); self.send_header('Cache-Control','no-store'); self.send_header('Content-Security-Policy',"default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'self'"); self.send_header('Permissions-Policy','camera=(), microphone=(), geolocation=()')
  for key,value in (extra or {}).items():self.send_header(key,value)
  self.end_headers()
  try:self.wfile.write(raw)
  except (BrokenPipeError,ConnectionResetError):pass
 def error(self,status,message,code=None):return self.send(status,{'error':message,'code':code or f'HTTP_{status}'})
 def send_error(self,code,message=None,explain=None):
  if urlsplit(getattr(self,'path','')).path.startswith('/api'):return self.error(405 if code==501 else code,'طريقة الطلب غير مدعومة.','METHOD_NOT_ALLOWED')
  return super().send_error(code,message,explain)
 def body(self):
  try:
   n=int(self.headers.get('Content-Length','0'))
   if n>12000 or n<0 or 'application/json' not in self.headers.get('Content-Type',''):return None
   x=json.loads(self.rfile.read(n))
   return x if isinstance(x,dict) else None
  except (ValueError,json.JSONDecodeError):return None
 def origin_ok(self):
  origin=self.headers.get('Origin'); host=self.headers.get('Host','')
  if not origin:return False
  x=urlsplit(origin);return x.scheme in ('http','https') and x.netloc==host
 def current(self,c):
  try:
   jar=SimpleCookie();jar.load(self.headers.get('Cookie',''));token=jar['zill_session'].value
   return c.execute('SELECT u.*,s.csrf,s.expires session_expires FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires>? AND u.active=1',(token_hash(token),int(time.time()))).fetchone()
  except (KeyError,ValueError):return None
 def auth(self,c,roles=None,mutating=False):
  u=self.current(c)
  if not u:self.error(401,'انتهت الجلسة أو لم يتم تسجيل الدخول.','SESSION_REQUIRED');return None
  if roles and u['role'] not in roles:self.error(403,'هذه العملية غير متاحة لدور حسابك.','ROLE_FORBIDDEN');return None
  if mutating and (not self.origin_ok() or not hmac.compare_digest(self.headers.get('X-CSRF-Token',''),u['csrf'])):self.error(403,'تعذر التحقق من مصدر الطلب أو رمز الحماية.','CSRF_REJECTED');return None
  return u
 def do_GET(self):
  try:self.get_route()
  except (BrokenPipeError,ConnectionResetError):return
  except Exception as e:print('ZILL GET failure:',type(e).__name__,file=sys.stderr);self.error(500,'تعذر إتمام الطلب. حاول مجددًا.','SERVER_ERROR')
 def do_POST(self):
  try:self.write_route('POST')
  except (BrokenPipeError,ConnectionResetError):return
  except Exception as e:print('ZILL POST failure:',type(e).__name__,file=sys.stderr);self.error(500,'تعذر حفظ التغيير. لم تُعرض بيانات داخلية.','SERVER_ERROR')
 def do_PUT(self):
  try:self.write_route('PUT')
  except Exception as e:print('ZILL PUT failure:',type(e).__name__,file=sys.stderr);self.error(500,'تعذر حفظ التغيير.','SERVER_ERROR')
 def do_PATCH(self):
  try:self.write_route('PATCH')
  except Exception as e:print('ZILL PATCH failure:',type(e).__name__,file=sys.stderr);self.error(500,'تعذر حفظ التغيير.','SERVER_ERROR')
 def do_DELETE(self):
  try:self.write_route('DELETE')
  except Exception as e:print('ZILL DELETE failure:',type(e).__name__,file=sys.stderr);self.error(500,'تعذر حفظ التغيير.','SERVER_ERROR')
 def unsupported(self):return self.error(405,'طريقة الطلب غير مدعومة.','METHOD_NOT_ALLOWED')
 do_OPTIONS=unsupported
 def api_path(self):return urlsplit(self.path).path
 def get_route(self):
  path=self.api_path()
  if path.startswith('/api/'):
   if path=='/api/health':
    with db() as c:c.execute('SELECT 1')
    return self.send(200,{'status':'ok','mode':'DEMO','service':'zill-platform'})
   if path=='/api/demo/accounts':return self.demo_accounts()
   if path=='/api/session':
    with db() as c:
     u=self.current(c)
     return self.send(200,{'user':self.public_user(u),'csrf':u['csrf'] if u else None,'mode':'DEMO'})
   if path=='/api/dashboard':
    with db() as c:
     u=self.auth(c)
     if not u:return
     if u['role']=='COMPANY_ADMINISTRATOR':return self.company_data(c,u)
     if u['role']=='SUPERVISOR':return self.supervisor_data(c,u)
     return self.worker_data(c,u)
   if path=='/api/company/report.csv':
    with db() as c:
     u=self.auth(c,{'COMPANY_ADMINISTRATOR'})
     if not u:return
     return self.company_report(c)
   if path=='/api/audit':
    with db() as c:
     u=self.auth(c,{'COMPANY_ADMINISTRATOR'})
     if not u:return
     items=rows(c,'SELECT a.id,a.action,a.entity,a.entity_id,a.detail,a.created_at,u.employee_id actor_id FROM audit a LEFT JOIN users u ON u.id=a.actor_id ORDER BY a.id DESC LIMIT 200')
     return self.send(200,{'items':items})
   if path=='/api/sites' or path=='/api/teams':
    with db() as c:
     u=self.auth(c,{'COMPANY_ADMINISTRATOR'})
     if not u:return
     if path=='/api/sites':return self.send(200,{'items':rows(c,'SELECT * FROM sites ORDER BY active DESC,id')})
     return self.send(200,{'items':rows(c,'SELECT t.*,s.name site_name FROM teams t JOIN sites s ON s.id=t.site_id ORDER BY t.active DESC,t.id')})
   if path in ('/api/company/workers','/api/company/supervisors'):
    with db() as c:
     u=self.auth(c,{'COMPANY_ADMINISTRATOR'})
     if not u:return
     if path=='/api/company/workers':return self.send(200,{'items':self.company_workers(c)})
     sups=rows(c,"SELECT u.id,u.employee_id,u.username,u.display_name,u.role,u.active,u.site_id,u.team_id,s.name site_name,t.name team_name FROM users u LEFT JOIN sites s ON s.id=u.site_id LEFT JOIN teams t ON t.id=u.team_id WHERE u.role='SUPERVISOR' ORDER BY u.employee_id")
     return self.send(200,{'items':sups})
   if path=='/api/company/vests':
    with db() as c:
     u=self.auth(c,{'COMPANY_ADMINISTRATOR'})
     if not u:return
     return self.send(200,{'items':rows(c,"SELECT v.*,s.name site_name,CASE WHEN EXISTS(SELECT 1 FROM assignments a WHERE a.vest_id=v.id AND a.status='ACTIVE') THEN 'ASSIGNED' ELSE 'AVAILABLE' END availability FROM vests v JOIN sites s ON s.id=v.site_id ORDER BY v.id")})
   if path=='/api/company/access-requests':
    with db() as c:
     u=self.auth(c,{'COMPANY_ADMINISTRATOR'})
     if not u:return
     return self.send(200,{'items':rows(c,'SELECT ar.*,w.employee_id FROM access_requests ar JOIN users w ON w.id=ar.worker_id ORDER BY ar.id DESC')})
   if path=='/api/supervisor/data':
    with db() as c:
     u=self.auth(c,{'SUPERVISOR'})
     if not u:return
     return self.send(200,self.supervisor_data_obj(c,u))
   if path=='/api/worker/data':
    with db() as c:
     u=self.auth(c,{'WORKER'})
     if not u:return
     return self.send(200,self.worker_data_obj(c,u))
   if path=='/api/worker/consents':
    with db() as c:
     u=self.auth(c,{'WORKER'})
     if not u:return
     return self.send(200,{'items':rows(c,'SELECT ar.id,ar.reason,ar.scope,ar.status,ar.requested_at,ar.expires_at,admin.employee_id requested_by FROM access_requests ar JOIN users admin ON admin.id=ar.requested_by WHERE ar.worker_id=? ORDER BY ar.id DESC',(u['id'],))})
   if path=='/api/company/overview':
    with db() as c:
     u=self.auth(c,{'COMPANY_ADMINISTRATOR'})
     if not u:return
     return self.send(200,self.company_data_obj(c,u))
   if path.startswith('/api/'):return self.error(404,'مسار API غير موجود.','API_NOT_FOUND')
  filemap={'/':'index.html','/index.html':'index.html','/app.js':'app.js','/style.css':'style.css','/favicon.svg':'favicon.svg'}
  rel=filemap.get(path)
  if path.startswith('/images/'):
   cand=(PUBLIC/unquote(path.lstrip('/'))).resolve()
   try:cand.relative_to(PUBLIC.resolve())
   except ValueError:return self.error(404,'الملف غير موجود.','NOT_FOUND')
   if cand.is_file():
    ext=cand.suffix.lower();ct={'.png':'image/png','.jpg':'image/jpeg','.jpeg':'image/jpeg','.svg':'image/svg+xml','.webp':'image/webp'}.get(ext,'application/octet-stream')
    return self.send(200,cand.read_bytes(),ct)
  if rel:
   f=PUBLIC/rel
   if f.is_file():
    ct={'html':'text/html; charset=utf-8','js':'text/javascript; charset=utf-8','css':'text/css; charset=utf-8','svg':'image/svg+xml'}[f.suffix.lower().lstrip('.')]
    return self.send(200,f.read_bytes(),ct)
  return self.error(404,'الصفحة غير موجودة.','NOT_FOUND')
 def demo_accounts(self):
  role=parse_qs(urlsplit(self.path).query).get('role',[''])[0]
  if not allowed_demo(self):return self.error(404,'حسابات العرض غير متاحة في هذه البيئة.','DEMO_DISABLED')
  credential_map=read_credentials()
  if not role: return self.error(400,'حدد البوابة لعرض حساباتها.','ROLE_REQUIRED')
  if role not in ROLES:return self.error(400,'نوع البوابة غير صحيح.','INVALID_ROLE')
  with db() as c:
   out=[]
   for row in c.execute('SELECT id,username,employee_id,display_name,role,site_id,team_id,active FROM users WHERE role=? AND active=1 ORDER BY employee_id',(role,)):
    cred=credential_map.get(row['username'])
    if not cred or cred['role']!=role or not pw_valid(cred['password'],c.execute('SELECT password_hash FROM users WHERE id=?',(row['id'],)).fetchone()['password_hash']):continue
    scenario={'wrk-001':'تعيين نشط','wrk-002':'تعيين نشط','wrk-003':'تعيين نشط','wrk-004':'تعيين منتهٍ؛ لا يوجد نشط','wrk-005':'لا يوجد تعيين سابق'} .get(row['username'],'حساب تجريبي')
    out.append({'username':row['username'],'password':cred['password'],'role':role,'name':row['display_name'] or 'حساب جديد','employee_id':row['employee_id'],'scenario':scenario})
   if not out:return self.error(404,'لا توجد حسابات عرض صالحة لهذه البوابة.','DEMO_ACCOUNTS_MISSING')
   return self.send(200,{'accounts':out,'mode':'DEMO'})
 def public_user(self,u):
  if not u:return None
  return {'id':u['id'],'username':u['username'],'employee_id':u['employee_id'],'name':u['display_name'] or 'العامل','name_en':u['display_name_en'] or 'Worker','role':u['role'],'site_id':u['site_id'],'team_id':u['team_id'],'mode':'DEMO'}
 def company_workers(self,c):
  arr=rows(c,"""SELECT u.id,u.employee_id,u.username,u.role,u.active,u.site_id,u.team_id,s.name site_name,t.name team_name,
   (SELECT a.status FROM assignments a WHERE a.worker_id=u.id ORDER BY CASE a.status WHEN 'ACTIVE' THEN 0 WHEN 'EXPIRED' THEN 1 ELSE 2 END,a.id DESC LIMIT 1) assignment_status,
   (SELECT v.code FROM assignments a JOIN vests v ON v.id=a.vest_id WHERE a.worker_id=u.id AND a.status='ACTIVE' LIMIT 1) vest_code
   FROM users u LEFT JOIN sites s ON s.id=u.site_id LEFT JOIN teams t ON t.id=u.team_id WHERE u.role='WORKER' ORDER BY u.employee_id""")
  for w in arr:
   w['consent_active']=active_consent(c,w['id'],'PROFILE')
   w['assignment_consent_active']=active_consent(c,w['id'],'ASSIGNMENT')
   if w['consent_active']:
    person=c.execute('SELECT display_name,display_name_en FROM users WHERE id=?',(w['id'],)).fetchone();w['name']=person['display_name'];w['name_en']=person['display_name_en']
   else:w['name']=None;w['name_en']=None
   if not active_consent(c,w['id'],'ASSIGNMENT'):w['assignment_status']=None;w['vest_code']=None
  return arr
 def company_data_obj(self,c,u):
  site_items=rows(c,"""SELECT s.id,s.code,s.name,s.region,s.active,COUNT(DISTINCT t.id) teams,COUNT(DISTINCT CASE WHEN w.role='WORKER' THEN w.id END) workers,
   COUNT(DISTINCT CASE WHEN a.status='ACTIVE' THEN a.id END) active_assignments,
   COUNT(DISTINCT CASE WHEN al.status!='RESOLVED' THEN al.id END) open_alerts
   FROM sites s LEFT JOIN teams t ON t.site_id=s.id LEFT JOIN users w ON w.site_id=s.id LEFT JOIN assignments a ON a.site_id=s.id LEFT JOIN alerts al ON al.site_id=s.id GROUP BY s.id ORDER BY s.id""")
  metrics={
   'workers':c.execute("SELECT COUNT(*) FROM users WHERE role='WORKER' AND active=1").fetchone()[0],
   'active_assignments':c.execute("SELECT COUNT(*) FROM assignments WHERE status='ACTIVE'").fetchone()[0],
   'without_active':c.execute("SELECT COUNT(*) FROM users u WHERE u.role='WORKER' AND u.active=1 AND NOT EXISTS(SELECT 1 FROM assignments a WHERE a.worker_id=u.id AND a.status='ACTIVE')").fetchone()[0],
   'vests_ready':c.execute("SELECT COUNT(*) FROM vests WHERE status='READY'").fetchone()[0],
   'vests_available':c.execute("SELECT COUNT(*) FROM vests v WHERE v.status='READY' AND NOT EXISTS(SELECT 1 FROM assignments a WHERE a.vest_id=v.id AND a.status='ACTIVE')").fetchone()[0],
   'open_alerts':c.execute("SELECT COUNT(*) FROM alerts WHERE status IN ('NEW','ACKNOWLEDGED','IN_PROGRESS')").fetchone()[0],
   'sites':c.execute('SELECT COUNT(*) FROM sites WHERE active=1').fetchone()[0],
   'teams':c.execute('SELECT COUNT(*) FROM teams WHERE active=1').fetchone()[0]
  }
  activity=rows(c,'SELECT a.id,a.action,a.entity,a.entity_id,a.detail,a.created_at,u.employee_id actor FROM audit a LEFT JOIN users u ON u.id=a.actor_id ORDER BY a.id DESC LIMIT 10')
  return {'role':u['role'],'organization':dict(c.execute('SELECT * FROM organization WHERE id=1').fetchone()),'metrics':metrics,'sites':site_items,'activity':activity,'classification':'SIMULATED'}
 def company_data(self,c,u):return self.send(200,self.company_data_obj(c,u))
 def supervisor_data_obj(self,c,u):
  if not u['site_id'] or not u['team_id']:return {'role':u['role'],'site':None,'team':None,'workers':[],'vests':[],'alerts':[],'activities':[]}
  site=c.execute('SELECT * FROM sites WHERE id=? AND active=1',(u['site_id'],)).fetchone();team=c.execute('SELECT * FROM teams WHERE id=? AND active=1 AND site_id=?',(u['team_id'],u['site_id'])).fetchone()
  if not site or not team:return {'role':u['role'],'site':None,'team':None,'workers':[],'vests':[],'alerts':[],'activities':[]}
  workers=rows(c,"""SELECT u.id,u.employee_id,u.username,u.display_name name,u.display_name_en name_en,u.active,u.site_id,u.team_id,
    (SELECT a.id FROM assignments a WHERE a.worker_id=u.id AND a.status='ACTIVE' LIMIT 1) active_assignment_id,
    (SELECT v.code FROM assignments a JOIN vests v ON v.id=a.vest_id WHERE a.worker_id=u.id AND a.status='ACTIVE' LIMIT 1) vest_code,
    (SELECT a.status FROM assignments a WHERE a.worker_id=u.id ORDER BY CASE a.status WHEN 'ACTIVE' THEN 0 WHEN 'EXPIRED' THEN 1 ELSE 2 END,a.id DESC LIMIT 1) assignment_status
    FROM users u WHERE u.role='WORKER' AND u.site_id=? AND u.team_id=? ORDER BY u.employee_id""",(u['site_id'],u['team_id']))
  vests=rows(c,"""SELECT v.id,v.code,v.status,CASE WHEN a.id IS NULL THEN 'AVAILABLE' ELSE 'ASSIGNED' END availability
   FROM vests v LEFT JOIN assignments a ON a.vest_id=v.id AND a.status='ACTIVE' WHERE v.site_id=? ORDER BY v.code""",(u['site_id'],))
  alerts=rows(c,'SELECT id,title,description,severity,source_class,status,created_at,updated_at FROM alerts WHERE site_id=? AND (team_id=? OR team_id IS NULL) ORDER BY CASE status WHEN \'NEW\' THEN 0 WHEN \'ACKNOWLEDGED\' THEN 1 WHEN \'IN_PROGRESS\' THEN 2 ELSE 3 END,id DESC',(u['site_id'],u['team_id']))
  events=rows(c,'SELECT e.id,e.action,e.note,e.created_at,a.title alert_title,u.employee_id actor FROM alert_events e JOIN alerts a ON a.id=e.alert_id JOIN users u ON u.id=e.actor_id WHERE a.site_id=? AND a.team_id=? ORDER BY e.id DESC LIMIT 10',(u['site_id'],u['team_id']))
  histories=rows(c,"""SELECT a.id,a.status,a.start_date,a.end_date,w.employee_id,w.display_name worker_name,v.code vest_code FROM assignments a JOIN users w ON w.id=a.worker_id JOIN vests v ON v.id=a.vest_id WHERE a.site_id=? AND a.team_id=? ORDER BY a.id DESC""",(u['site_id'],u['team_id']))
  return {'role':u['role'],'site':dict(site),'team':dict(team),'workers':workers,'vests':vests,'assignments':histories,'alerts':alerts,'activities':events,'classification':'SIMULATED'}
 def supervisor_data(self,c,u):return self.send(200,self.supervisor_data_obj(c,u))
 def worker_data_obj(self,c,u):
  assignment=c.execute("""SELECT a.id assignment_id,a.start_date,a.end_date,a.status assignment_status,v.code vest_code,s.name site_name,t.name team_name
   FROM assignments a JOIN vests v ON v.id=a.vest_id JOIN sites s ON s.id=a.site_id JOIN teams t ON t.id=a.team_id
   WHERE a.worker_id=? AND a.status='ACTIVE' ORDER BY a.id DESC LIMIT 1""",(u['id'],)).fetchone()
  if assignment:
   notices=rows(c,'SELECT id,title,body,source_class,created_at FROM worker_notifications WHERE assignment_id=? ORDER BY id DESC',(assignment['assignment_id'],))
  else:notices=[]
  past=rows(c,"""SELECT a.id,a.start_date,a.end_date,a.status,v.code vest_code FROM assignments a JOIN vests v ON v.id=a.vest_id WHERE a.worker_id=? AND a.status!='ACTIVE' ORDER BY a.id DESC""",(u['id'],))
  return {'role':'WORKER','user':self.public_user(u),'assignment':dict(assignment) if assignment else None,'past_assignments':past,'notifications':notices,'telemetry':None,'telemetry_classification':'UNKNOWN','consents':rows(c,'SELECT id,reason,scope,status,requested_at,expires_at FROM access_requests WHERE worker_id=? ORDER BY id DESC',(u['id'],)),'classification':'SIMULATED'}
 def worker_data(self,c,u):return self.send(200,self.worker_data_obj(c,u))
 def company_report(self,c):
  d=self.company_data_obj(c,self.current(c)); m=d['metrics']
  buf=io.StringIO(newline='');w=csv.writer(buf);w.writerow(['metric','value','classification']);
  for k,v in m.items():w.writerow([k,v,'CALCULATED_FROM_DEMO_DATABASE'])
  w.writerow(['note','No live telemetry is connected','UNKNOWN']);raw=buf.getvalue().encode('utf-8-sig')
  return self.send(200,{'filename':'zill-aggregate-demo-report.csv','csv':raw.decode('utf-8-sig'),'classification':'CALCULATED_FROM_DEMO_DATABASE'})
 def write_route(self,method):
  path=self.api_path()
  if not path.startswith('/api/'):return self.error(404,'المسار غير موجود.','NOT_FOUND')
  if path in ('/api/login','/api/logout') and method!='POST':return self.error(405,'هذه الواجهة تقبل POST فقط.','METHOD_NOT_ALLOWED')
  if path=='/api/login' and method=='POST':return self.login()
  if path=='/api/logout' and method=='POST':return self.logout()
  if not re.fullmatch(r'/api/(company|supervisor|worker)/.*|/api/(sites|teams)',path):return self.error(404,'مسار API غير موجود.','API_NOT_FOUND')
  data=self.body()
  if data is None:return self.error(400,'جسم الطلب غير صالح؛ استخدم JSON صحيحًا.','INVALID_JSON')
  if not self.origin_ok():return self.error(403,'مصدر الطلب غير مصرح.','ORIGIN_REJECTED')
  with db() as c:
   u=self.auth(c,mutating=True)
   if not u:return
   if path.startswith('/api/company/'):
    if u['role']!='COMPANY_ADMINISTRATOR':return self.error(403,'تتطلب العملية صلاحية إدارة الشركة.','ROLE_FORBIDDEN')
    return self.company_write(c,u,method,path,data)
   if path.startswith('/api/supervisor/'):
    if u['role']!='SUPERVISOR':return self.error(403,'تتطلب العملية صلاحية المشرف.','ROLE_FORBIDDEN')
    return self.supervisor_write(c,u,method,path,data)
   if path.startswith('/api/worker/'):
    if u['role']!='WORKER':return self.error(403,'تتطلب العملية صلاحية العامل.','ROLE_FORBIDDEN')
    return self.worker_write(c,u,method,path,data)
   if path in ('/api/sites','/api/teams'):return self.error(403,'تعديل النطاق التنظيمي مقتصر على إدارة الشركة.','ROLE_FORBIDDEN')
   return self.error(404,'مسار API غير موجود.','API_NOT_FOUND')
 def login(self):
  data=self.body()
  if data is None:return self.error(400,'طلب تسجيل الدخول غير صالح.','INVALID_JSON')
  if not self.origin_ok():return self.error(403,'مصدر الطلب غير مصرح.','ORIGIN_REJECTED')
  username=data.get('username');password=data.get('password');role=data.get('role')
  if not isinstance(username,str) or not isinstance(password,str) or role not in ROLES or len(username)>80 or len(password)>200:return self.error(400,'تحقق من بيانات الدخول والدور.','INVALID_CREDENTIALS_FORMAT')
  now=time.time();key=(self.client_address[0],username.lower().strip())
  with lock:
   attempts[key]=[t for t in attempts.get(key,[]) if now-t<300]
   if len(attempts)>3000:attempts.clear()
   if len(attempts[key])>=8:return self.error(429,'محاولات كثيرة؛ حاول لاحقًا.','RATE_LIMITED')
   attempts[key].append(now)
  with db() as c:
   u=c.execute('SELECT * FROM users WHERE username=?',(username.lower().strip(),)).fetchone()
   dummy='00'*16+':'+('00'*32);ok=pw_valid(password,u['password_hash'] if u else dummy)
   if not u or not ok or not u['active'] or u['role']!=role:
    audit(c,u['id'] if u else None,'LOGIN_FAILED','USER',username[:80]);c.commit();return self.error(401,'بيانات الدخول أو بوابة الدور غير صحيحة.','LOGIN_FAILED')
   token=secrets.token_urlsafe(32);csrf=secrets.token_urlsafe(24);expires=int(now)+SESSION_SECONDS
   c.execute('DELETE FROM sessions WHERE expires<?',(int(now),));c.execute('INSERT INTO sessions VALUES(?,?,?,?,?)',(token_hash(token),u['id'],csrf,expires,stamp()));audit(c,u['id'],'LOGIN','SESSION',u['id']);c.commit()
  is_https=self.headers.get('X-Forwarded-Proto','')=='https'
  secure='; Secure' if is_https else ''
  same='None' if CROSS_SITE and is_https else 'Lax'
  return self.send(200,{'ok':True,'role':role},extra={'Set-Cookie':f'zill_session={token}; Path=/; HttpOnly; SameSite={same}; Max-Age={SESSION_SECONDS}{secure}'})
 def logout(self):
  data=self.body()
  if data is None:return self.error(400,'طلب غير صالح.','INVALID_JSON')
  if not self.origin_ok():return self.error(403,'مصدر الطلب غير مصرح.','ORIGIN_REJECTED')
  with db() as c:
   u=self.auth(c,mutating=True)
   if not u:return
   jar=SimpleCookie();jar.load(self.headers.get('Cookie',''));token=jar['zill_session'].value
   c.execute('DELETE FROM sessions WHERE token_hash=?',(token_hash(token),));audit(c,u['id'],'LOGOUT','SESSION',u['id']);c.commit()
  return self.send(200,{'ok':True},extra={'Set-Cookie':'zill_session=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0'})
 def company_write(self,c,u,method,path,d):
  # Organization-scoped operations: company owns sites/teams, worker org placement, accounts and vest stock.
  if path=='/api/company/sites' and method=='POST':
   name=str(d.get('name','')).strip();code=str(d.get('code','')).strip().upper();region=str(d.get('region','')).strip()
   if not name or not re.fullmatch(r'[A-Z0-9-]{2,16}',code):return self.error(400,'أدخل اسم الموقع ورمزًا صحيحًا.','VALIDATION_ERROR')
   try:
    cur=c.execute('INSERT INTO sites(name,code,region,active,created_at) VALUES(?,?,?,?,?)',(name,code,region,1,stamp()));audit(c,u['id'],'CREATE','SITE',cur.lastrowid,{'code':code});c.commit();return self.send(201,{'id':cur.lastrowid})
   except sqlite3.IntegrityError:return self.error(409,'رمز الموقع مستخدم بالفعل.','CONFLICT')
  m=re.fullmatch(r'/api/company/sites/(\d+)',path)
  if m:
   sid=int(m.group(1));site=c.execute('SELECT * FROM sites WHERE id=?',(sid,)).fetchone()
   if not site:return self.error(404,'الموقع غير موجود.','NOT_FOUND')
   if method in ('PUT','PATCH'):
    name=str(d.get('name',site['name'])).strip();region=str(d.get('region',site['region'])).strip();code=str(d.get('code',site['code'])).strip().upper();active=1 if d.get('active',bool(site['active'])) else 0
    if not name or not re.fullmatch(r'[A-Z0-9-]{2,16}',code):return self.error(400,'اسم الموقع أو رمزه غير صالح.','VALIDATION_ERROR')
    try:c.execute('UPDATE sites SET name=?,code=?,region=?,active=? WHERE id=?',(name,code,region,active,sid))
    except sqlite3.IntegrityError:return self.error(409,'رمز الموقع مستخدم مسبقًا.','CONFLICT')
    audit(c,u['id'],'UPDATE','SITE',sid,{'active':active});c.commit();return self.send(200,{'ok':True})
   if method=='DELETE':
    if c.execute("SELECT 1 FROM users WHERE site_id=? AND active=1 LIMIT 1",(sid,)).fetchone() or c.execute("SELECT 1 FROM assignments WHERE site_id=? AND status='ACTIVE' LIMIT 1",(sid,)).fetchone():return self.error(409,'انقل الحسابات أو أنه التعيينات قبل أرشفة الموقع.','SITE_IN_USE')
    c.execute('UPDATE sites SET active=0 WHERE id=?',(sid,));c.execute('UPDATE teams SET active=0 WHERE site_id=?',(sid,));audit(c,u['id'],'ARCHIVE','SITE',sid);c.commit();return self.send(200,{'ok':True})
  if path=='/api/company/teams' and method=='POST':
   try:
    site_id=int(d.get('site_id'));name=str(d.get('name','')).strip();code=str(d.get('code','')).strip().upper()
   except (TypeError,ValueError):return self.error(400,'حدد الموقع والفريق.','VALIDATION_ERROR')
   if not name or not re.fullmatch(r'[A-Z0-9-]{2,16}',code) or not c.execute('SELECT 1 FROM sites WHERE id=? AND active=1',(site_id,)).fetchone():return self.error(400,'بيانات الموقع أو الفريق غير صالحة.','VALIDATION_ERROR')
   try:
    cur=c.execute('INSERT INTO teams(site_id,name,code,active,created_at) VALUES(?,?,?,?,?)',(site_id,name,code,1,stamp()));audit(c,u['id'],'CREATE','TEAM',cur.lastrowid,{'site_id':site_id});c.commit();return self.send(201,{'id':cur.lastrowid})
   except sqlite3.IntegrityError:return self.error(409,'رمز الفريق مستخدم أو الفريق موجود.','CONFLICT')
  m=re.fullmatch(r'/api/company/teams/(\d+)',path)
  if m:
   tid=int(m.group(1));team=c.execute('SELECT * FROM teams WHERE id=?',(tid,)).fetchone()
   if not team:return self.error(404,'الفريق غير موجود.','NOT_FOUND')
   if method in ('PUT','PATCH'):
    name=str(d.get('name',team['name'])).strip();active=1 if d.get('active',bool(team['active'])) else 0
    try:c.execute('UPDATE teams SET name=?,active=? WHERE id=?',(name,active,tid))
    except sqlite3.IntegrityError:return self.error(409,'اسم الفريق موجود في هذا الموقع.','CONFLICT')
    audit(c,u['id'],'UPDATE','TEAM',tid,{'active':active});c.commit();return self.send(200,{'ok':True})
   if method=='DELETE':
    if c.execute('SELECT 1 FROM users WHERE team_id=? AND active=1 LIMIT 1',(tid,)).fetchone():return self.error(409,'لا يمكن أرشفة فريق عليه عمال نشطون؛ انقلهم تنظيميًا أولًا.','TEAM_IN_USE')
    c.execute('UPDATE teams SET active=0 WHERE id=?',(tid,));audit(c,u['id'],'ARCHIVE','TEAM',tid);c.commit();return self.send(200,{'ok':True})
  if path=='/api/company/vests' and method=='POST':
   code=str(d.get('code','')).strip().upper()
   try:site_id=int(d.get('site_id'))
   except (TypeError,ValueError):return self.error(400,'حدد موقع السترة.','VALIDATION_ERROR')
   if not re.fullmatch(r'ZT-[A-Z0-9-]{3,24}',code) or not c.execute('SELECT 1 FROM sites WHERE id=? AND active=1',(site_id,)).fetchone():return self.error(400,'رمز السترة أو الموقع غير صالح.','VALIDATION_ERROR')
   try:
    cur=c.execute('INSERT INTO vests(code,site_id,status,created_at) VALUES(?,?,?,?)',(code,site_id,'READY',stamp()));audit(c,u['id'],'CREATE','VEST',cur.lastrowid,{'code':code});c.commit();return self.send(201,{'id':cur.lastrowid})
   except sqlite3.IntegrityError:return self.error(409,'رمز السترة مسجل مسبقًا.','CONFLICT')
  m=re.fullmatch(r'/api/company/vests/(\d+)',path)
  if m:
   vid=int(m.group(1));vest=c.execute('SELECT * FROM vests WHERE id=?',(vid,)).fetchone()
   if not vest:return self.error(404,'السترة غير موجودة.','NOT_FOUND')
   if method in ('PUT','PATCH'):
    status=d.get('status',vest['status']);site_id=int(d.get('site_id',vest['site_id']))
    if status not in ('READY','MAINTENANCE','RETIRED'):return self.error(400,'حالة المخزون غير صالحة.','VALIDATION_ERROR')
    if c.execute("SELECT 1 FROM assignments WHERE vest_id=? AND status='ACTIVE'",(vid,)).fetchone() and (status!='READY' or site_id!=vest['site_id']):return self.error(409,'أنه التعيين النشط قبل تغيير حالة أو موقع السترة.','VEST_ASSIGNED')
    c.execute('UPDATE vests SET status=?,site_id=? WHERE id=?',(status,site_id,vid));audit(c,u['id'],'UPDATE','VEST',vid,{'status':status,'site_id':site_id});c.commit();return self.send(200,{'ok':True})
  if path=='/api/company/workers' and method=='POST':
   username=str(d.get('username','')).strip().lower();employee=str(d.get('employee_id',username)).strip().upper()
   try:site_id=int(d.get('site_id'));team_id=int(d.get('team_id'))
   except (TypeError,ValueError):return self.error(400,'حدد الموقع والفريق للعامل.','VALIDATION_ERROR')
   if not re.fullmatch(r'[a-z0-9-]{3,32}',username) or not c.execute('SELECT 1 FROM teams WHERE id=? AND site_id=? AND active=1',(team_id,site_id)).fetchone():return self.error(400,'معرّف العامل أو نطاق الفريق غير صالح.','VALIDATION_ERROR')
   password=new_password()
   try:
    cur=c.execute('INSERT INTO users(username,employee_id,display_name,display_name_en,role,password_hash,site_id,team_id,active,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)',(username,employee,None,None,'WORKER',pw_hash(password),site_id,team_id,1,stamp()));audit(c,u['id'],'CREATE','WORKER',cur.lastrowid,{'employee_id':employee,'site_id':site_id,'team_id':team_id});c.commit();return self.send(201,{'id':cur.lastrowid,'username':username,'temporary_password':password,'note':'تظهر كلمة المرور مرة واحدة؛ سلّمها للعامل عبر قناة آمنة.'})
   except sqlite3.IntegrityError:return self.error(409,'اسم المستخدم أو معرّف العامل مستخدم.','CONFLICT')
  m=re.fullmatch(r'/api/company/workers/(\d+)/(organization|status)',path)
  if m:
   wid=int(m.group(1));worker=c.execute("SELECT * FROM users WHERE id=? AND role='WORKER'",(wid,)).fetchone()
   if not worker:return self.error(404,'العامل غير موجود.','NOT_FOUND')
   if m.group(2)=='organization':
    try:site_id=int(d.get('site_id'));team_id=int(d.get('team_id'))
    except (TypeError,ValueError):return self.error(400,'حدد الموقع والفريق.','VALIDATION_ERROR')
    if not c.execute('SELECT 1 FROM teams WHERE id=? AND site_id=? AND active=1',(team_id,site_id)).fetchone():return self.error(400,'الفريق لا يتبع الموقع المحدد.','SITE_TEAM_MISMATCH')
    if c.execute("SELECT 1 FROM assignments WHERE worker_id=? AND status='ACTIVE'",(wid,)).fetchone():return self.error(409,'أنه التعيين النشط من المشرف قبل تغيير الموقع أو الفريق.','ACTIVE_ASSIGNMENT')
    c.execute('UPDATE users SET site_id=?,team_id=? WHERE id=?',(site_id,team_id,wid));audit(c,u['id'],'CHANGE_ORGANIZATION','WORKER',wid,{'site_id':site_id,'team_id':team_id});c.commit();return self.send(200,{'ok':True})
   active=1 if d.get('active') else 0
   if not active and c.execute("SELECT 1 FROM assignments WHERE worker_id=? AND status='ACTIVE'",(wid,)).fetchone():return self.error(409,'أنه التعيين النشط قبل إيقاف حساب العامل.','ACTIVE_ASSIGNMENT')
   c.execute('UPDATE users SET active=? WHERE id=?',(active,wid));audit(c,u['id'],'SET_ACCOUNT_STATUS','WORKER',wid,{'active':active});c.commit();return self.send(200,{'ok':True})
  if path=='/api/company/supervisors' and method=='POST':
   username=str(d.get('username','')).strip().lower();employee=str(d.get('employee_id',username)).strip().upper();display=str(d.get('display_name','')).strip()
   try:site_id=int(d.get('site_id'));team_id=int(d.get('team_id'))
   except (TypeError,ValueError):return self.error(400,'حدد الموقع والفريق.','VALIDATION_ERROR')
   if not display or not re.fullmatch(r'[a-z0-9-]{3,32}',username) or not c.execute('SELECT 1 FROM teams WHERE id=? AND site_id=? AND active=1',(team_id,site_id)).fetchone():return self.error(400,'بيانات المشرف غير صالحة.','VALIDATION_ERROR')
   password=new_password()
   try:
    cur=c.execute('INSERT INTO users(username,employee_id,display_name,display_name_en,role,password_hash,site_id,team_id,active,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)',(username,employee,display,display,'SUPERVISOR',pw_hash(password),site_id,team_id,1,stamp()));audit(c,u['id'],'CREATE','SUPERVISOR',cur.lastrowid,{'site_id':site_id,'team_id':team_id});c.commit();return self.send(201,{'id':cur.lastrowid,'username':username,'temporary_password':password})
   except sqlite3.IntegrityError:return self.error(409,'الحساب أو المعرّف مستخدم مسبقًا.','CONFLICT')
  m=re.fullmatch(r'/api/company/supervisors/(\d+)/(organization|status)',path)
  if m:
   sid=int(m.group(1));sup=c.execute("SELECT * FROM users WHERE id=? AND role='SUPERVISOR'",(sid,)).fetchone()
   if not sup:return self.error(404,'حساب المشرف غير موجود.','NOT_FOUND')
   if m.group(2)=='organization':
    try:site_id=int(d.get('site_id'));team_id=int(d.get('team_id'))
    except (TypeError,ValueError):return self.error(400,'حدد الموقع والفريق.','VALIDATION_ERROR')
    if not c.execute('SELECT 1 FROM teams WHERE id=? AND site_id=? AND active=1',(team_id,site_id)).fetchone():return self.error(400,'الفريق لا يتبع الموقع المحدد.','SITE_TEAM_MISMATCH')
    c.execute('UPDATE users SET site_id=?,team_id=? WHERE id=?',(site_id,team_id,sid));audit(c,u['id'],'CHANGE_SUPERVISOR_SCOPE','SUPERVISOR',sid,{'site_id':site_id,'team_id':team_id});c.commit();return self.send(200,{'ok':True})
   active=1 if d.get('active') else 0;c.execute('UPDATE users SET active=? WHERE id=?',(active,sid));audit(c,u['id'],'SET_ACCOUNT_STATUS','SUPERVISOR',sid,{'active':active});c.commit();return self.send(200,{'ok':True})
  if path=='/api/company/access-requests' and method=='POST':
   try:wid=int(d.get('worker_id'));scope=d.get('scope','PROFILE')
   except (TypeError,ValueError):return self.error(400,'اختر العامل ونطاق الطلب.','VALIDATION_ERROR')
   reason=str(d.get('reason','')).strip()
   if scope not in ('PROFILE','ASSIGNMENT') or len(reason)<8:return self.error(400,'اكتب سببًا واضحًا واختر نطاقًا صحيحًا.','VALIDATION_ERROR')
   if not c.execute("SELECT 1 FROM users WHERE id=? AND role='WORKER' AND active=1",(wid,)).fetchone():return self.error(404,'العامل غير متاح.','NOT_FOUND')
   cur=c.execute("INSERT INTO access_requests(worker_id,requested_by,reason,scope,status,requested_at) VALUES(?,?,?,?,?,?)",(wid,u['id'],reason,scope,'PENDING',stamp()));audit(c,u['id'],'REQUEST_CONSENT','ACCESS_REQUEST',cur.lastrowid,{'worker_id':wid,'scope':scope});c.commit();return self.send(201,{'id':cur.lastrowid})
  if path.startswith('/api/company/'):return self.error(404,'مسار إدارة الشركة غير موجود.','API_NOT_FOUND')
  return self.error(405,'الطريقة غير مدعومة.','METHOD_NOT_ALLOWED')
 def supervisor_write(self,c,u,method,path,d):
  if path=='/api/supervisor/assignments' and method=='POST':
   try:wid=int(d.get('worker_id'));vid=int(d.get('vest_id'))
   except (TypeError,ValueError):return self.error(400,'اختر العامل والسترة.','VALIDATION_ERROR')
   worker=c.execute("SELECT * FROM users WHERE id=? AND role='WORKER' AND active=1 AND site_id=? AND team_id=?",(wid,u['site_id'],u['team_id'])).fetchone()
   vest=c.execute("SELECT * FROM vests WHERE id=? AND site_id=? AND status='READY'",(vid,u['site_id'])).fetchone()
   if not worker:return self.error(404,'العامل خارج فريقك أو غير متاح.','OUT_OF_SCOPE')
   if not vest:return self.error(409,'السترة غير متاحة ضمن موقعك.','VEST_UNAVAILABLE')
   if c.execute("SELECT 1 FROM assignments WHERE worker_id=? AND status='ACTIVE'",(wid,)).fetchone():return self.error(409,'للعامل تعيين نشط بالفعل؛ أنهه قبل إنشاء تعيين جديد.','WORKER_ALREADY_ASSIGNED')
   if c.execute("SELECT 1 FROM assignments WHERE vest_id=? AND status='ACTIVE'",(vid,)).fetchone():return self.error(409,'السترة مسندة بالفعل.','VEST_ALREADY_ASSIGNED')
   start=iso_date(d.get('start_date') or date.today().isoformat())
   if not start:return self.error(400,'تاريخ بدء التعيين غير صالح.','INVALID_DATE')
   try:cur=c.execute("INSERT INTO assignments(worker_id,vest_id,site_id,team_id,status,start_date,created_by,created_at) VALUES(?,?,?,?,?,?,?,?)",(wid,vid,u['site_id'],u['team_id'],'ACTIVE',start.isoformat(),u['id'],stamp()))
   except sqlite3.IntegrityError:return self.error(409,'تعارض في التعيين؛ حدّث القائمة ثم حاول مجددًا.','ASSIGNMENT_CONFLICT')
   audit(c,u['id'],'ASSIGN_VEST','ASSIGNMENT',cur.lastrowid,{'worker_id':wid,'vest_id':vid,'site_id':u['site_id'],'team_id':u['team_id']});c.commit();return self.send(201,{'id':cur.lastrowid})
  m=re.fullmatch(r'/api/supervisor/assignments/(\d+)/end',path)
  if m and method=='POST':
   aid=int(m.group(1));a=c.execute("SELECT * FROM assignments WHERE id=? AND site_id=? AND team_id=? AND status='ACTIVE'",(aid,u['site_id'],u['team_id'])).fetchone()
   if not a:return self.error(404,'التعيين النشط غير موجود ضمن نطاقك.','OUT_OF_SCOPE')
   end=iso_date(d.get('end_date') or date.today().isoformat())
   if not end or end<date.fromisoformat(a['start_date']):return self.error(400,'تاريخ الانتهاء غير صالح.','INVALID_DATE')
   c.execute("UPDATE assignments SET status=?,end_date=?,ended_by=? WHERE id=?",('EXPIRED' if end<date.today() else 'ENDED',end.isoformat(),u['id'],aid));audit(c,u['id'],'END_ASSIGNMENT','ASSIGNMENT',aid,{'end_date':end.isoformat()});c.commit();return self.send(200,{'ok':True})
  if path=='/api/supervisor/alerts' and method=='POST':
   title=str(d.get('title','')).strip();description=str(d.get('description','')).strip();severity=d.get('severity','INFO')
   if len(title)<3 or len(description)<8 or severity not in ('INFO','ATTENTION','URGENT'):return self.error(400,'أدخل عنوانًا ووصفًا مناسبين.','VALIDATION_ERROR')
   cur=c.execute("INSERT INTO alerts(site_id,team_id,title,description,severity,source_class,status,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",(u['site_id'],u['team_id'],title,description,severity,'USER_REPORTED','NEW',u['id'],stamp(),stamp()));c.execute('INSERT INTO alert_events(alert_id,actor_id,action,note,created_at) VALUES(?,?,?,?,?)',(cur.lastrowid,u['id'],'CREATED','بلاغ يدوي من المشرف؛ ليس قراءة مستشعر.',stamp()));audit(c,u['id'],'CREATE','ALERT',cur.lastrowid,{'source':'USER_REPORTED','severity':severity});c.commit();return self.send(201,{'id':cur.lastrowid,'source_class':'USER_REPORTED'})
  m=re.fullmatch(r'/api/supervisor/alerts/(\d+)/transition',path)
  if m and method=='POST':
   aid=int(m.group(1));alert=c.execute('SELECT * FROM alerts WHERE id=? AND site_id=? AND (team_id=? OR team_id IS NULL)',(aid,u['site_id'],u['team_id'])).fetchone()
   if not alert:return self.error(404,'التنبيه غير متاح في نطاقك.','OUT_OF_SCOPE')
   action=d.get('action');note=str(d.get('note','')).strip()
   transitions={'ACKNOWLEDGED':('NEW','تم الإقرار'),'IN_PROGRESS':('ACKNOWLEDGED','بدأت المعالجة'),'RESOLVED':('IN_PROGRESS','تم الحل')}
   if action not in transitions:return self.error(400,'حالة انتقال غير صالحة.','INVALID_TRANSITION')
   before,label=transitions[action]
   if alert['status']!=before:return self.error(409,f'لا يمكن تنفيذ الإجراء؛ الحالة الحالية {alert["status"]}.','INVALID_STATE_TRANSITION')
   if action in ('IN_PROGRESS','RESOLVED') and len(note)<5:return self.error(400,'أضف ملاحظة تشغيلية موجزة لهذه الخطوة.','NOTE_REQUIRED')
   c.execute('UPDATE alerts SET status=?,assigned_to=?,updated_at=?,resolved_at=? WHERE id=?',(action,u['id'],stamp(),stamp() if action=='RESOLVED' else None,aid));c.execute('INSERT INTO alert_events(alert_id,actor_id,action,note,created_at) VALUES(?,?,?,?,?)',(aid,u['id'],action,note,stamp()));audit(c,u['id'],'ALERT_'+action,'ALERT',aid,{'note':note});c.commit();return self.send(200,{'ok':True,'status':action})
  if path.startswith('/api/supervisor/'):return self.error(404,'مسار عمليات المشرف غير موجود.','API_NOT_FOUND')
  return self.error(403,'لا يملك المشرف صلاحية إدارة المواقع أو الفرق أو حسابات المستخدمين.','ROLE_FORBIDDEN')
 def worker_write(self,c,u,method,path,d):
  if path=='/api/worker/profile' and method in ('PUT','PATCH'):
   name=str(d.get('display_name','')).strip();name_en=str(d.get('display_name_en',name)).strip()
   if len(name)<2 or len(name)>80:return self.error(400,'أدخل اسمًا من حرفين إلى 80 حرفًا.','VALIDATION_ERROR')
   c.execute('UPDATE users SET display_name=?,display_name_en=? WHERE id=?',(name,name_en,u['id']));audit(c,u['id'],'UPDATE_OWN_PROFILE','USER',u['id']);c.commit();return self.send(200,{'ok':True,'name':name,'name_en':name_en})
  m=re.fullmatch(r'/api/worker/consents/(\d+)/(grant|deny|revoke)',path)
  if m and method=='POST':
   rid=int(m.group(1));action=m.group(2);req=c.execute('SELECT * FROM access_requests WHERE id=? AND worker_id=?',(rid,u['id'])).fetchone()
   if not req:return self.error(404,'طلب الموافقة غير موجود.','NOT_FOUND')
   if action=='grant':
    if req['status']!='PENDING':return self.error(409,'الطلب لم يعد معلقًا.','INVALID_STATE_TRANSITION')
    hours=d.get('hours',24)
    if hours not in (1,8,24):return self.error(400,'اختر مدة 1 أو 8 أو 24 ساعة.','VALIDATION_ERROR')
    expiry=(utcnow()+timedelta(hours=hours)).isoformat(timespec='seconds')
    c.execute("UPDATE access_requests SET status='GRANTED',decided_at=?,expires_at=? WHERE id=?",(stamp(),expiry,rid))
   elif action=='deny':
    if req['status']!='PENDING':return self.error(409,'الطلب لم يعد معلقًا.','INVALID_STATE_TRANSITION')
    c.execute("UPDATE access_requests SET status='DENIED',decided_at=? WHERE id=?",(stamp(),rid))
   else:
    if req['status']!='GRANTED':return self.error(409,'لا توجد موافقة نشطة لسحبها.','INVALID_STATE_TRANSITION')
    c.execute("UPDATE access_requests SET status='REVOKED',decided_at=? WHERE id=?",(stamp(),rid))
   audit(c,u['id'],'CONSENT_'+action.upper(),'ACCESS_REQUEST',rid,{'scope':req['scope']});c.commit();return self.send(200,{'ok':True,'status':{'grant':'GRANTED','deny':'DENIED','revoke':'REVOKED'}[action]})
  if path.startswith('/api/worker/'):return self.error(404,'مسار العامل غير موجود.','API_NOT_FOUND')
  return self.error(403,'لا يملك العامل صلاحية تعديل النطاق التنظيمي أو التعيينات.','ROLE_FORBIDDEN')

def run():
 init_db();print(f'ZILL ready: http://{HOST}:{PORT} | demo credentials={DEMO_CREDENTIALS} | DB={DB}',flush=True)
 server_class=HTTPServer if os.environ.get('ZILL_SINGLE_THREAD','0')=='1' else ThreadingHTTPServer
 server_class((HOST,PORT),Handler).serve_forever()
if __name__=='__main__':run()
