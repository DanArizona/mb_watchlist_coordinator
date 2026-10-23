from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from datetime import datetime, timedelta
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from zoneinfo import ZoneInfo

from mb_watchlist_coordinator.models import IntentType, ProducerIntent
from mb_watchlist_coordinator.nasdaq_recovery import NasdaqRecoveryReceipts, RecoverySettings, RecoveryQuery
from mb_watchlist_coordinator.nasdaq_recovery_delivery import NasdaqRecoveryDelivery
from mb_watchlist_coordinator.nasdaq_sampling import HaltProducerSettings, HaltSnapshot, NasdaqSamplingProducer, halt_event_id
from mb_watchlist_coordinator.sampling_admission import AdmissionPolicy
from mb_watchlist_coordinator.sampling_policy import SamplingPolicy
from mb_watchlist_coordinator.sampling_projection import SamplingMembership
from mb_watchlist_coordinator.sampling_request_store import SamplingRequestStore
from mb_watchlist_coordinator.sampling_requests import canonical, digest, plain, timestamp

ET = ZoneInfo('America/New_York')
DAY = datetime.now(ET).date()+timedelta(days=1)
AT = datetime.combine(DAY, datetime.min.time().replace(hour=12), ET)
OWNER = 'nasdaq-shared'


class RecoveryDeliveryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.now = AT
        self.baseline = SamplingMembership(frozenset({'MSFT', 'SPY'}), frozenset({'SPY'}), frozenset())
        self.admission = AdmissionPolicy('synthetic-catalog', frozenset({'NVDA', 'AMD'}),
            frozenset({OWNER, 'manual'}), 1, 'session')
        self.requests = SamplingRequestStore(self.root/'requests.sqlite3', session_date=DAY,
            baseline=self.baseline, policy=SamplingPolicy('admin', 0, 0, 'immediate_cap'),
            admission=self.admission, clock=lambda: self.now)
        self.requests.initialize()
        self.live_settings = HaltProducerSettings('nasdaq-observations', ('LUDP', 'M'),
            'regular_close', False, False, 'external')
        self.live = NasdaqSamplingProducer(self.root/'live.sqlite3', request_store=self.requests,
            settings=self.live_settings, clock=lambda: self.now)
        self.live.initialize()
        self.query = RecoveryQuery(DAY, DAY)
        self.recovery_settings = RecoverySettings(DAY, 'late_start', (self.query,), False)
        self.recovery = self.reopen_recovery()
        self.recovery.initialize(create=True)
        self.delivery = self.open_delivery()
        self.delivery.initialize(create=True)

    def reopen_recovery(self):
        return NasdaqRecoveryReceipts(self.root/'recovery.sqlite3', request_store=self.requests,
            settings=self.recovery_settings, clock=lambda: self.now)

    def open_delivery(self, **kw):
        args = dict(live_producer=self.live, recovery_receipts=self.recovery,
            producer_id=OWNER, clock=lambda: self.now); args.update(kw)
        return NasdaqRecoveryDelivery(self.root/'delivery.sqlite3', **args)

    def row(self, symbol='MSFT', *, seconds=0, reason='LUDP', **extras):
        halt = AT.replace(hour=10)+timedelta(seconds=seconds)
        return {'symbol': symbol, 'halt_date': DAY.strftime('%m/%d/%Y'),
            'halt_time': halt.strftime('%H:%M:%S.%f'), 'reason_code': reason, **extras}

    def capture(self, cid, rows, mode='HISTORICAL'):
        return HaltSnapshot(cid, self.now, mode, digest(rows), tuple(rows), {'synthetic_only': True})

    def recover(self, rows=None, cid='recovered'):
        self.recovery.record(self.query, self.capture(cid, rows if rows is not None else [self.row()]))

    def live_event(self, *, symbol='MSFT'):
        self.live.record_snapshot(self.capture('baseline', [], 'CURRENT'))
        self.now += timedelta(seconds=2)
        at = self.now-timedelta(seconds=1)
        row = self.row(symbol)
        row.update(halt_date=at.strftime('%m/%d/%Y'), halt_time=at.strftime('%H:%M:%S.%f'))
        self.live.record_snapshot(self.capture('new-live', [row], 'CURRENT'))
        return row

    def cancel(self, rid):
        return self.requests.cancel_request('cancel-'+rid, owner_id=OWNER, request_id=rid, actor_id=OWNER)

    def test_recovered_halt_queues_at_recovery_not_original_halt_and_normal_hot_admission(self):
        self.recover([self.row(resumption_trade_time='10:05:00')])
        (eid,) = self.delivery.reconcile()
        command = self.delivery.snapshot()['commands'][eid]['command']
        self.assertEqual(timestamp(command['created_at_utc']), AT)
        self.assertEqual(timestamp(command['metadata']['halt_at_utc']), AT.replace(hour=10))
        self.assertEqual(command['metadata']['halt_event']['resumption_trade_time'], '10:05:00')
        (receipt,) = self.delivery.deliver_pending()
        self.assertTrue(receipt.event.accepted)
        self.assertEqual(self.requests.states()[-1].applied.hot, {'MSFT'})
        self.assertEqual(timestamp(command['expires_at_utc']), AT.replace(hour=16))
        self.assertEqual(self.delivery.snapshot()['status'], 'RECOVERING')
        self.assertEqual(self.delivery.snapshot()['publication'], 'EXTERNAL_NOT_VERIFIED')

    def test_recovery_first_then_live_same_halt_has_one_original_command(self):
        row = self.live_event()
        self.recover([row])
        # Force recovery to be the first observed input to a distinct live ledger.
        live = NasdaqSamplingProducer(self.root/'empty-live.sqlite3', request_store=self.requests,
            settings=self.live_settings, clock=lambda: self.now)
        live.initialize()
        delivery = NasdaqRecoveryDelivery(self.root/'recovery-first.sqlite3', live_producer=live,
            recovery_receipts=self.recovery, producer_id=OWNER, clock=lambda: self.now)
        delivery.initialize(create=True); delivery.reconcile(); delivery.deliver_pending()
        original = delivery.snapshot()['commands']
        live.record_snapshot(self.capture('late-baseline', [], 'CURRENT'))
        self.now += timedelta(seconds=2)
        # The original halt predates this startup, so normal live semantics skip it.
        live.record_snapshot(self.capture('same-event', [row], 'CURRENT'))
        self.assertFalse(delivery.reconcile())
        self.assertEqual(delivery.snapshot()['commands'], original)
        self.assertEqual(len(self.requests.events()), 1)

    def test_live_first_then_recovered_overlap_does_not_conflict(self):
        row = self.live_event()
        self.delivery.reconcile(); self.delivery.deliver_pending()
        original = self.delivery.snapshot()['commands']
        self.recover([row])
        self.assertFalse(self.delivery.reconcile())
        self.assertEqual(self.delivery.snapshot()['commands'], original)
        self.assertEqual(len(self.requests.events()), 1)

    def test_recovery_delivered_before_unreconciled_live_command_retains_payload(self):
        self.live.record_snapshot(self.capture('baseline', [], 'CURRENT'))
        self.now += timedelta(seconds=2)
        row = self.row();row['halt_time']=(self.now-timedelta(seconds=1)).strftime('%H:%M:%S.%f')
        self.recover([row]);self.delivery.reconcile();self.delivery.deliver_pending()
        original = self.delivery.snapshot()['commands']
        self.live.record_snapshot(self.capture('late-seen-live', [row], 'CURRENT'))
        self.assertEqual(len(self.live.snapshot()['commands']), 1)
        self.assertFalse(self.delivery.reconcile())
        self.assertEqual(self.delivery.snapshot()['commands'], original)
        self.assertEqual(len(self.requests.events()), 1)

    def test_same_event_after_cancel_never_resurrects_demand(self):
        self.recover();(eid,)=self.delivery.reconcile();self.delivery.deliver_pending();self.cancel(eid)
        self.now += timedelta(seconds=1)
        self.recover([self.row(resumption_trade_time='10:06:00')], 'release')
        self.assertFalse(self.delivery.reconcile());self.assertFalse(self.delivery.deliver_pending())
        self.assertFalse(self.requests.states()[-1].applied.hot)
        self.assertEqual(len(self.requests.events()), 2)

    def test_new_distinct_halt_same_symbol_reuses_own_active_demand(self):
        self.recover();self.delivery.reconcile();self.delivery.deliver_pending()
        self.now += timedelta(seconds=1)
        self.recover([self.row(seconds=60)], 'another-halt')
        (eid,) = self.delivery.reconcile();(result,)=self.delivery.deliver_pending()
        self.assertFalse(result.inserted)
        self.assertEqual(len(self.requests.events()), 1)
        self.assertIn('reused_request_id', self.delivery.snapshot()['deliveries'][eid])

    def test_new_distinct_halt_after_cancel_creates_new_normal_demand(self):
        self.recover();(eid,)=self.delivery.reconcile();self.delivery.deliver_pending();self.cancel(eid)
        self.now += timedelta(seconds=1)
        self.recover([self.row(seconds=60)], 'new-halt')
        self.delivery.reconcile();(result,)=self.delivery.deliver_pending()
        self.assertTrue(result.inserted)
        self.assertEqual(self.requests.states()[-1].applied.hot, {'MSFT'})

    def test_lost_ack_retry_after_cancel_preserves_original_receipt(self):
        self.recover();(eid,)=self.delivery.reconcile()
        def stop(_):raise RuntimeError('after request commit')
        with self.assertRaises(RuntimeError):self.delivery.deliver_pending(after_submit=stop)
        self.assertEqual(self.delivery.snapshot()['pending'], (eid,))
        self.cancel(eid);(retry,)=self.open_delivery().deliver_pending()
        self.assertFalse(retry.inserted)
        self.assertFalse(self.requests.states()[-1].applied.hot)
        self.assertEqual(len(self.requests.events()), 2)

    def test_lost_alias_ack_retry_after_cancel_cannot_create_a_new_request(self):
        self.recover();(first,)=self.delivery.reconcile();self.delivery.deliver_pending()
        self.recover([self.row(seconds=60)], 'other');(other,)=self.delivery.reconcile()
        def stop(_):raise RuntimeError('alias committed')
        with self.assertRaises(RuntimeError):self.delivery.deliver_pending(after_submit=stop)
        self.cancel(first);(retry,)=self.open_delivery().deliver_pending()
        self.assertFalse(retry.inserted)
        self.assertEqual(self.delivery.snapshot()['deliveries'][other]['reused_request_id'], first)
        self.assertFalse(self.requests.states()[-1].applied.hot)
        self.assertEqual(len(self.requests.events()), 2)

    def test_queued_before_close_but_delivered_after_close_is_normal_expired_rejection(self):
        self.recover();self.delivery.reconcile();self.now=AT.replace(hour=16)
        (result,) = self.delivery.deliver_pending()
        self.assertFalse(result.event.accepted)
        self.assertFalse(self.requests.states()[-1].applied.hot)
        self.assertFalse(self.delivery.snapshot()['pending'])

    def test_reconciliation_after_close_or_clock_rollback_does_not_queue(self):
        self.recover();self.delivery.reconcile();self.now-=timedelta(seconds=1)
        with self.assertRaisesRegex(ValueError, 'backwards'):self.delivery.reconcile()
        self.now=AT.replace(hour=16)
        with self.assertRaisesRegex(ValueError, 'regular session'):self.delivery.reconcile()

    def test_outside_uni_catalog_admission_and_nested_groups_are_normal(self):
        self.recover([self.row('NVDA')]);self.delivery.reconcile();self.delivery.deliver_pending()
        applied=self.requests.states()[-1].applied
        self.assertEqual(applied.uni, self.baseline.uni|{'NVDA'})
        self.assertEqual(applied.focus, self.baseline.focus|{'NVDA'})
        self.assertEqual(applied.hot, {'NVDA'})

    def test_unknown_catalog_and_capacity_rejections_are_durable(self):
        self.recover([self.row('NVDA')]);self.delivery.reconcile();self.delivery.deliver_pending()
        self.recover([self.row('AMD'),self.row('UNKNOWN')], 'more')
        self.delivery.reconcile();results=self.delivery.deliver_pending()
        self.assertEqual({r.event.rejection_reason for r in results}, {'session_admission_capacity','symbol_not_in_admission_catalog'})
        self.assertFalse(self.open_delivery().snapshot()['pending'])
        self.assertEqual(self.requests.states()[-1].applied.hot, {'NVDA'})

    def test_restriction_caps_applied_hot_and_reuse_cannot_bypass_it(self):
        self.requests.restrict_symbol('cap',symbol='MSFT',max_group='uni',actor_id='admin')
        self.recover();self.delivery.reconcile();self.delivery.deliver_pending()
        self.recover([self.row(seconds=60)], 'another');self.delivery.reconcile();self.delivery.deliver_pending()
        self.assertFalse(self.requests.states()[-1].applied.hot)
        self.assertEqual(self.requests.states()[-1].applied.uni, self.baseline.uni)

    def test_manual_demand_is_not_borrowed_or_withdrawn(self):
        intent=ProducerIntent('manual-1','manual',IntentType.ENSURE_PRESENT,frozenset({'MSFT'}),self.now,
            expires_at=AT.replace(hour=16),metadata={'sampling_channel':'hot','session_date':DAY.isoformat()})
        self.requests.submit_request(intent,actor_id='manual')
        self.recover();(eid,)=self.delivery.reconcile();self.delivery.deliver_pending()
        self.assertEqual(len([e for e in self.requests.events() if e.kind=='request']),2)
        self.cancel(eid)
        self.assertEqual(self.requests.states()[-1].applied.hot, {'MSFT'})

    def test_query_completion_blocks_recovery_but_not_new_live_delivery(self):
        previous=RecoveryQuery(DAY-timedelta(days=1),None)
        settings=replace(self.recovery_settings,queries=(self.query,previous))
        recovery=NasdaqRecoveryReceipts(self.root/'more-queries.sqlite3',request_store=self.requests,
            settings=settings,clock=lambda:self.now);recovery.initialize(create=True)
        recovery.record(self.query,self.capture('first-query',[self.row()]))
        delivery=NasdaqRecoveryDelivery(self.root/'more-delivery.sqlite3',live_producer=self.live,
            recovery_receipts=recovery,producer_id=OWNER,clock=lambda:self.now);delivery.initialize(create=True)
        self.assertFalse(delivery.reconcile())
        live_row=self.live_event(symbol='SPY');delivery.reconcile();delivery.deliver_pending()
        self.assertEqual(self.requests.states()[-1].applied.hot, {'SPY'})
        recovery.record(previous,self.capture('last-query',[]));delivery.reconcile();delivery.deliver_pending()
        self.assertEqual(self.requests.states()[-1].applied.hot, {'SPY','MSFT'})
        self.assertEqual(delivery.snapshot()['query_scope'],'COMPLETE_WITH_TRACE_GAPS')

    def test_context_and_unresolved_original_reason_do_not_gain_requests(self):
        older=self.row();older['halt_date']=(DAY-timedelta(days=1)).strftime('%m/%d/%Y')
        self.recover([older,self.row('SPY',reason='T3')])
        self.assertFalse(self.delivery.reconcile());self.assertFalse(self.requests.events())

    def test_all_changed_release_versions_and_receipt_times_remain_in_sources(self):
        self.recover();self.delivery.reconcile();self.delivery.deliver_pending()
        self.now+=timedelta(minutes=1)
        self.recover([self.row(reason='T3',resumption_quote_time='10:04:00',resumption_trade_time='10:05:00')],'release')
        self.assertFalse(self.delivery.reconcile())
        observations=self.recovery.snapshot()['candidates'][0]['observations']
        self.assertEqual(len(observations),2)
        self.assertEqual(timestamp(observations[1]['recovered_at_utc']),self.now)
        self.assertEqual(observations[1]['row']['resumption_trade_time'],'10:05:00')
        self.assertEqual(len(self.requests.events()),1)

    def test_missing_outbox_does_not_recreate_or_adopt_existing_source_demand(self):
        self.recover();self.delivery.reconcile();self.delivery.deliver_pending();self.delivery.path.unlink()
        with self.assertRaises(FileNotFoundError):self.open_delivery().initialize()
        self.assertFalse(self.delivery.path.exists())
        with self.assertRaisesRegex(ValueError,'unbound'):self.open_delivery().initialize(create=True)

    def test_changed_identity_and_legacy_direct_mode_are_refused(self):
        with self.assertRaises(ValueError):self.open_delivery(producer_id=self.live_settings.producer_id)
        direct=NasdaqSamplingProducer(self.root/'direct.sqlite3',request_store=self.requests,
            settings=replace(self.live_settings,delivery_mode='direct'),clock=lambda:self.now)
        with self.assertRaisesRegex(ValueError,'external'):self.open_delivery(live_producer=direct)
        with self.assertRaises(ValueError):self.open_delivery(producer_id='other-owner').initialize()
        with self.assertRaisesRegex(ValueError,'shared'):self.live.deliver_pending()

    def test_external_contract_is_explicit_and_default_v1_v2_payloads_unchanged(self):
        direct=replace(self.live_settings,delivery_mode='direct')
        self.assertNotIn('delivery_mode',direct.payload())
        self.assertEqual(self.live.contract,'nasdaq-source-observations-v3')
        self.assertNotIn('reuse_active_symbol_requests',direct.payload())
        self.assertNotIn('delivery_mode',replace(direct,reuse_active_symbol_requests=True).payload())
        with self.assertRaises(ValueError):HaltProducerSettings('x',('LUDP','M'),'regular_close',False,False,'automatic')

    def test_tampered_and_rehashed_queued_command_still_fails_source_derivation(self):
        self.recover();self.delivery.reconcile()
        with closing(sqlite3.connect(self.delivery.path)) as c,c:
            r=json.loads(c.execute('SELECT payload FROM delivery_command').fetchone()[0])
            r['command']['symbol']='SPY';r.pop('event_sha256');r['event_sha256']=digest(r)
            c.execute('UPDATE delivery_command SET payload=?',(canonical(r),))
        with self.assertRaisesRegex(ValueError,'source evidence'):self.open_delivery().snapshot()

    def test_source_rehash_after_warm_read_cannot_change_bound_origin(self):
        self.recover();self.delivery.reconcile();self.delivery.snapshot()
        with closing(sqlite3.connect(self.recovery.path)) as c,c:
            r=json.loads(c.execute('SELECT payload FROM recovery_receipt').fetchone()[0])
            r['snapshot']['records'][0]['resumption_trade_time']='10:09:00'
            r.pop('event_sha256');r['event_sha256']=digest(r)
            c.execute('UPDATE recovery_receipt SET payload=?',(canonical(r),))
        with self.assertRaisesRegex(ValueError,'source prefix'):self.delivery.snapshot()

    def test_ack_corruption_and_reuse_binding_deletion_fail_fresh_read(self):
        self.recover();self.delivery.reconcile();self.delivery.deliver_pending()
        self.recover([self.row(seconds=60)],'second');self.delivery.reconcile();self.delivery.deliver_pending()
        with closing(sqlite3.connect(self.requests.path)) as c,c:c.execute('DELETE FROM request_reuse')
        with self.assertRaisesRegex(ValueError,'acknowledgement'):self.open_delivery().snapshot()

    def test_concurrent_reconciliation_and_delivery_keep_one_request(self):
        self.recover()
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:self.open_delivery().reconcile(),range(2)))
        self.assertEqual(sum(len(r) for r in results),1)
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:self.open_delivery().deliver_pending(),range(2)))
        self.assertEqual(sum(len(r) for r in results),1)
        self.assertEqual(len(self.requests.events()),1)

    def test_reopen_is_exact_and_receipt_only_stage_remains_receipt_only(self):
        self.recover();self.delivery.reconcile();self.delivery.deliver_pending()
        self.assertEqual(self.open_delivery().initialize(),self.delivery.snapshot())
        self.assertEqual(self.recovery.snapshot()['delivery'],'NOT_IMPLEMENTED')
        self.assertEqual(self.recovery.snapshot()['stage'],'RECEIPTS_ONLY')

    def test_batch_interruption_replays_prior_request_and_restores_all_acks(self):
        self.recover([self.row(), self.row('SPY')]);self.delivery.reconcile()
        count=[0]
        def stop_on_second(_):
            count[0]+=1
            if count[0]==2:raise RuntimeError('second committed before batch ACK')
        with self.assertRaises(RuntimeError):self.delivery.deliver_pending(after_submit=stop_on_second)
        self.assertEqual(len(self.requests.events()),2)
        self.assertEqual(len(self.delivery.snapshot()['pending']),2)
        retries=self.open_delivery().deliver_pending()
        self.assertTrue(all(not r.inserted for r in retries))
        self.assertEqual(len(self.requests.events()),2)
        self.assertFalse(self.delivery.snapshot()['pending'])

    def test_saved_resume_receipts_use_same_delivery_without_declaring_ready(self):
        recovery=NasdaqRecoveryReceipts(self.root/'saved-recovery.sqlite3',request_store=self.requests,
            settings=replace(self.recovery_settings,mode='resume_saved'),clock=lambda:self.now)
        recovery.initialize(create=True);recovery.record(self.query,self.capture('saved',[self.row()]))
        delivery=NasdaqRecoveryDelivery(self.root/'saved-delivery.sqlite3',live_producer=self.live,
            recovery_receipts=recovery,producer_id=OWNER,clock=lambda:self.now)
        delivery.initialize(create=True);delivery.reconcile();delivery.deliver_pending()
        self.assertEqual(delivery.snapshot()['status'],'RECOVERING')
        self.assertEqual(self.requests.states()[-1].applied.hot,{'MSFT'})

    def test_external_observation_owner_cannot_bypass_shared_delivery(self):
        self.requests.submit_request(ProducerIntent('bypass',self.live_settings.producer_id,
            IntentType.ENSURE_PRESENT,frozenset({'MSFT'}),self.now,
            metadata={'sampling_channel':'hot','session_date':DAY.isoformat()}),actor_id=self.live_settings.producer_id)
        with self.assertRaisesRegex(ValueError,'observation owner'):self.delivery.snapshot()

    def test_lost_source_and_request_corruption_fail_before_new_outbox_write(self):
        self.recover();self.delivery.reconcile()
        before=self.delivery.path.read_bytes()
        with closing(sqlite3.connect(self.requests.path)) as c,c:c.execute("UPDATE request_identity SET payload='{}'")
        with self.assertRaises(ValueError):self.delivery.deliver_pending()
        self.assertEqual(self.delivery.path.read_bytes(),before)
        self.live.path.unlink()
        with self.assertRaises(sqlite3.OperationalError):self.delivery.snapshot()
        self.assertFalse(self.live.path.exists())

    def test_native_publication_uses_recovery_time_and_audits_replays(self):
        from mb_market_data.quote_observation_store import QuoteObservationStore
        from mb_market_data.quote_journal_audit import audit_quote_journal
        from mb_market_data.quote_journal_replay import QuoteJournalReplayReader
        from mb_market_data.sampling_membership import SamplingHierarchyRevision
        from mb_watchlist_coordinator.sampling_journal import SamplingJournal
        from mb_watchlist_coordinator.sampling_service import SamplingPublicationService,PublicationSettings
        native=QuoteObservationStore(self.root/'native.sqlite3',session_date=DAY,schema_version=2)
        native.initialize();native.record_membership_revision(SamplingHierarchyRevision(session_date=DAY,
            revision=0,effective_at=AT.replace(hour=9,minute=30),uni_symbols=tuple(self.baseline.uni),
            focus_symbols=tuple(self.baseline.focus),hot_symbols=(),source='synthetic-opening'))
        service=SamplingPublicationService(self.root/'publication.sqlite3',request_store=self.requests,
            journal=SamplingJournal(native),settings=PublicationSettings('synthetic-recovery',1,.1,AT.replace(hour=16)),clock=lambda:self.now)
        service.initialize();self.recover([self.row('NVDA')]);self.delivery.reconcile();self.delivery.deliver_pending()
        service.cycle()
        revisions=native.membership_revisions_in_effective_order()
        self.assertEqual(len(revisions),2)
        self.assertGreaterEqual(revisions[-1].effective_at,AT)
        self.assertEqual(set(revisions[-1].hot_symbols),{'NVDA'})
        self.assertTrue(audit_quote_journal(native.database_path).passed)
        def replay():return [(e.event_id,e.revision.content_sha256) for e in QuoteJournalReplayReader(native.database_path).events()]
        self.assertEqual(replay(),replay())
        self.assertEqual(self.delivery.snapshot()['publication'],'EXTERNAL_NOT_VERIFIED')


if __name__=='__main__':unittest.main()
