"""Scaling changes must preserve live reads, full replay and input rejection."""
from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from mb_watchlist_coordinator.models import IntentType, ProducerIntent
from mb_watchlist_coordinator import sampling_projection as projection
from mb_watchlist_coordinator.sampling_projection import SamplingMembership
from mb_watchlist_coordinator.sampling_request_store import SamplingRequestStore
from mb_watchlist_coordinator.sampling_requests import (RequestEvent, baseline_payload, digest,
                                                       replay_requests, request_payload)
from mb_watchlist_coordinator.sampling_policy import SamplingPolicy

NOW = datetime(2026, 10, 22, 14, tzinfo=timezone.utc)
BASELINE = SamplingMembership(frozenset({'AAPL', 'MSFT', 'SPY'}), frozenset({'SPY'}), frozenset())


class SymbolValidationTests(unittest.TestCase):
    def setUp(self):
        projection._canonical_text.cache_clear()

    def test_cached_tokens_do_not_bypass_membership_nesting(self):
        SamplingMembership({'AAPL', 'MSFT'}, {'MSFT'}, {'MSFT'})
        with self.assertRaisesRegex(ValueError, 'Hot <= Focus <= Uni'):
            SamplingMembership({'AAPL', 'MSFT'}, {'AAPL'}, {'MSFT'})

    def test_invalid_inputs_remain_invalid_after_valid_cache_warmup(self):
        SamplingMembership({'MSFT'}, set(), set())
        for value in ('MSFT', {'msft'}, {' MSFT'}, {'MS FT'}, {'MSFT,'}, {''}, {1}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                SamplingMembership(value, set(), set())

    def test_cached_invalid_text_keeps_the_correct_field_error(self):
        for field in ('uni', 'focus', 'hot'):
            values = dict(uni={'MSFT'}, focus=set(), hot=set())
            values[field] = {'bad'}
            with self.assertRaisesRegex(ValueError, field + ' must contain'):
                SamplingMembership(**values)

    def test_mutating_input_collection_cannot_mutate_cached_membership(self):
        symbols = {'MSFT'}
        before = SamplingMembership(symbols, set(), set())
        symbols.add('bad')
        self.assertEqual(before.uni, {'MSFT'})
        with self.assertRaises(ValueError):
            SamplingMembership(symbols, set(), set())

    def test_string_subclass_cannot_borrow_plain_string_cache_result(self):
        class MutableText(str):
            valid = True
            def strip(self):
                return self
            def upper(self):
                return self if self.valid else 'CHANGED'
        SamplingMembership({'MSFT'}, set(), set())
        value = MutableText('MSFT')
        SamplingMembership({value}, set(), set())
        value.valid = False
        with self.assertRaises(ValueError):
            SamplingMembership({value}, set(), set())

    def test_long_valid_strings_stay_supported_without_cache_retention(self):
        symbol = 'X' * 65
        self.assertEqual(SamplingMembership({symbol}, set(), set()).uni, {symbol})
        self.assertEqual(projection._canonical_text.cache_info().currsize, 0)

    def test_cache_is_bounded_and_eviction_preserves_validation(self):
        for index in range(4100):
            SamplingMembership({f'S{index:04d}'}, set(), set())
        self.assertEqual(projection._canonical_text.cache_info().currsize, 4096)
        self.assertEqual(SamplingMembership({'S0000'}, set(), set()).uni, {'S0000'})
        with self.assertRaises(ValueError):
            SamplingMembership({'s0000'}, set(), set())


class VerifiedHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        # Retain every handle so collection cannot hide a missing close on Unix.
        self.connections = []
        connect = sqlite3.connect
        class TrackedConnection(sqlite3.Connection):
            closed = False
            def close(self):
                super().close()
                self.closed = True
        def tracked_connect(*args, **kwargs):
            connection = connect(*args, factory=TrackedConnection, **kwargs)
            self.connections.append(connection)
            return connection
        self.addCleanup(self.assert_connections_closed)
        patcher = patch('sqlite3.connect', side_effect=tracked_connect)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.path = Path(self.temp.name) / 'requests.sqlite3'
        self.store = self.reopen()
        self.store.initialize()
        self.submit('hot-msft', 'MSFT')

    def assert_connections_closed(self):
        unclosed = [connection for connection in self.connections if not connection.closed]
        try:
            self.assertFalse(unclosed, 'SQLite handles must close before temporary-directory cleanup')
        finally:
            for connection in unclosed:
                connection.close()

    def reopen(self):
        return SamplingRequestStore(self.path, session_date=date(2026, 10, 22),
                                    baseline=BASELINE, clock=lambda: NOW)

    def submit(self, rid, symbol):
        return self.store.submit_request(ProducerIntent(rid, 'manual', IntentType.ENSURE_PRESENT,
            frozenset({symbol}), NOW, metadata={'sampling_channel': 'hot', 'session_date': '2026-10-22'}),
            actor_id='manual')

    def test_one_verified_history_read_returns_matching_events_and_states(self):
        with patch('mb_watchlist_coordinator.sampling_request_store.replay_requests', wraps=replay_requests) as replay:
            events, states = self.store.validated_history()
        self.assertEqual(replay.call_count, 1)
        self.assertEqual([s.payload() for s in states],
                         [s.payload() for s in replay_requests(self.store.session_date, BASELINE, events)])

    def test_states_does_not_repeat_the_same_full_replay(self):
        with patch('mb_watchlist_coordinator.sampling_request_store.replay_requests', wraps=replay_requests) as replay:
            self.store.states()
        self.assertEqual(replay.call_count, 1)

    def test_new_receipts_are_visible_after_a_warm_read(self):
        self.store.validated_history()
        self.submit('hot-aapl', 'AAPL')
        events, states = self.store.validated_history()
        self.assertEqual(len(events), 2)
        self.assertEqual(states[-1].applied.hot, {'MSFT', 'AAPL'})

    def test_warm_read_does_not_hide_hash_corruption(self):
        self.store.validated_history()
        with closing(sqlite3.connect(self.path)) as c, c:
            c.execute("UPDATE request_event SET actor_id='forged' WHERE sequence=1")
        with self.assertRaisesRegex(ValueError, 'hash'):
            self.store.validated_history()

    def test_rehashed_false_admission_still_fails_after_warm_read(self):
        events, _ = self.store.validated_history()
        forged = replace(events[0], accepted=False, rejection_reason='forged', event_sha256='')
        forged = replace(forged, event_sha256=digest(forged.hash_payload()))
        with closing(sqlite3.connect(self.path)) as c, c:
            c.execute('UPDATE request_event SET accepted=0,rejection_reason=?,event_sha256=? WHERE sequence=1',
                      (forged.rejection_reason, forged.event_sha256))
        with self.assertRaisesRegex(ValueError, 'admission outcome'):
            self.store.validated_history()

    def test_cold_reopen_and_empty_symbol_cache_produce_identical_states(self):
        before = [s.payload() for s in self.store.states()]
        projection._canonical_text.cache_clear()
        self.assertEqual(before, [s.payload() for s in self.reopen().states()])

    def test_configuration_changes_are_checked_after_every_warm_read(self):
        self.store.validated_history()
        self.store.baseline = SamplingMembership({'MSFT'}, set(), set())
        with self.assertRaisesRegex(ValueError, 'configuration changed'):
            self.store.validated_history()

    def test_a_returned_membership_cannot_poison_a_later_read(self):
        states = self.store.states()
        expected = [s.payload() for s in states]
        object.__setattr__(states[-1].retained, 'hot', frozenset({'FORGED'}))
        self.assertEqual(expected, [s.payload() for s in self.store.states()])


class ReplayValueTests(unittest.TestCase):
    def history(self, *, baseline=BASELINE, policy=None, request=None, ticks=200):
        previous = digest(baseline_payload(NOW.date(), baseline, policy))
        events = []
        for index in range(ticks + int(request is not None)):
            is_request = request is not None and index == 0
            event = RequestEvent(index+1, f'command-{index}', 'request' if is_request else 'tick',
                'manual' if is_request else '__coordinator__', request if is_request else {},
                NOW + timedelta(seconds=index), True, None, previous, '')
            event = replace(event, event_sha256=digest(event.hash_payload()))
            events.append(event)
            previous = event.event_sha256
        return tuple(events)

    def test_early_hash_and_sequence_damage_remain_visible_after_quiet_history(self):
        events = self.history()
        replay_requests(NOW.date(), BASELINE, events)
        for damaged in ((replace(events[0], event_sha256='forged'),)+events[1:], events[1:]):
            with self.subTest(), self.assertRaisesRegex(ValueError, 'hash chain|hash is'):
                replay_requests(NOW.date(), BASELINE, damaged)

    def test_rehashed_false_tick_admission_is_checked_after_many_equal_states(self):
        events = self.history()
        forged = replace(events[-1], actor_id='intruder', event_sha256='')
        forged = replace(forged, event_sha256=digest(forged.hash_payload()))
        with self.assertRaisesRegex(ValueError, 'admission outcome'):
            replay_requests(NOW.date(), BASELINE, events[:-1]+(forged,))

    def test_activation_expiry_and_residence_still_advance_during_quiet_ticks(self):
        policy = SamplingPolicy('admin', 5, 20, 'immediate_cap')
        request = request_payload(ProducerIntent('future', 'manual', IntentType.ENSURE_PRESENT,
            frozenset({'MSFT'}), NOW, effective_from=NOW+timedelta(seconds=100),
            expires_at=NOW+timedelta(seconds=110),
            metadata={'sampling_channel':'hot','session_date':NOW.date().isoformat()}))
        states = replay_requests(NOW.date(), BASELINE, self.history(policy=policy, request=request), policy=policy)
        by_time = {s.as_of:s for s in states}
        self.assertFalse(by_time[NOW+timedelta(seconds=99)].applied.hot)
        self.assertEqual(by_time[NOW+timedelta(seconds=100)].applied.hot, {'MSFT'})
        self.assertFalse(by_time[NOW+timedelta(seconds=110)].desired.hot)
        self.assertEqual(by_time[NOW+timedelta(seconds=119)].applied.hot, {'MSFT'})
        self.assertFalse(by_time[NOW+timedelta(seconds=120)].applied.hot)

    def test_a_tampered_plain_baseline_is_revalidated_before_reuse(self):
        baseline = SamplingMembership(BASELINE.uni, BASELINE.focus, BASELINE.hot)
        object.__setattr__(baseline, 'hot', frozenset({'MSFT'}))
        with self.assertRaisesRegex(ValueError, 'Hot <= Focus <= Uni'):
            replay_requests(NOW.date(), baseline, self.history())

    def test_mutable_baseline_tokens_keep_per_construction_validation(self):
        class MutableText(str):
            valid = True
            def strip(self):
                return self
            def upper(self):
                return self if self.valid else 'CHANGED'
        symbol = MutableText('MSFT')
        baseline = SamplingMembership({symbol}, set(), set())
        events = self.history(baseline=baseline)
        symbol.valid = False
        with self.assertRaisesRegex(ValueError, 'canonical uppercase symbols'):
            replay_requests(NOW.date(), baseline, events)


if __name__ == '__main__':
    unittest.main()
