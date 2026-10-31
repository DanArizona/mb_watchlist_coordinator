"""Build the isolated combined-controller Windows verification packet."""
import argparse,hashlib,json,subprocess,zipfile
from pathlib import Path

NATIVE='d37d2c37e3ac9cc2c860d0a2313a1526e30fd23e'
BASE='aa6deb13d2f3d34cf651b4ef96c4d41fc44d8a7a'
EXPERIMENT='experiments/manual_daily_controller_20261031'


def git(root,*args):return subprocess.check_output(['git','-C',str(root),*args]).decode().strip()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--market-data-root',type=Path,required=True)
    parser.add_argument('--destination',type=Path,required=True);args=parser.parse_args()
    repo=Path(__file__).resolve().parents[2];native=args.market_data_root.resolve()
    for root in(repo,native):
        if git(root,'status','--porcelain','--untracked-files=no'):raise ValueError('Committed source required')
    if git(native,'rev-parse','HEAD')!=NATIVE:raise ValueError('Pinned accepted native source required')
    args.destination.mkdir(parents=True,exist_ok=True);stage=args.destination/'p92';stage.mkdir(exist_ok=False)
    def copy(root,name,target):
        data=subprocess.check_output(['git','-C',str(root),'show','HEAD:'+name])
        if name.endswith('.cmd'):data=data.replace(b'\r\n',b'\n').replace(b'\n',b'\r\n')
        target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
    for root,folder,paths in((repo,'coordinator',('src','tests')),(native,'market_data',('src',))):
        for name in git(root,'ls-files',*paths).splitlines():
            if '__pycache__'in Path(name).parts or name.endswith(('.pyc','.pyo')):raise ValueError('Bytecode is not source')
            copy(root,name,stage/folder/name)
    for name in('run.py','README.md','92_verify_shared_manual_controller.cmd'):
        copy(repo,EXPERIMENT+'/'+name,stage/name)
    copy(repo,'experiments/manual_membership_20261031/run.py',stage/'manual_preview.py')
    filename='nasdaq_manual_controller_20261031_'+git(repo,'rev-parse','HEAD')[:7]+'.zip'
    readme=stage/'README.md';readme.write_bytes(readme.read_bytes().replace(b'@@ZIP@@',filename.encode()))
    manifest={'contract':'nasdaq-manual-daily-controller-source-v1','source':{
        'coordinator_commit':git(repo,'rev-parse','HEAD'),'coordinator_tree':git(repo,'rev-parse','HEAD^{tree}'),
        'manual_predecessor':BASE,'market_data_commit':NATIVE,
        'production_native_baseline':'6b53ab1d12e4e1fdaf4deb1d70b717e13570358c'},
        'changed_runtime_sources':git(repo,'diff','--name-only',BASE,'HEAD','--','src').splitlines(),
        'p85_source_settings_and_approval_changed':False,'production_launch_included':False,
        'files':{p.relative_to(stage).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in sorted(stage.rglob('*'))if p.is_file()}}
    (stage/'SOURCE_INVENTORY.json').write_text(json.dumps(manifest,indent=2,sort_keys=True)+'\n')
    archive=args.destination/filename
    with zipfile.ZipFile(archive,'x',compression=zipfile.ZIP_DEFLATED)as z:
        for p in sorted(stage.rglob('*')):
            if p.is_file():z.write(p,'p92/'+p.relative_to(stage).as_posix())
    print(json.dumps({'archive':str(archive),'bytes':archive.stat().st_size,'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),
        'stage':str(stage),'source':manifest['source']},indent=2))


if __name__=='__main__':main()
