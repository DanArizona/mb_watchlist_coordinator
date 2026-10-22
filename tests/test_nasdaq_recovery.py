from __future__ import annotations

from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date, datetime, timedelta
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from zoneinfo import ZoneInfo

from mb_watchlist_coordinator.nasdaq_recovery import NasdaqRecoveryReceipts, RecoveryQuery, RecoverySettings
from mb_watchlist_coordinator.nasdaq_sampling import HaltSnapshot, HaltProducerSettings, NasdaqSamplingProducer
from mb_watchlist_coordinator.sampling_policy import SamplingPolicy
from mb_watchlist_coordinator.sampling_projection import SamplingMembership
from mb_watchlist_coordinator.sampling_request_store import SamplingRequestStore
from mb_watchlist_coordinator.sampling_requests import canonical, digest, plain

DAY = date(2026, 10, 22)
AT = datetime(2026, 10, 22, 12, 0, tzinfo=ZoneInfo('America/New_York'))


class RecoveryReceiptsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.now = AT
        self.requests = SamplingRequestStore(self.root / 'requests.sqlite3', session_date=DAY,
            baseline=SamplingMembership(frozenset({'MSFT', 'SPY'}), frozenset({'SPY'}), frozenset()),
            policy=SamplingPolicy('admin', 2, 4, 'immediate_cap'), clock=lambda: self.now)
        self.requests.initialize()
        self.query = RecoveryQuery(DAY, DAY)
        self.settings = RecoverySettings(DAY, 'late_start', (self.query,), False)
        self.store = self.open()
        self.store.initialize(create=True)

    def open(self, **kwargs):
        return NasdaqRecoveryReceipts(self.root / 'recovery.sqlite3', request_store=self.requests,
            settings=kwargs.get('settings', self.settings), clock=lambda: self.now)

    def row(self, *, seconds=0, reason='M', symbol='MSFT', day=DAY, **extras):
        at = AT.replace(hour=10) + timedelta(seconds=seconds)
        return {'symbol': symbol, 'halt_date': day.strftime('%m/%d/%Y'),
            'halt_time': at.strftime('%H:%M:%S.%f'), 'reason_code': reason, **extras}

    def capture(self, cid='c1', rows=None, **kwargs):
        rows = rows if rows is not None else [self.row()]
        return HaltSnapshot(cid, kwargs.pop('retrieved_at', self.now), kwargs.pop('mode', 'HISTORICAL'),
            digest(rows), tuple(rows), {'synthetic_fixture': True, **kwargs})

    def test_noon_recovery_retains_halt_and_receipt_times_without_requesting(self):
        self.store.record(self.query, self.capture(rows=[self.row(resumption_date='10/22/2026',
            resumption_trade_time='10:05:00')]))
        snapshot = self.store.snapshot()
        fact = snapshot['candidates'][0]
        self.assertEqual(fact['decision'], 'eligible_for_normal_admission_review')
        self.assertEqual(datetime.fromisoformat(fact['halt_at_utc']).astimezone(AT.tzinfo).hour, 10)
        self.assertEqual(datetime.fromisoformat(fact['first_recovered_at_utc']), AT)
        self.assertEqual(fact['observations'][0]['row']['resumption_trade_time'], '10:05:00')
        self.assertEqual(snapshot['stage'], 'RECEIPTS_ONLY')
        self.assertEqual(snapshot['delivery'], 'NOT_IMPLEMENTED')
        self.assertFalse(self.requests.events())

    def test_exact_retry_reuses_original_receipt_and_reopen_replays(self):
        feed = self.capture()
        receipt, inserted = self.store.record(self.query, feed)
        self.assertTrue(inserted)
        self.now += timedelta(minutes=3)
        again, inserted = self.open().record(self.query, feed)
        self.assertFalse(inserted)
        self.assertEqual(receipt, again)
        self.assertEqual(self.store.snapshot(), self.open().initialize())

    def test_capture_id_conflict_refused_without_append(self):
        self.store.record(self.query, self.capture())
        with self.assertRaisesRegex(ValueError, 'different content'):
            self.store.record(self.query, self.capture(rows=[self.row(symbol='SPY')]))
        self.assertEqual(len(self.store.snapshot()['receipts']), 1)

    def test_repeat_and_resumption_update_do_not_create_distinct_halts(self):
        self.store.record(self.query, self.capture())
        self.now += timedelta(minutes=1)
        self.store.record(self.query, self.capture('c2', [self.row(reason='T3', resumption_trade_time='10:05:00')]))
        state = self.store.snapshot()
        self.assertEqual(len(state['candidates']), 1)
        self.assertEqual(len(state['candidates'][0]['observations']), 2)
        self.assertEqual(state['candidates'][0]['first_reason_code'], 'M')

    def test_two_halts_same_symbol_remain_distinct(self):
        self.store.record(self.query, self.capture(rows=[self.row(), self.row(seconds=600)]))
        facts = self.store.snapshot()['candidates']
        self.assertEqual(len(facts), 2)
        self.assertNotEqual(facts[0]['event_id'], facts[1]['event_id'])

    def test_original_reason_not_inferred_from_later_resumption_or_reclassification(self):
        self.store.record(self.query, self.capture(rows=[self.row(reason='T3')]))
        self.now += timedelta(minutes=1)
        self.store.record(self.query, self.capture('c2', [self.row(reason='M')]))
        self.assertEqual(self.store.snapshot()['candidates'][0]['decision'], 'unresolved_original_reason')

    def test_conflicting_rows_refused_atomically(self):
        with self.assertRaisesRegex(ValueError, 'Conflicting rows'):
            self.store.record(self.query, self.capture(rows=[self.row(), self.row(reason='T3')]))
        self.assertFalse(self.store.snapshot()['receipts'])

    def test_previous_day_is_context_and_unknown_carryover_stays_visible(self):
        self.store.record(self.query, self.capture(rows=[self.row(day=DAY-timedelta(days=1))]))
        state = self.store.snapshot()
        self.assertEqual(state['candidates'][0]['decision'], 'context_only_other_session_or_off_hours')
        self.assertIn('older_unknown_carryovers_not_proven_complete', state['known_gaps'])

    def test_query_completion_is_distinct_from_full_trace_and_candidate_admission(self):
        previous = RecoveryQuery(DAY-timedelta(days=1), None)
        self.settings = replace(self.settings, queries=(self.query, previous))
        store = NasdaqRecoveryReceipts(self.root / 'scope.sqlite3', request_store=self.requests,
            settings=self.settings, clock=lambda: self.now)
        store.initialize(create=True)
        store.record(self.query, self.capture(rows=[]))
        self.assertEqual(store.snapshot()['pending_query_ids'], (previous.query_id,))
        store.record(previous, self.capture('c2', []))
        state = store.snapshot()
        self.assertEqual(state['query_scope'], 'COMPLETE_WITH_TRACE_GAPS')
        self.assertEqual(state['status'], 'RECOVERING')
        self.assertFalse(state['candidates'])

    def test_undeclared_query_and_live_mode_do_not_append(self):
        with self.assertRaises(ValueError):
            self.store.record(RecoveryQuery(DAY, None), self.capture())
        with self.assertRaises(ValueError):
            self.store.record(self.query, self.capture(mode='CURRENT'))
        self.assertFalse(self.store.snapshot()['receipts'])

    def test_future_halt_capture_and_backwards_receipt_refused(self):
        with self.assertRaises(ValueError):
            self.store.record(self.query, self.capture(rows=[self.row(seconds=3*3600)]))
        with self.assertRaises(ValueError):
            self.store.record(self.query, self.capture(retrieved_at=AT+timedelta(seconds=1)))
        self.store.record(self.query, self.capture())
        self.now -= timedelta(seconds=1)
        with self.assertRaises(ValueError):
            self.store.record(self.query, self.capture('old'))

    def test_close_and_cross_session_receipts_refused(self):
        self.now = AT.replace(hour=16)
        with self.assertRaises(ValueError):
            self.store.record(self.query, self.capture())
        self.now = AT + timedelta(days=1)
        with self.assertRaises(ValueError):
            self.store.record(self.query, self.capture())

    def test_lost_file_reopen_does_not_create_replacement(self):
        self.store.path.unlink()
        with self.assertRaises(FileNotFoundError):
            self.open().initialize()
        self.assertFalse(self.store.path.exists())
        with self.assertRaises(sqlite3.OperationalError):
            self.store.record(self.query, self.capture())
        self.assertFalse(self.store.path.exists())

    def test_changed_config_existing_file_and_corruption_refused(self):
        with self.assertRaises(FileExistsError):
            self.store.initialize(create=True)
        with self.assertRaises(ValueError):
            self.open(settings=replace(self.settings, mode='resume_saved')).initialize()
        self.store.record(self.query, self.capture())
        with closing(sqlite3.connect(self.store.path)) as c, c:
            r = json.loads(c.execute('SELECT payload FROM recovery_receipt').fetchone()[0])
            r['snapshot']['records'][0]['symbol'] = 'SPY'
            c.execute('UPDATE recovery_receipt SET payload=?', (canonical(r),))
        with self.assertRaises(ValueError):
            self.open().snapshot()

    def test_existing_live_producer_keeps_baseline_and_historical_audit_only(self):
        live = NasdaqSamplingProducer(self.root / 'live.sqlite3', request_store=self.requests,
            settings=HaltProducerSettings('nasdaq', ('LUDP', 'M'), 'regular_close', False), clock=lambda: self.now)
        live.initialize()
        live.record_snapshot(self.capture('history'))
        live.record_snapshot(self.capture('live', mode='CURRENT'))
        self.assertFalse(live.snapshot()['commands'])
        self.assertEqual(live.snapshot()['outcomes'][0]['status'], 'historical_only')
        self.assertEqual(live.snapshot()['outcomes'][1]['status'], 'initial_baseline')

    def test_invalid_manifest_settings_are_refused(self):
        for mode, queries in [('implicit', (self.query,)), ('late_start', ()),
                              ('late_start', (self.query, self.query))]:
            with self.assertRaises(ValueError):
                RecoverySettings(DAY, mode, queries, False)
        with self.assertRaises(ValueError):
            RecoveryQuery(datetime(2026, 10, 22), None)
        with self.assertRaises(ValueError):
            NasdaqRecoveryReceipts(self.requests.path, request_store=self.requests,
                settings=self.settings, clock=lambda: self.now)

    def test_concurrent_capture_retry_has_one_committed_receipt(self):
        feed = self.capture()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.open().record(self.query, feed), range(2)))
        self.assertEqual(sum(inserted for _, inserted in results), 1)
        self.assertEqual(len(self.store.snapshot()['receipts']), 1)

    def test_request_identity_failure_blocks_new_recovery_receipt(self):
        with closing(sqlite3.connect(self.requests.path)) as c, c:
            c.execute("UPDATE request_identity SET payload='{}'")
        with self.assertRaises(ValueError):
            self.store.record(self.query, self.capture())
        with closing(sqlite3.connect(self.store.path)) as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM recovery_receipt').fetchone()[0], 0)


if __name__ == '__main__':
    unittest.main()
