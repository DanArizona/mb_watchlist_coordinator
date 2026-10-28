"""Create an immutable packet from committed Coordinator and native source."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args]).decode().strip()


def copy_tracked(root, prefix, destination):
    for name in git(root, 'ls-files', prefix).splitlines():
        if name.endswith(('.pyc', '.pyo')) or '__pycache__' in Path(name).parts:
            raise ValueError('Tracked bytecode refused')
        target = destination/name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(subprocess.check_output(['git', '-C', str(root), 'show', 'HEAD:'+name]))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--market-data-root', type=Path, required=True)
    parser.add_argument('--destination', type=Path, required=True)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[2]
    md = args.market_data_root.resolve()
    if git(repo, 'status', '--porcelain', '--untracked-files=no') or git(md, 'status', '--porcelain', '--untracked-files=no'):
        raise ValueError('Committed clean source required')
    source = {'coordinator_commit':git(repo,'rev-parse','HEAD'),
        'market_data_commit':git(md,'rev-parse','HEAD')}
    if source['market_data_commit'] != '6b53ab1d12e4e1fdaf4deb1d70b717e13570358c':
        raise ValueError('Native source must match the accepted installed cadence candidate')
    args.destination.mkdir(parents=True, exist_ok=True)
    name = 'daily_hot_session_20261028_'+source['coordinator_commit'][:7]
    stage = args.destination/name
    stage.mkdir(exist_ok=False)
    copy_tracked(repo,'src',stage/'coordinator')
    copy_tracked(repo,'tests',stage/'coordinator')
    copy_tracked(md,'src',stage/'market_data')
    packet = 'experiments/daily_hot_session_20261028/'
    for filename in ('run.py','README.md','60_verify_daily_hot_session.cmd'):
        raw = subprocess.check_output(['git','-C',str(repo),'show','HEAD:'+packet+filename])
        if filename.endswith('.cmd'): raw=raw.replace(b'\r\n',b'\n').replace(b'\n',b'\r\n')
        (stage/filename).write_bytes(raw)
    files = {p.relative_to(stage).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(stage.rglob('*')) if p.is_file()}
    manifest = {'contract':'daily-hot-session-source-inventory-v1','source':source,'files':files}
    (stage/'SOURCE_INVENTORY.json').write_text(json.dumps(manifest,sort_keys=True,indent=2)+'\n')
    archive = args.destination/(name+'.zip')
    with zipfile.ZipFile(archive,'x',compression=zipfile.ZIP_DEFLATED) as output:
        for path in sorted(stage.rglob('*')):
            if path.is_file(): output.write(path,str(Path(name)/path.relative_to(stage)))
    print(json.dumps({'artifact':str(archive),'stage':str(stage),'source':source,
        'files':len(files)+1,'bytes':archive.stat().st_size,
        'sha256':hashlib.sha256(archive.read_bytes()).hexdigest()},indent=2))


if __name__ == '__main__': main()
