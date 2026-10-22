"""Bounded offline affected-suite verification; no provider or capacity claim."""
from pathlib import Path
import argparse
from datetime import datetime, timezone
import json
import socket
import sys
import time
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[2]
SUITES = (
    'test_sampling_admission', 'test_sampling_policy', 'test_sampling_requests',
    'test_sampling_scaling', 'test_sampling_service',
    'test_nasdaq_recovery', 'test_nasdaq_sampling',
    'test_coordinator_growth', 'test_history_cost',
    'test_sampling_membership', 'test_quote_observation_store', 'test_sampling_metadata_cost',
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output-root', type=Path, required=True)
    args = parser.parse_args()
    def denied(*args, **kwargs):
        raise RuntimeError('Network denied in Coordinator history-cost verification')
    socket.socket.connect = socket.socket.connect_ex = denied
    socket.create_connection = socket.getaddrinfo = denied
    sys.path[:0] = [str(ROOT/'src'), str(ROOT/'tests'),
        str(ROOT/'experiments/sampling_promotion_20261016/market_data/src'),
        str(Path(__file__).parent/'native_tests')]
    suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(n) for n in SUITES)
    before = time.perf_counter()
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    report = {'result': 'PASS' if result.wasSuccessful() else 'FAILED',
        'tests': result.testsRun, 'seconds': time.perf_counter()-before,
        'network': 'denied', 'production_access': False,
        'scope': 'Affected request/policy/admission/publication/Nasdaq and native metadata/store tests; not complete recovery or capacity',
        'suites': list(SUITES)}
    folder = args.output_root/'verification'
    folder.mkdir(parents=True, exist_ok=True)
    path = folder/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8]+'.json')
    path.write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(report, indent=2)); print('Saved report: '+str(path))
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
