"""Build a small qualification-only follow-up; p85 runtime stays frozen."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile

EXPERIMENT = 'experiments/daily_hot_multisymbol_boundary_20261031'


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args]).decode().strip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--destination', required=True, type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    if git(root, 'status', '--porcelain', '--untracked-files=no'):
        raise ValueError('Committed clean source required')
    if git(root, 'diff', '--name-only', 'e7cb9b6fa786170455dbfe7c3226d8b18227487e', 'HEAD', '--', 'src'):
        raise ValueError('Qualification-only follow-up may not change runtime')
    stage = args.destination/'p87'
    stage.mkdir(parents=True, exist_ok=False)
    sources = {name: EXPERIMENT+'/'+name for name in
        ('complete.py', 'README.md', '87_complete_multisymbol_qualification.cmd')}
    for name in ('multisymbol_closed_checks.py', 'test_multisymbol_closed_checks.py',
                 'test_daily_source_stop_boundary.py', 'test_multisymbol_completion.py'):
        sources[name] = 'tests/'+name
    for name, original in sources.items():
        value = subprocess.check_output(['git', '-C', str(root), 'show', 'HEAD:'+original])
        if name.endswith('.cmd'): value = value.replace(b'\r\n', b'\n').replace(b'\n', b'\r\n')
        (stage/name).write_bytes(value)
    files = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(stage.iterdir())}
    source = {'coordinator_commit': git(root, 'rev-parse', 'HEAD'),
        'frozen_runtime_commit': 'e7cb9b6fa786170455dbfe7c3226d8b18227487e',
        'frozen_inventory_sha256': '0c5f9d7a2dfcdd72ffc9d3d07b7ea2e4b9528139a948496e4fd921476fdf6ffe',
        'runtime_changed': False}
    (stage/'SOURCE_INVENTORY.json').write_text(json.dumps({'contract':
        'multisymbol-stop-boundary-completion-source-v1', 'source': source, 'files': files}, indent=2, sort_keys=True)+'\n')
    archive = args.destination/('hot_multisymbol_completion_20261031_'+source['coordinator_commit'][:7]+'.zip')
    with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_DEFLATED) as z:
        for path in sorted(stage.iterdir()): z.write(path, 'p87/'+path.name)
    print(json.dumps({'archive': str(archive), 'stage': str(stage), 'source': source,
        'bytes': archive.stat().st_size, 'sha256': hashlib.sha256(archive.read_bytes()).hexdigest()}, indent=2))


if __name__ == '__main__': main()
