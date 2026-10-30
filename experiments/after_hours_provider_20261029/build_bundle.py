"""Deliver only the new off-hours profile and its focused qualification."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile

NATIVE = '5552c5db43351d1a9ae8d376196cc99ba9c7f05d'
BASE = 'cc8a4b3cd9c292a8a6daf4bcf16324cfa178d9f3'
def git(root, *args): return subprocess.check_output(['git', '-C', str(root), *args]).decode().strip()
def blob(root, path): return subprocess.check_output(['git', '-C', str(root), 'show', 'HEAD:'+path])
def sources(root, prefix, dest):
    for name in git(root, 'ls-files', prefix).splitlines():
        if '__pycache__' in Path(name).parts or name.endswith(('.pyc', '.pyo')): raise ValueError('Bytecode refused')
        p = dest/name; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(blob(root, name))

def main():
    p = argparse.ArgumentParser(); p.add_argument('--market-data-root', type=Path, required=True)
    p.add_argument('--destination', type=Path, required=True); args = p.parse_args()
    repo = Path(__file__).resolve().parents[2]; native = args.market_data_root.resolve()
    for root in (repo, native):
        if git(root, 'status', '--porcelain', '--untracked-files=no'): raise ValueError('Clean committed source required')
    if git(native, 'rev-parse', 'HEAD') != NATIVE: raise ValueError('Accepted native source required')
    changed = git(repo, 'diff', '--name-only', BASE, 'HEAD', '--', 'src').splitlines()
    if changed != ['src/mb_watchlist_coordinator/after_hours_entry.py', 'src/mb_watchlist_coordinator/after_hours_profile.py']:
        raise ValueError('Daily/production source changes are excluded')
    source = {'coordinator_commit': git(repo, 'rev-parse', 'HEAD'), 'market_data_commit': NATIVE,
        'accepted_daily_launch_baseline': BASE, 'production_native_baseline': '6b53ab1d12e4e1fdaf4deb1d70b717e13570358c'}
    name = 'after_hours_provider_20261029_'+source['coordinator_commit'][:7]+'_5552c5d'
    args.destination.mkdir(parents=True, exist_ok=True); stage = args.destination/name; stage.mkdir(exist_ok=False)
    sources(repo, 'src', stage/'coordinator'); sources(native, 'src', stage/'market_data')
    for path in ('tests/test_after_hours_profile.py', 'tests/fixtures/after_hours_process.py'):
        dest = stage/'coordinator'/path; dest.parent.mkdir(parents=True, exist_ok=True); dest.write_bytes(blob(repo, path))
    for name in ('run.py', 'README.md', 'LOCAL_QUALIFICATION.json', '73_verify_after_hours_provider.cmd', '74_run_after_hours_provider.cmd'):
        raw = blob(repo, 'experiments/after_hours_provider_20261029/'+name)
        if name.endswith('.cmd'): raw = raw.replace(b'\r\n', b'\n').replace(b'\n', b'\r\n')
        (stage/name).write_bytes(raw)
    for label, path in (('WINDOWS71_ACCEPTANCE.json', 'daily_hot_windows_evidence_read_20261029'),
            ('WINDOWS72_ACCEPTANCE.json', 'daily_hot_launch_20261029')):
        (stage/label).write_bytes(blob(repo, 'experiments/'+path+'/WINDOWS_ACCEPTANCE.json'))
    files = {p.relative_to(stage).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(stage.rglob('*')) if p.is_file()}
    (stage/'SOURCE_INVENTORY.json').write_text(json.dumps({'contract': 'after-hours-provider-source-v1',
        'source': source, 'runtime_changes': changed, 'production_and_daily_sources_changed': False, 'files': files}, indent=2, sort_keys=True)+'\n')
    archive = args.destination/(stage.name+'.zip')
    with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_DEFLATED) as z:
        for p in sorted(stage.rglob('*')):
            if p.is_file(): z.write(p, stage.name+'/'+p.relative_to(stage).as_posix())
    print(json.dumps({'artifact': str(archive), 'stage': str(stage), 'source': source,
        'tree': git(repo, 'rev-parse', 'HEAD^{tree}'), 'bytes': archive.stat().st_size,
        'sha256': hashlib.sha256(archive.read_bytes()).hexdigest()}, indent=2))

if __name__ == '__main__': main()
