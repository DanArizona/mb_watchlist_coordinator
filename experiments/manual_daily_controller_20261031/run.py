"""Focused offline combined-controller qualification; no live launch entry."""
from datetime import datetime,timezone
import hashlib,json,os
from pathlib import Path
import socket,sys,time,unittest
from uuid import uuid4

ROOT=Path(__file__).resolve().parent
sys.dont_write_bytecode=True
sys.path[:0]=[str(ROOT/'coordinator/src'),str(ROOT/'market_data/src'),str(ROOT/'coordinator/tests')]
CHECKS=45


def guard():
    manifest=json.loads((ROOT/'SOURCE_INVENTORY.json').read_text())
    if manifest['contract']!='nasdaq-manual-daily-controller-source-v1':raise ValueError('Exact combined candidate source required')
    for name,sha in manifest['files'].items():
        p=ROOT/name
        if p.is_symlink()or hashlib.sha256(p.read_bytes()).hexdigest()!=sha:raise ValueError('Combined source bytes differ')
    return manifest


def deny_network():
    def denied(*args,**kwargs):raise OSError('Network denied in offline combined-controller qualification')
    socket.socket.connect=socket.socket.connect_ex=socket.create_connection=socket.getaddrinfo=denied


def verify(manifest):
    root=ROOT/'runs'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ_')+uuid4().hex[:8])
    root.mkdir(parents=True,exist_ok=False);began=time.monotonic()
    print('OFFLINE Nasdaq/manual daily composition. Synthetic credentials, SDK, files and real owned processes only.',flush=True)
    print('45 focused checks and a 15-second readable GUI preview. No password, API or production access. Allow about 90 seconds.',flush=True)
    os.environ['MB_MANUAL_DAILY_PROOF_DIR']=str(root/'owned')
    suite=unittest.defaultTestLoader.loadTestsFromNames(['test_daily_manual.DailyManualTests',
        'test_daily_manual_owned.DailyManualOwnedTests','test_manual_membership_window.ManualWindowTests','test_daily_admission'])
    if suite.countTestCases()!=CHECKS:raise ValueError('Combined focused test count differs')
    class Log:
        def __init__(self,out):self.out=out
        def write(self,value):self.out.write(value);sys.stdout.write(value)
        def flush(self):self.out.flush();sys.stdout.flush()
    with(root/'tests.log').open('w',encoding='utf-8')as out:
        result=unittest.TextTestRunner(stream=Log(out),verbosity=2).run(suite)
    proof=None
    path=root/'owned/combined-proof.json'
    if path.exists():proof=json.loads(path.read_text())
    gui={'result':'NOT_EXERCISED','reason':'No local desktop; actual Windows preview remains due'}
    if result.wasSuccessful()and(os.name=='nt'or os.environ.get('DISPLAY')):
        try:
            from manual_preview import gui_proof
            gui=gui_proof(root)
        except Exception as error:gui={'result':'FAILED','error_type':type(error).__name__,'detail':str(error)}
    guard()
    passed=result.wasSuccessful()and not result.skipped and proof is not None and proof['result']=='PASS'and(os.name!='nt'or gui['result']=='PASS')
    report={'contract':'nasdaq-manual-daily-controller-offline-qualification-v1','result':'PASS'if passed else'FAILED',
        'tests':result.testsRun,'passed':result.testsRun-len(result.failures)-len(result.errors)-len(result.skipped),
        'failures':len(result.failures),'errors':len(result.errors),'skipped':len(result.skipped),
        'failed_tests':[t.id()for t,_ in result.failures+result.errors],
        'seconds':time.monotonic()-began,'platform':sys.platform,'python':list(sys.version_info[:3]),
        'windows_checks_passed':bool(passed and os.name=='nt'),'source':manifest['source'],
        'source_inventory_sha256':hashlib.sha256((ROOT/'SOURCE_INVENTORY.json').read_bytes()).hexdigest(),
        'profile':'manual-40-v1','sources':['nasdaq-shared-daily','operator:masterbot'],
        'shared_hot_session_limit':40,'shared_focus_additions_session_limit':40,'capacity_nonrecycling':True,
        'manual_promotion_scope':'verified opening Uni only; outside-Uni manual broker integration remains next',
        'owned_proof':proof,'gui_proof':gui,'network':'denied','actual_vault_access':False,
        'actual_broker_sdk_used':False,'production_changes':False,'production_manual_launch_available':False,
        'p85_source_settings_or_approval_changed':False,'unchanged_long_capacity_source_recovery_drills_repeated':False,
        'provider_capacity_qualified':False,'full_day_capacity_qualified':False,
        'remaining':['Windows result and actual returned CMD prompt','Outside-Uni manual identity integration',
            'Reviewed manual-enabled production delivery and activation before live use']}
    (root/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2));print('Saved report:',root/'verification.json',flush=True)
    return 0 if passed else 1


if __name__=='__main__':
    try:
        manifest=guard();deny_network()
        if sys.argv[1:]!=['verify']:raise ValueError('Use verify; no production launch is exposed')
        raise SystemExit(verify(manifest))
    except Exception as error:
        print('Combined controller qualification refused:',type(error).__name__,str(error),flush=True)
        raise SystemExit(1)
