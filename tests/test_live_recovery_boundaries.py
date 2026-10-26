"""Preserve recovery permits, native first-slot allowance and bounded close."""
from dataclasses import replace
from datetime import datetime,timedelta,timezone
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from mb_watchlist_coordinator.integrated_runtime import IntegratedRuntime,_PreparedDelivery
from mb_watchlist_coordinator.outer_harness import OuterHarness,OuterSchedule
from mb_watchlist_coordinator.outer_deadline import OuterBounds
from mb_watchlist_coordinator.recovery_workers import ManagedRecoveryWorker
from mb_watchlist_coordinator.sampling_requests import plain,utc_text
from runtime_fixtures import RuntimeFixture,ScriptedFeed
from test_nasdaq_feed_recovery import EMPTY,rss


class RecoveryDeliveryTests(unittest.TestCase):
    def fixture(self,profile='owned_worker_recovery',last_valid=True):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        f=RuntimeFixture(temp.name,profile=profile);self.addCleanup(f.session.close)
        feed=ScriptedFeed(f.session.feed)
        body=rss(f.start.date(),halt='09:59:30',symbol='NVDA')
        feed.responses=[EMPTY,body,body if last_valid else b'not an RSS document']
        runtime=IntegratedRuntime(f.session,feed_client=feed,worker_command=('synthetic-not-launched',))
        runtime.initialize();self.addCleanup(runtime.close)
        runtime.worker.ensure=lambda **kw:{'status':'RUNNING','synthetic_worker':True}
        return f,feed,runtime

    def history(self,f,runtime):
        f.now=f.start;runtime.step()
        f.now=f.start+timedelta(seconds=60);runtime.step()

    def test_real_pending_recovery_commands_wait_without_identity_or_hot_publication(self):
        f,feed,r=self.fixture();self.history(f,r)
        state=plain(f.session.gated_delivery.snapshot())
        self.assertTrue(state['pending']);self.assertTrue(state['commands'])
        self.assertEqual(state['identity_gate']['quote_permits'],0)
        self.assertEqual(f.events,['parent_constructed'])
        self.assertEqual(f.session.store.membership_revisions_in_effective_order()[-1].hot_symbols,())
        self.assertEqual(r.delivery.identity['request_delivery_policy'],
            'after_valid_dated_and_strictly_later_current_cutover')
        self.qualification_evidence={'queued_commands':len(state['commands']),
            'pending_commands_retained':len(state['pending']),'identity_permits_before_cutover':0,
            'hot_members_before_cutover':[],'quote_calls_before_cutover':0,
            'policy_scope':'owned_worker_recovery only; ordinary delivery unchanged'}

    def test_strict_later_current_uses_original_identity_admission_and_publication(self):
        f,feed,r=self.fixture();self.history(f,r)
        commands=plain(f.session.gated_delivery.snapshot())['commands']
        f.now=f.start+timedelta(seconds=120);report=r.step()
        state=plain(f.session.gated_delivery.snapshot())
        self.assertTrue(report['discovery_scope_reconciled'])
        self.assertEqual(state['commands'],commands)
        self.assertFalse(state['pending']);self.assertTrue(state['deliveries'])
        self.assertEqual(state['identity_gate']['quote_permits'],1)
        self.assertEqual(state['identity_gate']['selected_symbol'],'NVDA')
        latest=f.session.store.membership_revisions_in_effective_order()[-1]
        self.assertEqual(latest.hot_symbols,('NVDA',))
        self.assertGreater(latest.effective_at,f.start+timedelta(seconds=120))
        self.assertEqual(f.session.collector.settings.max_quote_calls,60)
        self.assertEqual(feed.calls,3)
        self.assertEqual(f.events,['parent_constructed',('identity_quote',['NVDA'],'all')])

    def test_unavailable_cutover_does_not_deliver_or_fabricate_empty_roster(self):
        f,feed,r=self.fixture(last_valid=False);self.history(f,r)
        before=plain(f.session.gated_delivery.snapshot())
        f.now=f.start+timedelta(seconds=120);report=r.step()
        after=plain(f.session.gated_delivery.snapshot())
        self.assertFalse(report['discovery_scope_reconciled'])
        self.assertEqual(before['commands'],after['commands'])
        self.assertEqual(before['pending'],after['pending'])
        self.assertEqual(after['identity_gate']['quote_permits'],0)
        self.assertEqual(f.session.store.membership_revisions_in_effective_order()[-1].hot_symbols,())

    def test_ordinary_delivery_still_admits_before_recovery_cutover(self):
        f,feed,r=self.fixture('ordinary');self.history(f,r)
        self.assertNotIn('request_delivery_policy',r.delivery.identity)
        state=plain(f.session.gated_delivery.snapshot())
        self.assertFalse(state['pending']);self.assertEqual(state['identity_gate']['quote_permits'],1)
        self.assertEqual(f.session.store.membership_revisions_in_effective_order()[-1].hot_symbols,('NVDA',))
        self.assertFalse(r.last_report['discovery_scope_reconciled'])

    def stub(self,state):
        at=datetime(2026,10,26,18,58,42,tzinfo=timezone.utc)
        feed=SimpleNamespace(snapshot=lambda:state,queries=(SimpleNamespace(query_id='DATED'),),
            limits=SimpleNamespace(interval_seconds=60))
        runtime=SimpleNamespace(session=SimpleNamespace(plan=SimpleNamespace(settings=
            SimpleNamespace(profile='owned_worker_recovery'),configuration_sha256='a'*64),feed=feed,client=object()),
            validate=Mock(),clock=lambda:at)
        gate=SimpleNamespace(path=Path('synthetic'),live=object(),recovery=object(),requests=object(),
            identity={'contract':'synthetic-gate'},deliver_pending=Mock(return_value=('normal-delivery',)))
        return _PreparedDelivery(runtime,gate),gate,at

    def test_baseline_missing_scope_pending_stale_bad_and_equal_time_do_not_open_delivery(self):
        at=datetime(2026,10,26,18,58,42,tzinfo=timezone.utc)
        def attempt(q,t,valid=True):return {'query_id':q,'completed_at_utc':utc_text(t),
            'outcome':{'status':'valid' if valid else 'unavailable'}}
        baseline=attempt('CURRENT',at-timedelta(seconds=120))
        dated=attempt('DATED',at-timedelta(seconds=60))
        current=attempt('CURRENT',at)
        cases=[{'attempts':[baseline]}, {'attempts':[baseline,dated]},
            {'attempts':[baseline,dated,current],'pending':{'attempt_id':'unresolved'}},
            {'attempts':[baseline,dated,current],'stop_reason':'budget'},
            {'attempts':[baseline,attempt('DATED',at),current]},
            {'attempts':[baseline,dated,attempt('CURRENT',at,False)]},
            {'attempts':[attempt('CURRENT',at-timedelta(seconds=190)),
                attempt('DATED',at-timedelta(seconds=180)),attempt('CURRENT',at-timedelta(seconds=131))]},
            {'attempts':[baseline,dated,attempt('CURRENT',at+timedelta(seconds=1))]},
            {'attempts':[baseline,attempt('OTHER',at-timedelta(seconds=60)),current]}]
        for case in cases:
            with self.subTest(case=case):
                delivery,gate,_=self.stub({'pending':None,'stop_reason':None,**case})
                self.assertEqual(delivery.deliver_pending(),());gate.deliver_pending.assert_not_called()

    def test_valid_source_scope_opens_only_the_normal_gate(self):
        at=datetime(2026,10,26,18,58,42,tzinfo=timezone.utc)
        attempts=[{'query_id':q,'completed_at_utc':utc_text(at-timedelta(seconds=n)),
            'outcome':{'status':'valid'}} for q,n in [('CURRENT',120),('DATED',60),('CURRENT',0)]]
        delivery,gate,_=self.stub({'attempts':attempts,'pending':None,'stop_reason':None})
        self.assertEqual(delivery.deliver_pending(),('normal-delivery',))
        delivery.runtime.validate.assert_called_once();gate.deliver_pending.assert_called_once()


