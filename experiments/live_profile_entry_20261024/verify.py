"""Affected entry/launcher qualification, synthetic APIs and owned children."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import platform
import socket
import sys
import time
import unittest
import uuid

ROOT=Path(__file__).resolve().parents[2]
SUITES=('test_live_profile','test_live_profile_launcher','test_live_profile_process')


class EvidenceResult(unittest.TextTestResult):
    def __init__(self,*a,evidence_root,**kw):
        super().__init__(*a,**kw);self.root=evidence_root;self.files=[];self.success_files=[]
    def capture(self,test):
        value=getattr(test,'failure_evidence',None)
        if value is None:return
        self.root.mkdir(parents=True,exist_ok=True)
        name=f'{len(self.files)+1:03d}-'+hashlib.sha256(test.id().encode()).hexdigest()[:12]+'.json'
        (self.root/name).write_text(json.dumps({'test':test.id(),'evidence':value},indent=2)+'\n');self.files.append(name)
    def addFailure(self,test,err):self.capture(test);super().addFailure(test,err)
    def addError(self,test,err):self.capture(test);super().addError(test,err)
    def addSuccess(self,test):
        value=getattr(test,'qualification_evidence',None)
        if value is not None:
            directory=self.root.parent/'success_evidence';directory.mkdir(parents=True,exist_ok=True)
            name=hashlib.sha256(test.id().encode()).hexdigest()[:12]+'.json'
            (directory/name).write_text(json.dumps({'test':test.id(),'evidence':value},indent=2)+'\n');self.success_files.append(name)
        super().addSuccess(test)


def main():
    p=argparse.ArgumentParser();p.add_argument('--output-root',type=Path,required=True);args=p.parse_args()
    def denied(*a,**kw):raise RuntimeError('Network denied in live-entry offline qualification')
    socket.socket.connect=socket.socket.connect_ex=socket.create_connection=socket.getaddrinfo=denied
    sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tests'),
        str(ROOT/'experiments/sampling_promotion_20261016/market_data/src'),
        str(ROOT/'experiments/authenticated_startup_20261023/reference_mb_tools/src')]
    pin=json.loads((Path(__file__).parent/'accepted_runtime_source_sha256.json').read_text())
    if any(hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=sha for name,sha in pin.items()):
        raise ValueError('Accepted runtime source changed')
    folder=args.output_root/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8]);folder.mkdir(parents=True)
    began=time.perf_counter()
    result=unittest.TextTestRunner(verbosity=1,resultclass=lambda *a,**kw:EvidenceResult(*a,evidence_root=folder/'failure_evidence',**kw)).run(
        unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(n) for n in SUITES))
    report={'result':'PASS' if result.wasSuccessful() else 'FAILED','tests':result.testsRun,
        'passed':result.testsRun-len(result.skipped)-len(result.failures)-len(result.errors),
        'skipped':len(result.skipped),'failures':len(result.failures),'errors':len(result.errors),
        'failed_tests':[str(t) for t,_ in result.failures+result.errors],
        'seconds':time.perf_counter()-began,'network':'denied','production_access':False,
        'python':list(sys.version_info[:3]),'executable':str(Path(sys.executable).resolve()),'platform':platform.platform(),
        'suites':list(SUITES),'accepted_runtime_source_files_unchanged':len(pin),
        'scope':'New human credential-bound fresh live entry, pinned role/argv dispatch, installed-helper recheck per worker, source/host offline gate, sequential invocation lease, bound stop requests, native bootstrap/runtime ordering, independent pipe deadline, owned synthetic native quote and separate read-only final audit/two replays. Synthetic APIs only. Feed reconciliation in the quote proof is logical; native child/credential/progress/cleanup work is elapsed. One quote is a wiring proof, not a completed 30 or 12+24 profile.',
        'actual_vault_access':False,'real_feed_directory_or_broker_requests':0,
        'failure_evidence_files':result.files,'success_evidence_files':result.success_files,'unchanged_accepted_suites_repeated':False,
        'prior_failed_results_retained':True,'windows_acceptance':'OPERATOR_RESULT_REQUIRED',
        'credential_bound_entry_current_host_offline_qualified':result.wasSuccessful(),
        'installed_live_integration_or_capacity_qualified':False,
        'manual_profile_controller_resume_exposed':False,
        'remaining':['Windows command50 final result and actual CMD prompt return',
            'separately invoked bounded live ordinary and owned-worker recovery profiles',
            'read-only Overlay adapter','production adoption and broader capacity']}
    (folder/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2));print('Saved report:',folder/'verification.json')
    return 0 if result.wasSuccessful() else 1


if __name__=='__main__':raise SystemExit(main())
