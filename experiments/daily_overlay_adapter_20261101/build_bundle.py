"""Package a read-only Overlay without changing any approved operating release."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile

CO_BASE='9d5ac24d1f18aa54b8a2161fbaa787ed523d2d1c'
MD_BASE='d37d2c37e3ac9cc2c860d0a2313a1526e30fd23e'
EXPERIMENT='experiments/daily_overlay_adapter_20261101'


def git(root,*args):return subprocess.check_output(['git','-C',str(root),*args]).decode().strip()


def main():
    p=argparse.ArgumentParser();p.add_argument('--market-data-root',type=Path,required=True)
    p.add_argument('--destination',type=Path,required=True);a=p.parse_args()
    co=Path(__file__).resolve().parents[2];md=a.market_data_root.resolve()
    for root in (co,md):
        if git(root,'status','--porcelain','--untracked-files=no'):raise ValueError('Committed clean source required')
    expected_co=['src/mb_watchlist_coordinator/daily_overlay.py','src/mb_watchlist_coordinator/daily_overlay_cli.py','src/mb_watchlist_coordinator/daily_overlay_view.py']
    expected_md=['src/mb_market_data/observation_overlay.py','src/mb_market_data/observation_overlay_view.py']
    if git(co,'diff','--name-only',CO_BASE,'HEAD','--','src').splitlines()!=expected_co:raise ValueError('Only new read-only adapter modules permitted')
    if git(md,'diff','--name-only',MD_BASE,'HEAD','--','src').splitlines()!=expected_md:raise ValueError('Only cache-optional/carryover chart adaptation permitted')
    stage=a.destination.resolve()/'p96';stage.mkdir(parents=True,exist_ok=False)
    def copy(root,name,destination):
        data=subprocess.check_output(['git','-C',str(root),'show','HEAD:'+name])
        if name.endswith('.cmd'):data=data.replace(b'\r\n',b'\n').replace(b'\n',b'\r\n')
        destination.parent.mkdir(parents=True,exist_ok=True);destination.write_bytes(data)
    for root,prefix in ((co,'coordinator'),(md,'market_data')):
        for name in git(root,'ls-files','src','tests').splitlines():
            if '__pycache__' in Path(name).parts or name.endswith(('.pyc','.pyo')):raise ValueError('No bytecode')
            copy(root,name,stage/prefix/name)
    for name in ('run.py','README.md','96_verify_overlay_adapter.cmd','97_preview_overlay_adapter.cmd','98_overlay_adapter.cmd'):
        copy(co,EXPERIMENT+'/'+name,stage/name)
    source={'coordinator_commit':git(co,'rev-parse','HEAD'),'coordinator_tree':git(co,'rev-parse','HEAD^{tree}'),
        'accepted_manual_delivery_base':CO_BASE,'market_data_commit':git(md,'rev-parse','HEAD'),
        'market_data_tree':git(md,'rev-parse','HEAD^{tree}'),'accepted_native_base':MD_BASE,
        'production_native_baseline':'6b53ab1d12e4e1fdaf4deb1d70b717e13570358c'}
    filename='daily_overlay_adapter_20261101_'+source['coordinator_commit'][:7]+'.zip'
    path=stage/'README.md';path.write_bytes(path.read_bytes().replace(b'@@ZIP@@',filename.encode()))
    manifest={'contract':'daily-readonly-overlay-source-v1','source':source,'expected_tests':97,
        'coordinator_runtime_changes':expected_co,'native_runtime_changes':expected_md,
        'controller_collector_policy_and_approved_packets_changed':False,
        'files':{p.relative_to(stage).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(stage.rglob('*')) if p.is_file()}}
    (stage/'SOURCE_INVENTORY.json').write_text(json.dumps(manifest,indent=2,sort_keys=True)+'\n')
    archive=a.destination.resolve()/filename
    with zipfile.ZipFile(archive,'x',compression=zipfile.ZIP_DEFLATED) as z:
        for path in sorted(stage.rglob('*')):
            if path.is_file():z.write(path,'p96/'+path.relative_to(stage).as_posix())
    print(json.dumps({'archive':str(archive),'bytes':archive.stat().st_size,
        'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'stage':str(stage),'source':source},indent=2))


if __name__=='__main__':main()
