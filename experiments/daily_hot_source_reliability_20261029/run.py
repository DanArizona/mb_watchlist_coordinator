"""Offline daily source reliability and actual paced owned collection checks."""
from datetime import datetime,timezone
import hashlib,json,os,socket,sys,time,unittest
from pathlib import Path
from uuid import uuid4

ROOT=Path(__file__).resolve().parent
NATIVE='5552c5db43351d1a9ae8d376196cc99ba9c7f05d'
CHANGED=['src/mb_watchlist_coordinator/daily_operating_worker.py',
    'src/mb_watchlist_coordinator/daily_source.py',
    'src/mb_watchlist_coordinator/nasdaq_recovery_supervisor.py',
    'src/mb_watchlist_coordinator/sampling_service.py']
NAMES=['test_daily_source_reliability.DailySourceReliabilityTests','test_daily_source',
    'test_source_diagnostics','test_sampling_service',
    'test_daily_controller.DailyControllerTests.test_source_integrity_block_stops_dependent_hot_without_demoting_saved_membership',
    'test_daily_controller.DailyControllerTests.test_foreign_publication_or_changed_claim_blocks_before_new_provider_calls',
    'test_daily_operating.DailyOperatingTests.test_actual_owner_stops_only_its_scope_then_runs_a_fresh_native_report',
    'test_daily_operating.DailyOperatingTests.test_actual_outer_loss_releases_only_its_known_owned_children',
    'test_daily_operating.DailyOperatingTests.test_detected_stop_keeps_its_original_cleanup_deadline_if_parent_recovers',
    'test_daily_source_reliability.DailyPacedSourceOwnerTests']


def inventory():
    m=json.loads((ROOT/'SOURCE_INVENTORY.json').read_text())
    if (m['contract']!='daily-hot-source-reliability-source-v1'
            or m['source']['market_data_commit']!=NATIVE
            or m['runtime_changes']!=CHANGED):raise ValueError('Source scope differs')
    actual={p.relative_to(ROOT).as_posix() for p in ROOT.rglob('*') if p.is_file()
        and p.relative_to(ROOT).parts[0]!='runs' and p!=ROOT/'SOURCE_INVENTORY.json'}
    if actual!=set(m['files']):raise ValueError('Source set differs')
    for name,sha in m['files'].items():
        p=ROOT/name
        if p.is_symlink() or not p.resolve().is_relative_to(ROOT) or hashlib.sha256(p.read_bytes()).hexdigest()!=sha:
            raise ValueError('Source bytes differ')
    return m


class Log:
    def __init__(self,file):self.file=file
    def write(self,value):self.file.write(value);sys.stdout.write(value)
    def flush(self):self.file.flush();sys.stdout.flush()


def verify(manifest):
    def denied(*args,**kwargs):raise OSError('Network denied in source reliability qualification')
    socket.socket.connect=socket.socket.connect_ex=socket.create_connection=socket.getaddrinfo=denied
    run=ROOT/'runs'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ_')+uuid4().hex[:8])
    run.mkdir(parents=True,exist_ok=False)
    os.environ['MB_DAILY_PACED_SOURCE_PROOF_DIR']=str(run/'paced')
    suite=unittest.defaultTestLoader.loadTestsFromNames(NAMES)
    if suite.countTestCases()!=50:raise ValueError('Expected fifty focused tests')
    print('OFFLINE daily source reliability. Synthetic SDK/data only; no password, API or production changes.',flush=True)
    print('50 checks include an actual paced CURRENT/history/fresh-CURRENT run. Allow about 2.5 minutes.',flush=True)
    print('The original 60-second intervals and all watchdog deadlines remain. Prior full-size/recovery drills are not repeated.',flush=True)
    began=time.monotonic()
    with (run/'tests.log').open('w',encoding='utf-8') as f:
        result=unittest.TextTestRunner(stream=Log(f),verbosity=1).run(suite)
    inventory()
    p=run/'paced/proof.json';paced=json.loads(p.read_text()) if p.exists() else None
    failure=run/'paced/closed-state/daily_hot_test/daily-source-failure.json'
    source_failure=json.loads(failure.read_text()) if failure.exists() else None
    passed=bool(result.wasSuccessful() and result.testsRun==50 and not result.skipped
        and paced and paced['result']=='PASS' and paced['source_reconciled']
        and paced['source_attempts']==3 and paced['actual_elapsed_pacing']
        and paced['native_audit_passed'] and paced['two_fresh_replays_equal'])
    report={'contract':'daily-hot-source-reliability-offline-qualification-v1',
        'result':'PASS' if passed else 'FAILED','tests':result.testsRun,
        'passed':result.testsRun-len(result.failures)-len(result.errors)-len(result.skipped),
        'failures':len(result.failures),'errors':len(result.errors),'skipped':len(result.skipped),
        'failed_tests':[t.id() for t,error in result.failures+result.errors],
        'seconds':time.monotonic()-began,'source':manifest['source'],
        'platform':sys.platform,'python':list(sys.version_info[:3]),
        'windows_checks_passed':bool(passed and os.name=='nt'),
        'source_scope':'declared daily query windows, fresh CURRENT cutover and publication; known history gaps retained',
        'network':'denied','actual_vault_access':False,'actual_broker_sdk_used':False,
        'production_changes':False,'production_hot_enabled':False,'live_launch_available':False,
        'proposed_values_adopted':False,'operating_release_qualified':False,
        'provider_capacity_qualified':False,'full_day_capacity_qualified':False,
        'source_loop_wait_seconds':.5,'feed_interval_seconds':60,
        'original_progress_seconds':3,'original_credential_seconds':8,
        'original_replacement_hold_seconds':15,'original_cleanup_seconds':10,
        'prior_capacity_and_recovery_drills_repeated':False,
        'original_windows_io_error_cause_resolved':False,
        'original_local_ledger_rollback_actor_identified':False,
        'source_failure_receipt':source_failure,'paced_proof':paced,
        'remaining':['Windows result and actual CMD prompt return',
            'Original transient I/O cause/old ledger change remain unassigned; evaluate with retained diagnostics if they recur',
            'Representative live provider performance and concrete launch/resume/deployment/rollback/settings review',
            'Explicit activation approval before controlled live Hot, followed by manual membership and read-only Overlay']}
    (run/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2),flush=True);print('Saved report:',run/'verification.json',flush=True)
    return 0 if passed else 1


def main():
    m=inventory();sys.dont_write_bytecode=True;os.environ['PYTHONDONTWRITEBYTECODE']='1'
    sys.path[:0]=[str(ROOT/'coordinator/src'),str(ROOT/'market_data/src'),str(ROOT/'coordinator/tests')]
    if sys.argv[1:]==['verify']:return verify(m)
    return 64


if __name__=='__main__':
    try:raise SystemExit(main())
    except (OSError,ValueError,KeyError,TypeError) as error:
        print('Source reliability check refused:',type(error).__name__,str(error),flush=True)
        raise SystemExit(70)
