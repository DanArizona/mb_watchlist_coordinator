"""Immutable source-pinned offline packet from two clean committed worktrees."""
import argparse,hashlib,json,subprocess,zipfile
from pathlib import Path


def git(root,*args):return subprocess.check_output(['git','-C',str(root),*args]).decode().strip()


def sources(root,prefix,destination):
    for name in git(root,'ls-files',prefix).splitlines():
        if '__pycache__' in Path(name).parts or name.endswith(('.pyc','.pyo')):raise ValueError('Bytecode refused')
        target=destination/name;target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(subprocess.check_output(['git','-C',str(root),'show','HEAD:'+name]))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--market-data-root',type=Path,required=True)
    parser.add_argument('--destination',type=Path,required=True)
    args=parser.parse_args();repo=Path(__file__).resolve().parents[2];md=args.market_data_root.resolve()
    for root in (repo,md):
        if git(root,'status','--porcelain','--untracked-files=no'):raise ValueError('Clean committed source required')
    subprocess.check_call(['git','-C',str(md),'merge-base','--is-ancestor',
        '6b53ab1d12e4e1fdaf4deb1d70b717e13570358c','HEAD'])
    source={'coordinator_commit':git(repo,'rev-parse','HEAD'),'market_data_commit':git(md,'rev-parse','HEAD'),
        'production_native_baseline':'6b53ab1d12e4e1fdaf4deb1d70b717e13570358c'}
    name='daily_hot_collection_20261028_'+source['coordinator_commit'][:7]+'_'+source['market_data_commit'][:7]
    args.destination.mkdir(parents=True,exist_ok=True);stage=args.destination/name;stage.mkdir(exist_ok=False)
    sources(repo,'src',stage/'coordinator');sources(repo,'tests',stage/'coordinator')
    sources(md,'src',stage/'market_data')
    # Legacy process fixtures use this established relative native path. Both
    # copies contain exactly the same committed candidate bytes.
    sources(md,'src',stage/'coordinator/experiments/sampling_promotion_20261016/market_data')
    prefix='experiments/daily_hot_collection_20261028/'
    for filename in ('run.py','README.md','61_verify_daily_hot_collection.cmd'):
        raw=subprocess.check_output(['git','-C',str(repo),'show','HEAD:'+prefix+filename])
        if filename.endswith('.cmd'):raw=raw.replace(b'\r\n',b'\n').replace(b'\n',b'\r\n')
        (stage/filename).write_bytes(raw)
    files={p.relative_to(stage).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(stage.rglob('*')) if p.is_file()}
    (stage/'SOURCE_INVENTORY.json').write_text(json.dumps({'contract':'daily-hot-collection-source-v1',
        'source':source,'files':files},indent=2,sort_keys=True)+'\n')
    archive=args.destination/(name+'.zip')
    with zipfile.ZipFile(archive,'x',compression=zipfile.ZIP_DEFLATED) as output:
        for p in sorted(stage.rglob('*')):
            if p.is_file():output.write(p,str(Path(name)/p.relative_to(stage)))
    print(json.dumps({'artifact':str(archive),'stage':str(stage),'source':source,
        'files':len(files)+1,'bytes':archive.stat().st_size,'sha256':hashlib.sha256(archive.read_bytes()).hexdigest()},indent=2))


if __name__=='__main__':main()
