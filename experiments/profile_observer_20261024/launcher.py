"""Source guard for command 49. It exposes offline verification only."""
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
        print('Profile observer verification BLOCKED: source inventory differs.', flush=True)
        return 70
    print('OFFLINE read-only profile observer correction. No API, password or production journal.', flush=True)
    print('Command48 FAILED retained. Focused observer/startup/native reporting checks; prior passed Windows Job drills are not repeated.', flush=True)
    args = [sys.executable, '-I', '-B', str(root/'coordinator/experiments/profile_observer_20261024/verify.py'),
        '--output-root', str(root/'runs')]
    before=set((root/'runs').glob('*/verification.json'))
    child = subprocess.Popen(args, stdout=subprocess.DEVNULL)
    try:
        code=child.wait(timeout=300)
    except (subprocess.TimeoutExpired, KeyboardInterrupt):
        child.terminate()
        try:
            child.wait(timeout=2)
        except subprocess.TimeoutExpired:
            child.kill(); child.wait(timeout=2)
        print('Profile observer qualification stopped before completion; no PASS is recorded.', flush=True)
        return 124
    try:
        fresh=set((root/'runs').glob('*/verification.json'))-before
        if len(fresh)!=1:raise ValueError()
        path=fresh.pop()
        if path.is_symlink() or path.stat().st_size>200_000:raise ValueError()
        value=json.loads(path.read_text())
        if (value.get('result') not in ('PASS','FAILED')
                or (code==0)!=(value['result']=='PASS')
                or code==0 and (value.get('failures')!=0 or value.get('errors')!=0)):
            raise ValueError()
    except Exception:
        print('Profile observer report BLOCKED: saved result missing or inconsistent.',flush=True)
        return 70
    # The outer launcher owns this output, even if a synthetic child changed
    # the verifier's own stdout/stderr. Never infer PASS from a silent exit.
    print(json.dumps(value,indent=2),flush=True)
    print('Saved report:',path,flush=True)
    return code


if __name__ == '__main__':
    raise SystemExit(main(Path(__file__).resolve().parent))
