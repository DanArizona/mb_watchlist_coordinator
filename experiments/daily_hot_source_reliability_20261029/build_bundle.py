"""Build the focused offline packet from clean, committed source trees."""
import argparse
import hashlib
import json
import subprocess
import zipfile
from pathlib import Path

BASE_TREE='961fe24daf7e6ee5dc541d69369615d197532b5f'
NATIVE='5552c5db43351d1a9ae8d376196cc99ba9c7f05d'
CHANGED=['src/mb_watchlist_coordinator/daily_operating_worker.py',
    'src/mb_watchlist_coordinator/daily_source.py',
    'src/mb_watchlist_coordinator/nasdaq_recovery_supervisor.py',
    'src/mb_watchlist_coordinator/sampling_service.py']


def git(root,*args):
    return subprocess.check_output(['git','-C',str(root),*args]).decode().strip()


def committed(root,name):
    return subprocess.check_output(['git','-C',str(root),'show','HEAD:'+name])


def sources(root,prefix,destination):
    for name in git(root,'ls-files',prefix).splitlines():
        if '__pycache__' in Path(name).parts or name.endswith(('.pyc','.pyo')):
            raise ValueError('Bytecode refused')
        target=destination/name
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(committed(root,name))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--market-data-root',type=Path,required=True)
    parser.add_argument('--destination',type=Path,required=True)
    args=parser.parse_args()
    repo=Path(__file__).resolve().parents[2]
    md=args.market_data_root.resolve()
    for root in (repo,md):
        if git(root,'status','--porcelain','--untracked-files=no'):
            raise ValueError('Clean committed source required')
    changed=git(repo,'diff','--name-only',BASE_TREE,'HEAD','--','src').splitlines()
    if changed!=CHANGED:
        raise ValueError('Unexpected runtime changes outside the focused reliability scope')
    if git(md,'rev-parse','HEAD')!=NATIVE:
        raise ValueError('Native source changed; prior component evidence cannot be reused')
    subprocess.check_call(['git','-C',str(md),'merge-base','--is-ancestor',
        '6b53ab1d12e4e1fdaf4deb1d70b717e13570358c','HEAD'])
    source={'coordinator_commit':git(repo,'rev-parse','HEAD'),
        'market_data_commit':NATIVE,
        'production_native_baseline':'6b53ab1d12e4e1fdaf4deb1d70b717e13570358c'}
    name='daily_hot_source_reliability_20261029_'+source['coordinator_commit'][:7]+'_5552c5d'
    args.destination.mkdir(parents=True,exist_ok=True)
    stage=args.destination/name
    stage.mkdir(exist_ok=False)
    sources(repo,'src',stage/'coordinator')
    sources(repo,'tests',stage/'coordinator')
    sources(md,'src',stage/'market_data')
    # Existing process fixtures also resolve this legacy relative native path.
    sources(md,'src',stage/'coordinator/experiments/sampling_promotion_20261016/market_data')
    prefix='experiments/daily_hot_source_reliability_20261029/'
    for filename in ('run.py','README.md','67_verify_daily_hot_source_reliability.cmd',
            'LOCAL_QUALIFICATION.json'):
        raw=committed(repo,prefix+filename)
        if filename.endswith('.cmd'):
            raw=raw.replace(b'\r\n',b'\n').replace(b'\n',b'\r\n')
        (stage/filename).write_bytes(raw)
    (stage/'REUSED_WINDOWS_COMPONENTS.json').write_bytes(committed(repo,
        'experiments/daily_hot_operating_20261028/validation/windows_3c0f8cd_review.json'))
    files={p.relative_to(stage).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(stage.rglob('*')) if p.is_file()}
    (stage/'SOURCE_INVENTORY.json').write_text(json.dumps({
        'contract':'daily-hot-source-reliability-source-v1',
        'source':source,'runtime_changes':changed,'files':files},indent=2,sort_keys=True)+'\n')
    archive=args.destination/(name+'.zip')
    with zipfile.ZipFile(archive,'x',compression=zipfile.ZIP_DEFLATED) as output:
        for p in sorted(stage.rglob('*')):
            if p.is_file():output.write(p,str(Path(name)/p.relative_to(stage)))
    print(json.dumps({'artifact':str(archive),'stage':str(stage),'source':source,
        'coordinator_tree':git(repo,'rev-parse','HEAD^{tree}'),
        'files':len(files)+1,'bytes':archive.stat().st_size,
        'sha256':hashlib.sha256(archive.read_bytes()).hexdigest()},indent=2))


if __name__=='__main__':main()
