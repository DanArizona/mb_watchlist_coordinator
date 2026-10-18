"""Admission through the actual journal, collector and acquisition-aware replay."""
from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

EXPERIMENT = Path(__file__).resolve().parent
ROOT = EXPERIMENT.parent.parent
sys.path[:0] = [str(ROOT/'src'), str(ROOT/'tests'), str(ROOT/'experiments/hot_acquisition_20261017')]
from test_hot_acquisition import Response, SyntheticClient, fail_at
from test_sampling_admission import START, BASELINE, ADMISSION, POLICY, make_request
from hot_proof import replay
from mb_market_data.quote_journal_audit import audit_quote_journal
from mb_market_data.quote_observation_store import QuoteObservationStore
from mb_market_data.sampling_membership import SamplingChannel, SamplingHierarchyRevision
from mb_market_data.sampling_acquisition import MARKER, AcquisitionSettings, ExplicitPollSlot, IsolatedSamplingPoller
from mb_market_data.watchlist_polling import PollWindow
from mb_watchlist_coordinator.sampling_request_store import SamplingRequestStore
from mb_watchlist_coordinator.sampling_journal import SamplingJournal
from mb_watchlist_coordinator.sampling_service import PublicationSettings, SamplingPublicationService


def fixture(folder, policy=POLICY):
    clock=[START];get_clock=lambda:clock[0]
    ledger=SamplingRequestStore(folder/'requests.sqlite3',session_date=START.date(),baseline=BASELINE,
        policy=policy,admission=ADMISSION,clock=get_clock);ledger.initialize()
    journal=QuoteObservationStore(folder/'quotes.sqlite3',session_date=START.date(),schema_version=2);journal.initialize()
    journal.record_membership_revision(SamplingHierarchyRevision(session_date=START.date(),revision=0,
        effective_at=START-timedelta(microseconds=1),uni_symbols=tuple(BASELINE.uni),
        focus_symbols=tuple(BASELINE.focus),hot_symbols=(),source='synthetic_admission_fixture',
        metadata={MARKER:True,'experimental':True,'logical_clock':True,'quote_source':'synthetic'}))
    service=SamplingPublicationService(folder/'publication.sqlite3',request_store=ledger,journal=SamplingJournal(journal),
        settings=PublicationSettings('admission-proof',0.05,0.35,START+timedelta(minutes=2)),clock=get_clock)
    service.initialize()
    return ledger,journal,service,clock


def poller(journal,clock,channel='uni',client=None,batch_size=2):
    settings=AcquisitionSettings(SamplingChannel(channel),tuple(range(0,60,2)),
        PollWindow(START,START+timedelta(seconds=10)),batch_size,'all','synthetic',0.8,0.05)
    value=IsolatedSamplingPoller(journal,settings=settings,client=client or SyntheticClient(),clock=lambda:clock[0])
    value.initialize();return value


def sample(poller,clock,seconds):
    clock[0]=START+timedelta(seconds=seconds)
    return poller.sample(ExplicitPollSlot(poller.settings.channel,clock[0],poller.settings.seconds))


class AdmissionPublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.folder=Path(self.temp.name)
        self.ledger,self.journal,self.service,self.clock=fixture(self.folder)
        clock=self.clock
        class LogicalDatetime(START.__class__):
            @classmethod
            def now(cls,tz=None):return clock[0].astimezone(tz or START.tzinfo)
        patcher=patch('mb_market_data.schwab_quotes.datetime',LogicalDatetime)
        patcher.start();self.addCleanup(patcher.stop)

    def submit(self,**kw):return self.ledger.submit_request(make_request(self.clock[0],**kw),actor_id=kw.get('owner','manual'))
    def advance(self,seconds):self.clock[0]=START+timedelta(seconds=seconds)
    def latest(self):return self.journal.membership_revisions_in_effective_order()[-1]
    def reopen(self):
        s=self.service
        self.service=SamplingPublicationService(s.path,request_store=self.ledger,journal=SamplingJournal(self.journal),
            settings=s.settings,clock=lambda:self.clock[0]);self.service.initialize();return self.service

    def test_pending_admission_does_not_interrupt_existing_slot_or_backfill_symbol(self):
        client=SyntheticClient();p=poller(self.journal,self.clock,client=client)
        self.submit();sample(p,self.clock,0)
        before=self.journal.acquisitions_in_replay_order()[0]
        self.assertEqual(before.requested_symbol_count,2)
        self.assertEqual(client.calls[0][0],['AAPL','SPY'])
        self.advance(0.1);self.service.cycle()
        sample(p,self.clock,2)
        after=self.journal.acquisitions_in_replay_order()[-1]
        self.assertEqual((after.channel_revision,after.requested_symbol_count),(1,3))
        self.assertEqual(client.calls[1:],[(['AAPL','MSFT'],'all'),(['SPY'],'all')])
        self.assertEqual(self.journal.membership_revisions_in_effective_order()[0].uni_symbols,('AAPL','SPY'))
        old=replay(self.journal.database_path,cutoff=self.latest().effective_at-timedelta(microseconds=1))
        self.assertNotIn('MSFT',old['membership']['uni'])
        self.assertNotIn('uni:MSFT',old['latest'])

    def test_inflight_uni_keeps_old_symbols_and_revision_during_admission(self):
        def respond(symbols,fields):
            self.advance(0.1);self.submit();self.service.cycle();self.advance(1)
            return Response({s:{'quote':{'lastPrice':17}} for s in symbols})
        client=SyntheticClient(respond);p=poller(self.journal,self.clock,client=client)
        sample(p,self.clock,0)
        self.assertEqual(self.journal.acquisitions_in_replay_order()[0].channel_revision,0)
        self.assertEqual(client.calls,[(['AAPL','SPY'],'all')])
        client.callback=None;sample(p,self.clock,2)
        self.assertEqual(self.journal.acquisitions_in_replay_order()[-1].requested_symbol_count,3)

    def test_first_new_quote_is_visible_only_at_response_receipt(self):
        self.submit();self.service.cycle()
        client=SyntheticClient(lambda symbols,fields:(self.advance(2.4) or Response({s:{'quote':{'lastPrice':11}} for s in symbols})))
        p=poller(self.journal,self.clock,channel='hot',client=client);sample(p,self.clock,2)
        a=self.journal.acquisitions_in_replay_order()[-1]
        self.assertNotIn('hot:MSFT',replay(self.journal.database_path,cutoff=a.completed_at_utc-timedelta(microseconds=1))['latest'])
        self.assertIn('hot:MSFT',replay(self.journal.database_path,cutoff=a.completed_at_utc)['latest'])

    def test_complete_expanded_hierarchy_replays_identically_and_keeps_origin(self):
        self.submit();self.service.cycle();self.advance(1)
        self.submit(owner='algorithm',rid='a1',symbols=('NVDA',),target='focus');self.service.cycle()
        first=replay(self.journal.database_path);second=replay(self.journal.database_path)
        self.assertEqual(first,second)
        self.assertEqual(first['membership'],{'uni':['AAPL','MSFT','NVDA','SPY'],'focus':['MSFT','NVDA','SPY'],'hot':['MSFT']})
        self.assertEqual([s['symbol'] for s in self.latest().metadata['request_state']['session_additions']],['MSFT','NVDA'])
        self.assertTrue(audit_quote_journal(self.journal.database_path).passed)

    def test_failed_channel_insert_rolls_back_whole_expansion_and_input_survives(self):
        self.submit()
        with closing(sqlite3.connect(self.journal.database_path)) as c,c:
            c.execute("CREATE TRIGGER fail_admission BEFORE INSERT ON sampling_channel_revision WHEN NEW.channel='hot' AND NEW.revision=1 BEGIN SELECT RAISE(ABORT,'injected'); END")
        with self.assertRaises(sqlite3.IntegrityError):self.service.cycle()
        self.assertEqual(self.latest().revision,0)
        self.assertEqual(len(self.ledger.events()),1)
        with closing(sqlite3.connect(self.journal.database_path)) as c,c:
            c.execute('DROP TRIGGER fail_admission')
        self.advance(1);self.reopen().cycle()
        self.assertEqual(self.latest().uni_symbols,('AAPL','MSFT','SPY'))
        self.assertEqual(len(self.journal.membership_revisions_in_effective_order()),2)

    def test_crash_after_expansion_commit_acknowledges_original_without_duplicate(self):
        self.submit()
        with self.assertRaises(RuntimeError):self.service.cycle(fault_hook=fail_at('after_commit'))
        original=self.latest();self.advance(5);self.reopen().cycle()
        self.assertEqual(self.latest(),original)
        self.assertEqual(len(self.journal.membership_revisions_in_effective_order()),2)
        self.assertTrue(self.service.snapshot()['outcomes'][-1]['recovered'])

    def test_expired_hot_request_after_uncommitted_plan_recovers_uni_only(self):
        # Explicit zero holds isolate expiry from the existing receipt-based
        # hysteresis policy, which may otherwise legitimately retain Hot.
        case=self.folder/'zero-holds';case.mkdir()
        self.ledger,self.journal,self.service,self.clock=fixture(case,policy=replace(POLICY,
            demotion_grace_seconds=0,minimum_residence_seconds=0))
        self.submit(expires_at=START+timedelta(seconds=1))
        with self.assertRaises(RuntimeError):self.service.cycle(fault_hook=fail_at('after_plan'))
        self.advance(10);self.reopen().cycle()
        self.assertEqual(self.latest().uni_symbols,('AAPL','MSFT','SPY'))
        self.assertEqual(self.latest().hot_symbols,())
        self.assertGreater(self.latest().effective_at,self.clock[0])

    def test_demotion_preserves_added_uni_and_reuses_origin_after_reentry(self):
        self.submit();self.service.cycle()
        self.advance(1);self.ledger.cancel_request('cancel',owner_id='manual',request_id='m1',actor_id='manual')
        self.advance(4);self.service.cycle()
        self.assertEqual(self.latest().hot_symbols,())
        self.assertIn('MSFT',self.latest().uni_symbols)
        origin=self.latest().metadata['request_state']['session_additions']
        self.advance(5);self.submit(rid='again');self.service.cycle()
        self.assertEqual(self.latest().hot_symbols,('MSFT',))
        self.assertEqual(self.latest().metadata['request_state']['session_additions'],origin)

    def test_saved_new_symbol_response_recovers_without_another_request(self):
        self.submit();self.service.cycle();p=poller(self.journal,self.clock,channel='hot')
        self.advance(2);slot=ExplicitPollSlot(SamplingChannel.HOT,self.clock[0],p.settings.seconds)
        with self.assertRaises(RuntimeError):p.sample(slot,fault_hook=fail_at('after_assembled'))
        original_calls=list(p.client.calls)
        p.recover()
        self.assertEqual(p.client.calls,original_calls)
        self.assertEqual(self.journal.acquisitions_in_replay_order()[0].requested_symbol_count,1)
        self.assertEqual(replay(self.journal.database_path),replay(self.journal.database_path))

    def test_larger_uni_audit_counts_follow_each_slot_revision(self):
        p=poller(self.journal,self.clock)
        sample(p,self.clock,0);self.advance(0.1);self.submit();self.service.cycle()
        sample(p,self.clock,2);sample(p,self.clock,4);sample(p,self.clock,6);sample(p,self.clock,8)
        report=audit_quote_journal(self.journal.database_path,audited_at=START+timedelta(seconds=10))
        self.assertTrue(report.passed,report.findings)
        self.assertEqual(report.table_counts['quote_acquisition'],5)
        self.assertEqual(report.table_counts['quote_observation'],14)

    def test_rejected_capacity_request_has_outcome_without_membership_change(self):
        self.submit(symbols=('MSFT','NVDA'));self.service.cycle()
        original=self.latest();self.advance(1)
        refusal=self.submit(rid='full',symbols=('AMD',))
        self.assertFalse(refusal.event.accepted)
        self.assertEqual(self.service.cycle()['status'],'idle')
        self.assertEqual(self.latest(),original)
        self.assertEqual(self.service.snapshot()['outcomes'][-1]['kind'],'no_change')
