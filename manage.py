#!/usr/bin/env python3
"""Small, dependency-free database and configuration helper for ZILL."""
import sys
from server import DB, DEMO_CREDENTIALS, db, init_db, read_credentials

def command_init():
 init_db()
 with db() as c:
  users=c.execute('SELECT COUNT(*) FROM users WHERE active=1').fetchone()[0]
  workers=c.execute("SELECT COUNT(*) FROM users WHERE role='WORKER' AND active=1").fetchone()[0]
 print(f'Database ready: {DB}')
 print(f'Active demo users: {users} (workers: {workers})')
 print('Demo account file:', 'available' if read_credentials() else 'not available')

def command_check():
 init_db()
 with db() as c:
  required=('organization','sites','teams','users','vests','assignments','alerts','sessions','audit')
  missing=[name for name in required if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(name,)).fetchone()]
  roles={row['role']:row['n'] for row in c.execute('SELECT role,COUNT(*) n FROM users WHERE active=1 GROUP BY role')}
 if missing:raise SystemExit('Missing schema tables: '+', '.join(missing))
 if DEMO_CREDENTIALS!='off' and not read_credentials():raise SystemExit('Demo account file missing; remove the demo DB to regenerate, or check ZILL_DEMO_CREDENTIAL_FILE.')
 if roles.get('COMPANY_ADMINISTRATOR',0)<1 or roles.get('SUPERVISOR',0)<1 or roles.get('WORKER',0)<5:raise SystemExit('Expected the seeded company, supervisor and five worker accounts.')
 print('Configuration and database check passed.')
 print('Active demo accounts:',roles)

if __name__=='__main__':
 action=sys.argv[1] if len(sys.argv)>1 else 'init-db'
 if action=='init-db':command_init()
 elif action=='check':command_check()
 else:raise SystemExit('Usage: python manage.py [init-db|check]')
