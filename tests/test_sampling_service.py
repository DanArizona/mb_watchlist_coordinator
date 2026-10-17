from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import threading
import unittest
from contextlib import closing
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments/sampling_promotion_20261016/market_data/src"))
from mb_market_data.quote_journal_audit import audit_quote_journal
from mb_market_data.quote_observation_store import QuoteObservationStore
from mb_market_data.sampling_membership import SamplingHierarchyRevision
from mb_watchlist_coordinator.models import IntentType, ProducerIntent
from mb_watchlist_coordinator.sampling_journal import PublicationDeadlineMissed, SamplingJournal
from mb_watchlist_coordinator.sampling_policy import SamplingPolicy
from mb_watchlist_coordinator.sampling_projection import SamplingMembership
from mb_watchlist_coordinator.sampling_request_store import SamplingRequestStore
from mb_watchlist_coordinator.sampling_requests import plain
from mb_watchlist_coordinator.sampling_service import (PublicationSettings, SamplingPublicationService,
                                                     ServiceBusy, owner_lock)

BASELINE = SamplingMembership(frozenset({"AAPL", "MSFT", "SPY"}), frozenset({"SPY"}), frozenset())
POLICY = SamplingPolicy("proof-super-user", 0, 0, "immediate_cap")


def fixture(folder, *, policy=POLICY, real_clock=False, settings_values=None):
    # Unit fault drills use an explicit logical clock; the bounded runner below
    # separately exercises the actual loop with the actual wall clock.
    start = datetime.now(timezone.utc) + timedelta(seconds=0 if real_clock else 600)
    session = start.astimezone(ZoneInfo("America/New_York")).date()
    clock = [start]
    get_clock = (lambda: datetime.now(timezone.utc)) if real_clock else (lambda: clock[0])
    ledger = SamplingRequestStore(folder / "requests.sqlite3", session_date=session,
                                  baseline=BASELINE, policy=policy, clock=get_clock)
    ledger.initialize()
    store = QuoteObservationStore(folder / "membership.sqlite3", session_date=session, schema_version=2)
    store.initialize()
    store.record_membership_revision(SamplingHierarchyRevision(
        session_date=session, revision=0, effective_at=start + timedelta(seconds=0.1 if real_clock else -1),
        uni_symbols=tuple(BASELINE.uni), focus_symbols=tuple(BASELINE.focus), hot_symbols=(),
        source="isolated_publication_service_proof", metadata={"experimental": True, "logical_clock": not real_clock}))
    settings = PublicationSettings("proof-publication-authority", 0.05, 0.2, start + timedelta(minutes=5))
    if settings_values:
        settings = replace(settings, **settings_values)
    service = SamplingPublicationService(folder / "publication.sqlite3", request_store=ledger,
                                          journal=SamplingJournal(store), settings=settings, clock=get_clock)
    service.initialize()
    return ledger, store, service, clock


def request(ledger, rid="m1", owner="manual", symbol="MSFT", **kwargs):
    values = dict(intent_id=rid, producer_id=owner, intent_type=IntentType.ENSURE_PRESENT,
                  symbols=frozenset({symbol}), created_at=ledger.clock(),
                  source_event_id="synthetic-" + rid,
                  metadata={"session_date": ledger.session_date.isoformat(), "sampling_channel": "hot"})
    values.update(kwargs)
    return ledger.submit_request(ProducerIntent(**values), actor_id=owner)


