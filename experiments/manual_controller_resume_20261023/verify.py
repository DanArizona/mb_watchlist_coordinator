"""Offline explicit manual-controller reopen and affected boundary checks."""
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
SUITES=('test_controller_resume','test_resume_entry','test_controller_resume_process',
    'test_supervised_hot_worker',
    'test_integrated_runtime.IntegratedRuntimeTests.test_existing_partial_runtime_is_not_a_fresh_reopen',
    'test_integrated_runtime.IntegratedRuntimeTests.test_an_uninitialized_second_instance_cannot_close_the_owners_client',
    'test_integrated_runtime_process.RuntimeProcessTests.test_three_second_gate_wins_over_eight_second_credential_budget_independently',
    'test_integrated_runtime_process.RuntimeProcessTests.test_credential_success_without_native_work_does_not_satisfy_three_second_gate')


def main():
    p=argparse.ArgumentParser();p.add_argument('--output-root',type=Path,required=True);args=p.parse_args()
    def denied(*a,**kw):raise RuntimeError('Network denied in manual-controller resume qualification')
    socket.socket.connect=socket.socket.connect_ex=socket.create_connection=socket.getaddrinfo=denied
    sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tests'),
        str(ROOT/'experiments/sampling_promotion_20261016/market_data/src'),
        str(ROOT/'experiments/hot_collector_recovery_20261023/native_tests'),
        str(ROOT/'experiments/authenticated_startup_20261023/reference_mb_tools/src')]
    from resume_failure_evidence import ManualFailureEvidenceResult
    pin=json.loads((Path(__file__).parent/'accepted_runtime_source_sha256.json').read_text())
    unchanged=all(hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==sha for name,sha in pin.items())
    if not unchanged:raise RuntimeError('Earlier accepted runtime/reference source differs')
    folder=args.output_root/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8])
    folder.mkdir(parents=True,exist_ok=False)
    start=time.perf_counter()
    result=unittest.TextTestRunner(verbosity=1,resultclass=lambda *a,**kw:
        ManualFailureEvidenceResult(*a,evidence_root=folder/'failure_evidence',**kw)).run(unittest.TestSuite(
            unittest.defaultTestLoader.loadTestsFromName(n) for n in SUITES))
    report={'result':'PASS' if result.wasSuccessful() else 'FAILED','tests':result.testsRun,
        'passed':result.testsRun-len(result.skipped)-len(result.failures)-len(result.errors),
        'skipped':len(result.skipped),'failures':len(result.failures),'errors':len(result.errors),
        'skipped_tests':[{'test':str(t),'reason':reason} for t,reason in result.skipped],
        'failed_tests':[str(t) for t,_ in result.failures+result.errors],
        'seconds':time.perf_counter()-start,'network':'denied','production_access':False,
        'python':list(sys.version_info[:3]),'executable':str(Path(sys.executable).resolve()),'platform':platform.platform(),
        'suites':list(SUITES),
        'scope':'Explicit new-human private-handoff reopen of an already initialized catalog-bound runtime, original proposal/dependency/session/window/source/native bindings, cumulative permits and generation history, request/publication/assembled-response recovery, unknown charged dispatches, lease-based orphan fencing and future-only native work. Synthetic credentials/SDK/HTTP and actual process exits/role leases only. Logical 59+1 native-budget workload is distinct from elapsed process drills. Not installed/live authentication, an independently preempting outer/profile harness, live acquisition/recovery, Overlay, production adoption or capacity.',
        'accepted_runtime_reference_source_files_unchanged':len(pin),
        'prior_accepted_runtime_sources_changed':False,
        'new_runtime_source_paths':['src/mb_watchlist_coordinator/controller_resume.py','src/mb_watchlist_coordinator/resume_entry.py'],
        'failure_evidence_files':result.evidence_files,'failure_evidence_write_errors':result.evidence_write_errors,
        'actual_vault_access':False,'real_feed_directory_or_broker_requests':0,
        'pinned_mb_tools_interfaces_exercised':True,'installed_sdk_or_live_authentication_qualified':False,
        'windows_acceptance':'OPERATOR_RESULT_REQUIRED',
        'manual_controller_resume_offline_qualified':result.wasSuccessful(),
        'outer_controller_profile_harness_qualified':False,'unattended_controller_bootstrap':False,
        'limits':{'worker_startup_seconds':3,'worker_stale_seconds':3,'credential_timeout_seconds':8,
            'manual_reopen_preparation_seconds':60,'original_active_window_seconds':720,
            'hot_quote_permits':60,'identity_quote_permits':3,'worker_starts':3,
            'directory_source_permits':2,'feed_attempts':10,'feed_completion_spacing_seconds':60},
        'original_failed_verdicts_retained':True,
        'remaining':['Windows operator validation and actual CMD prompt return',
            'owned outer-controller hard deadlines/shutdown and live profile goals/coverage/audit harness',
            'separately invoked live acquisition and worker recovery profiles',
            'read-only Overlay adapter','production adoption and broader capacity']}
    (folder/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2));print('Saved report:',folder/'verification.json')
    return 0 if result.wasSuccessful() else 1


if __name__=='__main__':raise SystemExit(main())
