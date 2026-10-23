from contextlib import closing
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from test_nasdaq_feed_recovery import EMPTY, HTML, rss
import test_nasdaq_recovery_delivery as delivery_fixtures
from mb_watchlist_coordinator.nasdaq_feed_recovery import FeedRecoveryTransport, query_url
from mb_watchlist_coordinator.nasdaq_recovery_supervisor import NasdaqRecoverySupervisor
from mb_watchlist_coordinator.recovery_workers import ManagedRecoveryWorker, next_future_slot, atomic_json
from mb_watchlist_coordinator.sampling_requests import canonical, digest, plain
from mb_watchlist_coordinator.sampling_service import owner_lock, SamplingPublicationService, PublicationSettings
from mb_watchlist_coordinator.sampling_journal import SamplingJournal
from mb_market_data.quote_observation_store import QuoteObservationStore
from mb_market_data.sampling_membership import SamplingHierarchyRevision
from mb_market_data.quote_journal_audit import audit_quote_journal
from mb_market_data.quote_journal_replay import QuoteJournalReplayReader

PROBE=Path(__file__).parent/'fixtures/recovery_probe_worker.py'
AT, DAY = delivery_fixtures.AT, delivery_fixtures.DAY


class ScriptedClient:
    def __init__(self,transport):self.transport=transport;self.responses=[]
    def attempt(self,query=None,**kw):
        r=self.transport.reserve(query,synthetic=True)
        if r is None:return {'status':'waiting'}
        raw=self.responses.pop(0) if self.responses else EMPTY
        self.transport.progress(r,{'status_code':200,'final_url':query_url(query),
            'headers':{},'body_complete':True},raw)
        self.transport.finish(r)
        return {'status':'completed'}


def wait_for(fn, *, seconds=4):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        value=fn()
        if value:return value
        time.sleep(.03)
    raise AssertionError('Owned process did not reach expected bounded state')


class ManagedWorkerTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name);self.workers=[]
        self.addCleanup(lambda:[w.stop_owned() for w in self.workers])

    def worker(self,**kw):
        args=dict(role='experimental_hot',command=(sys.executable,'-I','-B',str(PROBE)),binding={'synthetic_only':True},startup_seconds=.5,stale_seconds=.5)
        args.update(kw);w=ManagedRecoveryWorker(self.root,**args);self.workers.append(w);return w

    def test_healthy_worker_is_not_duplicated_and_stop_affects_its_exact_handle(self):
        w=self.worker();now=datetime.now(timezone.utc).isoformat()
        first=w.ensure(start_allowed=True,resume_after_utc=now)
        ready=wait_for(lambda:(v if (v:=w.ensure(start_allowed=True,resume_after_utc=now))['status']=='RUNNING' else None))
        self.assertEqual(first['pid'],ready['pid'])
        self.assertEqual(w._job()['generation'],1)
        self.assertEqual(w._job()['resume_after_utc'],now)
        self.assertTrue(w._job()['no_past_slot_catchup'])
        self.assertGreater(datetime.fromisoformat(w._job()['first_eligible_slot_utc']),datetime.fromisoformat(now))
        self.assertEqual(w.stop_owned()['status'],'OWNED_WORKER_STOPPED')

    def test_dead_owned_worker_restarts_only_at_current_future_boundary(self):
        w=self.worker();now=datetime.now(timezone.utc).isoformat()
        w.ensure(start_allowed=True,resume_after_utc=now)
        wait_for(lambda:w._heartbeat(w._job()))
        child=w.child;child.terminate();child.wait(timeout=2)
        time.sleep(.5)
        later=(datetime.now(timezone.utc)+timedelta(seconds=2)).isoformat()
        result=w.ensure(start_allowed=True,resume_after_utc=later)
        self.assertEqual(result['generation'],2)
        self.assertNotEqual(result['pid'],child.pid)
        self.assertEqual(w._job()['resume_after_utc'],later)

    def test_reopened_controller_observes_healthy_prior_worker_without_start_or_kill(self):
        w=self.worker();now=datetime.now(timezone.utc).isoformat();w.ensure(start_allowed=True,resume_after_utc=now)
        wait_for(lambda:w._heartbeat(w._job()))
        reopened=self.worker()
        self.assertEqual(reopened.ensure(start_allowed=True,resume_after_utc=now)['status'],'EXTERNAL_HEALTHY')
        self.assertIsNone(reopened.child)
        reopened.stop_owned();self.assertIsNone(w.child.poll())

    def test_unresponsive_owned_worker_is_stopped_with_bounded_restart_budget(self):
        w=self.worker(command=(sys.executable,'-I','-B',str(PROBE),'--hang'))
        w.ensure(start_allowed=True,resume_after_utc=datetime.now(timezone.utc).isoformat())
        time.sleep(.6)
        self.assertEqual(w.ensure(start_allowed=True,resume_after_utc=datetime.now(timezone.utc).isoformat())['status'],'RESTART_WAIT')
        self.assertIsNone(w.child)

    def test_foreign_lease_without_valid_heartbeat_is_not_killed_or_duplicated(self):
        w=self.worker()
        with owner_lock(w.lease):
            result=w.ensure(start_allowed=True,resume_after_utc=datetime.now(timezone.utc).isoformat())
            self.assertEqual(result['status'],'BLOCKED');self.assertIsNone(w.child)

    def test_production_roles_and_changed_registry_are_refused(self):
        with self.assertRaises(ValueError):self.worker(role='uni')
        with self.assertRaises(ValueError):self.worker(role='focus')
        w=self.worker();w.ensure(start_allowed=True,resume_after_utc=datetime.now(timezone.utc).isoformat())
        job=json.loads(w.registry.read_text());job['identity']['binding']={'other':True};job.pop('content_sha256');job['content_sha256']=digest(job);w.registry.write_text(canonical(job))
        with self.assertRaises(ValueError):w.ensure(start_allowed=True,resume_after_utc=datetime.now(timezone.utc).isoformat())
        # Restore registry so exact owned-handle cleanup remains cooperative.
        job['identity']=w.identity;job.pop('content_sha256');job['content_sha256']=digest(job);w.registry.write_text(canonical(job))

    def test_restart_budget_survives_controller_reopen(self):
        w=self.worker(max_starts=1)
        w.ensure(start_allowed=True,resume_after_utc=datetime.now(timezone.utc).isoformat())
        wait_for(lambda:w._heartbeat(w._job()));w.stop_owned();time.sleep(.5)
        reopened=self.worker(max_starts=1)
        result=reopened.ensure(start_allowed=True,resume_after_utc=datetime.now(timezone.utc).isoformat())
        self.assertEqual(result['status'],'BLOCKED')
        self.assertEqual(result['reason'],'worker_restart_budget_exhausted')

    def test_future_slot_gate_skips_exact_slots_and_reserved_seconds(self):
        at=AT.replace(second=58,microsecond=0)
        self.assertEqual(next_future_slot(at),at.replace(second=0)+timedelta(minutes=1,seconds=2))
        self.assertEqual(next_future_slot(AT.replace(second=8)),AT.replace(second=12))

    def test_missing_registry_is_not_a_fresh_owner_or_restart_budget(self):
        w=self.worker();w.ensure(start_allowed=True,resume_after_utc=datetime.now(timezone.utc).isoformat())
        wait_for(lambda:w._heartbeat(w._job()));w.registry.unlink()
        reopened=self.worker()
        with self.assertRaises(FileNotFoundError):reopened.ensure(start_allowed=True,resume_after_utc=datetime.now(timezone.utc).isoformat())
        self.assertIsNone(reopened.child)

    def test_transient_windows_heartbeat_replacement_keeps_same_owned_worker(self):
        w=self.worker(command=(sys.executable,'-I','-B',str(PROBE),'--sharing-race'))
        first=w.ensure(start_allowed=True,resume_after_utc=datetime.now(timezone.utc).isoformat())
        ready=wait_for(lambda:(v if (v:=w.ensure(start_allowed=True,resume_after_utc=datetime.now(timezone.utc).isoformat()))['status']=='RUNNING' else None))
        self.assertEqual(ready['pid'],first['pid']);self.assertEqual(w._job()['generation'],1)
        self.assertIsNone(w.last_exit)

    def test_owned_worker_failure_retains_bounded_stderr_and_exit_status(self):
        w=self.worker(command=(sys.executable,'-I','-B',str(PROBE),'--fail-stderr'))
        w.ensure(start_allowed=True,resume_after_utc=datetime.now(timezone.utc).isoformat())
        wait_for(lambda:w.child.poll() is not None)
        report=w.ensure(start_allowed=False,resume_after_utc=datetime.now(timezone.utc).isoformat())
        evidence=report['previous_worker_exit']
        self.assertEqual(evidence['returncode'],9)
        self.assertIn('synthetic worker failure',evidence['stderr_tail'])
        self.assertEqual(len(evidence['stderr_tail'].encode()),8192)
        self.assertEqual(json.loads((w.root/(w.owned_token+'.exit.json')).read_text()),evidence)
        self.assertIsNone(w.child)


class AtomicWorkerRecordTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.path=Path(temp.name)/'heartbeat.json';atomic_json(self.path,{'old':True})

    def error(self, code):
        error=PermissionError('injected Windows sharing conflict');error.winerror=code
        return error

    def test_windows_sharing_conflicts_retry_same_complete_temporary_value(self):
        replace=os.replace
        for code in (5,32,33):
            with self.subTest(winerror=code):
                seen=[]
                def once(source,target):
                    seen.append(Path(source))
                    if len(seen)==1:
                        self.assertEqual(json.loads(self.path.read_text()),{'old':True})
                        raise self.error(code)
                    replace(source,target)
                with patch('mb_watchlist_coordinator.recovery_workers.os.replace',side_effect=once):
                    atomic_json(self.path,{'new':True},sleep=lambda _:None)
                self.assertEqual(seen[0],seen[1])
                self.assertEqual(json.loads(self.path.read_text()),{'new':True})
                atomic_json(self.path,{'old':True})
        self.assertFalse(list(self.path.parent.glob('*.tmp')))

    def test_persistent_windows_conflict_is_bounded_and_keeps_previous_record(self):
        elapsed=[0.0]
        def sleep(seconds):elapsed[0]+=seconds
        with patch('mb_watchlist_coordinator.recovery_workers.os.replace',side_effect=self.error(32)) as replace:
            with self.assertRaises(PermissionError):
                atomic_json(self.path,{'new':True},monotonic=lambda:elapsed[0],sleep=sleep)
        self.assertLessEqual(replace.call_count,26);self.assertLessEqual(elapsed[0],.25)
        self.assertEqual(json.loads(self.path.read_text()),{'old':True})
        self.assertFalse(list(self.path.parent.glob('*.tmp')))

    def test_unrelated_error_has_no_retry(self):
        for error in (PermissionError('ordinary permission denied'),self.error(87)):
            with self.subTest(error=str(error)):
                with patch('mb_watchlist_coordinator.recovery_workers.os.replace',side_effect=error) as replace:
                    with self.assertRaises(PermissionError):atomic_json(self.path,{'new':True})
                self.assertEqual(replace.call_count,1)

    @unittest.skipUnless(os.name=='nt','Actual Windows file sharing requires Windows')
    def test_native_windows_reader_releases_replacement_before_retry_deadline(self):
        handle=self.path.open('rb')
        release=threading.Timer(.05,handle.close);release.start()
        try:
            atomic_json(self.path,{'new':True})
            self.assertEqual(json.loads(self.path.read_text()),{'new':True})
        finally:
            release.join();handle.close()


