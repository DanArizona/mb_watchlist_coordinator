"""Offline human-started credential handoff and authenticated-entry verification with synthetic SDK only."""
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
    'test_nasdaq_feed_recovery', 'test_nasdaq_recovery_supervisor',
    'test_hot_recovery_collector', 'test_sampling_acquisition',
    'test_authenticated_startup', 'test_authenticated_worker')


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
        str(ROOT/'experiments/coordinator_history_cost_20261022/native_tests'),
        str(ROOT/'experiments/hot_collector_recovery_20261023/native_tests'),
        str(ROOT/'experiments/authenticated_startup_20261023/reference_mb_tools/src')]
    suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(n) for n in SUITES)
    start = time.perf_counter()
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    folder = args.output_root/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8])
    folder.mkdir(parents=True, exist_ok=False)
    report = {'result': 'PASS' if result.wasSuccessful() else 'FAILED', 'tests': result.testsRun,
        'skipped': len(result.skipped), 'failures': len(result.failures), 'errors': len(result.errors),
        'passed': result.testsRun-len(result.skipped)-len(result.failures)-len(result.errors),
        'seconds': time.perf_counter()-start, 'network': 'denied', 'production_access': False,
        'scope': 'Human-started anonymous-pipe credential handoff, pinned mb_tools encrypted-config/status/client interfaces, noninteractive authenticated worker entry and affected native recovery paths. Synthetic credentials and SDK only; not installed SDK authentication, live HTTP, market-hours recovery, production adoption or capacity.',
        'credential_interfaces': {'repository': 'DanArizona/mb_tools', 'commit': 'abdceb1be988b7ee893b0bed725b90454ddf4f71', 'execution': 'pinned_public_reference_source', 'sdk': 'synthetic_replacement', 'actual_vault_access': False, 'installed_sdk_qualified': False},
        'unattended_controller_bootstrap': False, 'suites': list(SUITES), 'execution_environment': 'offline_current_host', 'windows_operator_acceptance_recorded_separately': True}
    (folder/'verification.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))
    print('Saved report:', folder/'verification.json')
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
