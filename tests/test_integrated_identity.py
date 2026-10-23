from contextlib import closing
from datetime import datetime, timedelta
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest

from test_integrated_catalog import AT, catalog
from mb_watchlist_coordinator.integrated_catalog import DirectoryCatalog
from mb_watchlist_coordinator.integrated_identity import IdentityGatedDelivery, IdentityStopRequired
from mb_watchlist_coordinator.nasdaq_recovery import NasdaqRecoveryReceipts, RecoverySettings, RecoveryQuery
from mb_watchlist_coordinator.nasdaq_recovery_delivery import NasdaqRecoveryDelivery
from mb_watchlist_coordinator.nasdaq_sampling import HaltProducerSettings, HaltSnapshot, NasdaqSamplingProducer
from mb_watchlist_coordinator.sampling_admission import AdmissionPolicy
from mb_watchlist_coordinator.sampling_policy import SamplingPolicy
from mb_watchlist_coordinator.sampling_projection import SamplingMembership
from mb_watchlist_coordinator.sampling_request_store import SamplingRequestStore
from mb_watchlist_coordinator.sampling_requests import canonical, digest, plain, utc_text
from mb_watchlist_coordinator.sampling_service import owner_lock, ServiceBusy
from mb_watchlist_coordinator.authenticated_startup import StartupError

OWNER = 'nasdaq-shared-integrated'
SECRET = 'SYNTHETIC-IDENTITY-EXCEPTION-CANARY-42'


def build(root, clock, *, create=False):
    at = AT
    cat = catalog(at).persist(root/'catalog') if create else DirectoryCatalog.load(root/'catalog')
    requests = SamplingRequestStore(root/'requests.sqlite3', session_date=at.date(),
        baseline=SamplingMembership(frozenset({'MSFT', 'IBM'}), frozenset({'MSFT'}), frozenset()),
        policy=SamplingPolicy('admin', 0, 0, 'immediate_cap'),
        admission=AdmissionPolicy(cat.catalog_id, frozenset(cat.symbols), frozenset({OWNER}), 1, 'session'), clock=clock)
    if create: requests.initialize()
    live = NasdaqSamplingProducer(root/'live.sqlite3', request_store=requests,
        settings=HaltProducerSettings('observations', ('LUDP', 'M'), 'regular_close', False, False, 'external'), clock=clock)
    if create: live.initialize()
    query = RecoveryQuery(at.date(), at.date())
    recovery = NasdaqRecoveryReceipts(root/'recovery.sqlite3', request_store=requests,
        settings=RecoverySettings(at.date(), 'late_start', (query,), False), clock=clock)
    recovery.initialize(create=create)
    delivery = NasdaqRecoveryDelivery(root/'delivery.sqlite3', live_producer=live,
        recovery_receipts=recovery, producer_id=OWNER, clock=clock)
    delivery.initialize(create=create)
    gate = IdentityGatedDelivery(root/'identity.sqlite3', delivery=delivery, catalog=cat,
        start_at=utc_text(at), stop_at=utc_text(at+timedelta(seconds=720)), clock=clock)
    gate.initialize(create=create)
    return gate


class Response:
    ok = True
    def __init__(self, symbol, status=200, body=None):
        self.status_code = status
        self.body = body if body is not None else {symbol: {'symbol': symbol,
            'assetMainType': 'EQUITY', 'assetSubType': 'COE', 'quote': {'lastPrice': 12.0}}}
    def json(self): return self.body


class IdentityTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name); self.now = AT; self.calls = []; self.response = None
        self.gate = build(self.root, lambda: self.now, create=True)
        case = self
        class Client:
            def quotes(self, symbols, *, fields):
                case.calls.append((list(symbols), fields))
                if isinstance(case.response, Exception): raise case.response
                return case.response or Response(symbols[0])
        self.client = Client()

    def row(self, symbol='NVDA', seconds=0, **extras):
        return {'symbol': symbol, 'halt_date': AT.strftime('%m/%d/%Y'),
            'halt_time': (AT-timedelta(minutes=5)+timedelta(seconds=seconds)).strftime('%H:%M:%S.%f'),
            'reason_code': 'LUDP', **extras}

    def queue(self, rows=None, cid=None):
        rows = [self.row()] if rows is None else rows
        capture = HaltSnapshot(cid or 'capture-'+str(len(self.gate.recovery.snapshot()['receipts'])), self.now,
            'HISTORICAL', digest(rows), tuple(rows), {'synthetic_only': True})
        self.gate.recovery.record(self.gate.recovery.settings.queries[0], capture)
        return self.gate.reconcile()

    def state(self): return plain(self.gate.snapshot())['identity_gate']
    def deliver(self, **kw): return self.gate.deliver_pending(client=self.client, **kw)

    def test_exact_broker_identity_drives_normal_outside_uni_admission(self):
        self.queue(); (result,) = self.deliver()
        self.assertTrue(result.event.accepted)
        self.assertEqual(self.calls, [(['NVDA'], 'all')]); self.assertEqual(self.state()['quote_permits'], 1)
        self.assertEqual(self.gate.requests.states()[-1].applied.hot, {'NVDA'})
        self.assertEqual(self.gate.requests.states()[-1].applied.focus, {'MSFT', 'NVDA'})

    def test_resumed_recovery_preserves_original_times_and_release_fact(self):
        self.queue([self.row(resumption_trade_time='09:59:00')]); self.deliver()
        e = self.gate.requests.events()[0]
        self.assertEqual(e.payload['metadata']['halt_event']['resumption_trade_time'], '09:59:00')
        self.assertEqual(e.payload['metadata']['source_kind'], 'recovery')
        self.assertEqual(e.payload['created_at_utc'], utc_text(AT))

    def test_two_baseline_uni_symbols_cannot_bypass_single_symbol_fence(self):
        self.queue([self.row('MSFT'), self.row('IBM')]); self.deliver()
        self.assertEqual(len(self.calls), 1); self.assertEqual(len(self.gate.requests.events()), 1)
        self.assertEqual(set(self.state()['dispositions'].values()), {'approved', 'one_symbol_limit'})

    def test_reopening_and_cancellation_never_reset_selected_symbol(self):
        (cid,) = self.queue(); self.deliver()
        self.gate.requests.cancel_request('cancel', owner_id=OWNER, request_id=cid, actor_id=OWNER)
        self.gate = build(self.root, lambda: self.now)
        self.queue([self.row('MSFT')]); self.deliver()
        self.assertFalse(self.gate.requests.states()[-1].applied.hot)
        self.assertEqual(self.state()['selected_symbol'], 'NVDA'); self.assertEqual(len(self.calls), 1)

    def test_new_halt_same_symbol_reuses_identity_and_normal_active_request(self):
        self.queue(); self.deliver(); self.queue([self.row(seconds=30)]); (result,) = self.deliver()
        self.assertFalse(result.inserted); self.assertEqual(len(self.calls), 1)
        self.assertEqual(len(self.gate.requests.events()), 1)
        self.assertEqual(len(self.gate.delivery.snapshot()['deliveries']), 2)

    def test_resumption_update_is_retained_without_another_identity_lookup(self):
        self.queue(); self.deliver(); before = len(self.gate.recovery.snapshot()['receipts'])
        self.queue([self.row(resumption_trade_time='10:06:00')]); self.deliver()
        self.assertGreater(len(self.gate.recovery.snapshot()['receipts']), before)
        self.assertEqual(len(self.calls), 1)

    def test_missing_catalog_symbol_never_uses_a_quote_permit(self):
        self.queue([self.row('UNRESOLVED')]); self.assertFalse(self.deliver())
        self.assertEqual(set(self.state()['dispositions'].values()), {'catalog_unresolved'})
        self.assertFalse(self.calls); self.assertEqual(self.state()['quote_permits'], 0)

    def test_alias_wrong_asset_or_invalid_provider_body_never_authorizes(self):
        for body in ({'NVDA': {'symbol': 'OTHER', 'assetMainType': 'EQUITY', 'assetSubType': 'COE'}},
                {'NVDA': {'symbol': 'NVDA', 'assetMainType': 'EQUITY', 'assetSubType': 'ETF'}}, {}):
            self.response = Response('NVDA', body=body)
            self.queue([self.row(seconds=len(self.calls)*10)]); self.deliver()
        self.assertFalse(self.gate.requests.events()); self.assertIsNone(self.state()['selected_symbol'])

    def test_three_cumulative_permits_include_failed_calls_and_survive_reopen(self):
        self.response = RuntimeError(SECRET)
        for seconds in (0, 10, 20, 30):
            self.queue([self.row(seconds=seconds)]); self.deliver(); self.gate = build(self.root, lambda: self.now)
        self.assertEqual(len(self.calls), 3); self.assertEqual(self.state()['quote_permits'], 3)
        self.assertIn('identity_budget_exhausted', self.state()['dispositions'].values())
        for p in self.root.rglob('*'):
            if p.is_file(): self.assertNotIn(SECRET.encode(), p.read_bytes())

    def test_reserved_unknown_is_charged_and_exact_event_is_not_retried(self):
        (cid,) = self.queue()
        def fault(stage):
            if stage == 'after_identity_reservation': raise RuntimeError('synthetic interruption')
        with self.assertRaises(RuntimeError): self.deliver(fault_hook=fault)
        self.gate = build(self.root, lambda: self.now); self.deliver()
        self.assertEqual(self.state()['dispositions'][cid], 'identity_outcome_unknown_no_retry')
        self.assertEqual(self.state()['quote_permits'], 1); self.assertFalse(self.calls)

    def test_response_without_durable_decision_remains_unknown_without_retry(self):
        self.queue()
        def fault(stage):
            if stage == 'after_identity_response': raise RuntimeError('synthetic response gap')
        with self.assertRaises(RuntimeError): self.deliver(fault_hook=fault)
        self.gate = build(self.root, lambda: self.now); self.deliver()
        self.assertEqual(len(self.calls), 1); self.assertFalse(self.gate.requests.events())

    def test_request_commit_before_outbox_ack_retries_without_api_or_duplicate(self):
        self.queue()
        def fault(_): raise RuntimeError('synthetic commit gap')
        with self.assertRaises(RuntimeError): self.deliver(after_submit=fault)
        self.gate = build(self.root, lambda: self.now); (result,) = self.deliver()
        self.assertFalse(result.inserted); self.assertEqual(len(self.calls), 1)
        self.assertEqual(len(self.gate.requests.events()), 1)

    def test_normal_restriction_is_not_overridden_by_identity_confirmation(self):
        self.gate.requests.restrict_symbol('cap', symbol='NVDA', max_group='uni', actor_id='admin')
        self.queue(); self.deliver()
        self.assertFalse(self.gate.requests.states()[-1].applied.hot)
        self.assertEqual(self.state()['selected_symbol'], 'NVDA')

    def test_restricted_membership_does_not_substitute_a_different_symbol(self):
        self.gate.requests.restrict_symbol('cap', symbol='NVDA', max_group='uni', actor_id='admin')
        self.queue(); self.deliver(); self.queue([self.row('AMD')]); self.deliver()
        self.assertEqual(self.state()['selected_symbol'], 'NVDA'); self.assertEqual(len(self.calls), 1)

    def test_deadline_stop_and_provider_stop_block_further_lookup(self):
        self.queue(); self.now = AT+timedelta(seconds=720); self.deliver()
        self.assertFalse(self.calls); self.assertEqual(set(self.state()['dispositions'].values()), {'window_ended'})

    def test_stop_after_reservation_never_dispatches(self):
        self.queue(); stopped = [False]; self.gate.stop_requested = lambda: stopped[0]
        def fault(stage):
            if stage == 'after_identity_reservation': stopped[0] = True
        self.deliver(fault_hook=fault)
        self.assertFalse(self.calls); self.assertEqual(self.state()['quote_permits'], 1)

    def test_http_401_403_429_are_durable_terminal_provider_stops(self):
        for status in (401, 403, 429):
            with self.subTest(status=status):
                with tempfile.TemporaryDirectory() as tmp:
                    gate = build(Path(tmp), lambda: AT, create=True)
                    row = self.row(); cap = HaltSnapshot('stop', AT, 'HISTORICAL', digest([row]), (row,), {})
                    gate.recovery.record(gate.recovery.settings.queries[0], cap); gate.reconcile()
                    client = SimpleNamespace(quotes=lambda *a, **kw: Response('NVDA', status=status))
                    with self.assertRaises(IdentityStopRequired): gate.deliver_pending(client=client)
                    self.assertTrue(gate.snapshot()['identity_gate']['provider_stop_required'])

    def test_provider_response_after_window_does_not_publish_hot(self):
        self.queue()
        client = SimpleNamespace(quotes=lambda *a, **kw: (setattr(self, 'now', AT+timedelta(seconds=720)) or Response('NVDA')))
        self.gate.deliver_pending(client=client)
        self.assertFalse(self.gate.requests.events()); self.assertEqual(self.state()['quote_permits'], 1)

    def test_missing_gate_or_changed_catalog_blocks_before_api(self):
        self.queue(); (self.root/'catalog/nasdaq.txt').write_bytes(b'changed')
        with self.assertRaises(ValueError): self.deliver()
        self.assertFalse(self.calls)

    def test_missing_ledger_cannot_be_recreated_with_original_commands(self):
        self.queue(); self.gate.gate_path.unlink()
        with self.assertRaises(FileNotFoundError): self.gate.initialize()
        with self.assertRaises(ValueError): self.gate.initialize(create=True)
        self.assertFalse(self.calls)

    def test_changed_outcome_is_detected_even_with_a_recomputed_hash(self):
        self.queue(); self.response = Response('NVDA', body={}); self.deliver()
        with closing(sqlite3.connect(self.gate.gate_path)) as c, c:
            n, raw = c.execute('SELECT * FROM identity_event ORDER BY sequence DESC LIMIT 1').fetchone()
            e = json.loads(raw); e['code'] = 'approved'; e.pop('event_sha256'); e['event_sha256'] = digest(e)
            c.execute('UPDATE identity_event SET payload=? WHERE sequence=?', (canonical(e), n))
        with self.assertRaisesRegex(ValueError, 'disposition'): self.gate.snapshot()

    def test_direct_shared_delivery_bypass_is_detected(self):
        self.queue(); self.gate.delivery.deliver_pending()
        with self.assertRaisesRegex(ValueError, 'bypassed'): self.gate.snapshot()
        self.assertFalse(self.calls)

    def test_second_owner_cannot_dispatch_during_an_active_identity_operation(self):
        self.queue()
        with owner_lock(self.gate.gate_path.with_suffix('.identity-owner.lock')):
            with self.assertRaises(ServiceBusy): self.deliver()
        self.assertFalse(self.calls)

    def test_already_approved_but_not_submitted_command_cannot_start_after_deadline(self):
        (cid,) = self.queue(); self.assertEqual(self.gate.authorize(cid, self.client), 'approved')
        self.now = AT+timedelta(seconds=720)
        with self.assertRaises(IdentityStopRequired): self.deliver()
        self.assertFalse(self.gate.requests.events()); self.assertEqual(len(self.calls), 1)

    def test_changed_window_blocks_before_additional_api(self):
        self.queue(); self.gate.stop += timedelta(seconds=1)
        with self.assertRaisesRegex(ValueError, 'dependencies'): self.deliver()
        self.assertFalse(self.calls)

    def test_overlong_identity_response_is_retained_without_approval(self):
        self.queue(); values = iter([0.0, 3.001]); self.gate.monotonic = lambda: next(values)
        self.deliver(); self.assertFalse(self.gate.requests.events())
        self.assertEqual(set(self.state()['dispositions'].values()), {'identity_timeout'})

    def test_unserializable_or_nonfinite_response_is_not_identity_evidence(self):
        self.queue(); self.response = Response('NVDA', body={'NVDA': float('nan')})
        self.deliver(); self.assertFalse(self.gate.requests.events())

    def test_authorization_callback_failure_requires_durable_stop(self):
        self.queue(); self.response = StartupError('authorization_required')
        with self.assertRaises(IdentityStopRequired): self.deliver()
        self.assertTrue(self.state()['provider_stop_required']); self.assertEqual(len(self.calls), 1)

    def test_oversized_response_consumes_permit_without_identity_approval(self):
        self.queue(); self.response = Response('NVDA', body={'padding': 'x'*1_000_001})
        self.deliver(); self.assertFalse(self.gate.requests.events())
        self.assertEqual(self.state()['quote_permits'], 1)

    def test_live_and_recovered_same_event_share_gate_and_normal_request(self):
        self.gate.live.record_snapshot(HaltSnapshot('baseline', self.now, 'CURRENT', digest([]), (), {}))
        self.now += timedelta(seconds=2)
        row = self.row(); row['halt_time'] = (self.now-timedelta(seconds=1)).strftime('%H:%M:%S.%f')
        self.gate.live.record_snapshot(HaltSnapshot('live', self.now, 'CURRENT', digest([row]), (row,), {}))
        self.gate.reconcile(); self.deliver(); self.queue([row]); self.deliver()
        self.assertEqual(len(self.calls), 1); self.assertEqual(len(self.gate.requests.events()), 1)


