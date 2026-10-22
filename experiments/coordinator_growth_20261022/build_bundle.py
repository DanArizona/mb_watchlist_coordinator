"""Build an isolated source-pinned Windows handoff; never install production."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import uuid
import zipfile

ROOT = Path(__file__).resolve().parents[2]

VERIFY = '''from pathlib import Path
import hashlib,json,socket,sys,time,unittest
ROOT=Path(__file__).resolve().parent
def verify_inventory():
    expected=json.loads((ROOT/'SOURCE_INVENTORY.json').read_text(encoding='utf-8'))
    actual={p.relative_to(ROOT).as_posix() for p in ROOT.rglob('*') if p.is_file() and 'runs' not in p.relative_to(ROOT).parts and '__pycache__' not in p.relative_to(ROOT).parts and p.name!='SOURCE_INVENTORY.json'}
    if actual!=set(expected['files']): raise ValueError('Bundle source inventory differs')
    for name,sha in expected['files'].items():
        p=ROOT/name
        if not p.resolve().is_relative_to(ROOT.resolve()) or p.is_symlink() or hashlib.sha256(p.read_bytes()).hexdigest()!=sha:
            raise ValueError('Changed bundled source: '+name)
def main():
    verify_inventory()
    def denied(*a,**k): raise RuntimeError('Network denied in growth/recovery verification')
    socket.socket.connect=socket.socket.connect_ex=denied
    socket.create_connection=socket.getaddrinfo=denied
    sys.path[:0]=[str(ROOT/'coordinator/src'),str(ROOT/'coordinator/tests'),str(ROOT/'coordinator/experiments/sampling_promotion_20261016/market_data/src')]
    suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(n) for n in ('test_nasdaq_recovery','test_coordinator_growth','test_nasdaq_sampling','test_sampling_service'))
    before=time.perf_counter(); result=unittest.TextTestRunner(verbosity=1).run(suite)
    report={'result':'PASS' if result.wasSuccessful() else 'FAILED','tests':result.testsRun,'seconds':time.perf_counter()-before,'network':'denied','scope':'Changed receipt/harness paths and affected native producer/service tests; not complete recovery or capacity','production_access':False}
    folder=ROOT/'runs/verification';folder.mkdir(parents=True,exist_ok=True)
    from datetime import datetime,timezone
    import uuid
    output=folder/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8]+'.json')
    output.write_text(json.dumps(report,indent=2)+'\\n',encoding='utf-8')
    print(json.dumps(report,indent=2));print('Saved report: '+str(output))
    return 0 if result.wasSuccessful() else 1
if __name__=='__main__': raise SystemExit(main())
'''

MEASURE = '''from pathlib import Path
from datetime import datetime,timezone
import subprocess,sys,uuid
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
from verify import verify_inventory
verify_inventory()
output=ROOT/'runs/growth'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8])
command=[sys.executable,'-I','-B',str(ROOT/'coordinator/experiments/coordinator_growth_20261022/qualify.py'),'--output',str(output)]
print('OFFLINE native 1000-receipt/200-publication measurement; this can take tens of minutes.',flush=True)
print('No API, password, production journal or poller. Performance FAILED is retained separately from correctness.',flush=True)
print('Output: '+str(output),flush=True)
raise SystemExit(subprocess.call(command))
'''


def build(destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    name = 'coordinator_growth_' + datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S') + '_' + uuid.uuid4().hex[:6]
    with tempfile.TemporaryDirectory(prefix='growth bundle ') as temporary:
        root = Path(temporary) / name
        root.mkdir()
        for source, relative in [
            (ROOT/'src', 'coordinator/src'),
            (ROOT/'experiments/sampling_promotion_20261016/market_data/src',
                'coordinator/experiments/sampling_promotion_20261016/market_data/src')]:
            shutil.copytree(source, root/relative, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        for name_test in ('test_nasdaq_recovery', 'test_coordinator_growth', 'test_nasdaq_sampling', 'test_sampling_service'):
            target = root/'coordinator/tests'/(name_test+'.py')
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT/'tests'/(name_test+'.py'), target)
        for filename in ('qualify.py','README.md'):
            target=root/'coordinator/experiments/coordinator_growth_20261022'/filename
            target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(Path(__file__).parent/filename,target)
        (root/'verify.py').write_text(VERIFY,encoding='utf-8')
        (root/'measure.py').write_text(MEASURE,encoding='utf-8')
        for filename,script in [('28_verify_growth_recovery.cmd','verify.py'),
                                ('29_measure_coordinator_growth.cmd','measure.py')]:
            (root/filename).write_bytes(('@echo off\r\nsetlocal\r\npython -I -B "%~dp0'+script+'"\r\nexit /b %errorlevel%\r\n').encode('utf-8'))
        files={p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob('*')) if p.is_file()}
        (root/'SOURCE_INVENTORY.json').write_text(json.dumps({'contract':'growth-recovery-review-v1',
            'files':files},indent=2)+'\n',encoding='utf-8')
        archive=destination/(name+'.zip')
        with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
            for path in sorted(root.rglob('*')):
                if path.is_file():z.write(path,name+'/'+path.relative_to(root).as_posix())
    return {'archive':str(archive.resolve()),'folder':name,'bytes':archive.stat().st_size,
        'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'files':len(files)+1}


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--destination',type=Path,required=True)
    print(json.dumps(build(parser.parse_args().destination),indent=2))
