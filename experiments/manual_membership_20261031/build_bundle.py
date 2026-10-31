"""Build the separate short-path manual-controls qualification/preview packet."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile

BASE='87565fb23099db9bf2e470fc748ed634782f86a1'
NATIVE='d37d2c37e3ac9cc2c860d0a2313a1526e30fd23e'
EXPERIMENT='experiments/manual_membership_20261031'
ADDED=['src/mb_watchlist_coordinator/manual_membership.py','src/mb_watchlist_coordinator/manual_membership_window.py']


def git(root,*args):
    return subprocess.check_output(['git','-C',str(root),*args]).decode().strip()


def blob(root,name):
    return subprocess.check_output(['git','-C',str(root),'show','HEAD:'+name])


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--market-data-root',required=True,type=Path)
    parser.add_argument('--destination',required=True,type=Path)
    parser.add_argument('--preview15',action='store_true'); args=parser.parse_args()
    repo=Path(__file__).resolve().parents[2]; native=args.market_data_root.resolve()
    for root in (repo,native):
        if git(root,'status','--porcelain','--untracked-files=no'): raise ValueError('Committed source required')
    if git(native,'rev-parse','HEAD')!=NATIVE: raise ValueError('Pinned accepted native source required')
    if git(repo,'diff','--name-only',BASE,'HEAD','--','src').splitlines()!=ADDED:
        raise ValueError('Only independent manual adapter/window may change runtime source')
    old={name:subprocess.check_output(['git','-C',str(repo),'show',BASE+':'+name])
         for name in git(repo,'ls-tree','-r','--name-only',BASE,'src').splitlines()}
    if any(blob(repo,name)!=data for name,data in old.items()): raise ValueError('An existing runtime source changed')
    stage_name='p91' if args.preview15 else 'p89'
    args.destination.mkdir(parents=True,exist_ok=True); stage=args.destination/stage_name; stage.mkdir(exist_ok=False)
    def copy(root,name,destination):
        data=blob(root,name)
        if name.endswith('.cmd'): data=data.replace(b'\r\n',b'\n').replace(b'\n',b'\r\n')
        destination.parent.mkdir(parents=True,exist_ok=True); destination.write_bytes(data)
    for root,prefix in ((repo,'coordinator'),(native,'market_data')):
        for name in git(root,'ls-files','src').splitlines():
            if '__pycache__' in Path(name).parts or name.endswith(('.pyc','.pyo')): raise ValueError('Bytecode is not source')
            copy(root,name,stage/prefix/name)
    for name in ('manual_membership_fixture.py','test_manual_membership.py','test_manual_membership_window.py'):
        copy(repo,'tests/'+name,stage/'coordinator/tests'/name)
    for name in ('run.py','README.md','89_verify_manual_membership.cmd','90_preview_manual_membership.cmd','91_preview_manual_membership_15_seconds.cmd'):
        copy(repo,EXPERIMENT+'/'+name,stage/name)
    filename=('manual_membership_preview15_20261031_' if args.preview15 else 'manual_membership_20261031_')+git(repo,'rev-parse','HEAD')[:7]+'.zip'
    readme=stage/'README.md'; readme.write_bytes(readme.read_bytes().replace(b'@@ZIP@@',filename.encode()))
    manifest={'contract':'manual-membership-candidate-source-v1','source':{
        'coordinator_commit':git(repo,'rev-parse','HEAD'),'coordinator_tree':git(repo,'rev-parse','HEAD^{tree}'),
        'accepted_operating_predecessor':BASE,'market_data_commit':NATIVE,
        'production_native_baseline':'6b53ab1d12e4e1fdaf4deb1d70b717e13570358c'},
        'new_runtime_sources':ADDED,'existing_runtime_source_files_unchanged':len(old),
        'production_or_p85_changed':False,'files':{p.relative_to(stage).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(stage.rglob('*')) if p.is_file()}}
    (stage/'SOURCE_INVENTORY.json').write_text(json.dumps(manifest,indent=2,sort_keys=True)+'\n')
    archive=args.destination/filename
    with zipfile.ZipFile(archive,'x',compression=zipfile.ZIP_DEFLATED) as z:
        for p in sorted(stage.rglob('*')):
            if p.is_file(): z.write(p,stage_name+'/'+p.relative_to(stage).as_posix())
    print(json.dumps({'archive':str(archive),'stage':str(stage),'bytes':archive.stat().st_size,
        'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'source':manifest['source'],
        'existing_runtime_source_files_unchanged':len(old)},indent=2))


if __name__=='__main__': main()
