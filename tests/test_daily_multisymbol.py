"""Changed multi-symbol envelope: logical ledger cases, real native persistence.

Logical time in these focused cases does not qualify elapsed process/provider
performance; the separate owned burst/history proof measures those scopes.
"""
from contextlib import closing
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import hashlib
import subprocess
import sys
import threading
from functools import lru_cache
import unittest
from unittest.mock import patch

from mb_watchlist_coordinator.daily_collector import DailyCollectorSettings, DailyHotCollector
from mb_watchlist_coordinator.daily_epoch_collector import make_daily_collector
from mb_watchlist_coordinator.daily_session import DailySession
from mb_watchlist_coordinator.daily_worker_view import DailyPublicationReader
from mb_watchlist_coordinator.integrated_catalog import DirectoryCatalog
from mb_watchlist_coordinator.integrated_identity import IdentityStopRequired
from mb_watchlist_coordinator.operating_plan import MULTI_PROFILE, proposed_policy, validate_policy
from mb_watchlist_coordinator.sampling_requests import digest, plain
import test_daily_session as legacy
from test_integrated_catalog import sources, receipts
from test_integrated_identity import Response


SYMBOLS = tuple(f'X{n:03d}' for n in range(150))


def large_catalog(at):
    bodies = sources(at)
    header, footer = bodies['nasdaq'].rsplit(b'File Creation Time:', 1)
    extra = ''.join(f'{s}|Synthetic burst {s}|Q|N|N|100|N\n' for s in SYMBOLS).encode()
    bodies['nasdaq'] = header+extra+b'File Creation Time:'+footer
    return DirectoryCatalog(bodies, receipts(at))


class MultiFixture:
    def __init__(self, *, background=False, root=None, at_open=False):
        self.case = legacy.DailySessionTests('test_preview_reads_published_anchor_and_creates_no_application_state_or_client')
        self.case.catalog_factory_override = large_catalog
        if root is not None:
            self.case.proof_directory_override = str(root)
        if background:
            self.case.universe_symbols_override = ['IBM', 'MSFT']+[f'C{n:04d}' for n in range(598)]
            self.case.focus_symbols_override = self.case.universe_symbols_override[:40]
            self.case.full_window_run_configs = at_open
        self.case.setUp()
        if at_open:
            self.case.now=self.case.at.replace(hour=9,minute=30,second=1)
            self.case.at=self.case.now+timedelta(seconds=59)
        self.case.settings = replace(self.case.settings, policy_profile=MULTI_PROFILE,
            policy_sha256=digest(proposed_policy(MULTI_PROFILE)))
        self.session = self.case.session = DailySession(self.case.settings, self.case.catalog,
            clock=lambda: self.case.now)
        self.session.attach(create=True, publication_approved=True)
        self.session.gate.monotonic = lambda: self.case.now.timestamp()

    def close(self):
        self.case.doCleanups()

    def queue(self, symbols, *, capture='burst', offset=0):
        rows = [self.case.row(s, seconds=n%50+offset) for n, s in enumerate(symbols)]
        self.session.recovery.record(self.session.recovery.settings.queries[0],
            self.case.snapshot('HISTORICAL', rows, capture))
        self.session.gate.reconcile()

    def pump(self, **kwargs):
        result = self.session.gate.deliver_pending(client=self.case.client, **kwargs)
        self.session.service.cycle()
        return result

    def advance(self, seconds=2):
        self.case.now += timedelta(seconds=seconds)

    def gate(self):
        return plain(self.session.gate.snapshot())['identity_gate']