class ReplacementPreparationTests(unittest.TestCase):
    def profile(self,held_seconds=15,*,child=None):
        from mb_watchlist_coordinator.profile_runtime import BoundProfile
        at=datetime(2026,10,26,18,59,14,tzinfo=timezone.utc)
        p=BoundProfile.__new__(BoundProfile)
        p.runtime=SimpleNamespace(clock=lambda:at+timedelta(seconds=held_seconds),
            managed=SimpleNamespace(child=child))
        p._events=lambda:{'fault':{'data':{'exit_observed_at_utc':utc_text(at)}}}
        p.hold_until=None;p.monotonic=lambda:0
        p.original_ensure=Mock(return_value={'status':'STARTING'})
        return p

    def test_replacement_declares_future_slot_after_original_three_second_preparation(self):
        from mb_watchlist_coordinator.recovery_workers import next_future_slot
        p=self.profile();now=p.runtime.clock()
        result=p._ensure(start_allowed=True,resume_after_utc=utc_text(now))
        fence=datetime.fromisoformat(p.original_ensure.call_args.kwargs['resume_after_utc'])
        self.assertEqual(fence,now+timedelta(seconds=3))
        self.assertGreater(next_future_slot(fence),now+timedelta(seconds=3))
        self.assertEqual(result['status'],'STARTING')
        self.qualification_evidence={'full_hold_seconds':15,'replacement_preparation_seconds':3,
            'declared_future_slot_after_preparation':True,'deadline_renewed':False,
            'raw_audit_and_outage_rules_changed':False}

    def test_hold_is_never_shortened_to_make_room_for_preparation(self):
        p=self.profile(14.999999)
        value=p._ensure(start_allowed=True,resume_after_utc=utc_text(p.runtime.clock()))
        self.assertEqual(value['status'],'WAITING_FOR_PROFILE_HOLD')
        p.original_ensure.assert_not_called()

    def test_later_caller_fence_is_not_shortened(self):
        p=self.profile();future=p.runtime.clock()+timedelta(seconds=8)
        p._ensure(start_allowed=True,resume_after_utc=utc_text(future))
        self.assertEqual(p.original_ensure.call_args.kwargs['resume_after_utc'],utc_text(future))

    def test_existing_owned_replacement_does_not_renew_its_fence_or_start(self):
        p=self.profile(child=object());original=utc_text(p.runtime.clock())
        p._ensure(start_allowed=False,resume_after_utc=original)
        p.original_ensure.assert_called_once_with(start_allowed=False,resume_after_utc=original)

    def test_unchanged_native_worker_respects_preparation_fence_and_preserves_raw_outage(self):
        from test_hot_recovery_collector import HotRecoveryCollectorTests
        from mb_watchlist_coordinator.hot_recovery_collector import run_worker
        from mb_market_data.quote_journal_audit import audit_quote_journal
        case=HotRecoveryCollectorTests('runTest');case.setUp();self.addCleanup(case.doCleanups)
        case.now=case.at+timedelta(seconds=1.6)
        managed=ManagedRecoveryWorker(case.root/'workers',role='experimental_hot',
            command=(sys.executable,'-I','-B','-c','import time;time.sleep(20)'),binding=case.binding,
            clock=lambda:case.now,startup_seconds=3,stale_seconds=3)
        self.addCleanup(managed.stop_owned)
        managed.ensure(start_allowed=True,resume_after_utc=utc_text(case.now+timedelta(seconds=3)))
        managed.child.terminate();managed.child.wait(timeout=2)
        managed._reap_owned('synthetic_registration_child_exited')
        job=managed._job();stopped=[False];pauses=[0]
        case.now=case.at+timedelta(seconds=4.1)
        def pause(_):
            pauses[0]+=1
            if pauses[0]==1:
                self.assertFalse(case.calls)
                case.now=case.at+timedelta(seconds=6)
            else:stopped[0]=True
        run_worker(job['job_path'],case.settings,client_factory=case.factory,
            clock=lambda:case.now,stop_requested=lambda:stopped[0],sleep=pause)
        self.assertEqual(len(case.calls),1)
        self.assertEqual(case.store.acquisitions_in_replay_order()[0].scheduled_at_utc,
            case.at+timedelta(seconds=6))
        audit=audit_quote_journal(case.store.database_path,audited_at=case.now)
        self.assertFalse(audit.passed)
        missing=next(c for c in audit.channels if c.channel=='hot').missing_slot_ids
        self.assertEqual(len(missing),2)
        self.assertNotIn('hot:'+str(case.at+timedelta(seconds=6)),missing)
        self.qualification_evidence={'first_eligible_slot_utc':job['first_eligible_slot_utc'],
            'preparation_fence_utc':job['resume_after_utc'],'pre_fence_calls':0,
            'first_eligible_slot_acquired':True,'raw_earlier_outage_slots_retained':2,
            'scope':'Synthetic quote API and unchanged native worker/ledger/audit; separate elapsed authenticated proof required'}


