"""Pinned subprocess roles; no synthetic mode or secret command-line value."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'src'),
    str(ROOT/'experiments/sampling_promotion_20261016/market_data/src')]


def main():
    from mb_watchlist_coordinator.live_profile import (bounded_json,
        run_controller, run_reporter, validate_configuration)
    from mb_watchlist_coordinator.installed_startup_probe import _silence
    from mb_watchlist_coordinator.owned_process_scope import receive_gate
    try:
        if len(sys.argv) < 4: return 64
        role, path, sha = sys.argv[1:4]
        value = bounded_json(path)
        if role in ('controller', 'report'):
            if len(sys.argv) != 4: return 64
            receive_gate(sys.stdin.buffer, value['nonce'])
            _silence()
            if role == 'report': return run_reporter(value, sha)
            return run_controller(value, path, sha, sys.stdin.buffer)
        if role == 'worker' and len(sys.argv) == 6:
            # Already assigned to the owning controller's process scope. The
            # existing generation-bound private handoff and 3s/8s gates apply.
            plan = validate_configuration(value, sha)
            from mb_watchlist_coordinator.installed_startup_probe import inspect_dependencies
            from mb_watchlist_coordinator.controller_bootstrap import EXPECTED_HELPERS
            from mb_watchlist_coordinator.sampling_requests import digest
            observed = inspect_dependencies(EXPECTED_HELPERS)
            if observed.get('qualified') is not True or digest(observed) != plan.settings.dependency_sha256:
                return 70
            expected = str(Path(value['settings']['experiment_root'])/'authenticated-worker.json')
            if sys.argv[4] != expected: return 70
            from mb_watchlist_coordinator.supervised_hot_worker import run_supervised
            result = run_supervised(sys.argv[4], sys.argv[5])
            if isinstance(result, dict) and result.get('status') == 'budget_exhausted':
                # The exact bound worker has stopped provider work. Notify the
                # independent outer owner immediately rather than waiting for
                # the next potentially expensive Coordinator cycle.
                from mb_watchlist_coordinator.live_profile import request_stop
                request_stop(value, sha, 'native_budget_exhausted')
            return 0
        return 64
    except KeyboardInterrupt: return 130
    except Exception: return 70


if __name__ == '__main__': raise SystemExit(main())
