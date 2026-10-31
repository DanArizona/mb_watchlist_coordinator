"""Offline manual outside-Uni qualification; no production start command."""
from datetime import datetime,timezone
import hashlib,json,os
from pathlib import Path
import socket,sys,time,unittest
from uuid import uuid4

ROOT=Path(__file__).resolve().parent
sys.dont_write_bytecode=True
sys.path[:0]=[str(ROOT/'coordinator/src'),str(ROOT/'market_data/src'),str(ROOT/'coordinator/tests')]
CHECKS=71


def guard():
    manifest=json.loads((ROOT/'SOURCE_INVENTORY.json').read_text())
    if manifest['contract']!='manual-shared-broker-identity-source-v1':raise ValueError('Exact manual identity candidate required')
    for name,sha in manifest['files'].items():
        path=ROOT/name
        if path.is_symlink()or hashlib.sha256(path.read_bytes()).hexdigest()!=sha:raise ValueError('Source bytes differ')
    return manifest


def deny_network():
    def denied(*args,**kwargs):raise OSError('Network denied in offline manual identity qualification')
    socket.socket.connect=socket.socket.connect_ex=socket.create_connection=socket.getaddrinfo=denied


def verify(manifest):
    root=ROOT/'runs'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ_')+uuid4().hex[:8])
    root.mkdir(parents=True,exist_ok=False);started=time.monotonic()
    print('OFFLINE manual outside-Uni broker integration. Synthetic credentials, SDK and journals; real owned processes.',flush=True)
    print('71 focused checks, a forced 20-manual/20-Nasdaq burst and a 15-second readable GUI preview. Allow about 90 seconds.',flush=True)
    print('No password, API or production changes. Approved p85 and accepted p92 packets are unchanged.',flush=True)
    os.environ['MB_MANUAL_IDENTITY_PROOF_DIR']=str(root/'owned')
    os.environ['MB_MANUAL_IDENTITY_BURST_PROOF']=str(root/'mixed-burst.json')
    suite=unittest.defaultTestLoader.loadTestsFromNames(['test_daily_manual_identity.DailyManualIdentityTests',
        'test_daily_manual_identity_owned.ManualIdentityOwnedTests','test_daily_manual.DailyManualTests',
        'test_manual_membership_window.ManualWindowTests','test_daily_admission'])
    if suite.countTestCases()!=CHECKS:raise ValueError('Focused count differs')
    class Log:
        def __init__(self,out):self.out=out
        def write(self,value):self.out.write(value);sys.stdout.write(value)
        def flush(self):self.out.flush();sys.stdout.flush()
    with(root/'tests.log').open('w',encoding='utf-8')as out:
        result=unittest.TextTestRunner(stream=Log(out),verbosity=2).run(suite)
    def saved(path):return json.loads(path.read_text())if path.exists()else None
    owned=saved(root/'owned/manual-identity-proof.json');burst=saved(root/'mixed-burst.json')
    gui={'result':'NOT_EXERCISED','reason':'Actual Windows GUI remains due'}
    if result.wasSuccessful()and(os.name=='nt'or os.environ.get('DISPLAY')):
        try:
            from manual_identity_preview import gui_proof
            gui=gui_proof(root)
        except Exception as error:gui={'result':'FAILED','error_type':type(error).__name__,'detail':str(error)}
    guard()
    passed=result.wasSuccessful()and not result.skipped and owned is not None and owned['result']=='PASS'and burst is not None and burst['result']=='PASS'and(os.name!='nt'or gui['result']=='PASS')
    report={'contract':'manual-shared-broker-identity-offline-qualification-v1','result':'PASS'if passed else'FAILED',
        'tests':result.testsRun,'passed':result.testsRun-len(result.failures)-len(result.errors)-len(result.skipped),
        'failures':len(result.failures),'errors':len(result.errors),'skipped':len(result.skipped),
        'failed_tests':[t.id()for t,_ in result.failures+result.errors],'seconds':time.monotonic()-started,
        'platform':sys.platform,'python':list(sys.version_info[:3]),'windows_checks_passed':bool(passed and os.name=='nt'),
        'source':manifest['source'],'source_inventory_sha256':hashlib.sha256((ROOT/'SOURCE_INVENTORY.json').read_bytes()).hexdigest(),
        'profile':'manual-identity-40-v1','shared_identity_limits':{'quote_calls':120,'calls_per_symbol':3,'minimum_spacing_seconds':2,'distinct_authorized_symbols':40},
        'clock_scope':'Logical future/advanced fixture session only; owned/native checks include actual elapsed time. No live clock override added.',
        'shared_membership_limits':{'hot_symbols':40,'focus_additions':40,'outside_uni_additions':40,'capacity_nonrecycling':True},
        'manual_promotion_scope':'Opening Uni without a lookup; other exact catalog symbols after retained shared broker confirmation',
        'pending_withdrawal_supported':True,'unknown_lookup_retried':False,
        'owned_proof':owned,'mixed_burst_proof':burst,'gui_proof':gui,
        'network':'denied','actual_vault_access':False,'actual_broker_sdk_used':False,'actual_provider_used':False,
        'production_changes':False,'production_start_command_generated':False,'p85_source_settings_or_approval_changed':False,
        'prior_p92_windows_acceptance':'ACCEPTED 45/45 retained; affected regressions included',
        'unchanged_long_history_feed_recovery_or_provider_drills_repeated':False,
        'provider_capacity_qualified':False,'full_day_capacity_qualified':False,
        'remaining':['Windows result and actual returned CMD prompt','Concrete manual-enabled operating delivery/review and activation before live use']}
    (root/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2));print('Saved report:',root/'verification.json',flush=True)
    return 0 if passed else 1


if __name__=='__main__':
    try:
        manifest=guard();deny_network()
        if sys.argv[1:]!=['verify']:raise ValueError('Use verify; no production start is exposed')
        raise SystemExit(verify(manifest))
    except Exception as error:
        print('Manual identity qualification refused:',type(error).__name__,str(error),flush=True)
        raise SystemExit(1)
