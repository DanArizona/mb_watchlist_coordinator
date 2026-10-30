"""Focused offline checks and bounded public daily-path trial commands."""
import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import socket
import sys
import time
import unittest
from uuid import uuid4

ROOT=Path(__file__).resolve().parent
sys.dont_write_bytecode=True
sys.path[:0]=[str(ROOT/'coordinator/src'),str(ROOT/'market_data/src'),str(ROOT/'coordinator/tests')]
CHECKS=48
QUALIFICATION='market-open-daily-path-offline-qualification-v1'


class Log:
    def __init__(self,file):self.file=file
    def write(self,value):self.file.write(value);sys.stdout.write(value)
    def flush(self):self.file.flush();sys.stdout.flush()


def verify(manifest,inventory):
    def denied(*a,**k):raise OSError('Network denied in offline market-open check qualification')
    socket.socket.connect=socket.socket.connect_ex=socket.create_connection=socket.getaddrinfo=denied
    os.environ['PYTHONDONTWRITEBYTECODE']='1'
    suite=unittest.defaultTestLoader.loadTestsFromNames(['test_market_open_check','test_daily_launch','test_daily_operating_review',
        'test_daily_collector.DailyCollectorTests.test_final_permitted_slot_is_schedule_completion_without_another_provider_call',
        'test_daily_collector.DailyCollectorTests.test_hot_call_ceiling_persists_across_restarts'])
    if suite.countTestCases()!=CHECKS:raise ValueError('Focused check count differs')
    folder=ROOT/'runs'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ_')+uuid4().hex[:8])
    folder.mkdir(parents=True,exist_ok=False)
    os.environ['MB_MARKET_OPEN_CHECK_PROOF']=str(folder/'native-proof')
    print('OFFLINE bounded daily-path check. Synthetic SDK/feed, real owned processes and elapsed gates.',flush=True)
    print('One short dispatch/collection/closeout proof; no password, network, installation or production changes. Allow about one minute.',flush=True)
    began=time.monotonic()
    with (folder/'tests.log').open('w',encoding='utf-8') as output:
        result=unittest.TextTestRunner(stream=Log(output),verbosity=2).run(suite)
    from mb_watchlist_coordinator.live_profile import source_guard
    source_guard(ROOT,inventory)
    proof_path=folder/'native-proof/packet with spaces/runs/market_open_daily_20261030_1234abcd/offline-proof.json'
    proof=json.loads(proof_path.read_text()) if proof_path.exists() else None
    passed=bool(result.wasSuccessful() and result.testsRun==CHECKS and not result.skipped and proof
        and proof['owner']['result']=='STOPPED' and proof['report']['hot_acquisitions']==2
        and proof['owner']['reporting']['native_audit_passed']
        and proof['owner']['reporting']['two_fresh_replays_equal'])
    windows=bool(passed and os.name=='nt' and proof['owner']['cleanup']['backend']=='windows_job'
        and proof['owner']['reporting']['cleanup']['backend']=='windows_job')
    report={'contract':QUALIFICATION,'result':'PASS' if passed else 'FAILED','tests':result.testsRun,
        'passed':result.testsRun-len(result.failures)-len(result.errors)-len(result.skipped),
        'failures':len(result.failures),'errors':len(result.errors),'skipped':len(result.skipped),
        'failed_tests':[t.id() for t,_ in result.failures+result.errors],'seconds':time.monotonic()-began,
        'source':manifest['source'],'source_inventory_sha256':inventory,'platform':sys.platform,
        'python':list(sys.version_info[:3]),'windows_checks_passed':windows,
        'network':'denied','actual_vault_access':False,'actual_broker_sdk_used':False,
        'production_changes':False,'production_hot_enabled':False,
        'original_fixed_dispatcher_executed':True,
        'offline_substitutions':'trusted process wrapper supplies synthetic SDK/feed, dependency evidence and constant shifted clock; no live CLI seam',
        'native_proof':proof,'unchanged_paced_capacity_recovery_drills_repeated':False,
        'live_market_open_check_qualified':False,'operating_release_qualified':False,
        'provider_capacity_qualified':False,'full_day_capacity_qualified':False}
    (folder/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2),flush=True);print('Saved report:',folder/'verification.json',flush=True)
    return 0 if passed else 1


def qualified_windows(inventory):
    for path in (ROOT/'runs').glob('*/verification.json'):
        try:
            v=json.loads(path.read_text())
            if (v['contract']==QUALIFICATION and v['result']=='PASS' and v['tests']==v['passed']==CHECKS
                    and not any(v[k] for k in ('failures','errors','skipped')) and v['windows_checks_passed'] is True
                    and v['source_inventory_sha256']==inventory):return True
        except (OSError,ValueError,KeyError,TypeError):pass
    return False


