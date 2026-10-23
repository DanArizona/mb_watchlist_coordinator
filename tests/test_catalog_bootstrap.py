from contextlib import closing
from dataclasses import replace
from datetime import timedelta
import json
from pathlib import Path
import sqlite3
import unittest

import test_controller_bootstrap as original
SECRET, INVENTORY = original.SECRET, original.INVENTORY
from test_integrated_catalog import catalog as fixture_catalog, sources
from mb_market_data.quote_journal_audit import audit_quote_journal
from mb_market_data.quote_journal_replay import QuoteJournalReplayReader
from mb_watchlist_coordinator.authenticated_startup import StartupError
from mb_watchlist_coordinator.catalog_startup import CatalogStartupLedger, CONTRACT
from mb_watchlist_coordinator.controller_bootstrap import bootstrap_fresh, BootstrapError
from mb_watchlist_coordinator.integrated_catalog import acquire_catalog, CatalogError
from mb_watchlist_coordinator.integrated_catalog import DirectoryCatalog
from mb_watchlist_coordinator.sampling_requests import canonical, digest, plain, utc_text


class CatalogBootstrapTests(unittest.TestCase):
    api = original.FreshBootstrapTests.api

    def setUp(self):
        original.FreshBootstrapTests.setUp(self)
        self.legacy = self.settings
        self.settings = replace(self.settings, catalog_mode='owned_directory', catalog_id='', catalog_symbols=())
        self.plan = self.settings.plan()
        self.catalog_calls = 0; self.catalog_mode = 'normal'; self.catalog_hook = None
        self.target = Path(self.settings.experiment_root)

    def acquirer(self, *, deadline, clock):
        self.catalog_calls += 1
        self.assertEqual(self.calls, ['load', 'construct'])
        self.assertEqual(self.status_calls, 2)
        self.assertFalse((self.target/'quotes.sqlite3').exists())
        self.assertEqual(self.ledger().snapshot()['status'], 'PENDING_UNKNOWN')
        self.assertEqual(self.ledger().snapshot()['reserved_source_permits'], 2)
        if self.catalog_hook: self.catalog_hook()
        if self.catalog_mode == 'failure':
            raise CatalogError('catalog_http_or_timing_invalid', [{'source': 'nasdaq', 'body_b64': 'PGh0bWw+'}])
        if self.catalog_mode == 'arbitrary_exception': raise RuntimeError(SECRET)
        return fixture_catalog(self.now)

    def ledger(self):
        return CatalogStartupLedger(self.target/'directory.sqlite3', preflight=self.settings.plan().public,
            clock=lambda: self.now)

    def bootstrap(self, **kw):
        password = bytearray(SECRET.encode()); self.password = password
        args = dict(clock=lambda: self.now, inventory=lambda _: INVENTORY,
            secure_api=self.api(), catalog_acquirer=self.acquirer); args.update(kw)
        return bootstrap_fresh(self.plan, password, **args)

    def fail(self, stage):
        def hook(name):
            if name == stage: raise RuntimeError('synthetic interruption')
        return hook

    def test_preflight_is_pure_and_does_not_invent_a_catalog_or_admission(self):
        self.assertFalse(self.target.exists())
        self.assertEqual(self.plan.public['contract'], CONTRACT)
        self.assertIsNone(self.plan.admission); self.assertIsNone(self.plan.public['admission'])
        self.assertEqual(self.plan.public['directory_limits']['reserved_source_permits'], 2)

    def test_rounded_t0_does_not_extend_sixty_seconds_from_password_submission(self):
        self.now += timedelta(seconds=60, microseconds=100000)
        self.assertLess(self.now, original.datetime.fromisoformat(self.plan.public['start_at_utc'].replace('Z', '+00:00')))
        with self.assertRaises(BootstrapError) as caught: self.bootstrap()
        self.assertEqual(caught.exception.code, 'bootstrap_window_ended')
        self.assertFalse(self.calls); self.assertFalse(self.target.exists())

    def test_directory_driver_receives_the_earlier_absolute_bootstrap_deadline(self):
        def inspect(**kw):
            self.assertEqual(kw['deadline'], self.now+timedelta(seconds=60))
            return self.acquirer(**kw)
        session = self.bootstrap(catalog_acquirer=inspect); self.addCleanup(session.close)
        self.assertEqual(session.catalog_ledger.identity['deadline_utc'], utc_text(self.now+timedelta(seconds=60)))

    def test_legacy_default_identity_remains_byte_compatible(self):
        legacy = self.legacy.plan()
        self.assertNotIn('catalog_mode', legacy.public['settings'])
        self.assertEqual(legacy.public['contract'], 'authenticated-recovery-bootstrap-v1')
        self.assertNotIn('directory_limits', legacy.public)

    def test_owned_mode_rejects_caller_catalog_and_unknown_modes(self):
        for s in (replace(self.settings, catalog_id='unverified'),
                replace(self.settings, catalog_symbols=('MSFT',)), replace(self.settings, catalog_mode='fallback')):
            with self.assertRaises(BootstrapError): s.plan()

    def test_credentials_then_reservation_then_catalog_then_native_run(self):
        session = self.bootstrap(); self.addCleanup(session.close)
        names = [s['stage'] for s in session.receipt['stages']]
        for a, b in zip(('credentials_accepted', 'root_claimed', 'directory_invocation_reserved',
                'directory_captured', 'catalog_bound', 'journal_initialized'),
                ('root_claimed', 'directory_invocation_reserved', 'directory_captured',
                 'catalog_bound', 'journal_initialized', 'initial_poll_run_registered')):
            self.assertLess(names.index(a), names.index(b))
        self.assertEqual(self.catalog_calls, 1); self.assertEqual(session.catalog_ledger.snapshot()['status'], 'BOUND')
        self.assertEqual(session.receipt['reserved_directory_permits'], 2)
        self.assertEqual(session.receipt['contract'], CONTRACT)
        self.assertFalse(self.password)

    def test_actual_owned_synthetic_directory_children_are_after_auth(self):
        def owned(**kw):
            self.assertEqual(self.calls, ['load', 'construct'])
            self.assertFalse((self.target/'quotes.sqlite3').exists())
            return acquire_catalog(**kw, synthetic={k: {'body': v.decode()} for k, v in sources(self.now).items()})
        session = self.bootstrap(catalog_acquirer=owned); self.addCleanup(session.close)
        self.assertEqual(session.catalog.symbols, ('AMD', 'IBM', 'MSFT', 'NVDA'))
        self.assertTrue(all(r['synthetic'] for r in session.catalog.receipts.values()))

    def test_catalog_binds_admission_anchor_worker_and_identity_gate(self):
        session = self.bootstrap(); self.addCleanup(session.close)
        self.assertEqual(session.requests.admission.catalog_id, session.catalog.catalog_id)
        self.assertEqual(session.requests.admission.catalog_symbols, frozenset(session.catalog.symbols))
        self.assertEqual(session.gated_delivery.snapshot()['identity_gate']['catalog_id'], session.catalog.catalog_id)
        self.assertIs(session.delivery, session.gated_delivery)
        self.assertIs(session.base_delivery, session.gated_delivery.delivery)
        self.assertEqual(session.receipt['preflight_configuration_sha256'], self.plan.configuration_sha256)
        self.assertNotEqual(session.plan.configuration_sha256, self.plan.configuration_sha256)
        (anchor,) = session.store.membership_revisions_in_effective_order()
        self.assertEqual(anchor.metadata['configuration_sha256'], session.plan.configuration_sha256)
        self.assertEqual(anchor.hot_symbols, ())
        self.assertEqual(session.collector.settings.publication_binding, plain(session.service.identity))
        self.assertEqual(session.password.identity['configuration_sha256'], digest(json.loads(
            (self.target/'authenticated-worker.json').read_text())))

    def test_no_quote_feed_or_worker_starts_and_client_is_not_reconstructed(self):
        session = self.bootstrap(); self.addCleanup(session.close)
        self.assertEqual(self.calls, ['load', 'construct']); self.assertEqual(self.status_calls, 2)
        self.assertIs(session.collector.client_factory(), session.client)
        self.assertEqual(session.gated_delivery.snapshot()['identity_gate']['quote_permits'], 0)
        self.assertFalse(session.feed.snapshot()['attempts'])
        self.assertFalse(session.store.acquisitions_in_replay_order())
        session.close(); session.close(); self.assertEqual(self.closed, 1)

    def test_native_audit_and_two_replays_agree_after_bound_bootstrap(self):
        session = self.bootstrap(); self.addCleanup(session.close)
        self.assertTrue(audit_quote_journal(session.store.database_path, audited_at=self.now).passed)
        def replay(): return [(e.event_id, repr(e)) for e in QuoteJournalReplayReader(session.store.database_path).events()]
        self.assertEqual(replay(), replay())

    def test_failed_auth_leaves_no_root_directory_or_catalog_call(self):
        self.mode = 'load_error'
        with self.assertRaises(StartupError): self.bootstrap()
        self.assertFalse(self.target.exists()); self.assertEqual(self.catalog_calls, 0)
        self.assertFalse(self.password)

    def test_missing_explicit_catalog_driver_is_rejected_before_auth(self):
        with self.assertRaises(BootstrapError): self.bootstrap(catalog_acquirer=None)
        self.assertFalse(self.calls); self.assertFalse(self.target.exists())

    def test_dependency_mismatch_never_loads_password_or_starts_directory(self):
        with self.assertRaises(BootstrapError): self.bootstrap(inventory=lambda _: {'qualified': False})
        self.assertFalse(self.calls); self.assertEqual(self.catalog_calls, 0)

    def test_failed_catalog_retains_failure_bytes_and_charges_both_permits(self):
        self.catalog_mode = 'failure'
        with self.assertRaises(BootstrapError) as caught: self.bootstrap()
        self.assertEqual(caught.exception.code, 'catalog_failed')
        state = self.ledger().snapshot()
        self.assertEqual(state['status'], 'FAILED'); self.assertEqual(state['reserved_source_permits'], 2)
        self.assertEqual(state['events'][-1]['payload']['receipts'][0]['body_b64'], 'PGh0bWw+')
        self.assertFalse((self.target/'quotes.sqlite3').exists()); self.assertEqual(self.closed, 1)

    def test_failed_or_interrupted_invocation_cannot_be_reserved_or_fetched_again(self):
        with self.assertRaises(BootstrapError): self.bootstrap(fault_hook=self.fail('directory_invocation_reserved'))
        self.assertEqual(self.catalog_calls, 0)
        self.assertEqual(self.ledger().snapshot()['status'], 'PENDING_UNKNOWN')
        with self.assertRaises(ValueError): self.ledger().reserve()
        calls = list(self.calls)
        with self.assertRaises(BootstrapError) as caught: self.bootstrap()
        self.assertEqual(caught.exception.code, 'target_exists'); self.assertEqual(self.calls, calls)
        self.assertEqual(self.ledger().snapshot()['reserved_source_permits'], 2)

    def test_captured_bytes_reconstruct_without_another_acquisition(self):
        with self.assertRaises(BootstrapError): self.bootstrap(fault_hook=self.fail('directory_captured'))
        self.assertEqual(self.ledger().snapshot()['status'], 'CAPTURED')
        recovered = self.ledger().recovered_catalog()
        self.assertEqual(recovered.catalog_id, fixture_catalog(self.now).catalog_id)
        self.assertEqual(self.catalog_calls, 1); self.assertFalse((self.target/'catalog').exists())

    def test_bound_catalog_survives_interrupt_before_initial_journal(self):
        with self.assertRaises(BootstrapError): self.bootstrap(fault_hook=self.fail('catalog_bound'))
        self.assertEqual(self.ledger().snapshot()['status'], 'BOUND')
        self.assertEqual(self.ledger().recovered_catalog().symbols, ('AMD', 'IBM', 'MSFT', 'NVDA'))
        self.assertFalse((self.target/'quotes.sqlite3').exists())

    def test_changed_proposal_during_fetch_blocks_native_creation(self):
        self.catalog_hook = lambda: Path(self.settings.opening_proposal).write_bytes(
            Path(self.settings.opening_proposal).read_bytes()+b' ')
        with self.assertRaises(BootstrapError): self.bootstrap()
        self.assertFalse((self.target/'quotes.sqlite3').exists()); self.assertEqual(self.closed, 1)

    def test_catalog_artifact_tampering_blocks_before_native_creation(self):
        def hook(name):
            if name == 'catalog_bound': (self.target/'catalog/nasdaq.txt').write_text('changed')
        with self.assertRaises(BootstrapError): self.bootstrap(fault_hook=hook)
        self.assertFalse((self.target/'quotes.sqlite3').exists())

    def test_catalog_ledger_tampering_blocks_before_native_creation(self):
        def hook(name):
            if name == 'catalog_bound':
                with closing(sqlite3.connect(self.target/'directory.sqlite3')) as c, c:
                    c.execute("UPDATE catalog_startup_identity SET payload='{}'")
        with self.assertRaises(BootstrapError): self.bootstrap(fault_hook=hook)
        self.assertFalse((self.target/'quotes.sqlite3').exists())

    def test_late_catalog_result_creates_no_native_run_and_keeps_reserved_budget(self):
        self.catalog_hook = lambda: setattr(self, 'now', self.now+timedelta(seconds=61))
        with self.assertRaises(BootstrapError): self.bootstrap()
        self.assertFalse((self.target/'quotes.sqlite3').exists())
        self.assertEqual(self.ledger().snapshot()['reserved_source_permits'], 2)

    def test_missing_reservation_or_bound_catalog_cannot_be_reset(self):
        session = self.bootstrap(); session.close()
        (self.target/'catalog/other.txt').unlink()
        with self.assertRaises(ValueError): self.ledger().snapshot()
        (self.target/'directory.sqlite3').unlink()
        with self.assertRaises(FileNotFoundError): self.ledger().initialize()

    def test_rehashed_false_permit_count_is_still_rejected_after_a_warm_read(self):
        with self.assertRaises(BootstrapError): self.bootstrap(fault_hook=self.fail('directory_invocation_reserved'))
        self.ledger().snapshot()
        with closing(sqlite3.connect(self.target/'directory.sqlite3')) as c, c:
            e = json.loads(c.execute('SELECT payload FROM catalog_startup_event').fetchone()[0])
            e['payload']['source_permits'] = 1; e.pop('event_sha256'); e['event_sha256'] = digest(e)
            c.execute('UPDATE catalog_startup_event SET payload=?', (canonical(e),))
        with self.assertRaises(ValueError): self.ledger().snapshot()

    def test_arbitrary_catalog_exception_never_enters_retained_artifacts(self):
        self.catalog_mode = 'arbitrary_exception'
        with self.assertRaises(BootstrapError) as caught: self.bootstrap()
        self.assertNotIn(SECRET, str(caught.exception))
        for p in self.target.rglob('*'):
            if p.is_file(): self.assertNotIn(SECRET.encode(), p.read_bytes())

    def test_partial_native_creation_remains_evidence_and_is_not_adopted(self):
        with self.assertRaises(BootstrapError): self.bootstrap(fault_hook=self.fail('initial_poll_run_registered'))
        with closing(sqlite3.connect(self.target/'quotes.sqlite3')) as c:
            self.assertEqual(c.execute('SELECT count(*) FROM poll_run').fetchone()[0], 1)
        calls = list(self.calls)
        with self.assertRaises(BootstrapError): self.bootstrap()
        self.assertEqual(self.calls, calls); self.assertEqual(self.catalog_calls, 1)

    def test_large_synthetic_catalog_keeps_exact_native_and_gate_binding(self):
        def large(**kw):
            base = fixture_catalog(self.now); bodies = dict(base.bodies)
            head, footer = bodies['nasdaq'].rsplit(b'File Creation Time:', 1)
            rows = ''.join(f'SYM{n:04d}|Synthetic listing {n}|Q|N|N|100|N\n' for n in range(7000)).encode()
            bodies['nasdaq'] = head+rows+b'File Creation Time:'+footer
            return DirectoryCatalog(bodies, plain(base.receipts))
        session = self.bootstrap(catalog_acquirer=large); self.addCleanup(session.close)
        self.assertEqual(len(session.requests.admission.catalog_symbols), 7004)
        self.assertEqual(session.catalog.catalog_id, session.catalog_ledger.recovered_catalog().catalog_id)
        self.assertEqual(session.gated_delivery.snapshot()['identity_gate']['catalog_id'], session.catalog.catalog_id)

    def test_completed_reservation_and_changed_binding_never_reset_budget(self):
        session = self.bootstrap(); session.close()
        with self.assertRaises(ValueError): self.ledger().reserve()
        altered = plain(self.plan.public); altered['settings']['nonce'] = 'b'*32
        ledger = CatalogStartupLedger(self.target/'directory.sqlite3', preflight=altered)
        with self.assertRaises(ValueError): ledger.initialize()
        self.assertEqual(self.ledger().snapshot()['reserved_source_permits'], 2)
