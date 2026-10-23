from dataclasses import replace
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import json
import sqlite3
from pathlib import Path
import tempfile
import sys
import time
import unittest
from unittest.mock import patch

from mb_market_data.quote_observation_store import QuoteObservationStore
from mb_market_data.sampling_membership import SamplingHierarchyRevision
from mb_market_data.sampling_acquisition import MARKER
from mb_market_data.quote_journal_audit import audit_quote_journal
from mb_market_data.quote_journal_replay import QuoteJournalReplayReader
from mb_watchlist_coordinator.hot_recovery_collector import HotCollectorSettings, HotRecoveryCollector
from mb_watchlist_coordinator.recovery_workers import ManagedRecoveryWorker


class Response:
    ok=True
    status_code=200
    def __init__(self, symbols):self.symbols=symbols
    def json(self):return {s:{'assetMainType':'EQUITY','quote':{'lastPrice':12.0}} for s in self.symbols}


class HotRecoveryCollectorTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)
        self.at=(datetime.now(timezone.utc)+timedelta(days=1)).replace(hour=14,minute=0,second=0,microsecond=0)
        self.now=self.at;case=self
        class Clock(datetime):
            @classmethod
            def now(cls,tz=None):return case.now.astimezone(tz or timezone.utc)
        p=patch('mb_market_data.schwab_quotes.datetime',Clock);p.start();self.addCleanup(p.stop)
        self.store=QuoteObservationStore(self.root/'quotes.sqlite3',session_date=self.at.date(),schema_version=2)
        self.store.initialize()
        self.store.record_membership_revision(SamplingHierarchyRevision(session_date=self.at.date(),revision=0,
            effective_at=self.at,uni_symbols=('MSFT','SPY'),focus_symbols=('MSFT',),hot_symbols=('MSFT',),
            source='synthetic-recovery-integration',metadata={MARKER:True,'experimental':True}))
        self.binding={'journal':{'path':str(self.store.database_path.resolve()),'session_date':self.at.date().isoformat(),'schema_version':2},'contract':'synthetic-explicit-publication'}
        self.settings=HotCollectorSettings(str(self.store.database_path),self.binding,self.at.isoformat(),(self.at+timedelta(seconds=60)).isoformat(),max_quote_calls=2,max_symbols=1)
        self.calls=[];self.factories=0
        self.worker=self.open();self.worker.prepare(create=True)

    def factory(self):
        self.factories+=1;case=self
        class Client:
            def quotes(self,symbols,*,fields):case.calls.append((list(symbols),fields));return Response(symbols)
        return Client()

    def open(self,settings=None):return HotRecoveryCollector(settings or self.settings,client_factory=self.factory,clock=lambda:self.now)
    def advance(self,seconds):self.now=self.at+timedelta(seconds=seconds)
    def fail(self,stage):
        def hook(point):
            if point==stage:raise RuntimeError('injected interruption: '+point)
        return hook

    def test_real_native_collector_uses_effective_hot_and_lazy_client(self):
        self.assertEqual(self.factories,0)
        self.advance(2);result=self.worker.tick()
        self.assertEqual(result['status'],'acquired');self.assertEqual(self.calls,[(['MSFT'],'all')])
        self.assertEqual(self.store.acquisitions_in_replay_order()[0].channel,'hot')
        self.assertEqual(self.store.get_observations(self.store.acquisitions_in_replay_order()[0].acquisition_id)[0].status,'quote')

    def test_idle_and_empty_membership_do_not_construct_provider(self):
        self.assertEqual(self.worker.tick()['status'],'idle')
        old=self.store.membership_revisions_in_effective_order()[-1]
        self.store.record_membership_revision(replace(old,published_at=None,revision=1,effective_at=self.at+timedelta(seconds=1),hot_symbols=()))
        self.advance(2);self.assertEqual(self.worker.tick()['status'],'empty_membership')
        self.assertEqual(self.factories,0)

    def test_saved_assembled_response_recovers_without_provider_call(self):
        self.advance(2)
        with self.assertRaises(RuntimeError):self.worker.tick(fault_hook=self.fail('after_assembled'))
        calls=len(self.calls);self.advance(10)
        reopened=self.open();result=reopened.prepare()
        self.assertTrue(result['recovered']);self.assertEqual(len(self.calls),calls)
        self.assertEqual(len(self.store.acquisitions_in_replay_order()),1)
        self.assertGreater(reopened.next.scheduled_at,self.now)

    def test_commit_before_ack_reopens_idempotently(self):
        self.advance(2)
        with self.assertRaises(RuntimeError):self.worker.tick(fault_hook=self.fail('after_journal_commit'))
        self.advance(10);reopened=self.open();self.assertTrue(reopened.prepare()['recovered'])
        self.assertEqual(len(self.calls),1);self.assertEqual(len(self.store.acquisitions_in_replay_order()),1)
        self.assertIsNone(reopened.poller.snapshot()['pending'])

    def test_acknowledged_response_is_not_repeated(self):
        self.advance(2)
        with self.assertRaises(RuntimeError):self.worker.tick(fault_hook=self.fail('after_ack'))
        self.advance(10);self.assertIsNone(self.open().prepare())
        self.assertEqual(len(self.calls),1)

    def test_uncertain_dispatch_is_retained_unknown_and_never_reissued(self):
        self.advance(2)
        with self.assertRaises(RuntimeError):self.worker.tick(fault_hook=self.fail('after_dispatch'))
        self.advance(12);reopened=self.open();self.assertEqual(reopened.prepare()['status'],'unresolved_dispatch')
        self.assertEqual(self.calls,[]);self.assertGreater(reopened.next.scheduled_at,self.now)
        self.assertEqual(reopened.poller.snapshot()['events'][-1]['kind'],'abandoned')

    def test_received_but_not_spooled_response_remains_unknown(self):
        self.advance(2)
        with self.assertRaises(RuntimeError):self.worker.tick(fault_hook=self.fail('after_response'))
        self.advance(12);self.assertEqual(self.open().prepare()['status'],'unresolved_dispatch')
        self.assertEqual(len(self.calls),1);self.assertFalse(self.store.acquisitions_in_replay_order())

    def test_quote_budget_does_not_reset_on_reopen(self):
        self.advance(2);self.worker.tick();self.advance(4);self.worker.tick()
        self.advance(6);reopened=self.open();reopened.prepare()
        self.assertEqual(reopened.tick()['status'],'budget_exhausted');self.assertEqual(len(self.calls),2)

    def test_unknown_dispatch_conservatively_consumes_budget(self):
        self.advance(2)
        with self.assertRaises(RuntimeError):self.worker.tick(fault_hook=self.fail('after_dispatch'))
        self.advance(3);reopened=self.open();reopened.prepare();self.advance(4);reopened.tick()
        self.advance(6);self.assertEqual(reopened.tick()['status'],'budget_exhausted');self.assertEqual(len(self.calls),1)

    def test_window_and_late_slot_do_not_catch_up(self):
        self.advance(9);self.assertEqual(self.worker.tick()['status'],'missed');self.assertFalse(self.calls)
        self.assertEqual(self.worker.next.scheduled_at,self.at+timedelta(seconds=12))
        self.advance(60);self.assertEqual(self.worker.tick()['status'],'window_ended')

    def test_missing_manifest_or_sidecar_blocks_instead_of_reset(self):
        self.worker.manifest.unlink()
        with self.assertRaises(ValueError):self.open().prepare()
        with self.assertRaises(ValueError):self.open().prepare(create=True)
        self.assertEqual(self.factories,0)

    def test_changed_binding_or_budget_cannot_adopt_saved_work(self):
        for settings in (replace(self.settings,max_quote_calls=3),replace(self.settings,publication_binding={'journal':self.binding['journal'],'contract':'other'})):
            with self.assertRaises(ValueError):self.open(settings).prepare()

    def test_changed_native_observation_is_detected_before_recovery_or_api(self):
        self.advance(2);self.worker.tick()
        with sqlite3.connect(self.store.database_path) as c:c.execute("UPDATE quote_observation SET status='invalid'")
        with self.assertRaises(ValueError):self.open().prepare()
        self.assertEqual(len(self.calls),1)

    def test_missing_sidecar_blocks_before_client_factory(self):
        self.worker.poller.path.unlink()
        with self.assertRaises(ValueError):self.open().prepare()
        self.assertEqual(self.factories,0)

    def test_roster_limit_does_not_send_an_oversized_provider_request(self):
        old=self.store.membership_revisions_in_effective_order()[-1]
        self.store.record_membership_revision(replace(old,published_at=None,revision=1,effective_at=self.at+timedelta(seconds=1),
            focus_symbols=('MSFT','SPY'),hot_symbols=('MSFT','SPY')))
        self.advance(2);self.assertEqual(self.worker.tick()['status'],'blocked')
        self.assertEqual(self.factories,0);self.assertFalse(self.calls)

    def test_native_audit_and_two_replays_match(self):
        self.advance(2);self.worker.tick();self.advance(4);self.worker.tick()
        self.assertTrue(audit_quote_journal(self.store.database_path,audited_at=self.now).passed)
        def replay():return [(e.event_id,str(e)) for e in QuoteJournalReplayReader(self.store.database_path).events()]
        self.assertEqual(replay(),replay())


