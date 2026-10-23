"""Inventory-pinned offline Windows handoff; never install into production."""
from datetime import datetime,timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import uuid
import zipfile

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).parent
spec=importlib.util.spec_from_file_location('reuse_verify',HERE/'verify.py')
verify=importlib.util.module_from_spec(spec);spec.loader.exec_module(verify)

LAUNCHER='''from pathlib import Path
import hashlib,json,subprocess,sys
ROOT=Path(__file__).resolve().parent
def verify_inventory():
    expected=json.loads((ROOT/'SOURCE_INVENTORY.json').read_text(encoding='utf-8'))['files']
    actual={p.relative_to(ROOT).as_posix() for p in ROOT.rglob('*') if p.is_file() and 'runs' not in p.relative_to(ROOT).parts and '__pycache__' not in p.relative_to(ROOT).parts and p.name!='SOURCE_INVENTORY.json'}
    if actual!=set(expected):raise ValueError('Bundle source inventory differs')
    for name,sha in expected.items():
        p=ROOT/name
        if not p.resolve().is_relative_to(ROOT.resolve()) or p.is_symlink() or hashlib.sha256(p.read_bytes()).hexdigest()!=sha:
            raise ValueError('Changed bundled source: '+name)
if __name__=='__main__':
    verify_inventory()
    print('OFFLINE native Hot collector and acquisition-recovery qualification. No API, password or production journal.',flush=True)
    print('Corrected test-owned SQLite cleanup. Collector runtime unchanged; synthetic provider/process drills only.',flush=True)
    args=[sys.executable,'-I','-B',str(ROOT/'coordinator/experiments/hot_collector_recovery_20261023/verify.py'),'--output-root',str(ROOT/'runs')]
    raise SystemExit(subprocess.call(args))
'''

def build(destination):
    destination=Path(destination);destination.mkdir(parents=True,exist_ok=True)
    name='hot_collector_cleanup_'+datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:6]
    with tempfile.TemporaryDirectory(prefix='recovery delivery bundle ') as temporary:
        root=Path(temporary)/name;root.mkdir()
        for source in [ROOT/'src',ROOT/'experiments/sampling_promotion_20261016/market_data/src']:
            shutil.copytree(source,root/'coordinator'/source.relative_to(ROOT),ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        for test in verify.SUITES:
            choices=[ROOT/'tests'/(test+'.py'),ROOT/'experiments/hot_collector_recovery_20261023/native_tests'/(test+'.py'),ROOT/'experiments/coordinator_history_reconstruction_20261022/native_tests'/(test+'.py'),ROOT/'experiments/coordinator_history_cost_20261022/native_tests'/(test+'.py')]
            source=next(p for p in choices if p.is_file());target=root/'coordinator'/source.relative_to(ROOT)
            target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
        for source in [HERE/'verify.py',ROOT/'experiments/nasdaq_request_reuse_20261022/qualify.py',ROOT/'experiments/nasdaq_request_reuse_20261022/workload_facts.json',ROOT/'experiments/coordinator_growth_20261022/qualify.py']:
            target=root/'coordinator'/source.relative_to(ROOT);target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
        (root/'coordinator/tests/fixtures').mkdir(parents=True,exist_ok=True)
        for fixture in ('recovery_probe_worker.py','recovery_collector_worker.py'):
            shutil.copyfile(ROOT/'tests/fixtures'/fixture,root/'coordinator/tests/fixtures'/fixture)
        shutil.copyfile(HERE/'README.md',root/'README.md')
        (root/'verify_source.py').write_text(LAUNCHER)
        (root/'37_verify_hot_collector_cleanup.cmd').write_bytes(b'@echo off\r\nsetlocal\r\npython -I -B "%~dp0verify_source.py"\r\nexit /b %errorlevel%\r\n')
        files={p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob('*')) if p.is_file()}
        (root/'SOURCE_INVENTORY.json').write_text(json.dumps({'contract':'nasdaq-recovery-supervision-handoff-v1','files':files},indent=2)+'\n')
        out=destination/(name+'.zip')
        with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
            for p in sorted(root.rglob('*')):
                if p.is_file():z.write(p,name+'/'+p.relative_to(root).as_posix())
    return {'archive':str(out.resolve()),'folder':name,'bytes':out.stat().st_size,
            'sha256':hashlib.sha256(out.read_bytes()).hexdigest(),'files':len(files)+1}

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--destination',type=Path,required=True)
    print(json.dumps(build(parser.parse_args().destination),indent=2))