class RecoverySupervisorTests(unittest.TestCase):
    def setUp(self):
        self.case=delivery_fixtures.RecoveryDeliveryTests('runTest');self.case.setUp();self.addCleanup(self.case.doCleanups)
        self.root=self.case.root
        self.native=QuoteObservationStore(self.root/'membership.sqlite3',session_date=DAY,schema_version=2)
        self.native.initialize();self.native.record_membership_revision(SamplingHierarchyRevision(session_date=DAY,
            revision=0,effective_at=AT.replace(hour=9,minute=30),uni_symbols=tuple(self.case.baseline.uni),
            focus_symbols=tuple(self.case.baseline.focus),hot_symbols=(),source='synthetic-start'))
        self.service=SamplingPublicationService(self.root/'publication.sqlite3',request_store=self.case.requests,
            journal=SamplingJournal(self.native),settings=PublicationSettings('synthetic-recovery',1,.1,AT.replace(hour=16)),clock=lambda:self.case.now)
        self.service.initialize()
        self.feed=FeedRecoveryTransport(self.root/'feed.sqlite3',session_date=DAY,queries=(self.case.query,),clock=lambda:self.case.now)
        self.feed.initialize(create=True);self.client=ScriptedClient(self.feed)
        self.worker=ManagedRecoveryWorker(self.root/'workers',role='experimental_hot',
            command=(sys.executable,'-I','-B',str(PROBE)),binding=plain(self.service.identity),startup_seconds=.7,stale_seconds=2)
        self.addCleanup(self.worker.stop_owned)
        self.supervisor=self.open();self.supervisor.initialize(create=True)

    def open(self,**kw):
        args=dict(feed_client=self.client,delivery=self.case.delivery,service=self.service,worker=self.worker,clock=lambda:self.case.now)
        args.update(kw);return NasdaqRecoverySupervisor(self.root/'supervisor.sqlite3',**args)

    def advance(self,seconds=60):self.case.now+=timedelta(seconds=seconds)

    def recover(self, raw=None):
        self.client.responses=[EMPTY,raw or rss(DAY,'NVDA'),EMPTY]
        first=self.supervisor.cycle();self.advance()
        second=self.supervisor.cycle();self.advance()
        third=self.supervisor.cycle()
        wait_for(lambda:self.worker._heartbeat(self.worker._job()))
        return self.supervisor.cycle()

    def test_end_to_end_scope_reconciliation_publication_and_owned_worker_ready_with_gaps(self):
        report=self.recover()
        self.assertEqual(report['status'],'READY_WITH_GAPS')
        self.assertTrue(report['local_membership_effective'])
        self.assertTrue(report['discovery_scope_reconciled'])
        self.assertEqual(self.case.requests.states()[-1].applied.hot,{'NVDA'})
        self.assertIn('intermediate_feed_mutations_not_reconstructible',report['reasons'])
        self.assertEqual(report['unmanaged_channels_untouched'],['uni','focus'])
        self.assertTrue(audit_quote_journal(self.native.database_path).passed)
        def replay():return [(e.event_id,e.revision.content_sha256) for e in QuoteJournalReplayReader(self.native.database_path).events()]
        self.assertEqual(replay(),replay())

    def test_current_baseline_then_dated_query_then_current_cutover_before_readiness(self):
        self.client.responses=[EMPTY,rss(DAY,'NVDA'),EMPTY]
        self.assertEqual(self.supervisor.cycle()['status'],'RECOVERING')
        self.assertEqual(self.feed.snapshot()['attempts'][-1]['query_id'],'CURRENT')
        self.advance();second=self.supervisor.cycle()
        self.assertEqual(self.feed.snapshot()['attempts'][-1]['query_id'],self.case.query.query_id)
        self.assertFalse(second['discovery_scope_reconciled'])
        self.assertIn('post_recovery_current_cutover_pending',second['reasons'])
        self.assertGreaterEqual(self.native.membership_revisions_in_effective_order()[-1].effective_at,AT+timedelta(seconds=60))
        self.advance();self.supervisor.cycle()
        self.assertEqual(self.feed.snapshot()['attempts'][-1]['query_id'],'CURRENT')

    def test_failed_feed_does_not_erase_saved_valid_demand_or_stop_healthy_worker(self):
        self.recover();pid=self.worker.child.pid;original=self.case.requests.states()[-1].applied
        self.advance();self.client.responses=[HTML]
        report=self.supervisor.cycle()
        self.assertEqual(report['status'],'INCOMPLETE')
        self.assertEqual(self.case.requests.states()[-1].applied,original)
        self.assertIsNotNone(self.worker.child,report)
        self.assertEqual(self.worker.child.pid,pid,report);self.assertIsNone(self.worker.child.poll())

    def test_source_commit_before_ingestion_ack_retries_without_duplicate_receipt(self):
        def fault(stage):
            if stage=='after_source_receipt':raise RuntimeError('crash before transport/source ACK')
        with self.assertRaises(RuntimeError):self.supervisor.cycle(fault_hook=fault)
        self.assertEqual(len(self.case.live.snapshot()['receipts']),1)
        self.open().cycle()
        self.assertEqual(len(self.case.live.snapshot()['receipts']),1)
        self.assertEqual(len(self.supervisor.snapshot()['ingested_attempt_ids']),1)

    def test_publication_commit_before_ack_recovers_same_revision(self):
        self.client.responses=[EMPTY,rss(DAY,'NVDA')];self.supervisor.cycle();self.advance()
        def fault(stage):
            if stage=='after_commit':raise RuntimeError('native committed before publication ACK')
        with self.assertRaises(RuntimeError):self.supervisor.cycle(service_fault_hook=fault)
        original=self.native.membership_revisions_in_effective_order()[-1]
        self.advance(1);self.open().cycle()
        self.assertEqual(self.native.membership_revisions_in_effective_order()[-1],original)
        self.assertIsNone(self.service.snapshot()['pending'])

    def test_valid_empty_dated_scope_does_not_claim_full_trace(self):
        report=self.recover(raw=EMPTY)
        self.assertEqual(report['status'],'READY_WITH_GAPS',report)
        self.assertFalse(self.case.requests.states()[-1].applied.hot)
        self.assertIn('older_unknown_carryovers_not_proven_complete',report['reasons'])

    def test_unknown_reason_candidates_are_retained_in_readiness_report(self):
        report=self.recover(raw=rss(DAY,'NVDA',reason='T3'))
        self.assertEqual(len(report['unresolved_candidates']),1)
        self.assertIn('unresolved_original_reason_candidates',report['reasons'])
        self.assertFalse(self.case.requests.states()[-1].applied.hot)

    def test_ordinary_catalog_rejection_is_not_overridden_by_recovery(self):
        report=self.recover(raw=rss(DAY,'UNKNOWN'))
        self.assertTrue(report['rejected_requests'])
        self.assertFalse(self.case.requests.states()[-1].applied.hot)

    def test_new_halt_between_dated_query_and_current_cutover_is_live_discovery(self):
        self.client.responses=[EMPTY,rss(DAY,'NVDA')]
        self.supervisor.cycle();self.advance();self.supervisor.cycle();self.advance()
        self.client.responses=[rss(DAY,'MSFT',halt='12:01:30')]
        self.supervisor.cycle()
        self.assertEqual(self.case.requests.states()[-1].applied.hot,{'NVDA','MSFT'})
        self.assertTrue(any(c['command']['metadata']['source_kind']=='live' for c in self.case.delivery.snapshot()['commands'].values()))

    def test_second_owner_does_not_write_or_start_duplicate_worker(self):
        before=self.supervisor.path.read_bytes()
        with owner_lock(self.supervisor.path.with_suffix('.owner.lock')):
            report=self.open().cycle()
        self.assertEqual(report['status'],'BLOCKED');self.assertFalse(report['status_persisted'])
        self.assertEqual(self.supervisor.path.read_bytes(),before);self.assertIsNone(self.worker.child)

    def test_corrupt_request_blocks_new_publication_before_worker_start(self):
        original=self.native.database_path.read_bytes()
        with closing(sqlite3.connect(self.case.requests.path)) as c,c:c.execute("UPDATE request_identity SET payload='{}'")
        self.assertEqual(self.supervisor.cycle()['status'],'BLOCKED')
        self.assertEqual(self.native.database_path.read_bytes(),original);self.assertIsNone(self.worker.child)

    def test_missing_and_corrupted_supervisor_ledger_are_not_reset(self):
        self.supervisor.path.unlink()
        with self.assertRaises(FileNotFoundError):self.open().initialize()
        self.assertFalse(self.supervisor.path.exists())

    def test_rehashed_source_prefix_after_warm_read_is_blocked(self):
        self.supervisor.cycle()
        with closing(sqlite3.connect(self.case.live.path)) as c,c:
            e=json.loads(c.execute('SELECT payload FROM halt_receipt').fetchone()[0])
            e['snapshot']['provenance']['changed']=True;e.pop('event_sha256');e['event_sha256']=digest(e)
            c.execute('UPDATE halt_receipt SET payload=?',(canonical(e),))
        self.assertEqual(self.open().cycle()['status'],'BLOCKED')

    def test_rehashed_transport_diagnostics_cannot_change_an_ingested_prefix(self):
        self.supervisor.cycle()
        with closing(sqlite3.connect(self.feed.path)) as c,c:
            rows=list(c.execute('SELECT sequence,payload FROM feed_event ORDER BY sequence'))
            previous=None
            for n,raw in rows:
                e=json.loads(raw)
                if previous is not None:e['previous_sha256']=previous
                if e['kind']=='progress':e['metadata']['headers']['Content-Type']='application/xml'
                e.pop('event_sha256');e['event_sha256']=digest(e);previous=e['event_sha256']
                c.execute('UPDATE feed_event SET payload=? WHERE sequence=?',(canonical(e),n))
        self.assertEqual(self.open().cycle()['status'],'BLOCKED')

    def test_stop_and_session_close_do_not_start_workers_or_backfill_slots(self):
        self.assertEqual(self.supervisor.cycle(stop_requested=lambda:True)['status'],'INCOMPLETE')
        self.assertIsNone(self.worker.child)
        self.case.now=AT.replace(hour=16)
        report=self.supervisor.cycle()
        self.assertEqual(report['status'],'INCOMPLETE')
        self.assertIn('outside_target_regular_session',report['reasons'])

    def test_session_ends_during_feed_attempt_retains_evidence_without_source_admission(self):
        original=self.client.attempt
        def close_during_fetch(*a,**kw):
            result=original(*a,**kw);self.case.now=AT.replace(hour=16);return result
        self.client.attempt=close_during_fetch
        report=self.supervisor.cycle()
        self.assertEqual(report['status'],'INCOMPLETE')
        self.assertIn('session_ended_during_feed_attempt',report['reasons'])
        self.assertTrue(self.feed.snapshot()['attempts'])
        self.assertFalse(self.case.live.snapshot()['receipts'])

    def test_status_write_failure_does_not_lose_committed_source_or_reset_ledgers(self):
        original=self.supervisor._append
        def disk_failure(*a,**kw):raise OSError('injected status disk failure')
        self.supervisor._append=disk_failure
        report=self.supervisor.cycle()
        self.assertEqual(report['status'],'BLOCKED');self.assertFalse(report['status_persisted'])
        self.assertEqual(len(self.case.live.snapshot()['receipts']),1)
        self.supervisor._append=original;self.supervisor.cycle()
        self.assertEqual(len(self.case.live.snapshot()['receipts']),1)

    def test_other_live_processes_remain_running_after_recovery_and_owned_stop(self):
        children=[subprocess.Popen([sys.executable,'-I','-B','-c','import time; time.sleep(30)'],
            stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL) for _ in ('uni','focus')]
        try:
            self.recover();self.supervisor.cycle(stop_requested=lambda:True)
            self.assertTrue(all(child.poll() is None for child in children))
        finally:
            for child in children:
                if child.poll() is None:child.terminate()
                child.wait(timeout=3)

    def test_five_and_thirty_minute_outages_use_explicit_new_bounded_window(self):
        self.recover();old_pid=self.worker.child.pid
        for number,seconds in enumerate((300,1800),1):
            self.advance(seconds)
            feed=FeedRecoveryTransport(self.root/f'feed-window-{number}.sqlite3',session_date=DAY,
                queries=(self.case.query,),clock=lambda:self.case.now);feed.initialize(create=True)
            client=ScriptedClient(feed)
            halt=(self.case.now-timedelta(seconds=1)).strftime('%H:%M:%S')
            client.responses=[EMPTY,rss(DAY,'MSFT',halt=halt),EMPTY]
            supervisor=NasdaqRecoverySupervisor(self.root/f'supervisor-window-{number}.sqlite3',
                feed_client=client,delivery=self.case.delivery,service=self.service,worker=self.worker,clock=lambda:self.case.now)
            supervisor.initialize(create=True);supervisor.cycle();self.advance()
            supervisor.cycle();self.advance();report=supervisor.cycle()
            self.assertTrue(report['discovery_scope_reconciled'])
            self.assertEqual(len(feed.snapshot()['attempts']),3)
            self.assertIsNotNone(self.worker.child,report)
            self.assertEqual(self.worker.child.pid,old_pid,report)
        self.assertEqual(self.case.requests.states()[-1].applied.hot,{'NVDA','MSFT'})

    def test_prior_query_completion_cannot_satisfy_new_window_or_early_recovery_delivery(self):
        self.case.recover([self.case.row()])
        self.client.responses=[EMPTY,rss(DAY,'NVDA'),EMPTY]
        self.supervisor.cycle()
        self.assertFalse(self.case.delivery.snapshot()['commands'])
        self.advance();self.supervisor.cycle()
        self.assertEqual(self.case.requests.states()[-1].applied.hot,{'NVDA','MSFT'})

    def test_bounded_loop_stops_only_owned_worker_and_returns_a_persisted_disposition(self):
        report=self.supervisor.run(stop_requested=lambda:False,max_seconds=.2,synthetic={})
        self.assertEqual(report['status'],'INCOMPLETE')
        self.assertIn('supervisor_deadline_ended',report['reasons'])
        self.assertIsNone(self.worker.child)

    def test_http_step_is_nonblocking_and_native_timer_checks_continue(self):
        from mb_watchlist_coordinator.nasdaq_feed_recovery import BoundedFeedClient
        class StepClient(ScriptedClient):
            def step(self,*a,**kw):return {'status':'acquiring'}
            def attempt(self,*a,**kw):raise AssertionError('Blocking HTTP method must not be used')
        client=StepClient(self.feed)
        supervisor=self.open(feed_client=client)
        before=time.monotonic();report=supervisor.cycle()
        self.assertLess(time.monotonic()-before,1)
        self.assertEqual(report['status'],'RECOVERING')
        self.assertTrue(self.case.requests.events())  # Native current timers were replayed.

    def test_loop_retries_recoverable_gaps_until_the_existing_failure_limit(self):
        self.client.responses=[HTML,HTML,HTML]
        original=self.client.attempt
        def paced_logical_attempt(*a,**kw):
            self.advance();return original(*a,**kw)
        self.client.attempt=paced_logical_attempt
        report=self.supervisor.run(stop_requested=lambda:False,max_seconds=2,synthetic={})
        self.assertEqual(len(self.feed.snapshot()['attempts']),3)
        self.assertEqual(report['status'],'INCOMPLETE')
        self.assertTrue(report['feed_stop_required'])

    def test_real_owned_http_child_does_not_block_native_request_expiry(self):
        from mb_watchlist_coordinator.nasdaq_feed_recovery import BoundedFeedClient
        from mb_watchlist_coordinator.models import ProducerIntent, IntentType
        request=ProducerIntent('short-manual','manual',IntentType.ENSURE_PRESENT,frozenset({'MSFT'}),self.case.now,
            expires_at=self.case.now+timedelta(seconds=2),metadata={'sampling_channel':'hot','session_date':DAY.isoformat()})
        self.case.requests.submit_request(request,actor_id='manual')
        client=BoundedFeedClient(self.feed);self.addCleanup(client.close_owned)
        supervisor=self.open(feed_client=client)
        before=time.monotonic();supervisor.cycle(synthetic={'hang_before_headers':True})
        self.assertLess(time.monotonic()-before,1)
        self.assertTrue(client.owns_attempt)
        self.advance(3)
        supervisor.cycle(synthetic={'hang_before_headers':True})
        self.assertFalse(self.case.requests.states()[-1].applied.hot)
        self.assertEqual(self.native.membership_revisions_in_effective_order()[-1].hot_symbols,())


if __name__=='__main__':unittest.main()
