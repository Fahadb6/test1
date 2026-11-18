#!/usr/bin/env python3
"""Build a clean, self-contained ZILL source ZIP with files at archive root."""
from pathlib import Path
import sys, zipfile
ROOT=Path(__file__).resolve().parent
OUTPUT=Path(sys.argv[1]).resolve() if len(sys.argv)>1 else ROOT.parent/'zill-platform-demo.zip'
INCLUDE_ROOT={'.gitignore','.env.example','README.md','TEST_REPORT.md','DEPLOY_TO_WASMER.md','app.yaml','wasmer.toml','server.py','manage.py','run.sh','run.bat','requirements.txt','requirements-test.txt','build_release.py'}
INCLUDE_DIRS={'public','wasmer_src','tests'}
EXCLUDE_NAMES={'.env','DEMO_ACCESS_LOCAL.txt','zill.sqlite3','zill.sqlite3-shm','zill.sqlite3-wal'}
files=[]
for name in INCLUDE_ROOT:
 p=ROOT/name
 if p.is_file():files.append(p)
for dirname in INCLUDE_DIRS:
 d=ROOT/dirname
 if d.exists():
  for p in d.rglob('*'):
   if p.is_file() and not any(x in {'__pycache__','.pytest_cache','node_modules'} for x in p.parts) and p.name not in EXCLUDE_NAMES and not p.name.endswith(('.pyc','.sqlite3','.db')):files.append(p)
OUTPUT.parent.mkdir(parents=True,exist_ok=True)
with zipfile.ZipFile(OUTPUT,'w',zipfile.ZIP_DEFLATED,compresslevel=8) as z:
 for p in sorted(set(files)):
  z.write(p,p.relative_to(ROOT).as_posix())
with zipfile.ZipFile(OUTPUT) as z:
 bad=z.testzip()
 if bad:raise SystemExit(f'ZIP CRC failure: {bad}')
 names=set(z.namelist())
 for required in ('server.py','public/index.html','manage.py','run.sh','run.bat','.env.example'):
  if required not in names:raise SystemExit(f'Missing release file: {required}')
 if any(n.endswith(('/DEMO_ACCESS_LOCAL.txt','.env','zill.sqlite3')) for n in names):raise SystemExit('Refusing to bundle generated credentials/database')
 print(f'Built {OUTPUT} ({len(names)} files, {OUTPUT.stat().st_size} bytes; archive root is directly runnable).')
