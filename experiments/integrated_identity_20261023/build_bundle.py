"""Build the source-pinned offline Windows command-42 handoff."""
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
    destination = Path(destination); destination.mkdir(parents=True, exist_ok=True)
    name = 'integrated_identity_'+datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:6]
    with tempfile.TemporaryDirectory(prefix='fresh controller source bundle ') as temp:
        root = Path(temp)/name; root.mkdir()
        for source in (ROOT/'src', ROOT/'experiments/sampling_promotion_20261016/market_data/src',
                ROOT/'experiments/authenticated_startup_20261023/reference_mb_tools'):
            shutil.copytree(source, root/'coordinator'/source.relative_to(ROOT),
                ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        sources = [ROOT/'tests'/n for n in ('test_integrated_catalog.py',
            'test_integrated_identity.py', 'test_nasdaq_recovery_delivery.py',
            'test_nasdaq_request_reuse.py', 'test_nasdaq_sampling.py',
            'test_sampling_admission.py', 'test_sampling_requests.py', 'test_controller_bootstrap.py')]
        sources += [ROOT/'tests/fixtures/identity_gate_worker.py',
            ROOT/'experiments/installed_startup_20261023/expected_mb_tools.json', HERE/'verify.py']
        for source in sources:
            target = root/'coordinator'/source.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(source, target)
        shutil.copyfile(HERE/'launcher.py', root/'launch.py')
        shutil.copyfile(HERE/'README.md', root/'README.md')
        (root/'42_verify_integrated_identity.cmd').write_bytes(
            b'@echo off\r\nsetlocal\r\npython -I -B "%~dp0launch.py"\r\nexit /b %errorlevel%\r\n')
        files = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob('*')) if p.is_file()}
        (root/'SOURCE_INVENTORY.json').write_text(json.dumps(
            {'contract': 'integrated-catalog-identity-offline-handoff-v1', 'files': files}, indent=2)+'\n')
        archive = destination/(name+'.zip')
        with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as out:
            for p in sorted(root.rglob('*')):
                if p.is_file(): out.write(p, name+'/'+p.relative_to(root).as_posix())
    return {'archive': str(archive.resolve()), 'folder': name, 'bytes': archive.stat().st_size,
        'sha256': hashlib.sha256(archive.read_bytes()).hexdigest(), 'files': len(files)+1}


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser(); p.add_argument('--destination', type=Path, required=True)
    print(json.dumps(build(p.parse_args().destination), indent=2))
