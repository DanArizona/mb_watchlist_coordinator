"""Build the source-pinned offline Windows command-49 handoff."""
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
    name = 'profile_observer_'+datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:6]
    with tempfile.TemporaryDirectory(prefix='fresh controller source bundle ') as temp:
        root = Path(temp)/name; root.mkdir()
        for source in (ROOT/'src', ROOT/'experiments/sampling_promotion_20261016/market_data/src',
                ROOT/'experiments/authenticated_startup_20261023/reference_mb_tools'):
            shutil.copytree(source, root/'coordinator'/source.relative_to(ROOT),
                ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        tests = ('test_integrated_runtime', 'test_integrated_runtime_process', 'test_supervised_hot_worker',
            'test_authenticated_startup', 'test_authenticated_worker', 'test_hot_recovery_collector',
            'test_nasdaq_recovery_supervisor', 'test_nasdaq_feed_recovery', 'test_integrated_identity',
            'test_nasdaq_recovery_delivery', 'test_catalog_bootstrap', 'test_controller_bootstrap',
            'test_integrated_catalog', 'test_nasdaq_request_reuse', 'test_nasdaq_sampling',
            'runtime_fixtures', 'runtime_process_evidence', 'test_runtime_process_evidence',
            'resume_fixtures', 'resume_failure_evidence', 'test_controller_resume',
            'test_controller_resume_process', 'test_resume_entry', 'saved_artifact_scan', 'test_saved_artifact_scan',
            'test_outer_deadline', 'test_outer_harness', 'test_profile_evidence', 'test_profile_runtime', 'test_profile_observation', 'test_profile_observer_launcher')
        sources = [ROOT/'tests'/(n+'.py') for n in tests]
        sources += [ROOT/'tests/fixtures'/n for n in ('supervised_hot_worker_probe.py',
            'runtime_feed_worker.py', 'outer_scope_probe.py', 'outer_runtime_probe.py', 'outer_hot_worker_probe.py', 'controller_resume_probe.py', 'authenticated_worker_probe.py', 'recovery_collector_worker.py',
            'recovery_probe_worker.py', 'identity_gate_worker.py')]
        sources += [ROOT/'experiments/hot_collector_recovery_20261023/native_tests/test_sampling_acquisition.py',
            ROOT/'experiments/installed_startup_20261023/expected_mb_tools.json', HERE/'verify.py', HERE/'launcher.py', HERE/'command48_runtime_source_sha256.json']
        for source in sources:
            target = root/'coordinator'/source.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(source, target)
        shutil.copyfile(HERE/'launcher.py', root/'launch.py')
        shutil.copyfile(HERE/'README.md', root/'README.md')
        (root/'49_verify_profile_observer.cmd').write_bytes(
            b'@echo off\r\nsetlocal\r\npython -I -B "%~dp0launch.py"\r\nexit /b %errorlevel%\r\n')
        files = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob('*')) if p.is_file()}
        (root/'SOURCE_INVENTORY.json').write_text(json.dumps(
            {'contract': 'readonly-profile-observer-correction-offline-v1', 'files': files}, indent=2)+'\n')
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
