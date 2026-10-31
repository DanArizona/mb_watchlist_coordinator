from contextlib import closing
from datetime import datetime,timedelta,timezone
import json
import os
from pathlib import Path
import sqlite3
import time
import unittest

from daily_manual_fixture import CombinedFixture
from mb_watchlist_coordinator.daily_broker_admission import identity_proof
from mb_watchlist_coordinator.daily_identity_manual_controls import gate_command_id
from mb_watchlist_coordinator.daily_session import DailySession
from mb_watchlist_coordinator.daily_worker_view import DailyPublicationReader
from mb_watchlist_coordinator.integrated_identity import IdentityStopRequired
from mb_watchlist_coordinator.models import ProducerIntent,IntentType
from mb_watchlist_coordinator.operating_plan import BROKER_MANUAL_PROFILE,MANUAL_PROFILE,proposed_policy,validate_policy
from mb_watchlist_coordinator.sampling_requests import canonical,digest,plain
from test_integrated_identity import Response


class DailyManualIdentityTests(unittest.TestCase):
    def setUp(self):
        self.f=CombinedFixture(profile=BROKER_MANUAL_PROFILE);self.addCleanup(self.f.close)
        self.c,self.s=self.f.case,self.f.session

    def gate(self):return plain(self.s.gate.snapshot())['identity_gate']
    def admit(self,symbol='X000',**kwargs):
        cid=self.f.manual(symbol,**kwargs);self.f.pump();self.f.publish();return cid

    def direct(self,cid='bypass',symbol='X000'):
        return self.s.requests.submit_request(ProducerIntent(cid,'operator:masterbot',IntentType.ENSURE_PRESENT,
            frozenset({symbol}),self.c.now,expires_at=self.s.service.settings.publish_until,
            metadata={'sampling_channel':'hot','session_date':str(self.c.now.date())}),actor_id='operator:masterbot').event

    def test_pending_outside_request_makes_no_gui_provider_call_or_membership(self):
        cid=self.f.manual('X000')
        self.assertEqual(self.c.calls,[]);self.assertEqual(self.gate()['quote_permits'],0)
        self.assertEqual(self.f.feedback(cid)['status'],'PENDING')
        self.assertEqual(self.f.feedback(cid)['effective_group'],'absent')
        self.assertEqual(self.s.requests.events(),())

    def test_exact_identity_then_normal_request_publishes_nested_membership(self):
        cid=self.admit()
        self.assertEqual(self.c.calls,[['X000']]);self.assertEqual(self.gate()['quote_permits'],1)
        row=self.f.feedback(cid);self.assertEqual(row['status'],'EFFECTIVE')
        membership=self.c.store.latest_membership_revision_effective_at(self.c.now)
        self.assertTrue(all('X000'in getattr(membership,c+'_symbols')for c in('uni','focus','hot')))
        self.assertEqual(next(e for e in self.s.requests.events()if e.kind=='request').actor_id,'operator:masterbot')

    def test_opening_uni_promotion_still_needs_no_identity_call(self):
        cid=self.f.manual('IBM');self.f.publish()
        self.assertEqual(self.f.feedback(cid)['status'],'EFFECTIVE');self.assertFalse(self.c.calls)

    def test_outside_catalog_is_durably_blocked_before_provider(self):
        cid=self.f.manual('NOTINCATALOG')
        self.f.pump()
        self.assertEqual(self.f.feedback(cid)['detail'],'symbol_not_in_admission_catalog')
        self.assertFalse(self.c.calls)

    def test_common_backend_refuses_manual_catalog_presence_without_confirmation(self):
        self.assertEqual(self.direct().rejection_reason,'manual_identity_confirmation_required')

    def test_later_confirmation_does_not_rewrite_an_earlier_rejection(self):
        rejected=self.direct();self.admit()
        self.assertEqual(self.s.requests.events()[0],rejected)
        self.assertFalse(rejected.accepted)

    def test_cached_broker_approval_is_immutable(self):
        self.admit();proof=identity_proof(self.s.requests.admission)
        with self.assertRaises(TypeError):proof['approved_at']['X001']=self.c.now

    def test_lost_manual_receipt_reuses_exact_original_approval_reference(self):
        cid=self.f.manual('X000')
        self.s.gate.authorize(gate_command_id(cid),self.c.client)
        def crash(stage):
            if stage=='after_backend':raise RuntimeError('synthetic lost manual result')
        _,commands,_=self.s.manual._read()
        with self.assertRaises(RuntimeError):self.s.manual._apply(commands[cid],fault_hook=crash)
        self.f.advance();self.f.queue_nasdaq(['X001'])
        snap=plain(self.s.gate.snapshot())
        nid=next(k for k,v in snap['commands'].items()if v['command']['symbol']=='X001')
        self.s.gate.authorize(nid,self.c.client)
        self.s.manual.retry(cid);self.f.publish()
        self.assertEqual(self.f.feedback(cid)['status'],'EFFECTIVE')
        self.assertEqual(sum(e.kind=='request'and e.command_id==cid for e in self.s.requests.events()),1)

    def test_forty_mixed_outside_admissions_share_capacity_and_overflow_without_extra_call(self):
        for n in range(20):self.f.manual(f'X{n:03d}')
        self.f.queue_nasdaq([f'X{n:03d}'for n in range(20,40)])
        durations=[]
        for _ in range(40):
            began=time.monotonic();self.f.pump();durations.append(time.monotonic()-began);self.f.advance()
        self.f.publish()
        overflow=self.f.manual('X040');self.f.pump()
        self.assertEqual(self.f.feedback(overflow)['detail'],'session_shared_hot_capacity')
        state=self.s.requests.states()[-1]
        self.assertEqual(len(state.applied.hot),40);self.assertEqual(self.gate()['quote_permits'],40)
        self.assertEqual(len(self.c.calls),40)
        self.assertEqual(sum(r['producer_id']=='operator:masterbot'for r in state.active_requests),20)
        self.assertEqual(sum(r['producer_id']=='nasdaq-shared-daily'for r in state.active_requests),20)
        self.assertEqual(len(self.s.manual.snapshot()['members']['hot']),40)
        from unittest.mock import patch
        from mb_watchlist_coordinator.daily_collector import DailyCollectorSettings
        from mb_watchlist_coordinator.daily_epoch_collector import make_daily_collector
        from mb_market_data.quote_journal_audit import audit_quote_journal
        from test_daily_multisymbol import full_quotes
        anchor,real=self.c.now,datetime.now(timezone.utc)
        def clock():return anchor+(datetime.now(timezone.utc)-real)
        class Client:
            def quotes(inner,symbols,*,fields):return Response(symbols[0],body=full_quotes(symbols,clock()))
            def close(inner):pass
        settings=DailyCollectorSettings(str(self.c.journal),plain(self.s.service.identity),plain(self.s.binding),plain(self.s.claim),
            (self.c.now+timedelta(seconds=5)).isoformat(),(self.c.now+timedelta(seconds=15)).isoformat(),10,40)
        collector=make_daily_collector(settings,publication_session=self.s,client_factory=Client,clock=clock,activation_approved=True)
        ticks=[]
        class Clock(datetime):
            @classmethod
            def now(cls,tz=None):return clock().astimezone(tz or timezone.utc)
        try:
            collector.prepare(create=True)
            for _ in range(2):
                anchor=collector.next.scheduled_at+timedelta(milliseconds=50);self.c.now=anchor
                real=datetime.now(timezone.utc);began=time.monotonic()
                with patch('mb_market_data.schwab_quotes.datetime',Clock):collector.tick()
                ticks.append(time.monotonic()-began)
        finally:collector.close()
        audit=audit_quote_journal(self.c.journal,audited_at=clock())
        self.assertTrue(audit.passed,audit)
        with closing(sqlite3.connect(self.c.journal.as_uri()+'?mode=ro',uri=True))as c:
            hot=c.execute('SELECT count(*) FROM quote_acquisition WHERE channel="hot" AND requested_symbol_count=40').fetchone()[0]
            observations=c.execute('SELECT count(*) FROM quote_observation WHERE status="quote"').fetchone()[0]
        self.assertEqual(hot,2);self.assertEqual(observations,80)
        if os.environ.get('MB_MANUAL_IDENTITY_BURST_PROOF'):
            Path(os.environ['MB_MANUAL_IDENTITY_BURST_PROOF']).write_text(json.dumps({
                'result':'PASS','manual_admissions':20,'nasdaq_admissions':20,'hot_symbols':40,
                'identity_quote_permits':40,'overflow_extra_provider_calls':0,
                'maximum_logical_pump_elapsed_seconds':max(durations),
                'forty_symbol_native_hot_acquisitions':hot,'native_quote_observations':observations,
                'maximum_native_cycle_elapsed_seconds':max(ticks),'native_audit_passed':audit.passed,
                'native_dispatch_clock':'logical due slot plus actual elapsed UTC; original 0.75-second limit',
                'clock':'logical advance only; real SQLite and measured pump elapsed time',
                'provider_capacity_qualified':False,'full_day_capacity_qualified':False},indent=2)+'\n')

    def test_nasdaq_and_manual_reuse_one_exact_symbol_confirmation(self):
        mid=self.admit();self.f.queue_nasdaq(['X000']);self.f.advance();self.f.pump();self.f.publish()
        self.assertEqual(self.c.calls,[['X000']]);self.assertEqual(self.gate()['quote_permits'],1)
        self.s.manual.submit('withdraw',request_id=mid);self.f.publish()
        self.assertEqual(self.f.feedback(mid)['effective_group'],'hot')
        self.assertIn('nasdaq-shared-daily',self.f.feedback(mid)['other_sources'])

    def test_nasdaq_confirmation_is_reused_by_later_manual_command(self):
        self.f.queue_nasdaq(['X000']);self.f.pump()
        mid=self.admit();self.assertEqual(self.f.feedback(mid)['identity_status'],'approved')
        self.assertEqual(len(self.c.calls),1)

    def test_both_sources_share_original_two_second_spacing(self):
        mid=self.f.manual('X000');self.f.pump()
        self.f.queue_nasdaq(['X001']);self.f.pump()
        self.assertEqual(self.c.calls,[['X000']])
        self.f.advance();self.f.pump()
        self.assertEqual(self.c.calls,[['X000'],['X001']])
        events=self.gate()['events'];reservations=[e for e in events if e['kind']=='reservation']
        from mb_watchlist_coordinator.sampling_requests import timestamp
        self.assertGreaterEqual((timestamp(reservations[1]['at_utc'])-timestamp(reservations[0]['at_utc'])).total_seconds(),2)

    def test_pending_withdrawal_prevents_broker_dispatch_and_admission(self):
        mid=self.f.manual('X000');wid=self.s.manual.submit('withdraw',request_id=mid)
        self.f.pump();self.f.publish()
        self.assertEqual(self.f.feedback(mid)['status'],'WITHDRAWN')
        self.assertEqual(self.f.feedback(wid)['symbol'],'X000')
        self.assertFalse(self.c.calls);self.assertFalse(self.s.requests.states()[-1].active_requests)

    def test_withdrawal_during_lookup_retains_charge_but_never_admits(self):
        mid=self.f.manual('X000');controls=self.s.manual
        class Client:
            def quotes(inner,symbols,*,fields):
                controls.submit('withdraw',request_id=mid)
                return Response(symbols[0])
        self.s.gate.deliver_pending(client=Client());self.f.publish()
        self.assertEqual(self.gate()['quote_permits'],1)
        self.assertEqual(self.f.feedback(mid)['status'],'WITHDRAWN')
        self.assertFalse(self.s.requests.states()[-1].active_requests)

    def test_unknown_charged_lookup_is_blocked_and_never_retried(self):
        mid=self.f.manual('X000')
        def crash(stage):
            if stage=='after_identity_reservation':raise RuntimeError('synthetic lost execution')
        with self.assertRaises(RuntimeError):self.s.gate.deliver_pending(client=self.c.client,fault_hook=crash)
        self.f.pump();self.s.manual.retry(mid)
        self.assertEqual(self.f.feedback(mid)['status'],'BLOCKED')
        self.assertEqual(self.f.feedback(mid)['detail'],'identity_outcome_unknown_no_retry')
        self.assertEqual(self.gate()['quote_permits'],1);self.assertFalse(self.c.calls)
        later=self.f.manual('X000');self.f.pump()
        self.assertEqual(self.f.feedback(later)['detail'],'identity_symbol_unknown_no_retry')
        self.assertEqual(self.gate()['quote_permits'],1);self.assertFalse(self.c.calls)

    def test_unconfirmed_alias_is_blocked_without_substitution(self):
        mid=self.f.manual('X000')
        class Client:
            def quotes(inner,symbols,*,fields):return Response('X001')
        self.s.gate.deliver_pending(client=Client())
        self.assertEqual(self.f.feedback(mid)['detail'],'identity_unconfirmed')
        self.assertFalse(self.s.requests.states()[-1].active_requests)

    def test_provider_rate_limit_latches_both_sources_without_second_call(self):
        self.f.manual('X000');self.f.queue_nasdaq(['X001']);calls=[]
        class Client:
            def quotes(inner,symbols,*,fields):calls.append(symbols);return Response(symbols[0],status=429)
        with self.assertRaises(IdentityStopRequired):self.s.gate.deliver_pending(client=Client())
        with self.assertRaises(IdentityStopRequired):self.s.gate.deliver_pending(client=Client())
        self.assertEqual(len(calls),1);self.assertTrue(self.gate()['provider_stop_required'])

    def test_per_symbol_budget_is_shared_across_manual_and_nasdaq(self):
        class Client:
            def quotes(inner,symbols,*,fields):return Response('WRONG')
        for n in range(3):
            self.f.manual('X000');self.s.gate.deliver_pending(client=Client());self.f.advance()
        self.f.queue_nasdaq(['X000']);self.s.gate.deliver_pending(client=Client())
        self.assertEqual(self.gate()['quote_permits'],3)
        self.assertIn('symbol_identity_budget_exhausted',self.gate()['dispositions'].values())

    def test_full_shared_hot_capacity_blocks_queue_without_extra_lookup(self):
        for symbol in self.c.universe_symbols_override[:40]:self.f.manual(symbol)
        mid=self.f.manual('X000');self.f.pump()
        self.assertEqual(self.f.feedback(mid)['detail'],'session_shared_hot_capacity');self.assertFalse(self.c.calls)

    def test_outside_own_demotion_and_restriction_reuse_original_identity(self):
        mid=self.admit();did=self.s.manual.submit('demote',request_id=mid,target='focus');self.f.publish()
        self.assertEqual(self.gate()['quote_permits'],1)
        self.c.now+=timedelta(seconds=125);self.f.publish()
        self.assertEqual(self.f.feedback(did)['effective_group'],'focus')
        lid=self.s.manual.submit('limit',symbol='X000',target='uni');self.f.publish()
        self.assertEqual(self.f.feedback(lid)['effective_group'],'uni')

    def test_restart_retains_manual_queue_charged_lookup_and_response(self):
        mid=self.admit();before=self.gate()
        self.s.close();reopened=DailySession(self.c.settings,self.c.catalog,clock=lambda:self.c.now)
        self.c.session=self.s=self.f.session=reopened;reopened.attach(create=False,publication_approved=True)
        self.assertEqual(self.gate(),before)
        new=self.f.manual('X000');self.f.pump();self.f.publish()
        self.assertEqual(self.f.feedback(new)['status'],'EFFECTIVE');self.assertEqual(len(self.c.calls),1)

    def test_missing_or_changed_identity_evidence_fails_closed(self):
        self.admit();path=self.s.root/'identity.sqlite3';moved=path.with_suffix('.retained')
        path.rename(moved)
        try:
            with self.assertRaises(ValueError):self.s.manual.snapshot()
        finally:moved.rename(path)
        with closing(sqlite3.connect(path))as c,c:
            sequence,raw=c.execute('SELECT sequence,payload FROM identity_event WHERE sequence=2').fetchone()
            value=json.loads(raw);value['outcome']['response']={'WRONG':{}}
            body=dict(value);body.pop('event_sha256');value['event_sha256']=digest(body)
            c.execute('UPDATE identity_event SET payload=? WHERE sequence=?',(canonical(value),sequence))
        with self.assertRaises(ValueError):self.s.manual.snapshot()

    def test_worker_reader_reconstructs_exact_shared_broker_gate(self):
        self.admit()
        reader=DailyPublicationReader(self.c.settings,str(self.c.root/'catalog'),binding=self.s.binding,claim=self.s.claim,
            publication_binding=plain(self.s.service.identity),fence=lambda:None,clock=lambda:self.c.now)
        self.assertEqual(reader.gate.snapshot(),self.s.gate.snapshot())
        self.assertEqual(reader.requests.identity,self.s.requests.identity)

    def test_new_profile_cannot_rebind_sealed_identity_limits_or_p92_scope(self):
        old=proposed_policy(MANUAL_PROFILE)
        self.assertEqual(old['manual_controls']['promotion_scope'],'opening_uni_only')
        self.assertEqual(digest(old),'a7a2b7d9c562e32b9cf327e0269d3b9bbc6734170f40cd16a042e28e0037ae87')
        value=proposed_policy(BROKER_MANUAL_PROFILE);self.assertEqual(validate_policy(value),value)
        value['limits']['maximum_identity_quote_calls']=121
        with self.assertRaises(ValueError):validate_policy(value)

    def test_public_review_matches_the_shared_broker_publication_identity(self):
        from mb_watchlist_coordinator.daily_operating_review import build_operating_review
        review=build_operating_review(self.c.r0,self.c.r1,journal=self.c.journal,catalog=self.c.root/'catalog',
            state_root=self.c.settings.state_root,ecfg=self.c.root/'synthetic-unused.ecfg',clock=lambda:self.c.now,
            policy_profile=BROKER_MANUAL_PROFILE)
        self.assertEqual(review['configuration']['collector']['publication_binding'],plain(self.s.service.identity))
