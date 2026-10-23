"""Affected offline paced-transport/recovery-supervision verification; owned synthetic children only."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import socket
import sys
import time
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[2]
SUITES = ('test_sampling_admission', 'test_sampling_policy', 'test_sampling_requests',
    'test_sampling_scaling', 'test_sampling_service', 'test_nasdaq_recovery',
    'test_nasdaq_sampling', 'test_coordinator_growth', 'test_history_cost',
    'test_history_reconstruction', 'test_sampling_membership', 'test_quote_observation_store',
    'test_sampling_metadata_cost', 'test_sampling_payload_reader', 'test_nasdaq_request_reuse',
    'test_nasdaq_reuse_workload', 'test_nasdaq_recovery_delivery',
    'test_nasdaq_feed_recovery', 'test_nasdaq_recovery_supervisor')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output-root', type=Path, required=True)
    args = parser.parse_args()
    def denied(*a, **kw):
        raise RuntimeError('Network denied in recovery-supervision qualification')
    socket.socket.connect = socket.socket.connect_ex = socket.create_connection = socket.getaddrinfo = denied
    sys.path[:0] = [str(ROOT/'src'), str(ROOT/'tests'),
        str(ROOT/'experiments/sampling_promotion_20261016/market_data/src'),
        str(ROOT/'experiments/coordinator_history_reconstruction_20261022/native_tests'),
        str(ROOT/'experiments/coordinator_history_cost_20261022/native_tests')]
    suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(n) for n in SUITES)
    start = time.perf_counter()
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    folder = args.output_root/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8])
    folder.mkdir(parents=True, exist_ok=False)
    report = {'result': 'PASS' if result.wasSuccessful() else 'FAILED', 'tests': result.testsRun,
        'skipped': len(result.skipped), 'failures': len(result.failures), 'errors': len(result.errors),
        'passed': result.testsRun-len(result.skipped)-len(result.failures)-len(result.errors),
        'seconds': time.perf_counter()-start, 'network': 'denied', 'production_access': False,
        'scope': 'Paced feed transport and isolated recovery authority/owned-worker protocol; synthetic HTTP children, source/store/admission/publication/native integration. Not live HTTP, broker collector integration, production adoption or capacity.',
        'suites': list(SUITES), 'execution_environment': 'offline_current_host', 'windows_operator_acceptance_recorded_separately': True}
    (folder/'verification.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))
    print('Saved report:', folder/'verification.json')
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
