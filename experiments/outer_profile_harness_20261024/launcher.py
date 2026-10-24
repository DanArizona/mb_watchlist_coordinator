"""Source guard for command 48. It exposes offline verification only."""
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
            and p.relative_to(root).parts[0] != 'runs'
            and p.name != 'SOURCE_INVENTORY.json'}
        if set(expected) != actual:
            raise ValueError()
        for name, sha in expected.items():
            p = root/name
            if p.is_symlink() or not p.resolve().is_relative_to(root) or hashlib.sha256(p.read_bytes()).hexdigest() != sha:
                raise ValueError()
    except Exception:
        print('Outer/profile harness verification BLOCKED: source inventory differs.', flush=True)
        return 70
    print('OFFLINE owned outer-controller, profile goals and native evidence qualification. No API, password or production journal.', flush=True)
    print('Original failures and command47 acceptance retained. Owned synthetic children only; Windows Job Object drills included on Windows.', flush=True)
    args = [sys.executable, '-I', '-B', str(root/'coordinator/experiments/outer_profile_harness_20261024/verify.py'),
        '--output-root', str(root/'runs')]
    child = subprocess.Popen(args)
    try:
        return child.wait(timeout=300)
    except (subprocess.TimeoutExpired, KeyboardInterrupt):
        child.terminate()
        try:
            child.wait(timeout=2)
        except subprocess.TimeoutExpired:
            child.kill(); child.wait(timeout=2)
        print('Outer/profile harness qualification stopped before completion; no PASS is recorded.', flush=True)
        return 124


if __name__ == '__main__':
    raise SystemExit(main(Path(__file__).resolve().parent))
