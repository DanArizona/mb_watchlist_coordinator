from contextlib import closing
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from resume_fixtures import ResumeFixture, SECRET
from mb_market_data.sampling_membership import SamplingChannel
from mb_market_data.sampling_acquisition import ExplicitPollSlot
from mb_watchlist_coordinator.authenticated_startup import StartupError
from mb_watchlist_coordinator.controller_resume import ResumeError, ResumeLedger, resume_manual
from mb_watchlist_coordinator.recovery_workers import HOT_SECONDS
from mb_watchlist_coordinator.sampling_requests import digest, plain
from mb_watchlist_coordinator.sampling_service import owner_lock


class ManualResumeTests(unittest.TestCase):
    def setUp(self):
        self.phase='setup'
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.f=ResumeFixture(temp.name);self.addCleanup(self.f.close)
        self.r=self.f.runtime
        f=self.f
        class QuoteClock(datetime):
            @classmethod
            def now(cls,tz=None):return f.clock().astimezone(tz or timezone.utc)
        p=patch('mb_market_data.schwab_quotes.datetime',QuoteClock);p.start();self.addCleanup(p.stop)

    def no_secret(self):
        for p in self.f.root.rglob('*'):
            if p.is_file():self.assertNotIn(SECRET.encode(),p.read_bytes(),str(p))

    def interrupt(self,stage):
        def hook(at):
            if at==stage:raise RuntimeError('Synthetic interruption')
        return hook

    def native(self,stage=None):
        self.f.halt()
        slot=ExplicitPollSlot(SamplingChannel.HOT,self.f.now,HOT_SECONDS)
        if stage:
            with self.assertRaises(RuntimeError):
                self.f.session.collector.poller.sample(slot,fault_hook=self.interrupt(stage))
        else:self.f.session.collector.poller.sample(slot)

    def test_reopens_original_bindings_without_registering_a_parent_poll_run_or_dispatch(self):
        self.f.stop_original();original={p:(self.f.target/p).read_bytes() for p in
            ('bootstrap.json','runtime-binding.json','authenticated-worker.json','runtime-stop.json')}
        r=self.f.reopen()
        self.assertEqual(r.identity,self.f.runtime.identity)
        self.assertEqual(r.stop,self.f.stop);self.assertEqual(r.start,self.f.start)
        self.assertEqual(self.f.runs(),1);self.assertFalse(self.f.input_password)
        self.assertEqual(self.f.auth_calls,['load','status','construct','status'])
        self.assertEqual(r.manual_resume_receipt['data']['counts']['directory_source_permits'],2)
        self.assertIsNone(r.managed.child)
        r.close();self.assertEqual(self.f.client_closes,1)
        for p,raw in original.items():self.assertEqual((self.f.target/p).read_bytes(),raw)
        self.no_secret()

    def test_missing_original_state_is_never_reinitialized_or_authenticated(self):
        self.f.stop_original()
        for name in ('requests.sqlite3','quotes.sqlite3','identity.sqlite3','feed.sqlite3',
                'runtime.sqlite3','quotes.hot.poller.sqlite3','quotes.hot.poller.recovery.json'):
            path=self.f.target/name;raw=path.read_bytes();path.unlink()
            try:
                with self.subTest(name=name),self.assertRaises(ResumeError):self.f.reopen()
                self.assertFalse(path.exists());self.assertFalse(self.f.auth_calls)
            finally:path.write_bytes(raw)

    def test_changed_expected_binding_and_worker_command_are_refused_before_credentials(self):
        self.f.stop_original();settings=self.f.settings_for_resume()
        for value in (replace(settings,original_runtime_sha256='0'*64),
                replace(settings,original_configuration_sha256='0'*64),
                replace(settings,worker_command=('another-worker',))):
            with self.subTest(value=value),self.assertRaises(ResumeError):self.f.reopen(settings=value)
        self.assertFalse(self.f.auth_calls)

    def test_changed_proposal_source_blocks_before_authentication(self):
        self.f.stop_original();p=Path(self.f.settings.opening_proposal);p.write_bytes(p.read_bytes()+b'\n')
        with self.assertRaises(ResumeError):self.f.reopen()
        self.assertFalse(self.f.auth_calls)

    def test_changed_dependency_fingerprint_is_refused_before_credential_access(self):
        self.f.stop_original();password=bytearray(SECRET.encode())
        from runtime_fixtures import ScriptedFeed
        with self.assertRaises(ResumeError) as caught:
            resume_manual(self.f.settings_for_resume(),password,feed_factory=ScriptedFeed,clock=self.f.clock,
                secure_api=self.f.api(),inventory=lambda _:{'qualified':True,'different_fingerprint':True})
        self.assertEqual(caught.exception.code,'dependency_rejected')
        self.assertFalse(password);self.assertFalse(self.f.auth_calls)

    def test_same_bootstrap_nonce_is_not_a_new_manual_handoff(self):
        with self.assertRaises(ResumeError):self.f.reopen(nonce=self.f.settings.nonce)
        self.assertFalse(self.f.auth_calls)

    def test_existing_controller_lease_is_not_adopted_or_stopped(self):
        self.f.now=self.f.start+timedelta(seconds=5)
        settings=self.f.settings_for_resume();password=bytearray(SECRET.encode())
        with self.assertRaises(ResumeError) as caught:
            resume_manual(settings,password,feed_factory=lambda _:None,clock=self.f.clock)
        self.assertEqual(caught.exception.code,'ownership_busy');self.assertFalse(password)
        self.assertFalse(self.f.runtime.closed)

    def test_resume_nonce_cannot_reuse_or_overwrite_an_earlier_attempt(self):
        r=self.f.reopen();r.close();before=(self.f.target/'resume.sqlite3').read_bytes()
        with self.assertRaises(ResumeError):self.f.reopen()
        self.assertEqual((self.f.target/'resume.sqlite3').read_bytes(),before)
        self.assertEqual(self.f.auth_calls.count('construct'),1)

    def test_missing_resume_ledger_beside_its_marker_is_blocked(self):
        self.f.reopen().close();p=self.f.target/'resume.sqlite3';p.unlink()
        with self.assertRaises(ResumeError):self.f.reopen(nonce='c'*32)
        self.assertFalse(p.exists());self.assertEqual(self.f.auth_calls.count('construct'),1)

    def test_pre_and_post_refresh_horizons_still_use_original_stop_plus_margin(self):
        for mode in ('horizon','post_horizon'):
            self.f.resume_mode=mode;self.f.auth_calls.clear()
            with self.subTest(mode=mode),self.assertRaises(StartupError) as caught:
                self.f.reopen(nonce=('b' if mode=='horizon' else 'c')*32)
            self.assertEqual(caught.exception.code,'credential_horizon')
        self.assertFalse(self.f.input_password);self.no_secret()

    def test_authorization_refusal_is_redacted_and_does_not_start_a_worker(self):
        self.f.resume_mode='authorization'
        with self.assertRaises(StartupError) as caught:self.f.reopen()
        self.assertEqual(caught.exception.code,'authorization_required')
        self.assertEqual(self.f.runs(),1);self.no_secret()

    def test_original_window_expiry_is_not_extended_by_new_submission(self):
        self.f.stop_original();self.f.now=self.f.stop
        with self.assertRaises(ResumeError) as caught:self.f.reopen()
        self.assertEqual(caught.exception.code,'resume_deadline_ended');self.assertFalse(self.f.auth_calls)

    def test_slow_authentication_cannot_renew_the_sixty_second_reopen_deadline(self):
        self.f.resume_constructor=lambda:setattr(self.f,'now',self.f.now+timedelta(seconds=61))
        with self.assertRaises(ResumeError) as caught:self.f.reopen()
        self.assertEqual(caught.exception.code,'resume_deadline_ended')
        self.assertEqual(self.f.client_closes,1);self.no_secret()

    def test_saved_assembled_response_recovers_without_quote_or_new_parent_run(self):
        self.native('after_assembled');self.assertFalse(self.f.session.store.acquisitions_in_replay_order())
        r=self.f.reopen()
        self.assertEqual(len(r.session.store.acquisitions_in_replay_order()),1)
        self.assertEqual(self.f.runs(),1)
        self.assertFalse([x for x in self.f.auth_calls if isinstance(x,tuple)])
        self.assertEqual(r.manual_resume_receipt['data']['counts']['hot_quote_permits'],1)
        self.assertTrue(r.manual_resume_receipt['data']['native_recovery']['recovered'])

    def test_saved_commit_before_ack_is_idempotent_across_two_manual_reopens(self):
        self.native('after_journal_commit');r=self.f.reopen();r.close()
        second=self.f.reopen(nonce='c'*32)
        self.assertEqual(len(second.session.store.acquisitions_in_replay_order()),1)
        self.assertIsNone(second.session.collector.poller.snapshot()['pending'])
        self.assertEqual(second.manual_resume_receipt['data']['counts']['hot_quote_permits'],1)
        self.assertEqual(self.f.runs(),1)

    def test_unknown_dispatch_stays_charged_and_is_not_refetched(self):
        self.native('after_dispatch');r=self.f.reopen()
        self.assertEqual(r.manual_resume_receipt['data']['native_recovery']['status'],'unresolved_dispatch')
        self.assertFalse(r.session.store.acquisitions_in_replay_order())
        self.assertEqual(r.manual_resume_receipt['data']['counts']['hot_quote_permits'],1)
        self.assertFalse([x for x in self.f.auth_calls if isinstance(x,tuple)])

    def test_identity_unknown_reservation_is_retained_without_another_lookup(self):
        self.f.activate();self.f.now=self.f.start+timedelta(seconds=1)
        from runtime_process_evidence import subsequent_halt_snapshot
        baseline=self.f.session.live.snapshot()['receipts'][0]['snapshot']
        self.f.session.live.record_snapshot(subsequent_halt_snapshot(baseline,observed_at=self.f.now,capture_id='unknown-identity'))
        gate=self.f.runtime.delivery.gate;gate.reconcile()
        with self.assertRaises(RuntimeError):gate.deliver_pending(client=self.f.session.client,
            fault_hook=self.interrupt('after_identity_reservation'))
        r=self.f.reopen();r.worker.ensure=lambda **kw:{'status':'RUNNING','synthetic_worker':True};r.step()
        state=r.session.gated_delivery.snapshot()['identity_gate']
        self.assertEqual(state['quote_permits'],1);self.assertIsNone(state['selected_symbol'])
        self.assertIn('identity_outcome_unknown_no_retry',state['dispositions'].values())
        self.assertFalse([x for x in self.f.auth_calls if isinstance(x,tuple)])

    def test_selected_symbol_and_pending_request_ack_reuse_do_not_lookup_again(self):
        self.f.halt();r=self.f.reopen()
        r.worker.ensure=lambda **kw:{'status':'RUNNING','synthetic_worker':True};r.step()
        state=r.session.gated_delivery.snapshot()['identity_gate']
        self.assertEqual(state['selected_symbol'],'NVDA');self.assertEqual(state['quote_permits'],1)
        self.assertFalse([x for x in self.f.auth_calls if isinstance(x,tuple)])

    def test_pending_feed_attempt_is_interrupted_charged_and_re_paced(self):
        self.f.activate();self.f.now+=timedelta(seconds=60)
        reservation=self.f.session.feed.reserve(synthetic=True);self.assertIsNotNone(reservation)
        r=self.f.reopen();state=r.session.feed.snapshot()
        self.assertIsNone(state['pending']);self.assertEqual(len(state['attempts']),2)
        self.assertEqual(state['attempts'][-1]['outcome']['kind'],'unknown_interrupted')
        self.assertEqual(r.manual_resume_receipt['data']['counts']['feed_attempts'],2)
        self.assertIsNone(r.session.feed.reserve(synthetic=True))

    def test_corrupt_native_observation_blocks_before_credential_access(self):
        self.native()
        with closing(sqlite3.connect(self.f.session.store.database_path)) as c,c:
            c.execute("UPDATE quote_observation SET status='invalid'")
        with self.assertRaises(ResumeError):self.f.reopen()
        self.assertFalse(self.f.auth_calls)

    def test_unregistered_generation_file_blocks_budget_reset(self):
        self.f.stop_original();p=self.f.target/'workers'/(('d'*32)+'.job.json')
        p.write_text('{}')
        with self.assertRaises(ResumeError):self.f.reopen()
        self.assertFalse(self.f.auth_calls)

    def test_interruption_after_credentials_keeps_failed_attempt_and_new_nonce_can_reopen(self):
        with self.assertRaises(ResumeError):self.f.reopen(fault_hook=self.interrupt('credentials_accepted'))
        r=self.f.reopen(nonce='c'*32)
        self.assertEqual(r.resume_ledger.snapshot()['states']['b'*32],'failed')
        self.assertEqual(r.resume_ledger.snapshot()['states']['c'*32],'ready')
        self.assertEqual(self.f.runs(),1);self.no_secret()

    def test_transient_native_read_lease_is_waited_for_without_repeating_provider_work(self):
        self.f.stop_original();held=threading.Event()
        def holder():
            with owner_lock(self.f.session.collector.poller.lock_path):
                held.set();time.sleep(.15)
        thread=threading.Thread(target=holder);thread.start();self.addCleanup(thread.join)
        self.assertTrue(held.wait(1));r=self.f.reopen()
        self.assertEqual(r.manual_resume_receipt['data']['counts']['hot_quote_permits'],0)
        self.assertEqual(self.f.auth_calls.count('construct'),1)

    def test_new_submission_cannot_precede_the_retained_stop_receipt(self):
        self.f.stop_original();self.f.now-=timedelta(seconds=1)
        with self.assertRaises(ResumeError):self.f.reopen()
        self.assertFalse(self.f.auth_calls)

    def test_missing_workers_directory_is_not_recreated(self):
        self.f.stop_original();p=self.f.target/'workers';p.rmdir()
        with self.assertRaises(ResumeError):self.f.reopen()
        self.assertFalse(p.exists());self.assertFalse(self.f.auth_calls)

    def test_terminal_provider_evidence_blocks_new_authentication(self):
        self.f.stop_original();p=self.f.target/'runtime-stop.json';value=json.loads(p.read_text())
        value['reason']='native_blocked';p.write_text(json.dumps(value))
        with self.assertRaises(ResumeError) as caught:self.f.reopen()
        self.assertEqual(caught.exception.code,'terminal_evidence');self.assertFalse(self.f.auth_calls)

    def test_rehashed_false_resume_allowance_is_rejected_without_using_it_as_a_budget(self):
        r=self.f.reopen();r.close();path=self.f.target/'resume.sqlite3'
        with closing(sqlite3.connect(path)) as c,c:
            events=[json.loads(row[0]) for row in c.execute('SELECT payload FROM resume_event ORDER BY sequence')]
            previous=events[0]['previous_sha256']
            from mb_watchlist_coordinator.sampling_requests import canonical
            for e in events:
                if e['kind']=='ready':e['data']['counts']['hot_quote_permits']=61
                e['previous_sha256']=previous;body=dict(e);body.pop('event_sha256');e['event_sha256']=digest(body)
                previous=e['event_sha256'];c.execute('UPDATE resume_event SET payload=? WHERE sequence=?',(canonical(e),e['sequence']))
        with self.assertRaises(ResumeError):self.f.reopen(nonce='c'*32)
        self.assertEqual(self.f.auth_calls.count('construct'),1)

    def queue_halt_without_publication(self):
        self.f.activate();self.f.now=self.f.start+timedelta(seconds=1)
        from runtime_process_evidence import subsequent_halt_snapshot
        baseline=self.f.session.live.snapshot()['receipts'][0]['snapshot']
        self.f.session.live.record_snapshot(subsequent_halt_snapshot(baseline,observed_at=self.f.now,capture_id='pending-ack-halt'))
        gate=self.f.runtime.delivery.gate;gate.reconcile()
        return gate

    def test_committed_request_without_delivery_ack_reopens_without_an_identity_lookup(self):
        gate=self.queue_halt_without_publication()
        def interrupted(_):raise RuntimeError('Synthetic post-submit interruption')
        with self.assertRaises(RuntimeError):gate.deliver_pending(client=self.f.session.client,after_submit=interrupted)
        r=self.f.reopen();r.worker.ensure=lambda **kw:{'status':'RUNNING','synthetic_worker':True};r.step()
        requests=[e for e in r.session.requests.events() if e.kind=='request']
        self.assertEqual(len(requests),1);self.assertTrue(r.session.base_delivery.snapshot()['deliveries'])
        self.assertEqual(r.session.gated_delivery.snapshot()['identity_gate']['quote_permits'],1)
        self.assertFalse([x for x in self.f.auth_calls if isinstance(x,tuple)])

    def test_native_publication_commit_without_ack_is_recovered_without_duplicate_revision(self):
        gate=self.queue_halt_without_publication();gate.deliver_pending(client=self.f.session.client)
        with self.assertRaises(RuntimeError):self.f.session.service.cycle(fault_hook=self.interrupt('after_commit'))
        before=len(self.f.session.store.membership_revisions_in_effective_order())
        r=self.f.reopen();r.worker.ensure=lambda **kw:{'status':'RUNNING','synthetic_worker':True};r.step()
        self.assertEqual(len(r.session.store.membership_revisions_in_effective_order()),before)
        self.assertFalse(r.session.service.snapshot()['unacknowledged'])
        self.assertFalse([x for x in self.f.auth_calls if isinstance(x,tuple)])

    def test_fifty_nine_unknown_dispatches_leave_exactly_one_quote_permit_after_reopen(self):
        self.f.halt()
        from mb_watchlist_coordinator.recovery_workers import next_future_slot
        for _ in range(59):
            self.f.now=next_future_slot(self.f.now)
            slot=ExplicitPollSlot(SamplingChannel.HOT,self.f.now,HOT_SECONDS)
            with self.assertRaises(RuntimeError):
                self.f.session.collector.poller.sample(slot,fault_hook=self.interrupt('after_dispatch'))
        r=self.f.reopen()
        self.assertEqual(r.manual_resume_receipt['data']['counts']['hot_quote_permits'],59)
        r.session.collector.prepare()
        self.f.now=r.session.collector.next.scheduled_at
        self.assertEqual(r.session.collector.tick()['status'],'acquired')
        self.assertEqual(r.session.collector.tick()['status'],'budget_exhausted')
        self.assertEqual(len([x for x in self.f.auth_calls if isinstance(x,tuple)]),1)
        r.close()
        with self.assertRaises(ResumeError) as caught:self.f.reopen(nonce='c'*32)
        self.assertEqual(caught.exception.code,'budget_exhausted')
        self.assertEqual(self.f.auth_calls.count('construct'),1)
