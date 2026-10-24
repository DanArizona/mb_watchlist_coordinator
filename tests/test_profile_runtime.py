from datetime import timedelta,datetime,timezone
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest

from runtime_fixtures import RuntimeFixture,ScriptedFeed
from test_nasdaq_feed_recovery import EMPTY,rss
from mb_watchlist_coordinator.integrated_runtime import IntegratedRuntime
from mb_watchlist_coordinator.profile_runtime import BoundProfile
from mb_watchlist_coordinator.outer_harness import OuterHarness,OuterSchedule
from mb_watchlist_coordinator.sampling_requests import timestamp,digest,utc_text


class ProfileRuntimeTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup)
        self.f=RuntimeFixture(t.name);self.addCleanup(self.f.session.close)
        self.feed=ScriptedFeed(self.f.session.feed)
        self.r=IntegratedRuntime(self.f.session,feed_client=self.feed,worker_command=('synthetic-no-worker-execution',))
        self.r.initialize();self.addCleanup(self.r.close)
        self.r.worker.ensure=lambda **kw:{'status':'RUNNING','synthetic_worker':True}
        self.p=BoundProfile(self.r,'ordinary')

    def reconcile(self):
        self.f.now=self.f.start;self.p.step()
        self.f.now=self.f.start+timedelta(seconds=60);self.p.step()
        self.f.now=self.f.start+timedelta(seconds=120);self.p.step()

    def test_cutover_is_derived_from_paced_source_receipts(self):
        self.reconcile();events=self.p._events()
        self.assertEqual(set(events),{'cutover'});self.p.verify_receipts(events)
        self.assertEqual(len(self.f.session.feed.snapshot()['attempts']),3)

    def test_reopen_retains_profile_binding_and_prior_cutover(self):
        self.reconcile();before=self.p.path.read_bytes()
        p=BoundProfile(self.r,'ordinary');self.assertEqual(p.path.read_bytes(),before)
        with self.assertRaises(ValueError):BoundProfile(self.r,'owned_worker_recovery')

    def test_rehashed_false_cutover_is_not_trusted(self):
        self.reconcile();value=json.loads(self.p.path.read_text())
        e=value['events'][0];e['data']['attempt_id']='invented';body=dict(e);body.pop('sha256');e['sha256']=digest(body)
        self.p.path.write_text(json.dumps(value))
        with self.assertRaises(ValueError):self.p.verify_receipts(self.p._events())

    def test_valid_startup_baseline_cannot_be_rehashed_into_a_post_history_cutover(self):
        self.reconcile();value=json.loads(self.p.path.read_text())
        baseline=self.f.session.feed.snapshot()['attempts'][0]
        e=value['events'][0];e['data']={'attempt_id':baseline['attempt_id'],'at_utc':baseline['completed_at_utc'],
            'feed_head_sha256':baseline['completion_event_sha256']}
        body=dict(e);body.pop('sha256');e['sha256']=digest(body);self.p.path.write_text(json.dumps(value))
        with self.assertRaises(ValueError):self.p.verify_receipts(self.p._events())

    def test_closed_profile_cannot_resume_new_work_or_reset_goal(self):
        self.f.now=self.f.start;self.p.step();self.p.close()
        before=self.f.session.feed.snapshot()['head_sha256']
        self.assertEqual(self.p.step()['status'],'STOPPED');self.assertEqual(self.f.session.feed.snapshot()['head_sha256'],before)

    def test_transient_native_snapshot_owner_does_not_repeat_provider_work(self):
        from unittest.mock import patch
        from mb_market_data.sampling_acquisition import AcquisitionBusy
        self.f.now=self.f.start
        with patch.object(self.p,'facts',side_effect=AcquisitionBusy('synthetic owner')):
            value=self.p.step()
        self.assertTrue(value['native_snapshot_pending'])
        self.assertEqual(self.f.events,['parent_constructed'])

    def recovery_profile(self):
        self.r.worker.ensure=self.p.original_ensure
        self.p.path.unlink();self.p=BoundProfile(self.r,'owned_worker_recovery');self.reconcile()
        fault={'generation':1,'token':'a'*32,'pid':123,'last_acknowledged_id':'synthetic-unit-ack',
            'requested_at_utc':utc_text(self.f.clock())}
        self.p._append('fault_intent',dict(fault));return fault

    def test_interrupted_fault_intent_is_not_repeated_or_restarted_on_reopen(self):
        self.recovery_profile()
        p=BoundProfile(self.r,'owned_worker_recovery')
        value=p._ensure(start_allowed=True,resume_after_utc=utc_text(self.f.clock()))
        self.assertEqual(value['status'],'BLOCKED');self.assertEqual(value['reason'],'profile_fault_outcome_unknown')

    def test_replacement_hold_needs_both_original_elapsed_and_event_clock_bounds(self):
        fault=self.recovery_profile();fault['exit_observed_at_utc']=utc_text(self.f.clock())
        self.p._append('fault',fault);mono=[0.0];self.p.monotonic=lambda:mono[0]
        now=self.f.now
        self.assertEqual(self.p._ensure(start_allowed=True,resume_after_utc=utc_text(self.f.clock()))['status'],'WAITING_FOR_PROFILE_HOLD')
        mono[0]=16;self.f.now=now+timedelta(seconds=14.9)
        self.assertEqual(self.p._ensure(start_allowed=True,resume_after_utc=utc_text(self.f.clock()))['status'],'WAITING_FOR_PROFILE_HOLD')
        self.f.now=now+timedelta(seconds=15)
        self.assertEqual(self.p._ensure(start_allowed=True,resume_after_utc=utc_text(self.f.clock()))['status'],'RUNNING')

    def test_profile_actions_after_stop_or_duplicate_fault_are_refused(self):
        self.recovery_profile()
        with self.assertRaises(ValueError):self.p._append('fault_intent',{})
        self.p.close()
        with self.assertRaises(ValueError):self.p._append('restart',{})

    def test_fault_policy_persists_intent_before_stopping_only_the_exact_owned_handle(self):
        from unittest.mock import patch
        self.r.worker.ensure=self.p.original_ensure
        self.p.path.unlink();self.p=BoundProfile(self.r,'owned_worker_recovery');self.reconcile()
        cutover=self.p._events()['cutover']['data']['at_utc']
        self.f.now+=timedelta(seconds=30)
        facts=[{'id':str(i),'slot_id':str(i),'quote':True,'ack_at_utc':utc_text(self.f.now),
            'scheduled_at_utc':utc_text(timestamp(cutover)+timedelta(seconds=2+i)), 'generation':1} for i in range(12)]
        child=subprocess.Popen([sys.executable,'-I','-B','-c','import time;time.sleep(20)'])
        other=subprocess.Popen([sys.executable,'-I','-B','-c','import time;time.sleep(20)'])
        self.r.managed.child=child
        def reaped(reason):
            self.assertEqual(reason,'profile_injected_fault');self.assertIsNotNone(child.poll())
            self.r.managed.child=None
        original_append=self.p._append
        def append(kind,data):
            if kind=='fault_intent':self.assertIsNone(child.poll())
            original_append(kind,data)
        try:
            with patch.object(self.r,'step',return_value={'worker':{'status':'RUNNING'}}),patch.object(
                    self.p,'facts',return_value=(facts,{'pending':None})),patch.object(
                    self.r.managed,'_job',return_value={'generation':1,'token':'a'*32}),patch.object(
                    self.r.managed,'_reap_owned',side_effect=reaped),patch.object(self.p,'_append',side_effect=append):
                self.p.step()
            self.assertIsNotNone(child.poll());self.assertIsNone(other.poll())
            self.assertIn('fault_intent',self.p._events());self.assertIn('fault',self.p._events())
        finally:
            self.r.managed.child=None
            for c in (child,other):
                if c.poll() is None:c.terminate()
                c.wait(timeout=2)


