"""Frozen offline feed/collection qualification. No live or install role."""
from datetime import datetime,timezone
import hashlib,json,os,socket,sys,time,unittest
from pathlib import Path
from uuid import uuid4

ROOT=Path(__file__).resolve().parent


def inventory():
    manifest=json.loads((ROOT/'SOURCE_INVENTORY.json').read_text())
    expected=manifest['files']
    actual={p.relative_to(ROOT).as_posix() for p in ROOT.rglob('*') if p.is_file()
        and p.relative_to(ROOT).parts[0]!='runs' and p!=ROOT/'SOURCE_INVENTORY.json'}
    if actual!=set(expected):raise ValueError('Source set differs')
    for name,sha in expected.items():
        p=ROOT/name
        if p.is_symlink() or not p.resolve().is_relative_to(ROOT) or hashlib.sha256(p.read_bytes()).hexdigest()!=sha:
            raise ValueError('Source bytes differ')
    return manifest


def verify(manifest):
    class OfflineSocket(socket.socket):
        def __new__(cls,*args,**kwargs):raise OSError('Network denied in daily collection qualification')
    def denied(*args,**kwargs):raise OSError('Network denied in daily collection qualification')
    socket.socket=OfflineSocket;socket.create_connection=socket.getaddrinfo=denied
    run=ROOT/'runs'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ_')+uuid4().hex[:8])
    run.mkdir(parents=True,exist_ok=False)
    os.environ['MB_DAILY_COLLECTION_PROOF_DIR']=str(run/'native-proof')
    names=['test_daily_collector','test_daily_feed','test_daily_source',
        'test_hot_recovery_collector','test_nasdaq_feed_recovery']
    print('OFFLINE daily feed/collection APIs: synthetic state only; no password, API or production changes.',flush=True)
    started=time.monotonic()
    result=unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.loadTestsFromNames(names))
    inventory()
    proof_path=run/'native-proof/proof.json'
    proof=json.loads(proof_path.read_text()) if proof_path.exists() else None
    passed=result.wasSuccessful() and not result.skipped and bool(proof and proof['result']=='PASS')
    report={'contract':'daily-hot-collection-offline-qualification-v1',
        'result':'PASS' if passed else 'FAILED','tests':result.testsRun,
        'passed':result.testsRun-len(result.failures)-len(result.errors)-len(result.skipped),
        'errors':len(result.errors),'failures':len(result.failures),'skipped':len(result.skipped),
        'failed_tests':[t.id() for t,e in result.failures+result.errors],
        'seconds':time.monotonic()-started,'source':manifest['source'],
        'python':list(sys.version_info[:3]),'platform':sys.platform,
        'windows_checks_passed':bool(passed and os.name=='nt'),
        'network':'denied','actual_vault_access':False,'production_changes':False,
        'daily_feed_and_collector_included':True,'authenticated_controller_included':False,
        'live_launch_available':False,'proposed_values_adopted':False,
        'full_day_capacity_qualified':False,'native_proof':proof,
        'remaining':['Owned authenticated daily controller and read-only native worker validation',
            'Original credential/progress gates, replacement hold, manual resume and cleanup/reporting',
            'Hot status/alerts, full-day capacity, deployment/settings review and activation approval',
            'Closely following manual membership controls and read-only Overlay']}
    (run/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2),flush=True)
    print('Saved report:',run/'verification.json',flush=True)
    return 0 if passed else 1


def main():
    manifest=inventory()
    sys.dont_write_bytecode=True;os.environ['PYTHONDONTWRITEBYTECODE']='1'
    sys.path[:0]=[str(ROOT/'coordinator/src'),str(ROOT/'market_data/src'),str(ROOT/'coordinator/tests')]
    return verify(manifest) if sys.argv[1:]==['verify'] else 64


if __name__=='__main__':
    try:raise SystemExit(main())
    except (OSError,ValueError,KeyError,TypeError) as error:
        print('Daily collection packet refused:',type(error).__name__,flush=True)
        raise SystemExit(70)
