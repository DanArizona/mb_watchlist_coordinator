"""Durable reservations and owner fences; no SDK or network."""
from datetime import timedelta
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
import unittest

import test_daily_controller as fixture
from mb_watchlist_coordinator.authenticated_startup import StartupError
from mb_watchlist_coordinator.daily_supervision import (DailyManagedWorker,
    assert_controller_fence, read_json, sealed)
from mb_watchlist_coordinator.daily_worker_view import _ReadPublication
from mb_watchlist_coordinator.recovery_workers import atomic_json
from mb_watchlist_coordinator.sampling_requests import utc_text
from mb_watchlist_coordinator.sampling_service import ServiceBusy, owner_lock
from mb_watchlist_coordinator.daily_authenticated_worker import owned_role_lease


class DailySupervisionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture.DailyControllerTests('test_read_only_view_requires_an_explicit_fence')
        self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        self.owner = self.fixture.make()
        self.root, self.clock = self.owner.root, self.fixture.clock
        atomic_json(self.root/'driver-binding.json', self.owner.identity)
        atomic_json(self.root/'daily-worker.json', self.owner.configuration.payload())
        self.owner.state.create()
        self.owner.invocation = 'f'*32
        self.owner.state.change(lambda s: s.update(active_invocation=self.owner.invocation))
        self.owner._live()
        with owner_lock(self.root/'driver-owner.lock'): pass

    def worker(self, **kwargs):
        return DailyManagedWorker(self.root/'workers', command=self.owner.commands['collector'],
            binding=self.owner.identity, state=self.owner.state, password=self.owner.password,
            clock=kwargs.get('clock', self.clock), monotonic=kwargs.get('monotonic', lambda: 0))

    def fence(self, **changes):
        return assert_controller_fence(self.owner.configuration, self.owner.identity,
            changes.get('token'), changes.get('invocation', self.owner.invocation),
            clock=changes.get('clock', self.clock))

    def test_owner_file_existence_does_not_prove_a_live_owner(self):
        with self.assertRaises(ValueError): self.fence()
        with owner_lock(self.root/'driver-owner.lock'): self.assertTrue(self.fence())

    def test_stale_guard_fences_even_while_the_owner_lease_is_busy(self):
        with owner_lock(self.root/'driver-owner.lock'):
            with self.assertRaises(ValueError): self.fence(clock=lambda: self.clock()+timedelta(seconds=4))

    def test_changed_invocation_or_unreserved_worker_never_passes_the_fence(self):
        with owner_lock(self.root/'driver-owner.lock'):
            with self.assertRaises(ValueError): self.fence(invocation='e'*32)
            with self.assertRaises(ValueError): self.fence(token='e'*32)

    def test_stop_state_blocks_before_a_new_provider_dispatch(self):
        self.owner.state.change(lambda s: s.update(stop={'reason': 'operator'}))
        with owner_lock(self.root/'driver-owner.lock'):
            with self.assertRaises(ValueError): self.fence()

    def test_reservation_remains_charged_if_private_handoff_fails_before_process_creation(self):
        worker = self.worker()
        with patch.object(self.owner.password, 'frame', side_effect=StartupError('credentials_unavailable')):
            with patch('subprocess.Popen') as popen:
                first = worker.ensure(start_allowed=True, resume_after_utc=utc_text(self.clock()))
                second = worker.ensure(start_allowed=True, resume_after_utc=utc_text(self.clock()))
                popen.assert_not_called()
        self.assertEqual(first['reason'], 'startup_credentials_unavailable')
        self.assertEqual(second['reason'], 'original_worker_start_evidence_missing')
        self.assertEqual(len(self.owner.state.read()['starts']), 1)

    def test_three_start_ceiling_is_durable_outside_the_worker_directory(self):
        def fill(s):
            s['starts'] = [{'generation': n, 'token': str(n)*32, 'invocation': self.owner.invocation,
                'reserved_at_utc': utc_text(self.clock()), 'exit_observed_at_utc': None} for n in (1, 2, 3)]
        self.owner.state.change(fill)
        worker = self.worker()
        with self.assertRaises(ValueError): worker.startup_handoff.frame('4'*32)
        self.assertEqual(len(self.owner.state.read()['starts']), 3)

    def test_wall_clock_forward_jump_cannot_shorten_the_elapsed_replacement_hold(self):
        at, elapsed = self.clock(), [0]
        worker = self.worker(clock=lambda: at+timedelta(seconds=100), monotonic=lambda: elapsed[0])
        self.owner.state.change(lambda s: s.update(hold_until_utc=utc_text(at+timedelta(seconds=15))))
        worker.hold_monotonic = 15
        elapsed[0] = 1
        with patch('subprocess.Popen') as popen:
            self.assertEqual(worker.ensure(start_allowed=True,
                resume_after_utc=utc_text(at))['status'], 'REPLACEMENT_HOLD')
            popen.assert_not_called()

    def test_state_corruption_is_not_an_invitation_to_reset(self):
        value = read_json(self.owner.state.path)
        value['starts'] = [{'generation': 99}]
        atomic_json(self.owner.state.path, value)
        with self.assertRaises(ValueError): self.owner.state.read()

    def test_publication_contention_retries_only_the_short_lock_entry(self):
        class Service:
            identity = {}
            calls = 0
            def snapshot(self):
                self.calls += 1
                if self.calls == 1: raise ServiceBusy('synthetic contention')
                return {'ok': True}
        service = Service()
        self.assertTrue(_ReadPublication(service).snapshot()['ok'])
        self.assertEqual(service.calls, 2)
        with patch.object(service, 'snapshot', side_effect=ValueError('integrity')):
            with self.assertRaises(ValueError): _ReadPublication(service).snapshot()

    def test_role_lease_contention_has_a_fixed_budget_and_other_errors_are_not_retried(self):
        elapsed, sleeps = [0.], []
        def sleep(seconds):
            sleeps.append(seconds)
            elapsed[0] += seconds
        target = 'mb_watchlist_coordinator.daily_authenticated_worker.owner_lock'
        with patch(target, side_effect=ServiceBusy('probe remains busy')) as entry:
            with self.assertRaises(ServiceBusy):
                with owned_role_lease(self.root/'role-test.lock',
                        monotonic=lambda: elapsed[0], sleep=sleep):
                    self.fail('Busy ownership must never enter role work')
        self.assertAlmostEqual(elapsed[0], .2)
        self.assertLessEqual(entry.call_count, 42)
        self.assertTrue(sleeps)
        for error in (ValueError('invalid ownership evidence'), OSError('unrelated failure')):
            with self.subTest(error=type(error).__name__):
                with patch(target, side_effect=error) as entry:
                    with self.assertRaises(type(error)):
                        with owned_role_lease(self.root/'role-test.lock', sleep=lambda _: self.fail('Unexpected retry')):
                            self.fail('Failed entry must never enter role work')
                self.assertEqual(entry.call_count, 1)

    def test_role_work_raising_service_busy_is_not_replayed_and_releases_ownership(self):
        calls = []
        @contextmanager
        def acquired(path):
            calls.append('entered')
            try: yield
            finally: calls.append('released')
        with patch('mb_watchlist_coordinator.daily_authenticated_worker.owner_lock', acquired):
            with self.assertRaises(ServiceBusy):
                with owned_role_lease(self.root/'role-test.lock'):
                    calls.append('work')
                    raise ServiceBusy('failure after ownership, do not repeat work')
        self.assertEqual(calls, ['entered', 'work', 'released'])


if __name__ == '__main__': unittest.main()
