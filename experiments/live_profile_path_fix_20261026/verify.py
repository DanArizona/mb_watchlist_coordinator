"""Affected path/publication and outer-failure qualification; no live APIs."""
import argparse
from datetime import datetime, timezone
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

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
CHANGED = frozenset(('src/mb_watchlist_coordinator/recovery_workers.py',
    'src/mb_watchlist_coordinator/outer_harness.py'))
SUITES = (
    'test_live_profile_path_fix',
    'test_nasdaq_recovery_supervisor.AtomicWorkerRecordTests',
    'test_outer_harness.OuterHarnessTests.test_bootstrap_deadline_wins_before_T0',
    'test_outer_harness.OuterHarnessTests.test_unexpected_controller_exit_cannot_become_pass',
    'test_outer_harness.OuterHarnessTests.test_reporter_deadline_is_independent_of_controller_completion',
    'test_outer_harness.OuterHarnessTests.test_stop_receipt_write_failure_still_stops_the_owned_child',
    'test_live_profile_process.NewEntryProcessTests.test_fresh_private_credentials_catalog_runtime_native_worker_and_bound_read_only_report',
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output-root', type=Path, required=True)
    args = parser.parse_args()
    def denied(*a, **kw):
        raise RuntimeError('Network denied in path-fix offline qualification')
    socket.socket.connect = socket.socket.connect_ex = socket.create_connection = socket.getaddrinfo = denied
    sys.path[:0] = [str(ROOT/'src'), str(ROOT/'tests'),
        str(ROOT/'experiments/sampling_promotion_20261016/market_data/src'),
        str(ROOT/'experiments/authenticated_startup_20261023/reference_mb_tools/src')]
    original = ROOT/'experiments/live_profile_entry_20261024'
    pin = json.loads((original/'accepted_runtime_source_sha256.json').read_text())
    changed = json.loads((HERE/'changed_runtime_source_sha256.json').read_text())
    if len(pin) != 70 or set(changed) != CHANGED or not CHANGED <= set(pin):
        raise ValueError('Reviewed runtime source set differs')
    if any(hashlib.sha256((ROOT/name).read_bytes()).hexdigest() != sha
            for name, sha in pin.items() if name not in CHANGED):
        raise ValueError('An unrelated accepted runtime source changed')
    if any(hashlib.sha256((ROOT/name).read_bytes()).hexdigest() != sha
            or sha == pin[name] for name, sha in changed.items()):
        raise ValueError('Reviewed correction source differs')
    spec = importlib.util.spec_from_file_location('entry_evidence_result', original/'verify.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    folder = args.output_root/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8])
    folder.mkdir(parents=True)
    began = time.perf_counter()
    result = unittest.TextTestRunner(verbosity=1, resultclass=lambda *a, **kw:
        module.EvidenceResult(*a, evidence_root=folder/'failure_evidence', **kw)).run(
            unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(name) for name in SUITES))
    report = {
        'contract': 'live-hot-path-fix-offline-qualification-v1',
        'result': 'PASS' if result.wasSuccessful() else 'FAILED',
        'tests': result.testsRun,
        'passed': result.testsRun-len(result.skipped)-len(result.failures)-len(result.errors),
        'skipped': len(result.skipped), 'failures': len(result.failures), 'errors': len(result.errors),
        'failed_tests': [str(test) for test, _ in result.failures+result.errors],
        'skipped_tests': [str(test) for test, _ in result.skipped],
        'seconds': time.perf_counter()-began, 'network': 'denied', 'production_access': False,
        'actual_vault_access': False, 'real_feed_directory_or_broker_requests': 0,
        'python': list(sys.version_info[:3]), 'executable': str(Path(sys.executable).resolve()),
        'platform': platform.platform(), 'suites': list(SUITES),
        'accepted_runtime_source_files_unchanged': 68,
        'changed_runtime_source_sha256': changed,
        'scope': 'Compact same-directory atomic temporary filenames at the recorded 190-character parent; owned synthetic worker job/heartbeat/exit; original sharing-conflict retry bounds and complete-value publication; failed/exited controller precedence without wider preparation, active, cleanup or reporting limits; one affected synthetic authenticated native quote plus separate read-only audit/two replays. This is not a live profile or production adoption.',
        'failure_evidence_files': result.files, 'success_evidence_files': result.success_files,
        'unchanged_accepted_suites_repeated': False, 'prior_failed_results_retained': True,
        'original_command51_result': 'FAILED',
        'windows_acceptance': 'OPERATOR_RESULT_REQUIRED',
        'live_profiles_run_with_correction': False,
        'remaining': ['Windows command54 result and actual CMD prompt return',
            'fresh production health and separately invoked ordinary command51',
            'ordinary evidence review before separate recovery command52',
            'minimum operating/adoption work for running automatic operation',
            'manual membership workflow and agreed read-only Overlay'],
    }
    (folder/'verification.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))
    print('Saved report:', folder/'verification.json')
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
