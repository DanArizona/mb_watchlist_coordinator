"""Focused offline fresh-controller bootstrap and credential-interface checks."""
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
SUITES = ('test_controller_bootstrap', 'test_controller_bootstrap_process', 'test_authenticated_startup')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output-root', type=Path, required=True)
    args = parser.parse_args()
    def denied(*a, **kw):
        raise RuntimeError('Network denied in fresh-controller bootstrap qualification')
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
        'platform': platform.platform(),
        'scope': 'Fresh-session credential-before-initial-journal/poll_run creation, bound native request/publication/source initialization and owned private-pipe deadline/redaction drills. Pinned mb_tools with synthetic configuration/SDK only.',
        'suites': list(SUITES), 'quote_dispatches_started': 0, 'feed_attempts_started': 0,
        'actual_vault_access': False, 'installed_sdk_or_live_authentication_qualified': False,
        'runtime_loop_or_live_recovery_qualified': False, 'windows_acceptance': 'OPERATOR_RESULT_REQUIRED',
        'unattended_controller_bootstrap': False,
        'prior_accepted_runtime_sources_changed': False,
        'remaining': ['coupled runtime supervision and worker startup timing',
            'live directory/catalog and identity-resolution integration',
            'durable cumulative identity budget and one-symbol admission fence',
            'manual controller resume', 'bounded live feed and authenticated native Hot recovery',
            'Overlay adapter', 'production adoption and broader capacity']}
    folder = args.output_root/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8])
    folder.mkdir(parents=True, exist_ok=False)
    (folder/'verification.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2)); print('Saved report:', folder/'verification.json')
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
