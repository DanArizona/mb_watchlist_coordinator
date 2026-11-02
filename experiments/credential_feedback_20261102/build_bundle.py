"""Build a source-pinned offline verifier; never installs an operating release."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile

BASE = '8d7d2d202db45d95a393508691c5638ee50545e2'
NATIVE = 'd37d2c37e3ac9cc2c860d0a2313a1526e30fd23e'
EXPERIMENT = 'experiments/credential_feedback_20261102'
CHANGED = sorted('src/mb_watchlist_coordinator/'+name+'.py' for name in (
    'authenticated_startup', 'daily_operating', 'daily_launch', 'daily_operator',
    'market_open_check', 'after_hours_profile', 'live_profile', 'installed_startup_probe'))


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args]).decode().strip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--native-root', required=True, type=Path)
    parser.add_argument('--destination', required=True, type=Path)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[2]
    native = args.native_root.resolve()
    for root in (repo, native):
        if git(root, 'status', '--porcelain', '--untracked-files=no'):
            raise ValueError('Committed clean source required')
    if git(native, 'rev-parse', 'HEAD') != NATIVE:
        raise ValueError('Original native baseline required')
    if sorted(git(repo, 'diff', '--name-only', BASE, 'HEAD', '--', 'src').splitlines()) != CHANGED:
        raise ValueError('Password feedback runtime change scope differs')
    args.destination.mkdir(parents=True, exist_ok=True)
    stage = args.destination/'p99'; stage.mkdir(exist_ok=False)
    def copy(root, name, target):
        value = subprocess.check_output(['git', '-C', str(root), 'show', 'HEAD:'+name])
        if name.endswith('.cmd'): value = value.replace(b'\r\n', b'\n').replace(b'\n', b'\r\n')
        target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(value)
    reference = 'experiments/authenticated_startup_20261023/reference_mb_tools/src'
    for root, prefix, sections in ((repo, 'coordinator', ('src', 'tests', reference)),
            (native, 'market_data', ('src',))):
        for section in sections:
            for name in git(root, 'ls-files', section).splitlines():
                if '__pycache__' in Path(name).parts or name.endswith(('.pyc', '.pyo')):
                    raise ValueError('Bytecode refused')
                copy(root, name, stage/prefix/name)
    for name in ('run.py', 'README.md', '99_verify_password_feedback.cmd', 'DEVELOPMENT.json'):
        copy(repo, EXPERIMENT+'/'+name, stage/name)
    source = {'coordinator_commit': git(repo, 'rev-parse', 'HEAD'),
        'coordinator_tree': git(repo, 'rev-parse', 'HEAD^{tree}'),
        'base_coordinator_commit': BASE, 'market_data_commit': NATIVE,
        'market_data_tree': git(native, 'rev-parse', 'HEAD^{tree}'),
        'runtime_changes': CHANGED,
        'unchanged_approved_p85_inventory_sha256': '0c5f9d7a2dfcdd72ffc9d3d07b7ea2e4b9528139a948496e4fd921476fdf6ffe'}
    files = {p.relative_to(stage).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(stage.rglob('*')) if p.is_file()}
    (stage/'SOURCE_INVENTORY.json').write_text(json.dumps({'contract': 'password-feedback-source-v1',
        'source': source, 'files': files}, indent=2, sort_keys=True)+'\n')
    archive = args.destination/('password_feedback_20261102_'+source['coordinator_commit'][:7]+'.zip')
    with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_DEFLATED) as z:
        for path in sorted(stage.rglob('*')):
            if path.is_file(): z.write(path, 'p99/'+path.relative_to(stage).as_posix())
    print(json.dumps({'archive': str(archive), 'stage': str(stage), 'source': source,
        'bytes': archive.stat().st_size, 'sha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
        'inventory_sha256': hashlib.sha256((stage/'SOURCE_INVENTORY.json').read_bytes()).hexdigest()}, indent=2))


if __name__ == '__main__': main()
