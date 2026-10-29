from dataclasses import replace
from datetime import datetime,timedelta,timezone
from pathlib import Path
import tempfile
import time
import json,subprocess,sys
import unittest
from zoneinfo import ZoneInfo

from mb_watchlist_coordinator.daily_feed import DailyFeedLimits,DailyFeedTransport,DailyFeedClient
from mb_watchlist_coordinator.nasdaq_feed_recovery import FeedLimits,query_url
from mb_watchlist_coordinator.nasdaq_recovery import RecoveryQuery

EMPTY=b'<rss><channel></channel></rss>'


class DailyFeedTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        self.now=(datetime.now(ZoneInfo('America/New_York'))+timedelta(days=1)).replace(
            hour=10,minute=0,second=0,microsecond=0)
        self.query=RecoveryQuery(self.now.date(),self.now.date())
        self.transport=self.open();self.transport.initialize(create=True)

    def open(self,limits=None):
        return DailyFeedTransport(self.root/'feed.sqlite3',session_date=self.query.halt_date,
            queries=(self.query,),limits=limits,clock=lambda:self.now)

    def complete(self,raw=EMPTY,*,code=200):
        reserved=self.transport.reserve(synthetic=True)
        self.assertIsNotNone(reserved)
        self.transport.progress(reserved,{'status_code':code,'final_url':query_url(),
            'headers':{},'body_complete':True},raw)
        self.transport.finish(reserved)
        return self.transport.snapshot()['attempts'][-1]

    def test_daily_limits_are_separate_and_original_experiment_stays_bounded(self):
        self.assertEqual(self.transport.limits.max_attempts,390)
        self.assertEqual(self.transport.limits.budget_seconds,23400)
        with self.assertRaises(ValueError):FeedLimits(max_attempts=390,budget_seconds=23400)

    def test_pacing_is_at_least_sixty_seconds_after_completion_across_reopen(self):
        reserved=self.transport.reserve(synthetic=True)
        self.now+=timedelta(seconds=5)
        self.transport.progress(reserved,{'status_code':200,'final_url':query_url(),
            'headers':{},'body_complete':True},EMPTY);self.transport.finish(reserved)
        self.now+=timedelta(seconds=59)
        self.assertIsNone(self.open().reserve(self.query,synthetic=True))
        self.now+=timedelta(seconds=1)
        self.assertIsNotNone(self.open().reserve(self.query,synthetic=True))

    def test_attempts_after_the_old_ten_attempt_limit_are_explicit_daily_evidence(self):
        for _ in range(12):self.complete();self.now+=timedelta(seconds=60)
        self.assertEqual(len(self.open().snapshot()['attempts']),12)

    def test_explicit_daily_attempt_ceiling_persists(self):
        self.transport=self.open(DailyFeedLimits(max_attempts=2))
        # Existing identity cannot silently change its ceiling.
        with self.assertRaises(ValueError):self.transport.snapshot()

    def test_preopen_and_close_do_not_reserve_work(self):
        self.now=self.now.replace(hour=9,minute=29)
        self.assertIsNone(self.transport.reserve(synthetic=True))
        self.now=self.now.replace(hour=16,minute=0)
        self.assertIsNone(self.transport.reserve(synthetic=True))

    def test_body_crossing_close_is_retained_as_unknown_not_normal_capture(self):
        self.now=self.now.replace(hour=15,minute=59,second=59)
        r=self.transport.reserve(synthetic=True)
        self.transport.progress(r,{'status_code':200,'final_url':query_url(),
            'headers':{},'body_complete':True},EMPTY)
        self.now+=timedelta(seconds=1);self.transport.finish(r)
        attempt=self.transport.snapshot()['attempts'][-1]
        self.assertEqual(attempt['outcome']['kind'],'unknown_hard_deadline')
        self.assertEqual(attempt['raw'],EMPTY)

    def test_http_rate_limit_and_three_unavailable_outcomes_stop_without_reset(self):
        self.complete(code=429)
        self.now+=timedelta(seconds=60)
        self.assertIsNone(self.open().reserve(synthetic=True))

    def test_modified_window_or_expanded_limits_are_refused(self):
        self.transport.stop+=timedelta(seconds=1)
        with self.assertRaises(ValueError):self.transport.reserve(synthetic=True)
        for values in ({'max_attempts':391},{'max_attempts':True},{'interval_seconds':59},
                       {'budget_seconds':23401},{'hard_timeout_seconds':11}):
            with self.assertRaises(ValueError):DailyFeedLimits(**values)

    def test_actual_synthetic_http_child_uses_daily_worker_and_retains_receipts(self):
        client=DailyFeedClient(self.transport)
        self.addCleanup(client.close_owned)
        result=client.attempt(synthetic={'clock_at_utc':self.now.isoformat(),'chunks':[EMPTY.decode()]})
        self.assertEqual(result['attempt']['outcome']['status'],'valid')
        self.assertEqual(result['attempt']['raw'],EMPTY)
        self.assertTrue(result['attempt']['synthetic'])

    def test_actual_child_shares_advancing_parent_clock_instead_of_an_older_sample(self):
        real_anchor=datetime.now(timezone.utc)
        logical_anchor=self.now
        self.transport.clock=lambda:logical_anchor+(datetime.now(timezone.utc)-real_anchor)
        client=DailyFeedClient(self.transport);self.addCleanup(client.close_owned)
        result=client.attempt(synthetic={'clock_at_utc':logical_anchor.isoformat(),
            'clock_real_anchor_utc':real_anchor.isoformat(),'chunks':[EMPTY.decode()]})
        attempt=result['attempt']
        self.assertEqual(attempt['outcome']['status'],'valid',attempt)
        self.assertEqual(attempt['raw'],EMPTY)
        self.assertGreater(datetime.fromisoformat(attempt['completed_at_utc']),
            datetime.fromisoformat(attempt['started_at_utc']))
        self.assertEqual(len(self.transport.snapshot()['attempts']),1)

    def test_network_is_refused_by_default_before_reservation(self):
        client=DailyFeedClient(self.transport)
        with self.assertRaises(ValueError):client.step()
        self.assertFalse(self.transport.snapshot()['events'])

    def short_transport(self):
        t=DailyFeedTransport(self.root/'short-feed.sqlite3',session_date=self.query.halt_date,
            queries=(self.query,),limits=DailyFeedLimits(hard_timeout_seconds=.3),clock=lambda:self.now)
        t.initialize(create=True);return t

    def test_actual_daily_child_hang_is_bounded_and_charges_unknown_attempt(self):
        t=self.short_transport();client=DailyFeedClient(t);self.addCleanup(client.close_owned)
        before=time.monotonic()
        result=client.attempt(synthetic={'clock_at_utc':self.now.isoformat(),'hang_before_headers':True})
        self.assertLess(time.monotonic()-before,3)
        self.assertEqual(result['attempt']['outcome']['kind'],'unknown_hard_deadline')
        self.assertEqual(len(t.snapshot()['attempts']),1)

    def test_daily_orphan_worker_exits_at_its_own_deadline_without_parent(self):
        import mb_watchlist_coordinator.daily_feed_worker as entry
        t=self.short_transport();reservation=t.reserve(synthetic=True)
        job={'path':str(t.path.resolve()),'identity':dict(t.identity),'reservation':reservation,
            'synthetic':{'clock_at_utc':self.now.isoformat(),'hang_before_headers':True}}
        from mb_watchlist_coordinator.sampling_requests import plain
        result=subprocess.run([sys.executable,'-I','-B',entry.__file__],input=json.dumps(plain(job)).encode(),
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=4)
        self.assertEqual(result.returncode,124,result.stderr.decode(errors='replace'))
        self.assertIsNotNone(t.snapshot()['pending'])
        client=DailyFeedClient(t);self.addCleanup(client.close_owned)
        client.step(synthetic={'clock_at_utc':self.now.isoformat(),'chunks':[EMPTY.decode()]})
        self.assertEqual(t.snapshot()['attempts'][0]['outcome']['kind'],'unknown_interrupted')


if __name__=='__main__':unittest.main()
