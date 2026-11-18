#!/usr/bin/env python3
"""Integration tests against an isolated real server and SQLite database."""
import os,shutil,sqlite3,subprocess,tempfile,time,hashlib
from pathlib import Path
import requests
ROOT=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory() as td:
 d=Path(td);shutil.copy(ROOT/'server.py',d/'server.py');shutil.copytree(ROOT/'public',d/'public');base='http://127.0.0.1:31991'
 p=subprocess.Popen(['python','server.py'],cwd=d,env={**os.environ,'PORT':'31991','ZILL_DB':str(d/'test.sqlite3'),'ZILL_DEMO_CREDENTIALS':'local'},stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
 n=0
 def ck(ok,label):
  global n
  assert ok,label;n+=1;print('PASS',label)
 def login(username,role=None):
  s=requests.Session();pw=creds[username];r=s.post(base+'/api/login',headers={'Origin':base},json={'username':username,'password':pw['password'],'role':role or pw['role']});return s,r
 def token(s):return s.get(base+'/api/session').json()['csrf']
 def post(s,path,data=None,csrf=None,origin=None):
  h={'Origin':origin or base}
  if csrf is not None:h['X-CSRF-Token']=csrf
  return s.post(base+path,headers=h,json=data or {})
 def mut(s,path,data,csrf,method='POST'):
  return s.request(method,base+path,headers={'Origin':base,'X-CSRF-Token':csrf},json=data)
 try:
  for _ in range(100):
   try:
    if requests.get(base+'/api/health',timeout=.2).status_code==200:break
   except requests.RequestException:time.sleep(.1)
  else:raise RuntimeError('server startup failed')
  ck(requests.get(base+'/').status_code==200,'landing served by same-origin application')
  roles={'COMPANY_ADMINISTRATOR':requests.get(base+'/api/demo/accounts?role=COMPANY_ADMINISTRATOR').json()['accounts'],'SUPERVISOR':requests.get(base+'/api/demo/accounts?role=SUPERVISOR').json()['accounts'],'WORKER':requests.get(base+'/api/demo/accounts?role=WORKER').json()['accounts']}
  ck([len(roles[x]) for x in roles]==[1,1,5],'seven actual seeded demo accounts exposed through validated endpoint')
  creds={x['username']:x for group in roles.values() for x in group}
  with sqlite3.connect(d/'test.sqlite3') as c:
   for x in creds.values():
    h=c.execute('SELECT password_hash FROM users WHERE username=?',(x['username'],)).fetchone()[0]
    salt,digest=h.split(':',1);actual=hashlib.scrypt(x['password'].encode(),salt=bytes.fromhex(salt),n=16384,r=8,p=1,dklen=32).hex()
    ck(actual==digest,'demo credential matches seeded scrypt hash '+x['username'])
  sessions={};tokens={}
  for user in creds:
   s,r=login(user);ck(r.status_code==200,'login '+user);sessions[user]=s;tokens[user]=token(s)
  admin=sessions['admin'];sup=sessions['supervisor'];worker=sessions['wrk-001'];w4=sessions['wrk-004'];w5=sessions['wrk-005'];ac=tokens['admin'];sc=tokens['supervisor'];wc=tokens['wrk-001']
  ck(admin.get(base+'/api/company/overview').status_code==200,'company overview authenticated')
  ck(sup.get(base+'/api/supervisor/data').json()['site']['code']=='JED-01','supervisor assigned site')
  team=sup.get(base+'/api/supervisor/data').json();ck(len(team['workers'])==5 and len(team['assignments'])==4,'supervisor team and active/expired assignment history')
  ck(w4.get(base+'/api/worker/data').json()['assignment'] is None and w4.get(base+'/api/worker/data').json()['past_assignments'][0]['status']=='EXPIRED','worker 004 sees expired history, no active vest')
  ck(w5.get(base+'/api/worker/data').json()['assignment'] is None and w5.get(base+'/api/worker/data').json()['notifications']==[],'worker 005 has no vest and no fallback notices')
  wd=worker.get(base+'/api/worker/data').json();ck(wd['assignment']['vest_code']=='ZT-DEMO-01','worker reads only their active vest');ck(wd['telemetry'] is None and wd['telemetry_classification']=='UNKNOWN','missing telemetry stays UNKNOWN rather than zero')
  ck(sup.get(base+'/api/company/overview').status_code==403 and worker.get(base+'/api/supervisor/data').status_code==403,'role authorization enforced server-side')
  ck(requests.get(base+'/api/company/workers').status_code==401,'sensitive API requires authentication')
  data=admin.get(base+'/api/company/workers').json()['items'];ck(len(data)==5 and all(x['name'] is None and x['assignment_status'] is None and x['vest_code'] is None for x in data),'individual identity and assignment details masked by default')
  cdata=admin.get(base+'/api/company/overview').json();ck(cdata['metrics']['workers']==5 and cdata['metrics']['active_assignments']==3 and cdata['metrics']['without_active']==2,'company metrics calculated from actual seeded data')
  ck(admin.get(base+'/api/company/report.csv').json()['classification']=='CALCULATED_FROM_DEMO_DATABASE','aggregate CSV report derives from live DB')
  # Consent request -> worker grant -> scoped disclosure -> worker revokes -> disclosure hidden.
  wid=next(x['id'] for x in data if x['employee_id']=='WRK-001')
  r=mut(admin,'/api/company/access-requests',{'worker_id':wid,'reason':'تدقيق حساب تجريبي محدد','scope':'PROFILE'},ac);ck(r.status_code==201,'company requests scoped worker consent')
  worker_data=worker.get(base+'/api/worker/data').json();rid=worker_data['consents'][0]['id']
  ck(mut(sessions['wrk-002'],f'/api/worker/consents/{rid}/grant',{'hours':1},tokens['wrk-002']).status_code==404,'worker cannot act on another worker consent request')
  ck(mut(worker,f'/api/worker/consents/{rid}/grant',{'hours':1},wc).status_code==200,'worker explicitly grants time-limited profile access')
  data=admin.get(base+'/api/company/workers').json()['items'];ck(next(x for x in data if x['id']==wid)['name']=='عبدالرحمن العتيبي','company sees name only after explicit active consent')
  ck(mut(worker,f'/api/worker/consents/{rid}/revoke',{},wc).status_code==200,'worker revokes consent')
  data=admin.get(base+'/api/company/workers').json()['items'];ck(next(x for x in data if x['id']==wid)['name'] is None,'company access disappears after consent revocation')
  r=mut(admin,'/api/company/access-requests',{'worker_id':wid,'reason':'مراجعة سجل التعيين','scope':'ASSIGNMENT'},ac);rid2=r.json()['id'];ck(r.status_code==201,'company requests a separate assignment scope')
  ck(mut(worker,f'/api/worker/consents/{rid2}/grant',{'hours':1},wc).status_code==200,'worker grants assignment details separately')
  detail=next(x for x in admin.get(base+'/api/company/workers').json()['items'] if x['id']==wid);ck(detail['vest_code']=='ZT-DEMO-01','only matching assignment grant reveals individual assignment and vest')
  ck(mut(worker,f'/api/worker/consents/{rid2}/revoke',{},wc).status_code==200,'worker revokes assignment scope')
  detail=next(x for x in admin.get(base+'/api/company/workers').json()['items'] if x['id']==wid);ck(detail['vest_code'] is None,'assignment detail is masked immediately after revocation')
  # Organization management remains Company-only.
  r=mut(admin,'/api/company/sites',{'name':'موقع اختبار','code':'TST-02','region':'جدة'},ac);ck(r.status_code==201,'company creates real DB site')
  site2=r.json()['id'];r=mut(admin,'/api/company/teams',{'site_id':site2,'name':'فريق اختبار','code':'TST-T2'},ac);ck(r.status_code==201,'company creates site-linked team')
  team2=r.json()['id'];ck(mut(sup,'/api/company/teams',{'site_id':site2,'name':'unauthorized','code':'BAD'},sc).status_code==403,'supervisor cannot manage company organization')
  ck(mut(admin,f'/api/company/sites/{site2}',{},ac,'DELETE').status_code==200,'company archives empty site and its teams')
  ck(mut(admin,'/api/company/sites/1',{},ac,'DELETE').status_code==409,'company cannot archive site with active accounts')
  # Create actual worker/supervisor accounts; password returned once and can authenticate.
  site=admin.get(base+'/api/sites').json()['items'][0]['id'];teamid=admin.get(base+'/api/teams').json()['items'][0]['id']
  r=mut(admin,'/api/company/workers',{'username':'wrk-006','employee_id':'WRK-006','site_id':site,'team_id':teamid},ac);ck(r.status_code==201 and r.json()['temporary_password'],'company provisions worker and gets one-time password')
  fresh=requests.Session();rr=fresh.post(base+'/api/login',headers={'Origin':base},json={'username':'wrk-006','password':r.json()['temporary_password'],'role':'WORKER'});ck(rr.status_code==200,'newly provisioned real account authenticates')
  # Vest assignment must be site/team scoped and conflict-free.
  d=sup.get(base+'/api/supervisor/data').json();w5id=next(w['id'] for w in d['workers'] if w['employee_id']=='WRK-005');vestid=next(v['id'] for v in d['vests'] if v['availability']=='AVAILABLE' and v['status']=='READY')
  r=mut(sup,'/api/supervisor/assignments',{'worker_id':w5id,'vest_id':vestid,'start_date':'2026-11-18'},sc);ck(r.status_code==201,'supervisor assigns available vest in own team')
  assigned_code=w5.get(base+'/api/worker/data').json()['assignment']['vest_code'];ck(assigned_code in ('ZT-DEMO-04','ZT-DEMO-05'),'assignment persists and appears only to worker')
  ck(mut(sup,'/api/supervisor/assignments',{'worker_id':w5id,'vest_id':vestid,'start_date':'2026-11-18'},sc).status_code==409,'duplicate active assignment rejected')
  # Alerts follow explicit state transitions and audit.
  r=mut(sup,'/api/supervisor/alerts',{'title':'بلاغ اختبار','description':'وصف بلاغ يدوي تجريبي','severity':'INFO'},sc);ck(r.status_code==201 and r.json()['source_class']=='USER_REPORTED','supervisor creates labeled manual alert')
  aid=r.json()['id'];ck(mut(sup,f'/api/supervisor/alerts/{aid}/transition',{'action':'RESOLVED','note':'تم الفحص'},sc).status_code==409,'cannot resolve before acknowledgement and handling')
  ck(mut(sup,f'/api/supervisor/alerts/{aid}/transition',{'action':'ACKNOWLEDGED'},sc).status_code==200,'supervisor acknowledges alert')
  ck(mut(sup,f'/api/supervisor/alerts/{aid}/transition',{'action':'IN_PROGRESS','note':'بدأت المتابعة'},sc).status_code==200,'supervisor records handling separately')
  ck(mut(sup,f'/api/supervisor/alerts/{aid}/transition',{'action':'RESOLVED','note':'اكتملت المعالجة'},sc).status_code==200,'supervisor resolves after handling')
  ck(mut(admin,f'/api/supervisor/alerts/{aid}/transition',{'action':'ACKNOWLEDGED'},ac).status_code==403,'company cannot perform supervisor alert actions')
  ck(mut(sup,f'/api/company/workers/{wid}/organization',{'site_id':site2,'team_id':team2},sc,'PATCH').status_code==403,'supervisor cannot change organizational scope')
  r=mut(admin,'/api/company/sites',{'name':'موقع نطاق مستقل','code':'OUT-01','region':'جدة'},ac);site3=r.json()['id']
  r=mut(admin,'/api/company/teams',{'site_id':site3,'name':'فريق مستقل','code':'OUT-T1'},ac);team3=r.json()['id']
  r=mut(admin,'/api/company/supervisors',{'username':'supervisor2','employee_id':'SUP-002','display_name':'مشرف مستقل','site_id':site3,'team_id':team3},ac);ck(r.status_code==201,'company provisions supervisor with a separate scope')
  sup2=requests.Session();rr=sup2.post(base+'/api/login',headers={'Origin':base},json={'username':'supervisor2','password':r.json()['temporary_password'],'role':'SUPERVISOR'});ck(rr.status_code==200,'second supervisor authenticates in assigned scope');sc2=token(sup2)
  scoped=sup2.get(base+'/api/supervisor/data').json();ck(scoped['site']['id']==site3 and scoped['workers']==[],'second supervisor sees only assigned site and team')
  r=mut(sup2,'/api/supervisor/assignments',{'worker_id':wid,'vest_id':vestid,'start_date':'2026-11-18'},sc2);ck(r.status_code==404 and r.json()['code']=='OUT_OF_SCOPE','supervisor cannot assign an out-of-scope worker or vest')
  original_alert=next(a['id'] for a in d['alerts'] if a['status']=='NEW')
  r=mut(sup2,f'/api/supervisor/alerts/{original_alert}/transition',{'action':'ACKNOWLEDGED'},sc2);ck(r.status_code==404 and r.json()['code']=='OUT_OF_SCOPE','supervisor cannot view or transition an out-of-scope alert')
  # HTTP / API errors remain JSON and do not leak internals.
  for method,path,status in [('GET','/api/not-real',404),('POST','/api/not-real',404),('PUT','/api/login',405)]:
   rr=requests.request(method,base+path,headers={'Origin':base},json={});ck(rr.status_code==status and rr.headers.get('content-type','').startswith('application/json') and isinstance(rr.json(),dict),f'{method} {path} returns JSON {status}')
  rr=requests.post(base+'/api/login',headers={'Origin':'https://attacker.invalid'},json={'username':'admin','password':'bad','role':'COMPANY_ADMINISTRATOR'});ck(rr.status_code==403 and rr.json()['code']=='ORIGIN_REJECTED','login rejects hostile origin')
  rr=requests.post(base+'/api/login',headers={'Origin':base,'Content-Type':'application/json'},data='not json');ck(rr.status_code==400 and rr.json()['code']=='INVALID_JSON','malformed JSON returns structured 400')
  ck(mut(sup,'/api/supervisor/alerts',{'title':'no CSRF','description':'missing token','severity':'INFO'},'bad-token').status_code==403,'CSRF token enforced')
  # Session expiry and logout are enforced by persisted session records.
  rr=post(worker,'/api/logout',{},wc);ck(rr.status_code==200 and worker.get(base+'/api/worker/data').status_code==401,'logout revokes session')
  wr=requests.get(base+'/api/not-real');ck(wr.status_code==404 and 'text/html' not in wr.headers.get('content-type',''),'anonymous unknown API route remains JSON 404')
  with sqlite3.connect(Path(td)/'test.sqlite3') as c:c.execute('ALTER TABLE teams RENAME TO teams_failure')
  rr=admin.get(base+'/api/teams');ck(rr.status_code==500 and rr.headers['content-type'].startswith('application/json') and 'Traceback' not in rr.text,'database failure returns safe JSON 500')
 finally:
  p.terminate();p.wait(timeout=10)
 if p.stderr:
  err=p.stderr.read().decode()
  if err.strip():print('server stderr:',err.strip())
 print(f'\n{n} API checks passed')
