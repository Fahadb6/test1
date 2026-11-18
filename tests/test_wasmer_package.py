#!/usr/bin/env python3
"""Local smoke test for the Wasmer Python-entrypoint and persistent-demo paths.
This does not emulate or claim to validate Wasmer Edge itself.
"""
import os, shutil, subprocess, tempfile, time, tomllib
from pathlib import Path
import requests
ROOT=Path(__file__).resolve().parents[1]
with (ROOT/'wasmer.toml').open('rb') as f: manifest=tomllib.load(f)
assert manifest['command'][0]['annotations']['wasi']['main-args']==['/src/main.py']
assert manifest['fs']['/app']=='.' and manifest['fs']['/src']=='./wasmer_src'
with tempfile.TemporaryDirectory() as td:
 work=Path(td)/'app';vol=Path(td)/'data';work.mkdir();vol.mkdir()
 shutil.copy(ROOT/'server.py',work/'server.py');shutil.copytree(ROOT/'public',work/'public');shutil.copytree(ROOT/'wasmer_src',work/'wasmer_src')
 env={**os.environ,'PORT':'31992','ZILL_HOST':'127.0.0.1','ZILL_ENV':'demo','ZILL_DEMO_CREDENTIALS':'shared','ZILL_DB':str(vol/'zill.sqlite3'),'ZILL_DEMO_CREDENTIAL_FILE':str(vol/'DEMO_ACCESS_LOCAL.txt'),'ZILL_SINGLE_THREAD':'1','ZILL_SERVER_PATH':str(work/'server.py')}
 base='http://127.0.0.1:31992'
 for run in range(2):
  p=subprocess.Popen(['python','wasmer_src/main.py'],cwd=work,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
  try:
   for _ in range(100):
    try:
     if requests.get(base+'/api/health',timeout=.2).status_code==200:break
    except requests.RequestException:time.sleep(.1)
   else:
    out=p.stderr.read().decode() if p.poll() is not None else 'still running without health response'
    raise AssertionError('local server did not start: '+out)
   accounts=requests.get(base+'/api/demo/accounts?role=SUPERVISOR').json()['accounts']
   assert len(accounts)==1 and accounts[0]['username']=='supervisor'
   s=requests.Session();r=s.post(base+'/api/login',headers={'Origin':base},json={'username':accounts[0]['username'],'password':accounts[0]['password'],'role':'SUPERVISOR'});assert r.status_code==200
   assert s.get(base+'/api/supervisor/data').status_code==200
   print(f'PASS run {run+1}: persisted demo account, login and API')
  finally:
   p.terminate();p.wait(timeout=10)
 assert Path(env['ZILL_DB']).exists() and Path(env['ZILL_DEMO_CREDENTIAL_FILE']).exists()
print('Local volume-path smoke test passed. Wasmer Edge deployment itself remains untested.')
