"""Package the exact focused source fix with unchanged candidate native source."""
import argparse,hashlib,json,subprocess,zipfile
from pathlib import Path

BASE='2f56703904db10cf6c47e410f350f60cfa03656f'
NATIVE='5552c5db43351d1a9ae8d376196cc99ba9c7f05d'
CHANGED=['src/mb_watchlist_coordinator/daily_session.py',
    'src/mb_watchlist_coordinator/daily_supervision.py',
    'src/mb_watchlist_coordinator/daily_worker_view.py',
    'src/mb_watchlist_coordinator/recovery_workers.py']


def git(root,*args):return subprocess.check_output(['git','-C',str(root),*args]).decode().strip()
def committed(root,name):return subprocess.check_output(['git','-C',str(root),'show','HEAD:'+name])


def sources(root,prefix,destination):
    for name in git(root,'ls-files',prefix).splitlines():
        if '__pycache__' in Path(name).parts or name.endswith(('.pyc','.pyo')):raise ValueError('Bytecode refused')
        target=destination/name;target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(committed(root,name))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--market-data-root',type=Path,required=True)
    parser.add_argument('--destination',type=Path,required=True);args=parser.parse_args()
    repo=Path(__file__).resolve().parents[2];md=args.market_data_root.resolve()
    for root in (repo,md):
        if git(root,'status','--porcelain','--untracked-files=no'):raise ValueError('Clean committed source required')
    changed=git(repo,'diff','--name-only',BASE,'HEAD','--','src').splitlines()
    if changed!=CHANGED or git(md,'rev-parse','HEAD')!=NATIVE:raise ValueError('Unexpected source scope')
    source={'coordinator_commit':git(repo,'rev-parse','HEAD'),'market_data_commit':NATIVE,
        'production_native_baseline':'6b53ab1d12e4e1fdaf4deb1d70b717e13570358c'}
    name='daily_hot_evidence_read_20261029_'+source['coordinator_commit'][:7]+'_5552c5d'
    args.destination.mkdir(parents=True,exist_ok=True);stage=args.destination/name;stage.mkdir(exist_ok=False)
    sources(repo,'src',stage/'coordinator');sources(repo,'tests',stage/'coordinator')
    sources(md,'src',stage/'market_data')
    sources(md,'src',stage/'coordinator/experiments/sampling_promotion_20261016/market_data')
    prefix='experiments/daily_hot_windows_evidence_read_20261029/'
    for name in ('run.py','README.md','71_verify_windows_evidence_read.cmd','LOCAL_QUALIFICATION.json'):
        raw=committed(repo,prefix+name)
        if name.endswith('.cmd'):raw=raw.replace(b'\r\n',b'\n').replace(b'\n',b'\r\n')
        (stage/name).write_bytes(raw)
    diagnostics=stage/'diagnostics';diagnostics.mkdir()
    prior='experiments/daily_hot_source_reliability_20261029/'
    for name in ('trace_control.py','observe_operating.py','operating_exception_observer.py','monitor_observer_child.py'):
        (diagnostics/name).write_bytes(committed(repo,prior+name))
    files={p.relative_to(stage).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(stage.rglob('*')) if p.is_file()}
    (stage/'SOURCE_INVENTORY.json').write_text(json.dumps({'contract':'daily-hot-windows-evidence-read-source-v1',
        'source':source,'runtime_baseline':BASE,'runtime_changes':changed,'files':files},indent=2,sort_keys=True)+'\n')
    archive=args.destination/(stage.name+'.zip')
    with zipfile.ZipFile(archive,'x',compression=zipfile.ZIP_DEFLATED) as z:
        for p in sorted(stage.rglob('*')):
            if p.is_file():z.write(p,stage.name+'/'+p.relative_to(stage).as_posix())
    print(json.dumps({'artifact':str(archive),'stage':str(stage),'source':source,
        'coordinator_tree':git(repo,'rev-parse','HEAD^{tree}'),'bytes':archive.stat().st_size,
        'sha256':hashlib.sha256(archive.read_bytes()).hexdigest()},indent=2))


if __name__=='__main__':main()
