"""Fixed isolated after-hours roles; no public synthetic mode."""
from pathlib import Path
import sys

COORDINATOR = Path(__file__).resolve().parents[2]
SOURCE = COORDINATOR.parent
sys.path[:0] = [str(COORDINATOR/'src'), str(SOURCE/'market_data/src')]


def main():
    try:
        if len(sys.argv) != 4 or sys.argv[1] not in ('worker', 'report'): return 64
        role, root, nonce = sys.argv[1:]
        from mb_watchlist_coordinator.installed_startup_probe import _silence, inspect_dependencies
        from mb_watchlist_coordinator.after_hours_profile import load_config, run_worker, run_report
        from mb_watchlist_coordinator.controller_bootstrap import EXPECTED_HELPERS
        from mb_watchlist_coordinator.live_profile import source_guard
        from mb_watchlist_coordinator.sampling_requests import digest
        _silence(); config = load_config(root)
        if config['review']['source_root'] != str(SOURCE) or config['nonce'] != nonce: return 70
        source_guard(SOURCE, config['review']['source_inventory_sha256'])
        if role == 'worker':
            observed = inspect_dependencies(EXPECTED_HELPERS)
            if observed.get('qualified') is not True or digest(observed) != config['review']['dependency_sha256']: return 70
            return run_worker(root, nonce)
        return run_report(root, nonce)
    except KeyboardInterrupt: return 130
    except Exception: return 70


if __name__ == '__main__': raise SystemExit(main())
