"""Deliver only the independent display entry and its focused qualification."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile

NATIVE = '5552c5db43351d1a9ae8d376196cc99ba9c7f05d'
BASE = '6665a953c8cb4ffadaeab7b5717df68cf9c69965'
EXPERIMENT = 'experiments/membership_status_20261030'


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args]).decode().strip()


def copy_blob(root, name, destination):
    data = subprocess.check_output(['git', '-C', str(root), 'show', 'HEAD:'+name])
    destination.parent.mkdir(parents=True, exist_ok=True)
    if name.endswith('.cmd'):
        data = data.replace(b'\r\n', b'\n').replace(b'\n', b'\r\n')
    destination.write_bytes(data)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--market-data-root', required=True, type=Path)
    parser.add_argument('--destination', required=True, type=Path)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[2]
    native = args.market_data_root.resolve()
    for root in (repo, native):
        if git(root, 'status', '--porcelain', '--untracked-files=no'):
            raise ValueError('Committed source required')
    if git(native, 'rev-parse', 'HEAD') != NATIVE:
        raise ValueError('Accepted native source required')
    changed = git(repo, 'diff', '--name-only', BASE, 'HEAD', '--', 'src').splitlines()
    expected = ['src/mb_watchlist_coordinator/daily_membership_'+name+'.py' for name in ('status', 'window')]
    if changed != expected:
        raise ValueError('Only the independent membership display may change')
    args.destination.mkdir(parents=True, exist_ok=True)
    stage = args.destination/'p81'
    stage.mkdir(exist_ok=False)
    for root, prefix in ((repo, 'coordinator'), (native, 'market_data')):
        for name in git(root, 'ls-files', 'src').splitlines():
            if '__pycache__' in Path(name).parts or name.endswith(('.pyc', '.pyo')):
                raise ValueError('Bytecode is not a runtime source')
            copy_blob(root, name, stage/prefix/name)
    for name in ('test_daily_membership_status.py', 'test_daily_membership_window.py'):
        copy_blob(repo, 'tests/'+name, stage/'coordinator/tests'/name)
    for name in ('run.py', 'README.md', '81_verify_membership_status.cmd', '82_show_membership_status.cmd'):
        copy_blob(repo, EXPERIMENT+'/'+name, stage/name)
    filename = 'membership_status_20261030_'+git(repo, 'rev-parse', 'HEAD')[:7]+'.zip'
    readme = stage/'README.md'
    readme.write_bytes(readme.read_bytes().replace(b'@@ZIP@@', filename.encode()))
    manifest = {'contract': 'membership-status-source-v1',
        'source': {'coordinator_commit': git(repo, 'rev-parse', 'HEAD'), 'market_data_commit': NATIVE,
            'accepted_daily_composition_baseline': BASE}, 'runtime_changes': changed,
        'files': {p.relative_to(stage).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in sorted(stage.rglob('*')) if p.is_file()}}
    (stage/'SOURCE_INVENTORY.json').write_text(json.dumps(manifest, indent=2, sort_keys=True)+'\n')
    archive = args.destination/filename
    with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_DEFLATED) as z:
        for path in sorted(stage.rglob('*')):
            if path.is_file():
                z.write(path, 'p81/'+path.relative_to(stage).as_posix())
    print(json.dumps({'archive': str(archive), 'stage': str(stage), 'bytes': archive.stat().st_size,
        'sha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
        'coordinator_tree': git(repo, 'rev-parse', 'HEAD^{tree}')}, indent=2))


if __name__ == '__main__':
    main()
