"""Offline qualification and explicit bounded off-hours provider entry."""
import argparse
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
sys.dont_write_bytecode = True
sys.path[:0] = [str(ROOT/'coordinator/src'), str(ROOT/'market_data/src'), str(ROOT/'coordinator/tests')]


class Log:
    def __init__(self, file): self.file = file
    def write(self, value): self.file.write(value); sys.stdout.write(value)
    def flush(self): self.file.flush(); sys.stdout.flush()


def verify(manifest, inventory_sha):
    os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
    def denied(*a, **k): raise OSError('Network denied in off-hours offline qualification')
    socket.socket.connect = socket.socket.connect_ex = socket.create_connection = socket.getaddrinfo = denied
    suite = unittest.defaultTestLoader.loadTestsFromName('test_after_hours_profile')
    if suite.countTestCases() != 19: raise ValueError('Focused after-hours test count differs')
    folder = ROOT/'runs'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ_')+uuid4().hex[:8])
    folder.mkdir(parents=True, exist_ok=False)
    os.environ['MB_AFTER_HOURS_PROOF'] = str(folder/'native-proof')
    print('OFFLINE off-hours provider profile. Synthetic SDK only; actual process/time gates and native journal.', flush=True)
    print('Includes one minute of the proposed 24-slot cadence. No password, API or production changes.', flush=True)
    began = time.monotonic()
    with (folder/'tests.log').open('w', encoding='utf-8') as output:
        result = unittest.TextTestRunner(stream=Log(output), verbosity=2).run(suite)
    from mb_watchlist_coordinator.live_profile import source_guard
    source_guard(ROOT, inventory_sha)
    p = folder/'native-proof/proof.json'; proof = json.loads(p.read_text()) if p.exists() else None
    passed = (result.wasSuccessful() and result.testsRun == 19 and not result.skipped
        and proof and proof['result'] == 'PASS' and proof['quote_dispatch_permits'] == 24
        and proof['native_audit_passed'] and proof['two_fresh_replays_equal'] and not proof['actual_provider_used'])
    windows = bool(passed and os.name == 'nt' and proof['cleanup']['backend'] == 'windows_job')
    report = {'contract': 'after-hours-provider-offline-qualification-v1', 'result': 'PASS' if passed else 'FAILED',
        'tests': result.testsRun, 'passed': result.testsRun-len(result.failures)-len(result.errors)-len(result.skipped),
        'failures': len(result.failures), 'errors': len(result.errors), 'skipped': len(result.skipped),
        'failed_tests': [test.id() for test, _ in result.failures+result.errors], 'seconds': time.monotonic()-began,
        'platform': sys.platform, 'python': list(sys.version_info[:3]), 'source': manifest['source'],
        'source_inventory_sha256': inventory_sha, 'windows_checks_passed': windows,
        'network': 'denied', 'actual_vault_access': False, 'actual_broker_sdk_used': False,
        'production_changes': False, 'production_hot_enabled': False, 'daily_launcher_changed': False,
        'native_proof': proof,
        'clock_scope': 'constant shifted wall clock in trusted offline fixture only; real elapsed pacing and deadlines; live entry has actual UTC clock',
        'unchanged_daily_paced_capacity_recovery_drills_repeated': False,
        'after_hours_live_provider_performance_qualified': False, 'daily_live_launch_qualified': False,
        'provider_capacity_qualified': False, 'full_day_capacity_qualified': False}
    (folder/'verification.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(report, indent=2), flush=True); print('Saved report:', folder/'verification.json', flush=True)
    return 0 if passed else 1


def qualified_windows(inventory_sha):
    for p in (ROOT/'runs').glob('*/verification.json'):
        try:
            v = json.loads(p.read_text(encoding='utf-8'))
            if (v['contract'] == 'after-hours-provider-offline-qualification-v1' and v['result'] == 'PASS'
                    and v['tests'] == v['passed'] == 19 and not v['failures'] and not v['errors'] and not v['skipped']
                    and v['windows_checks_passed'] is True and v['source_inventory_sha256'] == inventory_sha):
                return True
        except (OSError, ValueError, KeyError, TypeError): pass
    return False


def main(argv):
    from mb_watchlist_coordinator.live_profile import source_guard
    inventory_sha = source_guard(ROOT)
    manifest = json.loads((ROOT/'SOURCE_INVENTORY.json').read_text(encoding='utf-8'))
    if manifest['contract'] != 'after-hours-provider-source-v1': raise ValueError('Original delivered profile required')
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('verify')
    review = commands.add_parser('review')
    review.add_argument('--ecfg', required=True)
    live = commands.add_parser('live')
    live.add_argument('--ecfg', required=True)
    live.add_argument('--provider-trial-approved', action='store_true')
    live.add_argument('--market-closed-confirmed', action='store_true')
    stop = commands.add_parser('stop'); stop.add_argument('--run-root', required=True)
    args = parser.parse_args(argv)
    if args.command == 'verify': return verify(manifest, inventory_sha)
    from mb_watchlist_coordinator.after_hours_profile import build_review, run_profile, request_stop, load_config
    from mb_watchlist_coordinator.daily_supervision import read_json, unseal
    if args.command == 'stop':
        if load_config(args.run_root)['review']['source_root'] != str(ROOT): raise ValueError('Original profile source required')
        print(json.dumps(request_stop(args.run_root), indent=2)); return 0
    if args.command == 'live' and (not args.provider_trial_approved or not args.market_closed_confirmed):
        raise ValueError('Explicit closed-hours and bounded provider-trial assertions required')
    value = build_review(str(ROOT), args.ecfg)
    print(json.dumps(value, indent=2), flush=True)
    if args.command == 'review': return 0
    if not qualified_windows(inventory_sha): raise ValueError('Run and pass offline command73 in this exact delivery first')
    print('ISOLATED OFF-HOURS PROVIDER TRIAL: SPY only, at most24 quotes,120s active, no Nasdaq/directory requests.', flush=True)
    print('Uses existing encrypted config; SDK token refresh is possible. Production journals/processes and daily guards are unchanged.', flush=True)
    root, owner = run_profile(value, trial_approved=True, market_closed_confirmed=True)
    p = root/'performance-report.json'
    report = unseal(read_json(p)) if p.exists() else {'result': 'FAILED', 'owner': owner}
    print(json.dumps(report, indent=2), flush=True)
    print('Owner receipt:', root/'owner-result.json', flush=True)
    print('Saved report:', p, flush=True)
    return 0 if report['result'] == 'PASS' and owner['reporting']['status'] == 'COMPLETE' else 1


if __name__ == '__main__':
    try: raise SystemExit(main(sys.argv[1:]))
    except KeyboardInterrupt: raise SystemExit(130)
    except Exception as error:
        print('Off-hours profile refused:', type(error).__name__, flush=True)
        raise SystemExit(70)
