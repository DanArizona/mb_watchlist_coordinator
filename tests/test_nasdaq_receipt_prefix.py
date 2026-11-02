"""Append reuse must preserve the independent complete source replay."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import timedelta
import json
import sqlite3
import unittest

from mb_watchlist_coordinator.nasdaq_sampling import _reduce
from mb_watchlist_coordinator.sampling_requests import canonical, digest, plain
from test_nasdaq_sampling import NasdaqTests, START


class ReceiptPrefixTests(unittest.TestCase):
    def setUp(self):
        self.case = NasdaqTests('test_initial_current_snapshot_is_only_a_baseline')
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.p = self.case.producer

    def assert_full_replay_equal(self):
        snap = plain(self.p.snapshot())
        commands, outcomes = _reduce(self.p.identity, snap['receipts'])
        self.assertEqual(snap['commands'], commands)
        self.assertEqual(snap['outcomes'], outcomes)
        return snap

    def test_append_baseline_repeats_updates_historical_and_new_halts_match_full_replay(self):
        c = self.case
        self.p.record_snapshot(c.feed('history', [c.row(-1)], 'HISTORICAL'))
        c.baseline()
        for n, rows in enumerate(([c.row()], [c.row()],
                [c.row(reason='T3',resumption_trade_time='09:35:00')],
                [c.row(4)], [c.row(4),c.row(5,symbol='AAPL')]), 2):
            c.queue(rows, seconds=n, cid=f'capture-{n}')
            self.assert_full_replay_equal()
        before = self.assert_full_replay_equal()
        self.p = c.reopen()
        self.assertEqual(self.assert_full_replay_equal(), before)

    def test_changed_old_bytes_even_with_rehashed_chain_are_not_reused(self):
        c = self.case
        c.baseline(); c.queue(); self.assert_full_replay_equal()
        with closing(sqlite3.connect(self.p.path)) as db, db:
            value = json.loads(db.execute('SELECT payload FROM halt_receipt WHERE sequence=2').fetchone()[0])
            value['snapshot']['provenance']['extra']='edited after verification'
            body = dict(value); body.pop('event_sha256')
            value['event_sha256']=digest(body)
            db.execute('UPDATE halt_receipt SET payload=? WHERE sequence=2',(canonical(value),))
        with self.assertRaisesRegex(ValueError,'history changed'):
            self.p.snapshot()

    def test_deleted_tail_and_changed_capture_column_are_detected(self):
        for change in ('DELETE FROM halt_receipt WHERE sequence=2',
                "UPDATE halt_receipt SET capture_id='different' WHERE sequence=2"):
            with self.subTest(sql=change):
                c = NasdaqTests('test_initial_current_snapshot_is_only_a_baseline')
                c.setUp()
                try:
                    c.baseline(); c.queue(); c.producer.snapshot()
                    with closing(sqlite3.connect(c.producer.path)) as db, db:
                        db.execute(change)
                    with self.assertRaises(ValueError):
                        c.producer.snapshot()
                finally:
                    c.doCleanups()

    def test_invalid_new_snapshot_does_not_poison_prior_prefix(self):
        c = self.case
        c.baseline(); c.queue(); before=self.assert_full_replay_equal()
        with self.assertRaises(ValueError):
            c.queue([c.row(20)],seconds=3,cid='future')
        self.assertEqual(self.assert_full_replay_equal(),before)
        c.queue([c.row(4)],seconds=5,cid='valid-after-error')
        self.assert_full_replay_equal()

    def test_delivery_and_current_request_receipts_are_rechecked_on_unchanged_source(self):
        c = self.case
        c.baseline(); c.queue(); self.p.deliver_pending(); self.assert_full_replay_equal()
        with closing(sqlite3.connect(self.p.path)) as db, db:
            cid, raw = db.execute('SELECT * FROM halt_delivery').fetchone()
            value=json.loads(raw);value['request_sequence']=999
            db.execute('UPDATE halt_delivery SET payload=? WHERE command_id=?',(canonical(value),cid))
        with self.assertRaisesRegex(ValueError,'delivery acknowledgement'):
            self.p.snapshot()

    def test_parallel_public_snapshots_and_appends_keep_one_consistent_history(self):
        c = self.case
        c.baseline()
        def write():
            for n in range(2,20):
                c.at=START+timedelta(seconds=n)
                self.p.record_snapshot(c.feed(f'parallel-{n}',[c.row()]))
        def read():
            for _ in range(40):
                snap=plain(self.p.snapshot())
                commands,outcomes=_reduce(self.p.identity,snap['receipts'])
                self.assertEqual(commands,snap['commands'])
                self.assertEqual(outcomes,snap['outcomes'])
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures=[pool.submit(write),pool.submit(read),pool.submit(read)]
            for future in futures:
                future.result(timeout=15)
        self.assertEqual(len(self.assert_full_replay_equal()['receipts']),19)


if __name__ == '__main__':
    unittest.main()
