"""Focused recovery allocation, future-slot preparation and cooperative-close gate."""
import argparse
from datetime import datetime,timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import platform
import socket
import sys
import time
import unittest
import uuid

ROOT=Path(__file__).resolve().parents[2];HERE=Path(__file__).resolve().parent
SUITES=(
    'test_live_recovery_boundaries',
    'test_profile_runtime.ProfileRuntimeTests',
    'test_profile_evidence.ProfileEvidenceTests',
    'test_supervised_hot_worker.ProgressReceiptTests',
    'test_hot_recovery_collector.HotRecoveryCollectorTests.test_quote_budget_does_not_reset_on_reopen',
    'test_hot_recovery_collector.HotRecoveryCollectorTests.test_unknown_dispatch_conservatively_consumes_budget',
    'test_hot_recovery_collector.HotRecoveryCollectorTests.test_window_and_late_slot_do_not_catch_up',
    'test_live_profile_boundaries.WorkerPreparationTests',
    'test_live_profile_boundaries.GoalBeforeCycleTests',
    'test_live_profile_boundaries.WorkerBudgetNotificationTests',
    'test_live_profile_process.NewEntryProcessTests.test_fresh_private_credentials_catalog_runtime_native_worker_and_bound_read_only_report',
    'test_integrated_runtime_process.RuntimeProcessTests.test_real_owned_worker_reaches_authenticated_completed_work_under_original_gates',
    'test_integrated_runtime_process.RuntimeProcessTests.test_credential_success_without_native_work_does_not_satisfy_three_second_gate',
    'test_outer_harness.OuterHarnessTests.test_reporter_deadline_is_independent_of_controller_completion',
    'test_outer_harness.OuterHarnessTests.test_stop_receipt_write_failure_still_stops_the_owned_child',
    'test_profile_observation.ProfileObservationTests.test_commit_without_ack_is_not_counted_but_its_permit_remains_charged',
    'test_profile_observation.ProfileObservationTests.test_observer_does_not_take_the_acquisition_writer_lease',
)


def main():
    p=argparse.ArgumentParser();p.add_argument('--output-root',type=Path,required=True);args=p.parse_args()
    def denied(*a,**kw):raise RuntimeError('Network denied in recovery-fix qualification')
    socket.socket.connect=socket.socket.connect_ex=socket.create_connection=socket.getaddrinfo=denied
    sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tests'),
        str(ROOT/'experiments/sampling_promotion_20261016/market_data/src'),
        str(ROOT/'experiments/authenticated_startup_20261023/reference_mb_tools/src')]
    before=json.loads((HERE/'accepted_before_recovery_sha256.json').read_text())
    changed=json.loads((HERE/'changed_runtime_source_sha256.json').read_text())
    expected={'src/mb_watchlist_coordinator/'+n+'.py' for n in ('integrated_runtime','profile_runtime','outer_harness')}
    if len(before)!=72 or set(changed)!=expected:raise ValueError('Reviewed source set differs')
    for name,sha in before.items():
        actual=hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
        if actual!=changed.get(name,sha) or name in changed and actual==sha:
            raise ValueError('Reviewed runtime/native/helper bytes differ')
    spec=importlib.util.spec_from_file_location('recovery_evidence_result',ROOT/'experiments/live_profile_entry_20261024/verify.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    folder=args.output_root/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8]);folder.mkdir(parents=True)
    began=time.perf_counter()
    result=unittest.TextTestRunner(verbosity=1,resultclass=lambda *a,**kw:
        module.EvidenceResult(*a,evidence_root=folder/'failure_evidence',**kw)).run(
            unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(n) for n in SUITES))
    passed=result.wasSuccessful() and not result.skipped
    report={'contract':'live-hot-recovery-fix-offline-qualification-v1','result':'PASS' if passed else 'FAILED',
        'tests':result.testsRun,'passed':result.testsRun-len(result.skipped)-len(result.failures)-len(result.errors),
        'skipped':len(result.skipped),'failures':len(result.failures),'errors':len(result.errors),
        'failed_tests':[str(t) for t,_ in result.failures+result.errors],
        'seconds':time.perf_counter()-began,'python':list(sys.version_info[:3]),
        'executable':str(Path(sys.executable).resolve()),'platform':platform.platform(),
        'network':'denied','actual_vault_access':False,'production_access':False,'real_feed_directory_or_broker_requests':0,
        'suites':list(SUITES),'accepted_runtime_source_files_unchanged':69,'changed_runtime_source_sha256':changed,
        'raw_audit_replay_goal_and_outer_verdict_rules_unchanged':True,
        'scope':'Recovery-only queued request delivery after the same validated dated/later CURRENT cutover, genuinely empty native roster before normal admission; original 15s replacement hold and 3s preparation before a fixed future slot; native collector bytes unchanged; cooperative close uses nine of the original ten cleanup seconds with one reserved for scope confirmation; original goals, permits, dispatch deadlines, raw audit, replays and reporting rules. Synthetic APIs only; no live provider/production profile.',
        'failure_evidence_files':result.files,'success_evidence_files':result.success_files,
        'unrelated_accepted_suites_repeated':False,'prior_failed_results_retained':True,
        'ordinary_live_profile_result_retained':'PASS_WITH_WARNINGS','original_recovery_command52_result':'FAILED',
        'windows_acceptance':'OPERATOR_RESULT_REQUIRED','live_profiles_run_with_correction':False,
        'remaining':['Windows command56 complete result and actual CMD prompt return',
            'fresh complete production health before separately invoked corrected recovery command52',
            'full recovery evidence review; minimum operating/adoption work, manual membership and agreed read-only Overlay']}
    (folder/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2));print('Saved report:',folder/'verification.json')
    return 0 if passed else 1


if __name__=='__main__':raise SystemExit(main())