def main(argv):
    from mb_watchlist_coordinator.live_profile import source_guard
    from mb_watchlist_coordinator import market_open_check as check
    from mb_watchlist_coordinator.daily_supervision import sealed
    from mb_watchlist_coordinator.recovery_workers import atomic_json
    inventory=source_guard(ROOT)
    manifest=json.loads((ROOT/'SOURCE_INVENTORY.json').read_text())
    if manifest['contract']!='market-open-daily-path-source-v1':raise ValueError('Original delivered check required')
    parser=argparse.ArgumentParser(description=__doc__);commands=parser.add_subparsers(dest='command',required=True)
    commands.add_parser('verify');commands.add_parser('describe')
    prepare=commands.add_parser('prepare')
    prepare.add_argument('--opening-proposal',required=True);prepare.add_argument('--focus-proposal',required=True)
    prepare.add_argument('--market-open-confirmed',action='store_true')
    prepare.add_argument('--public-source-download-approved',action='store_true')
    live=commands.add_parser('live');live.add_argument('--trial-root',required=True);live.add_argument('--ecfg',required=True)
    live.add_argument('--market-open-confirmed',action='store_true');live.add_argument('--provider-trial-approved',action='store_true')
    for name in ('status','stop','report'):
        sub=commands.add_parser(name);sub.add_argument('--trial-root',required=True)
    args=parser.parse_args(argv)
    if args.command=='verify':return verify(manifest,inventory)
    if args.command=='describe':print(json.dumps(check.describe(),indent=2));return 0
    if args.command in ('prepare','live') and not qualified_windows(inventory):
        print('First run and pass 75_verify_market_open_daily_check.cmd in this exact delivery. No network or password action was taken.',flush=True)
        return 70
    if args.command=='prepare':
        if not args.market_open_confirmed or not args.public_source_download_approved:
            print('Preparation requires --market-open-confirmed and --public-source-download-approved (at most two public directory downloads).',flush=True)
            return 70
        from mb_watchlist_coordinator.integrated_catalog import acquire_catalog
        from mb_watchlist_coordinator.controller_bootstrap import _proposal
        now=datetime.now(timezone.utc);day=check.market_window(now)
        p0,_=_proposal(args.opening_proposal);p1,_=_proposal(args.focus_proposal)
        if p0.session_date!=day or p1.session_date!=day or p0.revision!=0 or p1.revision!=1:
            print('Use today\'s completed r0 and Focus r1 proposals. No download was attempted.',flush=True);return 70
        directory=acquire_catalog(deadline=now+timedelta(seconds=60),allow_network=True)
        root=ROOT/'runs'/('market_open_daily_'+day.strftime('%Y%m%d')+'_'+uuid4().hex[:8])
        result=check.prepare_trial(str(ROOT),str(root),args.opening_proposal,args.focus_proposal,directory)
        print(json.dumps(result,indent=2),flush=True)
        print('Prepared trial:',root,flush=True)
        print('Preparation did not open the encrypted configuration or start the daily owner.',flush=True)
        return 0
    if args.command=='live':
        if not args.market_open_confirmed or not args.provider_trial_approved:
            print('Live execution requires --market-open-confirmed and --provider-trial-approved for the documented bounded check.',flush=True)
            return 70
        review=check.build_trial_review(str(ROOT),args.trial_root,args.ecfg)
        launch=review['launch_review'];collector=launch['backend_review']['configuration']['collector']
        atomic_json(Path(args.trial_root)/'candidate-review.json',sealed(review))
        print(json.dumps({'profile':check.describe(),'review_sha256':review['review_sha256'],
            'collection_start_et':datetime.fromisoformat(collector['start_at_utc']).astimezone(check.ET).isoformat(),
            'collection_stop_et':datetime.fromisoformat(collector['stop_at_utc']).astimezone(check.ET).isoformat(),
            'trial_root':args.trial_root,'exact_review':str(Path(args.trial_root)/'candidate-review.json')},indent=2),flush=True)
        print('ISOLATED MARKET-OPEN DAILY PATH: actual daily launcher, source and authenticated roles; at most 72 Hot + 3 identity quote calls.',flush=True)
        print('Enter the encrypted-config password promptly. The dated window is not extended while typing; shared SDK token refresh is possible.',flush=True)
        owner=check.run_trial(review,trial_approved=True,market_open_confirmed=True)
        print('Owner result:',json.dumps(owner,indent=2),flush=True)
        report=check.summarize_trial(str(ROOT),args.trial_root)
        print(json.dumps(report,indent=2),flush=True)
        print('Saved report:',Path(args.trial_root)/'daily-path-report.json',flush=True)
        print('Owner receipt:',Path(launch['outer_root'])/'operating-result.json',flush=True)
        return 0 if report['daily_path_check_passed'] else 1
    prepared=check.load_prepared(str(ROOT),args.trial_root)
    if args.command=='report':result=check.summarize_trial(str(ROOT),args.trial_root)
    elif args.command=='stop':
        from mb_watchlist_coordinator.daily_operating import request_stop
        result=request_stop(Path(prepared['root'])/'daily_outer_check')
    else:
        from mb_watchlist_coordinator.daily_operating import inspect_operating_status
        result=inspect_operating_status(Path(prepared['root'])/'daily_outer_check')
    print(json.dumps(result,indent=2),flush=True);return 0


if __name__=='__main__':
    try:raise SystemExit(main(sys.argv[1:]))
    except KeyboardInterrupt:raise SystemExit(130)
    except Exception as error:
        from mb_watchlist_coordinator.authenticated_startup import StartupError
        from mb_watchlist_coordinator.market_open_check import CheckRefused
        detail=error.code if isinstance(error,StartupError) else str(error) if isinstance(error,CheckRefused) else type(error).__name__
        print('Market-open check refused:',detail,flush=True)
        print('Keep the prepared trial and any owner receipts; do not reset or reuse partial state.',flush=True)
        raise SystemExit(70)
