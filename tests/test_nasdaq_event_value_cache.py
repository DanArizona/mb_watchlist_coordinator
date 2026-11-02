"""Pure timestamp/identity reuse must never cache source authorization."""
from contextlib import closing
from datetime import timedelta
import json
import sqlite3
import unittest

from mb_watchlist_coordinator.nasdaq_sampling import (
    _event_time_value, _event_identity_value, event_time, halt_event_id,
)
from mb_watchlist_coordinator.sampling_requests import digest
from test_nasdaq_sampling import NasdaqTests, START


class EventValueCacheTests(unittest.TestCase):
    def setUp(self):
        _event_time_value.cache_clear()
        _event_identity_value.cache_clear()

    def row(self, **changes):
        return dict(symbol='MSFT', halt_date='11/02/2026',
            halt_time='10:00:00.000000', reason_code='LUDP', **changes)

    def test_equal_values_have_the_original_exact_identity(self):
        row = self.row()
        expected = 'nasdaq-halt-'+digest(['MSFT','2026-11-02T15:00:00+00:00'])
        self.assertEqual(halt_event_id(row), expected)
        self.assertEqual(halt_event_id(dict(row)), expected)
        self.assertEqual(_event_time_value.cache_info().hits, 1)
        self.assertEqual(_event_identity_value.cache_info().hits, 1)

    def test_timestamp_symbol_and_date_changes_cannot_reuse_an_identity(self):
        row = self.row()
        original = halt_event_id(row)
        for field, value in (('symbol','AAPL'),('halt_time','10:00:01.000000'),('halt_date','11/03/2026')):
            changed = dict(row, **{field:value})
            self.assertNotEqual(halt_event_id(changed), original)
        self.assertEqual(halt_event_id(row), original)

    def test_mutable_reason_and_resumption_keep_the_original_event_identity(self):
        row = self.row()
        self.assertEqual(halt_event_id(row), halt_event_id(dict(row,
            reason_code='T3', resumption_trade_time='10:05:00')))

    def test_invalid_new_strings_still_fail_after_warming(self):
        row = self.row()
        event_time(row)
        for field, value in (('halt_date','02/30/2026'),('halt_time','25:00:00'),('halt_time','10:00'),('halt_date','invalid')):
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                event_time(dict(row, **{field:value}))

    def test_eastern_offsets_and_equal_fraction_spellings_are_preserved(self):
        standard = self.row()
        daylight = dict(standard, halt_date='10/30/2026')
        self.assertEqual(event_time(standard).utcoffset(),timedelta(hours=-5))
        self.assertEqual(event_time(daylight).utcoffset(),timedelta(hours=-4))
        self.assertEqual(halt_event_id(standard),halt_event_id(dict(standard,halt_time='10:00:00')))

    def test_caches_are_bounded_and_hold_no_policy_results(self):
        self.assertEqual(_event_time_value.cache_info().maxsize,4096)
        self.assertEqual(_event_identity_value.cache_info().maxsize,4096)
        for second in range(4100):
            at = START+timedelta(seconds=second)
            event_time({'halt_date':at.strftime('%m/%d/%Y'),'halt_time':at.strftime('%H:%M:%S')})
            _event_identity_value('MSFT',at.isoformat())
        self.assertEqual(_event_time_value.cache_info().currsize,4096)
        self.assertEqual(_event_identity_value.cache_info().currsize,4096)

    def test_warm_event_values_do_not_hide_receipt_edits(self):
        case = NasdaqTests('test_initial_current_snapshot_is_only_a_baseline')
        case.setUp()
        try:
            case.baseline()
            case.queue()
            case.producer.snapshot()
            event_time(case.row())
            with closing(sqlite3.connect(case.producer.path)) as c, c:
                raw = json.loads(c.execute('SELECT payload FROM halt_receipt WHERE sequence=2').fetchone()[0])
                raw['snapshot']['records'][0]['reason_code']='T1'
                c.execute('UPDATE halt_receipt SET payload=? WHERE sequence=2',(json.dumps(raw),))
            with self.assertRaises(ValueError):
                case.producer.snapshot()
        finally:
            case.doCleanups()


if __name__ == '__main__':
    unittest.main()
