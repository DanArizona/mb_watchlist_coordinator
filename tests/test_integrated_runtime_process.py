from contextlib import closing
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from runtime_fixtures import RuntimeFixture, SECRET
from runtime_process_evidence import subsequent_halt_snapshot
from test_nasdaq_feed_recovery import EMPTY
from mb_market_data.quote_journal_audit import audit_quote_journal
from mb_market_data.quote_journal_replay import QuoteJournalReplayReader
from mb_watchlist_coordinator.integrated_runtime import IntegratedRuntime
from mb_watchlist_coordinator.nasdaq_feed_recovery import BoundedFeedClient
from mb_watchlist_coordinator.sampling_requests import timestamp, utc_text
from mb_watchlist_coordinator.supervised_hot_worker import progress_receipt

PROBE = Path(__file__).parent/'fixtures/supervised_hot_worker_probe.py'


class RuntimeProcessTests(unittest.TestCase):
    def setUp(self):
        self.phase = 'setup'
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.f = RuntimeFixture(tmp.name); self.addCleanup(self.f.session.close)
        self.feed = BoundedFeedClient(self.f.session.feed)
        self.scenario = {'chunks': [EMPTY.decode()]}
        self.simulation = self.f.root/'simulation.json'
        self.log = self.f.root/'worker-events.jsonl'
        original_popen = subprocess.Popen
        def owned_child(args, **kwargs):
            if len(args) > 3 and Path(str(args[3])).name == 'nasdaq_feed_worker.py':
                args = [*args[:3], str(Path(__file__).parent/'fixtures/runtime_feed_worker.py'), str(self.simulation)]
            return original_popen(args, **kwargs)
        patched = patch('subprocess.Popen', new=owned_child)
        patched.start(); self.addCleanup(patched.stop)
        self.r = IntegratedRuntime(self.f.session, feed_client=self.feed,
            worker_command=(sys.executable, '-I', '-B', str(PROBE),
                str(self.f.target/'authenticated-worker.json'), str(self.simulation)))
        self.r.initialize(); self.addCleanup(self.r.close)
        original_cycle = self.r.authority.cycle
        self.authority_observation = {}
        def observed_cycle(**kwargs):
            report = original_cycle(**kwargs)
            self.authority_observation = report
            return report
        self.r.authority.cycle = observed_cycle

    def step(self):
        return self.r.step(synthetic=self.scenario)

    def begin(self, mode='normal', crash_stage=None):
        self.f.realtime()
        self.simulation.write_text(json.dumps({'mode': mode, 'log': str(self.log),
            'real_anchor_utc': self.f.real.isoformat(), 'logical_anchor_utc': self.f.logical.isoformat(),
            'crash_stage': crash_stage}))
        self.step()
        return self.r.managed.child

    def wait(self, predicate, seconds=8, pump=True, phase='wait'):
        self.phase = phase
        until = time.monotonic()+seconds
        while time.monotonic() < until:
            if pump and not self.r.closed:
                self.step()
            result = predicate()
            if result:
                return result
            if pump and self.r.closed:
                self.fail('Owned synthetic runtime stopped before phase '+phase)
            time.sleep(.03)
        self.fail('Owned synthetic runtime did not reach phase '+phase+' within its original bounded wait')

    def ready(self):
        return self.wait(lambda: self.r.last_report if self.r.last_report
            and self.r.last_report.get('worker', {}).get('status') == 'RUNNING' else None,
            phase='worker_first_completed_work')

    def events(self):
        return [json.loads(s) for s in self.log.read_text().splitlines()] if self.log.exists() else []

    def runs(self):
        with closing(sqlite3.connect(self.f.session.store.database_path)) as c:
            return c.execute('SELECT count(*) FROM poll_run').fetchone()[0]

    def emit_halt(self):
        # The transport baseline is already saved by the controller. This
        # external-observation source fixture provides a genuinely subsequent
        # synthetic update without compressing the accepted 60s HTTP cadence.
        receipts = self.wait(lambda: self.f.session.live.snapshot()['receipts'], phase='startup_baseline')
        baseline = receipts[0]['snapshot']
        self.wait(lambda: self.f.clock() > timestamp(baseline['retrieved_at_utc']), phase='later_observation_clock')
        snapshot = subsequent_halt_snapshot(baseline, observed_at=self.f.clock(),
            capture_id='synthetic-runtime-'+str(len(receipts)))
        self.f.session.live.record_snapshot(snapshot)
        self.phase = 'source_request_queued'
        outcome = self.f.session.live.snapshot()['outcomes'][-1]
        self.assertEqual([e['status'] for e in outcome['events']], ['request_queued'])

    def native_count(self):
        return len(self.f.session.store.acquisitions_in_replay_order())

    def no_secrets(self):
        for p in self.f.root.rglob('*'):
            if p.is_file():
                data = p.read_bytes()
                self.assertNotIn(SECRET.encode(), data, str(p))
                self.assertNotIn(b'SYNTHETIC-CODE-CANARY-44', data, str(p))

    def test_real_owned_worker_reaches_authenticated_completed_work_under_original_gates(self):
        child = self.begin(); result = self.ready()
        first = result['worker']['first_completed_work']
        self.assertEqual(first['pid'], child.pid)
        self.assertLess((timestamp(first['observed_at_utc'])-timestamp(self.r.managed._job()['started_at_utc'])).total_seconds(), 3)
        self.assertEqual(self.r.managed.identity['startup_seconds'], 3)
        self.assertEqual(self.r.managed.identity['stale_seconds'], 3)
        self.assertEqual(self.r.managed._job()['identity']['startup_context'], self.f.session.password.identity)
        self.assertEqual(self.f.events, ['parent_constructed'])
        self.assertEqual(self.r.managed._job()['generation'], 1)
        self.assertEqual(self.native_count(), 0)
        self.r.close(); self.assertEqual(child.poll(), 0); self.no_secrets()

    def test_source_identity_request_publication_and_actual_native_hot_quote_share_one_session(self):
        self.begin(); self.ready(); self.emit_halt()
        self.wait(lambda: self.native_count() >= 1, phase='first_native_acquisition')
        stop = self.r.close(); self.assertTrue(stop['counts_verified'])
        self.assertEqual(stop['selected_symbol'], 'NVDA'); self.assertEqual(stop['identity_quote_permits'], 1)
        self.assertEqual(stop['hot_quote_permits'], self.native_count())
        self.assertEqual(self.f.events.count('parent_constructed'), 1)
        self.assertEqual(len([e for e in self.f.events if isinstance(e, tuple)]), 1)
        quotes = [e for e in self.events() if e['event'] == 'quote']
        self.assertEqual(len(quotes), self.native_count())
        self.assertTrue(all(e['symbols'] == ['NVDA'] for e in quotes))
        audit = audit_quote_journal(self.f.session.store.database_path,
            audited_at=timestamp(stop['acquisition_stop_requested_at_utc']))
        self.assertTrue(audit.passed)
        def replay(): return [(e.event_id, repr(e)) for e in QuoteJournalReplayReader(self.f.session.store.database_path).events()]
        self.assertEqual(replay(), replay()); self.no_secrets()

    def test_credential_success_without_native_work_does_not_satisfy_three_second_gate(self):
        child = self.begin('hang_after_auth')
        self.assertEqual(child.wait(timeout=5), 124)  # no parent health checks
        job = self.r.managed._job()
        self.assertEqual(json.loads((self.r.managed.root/(job['token']+'.auth.json')).read_text())['status'], 'credentials_accepted')
        self.assertEqual(progress_receipt(job)['status'], 'worker_startup_deadline_ended')
        self.assertEqual(self.step()['reason'], 'worker_startup_deadline_ended')
        self.assertEqual(self.runs(), 1); self.assertFalse(self.native_count()); self.no_secrets()

    def test_three_second_gate_wins_over_eight_second_credential_budget_independently(self):
        began = time.monotonic(); child = self.begin('slow_credential')
        self.assertEqual(child.wait(timeout=5), 124)
        self.assertLess(time.monotonic()-began, 4.5)
        self.assertEqual(self.step()['reason'], 'worker_startup_deadline_ended')
        self.assertEqual(self.runs(), 1); self.assertFalse(self.native_count()); self.no_secrets()

    def test_two_second_credential_start_can_reach_completed_work_before_original_cutoff(self):
        self.begin('two_second_credential'); result = self.ready()
        first = result['worker']['first_completed_work']; job = self.r.managed._job()
        elapsed = (timestamp(first['observed_at_utc'])-timestamp(job['started_at_utc'])).total_seconds()
        self.assertGreaterEqual(elapsed, 2); self.assertLess(elapsed, 3)
        self.assertFalse(self.native_count())

    def test_late_entry_cannot_restart_the_startup_clock_or_read_credentials(self):
        child = self.begin('late_entry'); self.assertEqual(child.wait(timeout=5), 70)
        self.assertFalse(self.events()); self.assertEqual(self.runs(), 1)
        self.assertEqual(self.step()['reason'], 'worker_startup_deadline_ended')

    def test_worker_authorization_refusal_is_terminal_without_automatic_reauthentication(self):
        child = self.begin('authorization'); self.assertEqual(child.wait(timeout=4), 70)
        self.step(); self.assertTrue(self.r.closed)
        self.assertEqual(self.r.last_report['reason'], 'worker_credentials_rejected')
        self.assertEqual(self.r.managed._job()['generation'], 1)
        self.assertEqual(self.runs(), 1); self.no_secrets()

    def test_changed_refresh_horizon_prevents_worker_native_run_registration(self):
        child = self.begin('changed_horizon'); self.assertEqual(child.wait(timeout=4), 70)
        self.step(); self.assertTrue(self.r.closed)
        self.assertEqual(self.runs(), 1); self.assertFalse(self.native_count()); self.no_secrets()

    def test_rate_limited_hot_response_is_charged_once_and_not_restarted(self):
        self.begin('rate_limit'); self.ready(); self.emit_halt()
        self.wait(lambda: self.r.closed)
        self.assertEqual(self.r.last_report['reason'], 'native_blocked')
        self.assertEqual(self.r.last_report['hot_quote_permits'], 1)
        self.assertEqual(len([e for e in self.events() if e['event'] == 'quote']), 1)
        self.assertEqual(self.r.managed._job()['generation'], 1); self.no_secrets()

    def test_owned_child_fault_restarts_future_slots_with_original_symbol_window_and_budgets(self):
        self.begin(); self.ready(); self.emit_halt()
        self.wait(lambda: self.native_count() >= 1, phase='first_native_acquisition')
        first = self.r.managed._job(); child = self.r.managed.child
        self.wait(lambda: (self.f.clock()-timestamp(first['started_at_utc'])).total_seconds() >= 3.1,
            phase='pre_fault_startup_age')
        child.terminate(); child.wait(timeout=2)
        after_fault = self.f.clock()
        self.wait(lambda: self.r.managed._job()['generation'] == 2, phase='replacement_generation')
        second = self.r.managed._job()
        self.assertEqual(first['identity'], second['identity']); self.assertNotEqual(first['token'], second['token'])
        self.assertGreater(timestamp(second['first_eligible_slot_utc']), after_fault)
        self.wait(lambda: self.native_count() >= 2, phase='post_fault_native_acquisition')
        stop = self.r.close()
        self.assertEqual(stop['identity_quote_permits'], 1); self.assertEqual(stop['selected_symbol'], 'NVDA')
        self.assertLessEqual(stop['hot_quote_permits'], 60)
        self.assertEqual(self.r.identity['stop_at_utc'], utc_text(self.f.stop))
        self.no_secrets()

    def test_closed_manual_secret_blocks_generation_without_resetting_public_configuration(self):
        self.f.session.password.close(); self.begin()
        self.assertIsNone(self.r.managed.child)
        self.assertTrue(self.r.closed)
        self.assertFalse(self.r.managed.registry.exists()); self.assertEqual(self.runs(), 1)

    def test_changed_completed_work_receipt_is_blocked_before_more_provider_activity(self):
        self.begin(); self.ready(); job = self.r.managed._job()
        p = self.r.managed.root/(job['token']+'.startup.json')
        value = json.loads(p.read_text()); value['pid'] += 100; p.write_text(json.dumps(value))
        self.step(); self.assertTrue(self.r.closed); self.assertFalse(self.native_count())

    def test_explicit_stop_preserves_request_demand_and_closes_only_owned_worker(self):
        child = self.begin(); self.ready()
        before = self.f.session.requests.events()
        result = self.r.close()
        self.assertIsNotNone(child.poll()); self.assertEqual(result['cleanup_findings'], [])
        self.assertEqual(self.f.session.requests.events(), before)
        self.assertTrue(self.f.session.closed); self.no_secrets()

    def test_blocked_http_child_does_not_block_worker_startup_and_exact_owned_stop_closes_both(self):
        self.scenario = {'hang_before_headers': True}
        hot = self.begin(); self.ready()
        feed_child = self.feed._active[0]
        self.assertIsNone(hot.poll()); self.assertIsNone(feed_child.poll())
        self.assertFalse(self.native_count())
        result = self.r.close()
        self.assertIsNotNone(hot.poll()); self.assertIsNotNone(feed_child.poll())
        self.assertFalse(self.f.session.feed.snapshot()['pending'])
        self.assertEqual(len(self.f.session.feed.snapshot()['attempts']), 1)
        self.assertEqual(result['cleanup_findings'], [])
