"""Immutable command56 recovery qualification and separate live profiles."""
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import uuid
import zipfile

ROOT=Path(__file__).resolve().parents[2];HERE=Path(__file__).resolve().parent

def build(destination, *, proof_snapshot=None):
    destination=Path(destination);destination.mkdir(parents=True,exist_ok=True)
    name='live_recovery_'+datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:6]
    with tempfile.TemporaryDirectory(prefix='hot-boundary-') as temp:
        root=Path(temp)/name;root.mkdir()
        for source in (ROOT/'src',ROOT/'tests',ROOT/'experiments/sampling_promotion_20261016/market_data/src',
                ROOT/'experiments/authenticated_startup_20261023/reference_mb_tools'):
            shutil.copytree(source,root/'coordinator'/source.relative_to(ROOT),ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        for dirname,files in (
            ('live_profile_entry_20261024',('verify.py','launcher.py','accepted_runtime_source_sha256.json')),
            ('live_profile_path_fix_20261026',('verify.py','launcher.py','changed_runtime_source_sha256.json')),
            ('live_profile_boundary_20261026',('verify.py','launcher.py','accepted_before_boundary_sha256.json','changed_runtime_source_sha256.json')),
            ('live_profile_recovery_fix_20261026',('verify.py','launcher.py','accepted_before_recovery_sha256.json','changed_runtime_source_sha256.json'))):
            for filename in files:
                source=ROOT/'experiments'/dirname/filename;target=root/'coordinator'/source.relative_to(ROOT)
                target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
        shutil.copyfile(HERE/'launcher.py',root/'launch.py');shutil.copyfile(HERE/'README.md',root/'README.md')
        if proof_snapshot is not None:
            proof_snapshot=Path(proof_snapshot)
            snapshot=json.loads((HERE/'validation/elapsed_recovery/snapshot.json').read_text())
            proof=json.loads((HERE/'validation/elapsed_recovery/evidence.json').read_text())
            if (hashlib.sha256(proof_snapshot.read_bytes()).hexdigest()!=snapshot['sha256']
                    or proof['result']!='PASS' or any(hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=sha
                        for name,sha in proof['source_sha256'].items())):
                raise ValueError('Elapsed proof does not match the reviewed source/snapshot')
            evidence=root/'offline_evidence';evidence.mkdir()
            shutil.copyfile(proof_snapshot,evidence/'elapsed_recovery_native_snapshot.zip')
        for filename,mode in {'56_verify_live_recovery_fix.cmd':'verify','51_run_ordinary_live_profile.cmd':'ordinary',
                '52_run_recovery_live_profile.cmd':'recovery','53_stop_live_profile.cmd':'stop'}.items():
            (root/filename).write_bytes(('@echo off\r\nsetlocal\r\npython -I -B "%~dp0launch.py" '+mode+' %*\r\nexit /b %errorlevel%\r\n').encode())
        files={p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob('*')) if p.is_file()}
        inventory=root/'SOURCE_INVENTORY.json';inventory.write_text(json.dumps({'contract':'credential-bound-live-hot-profile-v1','files':files},indent=2)+'\n')
        archive=destination/(name+'.zip')
        with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as out:
            for path in sorted(root.rglob('*')):
                if path.is_file():out.write(path,name+'/'+path.relative_to(root).as_posix())
        inventory_sha=hashlib.sha256(inventory.read_bytes()).hexdigest()
    return {'archive':str(archive.resolve()),'folder':name,'bytes':archive.stat().st_size,
        'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'files':len(files)+1,'inventory_sha256':inventory_sha}

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--destination',type=Path,required=True)
    p.add_argument('--proof-snapshot',type=Path)
    args=p.parse_args()
    print(json.dumps(build(args.destination,proof_snapshot=args.proof_snapshot),indent=2))
