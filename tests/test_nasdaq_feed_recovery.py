from contextlib import closing
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest

from mb_watchlist_coordinator.nasdaq_feed_recovery import (BASE_URL, BoundedFeedClient,
    FeedLimits, FeedRecoveryTransport, MAX_BYTES, classify, query_url)
from mb_watchlist_coordinator.nasdaq_feed_worker import fetch_http
from mb_watchlist_coordinator.nasdaq_recovery import RecoveryQuery
from mb_watchlist_coordinator.sampling_requests import canonical, digest
from mb_watchlist_coordinator.sampling_service import owner_lock

EMPTY = b'<rss><channel></channel></rss>'
HTML = b'<html><body>challenge</body></html>'


def rss(day, symbol='MSFT', halt='10:00:00', reason='LUDP', extra=''):
    return ('<rss><channel><item><ndaq:HaltDate>'+day.strftime('%m/%d/%Y')+
        '</ndaq:HaltDate><ndaq:HaltTime>'+halt+'</ndaq:HaltTime><ndaq:IssueSymbol>'+symbol+
        '</ndaq:IssueSymbol><ndaq:ReasonCode>'+reason+'</ndaq:ReasonCode>'+extra+
        '</item></channel></rss>').encode()


class FeedLedgerTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name);self.now=datetime.now(timezone.utc).replace(hour=20)
        self.query=RecoveryQuery(self.now.date(),self.now.date())
        self.transport=self.open();self.transport.initialize(create=True)

    def open(self, **kw):
        args=dict(session_date=self.now.date(),queries=(self.query,),clock=lambda:self.now);args.update(kw)
        return FeedRecoveryTransport(self.root/'feed.sqlite3',**args)

    def complete(self, query=None, raw=EMPTY, *, code=200, headers=None, error=None):
        r=self.transport.reserve(query,synthetic=True)
        self.assertIsNotNone(r)
        metadata={'status_code':code,'final_url':query_url(query),'headers':headers or {},
            'body_complete':True,'transport_error_type':error}
        self.transport.progress(r,metadata,raw);self.transport.finish(r)
        return self.transport.snapshot()['attempts'][-1]

    def test_union_query_url_and_fixed_origin(self):
        text=query_url(self.query)
        self.assertTrue(text.startswith(BASE_URL+'?feed=tradehalts&haltdate='))
        self.assertIn('&resumedate=',text)
        with self.assertRaises(ValueError):query_url('https://elsewhere/')

    def test_current_and_dated_share_completion_based_pacing_across_reopen(self):
        first=self.complete();self.now+=timedelta(seconds=59)
        self.assertIsNone(self.open().reserve(self.query,synthetic=True))
        self.now+=timedelta(seconds=1);self.assertIsNotNone(self.open().reserve(self.query,synthetic=True))
        self.assertEqual(first['outcome']['status'],'valid')

    def test_slow_attempt_paces_from_completion_not_dispatch(self):
        r=self.transport.reserve(synthetic=True);self.now+=timedelta(seconds=9)
        self.transport.progress(r,{'status_code':200,'body_complete':True,'headers':{},'final_url':query_url()},EMPTY)
        self.transport.finish(r);self.now+=timedelta(seconds=59)
        self.assertIsNone(self.transport.reserve(self.query,synthetic=True))

    def test_html_is_retained_and_never_becomes_empty_feed(self):
        a=self.complete(raw=HTML)
        self.assertEqual(a['raw'],HTML);self.assertEqual(a['outcome']['kind'],'non_feed_html')
        with self.assertRaises(ValueError):self.transport.halt_snapshot(a)

    def test_valid_empty_is_distinct_from_failed_or_malformed_response(self):
        self.assertEqual(self.complete()['outcome']['records'],[])
        self.now+=timedelta(seconds=60)
        self.assertEqual(self.complete(raw=b'<rss><channel>')['outcome']['kind'],'malformed_xml')
        self.assertEqual(len(self.transport.snapshot()['attempts']),2)

    def test_three_unavailable_attempts_stop_without_automatic_restart(self):
        for _ in range(3):
            self.complete(raw=HTML);self.now+=timedelta(seconds=60)
        self.assertEqual(self.open().snapshot()['stop_reason'],'consecutive_unavailable_limit')
        self.assertIsNone(self.open().reserve(synthetic=True))

    def test_valid_recovery_resets_consecutive_failure_but_retains_failed_attempt(self):
        self.complete(raw=HTML);self.now+=timedelta(seconds=60);self.complete()
        self.assertEqual(self.transport.snapshot()['consecutive_failures'],0)
        self.assertEqual(len(self.transport.snapshot()['attempts']),2)

    def test_access_denial_redirect_and_retry_after_are_terminal(self):
        for code in (403,429,302,503):
            metadata={'status_code':code,'body_complete':True,'headers':{'Retry-After':'120'} if code==503 else {}}
            self.assertTrue(classify(HTML,metadata,url=query_url(),at=self.now,historical=False)['terminal'])

    def test_body_size_length_encoding_and_non_rss_fail_explicitly(self):
        for raw,headers,expected in ((b'x'*(MAX_BYTES+1),{},'body_limit'),
                (EMPTY,{'Content-Length':'1'},'content_length_mismatch'),
                (EMPTY,{'Content-Length':'bad'},'invalid_content_length'),
                (b'\xff',{},'invalid_utf8'),(b'<other/>',{},'non_rss_document'),
                (b'<!DOCTYPE rss><rss><channel/></rss>',{},'unsupported_xml_declaration')):
            outcome=classify(raw,{'status_code':200,'body_complete':True,'headers':headers},url=query_url(),at=self.now,historical=False)
            self.assertEqual(outcome['kind'],expected)

    def test_normalized_release_fields_and_raw_bytes_remain_distinct(self):
        raw=rss(self.now.date(),extra='<ndaq:ResumptionTradeTime>10:05:00</ndaq:ResumptionTradeTime>')
        a=self.complete(self.query,raw)
        snap=self.transport.halt_snapshot(a)
        self.assertEqual(snap.raw_sha256,hashlib.sha256(raw).hexdigest())
        self.assertEqual(snap.records[0]['resumption_trade_time'],'10:05:00')
        self.assertEqual(snap.retrieval_mode,'HISTORICAL')

    def test_conflicting_rows_fail_without_silently_choosing_a_version(self):
        one=rss(self.now.date());two=rss(self.now.date(),reason='T3')
        raw=one.replace(b'</channel></rss>',two.split(b'<channel>')[1])
        self.assertEqual(self.complete(raw=raw)['outcome']['kind'],'conflicting_rows')

    def test_future_halt_is_unavailable_before_ingestion(self):
        future=self.now.date()+timedelta(days=1)
        self.assertEqual(self.complete(raw=rss(future))['outcome']['kind'],'future_halt_timestamp')

    def test_partial_diagnostic_bytes_survive_unknown_completion_and_stale_worker_is_fenced(self):
        r=self.transport.reserve(synthetic=True)
        self.transport.progress(r,{'status_code':200,'body_complete':False,'headers':{}},b'<rss>')
        self.transport.finish(r,unknown='interrupted')
        self.assertEqual(self.open().snapshot()['attempts'][0]['raw'],b'<rss>')
        with self.assertRaisesRegex(ValueError,'Stale'):self.open().progress(r,{},b'x')

    def test_no_second_reservation_while_attempt_is_pending(self):
        self.transport.reserve(synthetic=True)
        self.assertIsNone(self.open().reserve(self.query,synthetic=True))

    def test_attempt_and_elapsed_budgets_survive_reopen(self):
        t=FeedRecoveryTransport(self.root/'small.sqlite3',session_date=self.now.date(),queries=(self.query,),
            limits=FeedLimits(max_attempts=1,budget_seconds=2),clock=lambda:self.now);t.initialize(create=True)
        r=t.reserve(synthetic=True);self.now+=timedelta(seconds=3)
        t.progress(r,{'status_code':200,'body_complete':True,'headers':{}},EMPTY);t.finish(r)
        self.assertEqual(t.snapshot()['attempts'][0]['outcome']['kind'],'unknown_hard_deadline')
        self.assertIsNone(t.reserve(synthetic=True))

    def test_clock_rollback_header_leak_and_undeclared_query_do_not_append(self):
        r=self.transport.reserve(synthetic=True)
        with self.assertRaises(ValueError):self.transport.progress(r,{'headers':{'Set-Cookie':'private'}})
        self.now-=timedelta(seconds=1)
        with self.assertRaises(ValueError):self.transport.progress(r,{},b'a')
        self.assertEqual(len(self.transport.snapshot()['events']),1)

    def test_raw_body_corruption_after_warm_read_fails(self):
        self.complete();self.transport.snapshot()
        with closing(sqlite3.connect(self.transport.path)) as c,c:
            c.execute("UPDATE feed_event SET body=? WHERE json_extract(payload,'$.kind')='progress'",(b'changed',))
        with self.assertRaisesRegex(ValueError,'chain'):self.open().snapshot()

    def test_rehashed_false_valid_outcome_still_fails(self):
        self.complete(raw=HTML)
        with closing(sqlite3.connect(self.transport.path)) as c,c:
            n,p=c.execute('SELECT sequence,payload FROM feed_event ORDER BY sequence DESC LIMIT 1').fetchone()
            e=json.loads(p);e['outcome']={'status':'valid','kind':'rss','terminal':False,'records':[]};e.pop('event_sha256');e['event_sha256']=digest(e)
            c.execute('UPDATE feed_event SET payload=? WHERE sequence=?',(canonical(e),n))
        with self.assertRaisesRegex(ValueError,'outcome'):self.transport.snapshot()

    def test_missing_or_changed_ledger_is_not_silently_replaced(self):
        self.transport.path.unlink()
        with self.assertRaises(FileNotFoundError):self.open().initialize()
        self.assertFalse(self.transport.path.exists())
        with self.assertRaises(ValueError):FeedLimits(interval_seconds=59)
        with self.assertRaises(ValueError):FeedLimits(max_attempts=11)


class BoundedChildTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name);day=datetime.now(timezone.utc).date()
        self.query=RecoveryQuery(day,day)
        self.transport=FeedRecoveryTransport(self.root/'feed.sqlite3',session_date=day,queries=(self.query,),limits=FeedLimits(hard_timeout_seconds=1))
        self.transport.initialize(create=True)
        self.client=BoundedFeedClient(self.transport)

    def test_network_is_disabled_without_explicit_authorization(self):
        with self.assertRaisesRegex(ValueError,'HTTP disabled'):self.client.attempt()
        self.assertFalse(self.transport.snapshot()['events'])

    def test_owned_synthetic_child_retains_valid_body_and_exits(self):
        r=self.client.attempt(self.query,synthetic={'chunks':[EMPTY.decode()]})
        self.assertEqual(r['status'],'completed')
        self.assertEqual(r['attempt']['outcome']['status'],'valid')
        self.assertTrue(r['attempt']['synthetic'])

    def test_independent_hard_deadline_stops_hanging_child(self):
        before=time.monotonic()
        r=self.client.attempt(synthetic={'hang_before_headers':True})
        self.assertLess(time.monotonic()-before,4)
        self.assertEqual(r['attempt']['outcome']['kind'],'unknown_hard_deadline')
        self.assertIsNone(self.transport.snapshot()['pending'])

    def test_stop_during_http_marks_unknown_and_returns_without_past_retry(self):
        before=time.monotonic()
        r=self.client.attempt(synthetic={'hang_after_body':True,'chunks':['<rss>']},stop_requested=lambda:time.monotonic()-before>.3)
        self.assertEqual(r['attempt']['outcome']['kind'],'unknown_stop_requested')
        self.assertEqual(self.client.attempt(synthetic={'chunks':[EMPTY.decode()]})['status'],'waiting_for_pacing')

    def test_reopen_of_unfinished_attempt_waits_for_network_owner_then_fences(self):
        self.transport.reserve(synthetic=True)
        with owner_lock(self.transport.path.with_suffix('.network.lock')):
            self.assertEqual(self.client.attempt(synthetic={})['status'],'in_flight_unknown')
        self.assertEqual(self.client.attempt(synthetic={})['status'],'waiting_for_pacing')
        self.assertEqual(self.transport.snapshot()['attempts'][0]['outcome']['kind'],'unknown_interrupted')

    def test_monotonic_reopen_cooldown_survives_forward_wall_jump(self):
        self.client.attempt(synthetic={'chunks':[EMPTY.decode()]})
        self.transport.clock=lambda:datetime.now(timezone.utc)+timedelta(hours=1)
        reopened=BoundedFeedClient(self.transport)
        self.assertEqual(reopened.attempt(synthetic={})['status'],'waiting_for_pacing')

    def test_child_enforces_its_deadline_even_without_a_surviving_controller(self):
        import mb_watchlist_coordinator.nasdaq_feed_recovery as module
        from mb_watchlist_coordinator.sampling_requests import plain
        r=self.transport.reserve(synthetic=True)
        job={'path':str(self.transport.path),'identity':plain(self.transport.identity),'reservation':r,
             'synthetic':{'hang_before_headers':True}}
        child=subprocess.Popen([sys.executable,'-I','-B',str(Path(module.__file__).with_name('nasdaq_feed_worker.py'))],
            stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        try:
            child.stdin.write(json.dumps(job).encode());child.stdin.close()
            self.assertEqual(child.wait(timeout=4),124)
            self.assertIsNotNone(self.transport.snapshot()['pending'])
            self.assertEqual(self.client.attempt(synthetic={})['status'],'waiting_for_pacing')
        finally:
            if child.poll() is None:child.kill();child.wait(timeout=2)

    def test_http_adapter_retains_error_body_and_only_allowed_headers(self):
        class Response:
            headers={'Content-Type':'text/html','Set-Cookie':'not retained'}
            def getcode(self):return 403
            def geturl(self):return query_url()
            def read(self,n):
                value=getattr(self,'body',HTML);self.body=b'';return value
            def close(self):pass
        class Opener:
            def open(self,request,timeout):return Response()
        r=self.transport.reserve(synthetic=True);fetch_http(self.transport,r,opener=Opener())
        a=self.transport.snapshot()['attempts'][0]
        self.assertEqual(a['raw'],HTML)
        self.assertNotIn('Set-Cookie',a['metadata']['headers'])
        self.assertTrue(a['outcome']['terminal'])


if __name__=='__main__':unittest.main()
