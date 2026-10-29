"""Focused offline correction; preserves the original Windows FAILED verdict."""
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
NATIVE='5552c5db43351d1a9ae8d376196cc99ba9c7f05d'
CHANGED=['src/mb_watchlist_coordinator/daily_supervision.py']


def inventory():
    manifest=json.loads((ROOT/'SOURCE_INVENTORY.json').read_text())
    if (manifest['contract']!='daily-hot-exit-fix-source-v1'
            or manifest['source']['market_data_commit']!=NATIVE
            or manifest['reused_runtime_changes']!=CHANGED):
        raise ValueError('Correction/reuse source contract differs')
    actual={p.relative_to(ROOT).as_posix() for p in ROOT.rglob('*') if p.is_file()
        and p.relative_to(ROOT).parts[0]!='runs' and p!=ROOT/'SOURCE_INVENTORY.json'}
    if actual!=set(manifest['files']):raise ValueError('Source set differs')
    for name,sha in manifest['files'].items():
        path=ROOT/name
        if path.is_symlink() or not path.resolve().is_relative_to(ROOT) or hashlib.sha256(path.read_bytes()).hexdigest()!=sha:
            raise ValueError('Source bytes differ')
    return manifest


def reused_components(manifest):
    prior=json.loads((ROOT/'REUSED_WINDOWS_COMPONENTS.json').read_text())
    if (prior['result']!='FAILED' or prior['passed']!=133 or prior['tests']!=134
            or prior['source']['coordinator_commit']!='3c0f8cde268160277e2ad426dfe7f8cf655197ac'
            or prior['source']['market_data_commit']!=manifest['source']['market_data_commit']
            or prior['owner_component']['result']!='STOPPED'
            or not prior['owner_component']['scope_empty_observed']
            or not prior['owner_component']['native_audit_passed']
            or not prior['owner_component']['two_fresh_replays_equal']
            or prior['capacity_component']['qualification_result']!='PASS'
            or not prior['capacity_component']['native_audit_passed']
            or not prior['capacity_component']['two_fresh_replays_equal']):
        raise ValueError('Original supplied Windows component evidence differs')
    return {'basis':prior['basis'],'original_run':prior['run'],'original_packet_result':'FAILED',
        'original_files_independently_read':False,'native_source_unchanged':True,
        'owner_component':prior['owner_component'],'capacity_component':prior['capacity_component'],
        'unchanged_full_size_and_old_packet_repeated':False}


def verify(manifest):
    reused=reused_components(manifest)
    class OfflineSocket(socket.socket):
        def __new__(cls,*a,**kw):raise OSError('Network denied in exit correction qualification')
    def denied(*a,**kw):raise OSError('Network denied in exit correction qualification')
    socket.socket=OfflineSocket;socket.create_connection=socket.getaddrinfo=denied
    run=ROOT/'runs'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ_')+uuid4().hex[:8])
    run.mkdir(parents=True,exist_ok=False)
    os.environ['MB_DAILY_CONTROLLER_RECOVERY_PROOF_DIR']=str(run/'recovery')
    os.environ['MB_DAILY_OPERATING_OWNER_DIR']=str(run/'owner')
    names=['test_daily_supervision',
        'test_daily_controller.DailyControllerTests.test_lost_owned_worker_recovers_response_after_full_fifteen_second_hold',
        'test_daily_operating.DailyOperatingTests.test_complete_collection_proof_preserves_native_journal_and_never_reports_in_the_active_scope']
    print('OFFLINE owned exit/lease correction: real processes/locks and full 15-second hold. No password, API or production changes.',flush=True)
    print('15 focused checks; prior Windows capacity and ownership evidence retained. Allow about 45 seconds.',flush=True)
    started=time.monotonic()
    with (run/'tests.log').open('w',encoding='utf-8') as stream:
        result=unittest.TextTestRunner(stream=stream,verbosity=1).run(unittest.defaultTestLoader.loadTestsFromNames(names))
    print((run/'tests.log').read_text(),flush=True)
    inventory()
    def read(path):return json.loads(path.read_text()) if path.exists() else None
    recovery=read(run/'recovery/recovery-proof.json')
    from mb_watchlist_coordinator.daily_supervision import unseal
    owner=read(run/'owner/daily_outer_test/operating-result.json')
    if owner:owner=unseal(owner)
    passed=bool(result.wasSuccessful() and result.testsRun==15 and not result.skipped
        and recovery and recovery['result']=='PASS' and recovery['actual_role_lease_exit_gap_forced']
        and owner and owner['result']=='STOPPED' and owner['cleanup']['status']=='EXIT_OBSERVED'
        and owner['reporting']['status']=='COMPLETE' and owner['reporting']['native_audit_passed']
        and owner['reporting']['two_fresh_replays_equal'])
    report={'contract':'daily-hot-exit-correction-offline-qualification-v1',
        'scope':'focused exit/lease correction; prior supplied Windows component evidence reused',
        'result':'PASS' if passed else 'FAILED','tests':result.testsRun,
        'passed':result.testsRun-len(result.failures)-len(result.errors)-len(result.skipped),
        'failures':len(result.failures),'errors':len(result.errors),'skipped':len(result.skipped),
        'failed_tests':[test.id() for test,error in result.failures+result.errors],
        'seconds':time.monotonic()-started,'source':manifest['source'],
        'platform':sys.platform,'python':list(sys.version_info[:3]),
        'windows_checks_passed':bool(passed and os.name=='nt'),
        'network':'denied','actual_vault_access':False,'actual_broker_sdk_used':False,
        'production_changes':False,'production_hot_enabled':False,'proposed_values_adopted':False,
        'live_launch_available':False,'provider_capacity_qualified':False,'full_day_capacity_qualified':False,
        'lease_exit_confirmation_max_seconds':.05,'minimum_replacement_hold_seconds':15,
        'original_windows_packet_result':'FAILED','reused_windows_components':reused,
        'owner_proof':owner,'recovery_proof':recovery,
        'remaining':['Windows correction result and actual CMD prompt return',
            'Provider capacity and concrete deployment/rollback/settings/activation review',
            'Controlled live automatic Hot, manual membership and read-only Overlay']}
    (run/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2),flush=True);print('Saved report:',run/'verification.json',flush=True)
    return 0 if passed else 1


def main():
    manifest=inventory()
    sys.dont_write_bytecode=True;os.environ['PYTHONDONTWRITEBYTECODE']='1'
    sys.path[:0]=[str(ROOT/'coordinator/src'),str(ROOT/'market_data/src'),str(ROOT/'coordinator/tests')]
    if sys.argv[1:]==['verify']:return verify(manifest)
    return 64


if __name__=='__main__':
    try:raise SystemExit(main())
    except (OSError,ValueError,KeyError,TypeError) as error:
        print('Daily exit correction refused:',type(error).__name__,flush=True)
        raise SystemExit(70)
