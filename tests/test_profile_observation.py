from contextlib import closing
from datetime import timedelta
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import mb_market_data.sampling_acquisition as native
import test_profile_evidence as fixture
from runtime_fixtures import RuntimeFixture,ScriptedFeed
from mb_watchlist_coordinator.profile_observation import observe_native_facts,ObservationPending
from mb_watchlist_coordinator.integrated_runtime import IntegratedRuntime
from mb_watchlist_coordinator.recovery_workers import next_future_slot


class ProfileObservationTests(unittest.TestCase):
    setUp=fixture.ProfileEvidenceTests.setUp
    poll=fixture.ProfileEvidenceTests.poll
    def observe(self,**kw):return observe_native_facts(self.session,generation_for=lambda a:1,**kw)

    def test_observer_does_not_take_the_acquisition_writer_lease(self):
        self.poll(1)
        with native.owner_lock(self.worker.poller.lock_path):
            with self.assertRaises(native.AcquisitionBusy):self.worker.poller.snapshot()
            facts,state=self.observe()
        self.assertEqual(len(facts),1);self.assertTrue(facts[0]['quote']);self.assertTrue(state['progress_observation_only'])

    def test_observer_never_calls_the_strict_writer_snapshot(self):
        self.poll(1)
        with patch.object(self.worker.poller,'snapshot',side_effect=AssertionError('Observer took writer lease')):
            facts,_=self.observe()
        self.assertEqual(len(facts),1)

    def test_quiescent_progress_facts_match_original_strict_native_facts(self):
        from mb_watchlist_coordinator.profile_evidence import native_facts
        self.poll(2)
        strict,_=native_facts(self.session,generation_for=lambda a:1)
        self.assertEqual(self.observe()[0],strict)

    def test_commit_without_ack_is_not_counted_but_its_permit_remains_charged(self):
        self.now=next_future_slot(self.now)
        def stop(stage):
            if stage=='after_journal_commit':raise RuntimeError('synthetic interruption')
        with self.assertRaises(RuntimeError):self.worker.tick(fault_hook=stop)
        facts,state=self.observe()
        self.assertEqual(facts,());self.assertIsNotNone(state['pending'])
        self.assertEqual(sum(e['kind']=='dispatch' and bool(e['symbols']) for e in state['events']),1)

    def test_newer_journal_work_during_observation_is_deferred_to_next_prefix(self):
        self.poll(1);facts,_=self.observe(after_prefix=lambda:self.poll(1))
        self.assertEqual(len(facts),1);self.assertEqual(len(self.observe()[0]),2);self.assertEqual(self.calls,2)

    def test_changed_normalized_observation_is_not_trusted(self):
        self.poll(1)
        with closing(sqlite3.connect(self.store.database_path)) as c,c:c.execute("UPDATE quote_observation SET status='invalid'")
        with self.assertRaises(ValueError):self.observe()

    def test_corrupt_prefix_hash_is_not_trusted(self):
        self.poll(1)
        with closing(sqlite3.connect(self.worker.poller.path)) as c,c:c.execute("UPDATE acquisition_event SET event_sha256='changed' WHERE sequence=1")
        with self.assertRaises(ValueError):self.observe()

    def test_changed_ack_receipt_is_rejected_even_after_rehash(self):
        self.poll(1)
        with closing(sqlite3.connect(self.worker.poller.path)) as c,c:
            n,raw,prior,_=c.execute('SELECT * FROM acquisition_event ORDER BY sequence DESC LIMIT 1').fetchone()
            e=json.loads(raw);e['journal_receipt']['content_sha256']='0'*64
            sha=native.digest({'sequence':n,'payload':e,'previous_sha256':prior})
            c.execute('UPDATE acquisition_event SET payload=?,event_sha256=? WHERE sequence=?',(native.canonical(e),sha,n))
        with self.assertRaises(ValueError):self.observe()

    def test_observer_keeps_provider_non_quote_status(self):
        self.invalid=True;self.poll(1);facts,_=self.observe()
        self.assertFalse(facts[0]['quote']);self.assertEqual(facts[0]['statuses'],['missing'])

    def test_empty_membership_ack_remains_a_skip_and_later_quote_is_observed(self):
        from dataclasses import replace
        old=self.store.membership_revisions_in_effective_order()[-1]
        self.store.record_membership_revision(replace(old,revision=1,published_at=None,
            effective_at=self.start+timedelta(seconds=1),hot_symbols=()))
        self.now=self.start+timedelta(seconds=2)
        self.assertEqual(self.worker.tick()['status'],'empty_membership')
        facts,state=self.observe();self.assertEqual(facts,())
        self.assertEqual(sum(e['kind']=='dispatch' and bool(e['symbols']) for e in state['events']),0)
        self.store.record_membership_revision(replace(old,revision=2,published_at=None,
            effective_at=self.start+timedelta(seconds=3)))
        self.poll(1);self.assertEqual(len(self.observe()[0]),1)

    def test_sqlite_busy_is_deferred_without_a_read_retry_loop(self):
        error=sqlite3.OperationalError('synthetic busy');error.sqlite_errorcode=sqlite3.SQLITE_BUSY
        with patch('mb_watchlist_coordinator.profile_observation.sqlite3.connect',side_effect=error) as read:
            with self.assertRaises(ObservationPending):self.observe()
        self.assertEqual(read.call_count,1)

    def test_other_sqlite_errors_are_not_treated_as_busy(self):
        error=sqlite3.OperationalError('synthetic invalid database');error.sqlite_errorcode=sqlite3.SQLITE_CORRUPT
        with patch('mb_watchlist_coordinator.profile_observation.sqlite3.connect',side_effect=error):
            with self.assertRaises(sqlite3.OperationalError):self.observe()


class WorkerObservationContentionTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.f=RuntimeFixture(temp.name);self.addCleanup(self.f.session.close)
        sim=self.f.root/'worker-simulation.json';self.log=self.f.root/'worker-events.jsonl'
        command=(sys.executable,'-I','-B',str(Path(__file__).parent/'fixtures/outer_hot_worker_probe.py'),
            str(self.f.target/'authenticated-worker.json'),str(sim))
        self.r=IntegratedRuntime(self.f.session,feed_client=ScriptedFeed(self.f.session.feed),worker_command=command)
        self.r.initialize();self.addCleanup(self.r.close);self.f.realtime()
        sim.write_text(json.dumps({'mode':'normal','log':str(self.log),
            'real_anchor_utc':self.f.real.isoformat(),'logical_anchor_utc':self.f.logical.isoformat()}))

    def test_controlled_writer_lease_conflict_reproduces_generic_credentials_rejection(self):
        with native.owner_lock(self.f.session.collector.poller.lock_path):
            self.r.step();job=self.r.managed._job()
            self.assertEqual(self.r.managed.child.wait(timeout=3),70)
            auth=json.loads((self.r.managed.root/(job['token']+'.auth.json')).read_text())
        self.assertEqual(auth['status'],'startup_failed')
        self.assertEqual(self.r.step()['reason'],'worker_credentials_rejected')
        events=[json.loads(s) for s in self.log.read_text().splitlines()]
        self.assertFalse(any(e['event']=='constructed' for e in events))
        self.assertTrue(any(e['event']=='safe_failure' and any(c['exception_type']=='AcquisitionBusy' for c in e['contexts']) for e in events))

    def test_read_only_progress_observer_does_not_block_worker_authentication_or_first_work(self):
        observed={}
        def start_worker():
            self.r.step();until=time.monotonic()+3
            while time.monotonic()<until:
                report=self.r.step()
                if report.get('worker',{}).get('status')=='RUNNING':
                    observed.update(report);return
                if self.r.closed:self.fail('Native startup stopped while read-only observer was active')
                time.sleep(.02)
            self.fail('Original worker first-work deadline did not complete')
        facts,state=observe_native_facts(self.f.session,generation_for=lambda a:1,after_prefix=start_worker)
        self.assertEqual(facts,());self.assertEqual(observed['worker']['status'],'RUNNING')
        job=self.r.managed._job();auth=json.loads((self.r.managed.root/(job['token']+'.auth.json')).read_text())
        self.assertEqual(auth['status'],'credentials_accepted');self.assertIsNone(self.r.managed.child.poll())
        self.assertEqual(self.r.identity['worker_startup_seconds'],3);self.assertEqual(self.r.identity['credential_timeout_seconds'],8)
