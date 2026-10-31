from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from datetime import timedelta
import json
from pathlib import Path
import sqlite3
import unittest

from daily_manual_fixture import CombinedFixture
from mb_watchlist_coordinator.daily_collector import DailyCollectorSettings
from mb_watchlist_coordinator.daily_epoch_collector import make_daily_collector
from mb_watchlist_coordinator.daily_session import DailySession
from mb_watchlist_coordinator.daily_worker_view import DailyPublicationReader
from mb_watchlist_coordinator.manual_membership import ManualMembershipControls
from mb_watchlist_coordinator.models import ProducerIntent,IntentType
from mb_watchlist_coordinator.operating_plan import MANUAL_PROFILE,MULTI_PROFILE,proposed_policy,validate_policy
from mb_watchlist_coordinator.sampling_requests import digest,plain


class DailyManualTests(unittest.TestCase):
    def setUp(self):
        self.f=CombinedFixture();self.addCleanup(self.f.close)
        self.c,self.s=self.f.case,self.f.session

    def test_new_profile_is_sealed_and_original_profile_hashes_unchanged(self):
        self.assertEqual(digest(proposed_policy(MULTI_PROFILE)),'e3e7d2449214928e7094735ba1f5cbed641dba37c61b0ea085b86e827f5944b6')
        self.assertEqual(digest(proposed_policy()),'df436169ad6674deb906c41706eaa8323b63dee8c7fb5232364e38d5770751db')
        p=proposed_policy(MANUAL_PROFILE);self.assertEqual(validate_policy(p),p)
        p['limits']['maximum_distinct_hot_symbols_per_session']=41
        with self.assertRaises(ValueError):validate_policy(p)

    def test_same_session_accepts_nasdaq_and_manual_with_one_native_publisher(self):
        mid=self.f.manual('IBM');self.f.queue_nasdaq(['X000']);self.f.pump();self.f.publish()
        state=self.s.requests.states()[-1]
        self.assertEqual({r['producer_id']for r in state.active_requests},{'operator:masterbot','nasdaq-shared-daily'})
        self.assertEqual(set(self.c.store.latest_membership_revision_effective_at(self.c.now).hot_symbols),{'IBM','X000'})
        self.assertEqual(self.f.feedback(mid)['status'],'EFFECTIVE')

    def test_own_withdrawal_preserves_nasdaq_demand_for_same_symbol(self):
        mid=self.f.manual('IBM');self.f.queue_nasdaq(['IBM']);self.f.pump();self.f.publish()
        self.s.manual.submit('withdraw',request_id=mid);self.f.publish()
        self.assertEqual(self.s.requests.states()[-1].reasons_for('IBM','hot'),(('nasdaq-shared-daily',next(r['intent_id']for r in self.s.requests.states()[-1].active_requests)),))
        self.assertEqual(self.f.feedback(mid)['effective_group'],'hot')

    def test_forty_manual_hot_requests_leave_no_separate_nasdaq_allowance(self):
        for symbol in list(self.c.universe_symbols_override)[:40]:self.f.manual(symbol)
        self.f.queue_nasdaq(['X000']);self.f.pump();self.f.publish()
        rejected=[e for e in self.s.requests.events()if e.kind=='request'and not e.accepted]
        self.assertEqual(rejected[-1].rejection_reason,'session_shared_hot_capacity')
        self.assertEqual(len(self.s.requests.states()[-1].applied.hot),40)

    def test_nasdaq_admission_and_manual_admission_share_last_capacity_slot(self):
        for symbol in self.c.universe_symbols_override[:39]:self.f.manual(symbol)
        self.f.queue_nasdaq(['X000']);self.f.pump()
        mid=self.f.manual(self.c.universe_symbols_override[39])
        self.assertEqual(self.f.feedback(mid)['detail'],'session_shared_hot_capacity')
        self.assertEqual(self.s.manual.snapshot()['shared_capacity']['hot_remaining'],0)

    def test_withdrawal_or_restriction_does_not_reset_distinct_session_budget(self):
        ids=[self.f.manual(s)for s in self.c.universe_symbols_override[:40]]
        self.s.manual.submit('withdraw',request_id=ids[0])
        self.s.manual.submit('limit',symbol=self.c.universe_symbols_override[1],target='uni')
        mid=self.f.manual(self.c.universe_symbols_override[40])
        self.assertEqual(self.f.feedback(mid)['detail'],'session_shared_hot_capacity')

    def test_duplicate_symbol_across_sources_consumes_one_capacity_slot(self):
        self.f.manual('IBM');self.f.queue_nasdaq(['IBM']);self.f.pump()
        for symbol in self.c.universe_symbols_override[1:40]:self.f.manual(symbol)
        self.assertEqual(len(self.s.requests.states()[-1].applied.hot),40)

    def test_focus_capacity_is_shared_even_for_symbols_already_in_uni(self):
        for symbol in self.c.universe_symbols_override[2:42]:self.f.manual(symbol,target='focus')
        mid=self.f.manual(self.c.universe_symbols_override[42],target='focus')
        self.assertEqual(self.f.feedback(mid)['detail'],'session_shared_focus_capacity')
        self.assertEqual(len(self.s.requests.states()[-1].applied.focus),42)

    def test_manual_outside_uni_is_blocked_at_common_backend_even_without_gui(self):
        intent=ProducerIntent('bypass','operator:masterbot',IntentType.ENSURE_PRESENT,frozenset({'X000'}),self.c.now,
            metadata={'sampling_channel':'hot','session_date':str(self.c.now.date())})
        event=self.s.requests.submit_request(intent,actor_id='operator:masterbot').event
        self.assertEqual(event.rejection_reason,'manual_identity_confirmation_required')

    def test_foreign_source_and_foreign_withdrawal_are_rejected(self):
        self.f.queue_nasdaq(['X000']);self.f.pump()
        nid=next(e.command_id for e in self.s.requests.events()if e.accepted and e.kind=='request')
        event=self.s.requests.cancel_request('foreign',owner_id='nasdaq-shared-daily',request_id=nid,actor_id='operator:masterbot').event
        self.assertEqual(event.rejection_reason,'actor_does_not_own_request')

    def test_concurrent_sources_cannot_both_take_fortieth_slot(self):
        for symbol in self.c.universe_symbols_override[:39]:self.f.manual(symbol)
        def submit(index):
            owner=['operator:masterbot','nasdaq-shared-daily'][index]
            symbol=self.c.universe_symbols_override[39+index]
            return self.s.requests.submit_request(ProducerIntent('race-'+str(index),owner,IntentType.ENSURE_PRESENT,
                frozenset({symbol}),self.c.now,metadata={'sampling_channel':'hot','session_date':str(self.c.now.date())}),actor_id=owner).event
        # The shared ledger transaction itself is exercised here; the separate
        # gate/owned-controller checks establish Nasdaq broker provenance.
        with ThreadPoolExecutor(max_workers=2)as pool:events=list(pool.map(submit,range(2)))
        self.assertEqual(sum(e.accepted for e in events),1)
        self.assertEqual(len(self.s.requests.states()[-1].applied.hot),40)

    def test_worker_reader_reconstructs_exact_shared_admission_identity(self):
        reader=DailyPublicationReader(self.c.settings,str(self.c.root/'catalog'),binding=self.s.binding,
            claim=self.s.claim,publication_binding=plain(self.s.service.identity),fence=lambda:None,clock=lambda:self.c.now)
        self.assertEqual(reader.requests.identity,self.s.requests.identity)
        self.assertEqual(reader.requests.admission.allowed_sources,{'operator:masterbot','nasdaq-shared-daily'})

    def test_original_ledger_resume_retains_manual_receipts_and_shared_budget(self):
        mid=self.f.manual('IBM');self.f.publish();before=self.s.manual.snapshot()
        self.s.close()
        reopened=DailySession(self.c.settings,self.c.catalog,clock=lambda:self.c.now)
        self.c.session=self.s=reopened;self.s.attach(create=False,publication_approved=True)
        self.assertEqual(self.s.manual.snapshot(),before)
        self.assertEqual(self.f.feedback(mid)['status'],'EFFECTIVE')

    def test_missing_manual_ledger_is_not_recreated_on_resume(self):
        path=self.s.root/'manual.sqlite3';self.s.close();path.unlink()
        reopened=DailySession(self.c.settings,self.c.catalog,clock=lambda:self.c.now)
        self.c.session=reopened
        with self.assertRaises(ValueError):reopened.attach(create=False,publication_approved=True)
        self.assertFalse(path.exists())

    def test_shared_capacity_descriptor_is_immutable(self):
        object.__setattr__(self.s.requests.admission,'maximum_hot',41)
        with self.assertRaises(ValueError):self.f.manual('IBM')

    def test_manual_demotion_feedback_shows_a_restriction_on_its_replacement(self):
        mid=self.f.manual('IBM');self.f.publish()
        lowered=self.s.manual.submit('demote',request_id=mid,target='focus')
        self.s.manual.submit('limit',symbol='IBM',target='uni');self.f.publish()
        self.assertEqual(self.f.feedback(lowered)['status'],'BLOCKED')
        self.assertEqual(self.f.feedback(lowered)['effective_group'],'uni')

    def test_review_and_attachment_compute_identical_shared_publication_identity(self):
        from mb_watchlist_coordinator.daily_operating_review import build_operating_review
        review=build_operating_review(self.c.r0,self.c.r1,journal=self.c.journal,catalog=self.c.root/'catalog',
            state_root=self.c.settings.state_root,ecfg=self.c.root/'synthetic-unused.ecfg',clock=lambda:self.c.now,
            policy_profile=MANUAL_PROFILE)
        self.assertEqual(review['configuration']['collector']['publication_binding'],plain(self.s.service.identity))

    def test_manual_policy_flags_cannot_be_silently_rebound(self):
        p=proposed_policy(MANUAL_PROFILE);p['manual_controls']['actor_id']='nasdaq-shared-daily'
        with self.assertRaises(ValueError):validate_policy(p)

    def test_cleared_limit_reveals_existing_source_demand_without_new_identity_quote(self):
        self.f.manual('IBM');self.f.queue_nasdaq(['IBM']);self.f.pump();self.f.publish()
        calls=len(self.c.calls)
        cap=self.s.manual.submit('limit',symbol='IBM',target='uni');self.f.publish()
        self.s.manual.submit('clear_limit',symbol='IBM',request_id=cap);self.f.publish()
        self.assertEqual(len(self.c.calls),calls)
        self.assertEqual(self.c.store.latest_membership_revision_effective_at(self.c.now).hot_symbols,('IBM',))
