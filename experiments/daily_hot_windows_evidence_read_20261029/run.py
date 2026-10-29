"""Focused Windows process-record correction and original actual paced proof."""
import ast
from datetime import datetime,timezone
import hashlib,importlib.util,json,os,socket,sys,time,types,unittest
from pathlib import Path
from uuid import uuid4

ROOT=Path(__file__).resolve().parent
NATIVE='5552c5db43351d1a9ae8d376196cc99ba9c7f05d'
BASE='2f56703904db10cf6c47e410f350f60cfa03656f'
CHANGED=['src/mb_watchlist_coordinator/daily_session.py',
    'src/mb_watchlist_coordinator/daily_supervision.py',
    'src/mb_watchlist_coordinator/daily_worker_view.py',
    'src/mb_watchlist_coordinator/recovery_workers.py']
TEST_SHA='91c87dc7974a47e3a6e0b32ced6850b4b6862109891c22a5814d2b31cd70d706'
METHOD='test_three_real_paced_feed_children_reconcile_while_owned_hot_collection_continues'


def inventory():
    m=json.loads((ROOT/'SOURCE_INVENTORY.json').read_text())
    if (m['contract']!='daily-hot-windows-evidence-read-source-v1'
            or m['source']['market_data_commit']!=NATIVE
            or m['runtime_baseline']!=BASE or m['runtime_changes']!=CHANGED):
        raise ValueError('Expected focused source correction required')
    actual={p.relative_to(ROOT).as_posix() for p in ROOT.rglob('*') if p.is_file()
        and p.relative_to(ROOT).parts[0]!='runs' and p!=ROOT/'SOURCE_INVENTORY.json'}
    if actual!=set(m['files']):raise ValueError('Source file set differs')
    for name,sha in m['files'].items():
        p=ROOT/name
        if p.is_symlink() or not p.resolve().is_relative_to(ROOT) or hashlib.sha256(p.read_bytes()).hexdigest()!=sha:
            raise ValueError('Source bytes differ')
    return m


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


class Log:
    def __init__(self,file):self.file=file
    def write(self,value):self.file.write(value);sys.stdout.write(value)
    def flush(self):self.file.flush();sys.stdout.flush()


