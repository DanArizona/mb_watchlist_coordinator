from dataclasses import asdict, replace
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import unittest

import test_controller_bootstrap_process as prior
from test_controller_bootstrap import INVENTORY, SECRET
from mb_watchlist_coordinator.authenticated_startup import SessionPassword
from mb_watchlist_coordinator.bootstrap_entry import parse_receipt
from mb_watchlist_coordinator.catalog_startup import CatalogStartupLedger, CONTRACT
from mb_watchlist_coordinator.controller_bootstrap import BootstrapError


class CatalogBootstrapProcessTests(unittest.TestCase):
    events = prior.BootstrapProcessTests.events
    count_runs = prior.BootstrapProcessTests.count_runs

    def setUp(self):
        prior.BootstrapProcessTests.setUp(self)
        self.frame.close()
        self.settings = replace(self.settings, catalog_mode='owned_directory', catalog_id='', catalog_symbols=())
        self.plan = self.settings.plan()
        self.configuration.write_text(json.dumps(asdict(self.settings)))
        self.frame = SessionPassword(SECRET, self.plan.configuration_sha256); self.addCleanup(self.frame.close)

    def ledger(self):
        return CatalogStartupLedger(self.target/'directory.sqlite3', preflight=self.plan.public)

    def run_child(self, mode='normal', *, frame=True, **limits):
        token = limits.pop('private_token', self.settings.nonce)
        self.simulation.write_text(json.dumps({'mode': mode, 'real_anchor_utc': datetime.now(timezone.utc).isoformat(),
            'logical_anchor_utc': self.at.isoformat(), 'configuration': str(self.configuration),
            'configuration_sha256': self.plan.configuration_sha256, 'experiment_root': str(self.target),
            'opening_proposal': self.settings.opening_proposal, 'log': str(self.log),
            'inventory': INVENTORY, **limits}))
        child = subprocess.Popen([sys.executable, '-I', '-B',
            str(Path(__file__).parent/'fixtures/catalog_bootstrap_worker.py'), str(self.simulation)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            if frame:
                out, err = child.communicate(self.frame.frame(token), timeout=12)
            else:
                child.wait(timeout=5); out, err = child.communicate()
        finally:
            if child.poll() is None: child.kill()
            child.communicate()
            if child.stdin: child.stdin.close()
            if child.stdout: child.stdout.close()
            if child.stderr: child.stderr.close()
        self.assertEqual(err, b''); self.assertNotIn(SECRET.encode(), out)
        self.assertNotIn(b'SYNTHETIC-CODE-CANARY-41', out)
        return child.returncode, parse_receipt(out, self.plan.configuration_sha256, contract=CONTRACT) if out else None

    def test_pinned_auth_then_owned_catalog_then_native_creation_and_quiet_receipt(self):
        code, result = self.run_child()
        self.assertEqual(code, 0); self.assertEqual(result['result'], 'PASS')
        self.assertEqual(self.events(), ['constructed', 'directory_called', 'closed'])
        self.assertEqual(result['reserved_directory_permits'], 2)
        self.assertEqual(self.ledger().snapshot()['status'], 'BOUND'); self.assertEqual(self.count_runs(), 1)
        public = json.loads((self.target/'bootstrap.json').read_text())
        self.assertEqual(result['bound_configuration_sha256'], public['configuration_sha256'])
        self.assertTrue(result['client_close_invoked'])
        self.assertEqual(result['quote_dispatches_started'], 0); self.assertEqual(result['feed_attempts_started'], 0)
        for p in self.target.rglob('*'):
            if p.is_file(): self.assertNotIn(SECRET.encode(), p.read_bytes())

    def test_wrong_password_never_claims_root_or_directory_permits(self):
        self.frame.close(); self.frame = SessionPassword('synthetic-wrong', self.plan.configuration_sha256)
        self.addCleanup(self.frame.close)
        code, result = self.run_child()
        self.assertEqual(code, 70); self.assertFalse(self.target.exists())
        self.assertEqual(result['reserved_directory_permits'], 0); self.assertFalse(self.events())

    def test_authorization_refusal_never_fetches_catalog_or_creates_journal(self):
        code, result = self.run_child('authorization')
        self.assertEqual(code, 70); self.assertEqual(result['reason'], 'authorization_required')
        self.assertFalse(self.target.exists()); self.assertNotIn('directory_called', self.events())

    def test_missing_private_frame_is_stopped_before_native_or_catalog(self):
        code, result = self.run_child(frame=False, startup_seconds=1, hard_seconds=3)
        self.assertEqual(code, 124); self.assertEqual(result['reason'], 'credential_deadline_ended')
        self.assertFalse(self.target.exists()); self.assertFalse(self.events())

    def test_directory_http_failure_is_retained_without_native_run(self):
        code, result = self.run_child('directory_http_failure')
        self.assertEqual(code, 70); self.assertEqual(result['reason'], 'catalog_failed')
        self.assertEqual(self.ledger().snapshot()['status'], 'FAILED')
        self.assertEqual(result['reserved_directory_permits'], 2)
        self.assertFalse((self.target/'quotes.sqlite3').exists())

    def test_directory_owned_child_timeout_is_charged_and_not_retried(self):
        code, result = self.run_child('directory_timeout')
        self.assertEqual(code, 70); self.assertEqual(result['reason'], 'catalog_failed')
        state = self.ledger().snapshot(); self.assertEqual(state['status'], 'FAILED')
        self.assertEqual(state['events'][-1]['payload']['code'], 'catalog_hard_deadline')
        self.assertEqual(state['reserved_source_permits'], 2)
        code, result = self.run_child(); self.assertEqual(code, 70); self.assertEqual(result['reason'], 'target_exists')
        self.assertEqual(self.events().count('directory_called'), 1)

    def test_process_exit_after_reservation_preserves_unknown_and_blocks_fresh_retry(self):
        code, result = self.run_child('crash_directory_invocation_reserved')
        self.assertEqual(code, 77); self.assertIsNone(result)
        self.assertEqual(self.ledger().snapshot()['status'], 'PENDING_UNKNOWN')
        self.assertNotIn('directory_called', self.events())
        code, result = self.run_child(); self.assertEqual(code, 70)
        self.assertEqual(result['reason'], 'target_exists'); self.assertEqual(self.events().count('constructed'), 1)

    def test_process_exit_after_capture_retains_raw_catalog_without_refetch(self):
        code, result = self.run_child('crash_directory_captured')
        self.assertEqual(code, 77); self.assertIsNone(result)
        self.assertEqual(self.ledger().snapshot()['status'], 'CAPTURED')
        self.assertEqual(self.ledger().recovered_catalog().symbols, ('AMD', 'IBM', 'MSFT', 'NVDA'))
        self.assertFalse((self.target/'quotes.sqlite3').exists())
        self.assertEqual(self.events().count('directory_called'), 1)

    def test_process_exit_after_binding_retains_catalog_before_native_creation(self):
        code, result = self.run_child('crash_catalog_bound')
        self.assertEqual(code, 77); self.assertIsNone(result)
        self.assertEqual(self.ledger().snapshot()['status'], 'BOUND')
        self.assertFalse((self.target/'quotes.sqlite3').exists())
        code, result = self.run_child(); self.assertEqual(code, 70); self.assertEqual(result['reason'], 'target_exists')

    def test_process_exit_after_native_run_preserves_single_run_and_original_binding(self):
        code, result = self.run_child('crash_initial_poll_run_registered')
        self.assertEqual(code, 77); self.assertIsNone(result); self.assertEqual(self.count_runs(), 1)
        before = self.ledger().snapshot()
        code, result = self.run_child(); self.assertEqual(code, 70); self.assertEqual(self.count_runs(), 1)
        self.assertEqual(self.ledger().snapshot(), before)

    def test_overall_deadline_still_bounds_a_blocked_post_auth_directory_driver(self):
        code, result = self.run_child('hang_catalog', startup_seconds=3, hard_seconds=4)
        self.assertEqual(code, 124); self.assertEqual(result['reason'], 'bootstrap_deadline_ended')
        self.assertEqual(result['reserved_directory_permits'], 2)
        self.assertEqual(self.ledger().snapshot()['status'], 'PENDING_UNKNOWN')
        self.assertFalse((self.target/'quotes.sqlite3').exists())

    def test_close_remains_inside_overall_deadline_after_bound_native_creation(self):
        code, result = self.run_child('hung_close', startup_seconds=3, hard_seconds=4)
        self.assertEqual(code, 124); self.assertEqual(result['reason'], 'bootstrap_deadline_ended')
        self.assertTrue(result['native_run_registered']); self.assertTrue(result['client_close_invoked'])
        self.assertEqual(self.ledger().snapshot()['status'], 'BOUND')

    def test_v2_protocol_cannot_be_misread_as_legacy_or_accept_false_permits(self):
        code, result = self.run_child(); self.assertEqual(code, 0)
        with self.assertRaises(BootstrapError): parse_receipt(json.dumps(result), self.plan.configuration_sha256)
        for updates in ({'reserved_directory_permits': 1}, {'bound_configuration_sha256': None},
                {'bound_configuration_sha256': self.plan.configuration_sha256}, {'extra': SECRET}):
            with self.assertRaises(BootstrapError) as caught:
                parse_receipt(json.dumps(dict(result, **updates)), self.plan.configuration_sha256, contract=CONTRACT)
            self.assertNotIn(SECRET, str(caught.exception))

    def test_existing_partial_root_is_rejected_before_reading_another_password_frame(self):
        code, _ = self.run_child('crash_directory_captured'); self.assertEqual(code, 77)
        before = self.ledger().snapshot()
        code, result = self.run_child(frame=False, startup_seconds=1, hard_seconds=3)
        self.assertEqual(code, 70); self.assertEqual(result['reason'], 'target_exists')
        self.assertEqual(self.events().count('constructed'), 1)
        self.assertEqual(self.ledger().snapshot(), before)

    def test_late_child_entry_cannot_spend_rounded_t0_lead_on_authentication(self):
        code, result = self.run_child('late_after_prompt')
        self.assertEqual(code, 70); self.assertEqual(result['reason'], 'bootstrap_window_ended')
        self.assertFalse(self.target.exists()); self.assertFalse(self.events())
