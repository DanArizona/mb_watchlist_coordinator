"""Source guard for command 41. It exposes offline verification only."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys


def main(root):
    root = Path(root).resolve()
    try:
        expected = json.loads((root/'SOURCE_INVENTORY.json').read_text())['files']
        actual = {p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()
            and 'runs' not in p.relative_to(root).parts and '__pycache__' not in p.relative_to(root).parts
            and p.name != 'SOURCE_INVENTORY.json'}
        if set(expected) != actual:
            raise ValueError()
        for name, sha in expected.items():
            p = root/name
            if p.is_symlink() or not p.resolve().is_relative_to(root) or hashlib.sha256(p.read_bytes()).hexdigest() != sha:
                raise ValueError()
    except Exception:
        print('Fresh-controller verification BLOCKED: source inventory differs.', flush=True)
        return 70
    print('OFFLINE fresh-controller bootstrap qualification. No API, password or production journal.', flush=True)
    print('Credential acceptance precedes initial native journal/poll_run creation; synthetic SDK/config and owned process drills only.', flush=True)
    args = [sys.executable, '-I', '-B', str(root/'coordinator/experiments/controller_bootstrap_20261023/verify.py'),
        '--output-root', str(root/'runs')]
    child = subprocess.Popen(args)
    try:
        return child.wait(timeout=180)
    except (subprocess.TimeoutExpired, KeyboardInterrupt):
        child.terminate()
        try:
            child.wait(timeout=2)
        except subprocess.TimeoutExpired:
            child.kill(); child.wait(timeout=2)
        print('Fresh-controller qualification stopped before completion; no PASS is recorded.', flush=True)
        return 124


if __name__ == '__main__':
    raise SystemExit(main(Path(__file__).resolve().parent))
