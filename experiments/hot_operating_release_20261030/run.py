"""Operating release entry: verify/review/prepare, then explicitly approved start."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import unittest
from uuid import uuid4

ROOT = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path[:0] = [str(ROOT/'coordinator/src'), str(ROOT/'market_data/src'), str(ROOT/'coordinator/tests')]
MARKET = r'C:\Users\danla\Documents\github\mb_market_data'
WATCHLISTS = r'C:\Users\danla\Documents\github\schwab_watchlists'


def deny_network():
    def denied(*args, **kwargs): raise OSError('Network denied in read-only/offline operating preparation')
    socket.socket.connect = socket.socket.connect_ex = socket.create_connection = socket.getaddrinfo = denied


def cmd_proof(folder):
    from mb_watchlist_coordinator.daily_operator import _batch
    root = folder/'cmd proof (spaces)'
    root.mkdir()
    (root/'run.py').write_text('import sys,json\nprint(json.dumps(sys.argv[1:]))\n')
    review = root/'review with spaces (one)'/'launch-review.json'
    path = root/'STATUS with spaces.cmd'
    _batch(path, root, 'status', arguments=('--review', str(review)))
    result = subprocess.run(['cmd.exe', '/d', '/c', 'call', str(path)],
        capture_output=True, text=True, timeout=15)
    expected = ['status', '--review', str(review)]
    try: received = json.loads(result.stdout)
    except ValueError: received = None
    return {'result': 'PASS' if result.returncode == 0 and received == expected else 'FAILED',
            'actual_cmd_exe': True, 'returncode': result.returncode,
            'space_and_parenthesis_paths_preserved': received == expected,
            'synthetic_entry_only': True, 'provider_requests': 0}


def verify(inventory):
    from mb_watchlist_coordinator.daily_operator import release_info
    from mb_watchlist_coordinator.recovery_workers import atomic_json
    deny_network()
    folder = ROOT/'runs'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ_')+uuid4().hex[:8])
    folder.mkdir(parents=True, exist_ok=False)
    print('OFFLINE operating release: synthetic journals, repositories and credentials only.', flush=True)
    print('30 focused packaging/review checks; Windows also executes one synthetic CMD file. No live launch or installation.', flush=True)
    suite = unittest.defaultTestLoader.loadTestsFromNames([
        'test_daily_operator.OperatorTests', 'test_daily_operating_review.DailyOperatingReviewTests'])
    if suite.countTestCases() != 30: raise ValueError('Operating check count differs')
    class Log:
        def __init__(self, file): self.file = file
        def write(self, text): self.file.write(text); sys.stdout.write(text)
        def flush(self): self.file.flush(); sys.stdout.flush()
    began = time.monotonic()
    with (folder/'tests.log').open('w', encoding='utf-8') as output:
        result = unittest.TextTestRunner(stream=Log(output), verbosity=2).run(suite)
    cmd = {'result': 'NOT_EXERCISED', 'reason': 'Actual CMD behavior is qualified on Windows'}
    if os.name == 'nt' and result.wasSuccessful():
        try: cmd = cmd_proof(folder)
        except Exception as error: cmd = {'result': 'FAILED', 'error_type': type(error).__name__}
    release_info(ROOT)
    passed = result.wasSuccessful() and not result.skipped and (os.name != 'nt' or cmd['result'] == 'PASS')
    report = {'contract': 'daily-hot-operator-offline-qualification-v1',
        'result': 'PASS' if passed else 'FAILED', 'tests': result.testsRun,
        'passed': result.testsRun-len(result.failures)-len(result.errors)-len(result.skipped),
        'failures': len(result.failures), 'errors': len(result.errors), 'skipped': len(result.skipped),
        'failed_tests': [t.id() for t, _ in result.failures+result.errors],
        'seconds': time.monotonic()-began, 'platform': sys.platform, 'python': list(sys.version_info[:3]),
        'source': json.loads((ROOT/'SOURCE_INVENTORY.json').read_text())['source'],
        'source_inventory_sha256': inventory, 'windows_checks_passed': bool(passed and os.name == 'nt'),
        'native_cmd_proof': cmd, 'network': 'denied', 'actual_vault_access': False,
        'actual_provider_used': False, 'production_changes': False, 'production_hot_enabled': False,
        'native_source_changed': False, 'controller_recovery_and_collector_changed': False,
        'monday_est_window_qualified_offline': bool(passed),
        'qualified_scope': 'Deployment review, dated review/command generation, pre-open startup boundary, retained-state resume preflight and cooperative rollback routing',
        'prior_live_provider_recovery_capacity_and_gui_qualifications_repeated': False,
        'full_day_capacity_qualified': False,
        'remaining': ['Actual Windows83 result and returned CMD prompt',
            'Read-only deployment review on the production computer',
            'Approval of the concrete release, settings and first production activation']}
    atomic_json(folder/'verification.json', report)
    if os.name == 'nt': atomic_json(ROOT/'runs/windows-qualification.json', report)
    print(json.dumps(report, indent=2), flush=True)
    print('Saved report:', folder/'verification.json', flush=True)
    return 0 if passed else 1


def main(argv):
    from mb_watchlist_coordinator import daily_operator as operator
    _, inventory, _ = operator.release_info(ROOT)
    if argv == ['verify']: return verify(inventory)
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    review = commands.add_parser('review-release')
    prepare = commands.add_parser('prepare')
    for command in (review, prepare):
        command.add_argument('--market-data-root', default=MARKET)
        command.add_argument('--watchlists-root', default=WATCHLISTS)
    for name in ('opening-proposal', 'focus-proposal', 'journal', 'ecfg'):
        prepare.add_argument('--'+name, required=True)
    catalog = commands.add_parser('catalog')
    catalog.add_argument('--session-date', required=True)
    resume = commands.add_parser('resume')
    resume.add_argument('--review', required=True)
    start = commands.add_parser('start')
    start.add_argument('--review', required=True)
    start.add_argument('--approved-review-sha256', required=True)
    start.add_argument('--activation-approved', action='store_true')
    for action in ('status', 'stop', 'membership'):
        command = commands.add_parser(action)
        command.add_argument('--review', required=True)
    args = parser.parse_args(argv)
    if args.command not in ('catalog', 'start'): deny_network()
    if args.command == 'review-release':
        result = operator.review_deployment(ROOT, args.market_data_root, args.watchlists_root)
    elif args.command == 'catalog':
        result = operator.acquire_daily_catalog(ROOT, args.session_date)
    elif args.command == 'prepare':
        result = operator.prepare_day(ROOT, args.opening_proposal, args.focus_proposal, journal=args.journal,
            ecfg=args.ecfg, market_data_root=args.market_data_root, watchlists_root=args.watchlists_root)
    elif args.command == 'resume': result = operator.prepare_resume(ROOT, args.review)
    elif args.command == 'start':
        result = operator.start_day(ROOT, args.review, approved_review_sha256=args.approved_review_sha256,
                                    activation_approved=args.activation_approved)
    elif args.command == 'status': result = operator.day_status(ROOT, args.review)
    elif args.command == 'stop': result = operator.stop_day(ROOT, args.review)
    else:
        from mb_watchlist_coordinator.daily_membership_window import main as show
        value, _ = operator.load_review(ROOT, args.review)
        return show(['--state-root', value['backend_review']['configuration']['publication']['state_root']])
    print(json.dumps(result, indent=2), flush=True)
    return 1 if result.get('result') == 'FAILED' else 0


if __name__ == '__main__':
    try: raise SystemExit(main(sys.argv[1:]))
    except KeyboardInterrupt: raise SystemExit(130)
    except Exception as error:
        from mb_watchlist_coordinator.daily_operator import OperatorError
        detail = str(error) if isinstance(error, OperatorError) else type(error).__name__
        print('Operating release refused:', detail, flush=True)
        raise SystemExit(1)
