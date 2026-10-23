"""Offline command-45 fixture boundary, evidence and affected runtime checks."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import socket
import sys
import time
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[2]
SUITES = ('test_runtime_process_evidence', 'test_integrated_runtime_process',
    'test_integrated_runtime', 'test_supervised_hot_worker')


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--output-root', type=Path, required=True)
    args = parser.parse_args()
    def denied(*a, **kw): raise RuntimeError('Network denied in coupled runtime qualification')
    socket.socket.connect = socket.socket.connect_ex = socket.create_connection = socket.getaddrinfo = denied
    sys.path[:0] = [str(ROOT/'src'), str(ROOT/'tests'),
        str(ROOT/'experiments/sampling_promotion_20261016/market_data/src'),
        str(ROOT/'experiments/hot_collector_recovery_20261023/native_tests'),
        str(ROOT/'experiments/authenticated_startup_20261023/reference_mb_tools/src')]
    from runtime_process_evidence import FailureEvidenceResult
    import hashlib
    pinned = json.loads((Path(__file__).parent/'command44_runtime_source_sha256.json').read_text())
    unchanged = all(hashlib.sha256((ROOT/name).read_bytes()).hexdigest() == sha for name, sha in pinned.items())
    if not unchanged:
        raise RuntimeError('Command-44 runtime source differs; fixture-only qualification refused')
    folder = args.output_root/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8])
    folder.mkdir(parents=True, exist_ok=False)
    start = time.perf_counter()
    result = unittest.TextTestRunner(verbosity=1, resultclass=lambda *a, **kw:
        FailureEvidenceResult(*a, evidence_root=folder/'failure_evidence', **kw)).run(unittest.TestSuite(
        unittest.defaultTestLoader.loadTestsFromName(n) for n in SUITES))
    report = {'result': 'PASS' if result.wasSuccessful() else 'FAILED', 'tests': result.testsRun,
        'passed': result.testsRun-len(result.skipped)-len(result.failures)-len(result.errors),
        'skipped': len(result.skipped), 'failures': len(result.failures), 'errors': len(result.errors),
        'skipped_tests': [{'test': str(t), 'reason': reason} for t, reason in result.skipped],
        'seconds': time.perf_counter()-start, 'network': 'denied', 'production_access': False,
        'python': list(sys.version_info[:3]), 'executable': str(Path(sys.executable).resolve()),
        'platform': platform.platform(), 'suites': list(SUITES),
        'scope': 'Affected fixture causality and allowlisted pre-cleanup failure evidence, followed by fresh command-43 session coupled to the accepted feed/source/request/publication authority, explicit prepared-client identity delivery and authenticated native owned Hot worker. Independent first-completed-work 3s gate with separate 8s credentials; synthetic HTTP/SDK and actual process failures. Logical feed pacing and elapsed worker drills are distinguished. Not installed/live authentication, an independently preempting outer controller/profile harness, full manual controller resume, live recovery, production adoption or capacity.',
        'prior_accepted_runtime_sources_changed': False,
        'command44_runtime_source_files_checked': len(pinned),
        'command44_runtime_sources_unchanged': unchanged,
        'command44_windows_failure_retained': True,
        'command44_windows_failure_cause': 'UNKNOWN',
        'failure_evidence_files': result.evidence_files,
        'failure_evidence_write_errors': result.evidence_write_errors,
        'unchanged_accepted_suites_repeated': False,
        'pinned_mb_tools_interfaces_exercised': True,
        'actual_vault_access': False, 'real_feed_directory_or_broker_requests': 0,
        'windows_acceptance': 'OPERATOR_RESULT_REQUIRED',
        'fresh_runtime_pump_offline_qualified': result.wasSuccessful(),
        'outer_controller_profile_harness_or_full_manual_resume_qualified': False,
        'unattended_controller_bootstrap': False,
        'limits': {'worker_startup_seconds': 3, 'worker_stale_seconds': 3,
            'credential_timeout_seconds': 8, 'hot_quote_permits': 60,
            'identity_quote_permits': 3, 'worker_starts': 3, 'original_active_window_seconds': 720},
        'remaining': ['full manual controller resume with original identities, frozen window and budgets',
            'owned outer-controller hard deadlines/shutdown and live profile goals/coverage/audit harness',
            'separately invoked live acquisition and worker recovery profiles',
            'read-only Overlay adapter', 'production adoption and broader capacity']}
    (folder/'verification.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2)); print('Saved report:', folder/'verification.json')
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
