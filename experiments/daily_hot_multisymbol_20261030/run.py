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


def verify(inventory):
    from mb_watchlist_coordinator.daily_operator import release_info
    from mb_watchlist_coordinator.recovery_workers import atomic_json
    from mb_watchlist_coordinator.live_profile import source_guard
    deny_network()
    folder=ROOT/'runs'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ_')+uuid4().hex[:8])
    folder.mkdir(parents=True,exist_ok=False)
    print('OFFLINE 40-symbol candidate: synthetic SDK, journals and real owned processes. No password, API or production changes.',flush=True)
    print('Forced 41-candidate burst, real 60-second feed pacing and full-size retained history. Allow about 10 minutes; up to 12 on a slower run. Synthetic evidence is about 1.1 GB.',flush=True)
    print('Original deadlines/cadence remain. Prior live-provider, GUI and unchanged recovery proofs are retained.',flush=True)
    names=['test_daily_multisymbol','test_daily_history_reader','test_daily_launch',
        'test_daily_operator','test_daily_operating_review']
    suite=unittest.defaultTestLoader.loadTestsFromNames(names)
    class Log:
        def __init__(self,file):self.file=file
        def write(self,text):self.file.write(text);sys.stdout.write(text)
        def flush(self):self.file.flush();sys.stdout.flush()
    began=time.monotonic();capacity=None;capacity_error=None;owned=None
    fast_count=suite.countTestCases()
    with (folder/'tests.log').open('w',encoding='utf-8')as output:
        result=unittest.TextTestRunner(stream=Log(output),verbosity=1).run(suite)
        if result.wasSuccessful():
            os.environ['MB_MULTI_OWNED_PROOF_DIR']=str(folder/'owned')
            try:
                owned=unittest.TextTestRunner(stream=Log(output),verbosity=1).run(
                    unittest.defaultTestLoader.loadTestsFromName('test_daily_multisymbol_owned'))
            finally:os.environ.pop('MB_MULTI_OWNED_PROOF_DIR',None)
        if owned and owned.wasSuccessful():
            import importlib.util
            path=ROOT/'coordinator/experiments/daily_hot_multisymbol_20261030/history_probe.py'
            spec=importlib.util.spec_from_file_location('multi_history_proof',path)
            module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
            try:capacity=module.run(folder/'multi_history_full',slots=9312,periods=True,background=True)
            except Exception as error:
                import traceback
                traceback.print_exc(file=Log(output));capacity_error=type(error).__name__
    source_guard(ROOT,inventory);release_info(ROOT)
    results=[x for x in (result,owned)if x is not None]
    failures=sum(len(x.failures)for x in results);errors=sum(len(x.errors)for x in results)
    skipped=sum(len(x.skipped)for x in results);tests=sum(x.testsRun for x in results)
    passed=all(x.wasSuccessful()for x in results)and owned is not None and not skipped and capacity is not None and capacity['result']=='PASS'
    proof_path=folder/'owned/multi-owned-proof.json'
    paced=json.loads(proof_path.read_text())if proof_path.exists()else None
    report={'contract':'daily-hot-multisymbol-offline-qualification-v1','result':'PASS'if passed else'FAILED',
        'tests':tests,'passed':tests-failures-errors-skipped,'failures':failures,'errors':errors,'skipped':skipped,
        'failed_tests':[t.id()for x in results for t,_ in x.failures+x.errors],
        'seconds':time.monotonic()-began,'platform':sys.platform,'python':list(sys.version_info[:3]),
        'source':json.loads((ROOT/'SOURCE_INVENTORY.json').read_text())['source'],
        'source_inventory_sha256':inventory,'windows_checks_passed':bool(passed and os.name=='nt'),
        'network':'denied','synthetic_sdk_only':True,'actual_vault_access':False,'actual_provider_used':False,
        'production_changes':False,'production_hot_enabled':False,'proposed_values_adopted':False,
        'maximum_hot_symbols':40,'maximum_distinct_admitted_symbols':40,'maximum_identity_calls':120,
        'identity_spacing_seconds':2,'membership_publication_minimum_interval_seconds':10,'active_collection_period_seconds':300,
        'original_progress_seconds':3,'original_credential_seconds':8,'original_replacement_hold_seconds':15,
        'original_cleanup_seconds':10,'original_report_seconds':60,'maximum_dispatch_lateness_seconds':.75,
        'focused_checks':fast_count,'paced_proof':paced,'capacity_proof':capacity,'capacity_error_type':capacity_error,
        'prior_provider_gui_capacity_and_recovery_proofs_repeated':False,
        'provider_capacity_qualified':False,'full_session_executed':False,'full_day_capacity_qualified':False,
        'operating_release_qualified':False,'production_activation_approved':False,
        'remaining':['Windows result and actual returned CMD prompt','Read-only deployment review for this exact candidate',
            'Concrete 40-symbol settings/integrity scope and first production activation approval']}
    atomic_json(folder/'verification.json',report)
    if os.name=='nt':atomic_json(ROOT/'runs/windows-qualification.json',report)
    print(json.dumps(report,indent=2),flush=True);print('Saved report:',folder/'verification.json',flush=True)
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
