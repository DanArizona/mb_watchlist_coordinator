"""Fixed delivered daily roles. No synthetic or arbitrary-command CLI mode."""
from pathlib import Path
import re
import sys

COORDINATOR = Path(__file__).resolve().parents[2]
SOURCE = COORDINATOR.parent
sys.path[:0] = [str(COORDINATOR/'src'), str(SOURCE/'market_data/src')]


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        if len(args) < 4:
            return 64
        role, inventory, dependencies, *rest = args
        if (role not in ('controller', 'reporter', 'collector', 'identity', 'report')
                or not all(re.fullmatch('[0-9a-f]{64}', s) for s in (inventory, dependencies))
                or len(rest) != (3 if role == 'reporter' else 2)):
            return 64
        from mb_watchlist_coordinator.live_profile import source_guard
        from mb_watchlist_coordinator.daily_launch import fixed_entries, validate_owned_launch
        from mb_watchlist_coordinator.installed_startup_probe import inspect_dependencies, _silence
        from mb_watchlist_coordinator.controller_bootstrap import EXPECTED_HELPERS
        from mb_watchlist_coordinator.sampling_requests import digest
        source_guard(SOURCE, inventory)
        _silence()
        if role in ('controller', 'collector', 'identity'):
            observed = inspect_dependencies(EXPECTED_HELPERS)
            if observed.get('qualified') is not True or digest(observed) != dependencies:
                return 70
        if role in ('controller', 'reporter'):
            root, nonce, *job = rest
            validate_owned_launch(Path(root), inventory, dependencies)
            from mb_watchlist_coordinator.daily_operating_worker import controller_entry, reporter_entry
            if role == 'controller':
                controller_entry(root, nonce)
            else:
                reporter_entry(root, nonce, job[0])
        else:
            from mb_watchlist_coordinator.daily_supervision import DailyWorkerConfiguration, read_json
            from mb_watchlist_coordinator.daily_authenticated_worker import run_collector, run_identity, run_report
            config_path, job = rest
            config = DailyWorkerConfiguration.load(config_path)
            commands, _, _ = fixed_entries(SOURCE, inventory, dependencies, config.publication.state_root)
            binding = read_json(Path(config.publication.state_root)/'driver-binding.json')
            if binding['commands'] != {k: list(v) for k, v in commands.items()}:
                raise ValueError('Original fixed worker commands differ')
            {'collector': run_collector, 'identity': run_identity, 'report': run_report}[role](config_path, job)
        return 0
    except KeyboardInterrupt:
        return 130
    except Exception:
        return 70


if __name__ == '__main__':
    raise SystemExit(main())
