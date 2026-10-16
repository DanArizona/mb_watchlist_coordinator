from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

from mb_market_data.quote_journal_audit import audit_quote_journal
from mb_market_data.quote_observation_store import DuplicateRecordError, QuoteObservationStore, RecordResult
from mb_watchlist_coordinator.models import IntentType
from mb_watchlist_coordinator.sampling_projection import SamplingMembership, project_promotion
from promotion_proof import fixture, plain, run_proof
from sampling_journal_bridge import promotion_proposal


class PromotionTests(unittest.TestCase):
    def setUp(self):
        self.baseline, self.request, self.now = fixture()
        self.membership = SamplingMembership(frozenset(self.baseline.uni_symbols),
                                            frozenset(self.baseline.focus_symbols), frozenset())

    def project(self, request=None, membership=None, at=None):
        return project_promotion(membership or self.membership, request or self.request,
                                 at=at or self.now)

    def test_hot_adds_focus_and_preserves_uni_and_baseline(self):
        result = self.project()
        self.assertEqual(result.membership.hot, {"MSFT"})
        self.assertEqual(result.membership.focus, {"MSFT", "SPY"})
        self.assertEqual(result.membership.uni, self.membership.uni)
        self.assertEqual(self.membership.focus, {"SPY"})
        self.assertEqual(self.membership.hot, set())
        self.assertEqual(result.producer_id, self.request.producer_id)

    def test_focus_promotion_keeps_existing_hot(self):
        baseline = SamplingMembership(self.membership.uni, frozenset({"SPY"}), frozenset({"SPY"}))
        request = replace(self.request, metadata={**self.request.metadata, "sampling_channel": "focus"})
        result = self.project(request, baseline)
        self.assertEqual(result.membership.focus, {"SPY", "MSFT"})
        self.assertEqual(result.membership.hot, {"SPY"})

    def test_outside_uni_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "outside"):
            self.project(replace(self.request, symbols=frozenset({"NVDA"})))

    def test_demotions_force_and_base_requests_are_rejected(self):
        for kind in IntentType:
            if kind != IntentType.ENSURE_PRESENT:
                with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, "promotions only"):
                    self.project(replace(self.request, intent_type=kind))

    def test_future_or_expired_request_is_rejected(self):
        for change in ({"created_at": self.now + timedelta(seconds=1)},
                       {"effective_from": self.now + timedelta(seconds=1)},
                       {"expires_at": self.now}):
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, "not active"):
                self.project(replace(self.request, **change))

    def test_naive_times_are_rejected(self):
        for name in ("created_at", "effective_from", "expires_at"):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "timezone-aware"):
                self.project(replace(self.request, **{name: self.now.replace(tzinfo=None)}))
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            self.project(at=self.now.replace(tzinfo=None))

    def test_invalid_channels_and_supersession_are_rejected(self):
        for target in (None, "uni", "HOT", "unknown"):
            with self.subTest(target=target), self.assertRaisesRegex(ValueError, "sampling_channel"):
                self.project(replace(self.request, metadata={"sampling_channel": target}))
        with self.assertRaisesRegex(ValueError, "Supersession"):
            self.project(replace(self.request, supersession_key="unresolved-source-group"))

    def test_invalid_membership_and_symbols_are_rejected(self):
        for uni, focus, hot in ((set(), set(), set()), ({"SPY"}, {"MSFT"}, set()),
                                ({"SPY"}, set(), {"SPY"})):
            with self.subTest(uni=uni, focus=focus, hot=hot), self.assertRaises(ValueError):
                SamplingMembership(uni, focus, hot)
        for symbols in (frozenset(), frozenset({"msft"}), frozenset({"MSFT,SPY"})):
            with self.subTest(symbols=symbols), self.assertRaises(ValueError):
                self.project(replace(self.request, symbols=symbols))


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.baseline, self.request, self.now = fixture()
        self.effective = self.baseline.effective_at + timedelta(seconds=1)

    def proposal(self, request=None, **kwargs):
        return promotion_proposal(self.baseline, request or self.request,
                                  decided_at=kwargs.get("decided_at", self.now),
                                  effective_at=kwargs.get("effective_at", self.effective))

    def test_complete_proposal_retains_immutable_provenance(self):
        request = replace(self.request, metadata={**self.request.metadata, "nested": {"evidence": [1]}})
        proposal = self.proposal(request)
        expected = plain(proposal.metadata)
        request.metadata["nested"]["evidence"].append(2)
        self.assertEqual(plain(proposal.metadata), expected)
        self.assertEqual(proposal.revision, 1)
        self.assertIsNone(proposal.published_at)
        self.assertEqual(proposal.reason, request.reason)
        self.assertEqual(proposal.metadata["request"]["source_event_id"], request.source_event_id)
        self.assertEqual(proposal.metadata["baseline_content_sha256"], self.baseline.content_sha256)
        self.assertEqual(proposal.metadata["decided_at_utc"], self.now.isoformat())

    def test_session_and_effective_time_are_guarded(self):
        with self.assertRaisesRegex(ValueError, "session_date"):
            self.proposal(replace(self.request, metadata={**self.request.metadata, "session_date": "2000-01-01"}))
        for effective in (self.baseline.effective_at, self.now - timedelta(seconds=1),
                          self.effective + timedelta(days=1)):
            with self.subTest(effective=effective), self.assertRaises(ValueError):
                self.proposal(effective_at=effective)

    def test_expiry_before_scheduled_effect_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "expire"):
            self.proposal(replace(self.request, expires_at=self.effective))

    def test_decision_cannot_precede_its_committed_baseline(self):
        committed = replace(self.baseline, published_at=self.now + timedelta(seconds=1))
        with self.assertRaisesRegex(ValueError, "precede publication"):
            promotion_proposal(committed, self.request, decided_at=self.now, effective_at=self.effective)

    def test_nonfinite_request_evidence_is_rejected(self):
        with self.assertRaises(ValueError):
            self.proposal(replace(self.request, metadata={**self.request.metadata, "value": float("nan")}))

    def test_retry_and_conflict_preserve_complete_revision(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "isolated.sqlite3"
            store = QuoteObservationStore(path, session_date=self.baseline.session_date, schema_version=2)
            store.initialize()
            store.record_membership_revision(self.baseline)
            proposal = self.proposal()
            self.assertEqual(store.record_membership_revision(proposal), RecordResult.INSERTED)
            self.assertEqual(store.record_membership_revision(proposal), RecordResult.ALREADY_PRESENT)
            with self.assertRaises(DuplicateRecordError):
                store.record_membership_revision(replace(proposal, reason="conflicting retry"))
            audit = audit_quote_journal(path)
            self.assertTrue(audit.passed, audit.findings)
            self.assertEqual(audit.table_counts["sampling_membership_revision"], 2)
            self.assertEqual(audit.table_counts["sampling_channel_revision"], 6)
            self.assertEqual(audit.table_counts["sampling_channel_member"], 10)

    def test_channel_write_failure_rolls_back_whole_hierarchy(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "rollback.sqlite3"
            store = QuoteObservationStore(path, session_date=self.baseline.session_date, schema_version=2)
            store.initialize()
            store.record_membership_revision(self.baseline)
            # Connection.__exit__ ends a transaction but leaves the handle
            # open. Own its lifetime explicitly so Windows can remove the DB.
            with closing(sqlite3.connect(path)) as connection:
                connection.executescript("""CREATE TRIGGER fail_hot BEFORE INSERT ON sampling_channel_revision
                    WHEN NEW.revision = 1 AND NEW.channel = 'hot'
                    BEGIN SELECT RAISE(ABORT, 'injected channel failure'); END;""")
            with self.assertRaises(sqlite3.ProgrammingError):
                connection.execute("SELECT 1")
            with self.assertRaises(sqlite3.IntegrityError):
                store.record_membership_revision(self.proposal())
            audit = audit_quote_journal(path)
            self.assertTrue(audit.passed, audit.findings)
            self.assertEqual(audit.table_counts["sampling_membership_revision"], 1)
            self.assertEqual(audit.table_counts["sampling_channel_revision"], 3)
            self.assertEqual(audit.table_counts["sampling_channel_member"], 4)

    def test_real_store_audit_and_two_replays_match_decision(self):
        with tempfile.TemporaryDirectory() as folder:
            report = run_proof(Path(folder))
            self.assertEqual(report["result"], "PASS")
            self.assertEqual(report["checkpoints"][1]["membership"]["hot"], ["MSFT"])
            self.assertEqual(report["table_counts"]["quote_acquisition"], 0)
            saved = json.loads((Path(folder) / "proof_report.json").read_text())
            self.assertEqual(saved, report)


if __name__ == "__main__":
    unittest.main()
