from datetime import datetime,timedelta,timezone
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from mb_market_data.quote_observation_store import QuoteObservationStore
from mb_market_data.sampling_membership import SamplingHierarchyRevision
from mb_market_data.sampling_acquisition import MARKER
from mb_watchlist_coordinator.hot_recovery_collector import HotCollectorSettings,HotRecoveryCollector
from mb_watchlist_coordinator.recovery_workers import HOT_SECONDS,next_future_slot
from mb_watchlist_coordinator.profile_evidence import native_facts,goal_counts,final_native_report
from mb_watchlist_coordinator.sampling_requests import utc_text


class ProfileEvidenceTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup);self.root=Path(t.name)
        self.start=(datetime.now(timezone.utc)+timedelta(days=1)).replace(hour=14,minute=0,second=0,microsecond=0);self.now=self.start
        case=self
        class Clock(datetime):
            @classmethod
            def now(cls,tz=None):return case.now.astimezone(tz or timezone.utc)
        p=patch('mb_market_data.schwab_quotes.datetime',Clock);p.start();self.addCleanup(p.stop)
        self.store=QuoteObservationStore(self.root/'quotes.sqlite3',session_date=self.start.date(),schema_version=2)
        self.store.initialize()
        self.store.record_membership_revision(SamplingHierarchyRevision(session_date=self.start.date(),revision=0,
            effective_at=self.start,uni_symbols=('MSFT',),focus_symbols=('MSFT',),hot_symbols=('MSFT',),
            source='synthetic-profile-evidence',metadata={MARKER:True,'experimental':True}))
        self.binding={'journal':{'path':str(self.store.database_path.resolve()),'session_date':self.start.date().isoformat(),'schema_version':2},'contract':'synthetic-profile-evidence'}
        self.settings=HotCollectorSettings(str(self.store.database_path),self.binding,utc_text(self.start),
            utc_text(self.start+timedelta(seconds=720)),max_quote_calls=60,max_symbols=1)
        self.invalid=False;self.calls=0
        class Response:
            ok=True;status_code=200
            def json(response):return {} if case.invalid else {'MSFT':{'symbol':'MSFT','assetMainType':'EQUITY','quote':{'lastPrice':12}}}
        class Client:
            def quotes(client,symbols,*,fields):case.calls+=1;return Response()
        self.worker=HotRecoveryCollector(self.settings,client_factory=Client,clock=lambda:self.now)
        self.worker.prepare(create=True);self.addCleanup(self.worker.close)
        self.session=SimpleNamespace(store=self.store,collector=self.worker)

    def poll(self,n):
        for _ in range(n):
            self.now=next_future_slot(self.now)
            self.assertEqual(self.worker.tick()['status'],'acquired')

    def facts(self,split=None):
        return native_facts(self.session,generation_for=lambda a:2 if split and a.scheduled_at_utc>=split else 1)[0]

    def report(self,profile='ordinary',**kw):
        return final_native_report(self.session,profile=profile,facts=self.facts(kw.pop('split',None)),
            stop_at_utc=utc_text(self.now+timedelta(microseconds=1)),cutover_at_utc=utc_text(self.start),
            source_reconciled=kw.pop('source_reconciled',True),**kw)

    def test_ordinary_thirty_actual_native_commits_and_acks_reach_goal(self):
        self.poll(30);r=self.report()
        self.assertEqual(r['result'],'PASS');self.assertEqual(r['goals']['after_cutover'],30)
        self.assertTrue(r['raw_native_audit_passed']);self.assertTrue(r['identical_fresh_replays']);self.assertEqual(self.calls,30)

    def test_goal_does_not_count_unacknowledged_commit(self):
        self.poll(29);self.now=next_future_slot(self.now)
        def fault(stage):
            if stage=='after_journal_commit':raise RuntimeError('synthetic post-commit interruption')
        with self.assertRaises(RuntimeError):self.worker.tick(fault_hook=fault)
        facts,state=native_facts(self.session,generation_for=lambda a:1)
        self.assertEqual(len(facts),30);self.assertEqual(sum(f['quote'] for f in facts),29)
        self.assertFalse(goal_counts('ordinary',facts,cutover_at_utc=utc_text(self.start))['goal_complete'])

    def test_partial_goals_and_feed_loss_are_incomplete(self):
        self.poll(2);self.assertEqual(self.report()['result'],'INCOMPLETE')
        self.assertEqual(self.report(source_reconciled=False)['result'],'INCOMPLETE')

    def test_non_quote_response_keeps_its_status_and_fails_profile(self):
        self.invalid=True;self.poll(1);r=self.report()
        self.assertEqual(r['result'],'FAILED');self.assertEqual(len(r['non_quote_acquisition_ids']),1)
        self.assertNotEqual(self.facts()[0]['statuses'],['quote'])

    def test_recovery_pause_is_reported_missing_without_rewriting_raw_audit(self):
        self.poll(12);before=self.facts();requested=self.now+timedelta(microseconds=1)
        fault={'generation':1,'token':'a'*32,'pid':101,'last_acknowledged_id':before[-1]['id'],
            'requested_at_utc':utc_text(requested),'exit_observed_at_utc':utc_text(requested)}
        self.now=requested+timedelta(seconds=15)
        restart={'generation':2,'token':'b'*32,'pid':102,'started_at_utc':utc_text(self.now),
            'ready_at_utc':utc_text(self.now),'first_eligible_slot_utc':utc_text(next_future_slot(self.now))}
        self.worker.close();self.worker=HotRecoveryCollector(self.settings,client_factory=lambda: self.client(),clock=lambda:self.now)
        # The same synthetic quote interface, with native future-only reopen.
        class Response:
            ok=True;status_code=200
            def json(self):return {'MSFT':{'assetMainType':'EQUITY','quote':{'lastPrice':12}}}
        self.client=lambda:SimpleNamespace(quotes=lambda *a,**kw:Response())
        self.worker.prepare();self.session.collector=self.worker
        self.poll(24)
        r=self.report('owned_worker_recovery',split=timestamp(restart['first_eligible_slot_utc']),fault=fault,restart=restart)
        self.assertEqual(r['result'],'PASS_WITH_WARNINGS');self.assertFalse(r['raw_native_audit_passed'])
        self.assertTrue(r['intentional_outage_missing_slot_ids']);self.assertEqual(r['unexplained_missing_slot_ids'],[])
        self.assertEqual(r['goals']['before_fault'],12);self.assertEqual(r['goals']['after_restart'],24)

    def test_unexplained_missing_slot_fails(self):
        self.poll(1);self.now=next_future_slot(self.now);self.now=next_future_slot(self.now);self.worker.tick()
        self.assertEqual(self.report()['result'],'FAILED')

    def test_duplicate_or_early_replacement_cannot_satisfy_goals(self):
        self.poll(1);facts=self.facts()
        with self.assertRaises(ValueError):goal_counts('ordinary',facts+facts,cutover_at_utc=utc_text(self.start))
        fault={'generation':1,'token':'a'*32,'pid':1,'last_acknowledged_id':facts[-1]['id'],
            'requested_at_utc':utc_text(self.now),'exit_observed_at_utc':utc_text(self.now)}
        restart={'generation':2,'token':'b'*32,'pid':2,'started_at_utc':utc_text(self.now+timedelta(seconds=14)),
            'ready_at_utc':utc_text(self.now+timedelta(seconds=14)),'first_eligible_slot_utc':utc_text(next_future_slot(self.now+timedelta(seconds=14)))}
        with self.assertRaises(ValueError):goal_counts('owned_worker_recovery',facts,cutover_at_utc=utc_text(self.start),fault=fault,restart=restart)

    def test_cleanup_time_commit_cannot_complete_a_goal_after_the_stop_endpoint(self):
        self.poll(30)
        r=final_native_report(self.session,profile='ordinary',facts=self.facts(),
            stop_at_utc=utc_text(self.now-timedelta(microseconds=1)),cutover_at_utc=utc_text(self.start),source_reconciled=True)
        self.assertEqual(r['goals']['after_cutover'],29);self.assertFalse(r['goals']['goal_complete'])
        self.assertEqual(r['result'],'INCOMPLETE')


from mb_watchlist_coordinator.sampling_requests import timestamp