class MultiIdentityTests(unittest.TestCase):
    def setUp(self):
        self.f = MultiFixture(); self.addCleanup(self.f.close)
        self.c, self.s = self.f.case, self.f.session

    def test_profile_is_explicit_sealed_and_does_not_change_single_symbol_default(self):
        self.assertEqual(proposed_policy()['limits']['maximum_active_hot_symbols'], 1)
        policy = proposed_policy(MULTI_PROFILE)
        self.assertEqual(policy['limits']['maximum_active_hot_symbols'], 40)
        self.assertEqual(validate_policy(policy), policy)
        policy['limits']['maximum_active_hot_symbols'] = 41
        with self.assertRaises(ValueError): validate_policy(policy)
        with self.assertRaises(ValueError): proposed_policy('unlimited')

    def test_one_cycle_authorizes_only_one_of_a_burst_and_returns_pending_work(self):
        self.f.queue(SYMBOLS[:4]); self.f.pump()
        self.assertEqual(len(self.c.calls), 1)
        self.assertEqual(len(self.f.gate()['authorized_symbols']), 1)
        self.assertTrue(self.s.gate.snapshot()['pending'])

    def test_identity_spacing_is_durable_and_does_not_sleep_or_charge_deferred_work(self):
        self.f.queue(SYMBOLS[:2]); self.f.pump()
        self.f.advance(1.99); self.f.pump()
        self.assertEqual(len(self.c.calls), 1)
        self.assertEqual(self.f.gate()['quote_permits'], 1)
        self.f.advance(.01); self.f.pump()
        self.assertEqual(len(self.c.calls), 2)

    def test_monotonic_spacing_also_fences_a_forward_wall_clock_jump(self):
        now = [10.0]; self.s.gate.monotonic = lambda: now[0]
        self.f.queue(SYMBOLS[:2]); self.f.pump()
        self.f.advance(30); self.f.pump()
        self.assertEqual(len(self.c.calls), 1)
        now[0] += 2; self.f.pump()
        self.assertEqual(len(self.c.calls), 2)

    def test_forty_authorizations_and_nested_membership_then_durable_overflow_without_quote(self):
        self.f.queue(SYMBOLS[:41])
        for _ in range(41): self.f.pump(); self.f.advance()
        state = self.f.gate()
        self.assertEqual(len(self.c.calls), 40)
        self.assertEqual(len(state['authorized_symbols']), 40)
        self.assertIn('authorization_capacity', state['dispositions'].values())
        self.f.advance(); self.s.service.cycle()
        r = self.c.store.latest_membership_revision_effective_at(self.c.now)
        self.assertEqual(len(r.hot_symbols), 40)
        self.assertTrue(set(r.hot_symbols) <= set(r.focus_symbols) <= set(r.uni_symbols))

    def test_same_symbol_new_command_reuses_its_own_identity_without_another_quote(self):
        self.f.queue(SYMBOLS[:1]); self.f.pump(); self.f.advance()
        self.f.queue(SYMBOLS[:1], capture='second', offset=20); self.f.pump()
        self.assertEqual(len(self.c.calls), 1)
        approvals = [e for e in self.f.gate()['events'] if e.get('code') == 'approved']
        self.assertEqual(len(approvals), 2)
        self.assertEqual(approvals[1]['outcome']['reuse_of'], approvals[0]['command_id'])

    def test_unknown_identity_response_is_charged_and_never_requested_again_after_reopen(self):
        self.f.queue(SYMBOLS[:1])
        def crash(stage):
            if stage == 'after_identity_response': raise RuntimeError('synthetic process-loss boundary')
        with self.assertRaises(RuntimeError): self.f.pump(fault_hook=crash)
        self.assertEqual(len(self.c.calls), 1)
        self.s.close(); self.f.advance()
        self.f.session = self.s = self.c.session = DailySession(self.c.settings, self.c.catalog, clock=lambda:self.c.now)
        self.s.attach(create=False, publication_approved=True)
        self.s.gate.monotonic = lambda:self.c.now.timestamp()
        self.f.pump()
        self.assertEqual(len(self.c.calls), 1)
        self.assertEqual(self.f.gate()['quote_permits'], 1)
        self.assertIn('identity_outcome_unknown_no_retry', self.f.gate()['dispositions'].values())

    def test_request_commit_before_ack_is_reconciled_without_another_quote_or_request(self):
        self.f.queue(SYMBOLS[:1])
        def crash(_): raise RuntimeError('after request commit')
        with self.assertRaises(RuntimeError): self.f.pump(after_submit=crash)
        requests = len(self.s.requests.events())
        self.f.pump()
        self.assertEqual(len(self.c.calls), 1)
        self.assertEqual(len(self.s.requests.events()), requests)
        self.assertEqual(len(self.s.delivery.snapshot()['deliveries']), 1)

    def test_rate_limit_is_charged_and_latched_before_any_second_symbol(self):
        self.f.queue(SYMBOLS[:2])
        calls = []
        class Limited:
            def quotes(self, symbols, *, fields):
                calls.append(symbols); return Response(symbols[0], status=429)
        self.c.client = Limited()
        with self.assertRaises(IdentityStopRequired): self.f.pump()
        self.f.advance(2)
        with self.assertRaises(IdentityStopRequired): self.f.pump()
        self.assertEqual(len(calls), 1)
        self.assertTrue(self.f.gate()['provider_stop_required'])

    def test_forged_authorization_is_rejected_before_collection(self):
        self.f.queue(SYMBOLS[:1]); self.f.pump()
        with closing(sqlite3.connect(self.s.gate.gate_path)) as c, c:
            raw = json.loads(c.execute('SELECT payload FROM identity_event WHERE sequence=2').fetchone()[0])
            raw['symbol'] = SYMBOLS[1]
            c.execute('UPDATE identity_event SET payload=? WHERE sequence=2', (json.dumps(raw),))
        with self.assertRaises(ValueError): self.s.validate()

    def test_three_unconfirmed_lookups_for_one_symbol_do_not_consume_the_whole_session_budget(self):
        self.f.queue([SYMBOLS[0]]*4)
        calls = []
        class Unconfirmed:
            def quotes(self, symbols, *, fields):
                calls.append(symbols); return Response(symbols[0], body={})
        self.c.client = Unconfirmed()
        for _ in range(4): self.f.pump(); self.f.advance()
        self.assertEqual(len(calls),3)
        self.assertIn('symbol_identity_budget_exhausted',self.f.gate()['dispositions'].values())
        self.assertFalse(self.f.gate()['authorized_symbols'])

    def test_one_hundred_twenty_cumulative_permits_are_not_reset_by_reopen(self):
        self.f.queue(SYMBOLS[:121])
        calls = []
        class Unconfirmed:
            def quotes(self, symbols, *, fields):
                calls.append(symbols); return Response(symbols[0], body={})
        self.c.client = Unconfirmed()
        for _ in range(121):
            self.s.gate.deliver_pending(client=self.c.client); self.f.advance()
        self.assertEqual(len(calls),120)
        self.assertIn('identity_budget_exhausted',self.f.gate()['dispositions'].values())
        self.s.close()
        self.f.session = self.s = self.c.session = DailySession(self.c.settings,self.c.catalog,clock=lambda:self.c.now)
        self.s.attach(create=False,publication_approved=True)
        self.assertEqual(self.f.gate()['quote_permits'],120)
        self.f.pump(); self.assertEqual(len(calls),120)

    def test_read_only_worker_reconstructs_multi_symbol_identity_and_keeps_existing_owner(self):
        self.f.queue(SYMBOLS[:2]); self.f.pump(); self.f.advance(); self.f.pump()
        reader = DailyPublicationReader(self.c.settings, self.c.root/'catalog',
            binding=self.s.binding, claim=self.s.claim, publication_binding=self.s.service.identity,
            clock=lambda:self.c.now, fence=lambda:None)
        self.assertTrue(reader.validate())
        self.assertEqual(reader.gate.snapshot()['identity_gate']['authorized_symbols'], tuple(SYMBOLS[:2]))


