"""Actual owned authenticated processes against synthetic daily-layout journals."""
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
import unittest
import os
from unittest.mock import patch
from contextlib import closing

from mb_watchlist_coordinator.authenticated_startup import AuthStartupSettings, SessionPassword
from mb_watchlist_coordinator.daily_collector import DailyCollectorSettings
from mb_watchlist_coordinator.daily_controller import DailyController
from mb_watchlist_coordinator.daily_session import DailySession
from mb_watchlist_coordinator.daily_supervision import DailyWorkerConfiguration, read_json, unseal
from mb_watchlist_coordinator.daily_worker_view import DailyPublicationReader
from mb_watchlist_coordinator.sampling_requests import digest, plain
from mb_watchlist_coordinator.sampling_service import ServiceBusy
import test_daily_session as daily


class DailyControllerTests(unittest.TestCase):
    def setUp(self):
        self.fixture = daily.DailySessionTests('test_preview_reads_published_anchor_and_creates_no_application_state_or_client')
        self.fixture.proof_directory_override=getattr(self,'proof_directory_override',None)
        if self._testMethodName == 'test_actual_source_identity_and_native_collection_with_owned_controller':
            self.fixture.proof_directory_override = os.environ.get('MB_DAILY_CONTROLLER_PROOF_DIR')
        elif self._testMethodName == 'test_lost_owned_worker_recovers_response_after_full_fifteen_second_hold':
            self.fixture.proof_directory_override = os.environ.get('MB_DAILY_CONTROLLER_RECOVERY_PROOF_DIR')
        self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        self.case, self.real = self.fixture, datetime.now(timezone.utc)
        self.logical = self.case.at
        self.clock = lambda: self.logical+(datetime.now(timezone.utc)-self.real)
        self.case.session = DailySession(self.case.settings, self.case.catalog, clock=self.clock)
        self.case.session.attach(create=True, publication_approved=True)
        session = self.case.session
        self.config = DailyWorkerConfiguration(session.settings, str(self.case.root/'catalog'),
            DailyCollectorSettings(str(self.case.journal), plain(session.service.identity),
                plain(session.binding), plain(session.claim), (self.logical+timedelta(seconds=6)).isoformat(),
                (self.logical+timedelta(minutes=5)).isoformat(), 100, 1),
            AuthStartupSettings(str(self.case.root/'unused.ecfg'), (self.logical+timedelta(minutes=5)).isoformat()))
        import mb_market_data
        self.scenario = {'real_anchor': self.real.isoformat(), 'logical_anchor': self.logical.isoformat(),
            'native_src': str(Path(mb_market_data.__file__).resolve().parents[1]),
            'log': str(self.case.root/'process-events.jsonl')}
        self.scenario_path = self.case.root/'scenario.json'
        entry = str(Path(__file__).parent/'fixtures/daily_authenticated_process.py')
        self.commands = {role: (sys.executable, '-I', '-B', entry, str(self.scenario_path), role,
            str(Path(session.settings.state_root)/'daily-worker.json')) for role in ('collector', 'identity', 'report')}
        self.controller = None
        self.addCleanup(self.close)

    def close(self):
        if self.controller is not None: self.controller.close(report=False)

    def make(self, *, mode='normal', target='collector'):
        self.scenario.update(mode=mode, target_role=target)
        self.scenario_path.write_text(json.dumps(self.scenario))
        secret = SessionPassword('SYNTHETIC-PRIVATE-CANARY-62', digest(self.config.payload()))
        return DailyController(self.case.session, self.config, commands=self.commands,
            password=secret, clock=self.clock, activation_approved=True)

    def start(self, **kwargs):
        self.controller = self.make(**kwargs)
        return self.controller.initialize(create=True)

    def wait(self, predicate, seconds=6):
        deadline = time.monotonic()+seconds
        while time.monotonic() < deadline:
            if predicate(): return
            time.sleep(.025)
        details = {'status': self.controller.status(), 'events': self.events(),
            'worker_exit': self.controller.worker.last_exit}
        self.fail('Expected daily controller condition was not observed: '+json.dumps(details, default=str))

    def running(self):
        return self.controller.status()['state'] in ('RUNNING', 'RUNNING_WITH_SOURCE_GAPS')

    def events(self):
        path = self.case.root/'process-events.jsonl'
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def test_reader_validates_while_the_original_publication_owner_stays_attached(self):
        before = len(self.case.session.requests.events())
        reader = DailyPublicationReader(self.case.settings, self.config.catalog_path,
            binding=self.config.collector.daily_binding, claim=self.config.collector.daily_claim,
            publication_binding=self.config.collector.publication_binding, clock=self.clock, fence=lambda: None)
        self.assertTrue(reader.validate())
        self.assertTrue(self.case.session.validate())
        self.assertEqual(len(self.case.session.requests.events()), before)

    def test_two_authenticated_owned_roles_start_without_a_provider_quote(self):
        self.start(); self.wait(self.running)
        self.assertEqual(self.controller.state.read()['starts'][0]['generation'], 1)
        self.assertEqual(sum(e['event'].startswith('quote:') for e in self.events()), 0)
        self.assertTrue(self.case.session.validate())
        job = self.controller.worker._job()
        self.assertTrue(Path(job['heartbeat_path']).exists())
        self.assertTrue(Path(job['job_path']).with_name(job['token']+'.startup.json').exists())

    def test_transient_health_probe_on_role_lease_does_not_abort_worker_startup(self):
        from mb_watchlist_coordinator.sampling_service import owner_lock
        ready, go = self.case.root/'role-probe-ready', self.case.root/'role-probe-go'
        self.scenario['role_lease_probe'] = {'ready': str(ready), 'go': str(go)}
        self.start()
        self.wait(ready.exists, seconds=2)
        job = self.controller.worker._job()
        # The monitor's health check also briefly takes this same real OS lock.
        # Force the new child to attempt entry while such a probe owns it.
        with owner_lock(Path(job['lease_path'])):
            go.write_text('probe-held')
            deadline = time.monotonic()+.15
            while time.monotonic() < deadline:
                if any(e['event'] == 'role_lease_probe_busy' for e in self.events()): break
                time.sleep(.002)
            self.assertTrue(any(e['event'] == 'role_lease_probe_busy' for e in self.events()))
        self.wait(self.running)
        self.assertEqual(len(self.controller.state.read()['starts']), 1)
        self.assertFalse(self.provider_calls())
        self.assertFalse(self.controller.state.read()['terminal'])

    def test_saved_status_exposes_source_gaps_without_claiming_feed_readiness(self):
        self.start(); self.wait(self.running)
        status = self.controller.status()
        self.assertEqual(status['state'], 'RUNNING_WITH_SOURCE_GAPS')
        self.assertFalse(status['source_reconciled'])
        incidents = unseal(read_json(self.controller.root/'hot-incidents.json'))['incidents']
        self.assertEqual(incidents['source:gap']['severity'], 'warning')
        self.assertIn('not a worker heartbeat', (self.controller.root/'HOT_STATUS.txt').read_text())

    def test_stop_cleans_only_owned_children_and_preserves_membership_and_uni_focus_runs(self):
        self.start(); self.wait(self.running)
        before = self.case.store.membership_revisions_in_effective_order()
        child, identity = self.controller.worker.child, self.controller.identity_client.child
        stopped = self.controller.close(report=False)
        self.assertIsNotNone(child.poll()); self.assertIsNotNone(identity.poll())
        self.assertTrue(stopped['cleanup_within_10_seconds'])
        self.assertEqual(self.case.store.membership_revisions_in_effective_order(), before)
        with closing(sqlite3.connect(self.case.journal)) as c:
            self.assertEqual(c.execute('SELECT count(*) FROM poll_run WHERE run_id IN (?,?)',
                ('existing-uni', 'existing-focus')).fetchone()[0], 2)

    def test_sdk_noise_and_secret_never_enter_saved_runtime_evidence(self):
        self.start(); self.wait(self.running); self.controller.close(report=False)
        for path in self.controller.root.rglob('*'):
            if path.is_file():
                content = path.read_bytes()
                for canary in (b'SYNTHETIC-PRIVATE-CANARY-62', b'SYNTHETIC-CODE-CANARY-62'):
                    self.assertNotIn(canary, content, str(path))
        self.assertFalse(self.controller.password._value)

    def source_attempt(self, raw):
        scenario = {'clock_at_utc': self.clock().isoformat(), 'chunks': [raw.decode()]}
        initial = len(self.controller.source.transport.snapshot()['attempts'])
        deadline = time.monotonic()+5
        while time.monotonic() < deadline:
            report = self.controller.step(synthetic=scenario)
            if len(self.controller.source.transport.snapshot()['attempts']) > initial:
                return report
            time.sleep(.02)
        self.fail('Synthetic source attempt did not finish')

    def provider_calls(self, role='collector'):
        return [e for e in self.events() if e['role'] == role and e['event'].startswith('quote:')]

    def test_actual_source_identity_and_native_collection_with_owned_controller(self):
        from test_nasdaq_feed_recovery import EMPTY
        self.start(); self.wait(self.running)
        self.source_attempt(EMPTY)
        # Reconcile an already saved, same-date dated capture. The existing
        # Windows-qualified feed proof covers the full paced three-HTTP sequence.
        self.case.now = self.clock()
        self.case.session.cycle(client=self.controller.identity_client,
            historical_snapshot=self.case.snapshot('HISTORICAL', [self.case.row()], 'saved-history'))
        self.assertEqual(len(self.provider_calls('identity')), 1)
        self.wait(lambda: len(self.provider_calls()) >= 2, seconds=12)
        def committed():
            with closing(sqlite3.connect(self.case.journal)) as c:
                return c.execute('SELECT count(*) FROM quote_acquisition WHERE channel="hot"').fetchone()[0] >= 2
        self.wait(committed)
        stopped = self.controller.close()
        final = unseal(read_json(Path(stopped['reporting']['report_path'])))
        self.assertTrue(final['native_audit_passed'], final['native_audit'])
        self.assertTrue(final['two_fresh_replays_equal'])
        self.assertEqual(self.case.store.membership_revisions_in_effective_order()[-1].hot_symbols, ('NVDA',))
        self.assertEqual(self.case.session.gate.snapshot()['identity_gate']['quote_permits'], 1)
        self.assertEqual(stopped['reporting']['status'], 'COMPLETE')
        if os.environ.get('MB_DAILY_CONTROLLER_PROOF_DIR'):
            from mb_watchlist_coordinator.recovery_workers import atomic_json
            proof = {'contract': 'daily-authenticated-controller-native-proof-v1', 'result': 'PASS',
                'synthetic_sdk_only': True, 'network': 'denied', 'actual_vault_access': False,
                'clock': 'shifted wall clock; actual elapsed process/authentication and pacing gates',
                'source_attempts': 1, 'saved_historical_captures': 1,
                'saved_history_submission': 'verified daily publication API; full paced transport proof is separate',
                'source_reconciled': False, 'identity_quote_permits': 1,
                'worker_starts': 1, 'hot_provider_calls': len(self.provider_calls()),
                'native_audit_passed': True, 'two_fresh_replays_equal': True,
                'first_replay': final['first_replay'], 'cleanup_within_10_seconds': stopped['cleanup_within_10_seconds'],
                'full_day_capacity_qualified': False, 'live_provider_qualification': False}
            atomic_json(self.case.root/'proof.json', proof)

    def test_lost_owned_worker_recovers_response_after_full_fifteen_second_hold(self):
        # Always exercise the platform-sensitive case: launch chooses :22,
        # while actual replacement startup completes just after that slot.
        self.scenario['replacement_cross_launch_slot'] = True
        released,observed=self.case.root/'fault-lease-released',self.case.root/'fault-lease-observed'
        self.scenario['exit_lease_gap']={'released':str(released),'observed':str(observed)}
        self.start(mode='crash_after_assembled'); self.wait(self.running)
        # Force the supervisor to see a real released OS lease while its exact
        # owned process is still alive, before that process exits with code 75.
        original_busy=self.controller.worker._lease_busy
        def probe():
            busy=original_busy()
            if not busy and released.exists():observed.write_text('observed')
            return busy
        patched=patch.object(self.controller.worker,'_lease_busy',side_effect=probe)
        patched.start();self.addCleanup(patched.stop)
        self.case.now = self.clock(); self.case.admit()
        self.wait(lambda: self.controller.state.read()['starts'][0]['exit_observed_at_utc'] is not None, seconds=10)
        original = self.controller.state.read()
        self.assertEqual(len(original['starts']), 1)
        self.wait(lambda: len(self.controller.state.read()['starts']) == 2, seconds=19)
        starts = self.controller.state.read()['starts']
        elapsed = (datetime.fromisoformat(starts[1]['reserved_at_utc'])-
            datetime.fromisoformat(starts[0]['exit_observed_at_utc'])).total_seconds()
        self.assertGreaterEqual(elapsed, 15)
        self.wait(lambda: len(self.provider_calls()) >= 2, seconds=6)
        def committed():
            with closing(sqlite3.connect(self.case.journal)) as c:
                return c.execute('SELECT count(*) FROM quote_acquisition WHERE channel="hot"').fetchone()[0] == 2
        self.wait(committed)
        stopped = self.controller.close(report=False)
        self.assertTrue(stopped['cleanup_within_10_seconds'])
        with closing(sqlite3.connect(self.case.journal)) as c:
            acquired_slots = [datetime.fromisoformat(row[0]) for row in c.execute(
                'SELECT scheduled_at_utc FROM quote_acquisition WHERE channel="hot" ORDER BY scheduled_at_utc')]
        self.assertEqual(len(acquired_slots), 2)
        self.assertEqual(len(self.provider_calls()), 2) # The first saved response was not requested again.
        self.assertTrue(released.exists() and observed.exists())
        job = self.controller.worker._job()
        self.assertEqual(job['generation'], 2)
        schedule = unseal(read_json(Path(job['job_path']).with_name(job['token']+'.schedule.json')))
        self.assertEqual(schedule['contract'], 'daily-hot-worker-schedule-v1')
        self.assertEqual(schedule['token'], starts[1]['token'])
        self.assertEqual(schedule['generation'], 2)
        self.assertEqual(schedule['invocation'], starts[1]['invocation'])
        self.assertEqual(schedule['configuration_sha256'], digest(self.config.payload()))
        self.assertEqual(schedule['resume_after_utc'], job['resume_after_utc'])
        self.assertEqual(schedule['launch_first_eligible_slot_utc'], job['first_eligible_slot_utc'])
        selected_at = datetime.fromisoformat(schedule['selected_at_utc'])
        eligible = datetime.fromisoformat(schedule['first_scheduled_slot_utc'])
        launch_slot = datetime.fromisoformat(job['first_eligible_slot_utc'])
        from mb_watchlist_coordinator.recovery_workers import atomic_json, next_future_slot
        self.assertGreaterEqual(selected_at, datetime.fromisoformat(self.config.collector.start_at_utc))
        self.assertEqual(eligible, next_future_slot(max(selected_at,
            datetime.fromisoformat(job['resume_after_utc']))))
        self.assertLess(launch_slot, selected_at)
        self.assertLess((selected_at-datetime.fromisoformat(job['started_at_utc'])).total_seconds(), 3)
        self.assertEqual(acquired_slots[-1], eligible) # No missing slot once actually ready.
        from mb_market_data.quote_journal_audit import audit_quote_journal
        # The proof ends with its first fresh committed replacement acquisition.
        # Producers are stopped above; do not race an in-flight/future slot or
        # pretend this short proof covers the configured five-minute window.
        audit = audit_quote_journal(self.case.journal, audited_at=acquired_slots[-1])
        gaps = next(c.missing_slot_ids for c in audit.channels if c.channel == 'hot')
        exited = datetime.fromisoformat(starts[0]['exit_observed_at_utc'])
        fault_at = datetime.fromisoformat(next(e['at'] for e in self.events()
            if e['role'] == 'collector' and e['event'] == 'fault:after_assembled'))
        self.assertLessEqual(fault_at, exited)
        expected_gaps = []
        cursor = next_future_slot(fault_at)
        while cursor < eligible:
            expected_gaps.append(cursor)
            cursor = next_future_slot(cursor)
        actual_gaps = [datetime.fromisoformat(slot.split(':', 1)[1]) for slot in gaps]
        diagnostics = {'contract': 'daily-recovery-gap-diagnostics-v1',
            'audit_through_utc': acquired_slots[-1].isoformat(),
            'fault_at_utc': fault_at.isoformat(), 'exit_observed_at_utc': exited.isoformat(),
            'replacement_schedule': schedule, 'starts': starts,
            'acquired_slots': [slot.isoformat() for slot in acquired_slots],
            'missing_slot_ids': list(gaps),
            'expected_missing_slots': [slot.isoformat() for slot in expected_gaps]}
        if os.environ.get('MB_DAILY_CONTROLLER_RECOVERY_PROOF_DIR'):
            atomic_json(self.case.root/'recovery-diagnostics.json', diagnostics)
            (self.case.root/'raw-recovery-audit.json').write_text(json.dumps(asdict(audit), default=str, indent=2)+'\n')
        self.assertTrue(gaps)
        self.assertEqual(actual_gaps, expected_gaps, diagnostics)
        self.assertEqual({f.code for f in audit.findings}, {'missing_poll_slots'})
        if os.environ.get('MB_DAILY_CONTROLLER_RECOVERY_PROOF_DIR'):
            from mb_market_data.quote_journal_replay import QuoteJournalReplayReader
            first = tuple(QuoteJournalReplayReader(self.case.journal).events())
            self.assertEqual(first, tuple(QuoteJournalReplayReader(self.case.journal).events()))
            atomic_json(self.case.root/'recovery-proof.json', {'contract': 'daily-owned-recovery-proof-v1',
                'result': 'PASS', 'synthetic_sdk_only': True, 'worker_starts': 2,
                'replacement_hold_seconds': elapsed, 'minimum_hold_seconds': 15,
                'starts': starts, 'provider_calls': 2, 'native_hot_acquisitions': 2,
                'audit_through_utc': acquired_slots[-1].isoformat(),
                'fault_at_utc': fault_at.isoformat(), 'replacement_schedule': schedule,
                'replacement_crossed_launch_slot': True,
                'saved_response_not_requested_again': True, 'two_fresh_replays_equal': True,
                'actual_role_lease_exit_gap_forced':True,
                'raw_native_audit_passed': audit.passed, 'intentional_missing_slot_ids': list(gaps),
                'unexplained_gaps': 0, 'intentional_hold_slots_not_backfilled': True,
                'full_day_capacity_qualified': False})

    def test_authentication_alone_does_not_satisfy_native_progress(self):
        self.start(mode='auth_hang')
        self.wait(lambda: self.controller.state.read()['terminal'] is not None, seconds=5)
        self.assertEqual(self.controller.state.read()['terminal'], 'worker_startup_deadline_ended')
        self.assertEqual(len(self.controller.state.read()['starts']), 1)
        self.assertFalse(self.provider_calls())

    def test_rejected_worker_credentials_do_not_start_a_replacement(self):
        self.start(mode='auth_error')
        self.wait(lambda: self.controller.state.read()['terminal'] is not None, seconds=5)
        self.assertEqual(self.controller.state.read()['terminal'], 'worker_credentials_rejected')
        self.assertEqual(len(self.controller.state.read()['starts']), 1)

    def test_identity_authentication_has_the_original_eight_second_bound(self):
        self.controller = self.make(mode='auth_hang', target='identity')
        began = time.monotonic()
        with self.assertRaises(Exception): self.controller.initialize(create=True)
        self.assertLess(time.monotonic()-began, 10)
        self.assertFalse(self.provider_calls('identity'))
        self.assertFalse(self.controller.password._value)

    def test_wrong_credential_horizon_never_reaches_worker_sdk_constructor(self):
        self.start(mode='credential_horizon')
        self.wait(lambda: self.controller.state.read()['terminal'] is not None, seconds=5)
        self.assertFalse([e for e in self.events() if e['role'] == 'collector' and e['event'] == 'constructed'])

    def test_interactive_authorization_is_rejected_and_not_saved(self):
        self.start(mode='authorization')
        self.wait(lambda: self.controller.state.read()['terminal'] is not None, seconds=5)
        self.assertFalse(self.provider_calls())
        self.controller.close(report=False)
        for path in self.controller.root.rglob('*.json'):
            self.assertNotIn('SYNTHETIC-CODE-CANARY-62', path.read_text())

    def test_hung_sdk_close_is_bounded_by_owned_process_cleanup(self):
        self.start(mode='close_hang'); self.wait(self.running)
        began = time.monotonic()
        stopped = self.controller.close(report=False)
        self.assertLess(time.monotonic()-began, 10)
        self.assertTrue(stopped['cleanup_within_10_seconds'])
        self.assertIsNone(self.controller.worker.child)

    def test_deleted_worker_registry_stops_collection_without_resetting_starts(self):
        self.start(); self.wait(self.running)
        self.controller.worker.registry.unlink()
        self.wait(lambda: self.controller.state.read()['terminal'] is not None)
        self.assertEqual(len(self.controller.state.read()['starts']), 1)
        self.assertFalse(self.provider_calls())

    def test_source_integrity_block_stops_dependent_hot_without_demoting_saved_membership(self):
        self.start(); self.wait(self.running)
        self.case.now = self.clock(); self.case.admit()
        before = self.case.store.membership_revisions_in_effective_order()
        with patch.object(self.controller.source, 'cycle', return_value={'status': 'BLOCKED'}):
            self.controller.step()
        self.assertTrue(self.controller.closed)
        self.assertEqual(self.controller.state.read()['terminal'], 'source_integrity_blocked')
        self.assertEqual(self.case.store.membership_revisions_in_effective_order(), before)

    def test_feed_unavailability_preserves_verified_membership_and_running_collector(self):
        self.start(); self.wait(self.running)
        self.case.now = self.clock(); self.case.admit()
        with patch.object(self.controller.source, 'cycle', return_value={'status': 'INCOMPLETE',
                'discovery_scope_reconciled': False, 'feed_stop_required': True}):
            report = self.controller.step()
        self.assertEqual(report['state'], 'RUNNING_WITH_SOURCE_GAPS')
        self.assertFalse(self.controller.stopped())
        self.assertEqual(self.case.store.membership_revisions_in_effective_order()[-1].hot_symbols, ('NVDA',))

    def test_foreign_publication_or_changed_claim_blocks_before_new_provider_calls(self):
        self.start(); self.wait(self.running)
        self.case.session.claim_path.write_text('{}')
        with self.assertRaises(Exception): self.controller.step()
        self.assertTrue(self.controller.closed)
        self.assertFalse(self.provider_calls())

    def reopen_session(self):
        self.case.session = DailySession(self.case.settings, self.case.catalog, clock=self.clock)
        self.case.session.attach(publication_approved=True)

    def test_manual_resume_keeps_original_budgets_and_requires_new_manual_secret(self):
        self.start(); self.wait(self.running)
        old = self.controller.state.read()['starts']
        self.controller.close(report=False)
        self.reopen_session()
        self.controller = self.make()
        self.controller.initialize(manual_resume_approved=True)
        state = self.controller.state.read()
        self.assertEqual(state['starts'], old)
        self.assertEqual(len(state['invocations']), 2)
        self.assertTrue(state['invocations'][-1]['manual_resume'])
        self.wait(lambda: self.controller.status()['state'] == 'REPLACEMENT_HOLD')
        self.assertGreaterEqual((datetime.fromisoformat(state['hold_until_utc'])-self.clock()).total_seconds(), 13)

    def test_unapproved_resume_and_fresh_create_cannot_reset_the_original_budget(self):
        self.start(); self.wait(self.running); self.controller.close(report=False)
        self.reopen_session()
        self.controller = self.make()
        with self.assertRaises(ValueError): self.controller.initialize()
        self.reopen_session()
        self.controller = self.make()
        with self.assertRaises(ValueError): self.controller.initialize(create=True)

    def test_missing_original_state_cannot_be_automatically_recreated(self):
        self.start(); self.wait(self.running); self.controller.close(report=False)
        self.controller.state.path.unlink(); self.reopen_session()
        self.controller = self.make()
        with self.assertRaises((FileNotFoundError, ValueError)): self.controller.initialize(manual_resume_approved=True)

    def test_read_only_view_requires_an_explicit_fence(self):
        with self.assertRaises(TypeError):
            DailyPublicationReader(self.case.settings, self.config.catalog_path,
                binding=self.config.collector.daily_binding, claim=self.config.collector.daily_claim,
                publication_binding=self.config.collector.publication_binding, clock=self.clock)

    def test_configuration_cannot_silently_adopt_settings_or_widen_worker_limits(self):
        from dataclasses import replace
        for auth in (replace(self.config.authentication, request_timeout_seconds=2),
                     replace(self.config.authentication, startup_timeout_seconds=9)):
            with self.assertRaises(ValueError): replace(self.config, authentication=auth).payload()
        with self.assertRaises(ValueError):
            DailyController(self.case.session, self.config, commands=self.commands,
                password=SessionPassword('synthetic', digest(self.config.payload())), clock=self.clock)

    def test_reporter_deadline_targets_only_the_owned_reporter(self):
        self.controller = self.make()
        class Hung:
            returncode = None
            def __init__(self): self.waits = []
            def wait(self, timeout):
                self.waits.append(timeout)
                if timeout in (56, 0): raise subprocess.TimeoutExpired('synthetic', timeout)
                self.returncode = -15
            def terminate(self): self.terminated = True
        hung = Hung()
        from mb_watchlist_coordinator.recovery_workers import atomic_json
        atomic_json(self.controller.root/'daily-worker.json', self.config.payload())
        with patch('mb_watchlist_coordinator.daily_controller.subprocess.Popen', return_value=hung):
            result = self.controller._final_report()
        self.assertEqual(result['status'], 'REPORT_INCOMPLETE')
        self.assertTrue(hung.terminated)
        self.assertEqual(hung.waits[0], 56)

    def test_daily_rate_limit_is_durable_and_manual_resume_cannot_retry_it(self):
        self.start(mode='rate_limit'); self.wait(self.running)
        self.case.now = self.clock(); self.case.admit()
        self.wait(lambda: self.controller.state.read()['terminal'] == 'native_blocked', seconds=10)
        calls = len(self.provider_calls())
        self.assertEqual(calls, 1)
        self.controller.close(report=False); self.reopen_session()
        self.controller = self.make(mode='rate_limit')
        with self.assertRaises(ValueError): self.controller.initialize(manual_resume_approved=True)
        self.assertEqual(len(self.provider_calls()), calls)

    def test_hung_quote_remains_unknown_and_waits_before_any_replacement(self):
        self.start(mode='quote_hang'); self.wait(self.running)
        self.case.now = self.clock(); self.case.admit()
        self.wait(lambda: self.controller.state.read()['hold_until_utc'] is not None, seconds=12)
        self.assertEqual(len(self.provider_calls()), 1)
        self.assertEqual(len(self.controller.state.read()['starts']), 1)
        with closing(sqlite3.connect(self.case.journal)) as c:
            self.assertEqual(c.execute('SELECT count(*) FROM quote_acquisition WHERE channel="hot"').fetchone()[0], 0)

    def test_actual_controller_process_loss_fences_both_orphan_roles(self):
        owner = self.make()
        self.case.session.close()
        ready = self.case.root/'owner-ready.json'
        scene = {**self.scenario, 'configuration': self.config.payload(), 'commands': self.commands,
            'ready': str(ready)}
        path = self.case.root/'owner-scene.json'; path.write_text(json.dumps(scene))
        command = [sys.executable, '-I', '-B', str(Path(__file__).parent/'fixtures/daily_controller_owner.py'), str(path)]
        child = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            deadline = time.monotonic()+7
            while not ready.exists() and child.poll() is None and time.monotonic() < deadline:
                time.sleep(.025)
            self.assertTrue(ready.exists(), child.stderr.read().decode() if child.poll() is not None else 'Controller not ready')
            child.kill(); child.wait(timeout=3)
            def free():
                try:
                    from mb_watchlist_coordinator.sampling_service import owner_lock
                    for lock in (owner.root/'workers/worker.lock', owner.root/'identity-owner.lock'):
                        with owner_lock(lock): pass
                    return True
                except ServiceBusy: return False
            self.wait(free, seconds=4)
            self.assertEqual(len(owner.state.read()['starts']), 1)
            self.assertFalse(self.provider_calls())
        finally:
            if child.poll() is None: child.kill(); child.wait(timeout=3)
            child.stdout.close(); child.stderr.close()
            owner.password.close()


if __name__ == '__main__': unittest.main()
