"""Focused offline outer-controller/profile qualification; no live mode."""
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
SUITES=('test_outer_deadline','test_outer_harness','test_profile_evidence','test_profile_runtime')


class EvidenceResult(unittest.TextTestResult):
    def __init__(self,*a,evidence_root,**kw):
        super().__init__(*a,**kw);self.root=evidence_root;self.files=[];self.write_errors=0
    def capture(self,test):
        value=getattr(test,'failure_evidence',None)
        if value is None:return
        try:
            self.root.mkdir(parents=True,exist_ok=True)
            name=f'{len(self.files)+1:03d}-'+hashlib.sha256(test.id().encode()).hexdigest()[:12]+'.json'
            (self.root/name).write_text(json.dumps({'test':test.id(),'evidence':value},indent=2)+'\n');self.files.append(name)
        except Exception:self.write_errors+=1
    def addFailure(self,test,err):self.capture(test);super().addFailure(test,err)
    def addError(self,test,err):self.capture(test);super().addError(test,err)


def main():
    p=argparse.ArgumentParser();p.add_argument('--output-root',type=Path,required=True);args=p.parse_args()
    def denied(*a,**kw):raise RuntimeError('Network denied in outer/profile offline qualification')
    socket.socket.connect=socket.socket.connect_ex=socket.create_connection=socket.getaddrinfo=denied
    sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tests'),
        str(ROOT/'experiments/sampling_promotion_20261016/market_data/src'),
        str(ROOT/'experiments/authenticated_startup_20261023/reference_mb_tools/src')]
    pin=json.loads((Path(__file__).parent/'accepted_runtime_source_sha256.json').read_text())
    if not all(hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==sha for name,sha in pin.items()):
        raise RuntimeError('Accepted command46 runtime source differs')
    folder=args.output_root/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8]);folder.mkdir(parents=True,exist_ok=False)
    begin=time.perf_counter()
    result=unittest.TextTestRunner(verbosity=1,resultclass=lambda *a,**kw:
        EvidenceResult(*a,evidence_root=folder/'failure_evidence',**kw)).run(unittest.TestSuite(
            unittest.defaultTestLoader.loadTestsFromName(name) for name in SUITES))
    report={'result':'PASS' if result.wasSuccessful() else 'FAILED','tests':result.testsRun,
        'passed':result.testsRun-len(result.skipped)-len(result.failures)-len(result.errors),
        'skipped':len(result.skipped),'failures':len(result.failures),'errors':len(result.errors),
        'skipped_tests':[{'test':str(t),'reason':why} for t,why in result.skipped],
        'failed_tests':[str(t) for t,_ in result.failures+result.errors],
        'seconds':time.perf_counter()-begin,'network':'denied','production_access':False,
        'python':list(sys.version_info[:3]),'executable':str(Path(sys.executable).resolve()),'platform':platform.platform(),
        'suites':list(SUITES),'accepted_runtime_reference_source_files_unchanged':len(pin),
        'scope':'Owned gated controller/reporting process scopes, frozen original window and new-human resume preparation, independent active/cleanup/report deadlines, durable one-fault intent/hold policy, logical native 30 and 12+24 profile workloads with real raw audit/two replays, and one elapsed owned controller/authenticated synthetic native quote/read-only reporter integration. Windows-only Job Object orphan/owner-death tests are explicitly skipped on other hosts. No installed/live client, full-goal elapsed/live profile, public HTTP, production adoption or capacity claim.',
        'failure_evidence_files':result.files,'failure_evidence_write_errors':result.write_errors,
        'actual_vault_access':False,'real_feed_directory_or_broker_requests':0,
        'unchanged_accepted_suites_repeated':False,'live_launcher_exposed':False,
        'windows_acceptance':'OPERATOR_RESULT_REQUIRED',
        'outer_profile_paths_current_host_qualified':result.wasSuccessful(),
        'windows_job_object_qualified':bool(result.wasSuccessful() and sys.platform=='win32'),
        'credential_bound_live_profile_entry_qualified':False,
        'remaining':['Windows command48 final result and actual CMD prompt return',
            'credential-bound live profile entry and separate operator launchers with affected offline qualification',
            'separately invoked bounded live ordinary and owned-worker recovery profiles',
            'read-only Overlay adapter','production adoption and broader capacity']}
    (folder/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2));print('Saved report:',folder/'verification.json')
    return 0 if result.wasSuccessful() else 1


if __name__=='__main__':raise SystemExit(main())
