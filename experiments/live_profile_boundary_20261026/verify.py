"""Affected first-slot, immutable catalog, profile-decision and worker-stop checks."""
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
    'test_live_profile_boundaries',
    'test_integrated_catalog',
    'test_profile_runtime.ProfileRuntimeTests',
    'test_profile_evidence.ProfileEvidenceTests',
    'test_live_profile.ControllerTests',
    'test_live_profile_launcher.PinnedRoleDispatchTests',
    'test_live_profile_process.NewEntryProcessTests.test_fresh_private_credentials_catalog_runtime_native_worker_and_bound_read_only_report',
    'test_profile_observation.ProfileObservationTests.test_commit_without_ack_is_not_counted_but_its_permit_remains_charged',
    'test_profile_observation.ProfileObservationTests.test_observer_does_not_take_the_acquisition_writer_lease',
    'test_integrated_runtime.IntegratedRuntimeTests.test_no_new_authentication_or_network_before_original_T0',
    'test_integrated_runtime.IntegratedRuntimeTests.test_changed_catalog_blocks_before_source_delivery',
    'test_integrated_runtime.IntegratedRuntimeTests.test_all_stop_and_lifetime_limits_remain_original',
)

def main():
    p=argparse.ArgumentParser();p.add_argument('--output-root',type=Path,required=True);args=p.parse_args()
    def denied(*a,**kw):raise RuntimeError('Network denied in boundary-fix qualification')
    socket.socket.connect=socket.socket.connect_ex=socket.create_connection=socket.getaddrinfo=denied
    sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tests'),
        str(ROOT/'experiments/sampling_promotion_20261016/market_data/src'),
        str(ROOT/'experiments/authenticated_startup_20261023/reference_mb_tools/src')]
    before=json.loads((HERE/'accepted_before_boundary_sha256.json').read_text())
    changed=json.loads((HERE/'changed_runtime_source_sha256.json').read_text())
    expected_changed={'src/mb_watchlist_coordinator/'+name+'.py' for name in
        ('integrated_catalog','integrated_runtime','live_profile','live_profile_entry','profile_runtime')}
    if len(before)!=72 or set(changed)!=expected_changed:raise ValueError('Reviewed source set differs')
    for name,sha in before.items():
        actual=hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
        if actual!=changed.get(name,sha) or name in changed and actual==sha:
            raise ValueError('Reviewed runtime/native/helper bytes differ')
    original=ROOT/'experiments/live_profile_entry_20261024/verify.py'
    spec=importlib.util.spec_from_file_location('entry_evidence_result',original)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    folder=args.output_root/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8]);folder.mkdir(parents=True)
    began=time.perf_counter()
    result=unittest.TextTestRunner(verbosity=1,resultclass=lambda *a,**kw:
        module.EvidenceResult(*a,evidence_root=folder/'failure_evidence',**kw)).run(
            unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(n) for n in SUITES))
    report={'contract':'live-hot-boundary-offline-qualification-v1',
        'result':'PASS' if result.wasSuccessful() else 'FAILED','tests':result.testsRun,
        'passed':result.testsRun-len(result.skipped)-len(result.failures)-len(result.errors),
        'skipped':len(result.skipped),'failures':len(result.failures),'errors':len(result.errors),
        'failed_tests':[str(t) for t,_ in result.failures+result.errors],
        'seconds':time.perf_counter()-began,'python':list(sys.version_info[:3]),
        'executable':str(Path(sys.executable).resolve()),'platform':platform.platform(),
        'network':'denied','actual_vault_access':False,'production_access':False,
        'real_feed_directory_or_broker_requests':0,'suites':list(SUITES),
        'accepted_runtime_source_files_unchanged':67,'changed_runtime_source_sha256':changed,
        'raw_audit_replay_goal_and_outer_verdict_rules_unchanged':True,
        'scope':'Prepare exact owned authenticated worker before original T0 without early feed/quote dispatch; native first empty-slot coverage and 3s progress/8s credentials; exact full-byte catalog validation without repeated semantic parsing; goal observation before another Coordinator cycle; immediate nonce-bound worker budget-stop notification; unchanged native audit/replays, invalid/unacknowledged/late-goal rejection and recovery hold; affected synthetic native wiring. No live provider/production profile.',
        'failure_evidence_files':result.files,'success_evidence_files':result.success_files,
        'unrelated_accepted_suites_repeated':False,'prior_failed_results_retained':True,
        'original_command51_results':['FAILED','FAILED'],
        'windows_acceptance':'OPERATOR_RESULT_REQUIRED','live_profiles_run_with_correction':False,
        'remaining':['Windows command55 complete result and actual CMD prompt return',
            'fresh production health before separately invoked corrected ordinary command51',
            'full ordinary evidence review before separate recovery command52',
            'minimum operating/adoption work, manual membership and agreed read-only Overlay']}
    (folder/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2));print('Saved report:',folder/'verification.json')
    return 0 if result.wasSuccessful() else 1

if __name__=='__main__':raise SystemExit(main())
