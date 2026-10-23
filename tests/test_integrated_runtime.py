from contextlib import closing
from datetime import timedelta
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from runtime_fixtures import RuntimeFixture, ScriptedFeed, SECRET, Response
from test_nasdaq_feed_recovery import EMPTY, HTML, rss
from mb_watchlist_coordinator.integrated_runtime import IntegratedRuntime
from mb_watchlist_coordinator.sampling_requests import digest, plain


class IntegratedRuntimeTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.f = RuntimeFixture(tmp.name); self.addCleanup(self.f.session.close)
        self.feed = ScriptedFeed(self.f.session.feed)
        self.r = IntegratedRuntime(self.f.session, feed_client=self.feed,
            worker_command=('synthetic-no-worker-execution',))
        self.r.initialize(); self.addCleanup(self.r.close)
        self.starts = []
        def ensure(**kw):
            self.starts.append(kw)
            return {'status': 'RUNNING', 'synthetic_worker': True}
        self.r.worker.ensure = ensure

    def activate(self):
        self.f.now = self.f.start
        return self.r.step()

    def recovered(self, *, response=None):
        self.activate()
        self.f.now += timedelta(seconds=60)
        self.feed.responses.append(response or rss(self.f.start.date(), 'NVDA',
            (self.f.start-timedelta(minutes=5)).astimezone(__import__('zoneinfo').ZoneInfo('America/New_York')).strftime('%H:%M:%S')))
        report = self.r.step()
        self.f.now += timedelta(seconds=1)
        return self.r.step()

    def test_no_new_authentication_or_network_before_original_T0(self):
        result = self.r.step()
        self.assertEqual(result['status'], 'WAITING')
        self.assertEqual(self.f.events, ['parent_constructed'])
        self.assertFalse(self.f.session.feed.snapshot()['attempts']); self.assertFalse(self.starts)

    def test_explicit_prepared_client_delivers_recovered_outside_uni_and_native_publication(self):
        self.recovered()
        gate = self.f.session.gated_delivery.snapshot()['identity_gate']
        self.assertEqual(gate['selected_symbol'], 'NVDA'); self.assertEqual(gate['quote_permits'], 1)
        self.assertEqual([x for x in self.f.events if isinstance(x, tuple)], [('identity_quote', ['NVDA'], 'all')])
        self.assertEqual(self.f.events.count('parent_constructed'), 1)
        self.assertEqual(self.f.session.store.membership_revisions_in_effective_order()[-1].hot_symbols, ('NVDA',))
        self.assertTrue(self.starts[-1]['start_allowed'])

    def test_current_dated_current_cutover_retains_scope_and_full_updates(self):
        self.recovered()
        self.f.now = self.f.start+timedelta(seconds=120)
        self.feed.responses.append(EMPTY)
        result = self.r.step()
        self.assertTrue(result['discovery_scope_reconciled'])
        self.assertIn('older_unknown_carryovers_not_proven_complete', result['reasons'])
        self.assertEqual(len(self.f.session.feed.snapshot()['attempts']), 3)

    def test_feed_gap_keeps_saved_membership_and_does_not_close_healthy_worker(self):
        self.recovered(); original = self.f.session.requests.events()
        self.f.now += timedelta(seconds=60); self.feed.responses.append(HTML)
        result = self.r.step()
        self.assertEqual(result['status'], 'INCOMPLETE'); self.assertFalse(self.r.closed)
        self.assertEqual(self.f.session.requests.events(), original)
        self.assertEqual(self.f.session.requests.states()[-1].applied.hot, {'NVDA'})
        self.assertTrue(self.starts[-1]['start_allowed'])

    def test_three_feed_failures_stop_feed_without_cancelling_verified_hot_demand(self):
        self.recovered()
        for _ in range(3):
            self.f.now += timedelta(seconds=60); self.feed.responses.append(HTML); result = self.r.step()
        self.assertTrue(result['feed_stop_required']); self.assertFalse(self.r.closed)
        self.assertEqual(self.f.session.requests.states()[-1].applied.hot, {'NVDA'})

    def test_identity_authorization_failure_stops_controller_without_retries(self):
        self.f.response = Response('NVDA', status=401)
        self.recovered()
        self.assertTrue(self.r.closed)
        count = len(self.f.events); saved = self.r.stop_path.read_bytes()
        self.r.step(); self.assertEqual(len(self.f.events), count)
        self.assertEqual(self.r.stop_path.read_bytes(), saved)
        self.assertEqual(self.r.last_report['identity_quote_permits'], 1)

    def test_invalid_identity_does_not_become_membership_or_worker_authentication(self):
        self.f.response = Response('NVDA', body={'OTHER': {'assetMainType': 'EQUITY'}})
        self.recovered()
        self.assertFalse(self.f.session.requests.states()[-1].applied.hot)
        self.assertIsNone(self.f.session.gated_delivery.snapshot()['identity_gate']['selected_symbol'])
        self.assertEqual(self.f.events.count('parent_constructed'), 1)

    def test_all_stop_and_lifetime_limits_remain_original(self):
        identity = self.r.identity
        self.assertEqual([identity[k] for k in ('worker_startup_seconds','worker_stale_seconds','credential_timeout_seconds')], [3,3,8])
        self.assertEqual([identity[k] for k in ('max_worker_starts','max_hot_quote_permits','max_identity_quote_permits')], [3,60,3])
        self.activate(); self.f.now = self.f.stop
        result = self.r.step(); self.assertEqual(result['status'], 'STOPPED')
        self.assertTrue(self.feed.closed); self.assertTrue(self.f.session.closed)
        self.assertEqual(self.f.session.plan.public['stop_at_utc'], identity['stop_at_utc'])

    def test_close_does_not_backdate_cancellation_and_reports_a_stop_not_a_profile_pass(self):
        self.recovered(); events = self.f.session.requests.events()
        result = self.r.close()
        self.assertEqual(self.f.session.requests.events(), events)
        self.assertEqual(result['profile_verdict'], 'NOT_QUALIFIED_BY_RUNTIME_PUMP')
        self.assertTrue(result['counts_verified']); self.assertEqual(result['identity_quote_permits'], 1)
        self.assertFalse(result['hot_quote_permits'])

    def test_runtime_binding_change_blocks_before_feed_or_provider(self):
        self.r.binding_path.write_text('{}')
        self.f.now = self.f.start; result = self.r.step()
        self.assertEqual(result['status'], 'STOPPED'); self.assertFalse(self.feed.calls)
        self.assertEqual(self.f.events, ['parent_constructed', 'parent_closed'])

    def test_changed_catalog_blocks_before_source_delivery(self):
        path = self.f.target/'catalog/nasdaq.txt'; path.write_bytes(path.read_bytes()+b'\n')
        self.f.now = self.f.start; result = self.r.step()
        self.assertTrue(self.r.closed); self.assertFalse(result['counts_verified']); self.assertFalse(self.feed.calls)

    def test_changed_worker_configuration_blocks_before_start_or_provider(self):
        path = self.r.configuration_path; value = json.loads(path.read_text())
        value['authentication']['startup_timeout_seconds'] = 9; path.write_text(json.dumps(value))
        self.f.now = self.f.start; self.r.step()
        self.assertTrue(self.r.closed); self.assertFalse(self.starts); self.assertFalse(self.feed.calls)

    def test_missing_identity_ledger_is_not_reset(self):
        path = self.f.session.gated_delivery.gate_path; path.unlink()
        self.f.now = self.f.start; self.r.step()
        self.assertTrue(self.r.closed); self.assertFalse(path.exists()); self.assertFalse(self.feed.calls)

    def test_existing_partial_runtime_is_not_a_fresh_reopen(self):
        second = IntegratedRuntime(self.f.session, feed_client=self.feed, worker_command=self.r.command)
        before = self.r.binding_path.read_bytes()
        with self.assertRaises(ValueError): second.initialize()
        self.assertEqual(self.r.binding_path.read_bytes(), before)
        self.assertIsNone(self.r.managed.child)

    def test_public_configuration_does_not_contain_the_manual_password(self):
        self.assertNotIn(SECRET, repr(self.r.identity)); self.assertNotIn(SECRET, self.r.binding_path.read_text())
        self.r.close(reason=SECRET)
        self.assertNotIn(SECRET, self.r.stop_path.read_text())

    def test_bounded_pump_uses_a_shorter_active_limit_without_extending_frozen_window(self):
        self.f.now = self.f.start; tick = [0.0]
        self.r.monotonic = lambda: tick[0]
        def advance(seconds):
            tick[0] += seconds; self.f.now += timedelta(seconds=seconds)
        result = self.r.run(max_seconds=.2, sleep=advance)
        self.assertEqual(result['status'], 'STOPPED'); self.assertLessEqual(tick[0], .25)
        self.assertFalse(result['hot_quote_permits'])

    def test_dependency_binding_failures_are_not_generic_client_discovery(self):
        class Other: transport = None
        with self.assertRaises(ValueError): IntegratedRuntime(self.f.session, feed_client=Other(), worker_command=('synthetic',))

    def test_closed_manual_session_cannot_construct_another_runtime(self):
        self.r.close()
        with self.assertRaises(ValueError): IntegratedRuntime(self.f.session, feed_client=self.feed, worker_command=('synthetic',))

    def test_an_uninitialized_second_instance_cannot_close_the_owners_client(self):
        second = IntegratedRuntime(self.f.session, feed_client=self.feed, worker_command=self.r.command)
        self.assertEqual(second.close()['status'], 'NOT_INITIALIZED')
        self.assertFalse(self.f.session.closed); self.assertFalse(self.feed.closed)
        self.assertEqual(self.r.step()['status'], 'WAITING')

    def test_lifetime_controller_lease_is_distinct_from_the_authority_cycle_lease(self):
        self.activate()
        self.assertNotEqual(self.f.target/'controller.owner.lock', self.r.authority.path.with_suffix('.owner.lock'))
        self.assertFalse(self.r.closed)

    def test_replacing_the_prepared_client_is_detected_before_identity_calls(self):
        original = self.f.session.client
        self.f.session.client = object()
        try:
            with self.assertRaises(ValueError): self.r.validate()
        finally: self.f.session.client = original

    def test_replacing_the_bound_feed_transport_is_detected_before_source_calls(self):
        original = self.feed.transport
        self.feed.transport = None
        try:
            with self.assertRaises(ValueError): self.r.validate()
        finally: self.feed.transport = original

    def test_binding_failure_closes_the_original_client_without_calling_a_replacement(self):
        class Unrelated:
            def close(self): raise AssertionError('An unrelated client must not be called')
        self.f.session.client = Unrelated()
        self.f.now = self.f.start; self.r.step()
        self.assertTrue(self.r.closed)
        self.assertEqual(self.f.events, ['parent_constructed', 'parent_closed'])
