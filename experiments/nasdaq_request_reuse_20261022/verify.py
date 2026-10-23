"""Bounded affected checks and optional native workload comparison, network denied."""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import socket
import sys
import time
import unittest
import uuid

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).parent
SUITES=('test_sampling_admission','test_sampling_policy','test_sampling_requests',
        'test_sampling_scaling','test_sampling_service','test_nasdaq_recovery','test_nasdaq_sampling',
        'test_coordinator_growth','test_history_cost','test_history_reconstruction',
        'test_sampling_membership','test_quote_observation_store','test_sampling_metadata_cost','test_sampling_payload_reader',
        'test_nasdaq_request_reuse','test_nasdaq_reuse_workload')

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output-root',type=Path,required=True)
    parser.add_argument('--workloads',action='store_true');args=parser.parse_args()
    def denied(*a,**kw):raise RuntimeError('Network denied in Nasdaq request-reuse qualification')
    socket.socket.connect=socket.socket.connect_ex=socket.create_connection=socket.getaddrinfo=denied
    sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tests'),str(ROOT/'experiments/sampling_promotion_20261016/market_data/src'),
        str(ROOT/'experiments/coordinator_history_reconstruction_20261022/native_tests'),
        str(ROOT/'experiments/coordinator_history_cost_20261022/native_tests')]
    suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(n) for n in SUITES)
    before=time.perf_counter();result=unittest.TextTestRunner(verbosity=1).run(suite)
    folder=args.output_root/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8])
    folder.mkdir(parents=True,exist_ok=False)
    report={'result':'PASS' if result.wasSuccessful() else 'FAILED','tests':result.testsRun,
        'seconds':time.perf_counter()-before,'network':'denied','production_access':False,
        'scope':'Changed Nasdaq reuse/store paths plus affected admission/replay/publication/native integration. Recovery transport and provider capacity are not qualified.',
        'suites':list(SUITES),'workloads':'NOT_REQUESTED'}
    if args.workloads and result.wasSuccessful():
        import importlib.util
        spec=importlib.util.spec_from_file_location('reuse_workload_run',HERE/'qualify.py')
        q=importlib.util.module_from_spec(spec);spec.loader.exec_module(q)
        try:
            workloads=q.run(folder/'workloads',samples=30)
            report['workloads']=workloads['result']
            if workloads['result']!='PASS':report['result']='FAILED'
        except Exception as exc:
            report.update(result='FAILED',workloads='FAILED',error_type=type(exc).__name__,error=str(exc))
    (folder/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2));print('Saved report:',folder/'verification.json')
    return 0 if report['result']=='PASS' else 1

if __name__=='__main__':raise SystemExit(main())
