"""Previously checked bytes stay checked; derived cached state is immutable."""
from contextlib import closing
from dataclasses import replace
import json
import sqlite3
import unittest
from unittest.mock import patch

import test_daily_collector as fixture
from mb_market_data.sampling_acquisition import IsolatedSamplingPoller
from mb_market_data.daily_acquisition_reader import read_daily_history
from mb_watchlist_coordinator.sampling_requests import plain


class DailyHistoryReaderTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixture.DailyCollectorTests('test_tail_window_idle_then_three_hot_quotes_native_audit_and_replays')
        self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.fixture.collector.prepare(create=True);self.fixture.tick(52);self.fixture.admit()
        for second in (54,56,58):self.fixture.tick(second)
        self.poller=self.fixture.collector.poller
        self.before=self.poller.snapshot()

    def test_warm_and_cold_reads_equal_the_original_full_reader_and_cannot_be_mutated(self):
        with self.poller.journal._connection() as c:
            reference=IsolatedSamplingPoller._read_checked(self.poller,c)
        self.assertEqual(plain(self.before),plain(reference))
        again=self.poller.snapshot()
        self.assertGreater(self.poller.history_reused_events,0)
        self.assertEqual(plain(again),plain(reference))
        with self.assertRaises(TypeError):again['events'][0]['kind']='changed'
        with self.assertRaises((TypeError,AttributeError)):again['events'].append({})
        self.assertEqual(plain(self.poller.snapshot()),plain(reference))
        self.poller._verified_history=None
        self.assertEqual(plain(self.poller.snapshot()),plain(reference))

    def test_interior_event_change_is_rejected_with_the_same_head_and_row_count(self):
        with closing(sqlite3.connect(self.poller.path)) as c,c:
            raw=c.execute('SELECT payload FROM acquisition_event WHERE sequence=1').fetchone()[0]
            e=json.loads(raw);e['run_id']=e['run_id'][:-1]+('0' if e['run_id'][-1]!='0' else '1')
            from mb_market_data.sampling_acquisition import canonical
            c.execute('UPDATE acquisition_event SET payload=? WHERE sequence=1',(canonical(e),))
        with self.assertRaisesRegex(ValueError,'Previously verified acquisition prefix'):
            self.poller.snapshot()

    def test_old_header_change_is_rejected_before_any_later_provider_call(self):
        before=len(self.fixture.calls)
        with closing(sqlite3.connect(self.fixture.case.journal)) as c,c:
            c.execute('UPDATE quote_acquisition SET request_count=2 WHERE acquisition_id=(SELECT acquisition_id FROM quote_acquisition LIMIT 1)')
        with self.assertRaisesRegex(ValueError,'Previously verified journal'):
            self.poller.snapshot()
        self.assertEqual(len(self.fixture.calls),before)

    def test_old_normalized_quote_change_is_rejected_on_warm_and_cold_reads(self):
        with closing(sqlite3.connect(self.fixture.case.journal)) as c,c:
            c.execute('UPDATE quote_observation SET quote_last_price=999 WHERE acquisition_id=(SELECT acquisition_id FROM quote_acquisition LIMIT 1)')
        with self.assertRaisesRegex(ValueError,'Previously verified journal'):self.poller.snapshot()
        self.poller._verified_history=None
        with self.assertRaisesRegex(ValueError,'observations differ'):self.poller.snapshot()

    def test_extra_observation_for_an_old_acquisition_is_not_hidden_by_prefix_reuse(self):
        with closing(sqlite3.connect(self.fixture.case.journal)) as c,c:
            c.row_factory=sqlite3.Row
            row=dict(c.execute('SELECT * FROM quote_observation LIMIT 1').fetchone())
            row.update(symbol='EXTRA',ordinal=1)
            c.execute('INSERT INTO quote_observation ('+','.join(row)+') VALUES ('+','.join('?' for _ in row)+')',tuple(row.values()))
        with self.assertRaisesRegex(ValueError,'Extra observation'):self.poller.snapshot()

    def test_deleted_old_observation_is_rejected_even_when_ack_and_header_still_exist(self):
        with closing(sqlite3.connect(self.fixture.case.journal)) as c,c:
            c.execute('DELETE FROM quote_observation WHERE acquisition_id=(SELECT acquisition_id FROM quote_acquisition LIMIT 1)')
        with self.assertRaisesRegex(ValueError,'Previously verified journal'):self.poller.snapshot()

    def test_extra_unknown_header_is_not_silently_adopted_from_the_journal(self):
        with closing(sqlite3.connect(self.fixture.case.journal)) as c,c:
            c.row_factory=sqlite3.Row
            row=dict(c.execute('SELECT * FROM quote_acquisition LIMIT 1').fetchone())
            row.update(acquisition_id='foreign-acquisition',slot_id='foreign-slot')
            c.execute('INSERT INTO quote_acquisition ('+','.join(row)+') VALUES ('+','.join('?' for _ in row)+')',tuple(row.values()))
        with self.assertRaisesRegex(ValueError,'outcomes differ'):self.poller.snapshot()

    def test_cached_dispatches_are_rechecked_when_effective_membership_changes(self):
        original=self.poller.journal.membership_revisions_in_effective_order()
        changed=replace(original[-1],hot_symbols=())
        with patch.object(self.poller.journal,'membership_revisions_in_effective_order',return_value=(*original[:-1],changed)):
            with self.poller.journal._connection() as c:
                with self.assertRaisesRegex(ValueError,'dispatch membership differs'):
                    read_daily_history(self.poller,c)

    def test_cold_v2_reader_rejects_formatting_edits_without_a_new_byte_digest(self):
        self.poller._verified_history=None
        with closing(sqlite3.connect(self.poller.path)) as c,c:
            raw=c.execute('SELECT payload FROM acquisition_event WHERE sequence=1').fetchone()[0]
            c.execute('UPDATE acquisition_event SET payload=? WHERE sequence=1',(' '+raw,))
        with self.assertRaisesRegex(ValueError,'outcome chain differs'):self.poller.snapshot()

    def test_provider_callback_cannot_borrow_an_old_persisted_dispatch_outside_sampling(self):
        calls=len(self.fixture.calls)
        with self.assertRaisesRegex(ValueError,'current verified native dispatch'):
            self.fixture.collector.quotes(['NVDA'],fields='all')
        self.assertEqual(len(self.fixture.calls),calls)


if __name__=='__main__':unittest.main()
