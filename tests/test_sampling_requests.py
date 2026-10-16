from __future__ import annotations

import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from mb_watchlist_coordinator.models import IntentType, ProducerIntent
from mb_watchlist_coordinator.sampling_projection import SamplingMembership
from mb_watchlist_coordinator.sampling_request_store import RequestConflictError, SamplingRequestStore
from mb_watchlist_coordinator.sampling_requests import replay_requests


NOW = datetime(2026, 10, 16, 14, tzinfo=timezone.utc)
SESSION = date(2026, 10, 16)
BASELINE = SamplingMembership(frozenset({"AAPL", "MSFT", "SPY"}), frozenset({"SPY"}), frozenset())


class Clock:
    value = NOW

    def __call__(self):
        return self.value


def intent(owner="manual", request_id="keep-msft", target="hot", **kwargs):
    return replace(ProducerIntent(
        request_id, owner, IntentType.ENSURE_PRESENT, frozenset({"MSFT"}), NOW,
        source_event_id="synthetic-" + owner,
        reason="Synthetic membership request",
        metadata={"sampling_channel": target, "session_date": SESSION.isoformat()},
    ), **kwargs)


class RequestStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "requests.sqlite3"
        self.clock = Clock()
        self.store = self.reopen()
        self.store.initialize()

    def reopen(self):
        return SamplingRequestStore(self.path, session_date=SESSION, baseline=BASELINE, clock=self.clock)

    def submit(self, owner="manual", request_id="keep-msft", target="hot", **kwargs):
        return self.store.submit_request(intent(owner, request_id, target, **kwargs), actor_id=owner)

    def test_two_sources_cancel_independently_and_last_is_eligible(self):
        self.submit()
        self.submit("halts", "halt-001")
        state = self.store.states()[-1]
        self.assertEqual(state.reasons_for("MSFT", "hot"), (("halts", "halt-001"), ("manual", "keep-msft")))
        self.store.cancel_request("withdraw-manual", owner_id="manual", request_id="keep-msft", actor_id="manual")
        state = self.reopen().states()[-1]
        self.assertEqual(state.desired.hot, {"MSFT"})
        self.assertEqual(state.reasons_for("MSFT", "hot"), (("halts", "halt-001"),))
        self.store.cancel_request("withdraw-halt", owner_id="halts", request_id="halt-001", actor_id="halts")
        state = self.reopen().states()[-1]
        self.assertEqual(state.desired.hot, set())
        self.assertEqual(state.retained.hot, {"MSFT"})
        self.assertEqual(state.demotion_eligible_hot, ("MSFT",))
        self.assertEqual(state.demotion_eligible_focus, ("MSFT",))

    def test_foreign_cancellation_is_durably_rejected(self):
        self.submit("halts", "halt-001")
        result = self.store.cancel_request("foreign", owner_id="halts", request_id="halt-001", actor_id="manual")
        self.assertFalse(result.event.accepted)
        self.assertEqual(result.event.rejection_reason, "actor_does_not_own_request")
        state = self.reopen().states()[-1]
        self.assertEqual(state.desired.hot, {"MSFT"})
        self.assertEqual(state.rejected_count, 1)
        self.assertFalse(self.reopen().events()[-1].accepted)

    def test_request_actor_cannot_impersonate_payload_producer(self):
        result = self.store.submit_request(intent("halts"), actor_id="manual")
        self.assertFalse(result.event.accepted)
        self.assertEqual(self.reopen().states()[-1].retained, BASELINE)

    def test_request_ids_are_scoped_to_source(self):
        self.submit("manual", "same")
        self.submit("halts", "same")
        self.store.cancel_request("remove", owner_id="manual", request_id="same", actor_id="manual")
        self.assertEqual(self.store.states()[-1].reasons_for("MSFT", "hot"), (("halts", "same"),))

    def test_identical_request_and_cancellation_retries_keep_original_receipt(self):
        first = self.submit()
        self.clock.value += timedelta(seconds=1)
        retry = self.submit()
        self.assertFalse(retry.inserted)
        self.assertEqual(first.event, retry.event)
        first = self.store.cancel_request("cancel", owner_id="manual", request_id="keep-msft", actor_id="manual")
        retry = self.reopen().cancel_request("cancel", owner_id="manual", request_id="keep-msft", actor_id="manual")
        self.assertFalse(retry.inserted)
        self.assertEqual(first.event, retry.event)
        self.assertEqual(len(self.store.events()), 2)

    def test_conflicting_request_or_cancellation_identity_is_refused(self):
        self.submit()
        with self.assertRaises(RequestConflictError):
            self.submit(reason="changed payload")
        self.store.cancel_request("cancel", owner_id="manual", request_id="keep-msft", actor_id="manual")
        with self.assertRaises(RequestConflictError):
            self.store.cancel_request("cancel", owner_id="manual", request_id="different", actor_id="manual")
        self.assertEqual(len(self.store.events()), 2)

    def test_expiry_becomes_eligible_only_at_a_recorded_tick(self):
        self.submit(expires_at=NOW + timedelta(seconds=10))
        self.clock.value = NOW + timedelta(seconds=10)
        self.assertEqual(self.reopen().states()[-1].desired.hot, {"MSFT"})
        self.store.tick("expiry")
        state = self.reopen().states()[-1]
        self.assertEqual(state.desired.hot, set())
        self.assertEqual(state.retained.hot, {"MSFT"})
        self.assertEqual(state.demotion_eligible_hot, ("MSFT",))

    def test_future_request_activates_at_recorded_boundary(self):
        self.submit(effective_from=NOW + timedelta(seconds=10))
        self.assertEqual(self.store.states()[-1].retained, BASELINE)
        self.clock.value = NOW + timedelta(seconds=10)
        self.store.tick("activation")
        self.assertEqual(self.store.states()[-1].desired.hot, {"MSFT"})

    def test_session_end_caps_unbounded_request(self):
        self.submit()
        self.clock.value = datetime(2026, 10, 17, 4, tzinfo=timezone.utc)
        self.store.tick("session-end")
        state = self.store.states()[-1]
        self.assertEqual(state.active_requests, ())
        self.assertEqual(state.demotion_eligible_hot, ("MSFT",))

    def test_focus_request_does_not_demand_hot(self):
        self.submit(target="focus")
        state = self.store.states()[-1]
        self.assertEqual(state.desired.focus, {"SPY", "MSFT"})
        self.assertEqual(state.desired.hot, set())

    def test_fixed_baseline_members_survive_withdrawal(self):
        self.store.submit_request(intent(symbols=frozenset({"SPY"}), metadata={"sampling_channel": "focus", "session_date": SESSION.isoformat()}), actor_id="manual")
        self.store.cancel_request("cancel", owner_id="manual", request_id="keep-msft", actor_id="manual")
        state = self.store.states()[-1]
        self.assertEqual(state.desired, BASELINE)
        self.assertEqual(state.demotion_eligible_focus, ())

    def test_outside_uni_or_wrong_session_is_recorded_rejection(self):
        a = self.submit(symbols=frozenset({"NVDA"})).event
        b = self.submit(request_id="wrong-day", metadata={"sampling_channel": "hot", "session_date": "2000-01-01"}).event
        self.assertEqual((a.rejection_reason, b.rejection_reason), ("outside_fixed_uni", "session_mismatch"))
        self.assertEqual(self.store.states()[-1].retained, BASELINE)

    def test_created_after_receipt_or_already_expired_is_rejected(self):
        a = self.submit(created_at=NOW + timedelta(seconds=1)).event
        b = self.submit(request_id="expired", created_at=NOW - timedelta(seconds=2), expires_at=NOW).event
        self.assertEqual((a.rejection_reason, b.rejection_reason), ("creation_after_receipt", "request_already_expired"))

    def test_unknown_request_cancellation_is_rejected(self):
        result = self.store.cancel_request("missing", owner_id="manual", request_id="missing", actor_id="manual")
        self.assertEqual(result.event.rejection_reason, "unknown_request")

    def test_withdrawn_request_never_reactivates_on_retry_or_tick(self):
        self.submit()
        self.store.cancel_request("cancel", owner_id="manual", request_id="keep-msft", actor_id="manual")
        self.submit()
        self.store.tick("later")
        self.assertEqual(self.store.states()[-1].desired.hot, set())

    def test_request_metadata_is_snapshot_immutable(self):
        metadata = {"sampling_channel": "hot", "session_date": SESSION.isoformat(), "nested": [1]}
        result = self.submit(metadata=metadata)
        metadata["nested"].append(2)
        self.assertEqual(result.event.payload["metadata"]["nested"], (1,))
        with self.assertRaises(TypeError):
            result.event.payload["metadata"]["change"] = True

    def test_naive_clock_and_clock_reversal_fail_without_append(self):
        self.submit()
        self.clock.value = NOW.replace(tzinfo=None)
        with self.assertRaises(ValueError):
            self.store.tick("naive")
        self.clock.value = NOW - timedelta(seconds=1)
        with self.assertRaises(ValueError):
            self.store.tick("backwards")
        self.assertEqual(len(self.store.events()), 1)

    def test_malformed_and_unsupported_requests_fail_without_append(self):
        for change in ({"intent_type": IntentType.FORCE_ABSENT}, {"supersession_key": "replace"},
                       {"created_at": NOW.replace(tzinfo=None)}, {"expires_at": NOW},
                       {"metadata": {"sampling_channel": "hot", "session_date": SESSION.isoformat(), "nan": float("nan")}}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.submit(**change)
        self.assertEqual(len(self.store.events()), 0)

    def test_restart_replays_every_checkpoint_identically(self):
        self.submit()
        self.submit("halts", "halt-001")
        self.store.cancel_request("cancel", owner_id="manual", request_id="keep-msft", actor_id="manual")
        first = tuple(s.payload() for s in self.store.states())
        second = tuple(s.payload() for s in self.reopen().states())
        self.assertEqual(first, second)

    def test_changed_history_or_missing_event_fails_closed(self):
        self.submit()
        self.submit("halts", "halt-001")
        events = self.store.events()
        with self.assertRaises(ValueError):
            replay_requests(SESSION, BASELINE, events[1:])
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute("UPDATE request_event SET actor_id='forged' WHERE sequence=1")
        with self.assertRaises(ValueError):
            self.reopen().states()

    def test_wrong_identity_and_unrelated_database_are_preserved(self):
        other = SamplingRequestStore(self.path, session_date=date(2026, 10, 17), baseline=BASELINE)
        with self.assertRaises(ValueError):
            other.initialize()
        self.assertEqual(self.store.events(), ())
        path = self.path.with_name("unrelated.sqlite3")
        with closing(sqlite3.connect(path)) as connection, connection:
            connection.execute("CREATE TABLE unrelated (id INTEGER)")
        with self.assertRaises(ValueError):
            SamplingRequestStore(path, session_date=SESSION, baseline=BASELINE).initialize()
        with closing(sqlite3.connect(path)) as connection:
            self.assertEqual(connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall(), [("unrelated",)])

    def test_parallel_appenders_preserve_all_commands_and_chain(self):
        def append(n):
            return self.reopen().submit_request(intent("worker", str(n)), actor_id="worker")
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(append, range(12)))
        self.assertTrue(all(r.inserted for r in results))
        self.assertEqual(len(self.store.events()), 12)
        self.assertEqual(len(self.store.states()[-1].active_requests), 12)