class OuterNativeProcessTests(unittest.TestCase):
    def test_gated_controller_native_acquisition_and_independent_read_only_report(self):
        from dataclasses import replace
        from test_controller_bootstrap import make_settings
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'outer_native';root.mkdir()
            # Public proposal preparation only; the child creates its synthetic
            # encrypted config, bootstrap and native state AFTER the scope gate.
            settings=replace(make_settings(root),catalog_mode='owned_directory',catalog_id='',catalog_symbols=())
            plan=settings.plan();root.rmdir() if not any(root.iterdir()) else None
            # The supervisor requires a fresh outer root; keep public fixtures
            # outside it until the owned child prepares its own identical inputs.
            for path in root.iterdir():path.unlink()
            root.rmdir()
            real=datetime.now(timezone.utc);initial=timestamp(settings.password_submitted_at_utc)+timedelta(seconds=1)
            def clock():
                anchor=root/'logical-clock.json'
                if anchor.exists():
                    v=json.loads(anchor.read_text())
                    return timestamp(v['logical'])+(datetime.now(timezone.utc)-timestamp(v['real']))
                return initial+(datetime.now(timezone.utc)-real)
            nonce='d'*32;probe=Path(__file__).parent/'fixtures/outer_runtime_probe.py'
            configs=[]
            for mode in ('controller','report'):
                path=Path(temp)/(mode+'.json');path.write_text(json.dumps({'mode':mode,'root':str(root),'nonce':nonce,
                    'trace_fixed_exceptions':True}));configs.append(path)
            h=OuterHarness(root,OuterSchedule(settings.password_submitted_at_utc,plan.public['start_at_utc'],plan.public['stop_at_utc']),
                nonce,clock=clock,expected_preflight_sha256=plan.configuration_sha256)
            began=time.monotonic()
            result=h.run((sys.executable,'-I','-B',str(probe),str(configs[0])),
                reporter_command=(sys.executable,'-I','-B',str(probe),str(configs[1])))
            self.failure_evidence={'outer':result,'entry_failure':json.loads((root/'entry-failure.json').read_text())
                if (root/'entry-failure.json').exists() else None,
                'controller_failure':json.loads((root/'controller-entry-failure.json').read_text())
                if (root/'controller-entry-failure.json').exists() else None}
            self.assertLess(time.monotonic()-began,15)
            self.assertEqual(result['cleanup']['status'],'EXIT_OBSERVED')
            self.assertTrue(result['reporting_complete'],self.failure_evidence)
            evidence=json.loads((root/'native-profile-report.json').read_text())
            self.assertTrue(evidence['reporting_read_only']);self.assertFalse(evidence['credential_access'])
            self.assertEqual(evidence['result'],'FAILED' if evidence['missing_slot_ids'] else 'INCOMPLETE')
            self.assertFalse(evidence['goals']['goal_complete'])
            self.assertEqual(result['result'],evidence['result'],self.failure_evidence)
            self.assertEqual(evidence['non_quote_acquisition_ids'],[])
            self.assertLessEqual({f['code'] for f in evidence['raw_native_audit']['findings']},{'missing_poll_slots'})
            self.assertTrue(evidence['identical_fresh_replays'])
            counts=evidence['raw_native_audit']['table_counts']
            self.assertGreaterEqual(counts['quote_acquisition'],1)
            self.assertEqual(evidence['replays'][0]['events'],counts['sampling_membership_revision']+counts['quote_acquisition'])
            import hashlib
            before=json.loads((root/'before-report-hashes.json').read_text())
            after={p.relative_to(root/'integrated_hot_fresh').as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
                for p in (root/'integrated_hot_fresh').rglob('*') if p.is_file() and not p.name.endswith(('-shm','-wal'))}
            self.assertEqual(before,after)
            from saved_artifact_scan import scan_saved_artifacts
            scanned=scan_saved_artifacts(root,(b'SYNTHETIC-PASSWORD-CANARY-41',b'SYNTHETIC-CODE-CANARY-44'))
            self.assertIn('integrated_hot_fresh/controller.owner.lock',scanned)