class MultiPublicationTests(unittest.TestCase):
    def setUp(self):
        self.f = MultiFixture(); self.addCleanup(self.f.close)
        self.c,self.s = self.f.case,self.f.session
        self.f.queue(SYMBOLS[:2]); self.f.pump(); self.f.advance()

    def test_returned_snapshot_cannot_mutate_a_later_verified_publication_view(self):
        view = plain(self.s.service.snapshot())
        view['journal'][-1]['proposal']['hot_symbols'].append('FORGED')
        self.assertNotIn('FORGED',self.s.service.snapshot()['journal'][-1]['proposal']['hot_symbols'])

    def test_warm_publication_view_rejects_modified_old_outcome_bytes(self):
        self.s.service.snapshot()
        with closing(sqlite3.connect(self.s.service.path)) as c,c:
            value = json.loads(c.execute('SELECT payload FROM publication_event WHERE sequence=1').fetchone()[0])
            value['kind'] = 'forged'
            c.execute('UPDATE publication_event SET payload=? WHERE sequence=1',(json.dumps(value),))
        with self.assertRaises(ValueError):self.s.service.snapshot()

    def test_warm_publication_view_rejects_deleted_request_prefix(self):
        self.s.service.snapshot()
        with closing(sqlite3.connect(self.s.requests.path)) as c,c:
            c.execute('DELETE FROM request_event WHERE sequence=1')
        with self.assertRaises(ValueError):self.s.service.snapshot()

    def test_native_commit_before_ack_reconciles_exactly_once_with_new_membership_proof(self):
        self.s.gate.deliver_pending(client=self.c.client)
        def fault(stage):
            if stage=='after_commit':raise RuntimeError('native commit boundary')
        with self.assertRaises(RuntimeError):self.s.service.cycle(fault_hook=fault)
        revisions = len(self.c.store.membership_revisions_in_effective_order())
        self.s.service.cycle()
        self.assertEqual(len(self.c.store.membership_revisions_in_effective_order()),revisions)
        self.assertFalse(self.s.service.snapshot()['unacknowledged'])

    def test_reader_cannot_reuse_old_view_through_a_concurrent_owned_publication(self):
        from mb_watchlist_coordinator.sampling_service import ServiceBusy
        reader = DailyPublicationReader(self.c.settings,self.c.root/'catalog',
            binding=self.s.binding,claim=self.s.claim,publication_binding=self.s.service.identity,
            clock=lambda:self.c.now,fence=lambda:None)
        reader.validate()
        self.s.gate.deliver_pending(client=self.c.client)
        entered,go = threading.Event(),threading.Event(); failures=[]
        def hook(stage):
            if stage=='after_commit':
                entered.set()
                if not go.wait(3):raise RuntimeError('barrier timeout')
        def publish():
            try:self.s.service.cycle(fault_hook=hook)
            except BaseException as error:failures.append(error)
        worker=threading.Thread(target=publish);worker.start()
        try:
            self.assertTrue(entered.wait(3))
            with self.assertRaises(ServiceBusy):reader.validate()
        finally:
            go.set();worker.join(timeout=3)
        self.assertFalse(worker.is_alive());self.assertFalse(failures,failures)
        self.assertTrue(reader.validate())
        self.assertEqual(len(reader.service.snapshot()['journal'][-1]['proposal']['hot_symbols']),2)


