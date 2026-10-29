"""Read-only Hot status cannot confuse a stale file with a live owner."""
from datetime import timedelta
from pathlib import Path
import tempfile
import unittest

import test_daily_supervision as fixture
from mb_watchlist_coordinator.daily_hot_status import inspect_hot_status
from mb_watchlist_coordinator.recovery_workers import atomic_json
from mb_watchlist_coordinator.sampling_requests import digest
from mb_watchlist_coordinator.sampling_service import owner_lock


class DailyHotStatusTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture.DailySupervisionTests('test_owner_file_existence_does_not_prove_a_live_owner')
        self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        self.owner = self.fixture.owner
        self.addCleanup(self.owner.password.close)
        self.owner.status()

    def inspect(self, **kwargs):
        return inspect_hot_status(self.owner.root, clock=kwargs.get('clock', self.fixture.clock))

    def test_recent_saved_running_status_does_not_prove_an_owner_is_running(self):
        self.assertEqual(self.inspect()['state'], 'CONTROLLER_NOT_RUNNING')

    def test_busy_lease_and_fresh_progress_are_observed_without_new_files(self):
        before = {p.relative_to(self.owner.root) for p in self.owner.root.rglob('*')}
        with owner_lock(self.owner.root/'driver-owner.lock'):
            result = self.inspect()
        self.assertEqual(result['state'], 'STARTING')
        self.assertFalse(result['provider_access'])
        self.assertFalse(result['restart_performed'])
        self.assertEqual(before, {p.relative_to(self.owner.root) for p in self.owner.root.rglob('*')})

    def test_stale_owner_progress_is_an_alert_even_when_the_lease_is_busy(self):
        with owner_lock(self.owner.root/'driver-owner.lock'):
            result = self.inspect(clock=lambda: self.fixture.clock()+timedelta(seconds=4))
        self.assertEqual(result['state'], 'STALE_CONTROLLER')

    def test_terminal_state_and_normal_stop_remain_distinct(self):
        self.owner.state.change(lambda s: s.update(terminal='native_blocked'))
        self.assertEqual(self.inspect()['state'], 'BLOCKED')
        self.owner.state.change(lambda s: s.update(terminal=None, stop={'reason': 'operator'}))
        self.assertEqual(self.inspect()['state'], 'STOPPED')

    def test_altered_or_missing_status_is_unknown_not_falsely_running(self):
        (self.owner.root/'hot-status.json').write_text('{}')
        self.assertEqual(self.inspect()['state'], 'UNKNOWN')

    def test_missing_state_root_is_not_created_by_inspection(self):
        path = self.owner.root/'not-created'
        self.assertEqual(inspect_hot_status(path)['state'], 'UNKNOWN')
        self.assertFalse(path.exists())


if __name__ == '__main__': unittest.main()
