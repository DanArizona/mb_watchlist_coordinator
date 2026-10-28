from contextlib import closing
from datetime import timedelta
import sqlite3
import time
import unittest
import os,json,hashlib
from dataclasses import asdict

import test_daily_collector as collector_fixture
from mb_watchlist_coordinator.daily_source import DailySourcePump
from mb_watchlist_coordinator.daily_feed import DailyFeedClient
from test_nasdaq_feed_recovery import rss,EMPTY,HTML


class DailySourceTests(unittest.TestCase):
    def setUp(self):
        self.fixture=collector_fixture.DailyCollectorTests('test_tail_window_idle_then_three_hot_quotes_native_audit_and_replays')
        self.fixture.preparation_seconds=120
        if self._testMethodName=='test_actual_feed_children_drive_identity_publication_then_native_hot_quotes':
            self.fixture.proof_directory_override=os.environ.get('MB_DAILY_COLLECTION_PROOF_DIR')
        self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.case=self.fixture.case
        self.pump=self.make();self.pump.initialize(create=True)
        self.addCleanup(lambda:self.pump.close())

    def make(self):
        # The source/pacing workload uses an explicit logical monotonic clock;
        # each HTTP child still has its independent elapsed hard timeout.
        return DailySourcePump(self.case.session,identity_client=self.case.client,clock=lambda:self.case.now,
            feed_client_factory=lambda t:DailyFeedClient(t,monotonic=lambda:self.case.now.timestamp()))

    def attempt(self,raw):
        scenario={'clock_at_utc':self.case.now.isoformat(),'chunks':[raw.decode()]}
        end=time.monotonic()+5
        original=len(self.pump.transport.snapshot()['attempts'])
        while time.monotonic()<end:
            report=self.pump.cycle(synthetic=scenario)
            if len(self.pump.transport.snapshot()['attempts'])>original and not self.pump.client.owns_attempt:
                return report
            time.sleep(.01)
        self.fail('Synthetic daily source child did not complete in five seconds')

    def establish(self):
        self.attempt(EMPTY) # Valid CURRENT startup baseline.
        self.case.now+=timedelta(seconds=60)
        return self.attempt(rss(self.case.now.date(),symbol='NVDA',halt='15:57:30'))

    def test_actual_feed_children_drive_identity_publication_then_native_hot_quotes(self):
        from mb_market_data.watchlist_polling import PollSlot,PollRequest,WatchlistKind
        from mb_market_data.schwab_quotes import QuoteBatchResult,QuoteResult,QuoteStatus
        def acquire(channel):
            at=self.case.now;hierarchy=self.case.store.latest_membership_revision_effective_at(at)
            symbols=getattr(hierarchy,channel+'_symbols')
            request=PollRequest(PollSlot(WatchlistKind(channel),at,'interleaved-v1'),hierarchy.revision,symbols,at)
            result=QuoteBatchResult(tuple(QuoteResult(s,QuoteStatus.QUOTE,{'symbol':s,'quote':{'lastPrice':12.0}},
                None,1,at,at) for s in symbols),1,400,())
            self.case.store.record_acquisition('existing-'+channel,request,result,completed_at=at)
        self.attempt(EMPTY)
        self.case.now=self.case.now.replace(minute=58,second=30);acquire('uni')
        self.case.now=self.case.now.replace(second=50)
        report=self.attempt(rss(self.case.now.date(),symbol='NVDA',halt='15:57:30'))
        self.assertTrue(report['source_only']);self.assertFalse(report['collector_managed'])
        self.assertEqual(self.case.calls,[['NVDA']])
        self.assertEqual(self.case.store.membership_revisions_in_effective_order()[-1].hot_symbols,('NVDA',))
        self.case.now=self.case.now.replace(minute=59,second=10);acquire('focus')
        self.case.now=self.case.now.replace(second=30);acquire('uni')
        self.case.now=self.case.now.replace(second=40);acquire('focus')
        self.case.now=self.case.now.replace(second=50)
        report=self.attempt(rss(self.case.now.date(),symbol='NVDA',halt='15:57:30'))
        self.assertTrue(report['discovery_scope_reconciled'])
        self.fixture.collector.prepare(create=True)
        for second in (52,54,56,58):self.fixture.tick(second)
        with closing(sqlite3.connect(self.case.journal)) as c:
            self.assertEqual(c.execute('SELECT count(*) FROM quote_acquisition WHERE channel="hot"').fetchone()[0],4)
        self.assertEqual(self.fixture.calls,[['NVDA']]*4)
        from mb_market_data.quote_journal_audit import audit_quote_journal
        audited_at=self.case.now.replace(hour=16,minute=0,second=0)
        audit=audit_quote_journal(self.case.journal,audited_at=audited_at)
        self.assertTrue(audit.passed)
        from mb_market_data.quote_journal_replay import QuoteJournalReplayReader
        first=tuple(QuoteJournalReplayReader(self.case.journal).events())
        self.assertEqual(first,tuple(QuoteJournalReplayReader(self.case.journal).events()))
        self.assertEqual(len(first),11)
        if os.environ.get('MB_DAILY_COLLECTION_PROOF_DIR'):
            native=self.case.root/'native-audit.json'
            native.write_text(json.dumps(asdict(audit),indent=2,default=str)+'\n')
            proof={'contract':'daily-source-native-collection-proof-v1','result':'PASS','synthetic_only':True,
                'clock':'logical; actual owned HTTP/collector process drills elsewhere in suite',
                'journal':str(self.case.journal),'source_attempts':3,'source_reconciled':True,
                'identity_quote_permits':self.case.session.status()['identity_quote_permits'],
                'membership_revisions':3,'events':11,'acquisitions':{'uni':2,'focus':2,'hot':4},
                'observations':13,'native_audit_passed':True,'two_fresh_replays_equal':True,
                'sequence_sha256':hashlib.sha256(''.join(e.event_id+'\n' for e in first).encode()).hexdigest(),
                'live_or_full_session_qualification':False,'authenticated_controller_qualified':False}
            (self.case.root/'proof.json').write_text(json.dumps(proof,indent=2)+'\n')

    def test_feed_failure_preserves_verified_hot_demand_and_native_collection(self):
        self.establish();self.case.now+=timedelta(seconds=60)
        report=self.attempt(HTML)
        self.assertFalse(report['discovery_scope_reconciled'])
        self.assertEqual(self.case.store.membership_revisions_in_effective_order()[-1].hot_symbols,('NVDA',))
        self.case.now=self.case.now.replace(minute=59,second=50)
        self.fixture.collector.prepare(create=True);self.fixture.tick(52)
        self.assertEqual(self.fixture.calls,[['NVDA']])

    def test_source_reopen_keeps_existing_feed_attempts_identity_permits_and_publication(self):
        self.establish();before=self.case.store.membership_revisions_in_effective_order()
        self.pump.close();self.case.now+=timedelta(seconds=1)
        self.pump=self.make();self.pump.initialize()
        self.assertEqual(len(self.pump.transport.snapshot()['attempts']),2)
        self.assertEqual(self.case.session.status()['identity_quote_permits'],1)
        self.assertEqual(self.case.store.membership_revisions_in_effective_order(),before)

    def test_close_stops_only_its_feed_child_and_preserves_the_publication_owner(self):
        self.establish();self.pump.close()
        self.assertTrue(self.case.session.validate())
        self.assertEqual(self.case.store.membership_revisions_in_effective_order()[-1].hot_symbols,('NVDA',))

    def test_missing_source_ledger_cannot_reset_attempt_budget(self):
        self.attempt(EMPTY);self.pump.close();self.pump.transport.path.unlink()
        other=self.make()
        with self.assertRaises(ValueError):other.initialize(create=True)
        self.assertFalse(other.transport.path.exists())
        with self.assertRaises(FileNotFoundError):self.make().initialize()

    def test_parallel_source_owner_is_refused(self):
        from mb_watchlist_coordinator.sampling_service import ServiceBusy
        with self.assertRaises(ServiceBusy):self.make().initialize()


if __name__=='__main__':unittest.main()
