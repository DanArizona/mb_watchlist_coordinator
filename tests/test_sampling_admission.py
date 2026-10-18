from __future__ import annotations

import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import FrozenInstanceError, replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from mb_watchlist_coordinator.models import IntentType, ProducerIntent
from mb_watchlist_coordinator.nasdaq_sampling import HaltProducerSettings, HaltSnapshot, NasdaqSamplingProducer
from mb_watchlist_coordinator.sampling_admission import AdmissionPolicy
from mb_watchlist_coordinator.sampling_policy import SamplingPolicy
from mb_watchlist_coordinator.sampling_projection import SamplingMembership
from mb_watchlist_coordinator.sampling_request_store import SamplingRequestStore, RequestConflictError
from mb_watchlist_coordinator.sampling_requests import baseline_payload, digest, plain, replay_requests


ET = ZoneInfo('America/New_York')
# Logical publication must remain in the future relative to SQLite's actual
# publication clock, including when this review is run on a later date.
START = datetime.combine(datetime.now(ET).date()+timedelta(days=1),
                         datetime.min.time().replace(hour=10), ET).astimezone(timezone.utc)
BASELINE = SamplingMembership(frozenset({'AAPL', 'SPY'}), frozenset({'SPY'}), frozenset())
ADMISSION = AdmissionPolicy('synthetic-identity-catalog-v1', frozenset({'MSFT', 'NVDA', 'AMD'}),
                            frozenset({'manual', 'nasdaq', 'algorithm'}), 2, 'session')
POLICY = SamplingPolicy('admin', 2, 4, 'immediate_cap')


def halt_row(symbol='MSFT', seconds=1):
    at=(START+timedelta(seconds=seconds)).astimezone(ET)
    return {'symbol':symbol,'halt_date':at.strftime('%m/%d/%Y'),
            'halt_time':at.strftime('%H:%M:%S.%f'),'reason_code':'LUDP'}


def make_request(at=START, *, owner='manual', rid='m1', symbols=('MSFT',), target='hot', **kwargs):
    return ProducerIntent(rid, owner, IntentType.ENSURE_PRESENT, frozenset(symbols), at,
        reason='Synthetic outside-opening-Uni request', source_event_id='synthetic-' + rid,
        metadata={'session_date': at.date().isoformat(), 'sampling_channel': target}, **kwargs)


class AdmissionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name); self.clock = [START]
        self.store = self.reopen(); self.store.initialize()

    def reopen(self, **kw):
        args = dict(session_date=START.date(), baseline=BASELINE, policy=POLICY,
                    admission=ADMISSION, clock=lambda: self.clock[0]); args.update(kw)
        return SamplingRequestStore(self.folder/'requests.sqlite3', **args)

    def submit(self, **kw):
        value = make_request(self.clock[0], **kw)
        return self.store.submit_request(value, actor_id=value.producer_id)

    def advance(self, seconds, tick=True):
        self.clock[0] = START + timedelta(seconds=seconds)
        if tick: self.store.tick('tick-' + str(seconds))

    def cancel(self, owner='manual', rid='m1', cid='cancel'):
        return self.store.cancel_request(cid, owner_id=owner, request_id=rid, actor_id=owner)

    def test_uni_only_inclusion_does_not_add_focus_or_hot(self):
        self.submit(target='uni')
        state = self.store.states()[-1]
        self.assertEqual(state.applied, replace(BASELINE, uni=BASELINE.uni | {'MSFT'}))
        self.assertEqual(state.reasons_for('MSFT', 'uni'), (('manual', 'm1'),))
        self.assertEqual(state.reasons_for('MSFT', 'focus'), ())

    def test_focus_admission_adds_parent_uni_without_hot(self):
        self.submit(target='focus')
        state = self.store.states()[-1]
        self.assertEqual(state.applied.uni, BASELINE.uni | {'MSFT'})
        self.assertEqual(state.applied.focus, {'SPY', 'MSFT'})
        self.assertFalse(state.applied.hot)

    def test_hot_admission_adds_all_groups_and_preserves_opening_baseline(self):
        opening = baseline_payload(START.date(), BASELINE, POLICY, ADMISSION)
        self.submit()
        state = self.store.states()[-1]
        self.assertEqual(state.applied.hot, {'MSFT'})
        self.assertEqual(state.applied.focus, {'SPY', 'MSFT'})
        self.assertEqual(self.store.baseline, BASELINE)
        self.assertEqual(self.store.identity, opening)
        self.assertEqual(self.store.states()[0].applied, BASELINE)
        origin = state.session_additions[0]
        self.assertEqual((origin['symbol'], origin['producer_id'], origin['request_id']), ('MSFT', 'manual', 'm1'))
        self.assertEqual(origin['request_event_sha256'], self.store.events()[0].event_sha256)

    def test_three_sources_withdraw_independently_then_demotion_keeps_uni(self):
        for owner in ('manual', 'nasdaq', 'algorithm'): self.submit(owner=owner, rid=owner)
        for owner in ('manual', 'nasdaq'): self.cancel(owner, owner, 'cancel-' + owner)
        self.assertEqual(self.store.states()[-1].reasons_for('MSFT', 'hot'), (('algorithm', 'algorithm'),))
        self.cancel('algorithm', 'algorithm', 'last')
        self.advance(3)
        self.assertEqual(self.store.states()[-1].applied.hot, {'MSFT'})
        self.advance(4)
        state = self.store.states()[-1]
        self.assertFalse(state.applied.hot)
        self.assertEqual(state.applied.focus, BASELINE.focus)
        self.assertEqual(state.applied.uni, BASELINE.uni | {'MSFT'})
        self.assertEqual(len(state.session_additions), 1)

    def test_expired_request_retains_uni_and_admission_origin(self):
        self.submit(expires_at=START+timedelta(seconds=5))
        origin = self.store.states()[-1].session_additions
        self.advance(5); self.advance(7)
        self.assertEqual(self.store.states()[-1].applied.uni, BASELINE.uni | {'MSFT'})
        self.assertFalse(self.store.states()[-1].applied.hot)
        self.assertEqual(self.store.states()[-1].session_additions, origin)

    def test_future_request_reserves_capacity_but_does_not_admit_early(self):
        self.submit(effective_from=START+timedelta(seconds=10))
        self.assertEqual(self.store.states()[-1].applied, BASELINE)
        self.advance(12)
        state = self.store.states()[-1]
        self.assertEqual(state.applied.hot, {'MSFT'})
        self.assertEqual(state.session_additions[0]['admitted_at_utc'], self.clock[0].isoformat())

    def test_cancelled_future_request_never_admits_on_retry(self):
        value = make_request(effective_from=START+timedelta(seconds=10))
        self.store.submit_request(value, actor_id='manual'); self.cancel()
        self.advance(12)
        retry = self.store.submit_request(value, actor_id='manual')
        self.assertFalse(retry.inserted)
        self.assertEqual(self.store.states()[-1].applied, BASELINE)
        self.assertFalse(self.store.states()[-1].session_additions)

    def test_outage_over_entire_future_lifetime_does_not_invent_admission(self):
        self.submit(effective_from=START+timedelta(seconds=2), expires_at=START+timedelta(seconds=4))
        self.advance(8)
        self.assertEqual(self.store.states()[-1].applied, BASELINE)
        self.assertFalse(self.store.states()[-1].session_additions)

    def test_duplicate_sources_and_retries_use_one_capacity_slot(self):
        first = self.submit()
        self.submit(owner='nasdaq', rid='n1')
        self.assertEqual(self.submit().event, first.event)
        self.submit(rid='n2', symbols=('NVDA',))
        self.assertEqual(len(self.store.states()[-1].session_additions), 2)
        refused = self.submit(rid='third', symbols=('AMD',)).event
        self.assertEqual(refused.rejection_reason, 'session_admission_capacity')
        self.assertEqual(self.reopen().events()[-1], refused)

    def test_capacity_reserves_future_requests_and_cancel_releases_unadmitted_slot(self):
        self.submit(symbols=('MSFT','NVDA'), effective_from=START+timedelta(seconds=10))
        self.assertEqual(self.submit(rid='blocked', symbols=('AMD',)).event.rejection_reason, 'session_admission_capacity')
        self.cancel()
        self.assertTrue(self.submit(rid='admit-amd', symbols=('AMD',)).event.accepted)
        self.assertEqual(self.store.states()[-1].applied.uni, BASELINE.uni | {'AMD'})

    def test_expired_future_reservation_releases_capacity_without_admission(self):
        self.submit(symbols=('MSFT','NVDA'), effective_from=START+timedelta(seconds=2), expires_at=START+timedelta(seconds=3))
        self.advance(4, tick=False)
        self.assertTrue(self.submit(rid='later', symbols=('AMD',)).event.accepted)
        self.assertEqual(self.store.states()[-1].applied.uni, BASELINE.uni | {'AMD'})

    def test_withdrawal_does_not_release_capacity_of_an_admitted_symbol(self):
        self.submit(symbols=('MSFT','NVDA')); self.cancel(); self.advance(10)
        self.assertEqual(self.submit(rid='third', symbols=('AMD',)).event.rejection_reason, 'session_admission_capacity')

    def test_catalog_rejection_is_all_or_nothing_and_durable(self):
        value = self.submit(symbols=('MSFT','UNKNOWN')).event
        self.assertEqual(value.rejection_reason, 'symbol_not_in_admission_catalog')
        self.assertEqual(self.reopen().states()[-1].applied, BASELINE)

    def test_unpermitted_source_and_foreign_actor_are_rejected(self):
        self.assertEqual(self.submit(owner='untrusted').event.rejection_reason, 'source_not_permitted')
        result = self.store.submit_request(make_request(), actor_id='nasdaq')
        self.assertEqual(result.event.rejection_reason, 'actor_does_not_own_request')
        self.assertEqual(self.store.states()[-1].applied, BASELINE)

    def test_foreign_withdrawal_cannot_remove_other_source(self):
        self.submit(owner='nasdaq')
        result = self.store.cancel_request('foreign', owner_id='nasdaq', request_id='m1', actor_id='manual')
        self.assertEqual(result.event.rejection_reason, 'actor_does_not_own_request')
        self.assertEqual(self.store.states()[-1].applied.hot, {'MSFT'})

    def test_preexisting_cap_on_outside_symbol_does_not_admit_it(self):
        self.store.restrict_symbol('cap', symbol='MSFT', max_group='uni', actor_id='admin')
        self.assertEqual(self.store.states()[-1].applied, BASELINE)
        self.submit()
        self.assertEqual(self.store.states()[-1].applied, replace(BASELINE, uni=BASELINE.uni | {'MSFT'}))
        self.store.clear_restriction('clear', symbol='MSFT', restriction_id='cap', actor_id='admin')
        self.assertEqual(self.store.states()[-1].applied.hot, {'MSFT'})

    def test_cap_clear_cannot_restore_withdrawn_demand_and_uni_survives(self):
        self.submit()
        self.store.restrict_symbol('cap', symbol='MSFT', max_group='uni', actor_id='admin')
        self.cancel()
        self.store.clear_restriction('clear', symbol='MSFT', restriction_id='cap', actor_id='admin')
        self.assertFalse(self.store.states()[-1].applied.hot)
        self.assertIn('MSFT', self.store.states()[-1].applied.uni)

    def test_ordinary_source_cannot_cap_new_symbol(self):
        result = self.store.restrict_symbol('cap', symbol='MSFT', max_group='uni', actor_id='manual')
        self.assertEqual(result.event.rejection_reason, 'not_restriction_authority')
        self.assertEqual(self.store.states()[-1].applied, BASELINE)

    def test_restart_reconstructs_every_admission_checkpoint_and_timers(self):
        self.submit(); self.advance(1); self.cancel(); self.advance(2)
        first = [s.payload() for s in self.store.states()]
        self.assertEqual(first, [s.payload() for s in self.reopen().states()])
        self.assertEqual(first, [s.payload() for s in replay_requests(START.date(), BASELINE,
            self.store.events(), policy=POLICY, admission=ADMISSION)])

    def test_new_session_does_not_inherit_prior_admissions(self):
        self.submit()
        new = SamplingRequestStore(self.folder/'tomorrow.sqlite3', session_date=START.date()+timedelta(days=1),
            baseline=BASELINE, policy=POLICY, admission=ADMISSION)
        new.initialize()
        self.assertEqual(new.states()[-1].applied, BASELINE)
        self.assertFalse(new.states()[-1].session_additions)

    def test_changed_catalog_sources_capacity_or_mode_cannot_reopen_ledger(self):
        self.submit()
        for change in ({'max_additional_symbols':3}, {'catalog_id':'other'},
                       {'catalog_symbols':frozenset({'MSFT'})}, {'allowed_sources':frozenset({'manual'})}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.reopen(admission=replace(ADMISSION, **change)).initialize()
        with self.assertRaises(ValueError): self.reopen(admission=None).initialize()
        self.assertEqual(len(self.store.events()),1)

    def test_configuration_and_admission_origin_are_immutable(self):
        self.submit()
        with self.assertRaises(FrozenInstanceError): ADMISSION.max_additional_symbols=99
        with self.assertRaises(TypeError): self.store.states()[-1].session_additions[0]['symbol']='OTHER'
        self.store.admission=replace(ADMISSION,max_additional_symbols=99)
        with self.assertRaises(ValueError): self.store.events()

    def test_conflicting_retry_does_not_replace_admitted_origin(self):
        self.submit()
        with self.assertRaises(RequestConflictError): self.submit(target='uni')
        self.assertEqual(len(self.store.events()),1)

    def test_parallel_admissions_cannot_overbook_the_session_limit(self):
        # Three distinct contenders, only two available places, one serialized ledger.
        def append(symbol):
            return self.reopen().submit_request(make_request(rid=symbol,symbols=(symbol,)),actor_id='manual')
        with ThreadPoolExecutor(max_workers=3) as pool:
            events=[r.event for r in pool.map(append,('MSFT','NVDA','AMD'))]
        self.assertEqual(sum(e.accepted for e in events),2)
        self.assertEqual(len(self.store.states()[-1].session_additions),2)
        self.assertEqual(len(self.store.events()),3)

    def test_modified_receipt_or_identity_is_detected(self):
        self.submit()
        with closing(sqlite3.connect(self.store.path)) as c,c:
            c.execute("UPDATE request_event SET actor_id='nasdaq' WHERE sequence=1")
        with self.assertRaises(ValueError): self.reopen().states()

    def test_invalid_admission_settings_are_refused(self):
        for changes in ({'catalog_symbols':frozenset()}, {'catalog_symbols':frozenset({'msft'})},
                        {'catalog_symbols':'MSFT'}, {'allowed_sources':'manual'},
                        {'allowed_sources':frozenset({'__coordinator__'})}, {'catalog_id':''},
                        {'max_additional_symbols':True}, {'max_additional_symbols':-1},
                        {'uni_retention':'forever'}):
            with self.subTest(changes=changes),self.assertRaises(ValueError): replace(ADMISSION,**changes)

    def test_fixed_uni_legacy_mode_remains_unchanged(self):
        old=SamplingRequestStore(self.folder/'legacy.sqlite3',session_date=START.date(),baseline=BASELINE,clock=lambda:START)
        old.initialize()
        self.assertEqual(old.submit_request(make_request(),actor_id='manual').event.rejection_reason,'outside_fixed_uni')
        with self.assertRaises(ValueError): old.submit_request(make_request(target='uni'),actor_id='manual')
        self.assertNotIn('admission',old.identity)
        self.assertNotIn('session_additions',old.states()[-1].payload())

    def test_nasdaq_outside_uni_uses_common_admission_and_durable_delivery(self):
        p=NasdaqSamplingProducer(self.folder/'nasdaq.sqlite3',request_store=self.store,
            settings=HaltProducerSettings('nasdaq',('LUDP','M'),'regular_close',True),clock=lambda:self.clock[0])
        p.initialize()
        p.record_snapshot(HaltSnapshot('baseline',START,'CURRENT',digest([]),(),{'synthetic':True}))
        self.clock[0]+=timedelta(seconds=2)
        row=halt_row()
        p.record_snapshot(HaltSnapshot('new',self.clock[0],'CURRENT',digest(row),(row,),{'synthetic':True}))
        def interrupted(_): raise RuntimeError('after request commit')
        with self.assertRaises(RuntimeError): p.deliver_pending(after_submit=interrupted)
        original=self.store.events()[0]
        self.assertTrue(original.accepted)
        self.assertEqual(self.store.states()[-1].applied.hot,{'MSFT'})
        result=p.deliver_pending()[0]
        self.assertFalse(result.inserted); self.assertEqual(result.event,original)
        self.assertFalse(p.snapshot()['pending'])

    def test_nasdaq_invalid_catalog_symbol_has_visible_rejected_ack(self):
        p=NasdaqSamplingProducer(self.folder/'nasdaq.sqlite3',request_store=self.store,
            settings=HaltProducerSettings('nasdaq',('LUDP',),'regular_close',True),clock=lambda:self.clock[0])
        p.initialize();p.record_snapshot(HaltSnapshot('baseline',START,'CURRENT',digest([]),(),{}))
        self.clock[0]+=timedelta(seconds=2)
        row=halt_row('UNKNOWN')
        p.record_snapshot(HaltSnapshot('new',self.clock[0],'CURRENT',digest(row),(row,),{}))
        result=p.deliver_pending()[0]
        self.assertEqual(result.event.rejection_reason,'symbol_not_in_admission_catalog')
        self.assertFalse(p.snapshot()['pending'])
        self.assertEqual(self.store.states()[-1].applied,BASELINE)