class NativeIdentityPublicationTests(unittest.TestCase):
    setUp = IdentityTests.setUp
    row = IdentityTests.row
    queue = IdentityTests.queue
    state = IdentityTests.state
    deliver = IdentityTests.deliver

    def native(self):
        from mb_market_data.quote_observation_store import QuoteObservationStore
        from mb_market_data.sampling_membership import SamplingHierarchyRevision
        from mb_market_data.sampling_acquisition import MARKER
        from mb_watchlist_coordinator.sampling_journal import SamplingJournal
        from mb_watchlist_coordinator.sampling_service import SamplingPublicationService, PublicationSettings
        store = QuoteObservationStore(self.root/'quotes.sqlite3', session_date=AT.date(), schema_version=2)
        store.initialize()
        store.record_membership_revision(SamplingHierarchyRevision(session_date=AT.date(), revision=0,
            effective_at=AT, uni_symbols=('IBM', 'MSFT'), focus_symbols=('MSFT',), hot_symbols=(),
            source='synthetic-identity-integration', metadata={MARKER: True, 'experimental': True}))
        service = SamplingPublicationService(self.root/'publication.sqlite3', request_store=self.gate.requests,
            journal=SamplingJournal(store), settings=PublicationSettings('identity-proof', 1, .5,
                AT+timedelta(seconds=720)), clock=lambda: self.now)
        service.initialize()
        return store, service

    def test_recovered_identity_to_native_publication_hot_acquisition_audit_replays(self):
        from mb_market_data.quote_journal_audit import audit_quote_journal
        from mb_market_data.quote_journal_replay import QuoteJournalReplayReader
        from mb_watchlist_coordinator.hot_recovery_collector import HotCollectorSettings, HotRecoveryCollector
        from unittest.mock import patch
        from datetime import timezone
        store, service = self.native()
        self.queue([self.row(resumption_trade_time='09:59:00')]); self.deliver(); service.cycle()
        self.now += timedelta(seconds=1); service.cycle()
        settings = HotCollectorSettings(str(store.database_path), plain(service.identity), utc_text(AT),
            utc_text(AT+timedelta(seconds=720)), max_quote_calls=60, max_symbols=1)
        collector = HotRecoveryCollector(settings, client_factory=lambda: self.client, clock=lambda: self.now)
        collector.prepare(create=True); self.addCleanup(collector.close)
        self.now = AT+timedelta(seconds=2); case = self
        class Clock(datetime):
            @classmethod
            def now(cls, tz=None): return case.now.astimezone(tz or timezone.utc)
        with patch('mb_market_data.schwab_quotes.datetime', Clock):
            self.assertEqual(collector.tick()['status'], 'acquired')
        self.assertEqual(len(self.calls), 2)  # One identity + one actual native synthetic quote.
        self.assertEqual(store.membership_revisions_in_effective_order()[-1].hot_symbols, ('NVDA',))
        self.assertTrue(audit_quote_journal(store.database_path, audited_at=self.now).passed)
        def replay(): return [(e.event_id, repr(e)) for e in QuoteJournalReplayReader(store.database_path).events()]
        self.assertEqual(replay(), replay())

    def test_multiple_captured_symbols_publish_only_one_selected_hot_member(self):
        store, service = self.native()
        self.queue([self.row('NVDA'), self.row('MSFT')]); self.deliver(); service.cycle()
        self.now += timedelta(seconds=1); service.cycle()
        self.assertEqual(len(store.membership_revisions_in_effective_order()[-1].hot_symbols), 1)
        self.assertEqual(len(self.gate.recovery.snapshot()['candidates']), 2)