class HotCollectorProcessTests(unittest.TestCase):
    setUp=HotRecoveryCollectorTests.setUp
    factory=HotRecoveryCollectorTests.factory
    open=HotRecoveryCollectorTests.open

    def wait(self,predicate,seconds=7):
        stop=time.monotonic()+seconds
        while time.monotonic()<stop:
            result=predicate()
            if result:return result
            time.sleep(.03)
        self.fail('Collector process did not reach bounded state')

    def start(self,stage=None,hang_quote_seconds=0):
        self.real_start=datetime.now(timezone.utc)
        self.log=self.root/'calls.jsonl'
        config={'settings':asdict(self.settings),'real_anchor_utc':self.real_start.isoformat(),
            'logical_anchor_utc':self.at.isoformat(),'call_log':str(self.log),'crash_stage':stage,
            'hang_quote_seconds':hang_quote_seconds}
        self.config=self.root/'collector-config.json';self.config.write_text(json.dumps(config))
        probe=Path(__file__).parent/'fixtures/recovery_collector_worker.py'
        self.managed=ManagedRecoveryWorker(self.root/'workers',role='experimental_hot',
            command=(sys.executable,'-I','-B',str(probe),str(self.config)),binding=self.binding,
            startup_seconds=1,stale_seconds=3)
        self.addCleanup(self.managed.stop_owned)
        return self.managed.ensure(start_allowed=True,resume_after_utc=self.at.isoformat())

    def now_logical(self):return self.at+(datetime.now(timezone.utc)-self.real_start)

    def test_owned_native_worker_collects_and_cooperative_stop_preserves_evidence(self):
        started=self.start()
        self.wait(lambda:self.log.exists())
        self.managed.stop_owned()
        self.assertIsNone(self.managed.child)
        self.assertEqual(self.managed.last_exit['pid'],started['pid'])
        self.assertGreaterEqual(len(self.store.acquisitions_in_replay_order()),1)
        self.assertTrue(self.log.read_text().strip())

    def recovery_case(self,stage):
        first=self.start(stage)
        self.wait(lambda:self.managed.child.poll() is not None)
        self.assertEqual(self.managed.child.returncode,77)
        count=len(self.log.read_text().splitlines()) if self.log.exists() else 0
        later=self.now_logical()
        second=self.managed.ensure(start_allowed=True,resume_after_utc=later.isoformat())
        self.assertNotEqual(first['pid'],second['pid'])
        beat=self.wait(lambda:self.managed._heartbeat(self.managed._job()))
        self.managed.stop_owned()
        self.assertEqual(len(self.log.read_text().splitlines()) if self.log.exists() else 0,count)
        self.assertGreater(datetime.fromisoformat(self.managed._job()['first_eligible_slot_utc']),later)
        return beat

    def test_actual_process_exit_after_spooling_recovers_with_no_repeat_provider_call(self):
        beat=self.recovery_case('after_assembled')
        self.assertTrue(beat['recovery']['recovered'])
        self.assertEqual(len(self.store.acquisitions_in_replay_order()),1)

    def test_actual_process_exit_after_commit_recovers_the_same_acquisition(self):
        beat=self.recovery_case('after_journal_commit')
        self.assertTrue(beat['recovery']['recovered'])
        self.assertEqual(len(self.store.acquisitions_in_replay_order()),1)

    def test_actual_process_exit_after_dispatch_never_reissues_unknown_request(self):
        beat=self.recovery_case('after_dispatch')
        self.assertEqual(beat['recovery']['status'],'unresolved_dispatch')
        self.assertFalse(self.store.acquisitions_in_replay_order())

    def test_changed_job_fence_stops_native_worker_before_provider_creation(self):
        self.start()
        self.wait(lambda:self.managed._heartbeat(self.managed._job()))
        self.managed.registry.write_text('{}')
        self.wait(lambda:self.managed.child.poll() is not None)
        self.assertFalse(self.log.exists())

    def test_hung_provider_is_stopped_by_exact_handle_and_dispatch_recovers_unknown(self):
        self.start(hang_quote_seconds=20)
        self.wait(lambda:self.log.exists())
        time.sleep(3.1)
        result=self.managed.ensure(start_allowed=True,resume_after_utc=self.now_logical().isoformat())
        self.assertEqual(result['status'],'RESTART_WAIT')
        self.assertIsNone(self.managed.child)
        later=self.now_logical()
        self.managed.ensure(start_allowed=True,resume_after_utc=later.isoformat())
        beat=self.wait(lambda:self.managed._heartbeat(self.managed._job()))
        self.managed.stop_owned()
        self.assertEqual(beat['recovery']['status'],'unresolved_dispatch')
        self.assertEqual(len(self.log.read_text().splitlines()),1)


