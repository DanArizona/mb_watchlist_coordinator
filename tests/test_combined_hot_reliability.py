"""Mixed Nasdaq/manual admission through the corrected native Hot collector.

Synthetic source records and quote responses; real request/publication journals,
shared broker-identity accounting, native period collector and replay. This is
not a live Nasdaq/Schwab test or sustained-provider-capacity qualification.
"""
from contextlib import closing
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch

from daily_manual_fixture import CombinedFixture
from mb_market_data.quote_journal_audit import audit_quote_journal
from mb_market_data.quote_journal_replay import QuoteJournalReplayReader
from mb_watchlist_coordinator.daily_collector import DailyCollectorSettings
from mb_watchlist_coordinator.daily_epoch_collector import make_daily_collector
from mb_watchlist_coordinator.operating_plan import BROKER_MANUAL_PROFILE
from mb_watchlist_coordinator.sampling_requests import plain
from test_daily_multisymbol import full_quotes
from test_integrated_identity import Response


# Full test selectors remain in console/result.json; only folder names are short.
PROOF_CASE_DIRS = {
    'test_mixed_admission_native_quotes_audit_and_replay': 'ok',
    'test_mixed_deadline_restart_retains_gap_and_never_retries_slot': 'gap',
}


class CombinedHotReliabilityTests(unittest.TestCase):
    """Requalify the composition, not just its old separate components."""

    def setUp(self):
        proof = os.environ.get('MB_COMBINED_HOT_PROOF_ROOT')
        root = Path(proof) / PROOF_CASE_DIRS[self._testMethodName] if proof else None
        self.f = CombinedFixture(profile=BROKER_MANUAL_PROFILE, root=root)
        self.addCleanup(self.f.close)
        self.c, self.s = self.f.case, self.f.session
        self.c.now = self.c.at.replace(hour=15, minute=59, second=40)
        self.manual_id = self.f.manual('X000')
        self.f.queue_nasdaq(['X001'], capture='mixed-corrected-native')
        # One shared identity authorization per pump; retain original spacing.
        self.f.pump()
        self.f.advance(2)
        self.f.pump()
        self.f.publish()
        self.assertEqual({tuple(s) for s in self.c.calls}, {('X000',), ('X001',)})
        self.assertEqual(len(self.c.calls), 2)
        self.assertEqual(self.f.feedback(self.manual_id)['status'], 'EFFECTIVE')
        self.assertEqual(
            {r['producer_id'] for r in self.s.requests.states()[-1].active_requests},
            {'operator:masterbot', 'nasdaq-shared-daily'},
        )
        self.assert_nested({'X000', 'X001'})
        start = self.c.at.replace(hour=15, minute=59, second=50)
        self.stop = start.replace(hour=16, minute=0, second=0)
        self.settings = DailyCollectorSettings(
            str(self.c.journal), plain(self.s.service.identity),
            plain(self.s.binding), plain(self.s.claim),
            start.isoformat(), self.stop.isoformat(), 100, 40,
        )
        self.quote_calls = []
        case = self

        class Client:
            def quotes(self, symbols, *, fields):
                case.quote_calls.append(tuple(symbols))
                return Response(symbols[0], body=full_quotes(symbols, case.c.now))

            def close(self):
                pass

        self.factory = Client
        self.collector = self.make_collector()
        self.addCleanup(lambda: self.collector.close())
        self.collector.prepare(create=True)

    def make_collector(self):
        return make_daily_collector(
            self.settings, publication_session=self.s,
            client_factory=self.factory, clock=lambda: self.c.now,
            activation_approved=True,
        )

    def assert_nested(self, expected_hot):
        membership = self.c.store.latest_membership_revision_effective_at(self.c.now)
        self.assertEqual(set(membership.hot_symbols), expected_hot)
        self.assertTrue(set(membership.hot_symbols) <= set(membership.focus_symbols)
                        <= set(membership.uni_symbols))

    def tick(self, second):
        self.c.now = self.c.now.replace(second=second, microsecond=0)
        case = self

        class QuoteClock(datetime):
            @classmethod
            def now(cls, tz=None):
                return case.c.now.astimezone(tz or timezone.utc)

        with patch('mb_market_data.schwab_quotes.datetime', QuoteClock):
            return self.collector.tick()

    def check_final(self, *, expected_quotes, missed_slot=None):
        audit = audit_quote_journal(self.c.journal, audited_at=self.stop)
        hot = next(c for c in audit.channels if c.channel == 'hot')
        self.assertEqual(hot.expected_slot_count, 4)
        self.assertEqual(hot.acquisition_count, expected_quotes)
        self.assertEqual(hot.observation_count, expected_quotes * 2)
        self.assertEqual(hot.skipped_slot_count, 0)
        self.assertEqual(hot.status_counts, {'quote': expected_quotes * 2})
        self.assertEqual(hot.row_count_mismatch_ids, ())
        expected_missing = [] if missed_slot is None else [missed_slot]
        self.assertEqual([str(s) for s in hot.missing_slot_ids], expected_missing)
        self.assertEqual(audit.passed, missed_slot is None)
        first = tuple(QuoteJournalReplayReader(self.c.journal).events())
        self.assertEqual(first, tuple(QuoteJournalReplayReader(self.c.journal).events()))
        with closing(sqlite3.connect(self.c.journal.as_uri() + '?mode=ro', uri=True)) as connection:
            self.assertEqual(connection.execute(
                'SELECT count(*) FROM quote_observation WHERE status="request_error"'
            ).fetchone()[0], 0)
            self.assertEqual(connection.execute(
                'SELECT count(*) FROM quote_acquisition WHERE channel="hot" '
                'AND requested_symbol_count=2'
            ).fetchone()[0], expected_quotes)
        self.assertEqual(len(self.quote_calls), expected_quotes)
        self.assertTrue(all(set(batch) == {'X000', 'X001'} for batch in self.quote_calls))
        self.assertEqual(plain(self.s.gate.snapshot())['identity_gate']['quote_permits'], 2)
        self.assert_nested({'X000', 'X001'})
        proof = {
            'test': self._testMethodName,
            'test_result': 'PASS',
            'manual_symbol': 'X000', 'nasdaq_symbol': 'X001',
            'both_outside_opening_uni': True,
            'shared_identity_permits': 2,
            'native_hot_acquisitions': hot.acquisition_count,
            'native_quote_observations': hot.observation_count,
            'native_audit_verdict': 'PASS' if audit.passed else 'FAIL',
            'missing_slot_ids': expected_missing,
            'replay_event_count': len(first), 'two_fresh_replays_equal': True,
            'no_real_credentials_or_provider_calls': True,
            'production_access': False, 'full_day_provider_capacity_qualified': False,
            'clock': 'logical fixture clock; not elapsed-time dispatch capacity',
        }
        (self.c.root / 'mixed-reliability-proof.json').write_text(
            json.dumps(proof, indent=2, sort_keys=True) + '\n', encoding='utf-8')

    def test_mixed_admission_native_quotes_audit_and_replay(self):
        for second in (52, 54, 56, 58):
            outcome = self.tick(second)
            self.assertEqual(outcome['status'], 'acquired', outcome)
        self.check_final(expected_quotes=4)

    def test_mixed_deadline_restart_retains_gap_and_never_retries_slot(self):
        self.assertEqual(self.tick(52)['status'], 'acquired')
        # Patch the ACTIVE period collector, not the facade: this is the actual
        # final local validation boundary preceding its provider invocation.
        active = self.collector.active
        validate = active.validate_publication
        crossed = [False]

        def expire_after_validation(dispatch, *, verified_state=None):
            result = validate(dispatch, verified_state=verified_state)
            if dispatch is not None and not crossed[0]:
                crossed[0] = True
                self.c.now += timedelta(milliseconds=751)
            return result

        with patch.object(active, 'validate_publication', side_effect=expire_after_validation):
            outcome = self.tick(54)
        self.assertTrue(crossed[0], 'Fault must actually cross the final provider boundary')
        self.assertEqual(outcome['status'], 'missed', outcome)
        self.assertEqual(outcome['gate'], 'final_pre_provider_deadline')
        self.assertFalse(active.refused_call)
        self.assertEqual(len(self.quote_calls), 1)
        missed_slot = outcome['slot_id']
        before = self.collector.poller.snapshot()
        self.assertEqual(before['finished'][missed_slot]['kind'], 'abandoned')
        before_dispatches = sum(e['kind'] == 'dispatch' and bool(e['symbols'])
                                for e in before['events'])
        self.assertEqual(before_dispatches, 2)  # one successful; one charged, abandoned
        self.collector.close()
        self.c.now = self.c.now.replace(second=55, microsecond=0)
        self.collector = self.make_collector()
        self.collector.prepare()
        reopened = self.collector.poller.snapshot()
        self.assertEqual(reopened['finished'][missed_slot]['kind'], 'abandoned')
        self.assertIsNone(reopened['pending'])
        self.assertEqual(sum(e['kind'] == 'dispatch' and bool(e['symbols'])
                             for e in reopened['events']), before_dispatches)
        self.assertEqual(self.collector.next.scheduled_at.second, 56)
        for second in (56, 58):
            self.assertEqual(self.tick(second)['status'], 'acquired')
        final = self.collector.poller.snapshot()
        self.assertEqual(sum(e['kind'] == 'abandoned' and e['slot_id'] == missed_slot
                             for e in final['events']), 1)
        self.check_final(expected_quotes=3, missed_slot=missed_slot)
