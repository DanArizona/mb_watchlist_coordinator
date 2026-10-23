"""Explicit offline verification followed by one installed-client quote probe."""
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import uuid
import zipfile

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent

def build(destination):
    destination=Path(destination);destination.mkdir(parents=True,exist_ok=True)
    name='installed_client_probe_'+datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:6]
    with tempfile.TemporaryDirectory(prefix='installed client source bundle ') as temporary:
        root=Path(temporary)/name;root.mkdir()
        for source in (ROOT/'src',ROOT/'experiments/authenticated_startup_20261023/reference_mb_tools'):
            shutil.copytree(source,root/'coordinator'/source.relative_to(ROOT),ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        sources=[ROOT/'tests'/name for name in ('test_authenticated_startup.py','test_installed_startup_probe.py','test_installed_probe_launcher.py')]
        sources += [ROOT/'tests/fixtures/installed_probe_worker.py']
        sources += [HERE/name for name in ('verify.py','probe.py','launcher.py','expected_mb_tools.json')]
        for source in sources:
            target=root/'coordinator'/source.relative_to(ROOT);target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
        shutil.copyfile(HERE/'README.md',root/'README.md')
        shutil.copyfile(HERE/'launcher.py',root/'launch.py')
        (root/'39_verify_installed_probe.cmd').write_bytes(b'@echo off\r\nsetlocal\r\npython -I -B "%~dp0launch.py" offline\r\nexit /b %errorlevel%\r\n')
        (root/'40_check_installed_client.cmd').write_bytes(b'@echo off\r\nsetlocal\r\nif "%~1"=="" (\r\n  echo Usage: 40_check_installed_client.cmd "absolute-path-to-secure_schwabdev.ecfg"\r\n  exit /b 64\r\n)\r\npython -I -B "%~dp0launch.py" installed "%~1"\r\nexit /b %errorlevel%\r\n')
        files={p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob('*')) if p.is_file()}
        (root/'SOURCE_INVENTORY.json').write_text(json.dumps({'contract':'installed-client-probe-handoff-v1','files':files},indent=2)+'\n')
        archive=destination/(name+'.zip')
        with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as out:
            for p in sorted(root.rglob('*')):
                if p.is_file():out.write(p,name+'/'+p.relative_to(root).as_posix())
    return {'archive':str(archive.resolve()),'folder':name,'bytes':archive.stat().st_size,
        'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'files':len(files)+1}

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--destination',type=Path,required=True)
    print(json.dumps(build(parser.parse_args().destination),indent=2))