class IdentityProcessTests(unittest.TestCase):
    setUp = IdentityTests.setUp
    row = IdentityTests.row
    queue = IdentityTests.queue
    state = IdentityTests.state
    deliver = IdentityTests.deliver

    def crash(self, stage):
        self.queue()
        child = subprocess.Popen([sys.executable, '-I', '-B', str(Path(__file__).parent/'fixtures/identity_gate_worker.py')],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        try:
            _, error = child.communicate(json.dumps({'root': str(self.root), 'stage': stage}).encode(), timeout=10)
            self.assertEqual(child.returncode, 75, error.decode(errors='replace'))
        finally:
            if child.poll() is None: child.kill(); child.wait(timeout=2)
            if child.stdin: child.stdin.close()
            if child.stderr: child.stderr.close()
        self.gate = build(self.root, lambda: self.now)

    def test_process_exit_after_permit_reservation_retains_unknown_without_quote(self):
        self.crash('after_identity_reservation'); self.deliver()
        self.assertEqual(self.state()['quote_permits'], 1); self.assertFalse(self.calls)
        self.assertFalse((self.root/'synthetic_quote_calls.txt').exists())

    def test_process_exit_after_provider_return_does_not_repeat_unknown_quote(self):
        self.crash('after_identity_response'); self.deliver()
        self.assertEqual((self.root/'synthetic_quote_calls.txt').read_text().splitlines(), ['NVDA'])
        self.assertFalse(self.calls); self.assertFalse(self.gate.requests.events())

    def test_process_exit_after_request_commit_retries_ack_without_lookup(self):
        self.crash('after_request_commit'); self.deliver()
        self.assertEqual((self.root/'synthetic_quote_calls.txt').read_text().splitlines(), ['NVDA'])
        self.assertFalse(self.calls); self.assertEqual(len(self.gate.requests.events()), 1)

