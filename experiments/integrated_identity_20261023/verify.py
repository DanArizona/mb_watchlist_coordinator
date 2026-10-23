"""Focused offline catalog/identity gate and affected native request checks."""
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
SUITES = ('test_integrated_catalog', 'test_integrated_identity',
    'test_nasdaq_recovery_delivery', 'test_nasdaq_request_reuse',
    'test_sampling_admission', 'test_sampling_requests', 'test_controller_bootstrap')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output-root', type=Path, required=True)
    args = parser.parse_args()
    def denied(*a, **kw): raise RuntimeError('Network denied in catalog/identity qualification')
    socket.socket.connect = socket.socket.connect_ex = socket.create_connection = socket.getaddrinfo = denied
    sys.path[:0] = [str(ROOT/'src'), str(ROOT/'tests'),
        str(ROOT/'experiments/sampling_promotion_20261016/market_data/src'),
        str(ROOT/'experiments/authenticated_startup_20261023/reference_mb_tools/src')]
    start = time.perf_counter()
    suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(n) for n in SUITES)
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    report = {'result': 'PASS' if result.wasSuccessful() else 'FAILED', 'tests': result.testsRun,
        'passed': result.testsRun-len(result.skipped)-len(result.failures)-len(result.errors),
        'skipped': len(result.skipped), 'failures': len(result.failures), 'errors': len(result.errors),
        'seconds': time.perf_counter()-start, 'network': 'denied', 'production_access': False,
        'python': list(sys.version_info[:3]), 'executable': str(Path(sys.executable).resolve()),
        'platform': platform.platform(), 'suites': list(SUITES),
        'scope': 'Owned synthetic directory retrieval/deadlines, immutable exact-symbol catalog, durable cumulative identity reservations and one-symbol authorization, ordinary shared request/reuse/admission and native Hot publication/acquisition. Synthetic provider/HTTP only; not installed SDK, coupled bootstrap/runtime, manual controller resume, live transport/recovery, production adoption or capacity.',
        'actual_vault_access': False, 'real_feed_or_broker_requests': 0,
        'prior_accepted_runtime_sources_changed': False,
        'windows_acceptance': 'OPERATOR_RESULT_REQUIRED',
        'runtime_loop_or_live_recovery_qualified': False,
        'remaining': ['catalog acquisition after credential acceptance in the coupled bootstrap',
            'prepared-client injection into runtime supervision and owned worker startup timing',
            'manual controller resume with all original bindings and cumulative budgets',
            'bounded live feed and authenticated native Hot recovery', 'Overlay adapter',
            'production adoption and broader capacity']}
    folder = args.output_root/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8])
    folder.mkdir(parents=True, exist_ok=False)
    (folder/'verification.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2)); print('Saved report:', folder/'verification.json')
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