class CoordinatorCollectorIntegrationTests(unittest.TestCase):
    def test_recovered_halt_native_publication_supervised_native_collector(self):
        import test_nasdaq_recovery_delivery as delivery_fixtures
        from test_nasdaq_recovery_supervisor import ScriptedClient
        from test_nasdaq_feed_recovery import EMPTY, rss
        from mb_watchlist_coordinator.nasdaq_feed_recovery import FeedRecoveryTransport
        from mb_watchlist_coordinator.nasdaq_recovery_supervisor import NasdaqRecoverySupervisor
        from mb_watchlist_coordinator.sampling_service import SamplingPublicationService, PublicationSettings
        from mb_watchlist_coordinator.sampling_journal import SamplingJournal
        case=delivery_fixtures.RecoveryDeliveryTests('runTest');case.setUp();self.addCleanup(case.doCleanups)
        at,day=delivery_fixtures.AT,delivery_fixtures.DAY
        store=QuoteObservationStore(case.root/'quotes.sqlite3',session_date=day,schema_version=2);store.initialize()
        store.record_membership_revision(SamplingHierarchyRevision(session_date=day,revision=0,effective_at=at,
            uni_symbols=tuple(sorted(case.baseline.uni)),focus_symbols=tuple(sorted(case.baseline.focus)),hot_symbols=(),
            source='synthetic-feed-to-native-collector',metadata={MARKER:True,'experimental':True}))
        service=SamplingPublicationService(case.root/'publication.sqlite3',request_store=case.requests,
            journal=SamplingJournal(store),settings=PublicationSettings('synthetic',1,.1,at.replace(hour=16)),clock=lambda:case.now);service.initialize()
        feed=FeedRecoveryTransport(case.root/'feed.sqlite3',session_date=day,queries=(case.query,),clock=lambda:case.now);feed.initialize(create=True)
        client=ScriptedClient(feed);client.responses=[EMPTY,rss(day,'NVDA'),EMPTY]
        supervisor=NasdaqRecoverySupervisor(case.root/'recovery-first.sqlite3',feed_client=client,delivery=case.delivery,service=service,clock=lambda:case.now);supervisor.initialize(create=True)
        for _ in range(3):supervisor.cycle();case.now+=timedelta(seconds=60)
        service.cycle()
        self.assertEqual(store.latest_membership_revision_effective_at(case.now).hot_symbols,('NVDA',))
        settings=HotCollectorSettings(str(store.database_path),dict(service.identity),case.now.isoformat(),
            (case.now+timedelta(seconds=15)).isoformat(),max_quote_calls=1,max_symbols=1)
        prepared=HotRecoveryCollector(settings,client_factory=lambda:None,clock=lambda:case.now);prepared.prepare(create=True)
        config=case.root/'collector.json';log=case.root/'calls.jsonl'
        # Serialization detaches the immutable publication binding.
        from mb_watchlist_coordinator.sampling_requests import plain
        config.write_text(json.dumps({'settings':{'journal_path':settings.journal_path,'publication_binding':plain(settings.publication_binding),
            'start_at_utc':settings.start_at_utc,'stop_at_utc':settings.stop_at_utc,'max_quote_calls':1,'max_symbols':1},
            'real_anchor_utc':datetime.now(timezone.utc).isoformat(),'logical_anchor_utc':case.now.isoformat(),'call_log':str(log)}))
        worker=ManagedRecoveryWorker(case.root/'workers',role='experimental_hot',command=(sys.executable,'-I','-B',str(Path(__file__).parent/'fixtures/recovery_collector_worker.py'),str(config)),binding=plain(service.identity),startup_seconds=1,stale_seconds=3)
        self.addCleanup(worker.stop_owned)
        supervised=NasdaqRecoverySupervisor(case.root/'recovery-with-collector.sqlite3',feed_client=client,delivery=case.delivery,service=service,worker=worker,clock=lambda:case.now);supervised.initialize(create=True)
        first=supervised.cycle();self.assertEqual(first['worker']['status'],'STARTING')
        deadline=time.monotonic()+7
        while time.monotonic()<deadline:
            if store.acquisitions_in_replay_order():break
            time.sleep(.03)
        worker.stop_owned()
        self.assertEqual(json.loads(log.read_text().splitlines()[0])['symbols'],['NVDA'])
        self.assertEqual(len(store.acquisitions_in_replay_order()),1)
        self.assertTrue(audit_quote_journal(store.database_path,audited_at=case.now+timedelta(seconds=2)).passed)
        def replay():return [(e.event_id,str(e)) for e in QuoteJournalReplayReader(store.database_path).events()]
        self.assertEqual(replay(),replay())
