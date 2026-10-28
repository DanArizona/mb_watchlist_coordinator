"""Source-pinned offline qualification and read-only preview; no live role."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import socket
import sys
import time
import unittest
from uuid import uuid4

ROOT = Path(__file__).resolve().parent


def inventory():
    manifest = json.loads((ROOT/'SOURCE_INVENTORY.json').read_text())
    expected = manifest['files']
    actual = {p.relative_to(ROOT).as_posix() for p in ROOT.rglob('*')
        if p.is_file() and p.relative_to(ROOT).parts[0] != 'runs' and p != ROOT/'SOURCE_INVENTORY.json'}
    if set(expected) != actual: raise ValueError('Source set differs')
    for name, sha in expected.items():
        path = ROOT/name
        if path.is_symlink() or not path.resolve().is_relative_to(ROOT) or hashlib.sha256(path.read_bytes()).hexdigest() != sha:
            raise ValueError('Source bytes differ')
    return manifest


def qualify(manifest):
    class OfflineSocket(socket.socket):
        def __new__(cls, *args, **kwargs): raise OSError('Network denied in daily-session qualification')
    def denied(*args, **kwargs): raise OSError('Network denied in daily-session qualification')
    socket.socket = OfflineSocket
    socket.create_connection = socket.getaddrinfo = denied
    directory = ROOT/'runs'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ_')+uuid4().hex[:8])
    directory.mkdir(parents=True, exist_ok=False)
    os.environ['MB_DAILY_SESSION_PROOF_DIR'] = str(directory/'native-proof')
    names = ['test_daily_session', 'test_integrated_identity.IdentityTests',
        'test_integrated_identity.IdentityProcessTests', 'test_sampling_service',
        'test_nasdaq_recovery_delivery', 'test_operating_plan']
    print('OFFLINE daily publication backend: synthetic journals only; no password, API or production changes.', flush=True)
    started = time.monotonic()
    result = unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.loadTestsFromNames(names))
    inventory()
    passed = result.wasSuccessful() and not result.skipped
    proof_path = directory/'native-proof/proof.json'
    proof = json.loads(proof_path.read_text()) if proof_path.exists() else None
    passed = passed and bool(proof and proof['result'] == 'PASS')
    report = {'contract':'daily-hot-session-offline-qualification-v1',
        'result':'PASS' if passed else 'FAILED', 'tests':result.testsRun,
        'passed':result.testsRun-len(result.errors)-len(result.failures)-len(result.skipped),
        'errors':len(result.errors), 'failures':len(result.failures), 'skipped':len(result.skipped),
        'failed_tests':[t.id() for t,e in result.errors+result.failures],
        'seconds':time.monotonic()-started, 'source':manifest['source'],
        'platform':sys.platform, 'python':list(sys.version_info[:3]),
        'windows_checks_passed':bool(passed and os.name == 'nt'),
        'network':'denied', 'actual_vault_access':False, 'production_changes':False,
        'live_launch_available':False, 'daily_collector_included':False,
        'proposed_values_adopted':False, 'native_proof':proof,
        'remaining':['Windows result and actual CMD prompt return',
            'Daily feed/collector/controller, bounded authentication and stop/recovery integration',
            'Hot status/alerts, deployment review and explicit settings/activation approval',
            'Closely following manual membership controls and read-only Overlay']}
    (directory/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2), flush=True)
    print('Saved report:', directory/'verification.json', flush=True)
    return 0 if passed else 1


def main():
    manifest = inventory()
    sys.dont_write_bytecode = True
    os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
    sys.path[:0] = [str(ROOT/'coordinator/src'), str(ROOT/'market_data/src'), str(ROOT/'coordinator/tests')]
    if sys.argv[1:] == ['verify']: return qualify(manifest)
    if sys.argv[1:2] == ['preview']:
        from mb_watchlist_coordinator.daily_session import main as preview
        return preview(sys.argv[2:])
    return 64


if __name__ == '__main__':
    try: raise SystemExit(main())
    except (OSError, ValueError, KeyError, TypeError) as error:
        print('Daily session packet refused:', type(error).__name__, flush=True)
        raise SystemExit(70)
