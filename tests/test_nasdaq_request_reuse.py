"""Changed-mode compatibility plus durable coverage and update-retention proofs."""
from contextlib import closing
from dataclasses import replace
from datetime import timedelta
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import test_nasdaq_sampling as original
from mb_watchlist_coordinator.models import IntentType, ProducerIntent
from mb_watchlist_coordinator.nasdaq_sampling import HaltProducerSettings, NasdaqSamplingProducer
from mb_watchlist_coordinator.sampling_projection import SamplingMembership
from mb_watchlist_coordinator.sampling_policy import SamplingPolicy
from mb_watchlist_coordinator.sampling_request_store import SamplingRequestStore, RequestConflictError
from mb_watchlist_coordinator.sampling_requests import digest, plain


class ReuseTests(original.NasdaqTests):
    # Run the existing behavioral contract against the explicitly selected new
    # producer identity as well. Only later-distinct-halt request count changes.
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.at = original.START
        self.settings = HaltProducerSettings('nasdaq-test', ('LUDP','M'), 'regular_close', False, True)
        self.members = SamplingMembership(frozenset({'AAPL','MSFT','SPY'}), frozenset({'SPY'}), frozenset())
        self.ledger = SamplingRequestStore(self.root/'requests.sqlite3', session_date=self.at.date(),
            baseline=self.members, clock=lambda:self.at, policy=SamplingPolicy('admin',60,120,'immediate_cap'))
        self.ledger.initialize(); self.producer = self.reopen()

    def twice(self):
        self.baseline(); self.queue(); self.producer.deliver_pending()
        self.queue([self.row(4)], seconds=5, cid='second-halt')
        return self.producer.deliver_pending()

    def test_later_distinct_halt_for_same_symbol_has_another_request(self):
        self.twice()
        self.assertEqual(len(self.ledger.events()), 1)
        self.assertEqual(len(self.producer.snapshot()['commands']), 2)
        self.assertEqual(len(self.ledger.validated_reuse_history()[2]), 1)

    def test_distinct_halts_share_demand_but_keep_separate_observations(self):
        self.twice(); s=self.producer.snapshot()
        self.assertEqual(len(s['receipts']),3)
        self.assertEqual(len(s['deliveries']),2)
        self.assertEqual(len(s['pending']),0)
        aliases=[v for v in s['deliveries'].values() if 'reused_request_id' in v]
        self.assertEqual(len(aliases),1)
        self.assertEqual(aliases[0]['request_sequence'],1)
        self.assertEqual(len(self.ledger.states()[-1].active_requests),1)
        self.assertEqual(self.reopen().snapshot(),s)

    def test_multiple_halts_in_one_capture_reuse_after_first_delivery(self):
        self.baseline(); self.queue([self.row(1),self.row(2)],seconds=3)
        self.producer.deliver_pending()
        self.assertEqual(len(self.ledger.events()),1)
        self.assertEqual(len(self.producer.snapshot()['commands']),2)

    def test_batch_interruption_rolls_back_source_acks_but_restores_both_bindings(self):
        self.baseline();self.queue([self.row(1),self.row(2)],seconds=3)
        calls=[]
        def fail_second(result):
            calls.append(result)
            if len(calls)==2:raise RuntimeError('second durable delivery')
        with self.assertRaises(RuntimeError):self.producer.deliver_pending(after_submit=fail_second)
        self.assertEqual(len(self.producer.snapshot()['pending']),2)
        self.assertEqual(len(self.ledger.events()),1)
        self.producer=self.reopen();self.producer.deliver_pending()
        self.assertFalse(self.producer.snapshot()['pending'])
        self.assertEqual(len(self.ledger.events()),1)

    def test_changed_resumption_versions_retain_available_at_times(self):
        self.twice(); request_count=len(self.ledger.events())
        for second,trade in [(8,'09:40:00'),(9,'09:45:00')]:
            self.queue([self.row(4,resumption_quote_time='09:39:00',resumption_trade_time=trade)],
                       seconds=second,cid='update-'+str(second))
            self.assertEqual(self.statuses(),['updated'])
            self.assertEqual(self.producer.deliver_pending(),())
        saved=self.reopen().snapshot()['receipts'][-2:]
        self.assertEqual([r['snapshot']['records'][0]['resumption_trade_time'] for r in saved],['09:40:00','09:45:00'])
        self.assertLess(saved[0]['recorded_at_utc'],saved[1]['recorded_at_utc'])
        self.assertEqual(len(self.ledger.events()),request_count)

    def test_other_producer_hot_demand_does_not_suppress_first_nasdaq_request(self):
        value=ProducerIntent('manual','manual',IntentType.ENSURE_PRESENT,frozenset({'MSFT'}),self.at,
            expires_at=self.at.replace(hour=16),metadata={'sampling_channel':'hot','session_date':self.at.date().isoformat()})
        self.ledger.submit_request(value,actor_id='manual')
        self.baseline();self.queue();self.producer.deliver_pending()
        self.assertEqual({r['producer_id'] for r in self.ledger.states()[-1].active_requests},{'manual','nasdaq-test'})

    def test_unrelated_same_owner_request_is_not_a_nasdaq_origin(self):
        value=ProducerIntent('unrelated','nasdaq-test',IntentType.ENSURE_PRESENT,frozenset({'MSFT'}),self.at,
            expires_at=self.at.replace(hour=16),metadata={'sampling_channel':'hot','session_date':self.at.date().isoformat()})
        self.ledger.submit_request(value,actor_id='nasdaq-test')
        self.baseline();self.queue();self.producer.deliver_pending()
        self.assertEqual(len(self.ledger.events()),2)

    def test_cancelled_original_does_not_cover_a_later_new_halt(self):
        self.baseline();self.queue();self.producer.deliver_pending();e=self.ledger.events()[0]
        self.ledger.cancel_request('cancel',owner_id=e.actor_id,request_id=e.command_id,actor_id=e.actor_id)
        self.queue([self.row(4)],seconds=5,cid='new-after-cancel');self.producer.deliver_pending()
        self.assertEqual(len([e for e in self.ledger.events() if e.kind=='request']),2)
        self.assertEqual(len(self.ledger.validated_reuse_history()[2]),0)

    def test_reuse_commit_before_source_ack_survives_cancellation_and_restart(self):
        self.baseline();self.queue();self.producer.deliver_pending();first=self.ledger.events()[0]
        self.queue([self.row(4)],seconds=5,cid='second')
        def fail(_):raise RuntimeError('after durable reuse before source ack')
        with self.assertRaises(RuntimeError):self.producer.deliver_pending(after_submit=fail)
        self.assertEqual(len(self.ledger.validated_reuse_history()[2]),1)
        self.ledger.cancel_request('cancel',owner_id=first.actor_id,request_id=first.command_id,actor_id=first.actor_id)
        self.at+=timedelta(seconds=1);self.producer=self.reopen();self.producer.deliver_pending()
        self.assertEqual(len([e for e in self.ledger.events() if e.kind=='request']),1)
        self.assertFalse(self.ledger.states()[-1].active_requests)
        self.assertFalse(self.producer.snapshot()['pending'])

    def test_alias_retry_after_close_does_not_create_an_expired_request(self):
        self.twice();command=list(self.producer.snapshot()['commands'].values())[-1]
        from mb_watchlist_coordinator.nasdaq_sampling import _intent
        self.at=self.at.replace(hour=16,minute=0,second=0,microsecond=0)
        retry=self.ledger.submit_request(_intent(command),actor_id='nasdaq-test')
        self.assertFalse(retry.inserted);self.assertEqual(len(self.ledger.events()),1)

    def test_alias_id_conflict_fails_without_new_receipt(self):
        self.twice();command=list(self.producer.snapshot()['commands'].values())[-1]
        from mb_watchlist_coordinator.nasdaq_sampling import _intent
        with self.assertRaises(RequestConflictError):
            self.ledger.submit_request(replace(_intent(command),reason='changed'),actor_id='nasdaq-test')
        self.assertEqual(len(self.ledger.events()),1)

    def test_active_restriction_still_caps_reused_demand(self):
        self.twice();self.ledger.restrict_symbol('cap',symbol='MSFT',max_group='focus',actor_id='admin')
        self.queue([self.row(7)],seconds=8,cid='third');self.producer.deliver_pending()
        self.assertEqual(len(self.ledger.states()[-1].active_requests),1)
        self.assertFalse(self.ledger.states()[-1].applied.hot)

    def test_deleted_reuse_receipt_is_detected_by_source_binding(self):
        self.twice()
        with closing(sqlite3.connect(self.ledger.path)) as c,c:c.execute('delete from request_reuse')
        with self.assertRaises(ValueError):self.producer.snapshot()

    def test_rehashed_false_coverage_is_refused(self):
        self.twice()
        with closing(sqlite3.connect(self.ledger.path)) as c,c:
            r=json.loads(c.execute('select payload from request_reuse').fetchone()[0])
            r['command']['payload']['symbols']=['AAPL']
            r.pop('receipt_sha256');r['receipt_sha256']=digest(r)
            c.execute('update request_reuse set payload=?',(json.dumps(r),))
        with self.assertRaises(ValueError):self.producer.snapshot()

    def test_parallel_reuse_decisions_keep_one_alias(self):
        self.baseline();self.queue();self.producer.deliver_pending()
        self.queue([self.row(4)],seconds=5,cid='second')
        with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(lambda _:self.producer.deliver_pending(),range(2)))
        self.assertEqual(len(self.ledger.events()),1)
        self.assertEqual(len(self.ledger.validated_reuse_history()[2]),1)

    def test_parallel_cancellation_cannot_produce_coverage_from_a_cancelled_prefix(self):
        self.baseline();self.queue();self.producer.deliver_pending();first=self.ledger.events()[0]
        self.queue([self.row(4)],seconds=5,cid='second')
        with ThreadPoolExecutor(max_workers=2) as pool:
            a=pool.submit(self.producer.deliver_pending)
            b=pool.submit(self.ledger.cancel_request,'cancel',owner_id=first.actor_id,
                          request_id=first.command_id,actor_id=first.actor_id)
            a.result();b.result()
        events,_,aliases=self.ledger.validated_reuse_history()
        if aliases:
            alias=next(iter(aliases.values()))
            self.assertLess(alias['request_head_sequence'],next(e.sequence for e in events if e.kind=='cancel'))
        else:
            self.assertEqual(len([e for e in events if e.kind=='request']),2)
        self.reopen().snapshot()

    def test_read_observes_one_prefix_while_another_connection_appends_a_binding(self):
        from mb_watchlist_coordinator.nasdaq_sampling import _intent
        self.baseline();self.queue();self.producer.deliver_pending();first=self.ledger.events()[0]
        self.queue([self.row(4)],seconds=5,cid='second')
        command=list(self.producer.snapshot()['commands'].values())[-1]
        with closing(sqlite3.connect(self.ledger.path)) as c:c.execute('pragma journal_mode=WAL')
        start=threading.Event();done=threading.Event();reader=threading.get_ident()
        original_read=self.ledger._read_history
        def paused(connection):
            result=original_read(connection)
            if threading.get_ident()==reader:
                start.set();self.assertTrue(done.wait(5))
            return result
        def writer():
            self.assertTrue(start.wait(5))
            try:
                self.ledger.tick('new-prefix')
                self.ledger.reuse_active_request(_intent(command),actor_id='nasdaq-test',candidate_request_ids=[first.command_id])
            finally:done.set()
        with ThreadPoolExecutor(max_workers=1) as pool:
            future=pool.submit(writer)
            with patch.object(self.ledger,'_read_history',side_effect=paused):
                events,_,aliases=self.ledger.validated_reuse_history()
            future.result()
        self.assertEqual((len(events),len(aliases)),(1,0))
        events,_,aliases=self.ledger.validated_reuse_history()
        self.assertEqual((len(events),len(aliases)),(2,1))

    def test_old_mode_cannot_open_new_identity(self):
        with self.assertRaisesRegex(ValueError,'mismatch'):
            self.reopen(settings=replace(self.settings,reuse_active_symbol_requests=False))

    def test_nonboolean_reuse_selection_refused(self):
        with self.assertRaises(ValueError):replace(self.settings,reuse_active_symbol_requests=1)

    def test_short_or_future_or_focus_requests_do_not_cover_full_session(self):
        from mb_watchlist_coordinator.nasdaq_sampling import _intent
        self.baseline();self.queue();desired=_intent(next(iter(self.producer.snapshot()['commands'].values())))
        for suffix,changes in [('short',{'expires_at':self.at+timedelta(seconds=10)}),
                               ('future',{'effective_from':self.at+timedelta(seconds=10)}),
                               ('focus',{'metadata':{'sampling_channel':'focus','session_date':self.at.date().isoformat()}})]:
            candidate=replace(desired,intent_id=suffix,**changes)
            self.ledger.submit_request(candidate,actor_id='nasdaq-test')
            self.assertIsNone(self.ledger.reuse_active_request(desired,actor_id='nasdaq-test',candidate_request_ids=[suffix]))

    def test_incomplete_alias_write_does_not_submit_new_demand(self):
        self.baseline();self.queue();self.producer.deliver_pending()
        self.queue([self.row(4)],seconds=5,cid='second')
        with patch.object(self.ledger,'reuse_active_request',side_effect=RuntimeError('write failed')):
            with self.assertRaises(RuntimeError):self.producer.deliver_pending()
        self.assertEqual(len(self.ledger.events()),1);self.assertEqual(len(self.producer.snapshot()['pending']),1)
