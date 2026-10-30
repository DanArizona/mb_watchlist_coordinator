"""Delivered public daily launch commands and short offline qualification."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import socket
import sys
import time
import unittest
from uuid import uuid4

ROOT = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path[:0] = [str(ROOT/'coordinator/src'), str(ROOT/'market_data/src'), str(ROOT/'coordinator/tests')]


class Log:
    def __init__(self, file): self.file = file
    def write(self, text): self.file.write(text); sys.stdout.write(text)
    def flush(self): self.file.flush(); sys.stdout.flush()


def verify(manifest):
    os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
    def denied(*args, **kwargs): raise OSError('Network denied in offline daily launch qualification')
    socket.socket.connect = socket.socket.connect_ex = socket.create_connection = socket.getaddrinfo = denied
    suite = unittest.defaultTestLoader.loadTestsFromNames(['test_daily_launch', 'test_daily_operating_review'])
    if suite.countTestCases() != 30: raise ValueError('Focused launch check count differs')
    folder = ROOT/'runs'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ_')+uuid4().hex[:8])
    folder.mkdir(parents=True, exist_ok=False)
    began = time.monotonic()
    print('OFFLINE public daily launch/review/resume checks. Synthetic files and private canaries only.', flush=True)
    print('No password, provider access, installation or production changes. Prior paced/recovery/capacity proofs retained.', flush=True)
    with (folder/'tests.log').open('w', encoding='utf-8') as output:
        result = unittest.TextTestRunner(stream=Log(output), verbosity=2).run(suite)
    from mb_watchlist_coordinator.live_profile import source_guard
    source_guard(ROOT)
    passed = result.wasSuccessful() and result.testsRun == 30 and not result.skipped
    report = {'contract': 'daily-hot-public-launch-offline-qualification-v1',
        'result': 'PASS' if passed else 'FAILED', 'tests': result.testsRun,
        'passed': result.testsRun-len(result.failures)-len(result.errors)-len(result.skipped),
        'failures': len(result.failures), 'errors': len(result.errors), 'skipped': len(result.skipped),
        'failed_tests': [test.id() for test, _ in result.failures+result.errors],
        'seconds': time.monotonic()-began, 'platform': sys.platform, 'python': list(sys.version_info[:3]),
        'source': manifest['source'], 'windows_checks_passed': bool(passed and os.name == 'nt'),
        'network': 'denied', 'actual_vault_access': False, 'actual_broker_sdk_used': False,
        'production_changes': False, 'production_hot_enabled': False, 'proposed_values_adopted': False,
        'public_live_launch_entry_included': True, 'live_launch_qualified': False,
        'operating_release_qualified': False, 'provider_capacity_qualified': False,
        'full_day_capacity_qualified': False,
        'prior_windows_71': 'ACCEPTED 26/26; read-conflict fix and original paced proof retained',
        'unchanged_paced_capacity_and_recovery_drills_repeated': False,
        'qualification_scope': 'public review and approval-before-prompt boundaries, fixed role dispatch, readonly resume preflight; backend ownership and provider execution are not newly qualified',
        'original_progress_seconds': 3, 'original_credential_seconds': 8,
        'original_replacement_hold_seconds': 15, 'original_cleanup_seconds': 10,
        'feed_interval_seconds': 60,
        'remaining': ['Windows result and actual returned CMD prompt',
            'Representative real-provider performance with the public daily composition',
            'Concrete settings, deployment/rollback and activation review before live Hot',
            'Manual membership controls and read-only Overlay']}
    (folder/'verification.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(report, indent=2), flush=True)
    print('Saved report:', folder/'verification.json', flush=True)
    return 0 if passed else 1


def main(argv):
    from mb_watchlist_coordinator.live_profile import source_guard
    source_guard(ROOT)
    manifest = json.loads((ROOT/'SOURCE_INVENTORY.json').read_text(encoding='utf-8'))
    if manifest['contract'] != 'daily-hot-public-launch-source-v1':
        raise ValueError('Original public launch delivery required')
    if argv == ['verify']: return verify(manifest)
    from mb_watchlist_coordinator.daily_launch_cli import main as operate
    return operate(str(ROOT), argv)


if __name__ == '__main__':
    try: raise SystemExit(main(sys.argv[1:]))
    except (OSError, ValueError, KeyError, TypeError) as error:
        print('Daily launch packet refused:', type(error).__name__, flush=True)
        raise SystemExit(70)
