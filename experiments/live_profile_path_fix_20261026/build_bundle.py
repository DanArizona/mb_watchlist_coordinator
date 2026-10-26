"""Immutable command54 corrective qualification and separate live launchers."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import uuid
import zipfile

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def build(destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    name = 'live_path_fix_'+datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:6]
    with tempfile.TemporaryDirectory(prefix='live-path-fix-') as temp:
        root = Path(temp)/name
        root.mkdir()
        for source in (ROOT/'src', ROOT/'tests', ROOT/'experiments/sampling_promotion_20261016/market_data/src',
                ROOT/'experiments/authenticated_startup_20261023/reference_mb_tools'):
            shutil.copytree(source, root/'coordinator'/source.relative_to(ROOT),
                ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        original = ROOT/'experiments/live_profile_entry_20261024'
        for source in (original/'verify.py', original/'launcher.py', original/'accepted_runtime_source_sha256.json',
                HERE/'verify.py', HERE/'launcher.py', HERE/'changed_runtime_source_sha256.json'):
            target = root/'coordinator'/source.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        shutil.copyfile(HERE/'launcher.py', root/'launch.py')
        shutil.copyfile(HERE/'README.md', root/'README.md')
        for filename, mode in {
            '54_verify_live_profile_path_fix.cmd': 'verify',
            '51_run_ordinary_live_profile.cmd': 'ordinary',
            '52_run_recovery_live_profile.cmd': 'recovery',
            '53_stop_live_profile.cmd': 'stop',
        }.items():
            (root/filename).write_bytes(('@echo off\r\nsetlocal\r\npython -I -B "%~dp0launch.py" '
                +mode+' %*\r\nexit /b %errorlevel%\r\n').encode())
        files = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob('*')) if p.is_file()}
        inventory = root/'SOURCE_INVENTORY.json'
        inventory.write_text(json.dumps({'contract': 'credential-bound-live-hot-profile-v1', 'files': files}, indent=2)+'\n')
        archive = destination/(name+'.zip')
        with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as out:
            for path in sorted(root.rglob('*')):
                if path.is_file():
                    out.write(path, name+'/'+path.relative_to(root).as_posix())
        inventory_sha = hashlib.sha256(inventory.read_bytes()).hexdigest()
    return {'archive': str(archive.resolve()), 'folder': name, 'bytes': archive.stat().st_size,
        'sha256': hashlib.sha256(archive.read_bytes()).hexdigest(), 'files': len(files)+1,
        'inventory_sha256': inventory_sha}


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--destination', type=Path, required=True)
    print(json.dumps(build(parser.parse_args().destination), indent=2))