def verify(manifest,*,paced_only=False):
    sys.dont_write_bytecode=True;os.environ['PYTHONDONTWRITEBYTECODE']='1'
    sys.path[:0]=[str(ROOT/'coordinator/src'),str(ROOT/'market_data/src'),str(ROOT/'coordinator/tests')]
    def denied(*a,**k):raise OSError('Network denied in offline evidence-read correction')
    socket.socket.connect=socket.socket.connect_ex=socket.create_connection=socket.getaddrinfo=denied
    control=load('_evidence_original_control',ROOT/'diagnostics/trace_control.py')
    parent=load('_evidence_error_observation',ROOT/'diagnostics/observe_operating.py')
    path=ROOT/'coordinator/tests/test_daily_source_reliability.py';raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=TEST_SHA:raise ValueError('Original paced test source differs')
    tree=ast.parse(raw,filename=str(path));transform=control.DisablePeriodicDumps()
    tree=transform.visit(tree);ast.fix_missing_locations(tree)
    if sorted(c['scenario'] for c in transform.changed)!=['auth_scene','scene']:
        raise ValueError('Exactly the original two test-only dump flags required')
    module=types.ModuleType('_hot_trace_control_fixture');module.__file__=str(path)
    sys.modules[module.__name__]=module;exec(compile(tree,str(path),'exec'),module.__dict__)
    import test_daily_operating as fixtures
    from mb_watchlist_coordinator.daily_operating import DailyOperatingOwner
    import test_process_evidence_reads as evidence_tests
    from mb_watchlist_coordinator import recovery_workers
    original_setup=fixtures.DailyOperatingTests.setUp
    original_run=parent.install_owner(DailyOperatingOwner)
    fixtures.DailyOperatingTests.setUp=lambda case:parent.setup_observed(case,original_setup)
    suite=unittest.TestSuite()
    if not paced_only:
        suite.addTests(unittest.defaultTestLoader.loadTestsFromNames([
            'test_process_evidence_reads.ProcessEvidenceReadTests','test_daily_supervision']))
        if os.name=='nt':
            suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(evidence_tests.NativeWindowsEvidenceReadTests))
    suite.addTest(module.DailyPacedSourceOwnerTests(METHOD))
    expected=1 if paced_only else 26 if os.name=='nt' else 23
    if suite.countTestCases()!=expected:raise ValueError('Focused check count differs')
    run=ROOT/'runs'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ_')+uuid4().hex[:8])
    run.mkdir(parents=True,exist_ok=False);os.environ['MB_DAILY_PACED_SOURCE_PROOF_DIR']=str(run/'paced')
    print('OFFLINE Windows process-record read correction. Synthetic SDK/data only.',flush=True)
    print('Windows-only read retry: .25s / 26 attempts; original freshness/binding checks and deadlines remain.',flush=True)
    print('One original CURRENT/history/fresh-CURRENT proof at actual 60-second intervals; allow about 2.5 minutes.',flush=True)
    began=time.monotonic()
    try:
        with (run/'tests.log').open('w',encoding='utf-8') as f:
            result=unittest.TextTestRunner(stream=Log(f),verbosity=2).run(suite)
    finally:
        fixtures.DailyOperatingTests.setUp=original_setup;DailyOperatingOwner._run=original_run
    inventory()
    proof_path=run/'paced/proof.json';proof=json.loads(proof_path.read_text()) if proof_path.exists() else None
    def receipt(name):
        p=run/'paced/closed-state'/name
        try:return json.loads(p.read_text()) if p.exists() else None
        except (OSError,ValueError) as e:return {'receipt_read_error':type(e).__name__}
    native=evidence_tests.NativeWindowsEvidenceReadTests.evidence
    passed=bool(result.wasSuccessful() and result.testsRun==expected and not result.skipped
        and proof and proof['result']=='PASS' and proof['source_reconciled']
        and proof['source_attempts']==3 and proof['native_audit_passed']
        and proof['two_fresh_replays_equal'] and (paced_only or os.name!='nt' or len(native)==3))
    report={'contract':'daily-hot-windows-evidence-read-qualification-v1',
        'result':'PASS' if passed else 'FAILED','tests':result.testsRun,
        'passed':result.testsRun-len(result.failures)-len(result.errors)-len(result.skipped),
        'failures':len(result.failures),'errors':len(result.errors),'skipped':len(result.skipped),
        'failed_tests':[t.id() for t,_ in result.failures+result.errors],
        'seconds':time.monotonic()-began,'platform':sys.platform,'python':list(sys.version_info[:3]),
        'test_scope':'original paced proof only; component evidence recorded separately' if paced_only else 'focused read/fence checks, native Windows sharing checks when Windows, original paced proof',
        'source':manifest['source'],'runtime_baseline':BASE,'runtime_changes':CHANGED,
        'windows_checks_passed':bool(passed and os.name=='nt' and not paced_only),
        'windows_read_retry_active':recovery_workers._WINDOWS_PROCESS_READS,
        'windows_native_proof':native,'windows_native_proof_qualified':bool(os.name=='nt' and len(native)==3 and passed and not paced_only),
        'read_retry_budget_seconds':.25,'read_retry_attempt_ceiling':26,
        'old_heartbeat_not_reused':True,'binding_and_age_checks_unchanged':True,
        'original_progress_seconds':3,'original_credential_seconds':8,
        'original_replacement_hold_seconds':15,'original_cleanup_seconds':10,
        'feed_interval_seconds':60,'periodic_stack_dumps':False,
        'original_test_source_sha256':TEST_SHA,'changed_test_only_flags':transform.changed,
        'monitor_exception':receipt('daily_hot_test/controller-monitor-error.json'),
        'operating_exception':receipt('daily_outer_test/operating-owner-error.json'),
        'paced_proof':proof,'prior_capacity_and_recovery_drills_repeated':False,
        'original_windows_commands_67_68_69_70':'FAILED; preserved',
        'original_io_ledger_change_and_native_crash_causes_resolved':False,
        'network':'denied','actual_vault_access':False,'actual_broker_sdk_used':False,
        'production_changes':False,'production_hot_enabled':False,'live_launch_available':False,
        'proposed_values_adopted':False,'operating_release_qualified':False,
        'provider_capacity_qualified':False,'full_day_capacity_qualified':False}
    (run/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2),flush=True);print('Saved report:',run/'verification.json',flush=True)
    return 0 if passed else 1


if __name__=='__main__':
    try:
        if sys.argv[1:]!=['verify']:raise ValueError('Use the supplied offline verify command')
        raise SystemExit(verify(inventory()))
    except (OSError,ValueError,KeyError,TypeError) as error:
        print('Evidence-read qualification refused:',type(error).__name__,str(error),flush=True)
        raise SystemExit(70)
