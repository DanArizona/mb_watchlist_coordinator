"""Synthetic tail-window proof using real native Hot persistence/recovery."""
from dataclasses import replace,asdict
from datetime import timedelta, timezone
import json
from pathlib import Path
import sqlite3
from contextlib import closing
import unittest
import subprocess
import sys
from unittest.mock import patch

from mb_market_data.quote_journal_audit import audit_quote_journal
from mb_market_data.quote_journal_replay import QuoteJournalReplayReader
from mb_market_data.sampling_acquisition import IsolatedSamplingPoller
from mb_watchlist_coordinator.daily_collector import DailyCollectorSettings, DailyHotCollector
from mb_watchlist_coordinator.sampling_requests import plain
import test_daily_session as daily_fixture
from test_integrated_identity import Response


class DailyCollectorTests(unittest.TestCase):
    def setUp(self):
        self.case=daily_fixture.DailySessionTests('test_preview_reads_published_anchor_and_creates_no_application_state_or_client')
        self.case.proof_directory_override=getattr(self,'proof_directory_override',None)
        self.case.setUp();self.addCleanup(self.case.doCleanups)
        tail=self.case.at.replace(hour=15,minute=59,second=50)
        self.case.now=tail-timedelta(seconds=getattr(self,'preparation_seconds',0))
        self.case.attach()
        self.settings=DailyCollectorSettings(str(self.case.journal), plain(self.case.session.service.identity),
            plain(self.case.session.binding), plain(self.case.session.claim), tail.isoformat(),
            tail.replace(hour=16,minute=0,second=0).isoformat(), 100, 1)
        self.calls=[];self.clients=[];case=self
        class Client:
            def quotes(self,symbols,*,fields):
                case.calls.append(list(symbols));return Response(symbols[0])
            def close(self): pass
        def factory():
            client=Client();self.clients.append(client);return client
        self.factory=factory
        self.collector=self.make();self.addCleanup(lambda:self.collector.close())

    def make(self,**changes):
        return DailyHotCollector(replace(self.settings,**changes),publication_session=self.case.session,
            client_factory=self.factory,clock=lambda:self.case.now,activation_approved=True)

    def tick(self,second,**kwargs):
        from datetime import datetime
        self.case.now=self.case.now.replace(second=second)
        case=self.case
        class Clock(datetime):
            @classmethod
            def now(cls,tz=None):return case.now.astimezone(tz or timezone.utc)
        with patch('mb_market_data.schwab_quotes.datetime',Clock):return self.collector.tick(**kwargs)

    def admit(self):
        self.case.now=self.case.now.replace(second=53)
        self.case.admit()

    def test_tail_window_idle_then_three_hot_quotes_native_audit_and_replays(self):
        self.collector.prepare(create=True)
        self.tick(52)
        self.admit()
        for second in (54,56,58):self.tick(second)
        self.assertEqual(self.calls,[['NVDA']]*3)
        audit=audit_quote_journal(self.case.journal,audited_at=self.case.now.replace(hour=16,minute=0,second=0))
        self.assertTrue(audit.passed,audit)
        first=tuple(QuoteJournalReplayReader(self.case.journal).events())
        self.assertEqual(first,tuple(QuoteJournalReplayReader(self.case.journal).events()))
        with closing(sqlite3.connect(self.case.journal)) as c:
            self.assertEqual(c.execute('SELECT count(*) FROM quote_acquisition WHERE channel="hot"').fetchone()[0],3)
            self.assertEqual(c.execute('SELECT count(*) FROM poll_slot_skip WHERE channel="hot"').fetchone()[0],1)
        self.assertEqual(len(self.case.store.membership_revisions_in_effective_order()),3)

    def test_isolated_constructor_still_refuses_the_daily_journal(self):
        with self.assertRaises(ValueError):
            IsolatedSamplingPoller(self.case.store,settings=self.collector.poller.settings,client=self.collector)

    def test_activation_is_an_explicit_trusted_api_assertion(self):
        with self.assertRaises(ValueError):DailyHotCollector(self.settings,publication_session=self.case.session,
            client_factory=self.factory,clock=lambda:self.case.now)
        self.assertFalse(self.collector.poller.path.exists())

    def test_native_callback_must_explicitly_confirm_the_publication_binding(self):
        from mb_market_data.daily_hot_acquisition import DailyHotPoller
        with self.assertRaises(ValueError):
            DailyHotPoller(self.case.store,settings=self.collector.poller.settings,client=self.collector,
                daily_binding=self.settings.daily_binding,daily_claim=self.settings.daily_claim,
                publication_binding=self.settings.publication_binding,validate_publication=lambda _:False,
                clock=lambda:self.case.now,activation_approved=True)
        self.assertFalse(self.collector.poller.path.exists())

    def test_daily_full_window_is_explicitly_accepted_without_claiming_provider_capacity(self):
        start=self.case.at.replace(hour=9,minute=30,second=0)
        collector=self.make(start_at_utc=start.isoformat(),max_quote_calls=9360)
        self.assertEqual(collector.identity['max_quote_calls'],9360)
        self.assertFalse(self.calls)
        self.assertFalse(collector.poller.path.exists())

    def test_final_permitted_slot_is_schedule_completion_without_another_provider_call(self):
        self.admit()
        self.collector.close()
        self.collector=self.make(start_at_utc=self.case.now.replace(second=57).isoformat(),max_quote_calls=1)
        self.collector.prepare(create=True)
        self.tick(58)
        self.assertEqual(self.tick(59)['status'],'schedule_complete')
        self.assertEqual(self.tick(59)['status'],'schedule_complete')
        self.assertEqual(self.calls,[['NVDA']])
        self.assertTrue(audit_quote_journal(self.case.journal,
            audited_at=self.case.now.replace(hour=16,minute=0,second=0)).passed)

    def test_daily_limits_cannot_be_widened_by_boolean_or_extra_symbols(self):
        for changes in ({'max_quote_calls':9361},{'max_quote_calls':True},{'max_symbols':2}):
            with self.assertRaises(ValueError):self.make(**changes)

    def test_identity_reservation_call_is_not_a_hot_collection_permit(self):
        self.collector.prepare(create=True);self.tick(52);self.admit();self.tick(54)
        state=self.collector.poller.snapshot()
        used=sum(e['kind']=='dispatch' and bool(e['symbols']) for e in state['events'])
        self.assertEqual(used,1)
        self.assertEqual(self.case.session.status()['identity_quote_permits'],1)

    def test_collector_restart_uses_original_window_and_no_past_slot_catchup(self):
        self.collector.prepare(create=True);self.tick(52);self.admit();self.tick(54)
        self.collector.close();self.case.now=self.case.now.replace(second=57)
        self.collector=self.make();self.collector.prepare()
        self.assertEqual(self.collector.next.scheduled_at.second,58)
        self.tick(58)
        self.assertEqual(len(self.calls),2)
        audit=audit_quote_journal(self.case.journal,audited_at=self.case.now.replace(hour=16,minute=0,second=0))
        self.assertFalse(audit.passed) # The deliberately missed :56 stays missing.

    def test_saved_assembled_response_recovers_without_a_second_provider_call(self):
        self.collector.prepare(create=True);self.tick(52);self.admit()
        def fault(stage):
            if stage=='after_assembled':raise RuntimeError('synthetic interruption')
        with self.assertRaises(RuntimeError):self.tick(54,fault_hook=fault)
        self.collector.close();self.case.now=self.case.now.replace(second=55)
        self.collector=self.make();self.collector.prepare()
        self.assertEqual(self.calls,[['NVDA']])
        with closing(sqlite3.connect(self.case.journal)) as c:
            self.assertEqual(c.execute('SELECT count(*) FROM quote_acquisition WHERE channel="hot"').fetchone()[0],1)

    def test_unknown_dispatch_is_never_retried_or_filled_with_later_quotes(self):
        self.collector.prepare(create=True);self.tick(52);self.admit()
        def fault(stage):
            if stage=='after_dispatch':raise RuntimeError('synthetic interruption')
        with self.assertRaises(RuntimeError):self.tick(54,fault_hook=fault)
        self.collector.close();self.case.now=self.case.now.replace(second=55)
        self.collector=self.make();self.collector.prepare();self.tick(56)
        self.assertEqual(self.calls,[['NVDA']])
        with closing(sqlite3.connect(self.case.journal)) as c:
            statuses=dict(c.execute('SELECT status,count(*) FROM quote_observation GROUP BY status').fetchall())
        self.assertEqual(statuses,{'quote':1})
        state=self.collector.poller.snapshot()
        self.assertEqual(sum(e['kind']=='dispatch' and bool(e['symbols']) for e in state['events']),2)
        self.assertTrue(any(e['kind']=='abandoned' for e in state['events']))
        self.assertFalse(audit_quote_journal(self.case.journal,
            audited_at=self.case.now.replace(hour=16,minute=0,second=0)).passed)

    def test_hot_call_ceiling_persists_across_restarts(self):
        self.settings=replace(self.settings,max_quote_calls=1);self.collector=self.make()
        self.collector.prepare(create=True);self.tick(52);self.admit();self.tick(54)
        self.collector.close();self.case.now=self.case.now.replace(second=55)
        self.collector=self.make();self.collector.prepare()
        self.assertEqual(self.tick(56)['status'],'budget_exhausted')
        self.assertEqual(len(self.calls),1)

    def test_changed_claim_or_foreign_publication_blocks_before_provider(self):
        self.collector.prepare(create=True);self.tick(52);self.admit()
        self.case.session.claim_path.write_text('{}')
        with self.assertRaises(ValueError):self.tick(54)
        self.assertFalse(self.calls)

    def test_closed_publication_owner_prevents_new_native_dispatch(self):
        self.collector.prepare(create=True);self.tick(52);self.admit();self.case.close()
        with self.assertRaises(ValueError):self.tick(54)
        self.assertFalse(self.calls)

    def test_no_provider_call_at_or_after_close(self):
        self.collector.prepare(create=True)
        self.case.now=self.case.now.replace(hour=16,minute=0,second=0)
        self.assertEqual(self.collector.tick()['status'],'window_ended')
        self.assertFalse(self.calls)

    def test_duplicate_daily_collector_lifetime_owner_is_refused(self):
        from mb_watchlist_coordinator.sampling_service import ServiceBusy
        self.collector.prepare(create=True)
        other=self.make()
        with self.assertRaises(ServiceBusy):other.prepare()
        self.assertFalse(self.calls)

    def crash(self,stage):
        import mb_market_data
        self.collector.prepare(create=True);self.tick(52);self.admit()
        self.collector.close();self.case.close()
        job={'publication_settings':asdict(self.case.settings),'catalog':str(self.case.root/'catalog'),
            'collector':asdict(self.settings),'at':self.case.now.replace(second=54).isoformat(),
            'native_src':str(Path(mb_market_data.__file__).resolve().parents[1]),'stage':stage}
        result=subprocess.run([sys.executable,'-I','-B',str(Path(__file__).parent/'fixtures/daily_collector_worker.py')],
            input=json.dumps(job).encode(),stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=15)
        self.assertEqual(result.returncode,75,result.stderr.decode(errors='replace'))
        self.case.now=self.case.now.replace(second=55);self.case.attach(create=False)
        self.collector=self.make();self.collector.prepare()

    def test_actual_process_loss_after_assembled_response_recovers_without_sdk_call(self):
        self.crash('after_assembled')
        self.assertFalse(self.calls)
        self.assertFalse(self.clients)
        self.assertEqual((self.case.root/'native-provider-calls.txt').read_text().splitlines(),['NVDA'])
        with closing(sqlite3.connect(self.case.journal)) as c:
            self.assertEqual(c.execute('SELECT count(*) FROM quote_acquisition WHERE channel="hot"').fetchone()[0],1)

    def test_actual_process_loss_after_journal_commit_reconciles_single_receipt(self):
        self.crash('after_journal_commit')
        self.assertFalse(self.calls)
        with closing(sqlite3.connect(self.case.journal)) as c:
            self.assertEqual(c.execute('SELECT count(*) FROM quote_acquisition WHERE channel="hot"').fetchone()[0],1)

    def test_actual_process_loss_after_dispatch_retains_unknown_and_consumes_permit(self):
        self.crash('after_dispatch')
        self.assertFalse(self.calls)
        self.assertFalse((self.case.root/'native-provider-calls.txt').exists())
        state=self.collector.poller.snapshot()
        self.assertTrue(any(e['kind']=='abandoned' for e in state['events']))
        self.assertEqual(sum(e['kind']=='dispatch' and bool(e['symbols']) for e in state['events']),1)

    def test_rate_limit_is_durable_and_new_collector_cannot_resume_provider_work(self):
        case=self
        class Limited:
            def quotes(self,symbols,*,fields):
                case.calls.append(list(symbols))
                response=Response(symbols[0],status=429);response.ok=False
                response.text='synthetic HTTP rate limit'
                return response
            def close(self):pass
        self.factory=Limited;self.collector=self.make()
        self.collector.prepare(create=True);self.tick(52);self.admit()
        self.assertEqual(self.tick(54)['status'],'blocked')
        self.collector.close();self.case.now=self.case.now.replace(second=55)
        self.collector=self.make()
        with self.assertRaises(ValueError):self.collector.prepare()
        self.assertEqual(self.calls,[['NVDA']])
        self.collector.provider_stop_path.unlink()
        with self.assertRaises(ValueError):self.make().prepare()
        self.assertEqual(self.calls,[['NVDA']])


if __name__=='__main__':unittest.main()
