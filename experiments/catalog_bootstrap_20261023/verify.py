"""Offline post-credential catalog binding and affected bootstrap qualification."""
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
SUITES = ('test_catalog_bootstrap', 'test_catalog_bootstrap_process',
    'test_controller_bootstrap', 'test_controller_bootstrap_process', 'test_authenticated_startup',
    'test_integrated_catalog', 'test_integrated_identity', 'test_nasdaq_recovery_delivery',
    'test_nasdaq_request_reuse', 'test_sampling_admission', 'test_sampling_requests')


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--output-root', type=Path, required=True)
    args = parser.parse_args()
    def denied(*a, **kw): raise RuntimeError('Network denied in catalog-bound bootstrap qualification')
    socket.socket.connect = socket.socket.connect_ex = socket.create_connection = socket.getaddrinfo = denied
    sys.path[:0] = [str(ROOT/'src'), str(ROOT/'tests'),
        str(ROOT/'experiments/sampling_promotion_20261016/market_data/src'),
        str(ROOT/'experiments/authenticated_startup_20261023/reference_mb_tools/src')]
    start = time.perf_counter()
    result = unittest.TextTestRunner(verbosity=1).run(unittest.TestSuite(
        unittest.defaultTestLoader.loadTestsFromName(n) for n in SUITES))
    report = {'result': 'PASS' if result.wasSuccessful() else 'FAILED', 'tests': result.testsRun,
        'passed': result.testsRun-len(result.skipped)-len(result.failures)-len(result.errors),
        'skipped': len(result.skipped), 'failures': len(result.failures), 'errors': len(result.errors),
        'seconds': time.perf_counter()-start, 'network': 'denied', 'production_access': False,
        'python': list(sys.version_info[:3]), 'executable': str(Path(sys.executable).resolve()),
        'platform': platform.platform(), 'suites': list(SUITES),
        'scope': 'Post-credential one-invocation/two-permit catalog reservation, retained source bytes, catalog/admission/identity/native bootstrap binding and private-pipe process interruption/deadline regressions. Pinned mb_tools with synthetic configuration, SDK and directory HTTP only; not installed authentication, running collector supervision, full manual controller resume, live acquisition/recovery, production adoption or capacity.',
        'changed_accepted_source_paths': ['src/mb_watchlist_coordinator/controller_bootstrap.py',
            'src/mb_watchlist_coordinator/bootstrap_entry.py'],
        'legacy_v1_public_identity_preserved': True,
        'prior_pinned_acceptances_and_archives_retained': True,
        'actual_vault_access': False, 'real_feed_directory_or_broker_requests': 0,
        'windows_acceptance': 'OPERATOR_RESULT_REQUIRED',
        'runtime_loop_or_full_manual_resume_qualified': False,
        'unattended_controller_bootstrap': False,
        'remaining': ['prepared-client runtime and owned-worker startup timing integration',
            'full manual controller resume with original identities and budgets',
            'separately invoked bounded live acquisition and worker recovery profiles',
            'Overlay adapter', 'production adoption and broader capacity']}
    folder = args.output_root/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8])
    folder.mkdir(parents=True, exist_ok=False)
    (folder/'verification.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2)); print('Saved report:', folder/'verification.json')
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
