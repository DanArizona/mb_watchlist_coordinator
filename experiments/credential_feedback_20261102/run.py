"""Offline verification only. No installation or live launch command."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import socket
import sys
import time
import unittest
from uuid import uuid4

ROOT = Path(__file__).resolve().parent
TESTS = [
    'test_password_feedback', 'test_authenticated_startup', 'test_daily_launch',
    'test_daily_operator', 'test_live_profile.OperatorParentTests',
]


def main():
    if sys.argv[1:] != ['verify']:
        raise ValueError('This packet supports offline verify only')
    inventory_path = ROOT/'SOURCE_INVENTORY.json'
    inventory = json.loads(inventory_path.read_text(encoding='utf-8'))
    for name, sha in inventory['files'].items():
        path = ROOT/name
        if path.is_symlink() or not path.resolve().is_relative_to(ROOT):
            raise ValueError('Source path escaped verification packet')
        if hashlib.sha256(path.read_bytes()).hexdigest() != sha:
            raise ValueError('Verification source inventory differs')
    sys.dont_write_bytecode = True
    sys.path[:0] = [str(ROOT/'coordinator/src'), str(ROOT/'coordinator/tests'),
        str(ROOT/'market_data/src'),
        str(ROOT/'coordinator/experiments/authenticated_startup_20261023/reference_mb_tools/src')]
    def denied(*args, **kwargs):
        raise OSError('Network denied in offline password feedback verification')
    socket.socket.connect = socket.socket.connect_ex = socket.create_connection = socket.getaddrinfo = denied
    print('OFFLINE password feedback: synthetic credentials/SDKs and real owned child processes.', flush=True)
    print('100 focused checks; no password, vault, provider, installation or production changes.', flush=True)
    suite = unittest.defaultTestLoader.loadTestsFromNames(TESTS)
    if suite.countTestCases() != 100:
        raise ValueError('Focused verification count differs')
    out = ROOT/'runs'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ_')+uuid4().hex[:8])
    out.mkdir(parents=True, exist_ok=False)
    class Tee:
        def __init__(self, log): self.log = log
        def write(self, value): self.log.write(value); sys.stdout.write(value)
        def flush(self): self.log.flush(); sys.stdout.flush()
    began = time.monotonic()
    with (out/'tests.log').open('w', encoding='utf-8') as log:
        result = unittest.TextTestRunner(stream=Tee(log), verbosity=1).run(suite)
    passed = result.wasSuccessful() and not result.skipped
    report = {'contract': 'password-feedback-offline-qualification-v1',
        'result': 'PASS' if passed else 'FAILED', 'tests': result.testsRun,
        'passed': result.testsRun-len(result.failures)-len(result.errors)-len(result.skipped),
        'failures': len(result.failures), 'errors': len(result.errors), 'skipped': len(result.skipped),
        'failed_tests': [t.id() for t, _ in result.failures+result.errors],
        'seconds': time.monotonic()-began, 'platform': sys.platform,
        'python': list(sys.version_info[:3]), 'source': inventory['source'],
        'source_inventory_sha256': hashlib.sha256(inventory_path.read_bytes()).hexdigest(),
        'windows_checks_passed': bool(passed and sys.platform == 'win32'),
        'scope': 'Shared coordinator prompt submission and parent-confirmed credential acceptance; unchanged control decisions',
        'interactive_coordinator_entry_points_covered': [
            'daily_fresh_and_manual_resume', 'bounded_market_open', 'after_hours',
            'older_bounded_live_profile', 'installed_one_quote_probe'],
        'synthetic_only': True, 'network': 'denied', 'actual_vault_access': False,
        'actual_provider_used': False, 'production_changes': False,
        'approved_p85_modified': False, 'p94_modified': False, 'p96_modified': False,
        'password_protocol_changed': False, 'provider_budgets_changed': False,
        'watchdog_deadlines_changed': False, 'production_activation_approved': False,
        'remaining': ['Actual Windows result and returned CMD prompt',
            'Incorporate into a reviewed subsequent operating delivery before real launches use the correction']}
    (out/'verification.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(report, indent=2), flush=True)
    print('Saved report:', out/'verification.json', flush=True)
    return 0 if passed else 1


if __name__ == '__main__':
    try: raise SystemExit(main())
    except KeyboardInterrupt: raise SystemExit(130)
    except Exception as error:
        print('Offline password feedback verification refused:', type(error).__name__, flush=True)
        raise SystemExit(1)