def interruption(stage):
    def hook(actual):
        if actual == stage:
            raise RuntimeError("injected interruption " + stage)
    return hook


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.ledger, self.store, self.service, self.clock = fixture(self.folder)
        self.start = self.clock[0]

    def advance(self, seconds):
        self.clock[0] = self.start + timedelta(seconds=seconds)

    def reopen(self):
        s = self.service
        self.service = SamplingPublicationService(s.path, request_store=self.ledger,
            journal=SamplingJournal(self.store), settings=s.settings, clock=lambda: self.clock[0])
        self.service.initialize()
        return self.service

    def snapshot(self):
        return plain(self.service.snapshot())

    def latest(self):
        return self.store.membership_revisions_in_effective_order()[-1]

    def test_publishes_complete_hierarchy_and_acks_actual_receipt(self):
        request(self.ledger)
        self.assertEqual(self.service.cycle()["status"], "published")
        s = self.snapshot()
        self.assertIsNone(s["pending"])
        self.assertEqual(self.latest().hot_symbols, ("MSFT",))
        self.assertEqual(self.latest().focus_symbols, ("MSFT", "SPY"))
        ack = s["outcomes"][-1]
        self.assertEqual(ack["journal_receipt"]["published_at_utc"], self.latest().published_at.isoformat())
        self.assertEqual(ack["journal_receipt"]["content_sha256"], self.latest().content_sha256)
        self.assertTrue(audit_quote_journal(self.store.database_path).passed)

    def test_restart_after_commit_acks_same_revision_without_duplicate(self):
        request(self.ledger)
        with self.assertRaises(RuntimeError):
            self.service.cycle(fault_hook=interruption("after_commit"))
        original = self.latest()
        self.assertIsNotNone(self.snapshot()["pending"])
        self.advance(5); self.reopen().cycle()
        self.assertEqual(self.latest(), original)
        self.assertEqual(len(self.snapshot()["journal"]), 2)
        self.assertTrue(next(x for x in self.snapshot()["outcomes"] if x["kind"] == "acknowledged")["recovered"])

    def test_restart_after_ack_is_idle_and_preserves_receipt(self):
        request(self.ledger)
        with self.assertRaises(RuntimeError):
            self.service.cycle(fault_hook=interruption("after_ack"))
        old = self.snapshot()
        self.reopen().cycle()
        self.assertEqual(self.snapshot(), old)

    def test_uncommitted_plan_is_abandoned_and_rescheduled_after_missed_time(self):
        request(self.ledger)
        with self.assertRaises(RuntimeError):
            self.service.cycle(fault_hook=interruption("after_plan"))
        self.assertEqual(self.latest().revision, 0)
        self.advance(5); self.reopen().cycle()
        self.assertEqual(self.latest().revision, 1)
        self.assertGreater(self.latest().effective_at, self.clock[0])
        self.assertEqual([x["kind"] for x in self.snapshot()["outcomes"]], ["plan", "abandoned", "plan", "acknowledged"])

    def test_expired_uncommitted_request_is_not_promoted_on_restart(self):
        request(self.ledger, expires_at=self.start + timedelta(seconds=2))
        with self.assertRaises(RuntimeError):
            self.service.cycle(fault_hook=interruption("after_plan"))
        self.advance(5); self.reopen().cycle()
        self.assertEqual(self.latest().revision, 0)
        self.assertEqual(self.ledger.events()[-1].kind, "tick")
        self.assertEqual(self.ledger.states()[-1].applied, BASELINE)

    def test_expired_committed_plan_is_acked_then_current_demotion_published(self):
        request(self.ledger, expires_at=self.start + timedelta(seconds=2))
        with self.assertRaises(RuntimeError):
            self.service.cycle(fault_hook=interruption("after_commit"))
        self.advance(5); self.reopen().cycle()
        self.assertEqual(self.latest().revision, 2)
        self.assertEqual(self.latest().hot_symbols, ())
        self.assertEqual(sum(x["kind"] == "acknowledged" for x in self.snapshot()["outcomes"]), 2)

    def test_new_inputs_before_commit_abandon_plan(self):
        request(self.ledger)
        def withdraw(stage):
            if stage == "after_plan":
                self.ledger.cancel_request("c1", owner_id="manual", request_id="m1", actor_id="manual")
        self.assertEqual(self.service.cycle(fault_hook=withdraw)["status"], "recheck")
        self.service.cycle()
        self.assertEqual(self.latest().revision, 0)

    def test_expiry_gets_a_durable_tick_without_new_source_request(self):
        request(self.ledger, expires_at=self.start + timedelta(seconds=2)); self.service.cycle()
        self.advance(2); self.service.cycle()
        self.assertEqual(self.ledger.events()[-1].kind, "tick")
        self.assertEqual(self.latest().hot_symbols, ())
        self.assertEqual(self.latest().revision, 2)

    def test_future_activation_is_not_early_and_is_driven_by_tick(self):
        request(self.ledger, effective_from=self.start + timedelta(seconds=2))
        self.service.cycle(); self.assertEqual(self.latest().revision, 0)
        self.advance(2); self.service.cycle()
        self.assertEqual(self.ledger.events()[-1].kind, "tick")
        self.assertEqual(self.latest().hot_symbols, ("MSFT",))

    def test_demotion_deadline_survives_service_restart(self):
        other = self.folder / "delayed"; other.mkdir()
        self.ledger, self.store, self.service, self.clock = fixture(other, policy=replace(POLICY, demotion_grace_seconds=60, minimum_residence_seconds=120))
        self.start = self.clock[0]
        request(self.ledger); self.service.cycle()
        self.advance(10)
        self.ledger.cancel_request("c1", owner_id="manual", request_id="m1", actor_id="manual")
        self.service.cycle()
        deadline = self.ledger.states()[-1].demotion_holds[0]["demotion_at_utc"]
        self.advance(119); self.reopen().cycle()
        self.assertEqual(self.ledger.states()[-1].demotion_holds[0]["demotion_at_utc"], deadline)
        self.assertEqual(self.latest().hot_symbols, ("MSFT",))
        self.advance(120); self.service.cycle()
        self.assertEqual(self.latest().hot_symbols, ())

    def test_two_sources_and_restriction_expiry_recompute_current_demand(self):
        request(self.ledger); request(self.ledger, "h1", "halts"); self.service.cycle()
        self.ledger.cancel_request("c1", owner_id="manual", request_id="m1", actor_id="manual")
        self.service.cycle(); self.assertEqual(self.latest().revision, 1)
        self.ledger.restrict_symbol("cap", symbol="MSFT", max_group="uni", actor_id="proof-super-user", expires_at=self.start + timedelta(seconds=2))
        self.service.cycle(); self.assertEqual(self.latest().hot_symbols, ())
        self.advance(2); self.service.cycle()
        self.assertEqual(self.latest().hot_symbols, ("MSFT",))
        self.assertEqual(self.ledger.states()[-1].reasons_for("MSFT", "hot"), (("halts", "h1"),))

    def test_no_change_inputs_have_durable_outcomes_without_extra_revisions(self):
        request(self.ledger); self.service.cycle(); request(self.ledger, "h1", "halts")
        self.service.cycle(); self.service.cycle()
        self.assertEqual(self.latest().revision, 1)
        self.assertEqual(self.snapshot()["outcomes"][-1]["kind"], "no_change")
        self.assertEqual(self.snapshot()["processed_sequence"], len(self.ledger.events()))
        self.assertEqual(len(self.snapshot()["outcomes"]), 3)

    def test_known_boundary_inside_lead_defers_instead_of_scheduling_stale_promotion(self):
        request(self.ledger, expires_at=self.start + timedelta(seconds=0.1))
        self.assertEqual(self.service.cycle()["status"], "deferred")
        self.service.cycle(); self.assertEqual(len(self.snapshot()["outcomes"]), 1)
        self.advance(1); self.service.cycle()
        self.assertEqual(self.latest().revision, 0)

    def test_write_failure_rolls_back_all_channels_and_input_survives(self):
        request(self.ledger)
        with closing(sqlite3.connect(self.store.database_path)) as c, c:
            c.execute("CREATE TRIGGER fail_channel BEFORE INSERT ON sampling_channel_revision BEGIN SELECT RAISE(ABORT,'injected channel failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.service.cycle()
        self.assertEqual(self.latest().revision, 0)
        self.assertIsNotNone(self.snapshot()["pending"])
        self.assertEqual(len(self.ledger.events()), 1)
        with closing(sqlite3.connect(self.store.database_path)) as c, c:
            c.execute("DROP TRIGGER fail_channel")
        self.reopen().cycle()
        self.assertEqual(self.latest().revision, 1)
        self.assertTrue(audit_quote_journal(self.store.database_path).passed)

    def test_operational_failure_is_retained_then_recovered(self):
        request(self.ledger)
        with patch.object(self.service.journal, "publish", side_effect=sqlite3.OperationalError("database is locked")):
            with self.assertRaises(sqlite3.OperationalError):
                self.service.cycle()
        self.assertEqual(self.snapshot()["outcomes"][-1]["kind"], "write_failed")
        self.reopen().cycle(); self.assertEqual(self.latest().revision, 1)

    def test_foreign_journal_revision_is_preserved_and_refused(self):
        v = self.latest()
        self.store.record_membership_revision(replace(v, revision=1, source="foreign", published_at=None))
        with self.assertRaisesRegex(ValueError, "Journal prefix"):
            self.service.cycle()
        self.assertEqual(self.latest().source, "foreign")

    def test_changed_outcome_is_detected(self):
        request(self.ledger); self.service.cycle()
        with closing(sqlite3.connect(self.service.path)) as c, c:
            c.execute("UPDATE publication_event SET payload='{}' WHERE sequence=1")
        with self.assertRaisesRegex(ValueError, "sequence/hash"):
            self.service.cycle()

    def test_changed_request_history_is_refused_before_any_new_publication(self):
        request(self.ledger); self.service.cycle()
        with closing(sqlite3.connect(self.ledger.path)) as c, c:
            c.execute("UPDATE request_event SET payload='{}' WHERE sequence=1")
        with self.assertRaises((ValueError, KeyError)):
            self.service.cycle()
        self.assertEqual(self.latest().revision, 1)

    def test_store_deadline_rejection_is_abandoned_then_rescheduled(self):
        request(self.ledger)
        with patch.object(self.service.journal, "publish", side_effect=PublicationDeadlineMissed("missed")):
            self.assertEqual(self.service.cycle()["status"], "recheck")
        self.assertIsNone(self.snapshot()["pending"])
        self.assertEqual(self.latest().revision, 0)
        self.advance(1); self.service.cycle()
        self.assertEqual(self.latest().revision, 1)

    def test_unacknowledged_different_commit_is_refused(self):
        request(self.ledger)
        with self.assertRaises(RuntimeError):
            self.service.cycle(fault_hook=interruption("after_plan"))
        p = self.snapshot()["pending"]["proposal"]
        self.store.record_membership_revision(replace(self.service.journal.value(p), source="other"))
        with self.assertRaisesRegex(ValueError, "differs from pending"):
            self.reopen()

    def test_identity_and_policy_changes_cannot_reopen_service(self):
        changed = SamplingPublicationService(self.service.path, request_store=self.ledger,
            journal=SamplingJournal(self.store), settings=replace(self.service.settings, poll_seconds=2), clock=lambda: self.clock[0])
        with self.assertRaisesRegex(ValueError, "identity/settings"):
            changed.initialize()
        self.assertEqual(self.snapshot()["outcomes"], [])
        with self.assertRaises(TypeError):
            self.service.identity["settings"]["authority_id"] = "foreign"

    def test_clock_reversal_and_naive_clock_do_not_publish(self):
        self.service.cycle(); old = self.snapshot()
        self.advance(-1)
        with self.assertRaisesRegex(ValueError, "clock moved backwards"):
            self.service.cycle()
        self.assertEqual(self.snapshot(), old)
        self.service.clock = lambda: datetime(2026, 10, 17)
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            self.service.cycle()

    def test_owner_lock_serializes_two_instances_and_is_released(self):
        other = self.reopen()
        with owner_lock(self.service.lock_path):
            with self.assertRaises(ServiceBusy):
                other.cycle()
        other.cycle()
        self.assertEqual(len(self.ledger.events()), 1)

    def test_publication_window_ends_without_processing_into_next_session(self):
        request(self.ledger); self.advance(300)
        self.assertEqual(self.service.cycle()["status"], "closed")
        self.assertEqual(self.latest().revision, 0)
        self.assertEqual(self.snapshot()["processed_sequence"], 0)
        self.assertEqual(len(self.snapshot()["outcomes"]), 1)

    def test_loop_stops_promptly_even_with_long_poll_interval(self):
        self.service.settings = replace(self.service.settings, poll_seconds=60)
        # A differently configured service gets its own correctly bound ledger.
        self.service = SamplingPublicationService(self.folder / "other-service.sqlite3", request_store=self.ledger,
            journal=SamplingJournal(self.store), settings=self.service.settings, clock=lambda: self.clock[0])
        self.service.initialize()
        stop, ready = threading.Event(), threading.Event()
        errors = []
        def run():
            try:
                self.service.run(stop, on_status=lambda _: ready.set())
            except BaseException as exc:
                errors.append(exc)
        thread = threading.Thread(target=run); thread.start()
        try:
            self.assertTrue(ready.wait(3)); stop.set(); thread.join(2)
            self.assertFalse(thread.is_alive()); self.assertEqual(errors, [])
        finally:
            stop.set(); thread.join(6)

    def test_invalid_settings_and_database_aliases_are_rejected(self):
        for change in ({"poll_seconds": 0}, {"publication_lead_seconds": float("nan")},
                       {"publication_lead_seconds": True}, {"authority_id": ""}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                replace(self.service.settings, **change)
        with self.assertRaisesRegex(ValueError, "different files"):
            SamplingPublicationService(self.ledger.path, request_store=self.ledger,
                journal=SamplingJournal(self.store), settings=self.service.settings)

    def test_missing_outcome_ledger_cannot_adopt_already_owned_journal(self):
        request(self.ledger); self.service.cycle()
        self.advance(1)
        self.ledger.cancel_request("c1", owner_id="manual", request_id="m1", actor_id="manual")
        self.service.cycle()
        self.assertEqual(self.latest().hot_symbols, ())
        self.service.path.unlink()
        with self.assertRaisesRegex(ValueError, "restore its original"):
            self.reopen()

    def test_loop_reports_operational_retry_then_recovers_and_integrity_error_stops(self):
        stop = threading.Event()
        statuses = []
        request(self.ledger)
        original = self.service.cycle
        failures = [True]
        def cycle():
            if failures:
                failures.pop(); raise sqlite3.OperationalError("busy proof")
            return original()
        def status(value):
            statuses.append(value)
            if value["status"] == "published":
                stop.set()
        with patch.object(self.service, "cycle", side_effect=cycle):
            self.assertEqual(self.service.run(stop, on_status=status)["status"], "stopped")
        self.assertEqual([x["status"] for x in statuses], ["retrying", "published"])
        with patch.object(self.service, "cycle", side_effect=ValueError("changed history")):
            with self.assertRaisesRegex(ValueError, "changed history"):
                self.service.run(threading.Event())


if __name__ == "__main__":
    unittest.main()
