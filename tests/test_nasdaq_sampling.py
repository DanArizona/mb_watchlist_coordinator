from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from mb_watchlist_coordinator.models import IntentType, ProducerIntent
from mb_watchlist_coordinator.nasdaq_sampling import (
    HaltProducerSettings, HaltSnapshot, NasdaqSamplingProducer, halt_event_id,
)
from mb_watchlist_coordinator.sampling_policy import SamplingPolicy
from mb_watchlist_coordinator.sampling_projection import SamplingMembership
from mb_watchlist_coordinator.sampling_request_store import SamplingRequestStore
from mb_watchlist_coordinator.sampling_requests import digest, plain

ET = ZoneInfo("America/New_York")
START = datetime(2026, 8, 14, 9, 30, tzinfo=ET)


class NasdaqTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.at = START
        self.settings = HaltProducerSettings("nasdaq-test", ("LUDP", "M"), "regular_close", False)
        self.members = SamplingMembership(frozenset({"AAPL", "MSFT", "SPY"}), frozenset({"SPY"}), frozenset())
        self.ledger = SamplingRequestStore(self.root / "requests.sqlite3", session_date=date(2026, 8, 14),
            baseline=self.members, clock=lambda: self.at, policy=SamplingPolicy("admin", 60, 120, "immediate_cap"))
        self.ledger.initialize()
        self.producer = self.reopen()

    def reopen(self, **changes):
        value = NasdaqSamplingProducer(self.root / "producer.sqlite3", request_store=self.ledger,
            settings=changes.get("settings", self.settings), clock=lambda: self.at)
        value.initialize()
        return value

    def row(self, seconds=1, symbol="MSFT", reason="LUDP", **extra):
        t = START + timedelta(seconds=seconds)
        return {"symbol": symbol, "halt_date": t.strftime("%m/%d/%Y"),
                "halt_time": t.strftime("%H:%M:%S.%f"), "reason_code": reason, **extra}

    def feed(self, cid, rows=(), mode="CURRENT", retrieved=None, **kwargs):
        return HaltSnapshot(cid, retrieved or self.at, mode, digest(rows), tuple(rows),
                            {"synthetic_fixture": True, **kwargs})

    def baseline(self, rows=()):
        return self.producer.record_snapshot(self.feed("baseline", rows))

    def queue(self, rows=None, seconds=2, cid="new"):
        self.at = START + timedelta(seconds=seconds)
        return self.producer.record_snapshot(self.feed(cid, rows if rows is not None else [self.row()]))

    def statuses(self):
        return [r["status"] for r in self.producer.snapshot()["outcomes"][-1]["events"]]

    def test_initial_current_snapshot_is_only_a_baseline(self):
        self.baseline([self.row(-1)])
        self.assertEqual(self.statuses(), ["baseline"])
        self.assertFalse(self.producer.snapshot()["pending"])

    def test_new_eligible_event_queues_and_delivers_hot_plus_focus(self):
        self.baseline(); self.queue()
        self.assertEqual(self.statuses(), ["request_queued"])
        self.producer.deliver_pending()
        state = self.ledger.states()[-1]
        self.assertEqual(state.applied.hot, {"MSFT"})
        self.assertEqual(state.applied.focus, {"SPY", "MSFT"})
        self.assertEqual(state.applied.uni, self.members.uni)

    def test_exact_capture_retry_keeps_original_receipt(self):
        snap = self.feed("baseline")
        a, inserted = self.producer.record_snapshot(snap)
        self.at += timedelta(seconds=20)
        b, again = self.producer.record_snapshot(snap)
        self.assertTrue(inserted); self.assertFalse(again); self.assertEqual(a, b)

    def test_conflicting_capture_identity_is_refused(self):
        self.baseline()
        with self.assertRaises(ValueError):
            self.producer.record_snapshot(replace(self.feed("baseline"), raw_sha256="1" * 64))
        self.assertEqual(len(self.producer.snapshot()["receipts"]), 1)

    def test_repeated_poll_does_not_repeat_request(self):
        self.baseline(); self.queue(); self.producer.deliver_pending()
        self.queue(seconds=3, cid="repeat")
        self.assertEqual(self.statuses(), ["repeat"])
        self.assertEqual(self.producer.deliver_pending(), ())
        self.assertEqual(len(self.ledger.events()), 1)

    def test_changed_reason_and_resumption_are_updates_not_new_events(self):
        self.baseline(); self.queue(); self.producer.deliver_pending()
        self.queue([self.row(reason="T3", resumption_trade_time="09:35:01")], seconds=3, cid="update")
        self.assertEqual(self.statuses(), ["updated"])
        self.assertEqual(self.producer.deliver_pending(), ())
        self.assertEqual(self.ledger.states()[-1].applied.hot, {"MSFT"})

    def test_later_distinct_halt_for_same_symbol_has_another_request(self):
        self.baseline(); self.queue(); self.producer.deliver_pending()
        self.queue([self.row(4)], seconds=5, cid="second-halt")
        self.producer.deliver_pending()
        self.assertEqual(len(self.ledger.events()), 2)
        self.assertNotEqual(self.ledger.events()[0].command_id, self.ledger.events()[1].command_id)

    def test_historical_queries_are_audit_only_and_do_not_start_current_baseline(self):
        self.producer.record_snapshot(self.feed("history", [self.row(-1)], "HISTORICAL"))
        self.baseline([self.row(-1)])
        self.assertEqual(self.statuses(), ["baseline"])
        self.assertFalse(self.producer.snapshot()["commands"])

    def test_event_before_startup_is_not_promoted_when_missing_from_initial_feed(self):
        self.baseline(); self.queue([self.row(-1)])
        self.assertEqual(self.statuses(), ["predates_startup"])

    def test_live_startup_floor_uses_capture_not_later_adapter_receipt(self):
        self.at = START + timedelta(seconds=2)
        self.producer.record_snapshot(self.feed("baseline", retrieved=START))
        self.queue(seconds=3)
        self.assertEqual(self.statuses(), ["request_queued"])

    def test_outside_fixed_uni_is_recorded_without_request(self):
        self.baseline(); self.queue([self.row(symbol="OTHER")])
        self.assertEqual(self.statuses(), ["outside_fixed_uni"])
        self.assertFalse(self.producer.snapshot()["pending"])

    def test_unselected_reason_is_recorded_without_request(self):
        self.baseline(); self.queue([self.row(reason="T1")])
        self.assertEqual(self.statuses(), ["reason_not_selected"])

    def test_reclassification_of_seen_event_does_not_create_a_request(self):
        self.baseline(); self.queue([self.row(reason="T1")])
        self.queue([self.row(reason="M")], seconds=3, cid="changed-code")
        self.assertEqual(self.statuses(), ["updated"])
        self.assertFalse(self.producer.snapshot()["pending"])

    def test_other_session_is_not_promoted(self):
        self.baseline(); self.queue([self.row(-86400)])
        self.assertEqual(self.statuses(), ["different_session"])

    def test_regular_close_excludes_new_receipts(self):
        self.baseline(); self.queue([self.row(23000)], seconds=23400)
        self.assertEqual(self.statuses(), ["outside_receipt_window"])

    def test_premarket_event_after_early_startup_is_not_promoted(self):
        self.at = START - timedelta(hours=1)
        self.baseline()
        self.queue([self.row(-60)], seconds=2)
        self.assertEqual(self.statuses(), ["outside_halt_window"])

    def test_future_halt_fails_without_appending_snapshot(self):
        self.baseline()
        with self.assertRaises(ValueError): self.queue([self.row(3)])
        self.assertEqual(len(self.producer.snapshot()["receipts"]), 1)

    def test_future_capture_is_refused_in_live_mode(self):
        with self.assertRaises(ValueError):
            self.producer.record_snapshot(self.feed("bad", retrieved=START + timedelta(seconds=1)))
        self.assertFalse(self.producer.snapshot()["receipts"])

    def test_replay_mode_must_be_configured_and_is_retained_in_request(self):
        self.settings = replace(self.settings, replay_mode=True)
        self.producer = NasdaqSamplingProducer(self.root / "replay.sqlite3", request_store=self.ledger,
            settings=self.settings, clock=lambda: self.at)
        self.producer.initialize(); self.baseline(); self.queue()
        self.producer.deliver_pending()
        self.assertTrue(self.ledger.events()[0].payload["metadata"]["replay_mode"])

    def test_capture_and_receipt_clocks_cannot_go_backwards(self):
        self.baseline(); self.queue()
        with self.assertRaises(ValueError):
            self.producer.record_snapshot(self.feed("old-capture", retrieved=START))
        self.at = START - timedelta(seconds=1)
        with self.assertRaises(ValueError): self.producer.record_snapshot(self.feed("old-receipt"))
        self.assertEqual(len(self.producer.snapshot()["receipts"]), 2)

    def test_pending_input_survives_restart(self):
        self.baseline(); self.queue()
        before = self.producer.snapshot()
        self.producer = self.reopen()
        self.assertEqual(before, self.producer.snapshot())
        self.producer.deliver_pending()
        self.assertEqual(self.ledger.states()[-1].applied.hot, {"MSFT"})

    def test_crash_after_request_commit_before_ack_retries_original_receipt(self):
        self.baseline(); self.queue()
        def fail(_): raise RuntimeError("injected interruption after commit")
        with self.assertRaises(RuntimeError): self.producer.deliver_pending(after_submit=fail)
        event = self.ledger.events()[0]
        self.assertEqual(len(self.producer.snapshot()["pending"]), 1)
        self.at += timedelta(seconds=20)
        self.producer = self.reopen()
        result = self.producer.deliver_pending()[0]
        self.assertFalse(result.inserted); self.assertEqual(result.event, event)
        self.assertFalse(self.producer.snapshot()["pending"])

    def test_failed_request_write_leaves_command_pending(self):
        self.baseline(); self.queue()
        with patch.object(self.ledger, "submit_request", side_effect=RuntimeError("injected write failure")):
            with self.assertRaises(RuntimeError): self.producer.deliver_pending()
        self.assertEqual(len(self.producer.snapshot()["pending"]), 1)
        self.assertFalse(self.ledger.events())

    def test_retry_cannot_reactivate_withdrawn_request(self):
        self.baseline(); self.queue()
        def fail(_): raise RuntimeError("injected lost ack")
        with self.assertRaises(RuntimeError): self.producer.deliver_pending(after_submit=fail)
        e = self.ledger.events()[0]
        self.ledger.cancel_request("withdraw", owner_id=e.actor_id, request_id=e.command_id, actor_id=e.actor_id)
        self.producer.deliver_pending()
        self.assertFalse(self.ledger.states()[-1].active_requests)
        self.assertEqual(len(self.ledger.events()), 2)

    def test_pending_request_expired_during_outage_is_terminally_rejected(self):
        self.baseline(); self.queue()
        self.at = START.replace(hour=16)
        result = self.producer.deliver_pending()[0]
        self.assertFalse(result.event.accepted)
        self.assertEqual(result.event.rejection_reason, "request_already_expired")
        self.assertFalse(self.producer.snapshot()["pending"])

    def test_request_expires_at_regular_close_not_at_resumption(self):
        self.baseline(); self.queue([self.row(resumption_trade_time="09:35:01")])
        self.producer.deliver_pending()
        e = self.ledger.events()[0]
        self.assertEqual(datetime.fromisoformat(e.payload["expires_at_utc"]), START.replace(hour=16, minute=0))
        self.assertEqual(datetime.fromisoformat(e.payload["created_at_utc"]), self.at)
        self.at = START.replace(hour=16); self.ledger.tick("close")
        self.assertFalse(self.ledger.states()[-1].active_requests)

    def test_manual_withdrawal_leaves_nasdaq_demand(self):
        self.baseline(); self.queue(); self.producer.deliver_pending()
        self.ledger.submit_request(ProducerIntent("manual", "manual", IntentType.ENSURE_PRESENT,
            frozenset({"MSFT"}), self.at, metadata={"session_date": "2026-08-14", "sampling_channel": "hot"}), actor_id="manual")
        self.ledger.cancel_request("cancel", owner_id="manual", request_id="manual", actor_id="manual")
        self.assertEqual(self.ledger.states()[-1].reasons_for("MSFT", "hot")[0][0], "nasdaq-test")

    def test_super_user_cap_retains_request_for_current_demand_reentry(self):
        self.baseline()
        self.ledger.restrict_symbol("cap", symbol="MSFT", max_group="focus", actor_id="admin")
        self.queue(); self.producer.deliver_pending()
        state = self.ledger.states()[-1]
        self.assertFalse(state.applied.hot); self.assertEqual(len(state.active_requests), 1)
        self.ledger.clear_restriction("clear", symbol="MSFT", restriction_id="cap", actor_id="admin")
        self.assertEqual(self.ledger.states()[-1].applied.hot, {"MSFT"})

    def test_identical_duplicate_rows_are_one_event_but_conflicting_rows_fail(self):
        self.baseline(); self.queue([self.row(), self.row()])
        self.assertEqual(len(self.producer.snapshot()["pending"]), 1)
        with self.assertRaises(ValueError):
            self.queue([self.row(), self.row(reason="M")], seconds=3, cid="conflict")

    def test_metadata_and_snapshots_are_immutable(self):
        rows = [self.row()]; snap = self.feed("new", rows, retrieved=START + timedelta(seconds=2))
        rows[0]["reason_code"] = "T1"
        self.assertEqual(snap.records[0]["reason_code"], "LUDP")
        with self.assertRaises(TypeError): snap.provenance["extra"] = 1
        self.baseline(); self.at += timedelta(seconds=2); self.producer.record_snapshot(snap)
        with self.assertRaises(TypeError): self.producer.snapshot()["commands"]["x"] = 1

    def test_history_and_delivery_tampering_are_detected(self):
        self.baseline(); self.queue(); self.producer.deliver_pending()
        with closing(sqlite3.connect(self.producer.path)) as c:
            with c:
                cid, raw = c.execute("SELECT * FROM halt_delivery").fetchone()
                ack = json.loads(raw); ack["request_sequence"] = 999
                c.execute("UPDATE halt_delivery SET payload=? WHERE command_id=?", (json.dumps(ack), cid))
        with self.assertRaises(ValueError): self.producer.snapshot()

    def test_changed_or_deleted_receipt_is_detected(self):
        self.baseline(); self.queue()
        with closing(sqlite3.connect(self.producer.path)) as c:
            with c: c.execute("DELETE FROM halt_receipt WHERE sequence=1")
        with self.assertRaises(ValueError): self.producer.snapshot()

    def test_wrong_configuration_or_unrelated_database_is_preserved(self):
        self.baseline()
        with self.assertRaises(ValueError): self.reopen(settings=replace(self.settings, producer_id="other"))
        unrelated = self.root / "unrelated.sqlite3"
        with closing(sqlite3.connect(unrelated)) as c:
            with c: c.execute("CREATE TABLE keep_me(x)")
        other = NasdaqSamplingProducer(unrelated, request_store=self.ledger, settings=self.settings)
        with self.assertRaises(ValueError): other.initialize()
        with closing(sqlite3.connect(unrelated)) as c:
            self.assertEqual(c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall(), [("keep_me",)])

    def test_changed_request_ledger_cannot_satisfy_prior_acknowledgement(self):
        self.baseline(); self.queue(); self.producer.deliver_pending()
        other = SamplingRequestStore(self.root / "other.sqlite3", session_date=self.ledger.session_date,
            baseline=self.members, policy=self.ledger.policy, clock=lambda: self.at)
        other.initialize()
        self.producer.request_store = other
        with self.assertRaises(ValueError): self.producer.snapshot()

    def test_parallel_capture_and_delivery_retries_preserve_single_command(self):
        self.baseline(); self.at += timedelta(seconds=2)
        snap = self.feed("parallel", [self.row()])
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.producer.record_snapshot(snap), range(2)))
        self.assertEqual(sum(x[1] for x in results), 1)
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda _: self.producer.deliver_pending(), range(2)))
        self.assertEqual(len(self.ledger.events()), 1)

    def test_malformed_inputs_and_nonfinite_provenance_are_refused(self):
        for changes in ({"symbol": " msft "}, {"halt_time": "bad"}, {"halt_date": "bad"}, {"reason_code": "ludp"}):
            with self.assertRaises(ValueError): self.feed("bad", [{**self.row(), **changes}])
        with self.assertRaises(ValueError): self.feed("bad", invalid=float("nan"))
        with self.assertRaises(ValueError): self.feed("bad", retrieved=datetime(2026, 8, 14))

    def test_settings_are_explicit_and_event_identity_ignores_mutable_fields(self):
        for codes, lifetime, replay in (((), "regular_close", False), (("LUDP",), "resumption", False), (("LUDP",), "regular_close", 1)):
            with self.assertRaises(ValueError): HaltProducerSettings("p", codes, lifetime, replay)
        a = self.row(); b = {**a, "halt_time": "09:30:01", "reason_code": "T3"}
        self.assertEqual(halt_event_id(a), halt_event_id(b))
        self.assertNotEqual(halt_event_id(a), halt_event_id(self.row(2)))


if __name__ == "__main__":
    unittest.main()
