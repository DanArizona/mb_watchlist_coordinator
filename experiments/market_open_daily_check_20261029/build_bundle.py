"""Package the bounded daily composition and its focused offline checks."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile

BASE='ea43b37a06eac06313b662505b79a109fea3625e'
NATIVE='5552c5db43351d1a9ae8d376196cc99ba9c7f05d'
def git(root,*args):return subprocess.check_output(['git','-C',str(root),*args]).decode().strip()
def blob(root,path):return subprocess.check_output(['git','-C',str(root),'show','HEAD:'+path])
def sources(root,prefix,dest):
    for name in git(root,'ls-files',prefix).splitlines():
        if '__pycache__' in Path(name).parts or name.endswith(('.pyc','.pyo')):raise ValueError('Bytecode refused')
        p=dest/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(blob(root,name))

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--market-data-root',required=True,type=Path)
    parser.add_argument('--destination',required=True,type=Path);args=parser.parse_args()
    repo=Path(__file__).resolve().parents[2];native=args.market_data_root.resolve()
    for root in (repo,native):
        if git(root,'status','--porcelain','--untracked-files=no'):raise ValueError('Committed clean source required')
    if git(native,'rev-parse','HEAD')!=NATIVE:raise ValueError('Accepted native source required')
    changed=git(repo,'diff','--name-only',BASE,'HEAD','--','src').splitlines()
    expected=['src/mb_watchlist_coordinator/'+name+'.py' for name in
        ('daily_collector','daily_controller','daily_feed','daily_launch','daily_operating_review','market_open_check')]
    if changed!=expected:raise ValueError('Unexpected runtime change scope')
    source={'coordinator_commit':git(repo,'rev-parse','HEAD'),'market_data_commit':NATIVE,
        'accepted_after_hours_closeout_baseline':BASE,
        'production_native_baseline':'6b53ab1d12e4e1fdaf4deb1d70b717e13570358c'}
    name='market_open_daily_check_20261029_'+source['coordinator_commit'][:7]+'_5552c5d'
    args.destination.mkdir(parents=True,exist_ok=True);stage=args.destination/name;stage.mkdir(exist_ok=False)
    sources(repo,'src',stage/'coordinator');sources(repo,'tests',stage/'coordinator')
    sources(native,'src',stage/'market_data')
    for item in ('run.py','README.md','75_verify_market_open_daily_check.cmd',
            '76_prepare_market_open_daily_check.cmd','77_run_market_open_daily_check.cmd','market_open_check.cmd',
            'LOCAL_QUALIFICATION.json'):
        raw=blob(repo,'experiments/market_open_daily_check_20261029/'+item)
        if item=='README.md':raw=raw.replace(b'@@PACKET@@',name.encode())
        if item.endswith('.cmd'):raw=raw.replace(b'\r\n',b'\n').replace(b'\n',b'\r\n')
        (stage/item).write_bytes(raw)
    for label,path in (('WINDOWS71_ACCEPTANCE.json','daily_hot_windows_evidence_read_20261029/WINDOWS_ACCEPTANCE.json'),
            ('WINDOWS72_ACCEPTANCE.json','daily_hot_launch_20261029/WINDOWS_ACCEPTANCE.json'),
            ('AFTER_HOURS_ACCEPTANCE.json','after_hours_provider_20261029/WINDOWS_LIVE_ACCEPTANCE.json')):
        (stage/label).write_bytes(blob(repo,'experiments/'+path))
    files={p.relative_to(stage).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(stage.rglob('*')) if p.is_file()}
    (stage/'SOURCE_INVENTORY.json').write_text(json.dumps({'contract':'market-open-daily-path-source-v1',
        'source':source,'runtime_changes':changed,'native_source_changed':False,'files':files},indent=2,sort_keys=True)+'\n')
    archive=args.destination/(name+'.zip')
    with zipfile.ZipFile(archive,'x',compression=zipfile.ZIP_DEFLATED) as z:
        for path in sorted(stage.rglob('*')):
            if path.is_file():z.write(path,stage.name+'/'+path.relative_to(stage).as_posix())
    print(json.dumps({'artifact':str(archive),'stage':str(stage),'source':source,
        'tree':git(repo,'rev-parse','HEAD^{tree}'),'bytes':archive.stat().st_size,
        'sha256':hashlib.sha256(archive.read_bytes()).hexdigest()},indent=2))

if __name__=='__main__':main()
