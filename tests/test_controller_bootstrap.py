from contextlib import closing
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest

from mb_market_data.sampling_membership import SamplingHierarchyRevision
from mb_market_data.quote_journal_audit import audit_quote_journal
from mb_market_data.quote_journal_replay import QuoteJournalReplayReader
from mb_watchlist_coordinator.authenticated_startup import StartupError, receive_password
from mb_watchlist_coordinator.controller_bootstrap import (
    BootstrapSettings, BootstrapError, EXPECTED_HELPERS, bootstrap_fresh, strict_json)
from mb_watchlist_coordinator.sampling_requests import digest, plain

SECRET = 'SYNTHETIC-PASSWORD-CANARY-41'
INVENTORY = {'qualified': True, 'reason': 'probe_pass', 'synthetic_only': True}


def make_settings(root):
    from mb_market_data.watchlist_polling import ET
    submitted = (datetime.now(ET)+timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=123456)
    opening = submitted.replace(hour=9, minute=30, second=0, microsecond=0)
    proposals = []
    for rev in (0, 1):
        value = {'session_date': opening.date().isoformat(), 'revision': rev,
            'effective_at': opening.isoformat(), 'uni_symbols': ['MSFT', 'SPY'],
            'focus_symbols': [] if rev == 0 else ['SPY'], 'hot_symbols': [],
            'source': 'synthetic-bootstrap', 'metadata': {'test_fixture': True}}
        path = root/('r'+str(rev)+'.json')
        path.write_text(json.dumps(value))
        native = dict(value, session_date=opening.date(), effective_at=opening)
        proposals.append((path, SamplingHierarchyRevision(**native).content_sha256))
    return BootstrapSettings(str(root/'integrated_hot_fresh'), str(proposals[0][0]), str(proposals[1][0]),
        proposals[0][1], proposals[1][1], str(root/'synthetic.ecfg'), submitted.astimezone(timezone.utc).isoformat(),
        'a'*32, digest(INVENTORY), 'synthetic-reviewed-catalog', ('MSFT', 'SPY', 'NVDA'))


class FreshBootstrapTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.settings = make_settings(self.root)
        self.now = datetime.fromisoformat(self.settings.password_submitted_at_utc)
        self.plan = self.settings.plan()
        self.calls = []; self.closed = 0; self.status_calls = 0
        self.mode = 'normal'; self.constructor_hook = None

    def api(self):
        case = self
        def load(path, password):
            case.calls.append('load')
            case.assertEqual(bytes(password), SECRET.encode())
            if case.mode == 'load_error':
                raise RuntimeError(SECRET)
            return object()
        def status(config, *, observed_at):
            case.status_calls += 1
            def require(required):
                case.assertEqual(required, datetime.fromisoformat(case.plan.public['stop_at_utc'].replace('Z', '+00:00'))+timedelta(minutes=75, seconds=30))
                if case.mode == 'horizon' or case.mode == 'post_horizon' and case.status_calls == 2:
                    raise RuntimeError(SECRET)
            return SimpleNamespace(require_refresh_valid_through=require)
        def make(config, *, timeout, call_on_auth):
            case.calls.append('construct')
            case.assertFalse(Path(case.settings.experiment_root).exists())
            if case.constructor_hook:
                case.constructor_hook()
            if case.mode == 'authorization':
                call_on_auth('https://synthetic.invalid?code='+SECRET)
            class Client:
                def quotes(self, *a, **kw):
                    raise AssertionError('Bootstrap must never request a quote')
                def close(self):
                    case.closed += 1
            return Client()
        return SimpleNamespace(load_secure_schwab_config=load, read_schwab_token_status=status,
            make_client_from_config=make, DEFAULT_POLLING_REFRESH_MARGIN=timedelta(minutes=75, seconds=30))

    def bootstrap(self, **kw):
        self.password = bytearray(SECRET.encode())
        args = dict(clock=lambda: self.now, inventory=lambda _: INVENTORY, secure_api=self.api()); args.update(kw)
        return bootstrap_fresh(self.plan, self.password, **args)

    def rows(self, table):
        with closing(sqlite3.connect(Path(self.settings.experiment_root)/'quotes.sqlite3')) as c:
            return c.execute('SELECT count(*) FROM '+table).fetchone()[0]

    def test_pure_validation_creates_no_target_and_freezes_window_and_source_hashes(self):
        self.assertFalse(Path(self.settings.experiment_root).exists())
        start = datetime.fromisoformat(self.plan.public['start_at_utc'].replace('Z', '+00:00'))
        self.assertEqual(start-self.now, timedelta(seconds=60, microseconds=876544))
        self.assertEqual(datetime.fromisoformat(self.plan.public['stop_at_utc'].replace('Z', '+00:00'))-start, timedelta(seconds=720))
        with self.assertRaises(TypeError):
            self.plan.public['new'] = True

    def test_success_initializes_bound_native_and_coordinator_state_only_after_authentication(self):
        session = self.bootstrap(); self.addCleanup(session.close)
        self.assertEqual(self.calls, ['load', 'construct']); self.assertEqual(self.status_calls, 2)
        stages = [s['stage'] for s in session.receipt['stages']]
        self.assertLess(stages.index('credentials_accepted'), stages.index('journal_initialized'))
        self.assertLess(stages.index('credentials_accepted'), stages.index('initial_poll_run_registered'))
        self.assertEqual(self.rows('poll_run'), 1); self.assertEqual(self.rows('quote_acquisition'), 0)
        self.assertEqual(self.rows('quote_observation'), 0)
        self.assertEqual(session.receipt['status'], 'BOOTSTRAPPED_NOT_RUNNING')
        self.assertEqual(session.collector.settings.publication_binding, plain(session.service.identity))
        self.assertEqual(session.collector.settings.max_quote_calls, 60)
        self.assertEqual(session.collector.settings.max_symbols, 1)
        self.assertIs(session.collector.client_factory(), session.client)
        self.assertFalse(session.feed.snapshot()['attempts'])
        self.assertEqual(session.live.snapshot()['receipts'], ())
        self.assertFalse(self.password)
        session.close(); session.close(); self.assertEqual(self.closed, 1)

    def test_native_anchor_keeps_rosters_with_empty_hot_and_future_effective_time(self):
        session = self.bootstrap(); self.addCleanup(session.close)
        (anchor,) = session.store.membership_revisions_in_effective_order()
        self.assertEqual(anchor.uni_symbols, ('MSFT', 'SPY'))
        self.assertEqual(anchor.focus_symbols, ('SPY',)); self.assertEqual(anchor.hot_symbols, ())
        self.assertGreater(anchor.effective_at, self.now)
        self.assertNotEqual(anchor.content_sha256, self.settings.focus_content_sha256)

    def test_native_audit_and_independent_replays_agree_before_any_acquisition(self):
        session = self.bootstrap(); self.addCleanup(session.close)
        self.assertTrue(audit_quote_journal(session.store.database_path, audited_at=self.now).passed)
        def replay():
            return [(e.event_id, repr(e)) for e in QuoteJournalReplayReader(session.store.database_path).events()]
        self.assertEqual(replay(), replay())

    def test_manual_secret_is_bound_to_actual_worker_configuration_and_not_written(self):
        import io
        session = self.bootstrap(); self.addCleanup(session.close)
        worker = json.loads((Path(self.settings.experiment_root)/'authenticated-worker.json').read_text())
        self.assertEqual(session.password.identity['configuration_sha256'], digest(worker))
        self.assertEqual(receive_password(io.BytesIO(session.password.frame('b'*32)), 'b'*32), SECRET.encode())
        self.assertNotIn(SECRET, repr(session))
        for p in Path(self.settings.experiment_root).rglob('*'):
            if p.is_file(): self.assertNotIn(SECRET.encode(), p.read_bytes(), str(p))

    def test_invalid_credential_and_horizon_paths_leave_no_experiment(self):
        for mode in ('load_error', 'horizon', 'post_horizon', 'authorization'):
            with self.subTest(mode=mode):
                self.mode = mode; self.status_calls = 0
                with self.assertRaises(StartupError) as result: self.bootstrap()
                self.assertNotIn(SECRET, str(result.exception))
                self.assertFalse(Path(self.settings.experiment_root).exists())
                self.assertFalse(self.password)

    def test_rejected_dependency_never_loads_credentials_or_creates_target(self):
        for value in ({'qualified': False}, dict(INVENTORY, changed=True)):
            with self.assertRaises(BootstrapError): self.bootstrap(inventory=lambda _: value)
        self.assertFalse(self.calls); self.assertFalse(Path(self.settings.experiment_root).exists())

    def test_source_change_while_constructor_runs_blocks_before_initial_journal(self):
        self.constructor_hook = lambda: Path(self.settings.opening_proposal).write_bytes(Path(self.settings.opening_proposal).read_bytes()+b' ')
        with self.assertRaises(BootstrapError) as result: self.bootstrap()
        self.assertEqual(result.exception.code, 'inputs_changed')
        self.assertFalse(Path(self.settings.experiment_root).exists()); self.assertEqual(self.closed, 1)

    def test_window_ending_while_authenticating_leaves_target_uncreated(self):
        self.constructor_hook = lambda: setattr(self, 'now', datetime.fromisoformat(self.plan.public['start_at_utc'].replace('Z', '+00:00')))
        with self.assertRaises(BootstrapError) as result: self.bootstrap()
        self.assertEqual(result.exception.code, 'bootstrap_window_ended')
        self.assertFalse(Path(self.settings.experiment_root).exists()); self.assertEqual(self.closed, 1)

    def test_existing_root_is_never_adopted_or_authenticated_again(self):
        target = Path(self.settings.experiment_root); target.mkdir(); (target/'foreign.txt').write_text('retain')
        with self.assertRaises(BootstrapError) as result: self.bootstrap()
        self.assertEqual(result.exception.code, 'target_exists'); self.assertFalse(self.calls)
        self.assertEqual((target/'foreign.txt').read_text(), 'retain')

    def test_partial_creation_is_preserved_and_second_fresh_attempt_is_refused(self):
        def fault(name):
            if name == 'initial_poll_run_registered': raise RuntimeError(SECRET)
        with self.assertRaises(BootstrapError): self.bootstrap(fault_hook=fault)
        target = Path(self.settings.experiment_root)
        self.assertEqual(self.rows('poll_run'), 1)
        self.assertEqual(json.loads((target/'bootstrap-failed.json').read_text())['status'], 'PARTIAL_REQUIRES_REVIEW')
        before = (target/'quotes.sqlite3').read_bytes(); calls = list(self.calls)
        with self.assertRaises(BootstrapError): self.bootstrap()
        self.assertEqual(self.calls, calls); self.assertEqual((target/'quotes.sqlite3').read_bytes(), before)

    def test_failure_after_authentication_before_root_claim_closes_client_and_clears_secret(self):
        def fault(name):
            if name == 'credentials_accepted': raise RuntimeError(SECRET)
        with self.assertRaises(BootstrapError): self.bootstrap(fault_hook=fault)
        self.assertEqual(self.closed, 1); self.assertFalse(self.password)
        self.assertFalse(Path(self.settings.experiment_root).exists())

    def test_backward_clock_after_claim_blocks_before_journal_creation(self):
        def fault(name):
            if name == 'root_claimed': self.now -= timedelta(seconds=1)
        with self.assertRaises(BootstrapError) as result: self.bootstrap(fault_hook=fault)
        self.assertEqual(result.exception.code, 'bootstrap_window_ended')
        self.assertFalse((Path(self.settings.experiment_root)/'quotes.sqlite3').exists())
        self.assertEqual(self.closed, 1)

    def test_public_input_hash_date_and_initial_hot_mismatch_are_rejected(self):
        for setting in (replace(self.settings, focus_content_sha256='0'*64),
                replace(self.settings, nonce='invalid'), replace(self.settings, profile='unbounded'),
                replace(self.settings, experiment_root=str(self.root/'quote_observation_journal_prod'))):
            with self.assertRaises(BootstrapError): setting.plan()
        value = json.loads(Path(self.settings.focus_proposal).read_text()); value['hot_symbols'] = ['SPY']
        Path(self.settings.focus_proposal).write_text(json.dumps(value))
        with self.assertRaises(BootstrapError): self.settings.plan()

    def test_window_cannot_cross_regular_close_or_target_session(self):
        submitted = self.now.replace(hour=20, minute=0)
        with self.assertRaises(BootstrapError): replace(self.settings, password_submitted_at_utc=submitted.isoformat()).plan()
        with self.assertRaises(BootstrapError): replace(self.settings, password_submitted_at_utc=(self.now+timedelta(days=1)).isoformat()).plan()

    def test_exact_close_is_allowed_but_one_microsecond_later_is_rejected(self):
        from mb_market_data.watchlist_polling import ET
        submitted = self.now.astimezone(ET).replace(hour=15, minute=47, second=0, microsecond=0)
        plan = replace(self.settings, password_submitted_at_utc=submitted.isoformat()).plan()
        self.assertEqual(datetime.fromisoformat(plan.public['stop_at_utc'].replace('Z', '+00:00')).astimezone(ET).time().isoformat(), '16:00:00')
        with self.assertRaises(BootstrapError):
            replace(self.settings, password_submitted_at_utc=(submitted+timedelta(microseconds=1)).isoformat()).plan()

    def test_duplicate_and_nonfinite_json_are_rejected(self):
        for raw in ('{"a":1,"a":2}', '{"a":NaN}'):
            with self.assertRaises(ValueError): strict_json(raw)

    def test_helper_pin_matches_accepted_installed_probe_reference(self):
        p = Path(__file__).resolve().parents[1]/'experiments/installed_startup_20261023/expected_mb_tools.json'
        self.assertEqual(EXPECTED_HELPERS, json.loads(p.read_text())['files'])
