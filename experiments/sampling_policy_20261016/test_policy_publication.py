import sqlite3
import tempfile
import unittest
from contextlib import closing
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

from mb_market_data.quote_journal_audit import audit_quote_journal
from mb_market_data.quote_observation_store import QuoteObservationStore, RecordResult
from mb_watchlist_coordinator.models import IntentType, ProducerIntent
from mb_watchlist_coordinator.sampling_request_store import SamplingRequestStore
from policy_proof import PROOF_POLICY, initialize_fixture, publish_policy_states, run_proof


class PolicyPublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)

    def request(self, ledger, clock):
        request = ProducerIntent("m1", "manual", IntentType.ENSURE_PRESENT, frozenset({"MSFT"}), clock(),
            metadata={"sampling_channel": "hot", "session_date": ledger.session_date.isoformat(), "synthetic_policy_clock": True})
        ledger.submit_request(request, actor_id="manual")

    def test_full_policy_trace_replays_every_published_checkpoint(self):
        report = run_proof(self.folder)
        self.assertEqual(report["result"], "PASS")
        self.assertEqual(len(report["trace"]), 21)
        self.assertEqual(report["table_counts"]["sampling_membership_revision"], 22)
        self.assertTrue(report["synthetic_policy_clock"])
        self.assertEqual(report["request_checkpoints"][-1]["retained"]["hot"], [])

    def test_pending_policy_state_survives_restart_and_commit_retry(self):
        ledger, journal, clock = initialize_fixture(self.folder)
        self.request(ledger, clock)
        clock.at(1)
        ledger.restrict_symbol("r1", symbol="MSFT", max_group="focus", actor_id="proof-super-user")
        reopened = SamplingRequestStore(ledger.path, session_date=ledger.session_date, baseline=ledger.baseline,
            policy=PROOF_POLICY, clock=clock)
        self.assertEqual(publish_policy_states(reopened, journal), (RecordResult.INSERTED, RecordResult.INSERTED))
        original = journal.membership_revisions_in_effective_order()
        self.assertEqual(publish_policy_states(reopened, journal), (RecordResult.ALREADY_PRESENT, RecordResult.ALREADY_PRESENT))
        self.assertEqual(journal.membership_revisions_in_effective_order(), original)

    def test_failed_channel_insert_rolls_back_without_losing_policy_input(self):
        ledger, journal, clock = initialize_fixture(self.folder)
        self.request(ledger, clock)
        with closing(sqlite3.connect(journal.database_path)) as connection:
            connection.executescript("""CREATE TRIGGER fail_hot BEFORE INSERT ON sampling_channel_revision
                WHEN NEW.revision=1 AND NEW.channel='hot'
                BEGIN SELECT RAISE(ABORT, 'injected policy publication failure'); END;""")
        with self.assertRaises(sqlite3.IntegrityError):
            publish_policy_states(ledger, journal)
        audit = audit_quote_journal(journal.database_path)
        self.assertTrue(audit.passed, audit.findings)
        self.assertEqual(audit.table_counts["sampling_membership_revision"], 1)
        self.assertEqual(len(ledger.events()), 1)
        with closing(sqlite3.connect(journal.database_path)) as connection:
            connection.execute("DROP TRIGGER fail_hot")
        self.assertEqual(publish_policy_states(ledger, journal), (RecordResult.INSERTED,))

    def test_different_policy_cannot_extend_the_same_journal(self):
        ledger, journal, clock = initialize_fixture(self.folder)
        other = SamplingRequestStore(self.folder / "other.sqlite3", session_date=ledger.session_date,
            baseline=ledger.baseline, clock=clock, policy=replace(PROOF_POLICY, demotion_grace_seconds=1))
        other.initialize()
        with self.assertRaisesRegex(RuntimeError, "baseline differ"):
            publish_policy_states(other, journal)

    def test_published_history_ahead_of_request_log_is_refused(self):
        ledger, journal, clock = initialize_fixture(self.folder)
        self.request(ledger, clock); publish_policy_states(ledger, journal)
        with closing(sqlite3.connect(ledger.path)) as connection, connection:
            connection.execute("DELETE FROM request_event")
        with self.assertRaisesRegex(RuntimeError, "ahead"):
            publish_policy_states(ledger, journal)

    def test_rejected_cap_is_retained_as_evidence_without_applying_cap(self):
        ledger, journal, clock = initialize_fixture(self.folder)
        self.request(ledger, clock)
        ledger.restrict_symbol("denied", symbol="MSFT", max_group="uni", actor_id="manual")
        publish_policy_states(ledger, journal)
        latest = journal.membership_revisions_in_effective_order()[-1]
        self.assertEqual(latest.hot_symbols, ("MSFT",))
        self.assertFalse(latest.metadata["input_event"]["accepted"])
        self.assertTrue(latest.metadata["synthetic_policy_clock"])

    def test_cap_expiring_before_effective_time_is_not_published(self):
        ledger, journal, clock = initialize_fixture(self.folder)
        self.request(ledger, clock)
        ledger.restrict_symbol("too-short", symbol="MSFT", max_group="uni", actor_id="proof-super-user",
            expires_at=clock() + timedelta(microseconds=1))
        with self.assertRaisesRegex(RuntimeError, "expires"):
            publish_policy_states(ledger, journal)
        self.assertEqual(len(journal.membership_revisions_in_effective_order()), 1)

    def test_conflicting_valid_published_prefix_is_preserved(self):
        ledger, journal, clock = initialize_fixture(self.folder)
        self.request(ledger, clock); publish_policy_states(ledger, journal)
        revisions = journal.membership_revisions_in_effective_order()
        other = QuoteObservationStore(self.folder / "conflict.sqlite3", session_date=ledger.session_date, schema_version=2)
        other.initialize()
        other.record_membership_revision(replace(revisions[0], published_at=None))
        other.record_membership_revision(replace(revisions[1], published_at=None, reason="different publisher content"))
        with self.assertRaisesRegex(RuntimeError, "prefix differs"):
            publish_policy_states(ledger, other)
        self.assertEqual(other.membership_revisions_in_effective_order()[1].reason, "different publisher content")
