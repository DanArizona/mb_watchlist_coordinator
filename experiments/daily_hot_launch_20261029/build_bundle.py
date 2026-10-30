"""Package committed public launch composition with the accepted native source."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile

NATIVE = '5552c5db43351d1a9ae8d376196cc99ba9c7f05d'
ACCEPTED = '64c33c27131f96902c46cb4d175536248bd52072'


def git(root, *args): return subprocess.check_output(['git', '-C', str(root), *args]).decode().strip()
def blob(root, path): return subprocess.check_output(['git', '-C', str(root), 'show', 'HEAD:'+path])


def copy_sources(root, prefix, destination):
    for name in git(root, 'ls-files', prefix).splitlines():
        if '__pycache__' in Path(name).parts or name.endswith(('.pyc', '.pyo')):
            raise ValueError('Bytecode refused')
        path = destination/name; path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(blob(root, name))


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--market-data-root', type=Path, required=True)
    p.add_argument('--destination', type=Path, required=True)
    args = p.parse_args()
    repo = Path(__file__).resolve().parents[2]; native = args.market_data_root.resolve()
    for root in (repo, native):
        if git(root, 'status', '--porcelain', '--untracked-files=no'):
            raise ValueError('Clean committed source required')
    if git(native, 'rev-parse', 'HEAD') != NATIVE:
        raise ValueError('Accepted candidate native source required')
    changed = git(repo, 'diff', '--name-only', ACCEPTED, 'HEAD', '--', 'src').splitlines()
    expected = ['src/mb_watchlist_coordinator/'+s for s in
        ('daily_launch.py', 'daily_launch_cli.py', 'daily_launch_entry.py', 'integrated_catalog.py')]
    if changed != expected: raise ValueError('Unexpected runtime source scope')
    source = {'coordinator_commit': git(repo, 'rev-parse', 'HEAD'), 'market_data_commit': NATIVE,
        'production_native_baseline': '6b53ab1d12e4e1fdaf4deb1d70b717e13570358c',
        'accepted_local_predecessor': ACCEPTED}
    name = 'daily_hot_launch_20261029_'+source['coordinator_commit'][:7]+'_5552c5d'
    args.destination.mkdir(parents=True, exist_ok=True)
    stage = args.destination/name; stage.mkdir(exist_ok=False)
    copy_sources(repo, 'src', stage/'coordinator'); copy_sources(repo, 'tests', stage/'coordinator')
    copy_sources(native, 'src', stage/'market_data')
    copy_sources(native, 'src', stage/'coordinator/experiments/sampling_promotion_20261016/market_data')
    prefix = 'experiments/daily_hot_launch_20261029/'
    for name in ('run.py', 'README.md', '72_verify_daily_hot_launch.cmd', 'daily_hot.cmd', 'LOCAL_QUALIFICATION.json'):
        raw = blob(repo, prefix+name)
        if name.endswith('.cmd'): raw = raw.replace(b'\r\n', b'\n').replace(b'\n', b'\r\n')
        (stage/name).write_bytes(raw)
    (stage/'WINDOWS71_ACCEPTANCE.json').write_bytes(blob(repo,
        'experiments/daily_hot_windows_evidence_read_20261029/WINDOWS_ACCEPTANCE.json'))
    files = {p.relative_to(stage).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(stage.rglob('*')) if p.is_file()}
    (stage/'SOURCE_INVENTORY.json').write_text(json.dumps({'contract': 'daily-hot-public-launch-source-v1',
        'source': source, 'runtime_changes_since_accepted': changed,
        'integrated_catalog_change': 'documentation only; acquisition implementation unchanged',
        'files': files}, indent=2, sort_keys=True)+'\n', encoding='utf-8')
    archive = args.destination/(stage.name+'.zip')
    with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_DEFLATED) as z:
        for p in sorted(stage.rglob('*')):
            if p.is_file(): z.write(p, stage.name+'/'+p.relative_to(stage).as_posix())
    print(json.dumps({'artifact': str(archive), 'stage': str(stage), 'source': source,
        'tree': git(repo, 'rev-parse', 'HEAD^{tree}'), 'bytes': archive.stat().st_size,
        'sha256': hashlib.sha256(archive.read_bytes()).hexdigest()}, indent=2))


if __name__ == '__main__': main()