class CooperativeCloseTests(unittest.TestCase):
    def run_scope(self,mode,*,cleanup_seconds=10):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        root=Path(temp.name);outer=root/'outer_controller';nonce='b'*32;preflight='a'*64
        now=datetime.now(timezone.utc);start=now-timedelta(seconds=719.5)
        schedule=OuterSchedule(utc_text(start-timedelta(seconds=60)),utc_text(start),utc_text(start+timedelta(seconds=720)))
        harness=OuterHarness(outer,schedule,nonce,entry_mode='manual_resume',
            preparation_submitted_at_utc=utc_text(now),expected_preflight_sha256=preflight)
        harness.bounds=OuterBounds(harness.bounds.active_end,cleanup_seconds=cleanup_seconds,report_seconds=1)
        path=root/'synthetic.json';path.write_text(json.dumps({'root':str(outer),'nonce':nonce,
            'preflight':preflight,'close_seconds':.8}))
        probe=Path(__file__).parent/'fixtures/recovery_cleanup_probe.py'
        def command(role):return (sys.executable,'-I','-B',str(probe),role,str(path))
        began=time.monotonic();result=harness.run(command(mode),reporter_command=command('report'))
        return outer,result,time.monotonic()-began

    def test_bound_native_controller_can_save_stop_after_half_second_without_force(self):
        root,result,elapsed=self.run_scope('cooperative')
        self.assertTrue((root/'cooperative-close.json').is_file())
        self.assertFalse(result['cleanup']['forced']);self.assertEqual(result['cleanup']['controller_returncode'],0)
        self.assertTrue(result['reporting_complete']);self.assertLess(elapsed,3)
        self.qualification_evidence={'cooperative_close_seconds':.8,'original_cleanup_limit_seconds':10,
            'controller_forced':False,'controller_returncode':0,'separate_reporting_complete':True,
            'scope':'Real owned synthetic child; no native profile goal is claimed by this lifecycle fixture'}

    def test_hung_controller_still_uses_one_original_cleanup_bound_with_force_reserve(self):
        root,result,elapsed=self.run_scope('hang',cleanup_seconds=1.2)
        self.assertTrue(result['cleanup']['forced']);self.assertTrue(result['cleanup']['scope_empty_observed'])
        self.assertEqual(result['stop_reason'],'active_deadline_ended')
        self.assertFalse((root/'cooperative-close.json').exists());self.assertLess(elapsed,2.5)


if __name__=='__main__':unittest.main()
