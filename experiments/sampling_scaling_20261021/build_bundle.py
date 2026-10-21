"""Create a unique offline-only Windows qualification package from committed source."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tempfile
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = '0417b345e2725f4e1e184d3b3202bedb846dbfca'
TESTS = ('sampling_scaling', 'sampling_requests', 'sampling_policy', 'sampling_admission',
         'sampling_service', 'nasdaq_sampling')


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output-root', type=Path, required=True)
    parser.add_argument('--published-commit')
    args = parser.parse_args()
    if git('status', '--porcelain').strip():
        parser.error('Commit the reviewed source before building')
    source_commit = git('rev-parse', 'HEAD').decode().strip()
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
    name = f'coordinator_scaling_{stamp}_{uuid.uuid4().hex[:6]}'
    args.output_root.mkdir(parents=True, exist_ok=True)
    archive = args.output_root/(name+'.zip')
    with tempfile.TemporaryDirectory(prefix='coordinator scaling build ') as temporary:
        root = Path(temporary)/name
        root.mkdir()
        def write(relative, body):
            path = root/relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(body)
        files = git('ls-tree', '-r', '--name-only', 'HEAD', 'src/mb_watchlist_coordinator').decode().splitlines()
        for path in files:
            if path.endswith('.py'):
                write(path, git('show', 'HEAD:'+path))
        baseline = git('ls-tree', '-r', '--name-only', BASE, 'src/mb_watchlist_coordinator').decode().splitlines()
        for path in baseline:
            if path.endswith('.py'):
                write('baseline_coordinator_src/'+path.removeprefix('src/'), git('show', BASE+':'+path))
        for test in TESTS:
            path = 'tests/test_'+test+'.py'
            write(path, git('show', 'HEAD:'+path))
        market = 'experiments/sampling_promotion_20261016/market_data/src'
        for path in git('ls-tree', '-r', '--name-only', 'HEAD', market).decode().splitlines():
            if path.endswith('.py'):
                write(path, git('show', 'HEAD:'+path))
        for suffix in ('qualify.py', 'README.md'):
            path = 'experiments/sampling_scaling_20261021/'+suffix
            write(path, git('show', 'HEAD:'+path))
        write('README.md', git('show', 'HEAD:experiments/sampling_scaling_20261021/README.md'))
        launcher = ('@echo off\r\nsetlocal\r\necho OFFLINE Coordinator scaling qualification. No API, password or production journal.\r\n'
            'python -I -B "%~dp0experiments\\sampling_scaling_20261021\\qualify.py"\r\nexit /b %ERRORLEVEL%\r\n')
        write('26_verify_coordinator_scaling.cmd', launcher.encode('ascii'))
        delivery = {'name': name, 'purpose': 'Offline Coordinator scaling qualification only',
            'baseline_commit': BASE, 'local_source_commit': source_commit,
            'source_tree': git('rev-parse', 'HEAD^{tree}').decode().strip(),
            'published_checkpoint_commit': args.published_commit, 'network': 'denied',
            'production_installation': False, 'live_provider_calls': False}
        write('DELIVERY.json', (json.dumps(delivery, indent=2)+'\n').encode())
        inventory = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                     for p in sorted(root.rglob('*')) if p.is_file()}
        write('SCALING_SOURCE_INVENTORY.json', (json.dumps({'files': inventory}, indent=2)+'\n').encode())
        with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
            for path in sorted(root.rglob('*')):
                if path.is_file():
                    z.write(path, path.relative_to(root.parent).as_posix())
        with zipfile.ZipFile(archive) as z:
            assert z.testzip() is None
            assert all(not p.startswith('/') and '..' not in Path(p).parts for p in z.namelist())
            assert b'\r\n' in z.read(name+'/26_verify_coordinator_scaling.cmd')
    print(json.dumps({'archive': str(archive.resolve()), 'folder': name, 'bytes': archive.stat().st_size,
                      'sha256': hashlib.sha256(archive.read_bytes()).hexdigest(), **delivery}, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