@lru_cache(maxsize=1)
def _quote_shape():
    import importlib.util
    path = Path(__file__).resolve().parents[1]/'experiments/daily_hot_operating_20261028/capacity_probe.py'
    spec = importlib.util.spec_from_file_location('_multi_quote_shape', path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module.quote_payload


def full_quotes(symbols, at):
    # Retain the already reviewed complete quote shape for the larger workload.
    body = {}
    for n, symbol in enumerate(symbols):
        payload = _quote_shape()(at, n); payload['symbol'] = symbol
        body[symbol] = payload
    return body


def replay_identity(journal):
    from mb_market_data.quote_journal_replay import QuoteJournalReplayReader
    h = hashlib.sha256(); count = 0
    for event in QuoteJournalReplayReader(journal).events():
        count += 1; h.update((event.event_id+'\n').encode())
    return {'events': count, 'sequence_sha256': h.hexdigest()}


class MultiNativeTests(unittest.TestCase):
    def setUp(self):
        self.f = MultiFixture(background=self._testMethodName ==
            'test_actual_native_batches_follow_forty_admissions_and_overflow_with_audit_and_replay')
        self.addCleanup(self.f.close)
        self.c, self.s = self.f.case, self.f.session
        self.quote_calls = []
        case = self
        class Client:
            def quotes(self, symbols, *, fields):
                case.quote_calls.append(list(symbols))
                return Response(symbols[0], body=full_quotes(symbols, case.c.now))
            def close(self): pass
        self.settings = DailyCollectorSettings(str(self.c.journal), plain(self.s.service.identity),
            plain(self.s.binding), plain(self.s.claim), self.c.at.isoformat(),
            (self.c.at+timedelta(minutes=10)).isoformat(), 240, 40)
        self.factory = Client
        self.collector = self.make(); self.addCleanup(lambda:self.collector.close())

    def make(self, factory=None):
        return make_daily_collector(self.settings, publication_session=self.s,
            client_factory=factory or self.factory, clock=lambda:self.c.now, activation_approved=True)

    def tick(self):
        self.c.now = self.collector.next.scheduled_at+timedelta(milliseconds=50)
        case = self
        class Clock(datetime):
            @classmethod
            def now(cls, tz=None): return case.c.now.astimezone(tz or timezone.utc)
        with patch('mb_market_data.schwab_quotes.datetime', Clock): return self.collector.tick()

    def test_actual_native_batches_follow_forty_admissions_and_overflow_with_audit_and_replay(self):
        from mb_market_data.quote_journal_audit import audit_quote_journal
        self.f.queue(SYMBOLS[:41]); self.collector.prepare(create=True)
        for _ in range(41): self.f.pump(); self.tick()
        self.assertEqual(len(self.c.calls), 40)
        self.assertEqual(len(self.quote_calls[-1]), 40)
        self.assertTrue(all(len(s) <= 40 for s in self.quote_calls))
        effective = self.c.store.latest_membership_revision_effective_at(self.c.now)
        self.assertEqual((len(effective.uni_symbols),len(effective.focus_symbols),len(effective.hot_symbols)),(640,80,40))
        audit = audit_quote_journal(self.c.journal, audited_at=self.c.now)
        self.assertTrue(audit.passed, audit)
        self.assertEqual(replay_identity(self.c.journal), replay_identity(self.c.journal))

    def test_multi_symbol_collector_refuses_widened_or_wrong_sealed_roster(self):
        with self.assertRaises(ValueError): replace(self.settings, max_symbols=41).payload()
        self.f.queue(SYMBOLS[:1]); self.f.pump(); self.f.advance()
        self.collector.prepare(create=True)
        r = self.c.store.latest_membership_revision_effective_at(self.c.now)
        with self.assertRaises(ValueError):
            self.collector.validate_publication({'revision':r.revision, 'symbols':[SYMBOLS[149]]})

    def test_warm_preview_still_reads_and_rejects_changed_membership_values(self):
        self.c.settings.preview()
        with closing(sqlite3.connect(self.c.journal)) as connection, connection:
            connection.execute("UPDATE sampling_channel_member SET symbol='TAMPER' WHERE revision=1 AND channel='uni' AND ordinal=0")
        from mb_market_data.quote_observation_store import QuoteObservationStoreError
        with self.assertRaises((QuoteObservationStoreError,ValueError)): self.c.settings.preview()

    def test_forty_row_saved_response_recovers_after_actual_process_exit_without_second_call(self):
        from dataclasses import asdict
        import mb_market_data
        self.f.queue(SYMBOLS[:40])
        for _ in range(40): self.f.pump(); self.f.advance()
        self.collector.prepare(create=True)
        at = self.collector.next.scheduled_at
        self.collector.close()
        job = {'publication_settings':asdict(self.c.settings),'catalog':str(self.c.root/'catalog'),
            'binding':plain(self.s.binding),'claim':plain(self.s.claim),
            'collector':asdict(self.settings),'at':at.isoformat(),
            'native_src':str(Path(mb_market_data.__file__).resolve().parents[1]),
            'stage':'after_assembled', 'call_log':str(self.c.root/'multi-native-calls.jsonl')}
        run = subprocess.run([sys.executable,'-I','-B',str(Path(__file__).parent/'fixtures/multi_collector_process.py')],
            input=json.dumps(job).encode(),stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=20)
        self.assertEqual(run.returncode,75,run.stderr.decode(errors='replace'))
        calls = Path(job['call_log']).read_text().splitlines()
        self.assertEqual(len(calls),1); self.assertEqual(len(json.loads(calls[0])),40)
        def forbidden(): raise AssertionError('Saved assembled response must not request quotes again')
        self.c.now = at+timedelta(seconds=1)
        self.collector = self.make(forbidden); self.collector.prepare()
        with closing(sqlite3.connect(self.c.journal)) as c:
            self.assertEqual(c.execute('SELECT count(*) FROM quote_acquisition WHERE channel="hot"').fetchone()[0],1)
            self.assertEqual(c.execute('SELECT count(*) FROM quote_observation').fetchone()[0],40)
        self.assertEqual(Path(job['call_log']).read_text().splitlines(),calls)


class MultiSourceContentionTests(unittest.TestCase):
    def setUp(self):
        from mb_watchlist_coordinator.daily_source import DailySourcePump
        self.f=MultiFixture();self.addCleanup(self.f.close)
        self.c,self.s=self.f.case,self.f.session
        self.pump=DailySourcePump(self.s,identity_client=self.c.client,clock=lambda:self.c.now)
        self.pump.initialize(create=True);self.addCleanup(self.pump.close)

    def test_nested_publication_collision_yields_once_without_integrity_block_or_retry(self):
        from mb_watchlist_coordinator.sampling_service import ServiceBusy
        with patch.object(self.pump.authority,'_cycle',side_effect=ServiceBusy('forced nested read'))as body:
            result=self.pump.cycle()
        body.assert_called_once();self.assertEqual(result['status'],'WAITING')
        self.assertFalse(result['operation_retried']);self.assertFalse(self.c.calls)
        self.assertFalse((self.s.root/'daily-source-failure.json').exists())

    def test_real_authority_lease_collision_remains_blocked_and_does_not_enter_body(self):
        from mb_watchlist_coordinator.sampling_service import owner_lock
        with owner_lock(self.pump.authority.path.with_suffix('.owner.lock')):
            with patch.object(self.pump.authority,'_cycle')as body:result=self.pump.cycle()
        body.assert_not_called();self.assertEqual(result['status'],'BLOCKED')
        self.assertEqual(result['detail'],'Authority already owned')

    def test_collision_after_durable_identity_result_does_not_repeat_provider_call(self):
        from mb_watchlist_coordinator.sampling_service import ServiceBusy
        self.f.queue(SYMBOLS[:1])
        def body(**kwargs):
            self.s.gate.deliver_pending(client=self.c.client)
            raise ServiceBusy('forced after durable response')
        with patch.object(self.pump.authority,'_cycle',side_effect=body):
            self.assertEqual(self.pump.cycle()['status'],'WAITING')
            self.assertEqual(self.pump.cycle()['status'],'WAITING')
        self.assertEqual(len(self.c.calls),1)


class MultiPeriodTests(unittest.TestCase):
    def setUp(self):
        self.h=MultiNativeTests('test_multi_symbol_collector_refuses_widened_or_wrong_sealed_roster')
        self.h.setUp();self.addCleanup(self.h.doCleanups)
        self.c,self.s,self.f=self.h.c,self.h.s,self.h.f

    def prepare_boundary(self):
        self.f.queue(SYMBOLS[:2]);self.f.pump();self.f.advance();self.f.pump();self.f.advance()
        self.h.collector.close()
        self.h.settings=replace(self.h.settings,start_at_utc=self.c.at.replace(minute=4,second=56).isoformat(),
            stop_at_utc=self.c.at.replace(minute=5,second=6).isoformat(),max_quote_calls=4)
        self.h.collector=self.h.make();self.h.collector.client=self.h.factory()
        self.h.collector.prepare(create=True)

    def cross(self):
        self.prepare_boundary();self.h.tick();self.h.tick()
        self.c.now=self.c.at.replace(minute=5,second=0)+timedelta(milliseconds=50)
        self.h.collector.tick();self.h.tick();self.h.tick()

    def test_full_session_periods_partition_exactly_9360_unique_slots(self):
        from mb_watchlist_coordinator.daily_epoch_collector import period_windows
        start=self.c.at.replace(hour=9,minute=30);stop=start.replace(hour=16,minute=0)
        periods=period_windows(start.isoformat(),stop.isoformat())
        self.assertEqual(len(periods),78)
        self.assertEqual(sum(p[3]for p in periods),9360)
        self.assertTrue(all(periods[n][2]==periods[n+1][1]for n in range(77)))

    def test_insufficient_global_call_budget_is_refused_before_state_or_client_creation(self):
        with self.assertRaises(ValueError):
            make_daily_collector(replace(self.h.settings,max_quote_calls=1),publication_session=self.s,
                client_factory=self.h.factory,clock=lambda:self.c.now,activation_approved=True)
        self.assertFalse(self.c.calls);self.assertFalse(self.h.quote_calls)

    def test_rollover_retains_all_native_rows_and_complete_schedule_audit(self):
        from mb_market_data.quote_journal_audit import audit_quote_journal
        self.cross()
        self.assertEqual(len(self.h.quote_calls),4)
        self.assertEqual(len(list(self.c.journal.parent.glob('*.hot.e*.poller.sqlite3'))),2)
        self.assertTrue(audit_quote_journal(self.c.journal,audited_at=self.c.now).passed)
        self.assertEqual(replay_identity(self.c.journal),replay_identity(self.c.journal))

    def test_closed_row_change_is_detected_by_full_audit_while_active_scope_remains_explicit(self):
        from mb_watchlist_coordinator.daily_epoch_integrity import verify_journal_content
        self.cross()
        with closing(sqlite3.connect(self.c.journal))as c,c:
            c.execute('UPDATE quote_observation SET quote_last_price=99 WHERE acquisition_id='
                '(SELECT acquisition_id FROM quote_acquisition ORDER BY scheduled_at_utc LIMIT 1) AND ordinal=0')
        # Closed payloads are deliberately not claimed as verified by the next
        # active heartbeat. The independent stored-value check must detect this old edit.
        self.assertTrue(self.h.collector.poller.snapshot())
        self.assertFalse(verify_journal_content(self.c.journal)['passed'])

    def test_independent_content_check_and_native_sequence_digest_match_full_replay(self):
        from mb_watchlist_coordinator.daily_epoch_integrity import verify_journal_content,replay_sequence_digest
        self.cross()
        self.h.collector.close()
        self.assertTrue(verify_journal_content(self.c.journal)['passed'])
        self.assertEqual(replay_sequence_digest(self.c.journal),replay_identity(self.c.journal))

    def test_missing_closed_ledger_blocks_resume_without_reset_or_api_call(self):
        self.cross();self.h.collector.close()
        old=sorted(self.c.journal.parent.glob('*.hot.e*.poller.sqlite3'))[0]
        old.unlink();calls=list(self.h.quote_calls)
        self.h.collector=self.h.make()
        with self.assertRaises(ValueError):self.h.collector.prepare()
        self.assertEqual(self.h.quote_calls,calls)




if __name__ == '__main__': unittest.main()
