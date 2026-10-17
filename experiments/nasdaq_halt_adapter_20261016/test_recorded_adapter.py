from __future__ import annotations
import json
import shutil
import sqlite3
import tempfile
import unittest
from contextlib import closing
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from mb_market_data.quote_observation_store import QuoteObservationStore
from mb_market_data.sampling_membership import SamplingHierarchyRevision
from mb_watchlist_coordinator.nasdaq_sampling import HaltProducerSettings, NasdaqSamplingProducer
from mb_watchlist_coordinator.sampling_projection import SamplingMembership
from mb_watchlist_coordinator.sampling_request_store import SamplingRequestStore
from recorded_proof import (
    EXPERIMENT, load_captures, parse_saved, replay_original_current, run_proof,
    simulation_fixture, exercise_simulation, publish_states, verify_evidence,
)


class RecordedAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.captures, cls.inventory = load_captures()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_all_twelve_real_capture_pairs_parse_without_editing_originals(self):
        self.assertEqual(len(self.captures), 12)
        self.assertEqual(sum(len(s.records) for s in self.captures), 690)
        self.assertEqual(sum(s.retrieval_mode == "CURRENT" for s in self.captures), 4)
        self.assertEqual(sum(s.retrieval_mode == "HISTORICAL" for s in self.captures), 8)
        self.assertTrue(any(x["differences_from_legacy_json"] for x in self.inventory))

    def test_original_current_sequence_has_no_promotion_and_preserves_receipts(self):
        report = replay_original_current(self.root, self.captures)
        self.assertEqual(report["request_receipts"], 0)
        self.assertEqual(len(report["receipts"]), 4)
        self.assertEqual(report["outcomes"][0]["status"], "initial_baseline")
        self.assertEqual({e["status"] for e in report["outcomes"][1]["events"]}, {"repeat"})
        self.assertEqual(sum(e["status"] == "outside_receipt_window" for e in report["outcomes"][-1]["events"]), 3)

    def test_original_historical_capture_cannot_become_a_live_request(self):
        s = next(s for s in self.captures if s.retrieval_mode == "HISTORICAL")
        at = s.retrieved_at
        ledger = SamplingRequestStore(self.root / "r.sqlite3", session_date=at.date(),
            baseline=SamplingMembership(frozenset({"DFSC"}), frozenset(), frozenset()), clock=lambda: at)
        ledger.initialize()
        p = NasdaqSamplingProducer(self.root / "p.sqlite3", request_store=ledger,
            settings=HaltProducerSettings("p", ("LUDP", "M"), "regular_close", False), clock=lambda: at)
        p.initialize(); p.record_snapshot(s)
        self.assertEqual(p.snapshot()["outcomes"][0]["status"], "historical_only")
        self.assertFalse(p.deliver_pending()); self.assertFalse(ledger.events())

    def test_changed_original_evidence_is_refused(self):
        manifest = json.loads((EXPERIMENT / "evidence_manifest.json").read_text())
        relative, item = next(iter(manifest["files"].items()))
        folder = self.root / "evidence"; target = folder / relative
        target.parent.mkdir(parents=True); target.write_bytes(b"changed")
        with self.assertRaisesRegex(RuntimeError, "changed"):
            verify_evidence(folder, {"files": {relative: item}})

    def test_manifest_path_escape_is_refused(self):
        with self.assertRaisesRegex(RuntimeError, "escapes"):
            verify_evidence(self.root, {"files": {"../outside.xml": {"size": 0, "sha256": "0" * 64}}})

    def test_invalid_or_unrelated_xml_is_not_an_empty_baseline(self):
        for raw in (b"<html><body/></html>", b"<rss/>", b"not xml"):
            with self.assertRaises(Exception):
                parse_saved(raw, capture_id="bad", retrieved_at=self.captures[0].retrieved_at,
                            mode="CURRENT", provenance={})

    def test_derived_arrival_proof_preserves_original_identity_and_audit_replay(self):
        report = run_proof(self.root)
        self.assertEqual(report["audit"], "PASS")
        self.assertTrue(report["synthetic_policy_clock"])
        self.assertEqual(report["table_counts"]["quote_acquisition"], 0)
        states = report["simulation_request_states"]
        self.assertEqual(len(states), 8)
        self.assertEqual(states[-1]["retained"]["hot"], ["AEHL"])
        metadata = states[-1]["active_requests"][0]["metadata"]
        self.assertEqual(metadata["halt_event"]["original_record"]["halt_date"], "08/14/2026")
        self.assertEqual(metadata["capture_retrieved_at_utc"], "2026-08-14T21:01:37.278583+00:00")
        self.assertTrue(metadata["replay_mode"])

    def test_channel_failure_preserves_input_and_rolls_back_complete_revision(self):
        fixture = simulation_fixture(self.root, self.captures)
        ledger, _, journal, *_ = fixture
        exercise_simulation(fixture)
        with closing(sqlite3.connect(journal.database_path)) as conn:
            with conn:
                conn.execute("CREATE TRIGGER reject_hot BEFORE INSERT ON sampling_channel_revision WHEN NEW.channel='hot' AND NEW.revision=1 BEGIN SELECT RAISE(ABORT,'injected failure'); END")
        with self.assertRaises(sqlite3.IntegrityError): publish_states(ledger, journal)
        self.assertEqual(len(ledger.events()), 7)
        self.assertEqual(len(journal.membership_revisions_in_effective_order()), 1)
        with closing(sqlite3.connect(journal.database_path)) as conn:
            with conn: conn.execute("DROP TRIGGER reject_hot")
        publish_states(ledger, journal)
        self.assertEqual(len(journal.membership_revisions_in_effective_order()), 8)

    def test_journal_prefix_mismatch_is_refused_without_extending_history(self):
        fixture = simulation_fixture(self.root, self.captures)
        ledger, _, journal, clock, *_ = fixture
        exercise_simulation(fixture)
        journal.record_membership_revision(SamplingHierarchyRevision(session_date=ledger.session_date,
            revision=1, effective_at=clock.start.replace(second=1), uni_symbols=tuple(ledger.baseline.uni),
            focus_symbols=tuple(ledger.baseline.focus), hot_symbols=(), source="conflicting", reason="valid but wrong prefix"))
        with self.assertRaisesRegex(RuntimeError, "prefix"):
            publish_states(ledger, journal)
        self.assertEqual(len(journal.membership_revisions_in_effective_order()), 2)


if __name__ == "__main__":
    unittest.main()
