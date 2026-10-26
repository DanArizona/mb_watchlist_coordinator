"""First-slot readiness, unchanged catalog bytes and prompt profile decisions."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sqlite3
from types import SimpleNamespace
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from mb_watchlist_coordinator.integrated_catalog import DirectoryCatalog, CatalogError
from mb_watchlist_coordinator.profile_runtime import BoundProfile
from mb_watchlist_coordinator.sampling_requests import utc_text, digest
from mb_watchlist_coordinator.recovery_workers import next_future_slot
from test_integrated_catalog import catalog, sources, receipts


class ExactCatalogValidationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.saved = catalog().persist(self.root/'catalog')

    def test_every_validation_reads_all_original_bytes_without_reparsing_rows(self):
        reads = []; read = Path.read_bytes
        def observed(path):
            reads.append(path.name)
            return read(path)
        with patch('mb_watchlist_coordinator.integrated_catalog._rows', side_effect=AssertionError('Repeated parsing')), patch.object(Path, 'read_bytes', observed):
            for _ in range(3):
                value = self.saved.validate()
                self.assertEqual(value.catalog_id, self.saved.catalog_id)
                self.assertEqual(value.symbols, self.saved.symbols)
        self.assertEqual(sorted(reads), sorted(['catalog.json','nasdaq.txt','other.txt']*3))

    def test_same_size_changes_with_restored_timestamps_are_rejected_for_all_files(self):
        for name in ('catalog.json','nasdaq.txt','other.txt'):
            with self.subTest(name=name):
                path = self.saved.path/name; raw = path.read_bytes(); stat = path.stat()
                altered = bytes([raw[0] ^ 1])+raw[1:]
                try:
                    path.write_bytes(altered)
                    os.utime(path, ns=(stat.st_atime_ns,stat.st_mtime_ns))
                    with self.assertRaises(CatalogError): self.saved.validate()
                finally:
                    path.write_bytes(raw)
                self.saved.validate()

    def test_changed_memory_or_directory_alias_cannot_reuse_parsed_facts(self):
        for field, replacement in (('catalog_id','changed'),('symbols',('FAKE',)),
                ('public',dict(self.saved.public)),('receipts',dict(self.saved.receipts)),
                ('bodies',{}),('path',self.root/'other')):
            with self.subTest(field=field):
                original = getattr(self.saved,field)
                try:
                    setattr(self.saved,field,replacement)
                    with self.assertRaises(CatalogError): self.saved.validate()
                finally: setattr(self.saved,field,original)

    def test_missing_or_extra_artifacts_are_rejected(self):
        extra = self.saved.path/'unreviewed.txt'; extra.write_bytes(b'extra')
        with self.assertRaises(CatalogError): self.saved.validate()
        extra.unlink(); path = self.saved.path/'other.txt'; raw=path.read_bytes(); path.unlink()
        with self.assertRaises(CatalogError): self.saved.validate()
        path.write_bytes(raw); self.saved.validate()

    def test_large_catalog_reuses_semantics_while_still_verifying_full_file_bytes(self):
        bodies=sources(); lines=bodies['nasdaq'].splitlines()
        bodies['nasdaq']=b'\n'.join([lines[0],*[f'A{i:05d}|Synthetic security {i}|Q|N|N|100|N'.encode() for i in range(10000)],lines[-1]])+b'\n'
        saved=DirectoryCatalog(bodies,receipts()).persist(self.root/'large')
        began=time.perf_counter(); DirectoryCatalog.load(saved.path)
        fresh_seconds=time.perf_counter()-began
        began=time.perf_counter()
        with patch('mb_watchlist_coordinator.integrated_catalog._rows',side_effect=AssertionError('Repeated parsing')):
            for _ in range(5): saved.validate()
        self.qualification_evidence={'symbols':len(saved.symbols),'source_bytes':sum(map(len,bodies.values())),
            'one_fresh_semantic_load_seconds':fresh_seconds,'five_exact_byte_validations_seconds':time.perf_counter()-began,
            'full_file_bytes_checked_each_time':True,'mtime_only_cache':False,'provider_requests':0,
            'scope':'Representative immutable-directory validation cost; not provider/full-session capacity.'}


class WorkerPreparationTests(unittest.TestCase):
    def setUp(self):
        from runtime_fixtures import RuntimeFixture, ScriptedFeed
        from mb_watchlist_coordinator.integrated_runtime import IntegratedRuntime
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.f=RuntimeFixture(temp.name);self.addCleanup(self.f.session.close)
        self.feed=ScriptedFeed(self.f.session.feed)
        self.r=IntegratedRuntime(self.f.session,feed_client=self.feed,worker_command=('synthetic-not-launched',))
        self.r.initialize();self.addCleanup(self.r.close)

    def test_preparation_uses_original_T0_future_fence_without_feed_or_quotes(self):
        ensure=Mock(return_value={'status':'RUNNING'});self.r.worker.ensure=ensure
        self.r.prepare_worker()
        resume=datetime.fromisoformat(ensure.call_args.kwargs['resume_after_utc'])
        self.assertEqual(resume,self.f.start-timedelta(microseconds=1))
        self.assertGreaterEqual(next_future_slot(resume),self.f.start)
        self.assertFalse(self.feed.calls);self.assertEqual(self.f.events,['parent_constructed'])

    def test_original_preparation_endpoint_is_not_renewed(self):
        end=self.f.session.plan.bootstrap_deadline
        self.f.now=end-timedelta(seconds=.015)
        self.r.worker.ensure=Mock(return_value={'status':'STARTING'})
        def advance(seconds):self.f.now+=timedelta(seconds=seconds)
        with self.assertRaises(ValueError):self.r.prepare_worker(sleep=advance)
        self.assertEqual(self.r.worker.ensure.call_count,2)
        self.assertFalse(self.feed.calls)

    def test_refused_first_work_is_terminal_and_does_not_start_another_generation(self):
        self.r.worker.ensure=Mock(return_value={'status':'BLOCKED','reason':'worker_startup_deadline_ended'})
        with self.assertRaises(ValueError):self.r.prepare_worker()
        self.assertEqual(self.r.worker.ensure.call_count,1)

    def test_bound_stop_blocks_preparation_before_worker_start(self):
        self.r.event.set();self.r.worker.ensure=Mock()
        with self.assertRaises(ValueError):self.r.prepare_worker()
        self.r.worker.ensure.assert_not_called()


class NativeFirstSlotTests(unittest.TestCase):
    def test_owned_native_worker_is_ready_before_T0_and_records_the_first_empty_slot(self):
        from test_integrated_runtime_process import RuntimeProcessTests
        from mb_market_data.quote_journal_audit import audit_quote_journal
        from mb_watchlist_coordinator.supervised_hot_worker import progress_receipt
        case=RuntimeProcessTests('runTest');case.setUp();self.addCleanup(case.doCleanups)
        f,r=case.f,case.r
        f.realtime(f.start-timedelta(seconds=2.5))
        case.simulation.write_text(json.dumps({'mode':'normal','log':str(case.log),
            'real_anchor_utc':f.real.isoformat(),'logical_anchor_utc':f.logical.isoformat(),'crash_stage':None}))
        ready=r.prepare_worker()
        job=r.managed._job();first=progress_receipt(job)
        self.assertEqual(ready['status'],'RUNNING')
        self.assertLess(datetime.fromisoformat(first['observed_at_utc']),f.start)
        self.assertFalse(f.session.feed.snapshot()['attempts'])
        expected=next_future_slot(f.start-timedelta(microseconds=1))
        until=time.monotonic()+7
        while True:
            with closing(sqlite3.connect(f.session.store.database_path.resolve().as_uri()+'?mode=ro',uri=True)) as c:
                skips=c.execute('SELECT count(*) FROM poll_slot_skip').fetchone()[0]
            if skips:break
            if time.monotonic()>=until:self.fail('Original first eligible empty-membership slot was not recorded')
            time.sleep(.02)
        result=r.close();audit=audit_quote_journal(f.session.store.database_path,
            audited_at=datetime.fromisoformat(result['acquisition_stop_requested_at_utc']))
        self.assertTrue(audit.passed, audit.findings)
        hot=next(c for c in audit.channels if c.channel=='hot')
        self.assertEqual(hot.acquisition_count,0);self.assertGreaterEqual(hot.skipped_slot_count,1)
        self.assertEqual(hot.missing_slot_ids,())
        self.assertFalse([e for e in case.events() if e['event']=='quote'])
        self.qualification_evidence={'first_eligible_slot_utc':expected.isoformat(),
            'first_completed_work_utc':first['observed_at_utc'],'window_start_utc':f.start.isoformat(),
            'raw_native_audit_passed':audit.passed,'empty_skips':hot.skipped_slot_count,
            'acquisitions':0,'feed_attempts':0,'provider_requests':0,'owned_exit_observed':r.managed.child is None}


class GoalBeforeCycleTests(unittest.TestCase):
    def fixture(self,n,*,acknowledged=True):
        cutover=datetime(2026,10,26,16,11,58,tzinfo=timezone.utc)
        facts=[{'id':str(i),'slot_id':str(i),'quote':True,'generation':1,
            'scheduled_at_utc':utc_text(cutover+timedelta(seconds=2*i+2)),
            'ack_at_utc':utc_text(cutover+timedelta(seconds=2*i+2,microseconds=1))} for i in range(n)]
        if not acknowledged:facts[-1].update(quote=False,ack_at_utc=None)
        p=BoundProfile.__new__(BoundProfile);p.profile='ordinary'
        p.runtime=SimpleNamespace(closed=False,last_report={'discovery_scope_reconciled':True},
            step=Mock(return_value={'status':'OBSERVING'}))
        p._events=lambda:{'cutover':{'data':{'at_utc':utc_text(cutover)}}}
        p.facts=Mock(return_value=(facts,{'pending':None}))
        return p

    def test_completed_goal_stops_before_another_potentially_slow_source_cycle(self):
        p=self.fixture(30);p.runtime.step.side_effect=AssertionError('Another cycle could consume the remaining quote budget')
        result=p.step();self.assertEqual(result['status'],'GOAL_COMPLETE')
        self.assertEqual(result['counts']['after_cutover'],30);p.runtime.step.assert_not_called()

    def test_29_or_unacknowledged_30th_do_not_claim_completion(self):
        for n,ack in ((29,True),(30,False)):
            with self.subTest(n=n,ack=ack):
                p=self.fixture(n,acknowledged=ack);self.assertNotEqual(p.step()['status'],'GOAL_COMPLETE')
                p.runtime.step.assert_called_once()

    def test_busy_progress_defers_without_starting_another_cycle_or_renewing_a_deadline(self):
        from mb_watchlist_coordinator.profile_observation import ObservationPending
        p=self.fixture(30);p.facts.side_effect=ObservationPending('Synthetic BUSY')
        result=p.step();self.assertTrue(result['native_snapshot_pending']);p.runtime.step.assert_not_called()


class WorkerBudgetNotificationTests(unittest.TestCase):
    def call(self,result):
        import mb_watchlist_coordinator.live_profile_entry as entry
        value={'settings':{'experiment_root':str(Path(tempfile.gettempdir()).resolve()/'integrated_hot_synthetic')}}
        observed={'qualified':True};plan=SimpleNamespace(settings=SimpleNamespace(dependency_sha256=digest(observed)))
        args=['entry','worker','launch.json','a'*64,str(Path(value['settings']['experiment_root'])/'authenticated-worker.json'),'job.json']
        with patch.object(sys,'argv',args),patch('mb_watchlist_coordinator.live_profile.bounded_json',return_value=value),patch(
                'mb_watchlist_coordinator.live_profile.validate_configuration',return_value=plan),patch(
                'mb_watchlist_coordinator.installed_startup_probe.inspect_dependencies',return_value=observed),patch(
                'mb_watchlist_coordinator.supervised_hot_worker.run_supervised',return_value=result),patch(
                'mb_watchlist_coordinator.live_profile.request_stop') as stop:
            self.assertEqual(entry.main(),0)
        return stop,value

    def test_exact_bound_worker_budget_result_requests_the_original_scope_stop(self):
        stop,value=self.call({'status':'budget_exhausted'})
        stop.assert_called_once_with(value,'a'*64,'native_budget_exhausted')

    def test_other_worker_results_never_fabricate_a_budget_stop(self):
        for result in ({'status':'stopped'},{'status':'blocked'},None):
            with self.subTest(result=result):self.call(result)[0].assert_not_called()
