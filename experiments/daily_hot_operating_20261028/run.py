"""Pinned offline daily operating qualification and review/status/stop commands."""
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import socket
import sys
import time
import unittest
from uuid import uuid4

ROOT=Path(__file__).resolve().parent


def inventory():
    manifest=json.loads((ROOT/'SOURCE_INVENTORY.json').read_text())
    if manifest['contract']!='daily-hot-operating-source-v1':raise ValueError('Source contract differs')
    actual={p.relative_to(ROOT).as_posix() for p in ROOT.rglob('*') if p.is_file()
        and p.relative_to(ROOT).parts[0]!='runs' and p!=ROOT/'SOURCE_INVENTORY.json'}
    if actual!=set(manifest['files']):raise ValueError('Source set differs')
    for name,sha in manifest['files'].items():
        path=ROOT/name
        if path.is_symlink() or not path.resolve().is_relative_to(ROOT) or hashlib.sha256(path.read_bytes()).hexdigest()!=sha:
            raise ValueError('Source bytes differ')
    return manifest


def suite():
    names=['test_daily_operating','test_daily_operating_review','test_daily_admission',
        'test_daily_history_reader','test_daily_membership_read','test_daily_collector',
        'test_daily_session','test_daily_capacity','test_quote_observation_store',
        'test_daily_controller.DailyControllerTests.test_reader_validates_while_the_original_publication_owner_stays_attached',
        'test_daily_controller.DailyControllerTests.test_two_authenticated_owned_roles_start_without_a_provider_quote',
        'test_daily_controller.DailyControllerTests.test_lost_owned_worker_recovers_response_after_full_fifteen_second_hold',
        'test_daily_controller.DailyControllerTests.test_sdk_noise_and_secret_never_enter_saved_runtime_evidence']
    return unittest.defaultTestLoader.loadTestsFromNames(names)


def verify(manifest):
    class OfflineSocket(socket.socket):
        def __new__(cls,*a,**kw):raise OSError('Network denied in daily operating qualification')
    def denied(*a,**kw):raise OSError('Network denied in daily operating qualification')
    socket.socket=OfflineSocket
    socket.create_connection=socket.getaddrinfo=denied
    run=ROOT/'runs'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ_')+uuid4().hex[:8])
    run.mkdir(parents=True,exist_ok=False)
    os.environ['MB_DAILY_OPERATING_CAPACITY_DIR']=str(run/'capacity')
    os.environ['MB_DAILY_OPERATING_OWNER_DIR']=str(run/'owner')
    os.environ['MB_DAILY_CONTROLLER_RECOVERY_PROOF_DIR']=str(run/'recovery')
    print('OFFLINE daily operating owner and full-size synthetic history. Actual elapsed gates; no password, API or production changes.',flush=True)
    print('Includes owned parent-loss/cleanup drills and a 542,099-observation fixture. Allow about two minutes.',flush=True)
    started=time.monotonic()
    result=unittest.TextTestRunner(verbosity=1).run(suite())
    inventory()
    def read(path):return json.loads(path.read_text()) if path.exists() else None
    capacity=read(run/'capacity/capacity-qualification.json')
    recovery=read(run/'recovery/recovery-proof.json')
    from mb_watchlist_coordinator.daily_supervision import unseal
    owner=read(run/'owner/daily_outer_test/operating-result.json')
    if owner:owner=unseal(owner)
    passed=bool(result.wasSuccessful() and not result.skipped and capacity
        and capacity['qualification_result']=='PASS' and recovery and recovery['result']=='PASS'
        and owner and owner['result']=='STOPPED' and owner['cleanup']['status']=='EXIT_OBSERVED'
        and owner['reporting']['status']=='COMPLETE' and owner['reporting']['native_audit_passed']
        and owner['reporting']['two_fresh_replays_equal'])
    summary=None
    if capacity:
        summary={key:capacity[key] for key in ('qualification_result','seeded_slots',
            'actual_tail_native_acquisitions','cold_prepare_seconds','tail','actual_elapsed_tick_clock',
            'native_audit_passed','two_fresh_replays_equal','first_replay','full_session_executed',
            'provider_capacity_qualified','full_day_capacity_qualified')}
        summary['owned_cold_startup']={key:capacity['owned_cold_startup'][key] for key in (
            'result','original_progress_deadline_seconds','job_to_first_native_work_seconds','synthetic_sdk_only')}
        summary['table_counts']=capacity['audit']['table_counts']
    report={'contract':'daily-hot-operating-offline-qualification-v1','result':'PASS' if passed else 'FAILED',
        'tests':result.testsRun,'passed':result.testsRun-len(result.failures)-len(result.errors)-len(result.skipped),
        'failures':len(result.failures),'errors':len(result.errors),'skipped':len(result.skipped),
        'failed_tests':[test.id() for test,error in result.failures+result.errors],
        'seconds':time.monotonic()-started,'source':manifest['source'],'platform':sys.platform,
        'python':list(sys.version_info[:3]),'windows_checks_passed':bool(passed and os.name=='nt'),
        'network':'denied','actual_vault_access':False,'actual_broker_sdk_used':False,
        'production_changes':False,'production_hot_enabled':False,'proposed_values_adopted':False,
        'live_launch_available':False,'full_day_capacity_qualified':False,'provider_capacity_qualified':False,
        'representative_synthetic_history_qualified':bool(passed),
        'independent_outer_owner_included':True,'review_status_stop_cli_included':True,
        'owner_proof':owner,'capacity_proof':summary,'recovery_proof':recovery,
        'remaining':['Windows result and actual CMD prompt return',
            'Provider capacity and deployment/rollback review; explicit settings/activation approval',
            'Controlled live automatic Hot observation, followed closely by manual membership and read-only Overlay']}
    (run/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2),flush=True)
    print('Saved report:',run/'verification.json',flush=True)
    return 0 if passed else 1


def main():
    manifest=inventory()
    sys.dont_write_bytecode=True;os.environ['PYTHONDONTWRITEBYTECODE']='1'
    sys.path[:0]=[str(ROOT/'coordinator/src'),str(ROOT/'market_data/src'),
        str(ROOT/'coordinator/tests'),str(ROOT/'native_tests'),str(ROOT/'sizing')]
    if sys.argv[1:]==['verify']:return verify(manifest)
    from mb_watchlist_coordinator.daily_operating_cli import main as operator
    return operator(sys.argv[1:])


if __name__=='__main__':
    try:raise SystemExit(main())
    except (OSError,ValueError,KeyError,TypeError) as error:
        print('Daily operating packet refused:',type(error).__name__,flush=True)
        raise SystemExit(70)
