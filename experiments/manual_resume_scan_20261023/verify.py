"""Offline corrective post-close artifact-scan and redaction qualification."""
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
SUITES=('test_saved_artifact_scan','test_resume_entry',
    'test_controller_resume.ManualResumeTests.test_interruption_after_credentials_keeps_failed_attempt_and_new_nonce_can_reopen',
    'test_controller_resume.ManualResumeTests.test_reopens_original_bindings_without_registering_a_parent_poll_run_or_dispatch',
    'test_controller_resume.ManualResumeTests.test_pre_and_post_refresh_horizons_still_use_original_stop_plus_margin',
    'test_controller_resume.ManualResumeTests.test_authorization_refusal_is_redacted_and_does_not_start_a_worker',
    'test_controller_resume.ManualResumeTests.test_slow_authentication_cannot_renew_the_sixty_second_reopen_deadline',
    'test_controller_resume_process.ManualResumeProcessTests.test_sdk_authorization_and_arbitrary_exceptions_are_redacted_without_dispatch')


def main():
    p=argparse.ArgumentParser();p.add_argument('--output-root',type=Path,required=True);args=p.parse_args()
    def denied(*a,**kw):raise RuntimeError('Network denied in post-close secret-scan qualification')
    socket.socket.connect=socket.socket.connect_ex=socket.create_connection=socket.getaddrinfo=denied
    sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tests'),
        str(ROOT/'experiments/sampling_promotion_20261016/market_data/src'),
        str(ROOT/'experiments/authenticated_startup_20261023/reference_mb_tools/src')]
    from resume_failure_evidence import ManualFailureEvidenceResult
    pin=json.loads((Path(__file__).parent/'command46_runtime_source_sha256.json').read_text())
    unchanged=all(hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==sha for name,sha in pin.items())
    if not unchanged:raise RuntimeError('Command-46 runtime/reference source differs; test-only correction refused')
    folder=args.output_root/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8]);folder.mkdir(parents=True,exist_ok=False)
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
        'scope':'Corrective test lifecycle: close the resumed controller before a strict whole-artifact secret scan. Complete lock/binary-file coverage, secret detection, unreadable/disappearing-file failures with relative paths, actual Windows exclusive-lock read behavior, and affected close/horizon/SDK-output redaction paths. Synthetic credentials/SDK and owned processes only; complementary to the retained FAILED command-46 result. Runtime implementation and limits unchanged; not a full runtime/provider/profile qualification rerun.',
        'command46_windows_result_retained':'FAILED',
        'command46_unreadable_file':'UNKNOWN_FROM_SUPPLIED_CONSOLE',
        'command46_runtime_reference_files_unchanged':len(pin),
        'runtime_source_changed':False,'limits_relaxed':False,'unreadable_artifacts_skipped':False,
        'failure_evidence_files':result.evidence_files,'failure_evidence_write_errors':result.evidence_write_errors,
        'actual_vault_access':False,'real_feed_directory_or_broker_requests':0,
        'windows_acceptance':'OPERATOR_RESULT_REQUIRED',
        'post_close_secret_scan_offline_qualified':result.wasSuccessful(),
        'full_runtime_qualification_rerun':False,'outer_controller_profile_harness_qualified':False,
        'remaining':['Windows corrective scan/lifecycle result and actual CMD prompt return',
            'owned outer-controller hard deadlines/shutdown and live profile goals/coverage/audit harness',
            'separately invoked live acquisition and worker recovery profiles',
            'read-only Overlay adapter','production adoption and broader capacity']}
    (folder/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2));print('Saved report:',folder/'verification.json')
    return 0 if result.wasSuccessful() else 1


if __name__=='__main__':raise SystemExit(main())
