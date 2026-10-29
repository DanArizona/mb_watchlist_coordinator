"""Frozen offline daily controller qualification and read-only saved status."""
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
    if manifest['contract'] != 'daily-hot-controller-source-v1':
        raise ValueError('Controller source contract differs')
    expected = manifest['files']
    actual = {p.relative_to(ROOT).as_posix() for p in ROOT.rglob('*') if p.is_file()
        and p.relative_to(ROOT).parts[0] != 'runs' and p != ROOT/'SOURCE_INVENTORY.json'}
    if actual != set(expected): raise ValueError('Source set differs')
    for name, sha in expected.items():
        path = ROOT/name
        if (path.is_symlink() or not path.resolve().is_relative_to(ROOT)
                or hashlib.sha256(path.read_bytes()).hexdigest() != sha):
            raise ValueError('Source bytes differ')
    return manifest


def suite():
    tests = unittest.defaultTestLoader.loadTestsFromNames([
        'test_daily_controller', 'test_daily_supervision', 'test_daily_shutdown', 'test_daily_hot_status'])
    import test_authenticated_startup as authentication
    tests.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(authentication.SecretHandoffTests))
    # The actual pinned mb_tools factory/reference test is already accepted;
    # include only the affected private-pipe, horizon, timeout and redaction cases.
    for name in unittest.defaultTestLoader.getTestCaseNames(authentication.BootstrapTests):
        if name != 'test_actual_pinned_ecfg_status_and_client_factory_with_synthetic_sdk':
            tests.addTest(authentication.BootstrapTests(name))
    return tests


def verify(manifest):
    class OfflineSocket(socket.socket):
        def __new__(cls, *args, **kwargs): raise OSError('Network denied in daily controller qualification')
    def denied(*args, **kwargs): raise OSError('Network denied in daily controller qualification')
    socket.socket = OfflineSocket
    socket.create_connection = socket.getaddrinfo = denied
    run = ROOT/'runs'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ_')+uuid4().hex[:8])
    run.mkdir(parents=True, exist_ok=False)
    os.environ['MB_DAILY_CONTROLLER_PROOF_DIR'] = str(run/'native')
    os.environ['MB_DAILY_CONTROLLER_RECOVERY_PROOF_DIR'] = str(run/'recovery')
    print('OFFLINE daily controller: synthetic SDK and journals; actual elapsed deadlines. No password, API or production changes.', flush=True)
    started = time.monotonic()
    result = unittest.TextTestRunner(verbosity=1).run(suite())
    inventory()
    def proof(path): return json.loads(path.read_text()) if path.exists() else None
    native, recovery = proof(run/'native/proof.json'), proof(run/'recovery/recovery-proof.json')
    passed = (result.wasSuccessful() and not result.skipped
        and all(p and p['result'] == 'PASS' for p in (native, recovery)))
    report = {'contract': 'daily-hot-controller-offline-qualification-v1',
        'result': 'PASS' if passed else 'FAILED', 'tests': result.testsRun,
        'passed': result.testsRun-len(result.failures)-len(result.errors)-len(result.skipped),
        'failures': len(result.failures), 'errors': len(result.errors), 'skipped': len(result.skipped),
        'failed_tests': [t.id() for t, error in result.failures+result.errors],
        'seconds': time.monotonic()-started, 'source': manifest['source'],
        'platform': sys.platform, 'python': list(sys.version_info[:3]),
        'windows_checks_passed': bool(passed and os.name == 'nt'),
        'network': 'denied', 'actual_vault_access': False, 'actual_broker_sdk_used': False,
        'production_changes': False, 'authenticated_controller_included': True,
        'read_only_hot_status_included': True, 'live_launch_available': False,
        'production_hot_enabled': False, 'proposed_values_adopted': False,
        'full_day_capacity_qualified': False, 'native_proof': native, 'recovery_proof': recovery,
        'remaining': ['Windows result and actual CMD prompt return',
            'Representative full-day performance/provider capacity and independent outer operating packaging',
            'Deployment/rollback and explicit settings/activation review',
            'Closely following manual membership controls and read-only Overlay']}
    (run/'verification.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2), flush=True)
    print('Saved report:', run/'verification.json', flush=True)
    return 0 if passed else 1


def main():
    manifest = inventory()
    sys.dont_write_bytecode = True
    os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
    sys.path[:0] = [str(ROOT/'coordinator/src'), str(ROOT/'market_data/src'), str(ROOT/'coordinator/tests')]
    if sys.argv[1:] == ['verify']: return verify(manifest)
    if len(sys.argv) == 4 and sys.argv[1:3] == ['status', '--state-root']:
        from mb_watchlist_coordinator.daily_hot_status import inspect_hot_status
        result = inspect_hot_status(Path(sys.argv[3]))
        print(json.dumps(result, indent=2))
        return 0 if result['state'] not in ('UNKNOWN', 'STALE_CONTROLLER', 'CONTROLLER_NOT_RUNNING', 'BLOCKED') else 1
    return 64


if __name__ == '__main__':
    try: raise SystemExit(main())
    except (OSError, ValueError, KeyError, TypeError) as error:
        print('Daily controller packet refused:', type(error).__name__, flush=True)
        raise SystemExit(70)
