"""Build only the short, inventory-pinned Windows affected-suite handoff."""
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import uuid
import zipfile

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).parent
spec = importlib.util.spec_from_file_location('history_reconstruction_verify', HERE/'verify.py')
verification = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verification)

LAUNCHER = '''from pathlib import Path
import hashlib,json,subprocess,sys
ROOT=Path(__file__).resolve().parent
def verify_inventory():
    expected=json.loads((ROOT/'SOURCE_INVENTORY.json').read_text(encoding='utf-8'))['files']
    actual={p.relative_to(ROOT).as_posix() for p in ROOT.rglob('*') if p.is_file() and 'runs' not in p.relative_to(ROOT).parts and '__pycache__' not in p.relative_to(ROOT).parts and p.name!='SOURCE_INVENTORY.json'}
    if actual!=set(expected): raise ValueError('Bundle source inventory differs')
    for name,sha in expected.items():
        path=ROOT/name
        if not path.resolve().is_relative_to(ROOT.resolve()) or path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest()!=sha:
            raise ValueError('Changed bundled source: '+name)
if __name__=='__main__':
    verify_inventory()
    print('OFFLINE changed-history-reconstruction verification. No API, password or production journal.',flush=True)
    print('This does not qualify complete recovery or provider capacity.',flush=True)
    raise SystemExit(subprocess.call([sys.executable,'-I','-B',str(ROOT/'coordinator/experiments/coordinator_history_reconstruction_20261022/verify.py'),'--output-root',str(ROOT/'runs')]))
'''


def build(destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    name = 'coordinator_history_reconstruction_'+datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:6]
    with tempfile.TemporaryDirectory(prefix='history cost bundle ') as temporary:
        root = Path(temporary)/name
        root.mkdir()
        for source, relative in [(ROOT/'src', 'coordinator/src'),
            (ROOT/'experiments/sampling_promotion_20261016/market_data/src',
             'coordinator/experiments/sampling_promotion_20261016/market_data/src')]:
            shutil.copytree(source, root/relative, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        for test in verification.SUITES:
            source = ROOT/'tests'/(test+'.py')
            relative = 'coordinator/tests/'+test+'.py'
            if not source.is_file():
                source = HERE/'native_tests'/(test+'.py')
                relative = 'coordinator/experiments/coordinator_history_reconstruction_20261022/native_tests/'+test+'.py'
                if not source.is_file():
                    source = ROOT/'experiments/coordinator_history_cost_20261022/native_tests'/(test+'.py')
                    relative = 'coordinator/experiments/coordinator_history_cost_20261022/native_tests/'+test+'.py'
            target = root/relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        for source, relative in [
            (HERE/'verify.py', 'coordinator/experiments/coordinator_history_reconstruction_20261022/verify.py'),
            (HERE/'README.md', 'README.md'),
            (ROOT/'experiments/coordinator_growth_20261022/qualify.py', 'coordinator/experiments/coordinator_growth_20261022/qualify.py')]:
            target = root/relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        (root/'verify_source.py').write_text(LAUNCHER, encoding='utf-8')
        (root/'31_verify_history_reconstruction.cmd').write_bytes(b'@echo off\r\nsetlocal\r\npython -I -B "%~dp0verify_source.py"\r\nexit /b %errorlevel%\r\n')
        files = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in sorted(root.rglob('*')) if p.is_file()}
        (root/'SOURCE_INVENTORY.json').write_text(json.dumps({'contract': 'history-reconstruction-handoff-v1', 'files': files}, indent=2)+'\n')
        archive = destination/(name+'.zip')
        with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as output:
            for path in sorted(root.rglob('*')):
                if path.is_file():
                    output.write(path, name+'/'+path.relative_to(root).as_posix())
    return {'archive': str(archive.resolve()), 'folder': name, 'bytes': archive.stat().st_size,
        'sha256': hashlib.sha256(archive.read_bytes()).hexdigest(), 'files': len(files)+1}


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--destination', type=Path, required=True)
    print(json.dumps(build(parser.parse_args().destination), indent=2))
