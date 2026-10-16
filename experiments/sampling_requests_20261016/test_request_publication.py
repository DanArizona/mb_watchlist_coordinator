import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import timedelta
from pathlib import Path

from mb_market_data.quote_journal_audit import audit_quote_journal
from mb_market_data.quote_observation_store import RecordResult
from mb_watchlist_coordinator.sampling_request_store import SamplingRequestStore
from mb_watchlist_coordinator.sampling_projection import SamplingMembership
from request_proof import initialize_fixture, publish_recorded_states, run_proof, synthetic_request


class RequestPublicationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name)

    def test_full_sequence_and_both_replay_paths(self):
        report = run_proof(self.folder)
        self.assertEqual(report["result"], "PASS")
        self.assertEqual(report["request_checkpoints"][-1]["demotion_eligible"]["hot"], ["MSFT"])

    def test_unpublished_request_survives_restart(self):
        ledger, journal = initialize_fixture(self.folder)
        ledger.submit_request(synthetic_request(ledger, "manual", "m1"), actor_id="manual")
        reopened = SamplingRequestStore(ledger.path, session_date=ledger.session_date, baseline=ledger.baseline)
        self.assertEqual(publish_recorded_states(reopened, journal), (RecordResult.INSERTED,))
        self.assertEqual(publish_recorded_states(reopened, journal), (RecordResult.ALREADY_PRESENT,))

    def test_journal_failure_keeps_request_and_rolls_back_entire_revision(self):
        ledger, journal = initialize_fixture(self.folder)
        ledger.submit_request(synthetic_request(ledger, "manual", "m1"), actor_id="manual")
        with closing(sqlite3.connect(journal.database_path)) as connection:
            connection.executescript("""CREATE TRIGGER fail_hot BEFORE INSERT ON sampling_channel_revision
                WHEN NEW.revision=1 AND NEW.channel='hot'
                BEGIN SELECT RAISE(ABORT, 'injected publication failure'); END;""")
        with self.assertRaises(sqlite3.IntegrityError):
            publish_recorded_states(ledger, journal)
        audit = audit_quote_journal(journal.database_path)
        self.assertTrue(audit.passed, audit.findings)
        self.assertEqual(audit.table_counts["sampling_membership_revision"], 1)
        self.assertEqual(len(ledger.events()), 1)
        with closing(sqlite3.connect(journal.database_path)) as connection:
            connection.execute("DROP TRIGGER fail_hot")
        self.assertEqual(publish_recorded_states(ledger, journal), (RecordResult.INSERTED,))

    def test_already_published_retry_keeps_publication_receipt(self):
        ledger, journal = initialize_fixture(self.folder)
        ledger.submit_request(synthetic_request(ledger, "manual", "m1"), actor_id="manual")
        publish_recorded_states(ledger, journal)
        first = journal.membership_revisions_in_effective_order()[1]
        publish_recorded_states(ledger, journal)
        self.assertEqual(journal.membership_revisions_in_effective_order()[1], first)

    def test_published_history_ahead_of_ledger_is_refused(self):
        ledger, journal = initialize_fixture(self.folder)
        ledger.submit_request(synthetic_request(ledger, "manual", "m1"), actor_id="manual")
        publish_recorded_states(ledger, journal)
        with closing(sqlite3.connect(ledger.path)) as connection, connection:
            connection.execute("DELETE FROM request_event")
        with self.assertRaisesRegex(RuntimeError, "ahead"):
            publish_recorded_states(ledger, journal)

    def test_changed_receipt_is_refused_before_publication(self):
        ledger, journal = initialize_fixture(self.folder)
        ledger.submit_request(synthetic_request(ledger, "manual", "m1"), actor_id="manual")
        with closing(sqlite3.connect(ledger.path)) as connection, connection:
            connection.execute("UPDATE request_event SET actor_id='forged'")
        with self.assertRaises(ValueError):
            publish_recorded_states(ledger, journal)
        self.assertEqual(len(journal.membership_revisions_in_effective_order()), 1)

    def test_request_expiring_before_scheduled_effect_is_refused(self):
        ledger, journal = initialize_fixture(self.folder)
        request = synthetic_request(ledger, "manual", "m1")
        from dataclasses import replace
        request = replace(request, expires_at=request.created_at + timedelta(seconds=60))
        ledger.submit_request(request, actor_id="manual")
        with self.assertRaisesRegex(RuntimeError, "expires"):
            publish_recorded_states(ledger, journal)

    def test_wrong_baseline_is_refused(self):
        ledger, journal = initialize_fixture(self.folder)
        wrong = SamplingRequestStore(self.folder / "different.sqlite3", session_date=ledger.session_date,
            baseline=SamplingMembership(ledger.baseline.uni, frozenset({"AAPL"}), frozenset()))
        wrong.initialize()
        with self.assertRaisesRegex(RuntimeError, "baselines differ"):
            publish_recorded_states(wrong, journal)
