#!/usr/bin/env python3
"""Acceptance test: build the actual ZIP, extract elsewhere, initialize, start, and use it."""
import os, socket, subprocess, sys, tempfile, time, zipfile
from pathlib import Path
import requests
ROOT=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='zill-release-') as td:
 td=Path(td);archive=td/'release.zip';extracted=td/'unpacked';extracted.mkdir()
 subprocess.run([sys.executable,str(ROOT/'build_release.py'),str(archive)],check=True,cwd=ROOT)
 with zipfile.ZipFile(archive) as z:
  assert z.testzip() is None
  assert 'server.py' in z.namelist() and 'zill-rebuild/server.py' not in z.namelist()
  assert not any(n.endswith(('DEMO_ACCESS_LOCAL.txt','.env','zill.sqlite3')) for n in z.namelist())
  z.extractall(extracted)
 app=extracted
 assert (app/'server.py').is_file() and (app/'public/index.html').is_file()
 # Install no packages; seed the isolated bundle-local DB and generated credentials.
 env={**os.environ,'PORT':'0','ZILL_HOST':'127.0.0.1','ZILL_ENV':'demo','ZILL_DEMO_CREDENTIALS':'local','ZILL_DB':'./data/zill.sqlite3','ZILL_DEMO_CREDENTIAL_FILE':'./data/DEMO_ACCESS_LOCAL.txt'}
 subprocess.run([sys.executable,'manage.py','init-db'],cwd=app,env=env,check=True)
 subprocess.run([sys.executable,'manage.py','check'],cwd=app,env=env,check=True)
 with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
 env['PORT']=str(port);base=f'http://127.0.0.1:{port}'
 p=subprocess.Popen([sys.executable,'server.py'],cwd=app,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
 try:
  for _ in range(120):
   try:
    if requests.get(base+'/api/health',timeout=.25).status_code==200:break
   except requests.RequestException:time.sleep(.1)
  else:raise AssertionError('server did not start from extracted ZIP')
  print('PASS extracted ZIP serves landing and health endpoints')
  assert requests.get(base+'/').status_code==200
  assert requests.get(base+'/images/vest-concept-illustration.png').headers['content-type'].startswith('image/png')
  assert requests.get(base+'/api/not-a-route').status_code==404 and requests.get(base+'/api/not-a-route').headers['content-type'].startswith('application/json')
  for role,expected in [('COMPANY_ADMINISTRATOR',1),('SUPERVISOR',1),('WORKER',5)]:
   response=requests.get(base+'/api/demo/accounts',params={'role':role});assert response.status_code==200 and len(response.json()['accounts'])==expected
  print('PASS extracted ZIP exposes seeded, authenticated demo cards for all roles')
  # Full Chromium/UI journeys against the app served from the extracted release, not workspace source.
  be={**env,'ZILL_TEST_BASE':base}
  subprocess.run([sys.executable,'tests/test_browser.py'],cwd=app,env=be,check=True)
  print('PASS browser acceptance suite against extracted ZIP')
 finally:
  p.terminate()
  try:p.wait(timeout=10)
  except subprocess.TimeoutExpired:p.kill();p.wait(timeout=5)
print('Downloaded-bundle acceptance passed. This does not exercise a remote Wasmer deployment.')
