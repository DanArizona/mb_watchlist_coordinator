from contextlib import closing
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from mb_tools.secure_config import save_ecfg
from mb_watchlist_coordinator.authenticated_startup import SessionPassword
from mb_watchlist_coordinator.bootstrap_entry import parse_receipt
from mb_watchlist_coordinator.controller_bootstrap import BootstrapError
from test_controller_bootstrap import make_settings, INVENTORY, SECRET


class BootstrapProcessTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.settings = make_settings(self.root)
        self.plan = self.settings.plan()
        self.at = datetime.fromisoformat(self.settings.password_submitted_at_utc)
        self.database = self.root/'synthetic-token-metadata.sqlite3'
        with closing(sqlite3.connect(self.database)) as c, c:
            c.execute('CREATE TABLE schwabdev(access_token_issued TEXT,refresh_token_issued TEXT,expires_in INTEGER)')
            c.execute('INSERT INTO schwabdev VALUES(?,?,?)', (self.at.isoformat(), self.at.isoformat(), 1800))
        save_ecfg(Path(self.settings.ecfg_path), {'SCHWAB_APP_KEY': 'A'*16, 'SCHWAB_APP_SECRET': 'B'*16,
            'SCHWAB_CALLBACK_URL': 'https://synthetic.invalid', 'SCHWAB_TOKENS_DB': str(self.database),
            'SCHWAB_TOKEN_DB_FERNET_KEY': 'synthetic-placeholder'}, SECRET)
        self.configuration = self.root/'public.json'; self.configuration.write_text(json.dumps(asdict(self.settings)))
        self.log = self.root/'sdk-events.txt'
        self.simulation = self.root/'simulation.json'
        self.frame = SessionPassword(SECRET, self.plan.configuration_sha256); self.addCleanup(self.frame.close)
        self.target = Path(self.settings.experiment_root)

    def run_child(self, mode='normal', *, frame=True, inventory=None, **limits):
        private_token = limits.pop('private_token', self.settings.nonce)
        self.simulation.write_text(json.dumps({'mode': mode, 'real_anchor_utc': datetime.now(timezone.utc).isoformat(),
            'logical_anchor_utc': self.at.isoformat(), 'configuration': str(self.configuration),
            'configuration_sha256': self.plan.configuration_sha256,
            'experiment_root': str(self.target), 'opening_proposal': self.settings.opening_proposal,
            'log': str(self.log), 'inventory': INVENTORY if inventory is None else inventory, **limits}))
        child = subprocess.Popen([sys.executable, '-I', '-B', str(Path(__file__).parent/'fixtures/controller_bootstrap_worker.py'), str(self.simulation)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            if frame:
                out, err = child.communicate(self.frame.frame(private_token), timeout=10)
            else:
                child.wait(timeout=5)
                out, err = child.communicate()
        finally:
            if child.poll() is None: child.kill()
            child.communicate()
        self.assertEqual(err, b'')
        self.assertNotIn(SECRET.encode(), out); self.assertNotIn(b'SYNTHETIC-CODE-CANARY-41', out)
        if not out:
            return child.returncode, None
        return child.returncode, parse_receipt(out, self.plan.configuration_sha256)

    def events(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def count_runs(self):
        with closing(sqlite3.connect(self.target/'quotes.sqlite3')) as c:
            return c.execute('SELECT count(*) FROM poll_run').fetchone()[0]

    def test_actual_pinned_config_status_and_factory_create_one_native_run_after_auth(self):
        code, result = self.run_child()
        self.assertEqual(code, 0); self.assertEqual(result['result'], 'PASS')
        self.assertTrue(result['native_run_registered']); self.assertTrue(result['client_close_invoked'])
        self.assertEqual(self.count_runs(), 1); self.assertEqual(self.events(), ['constructed', 'closed'])
        self.assertEqual(result['quote_dispatches_started'], 0); self.assertEqual(result['feed_attempts_started'], 0)
        receipt = json.loads((self.target/'bootstrap.json').read_text())
        self.assertEqual(receipt['status'], 'BOOTSTRAPPED_NOT_RUNNING')
        for p in self.target.rglob('*'):
            if p.is_file(): self.assertNotIn(SECRET.encode(), p.read_bytes())

    def test_wrong_password_creates_no_experiment(self):
        self.frame.close(); self.frame = SessionPassword('synthetic-wrong-password', self.plan.configuration_sha256)
        self.addCleanup(self.frame.close)
        code, result = self.run_child()
        self.assertEqual(code, 70); self.assertEqual(result['result'], 'FAILED')
        self.assertFalse(self.target.exists()); self.assertFalse(self.events())

    def test_dependency_mismatch_is_rejected_before_waiting_for_password(self):
        code, result = self.run_child(frame=False, inventory={'qualified': False}, startup_seconds=1)
        self.assertEqual(code, 70); self.assertEqual(result['reason'], 'dependency_rejected')
        self.assertFalse(self.target.exists()); self.assertFalse(self.events())

    def test_existing_target_is_rejected_without_waiting_for_private_frame(self):
        self.target.mkdir(); (self.target/'retain.txt').write_text('foreign')
        code, result = self.run_child(frame=False, startup_seconds=1)
        self.assertEqual(code, 70); self.assertEqual(result['reason'], 'target_exists')
        self.assertEqual((self.target/'retain.txt').read_text(), 'foreign'); self.assertFalse(self.events())

    def test_wrong_private_token_cannot_authenticate_or_initialize(self):
        code, result = self.run_child(private_token='b'*32)
        self.assertEqual(code, 70); self.assertEqual(result['reason'], 'secret_handoff_invalid')
        self.assertFalse(self.target.exists()); self.assertFalse(self.events())

    def test_authorization_callback_never_registers_initial_run(self):
        code, result = self.run_child('authorization')
        self.assertEqual(code, 70); self.assertEqual(result['reason'], 'authorization_required')
        self.assertFalse(result['native_run_registered']); self.assertFalse(self.target.exists())
        self.assertEqual(self.events(), ['constructed', 'closed'])

    def test_changed_postconstructor_horizon_leaves_no_experiment(self):
        code, result = self.run_child('changed_horizon')
        self.assertEqual(code, 70); self.assertEqual(result['reason'], 'credential_horizon')
        self.assertFalse(self.target.exists()); self.assertEqual(self.events(), ['constructed', 'closed'])

    def test_sdk_exception_does_not_echo_raw_secret_or_create_target(self):
        code, result = self.run_child('constructor_error')
        self.assertEqual(code, 70); self.assertEqual(result['reason'], 'startup_failed')
        self.assertFalse(self.target.exists())

    def test_changed_proposal_after_credential_startup_is_refused(self):
        code, result = self.run_child('changed_input')
        self.assertEqual(code, 70); self.assertEqual(result['reason'], 'inputs_changed')
        self.assertFalse(self.target.exists()); self.assertEqual(self.events(), ['constructed', 'closed'])

    def test_expired_preparation_window_is_refused_before_creation(self):
        code, result = self.run_child('window_expired')
        self.assertEqual(code, 70); self.assertEqual(result['reason'], 'bootstrap_window_ended')
        self.assertFalse(self.target.exists())

    def test_blocked_constructor_has_child_enforced_deadline(self):
        code, result = self.run_child('hung_constructor', startup_seconds=1, hard_seconds=3)
        self.assertEqual(code, 124); self.assertEqual(result['reason'], 'credential_deadline_ended')
        self.assertFalse(self.target.exists())

    def test_missing_private_frame_has_child_enforced_deadline(self):
        code, result = self.run_child(frame=False, startup_seconds=1, hard_seconds=3)
        self.assertEqual(code, 124); self.assertEqual(result['reason'], 'credential_deadline_ended')
        self.assertFalse(self.target.exists()); self.assertFalse(self.events())

    def test_fault_after_auth_before_root_claim_does_not_create_target(self):
        code, result = self.run_child('fault_before_root')
        self.assertEqual(code, 70); self.assertEqual(result['reason'], 'initialization_failed')
        self.assertFalse(self.target.exists()); self.assertEqual(self.events(), ['constructed', 'closed'])

    def test_process_exit_after_claim_preserves_partial_evidence_without_native_run(self):
        code, result = self.run_child('crash_after_root')
        self.assertEqual(code, 77); self.assertIsNone(result)
        before = (self.target/'bootstrap.json').read_bytes()
        self.assertFalse((self.target/'quotes.sqlite3').exists())
        code, result = self.run_child()
        self.assertEqual(code, 70); self.assertEqual(result['reason'], 'target_exists')
        self.assertEqual((self.target/'bootstrap.json').read_bytes(), before)

    def test_postauthentication_block_has_independent_overall_deadline(self):
        code, result = self.run_child('hang_after_root', startup_seconds=3, hard_seconds=4)
        self.assertEqual(code, 124); self.assertEqual(result['reason'], 'bootstrap_deadline_ended')
        self.assertTrue(self.target.exists()); self.assertFalse((self.target/'quotes.sqlite3').exists())

    def test_fault_after_native_registration_is_preserved_and_not_adopted(self):
        code, result = self.run_child('fault_after_run')
        self.assertEqual(code, 70); self.assertTrue(result['native_run_registered'])
        self.assertEqual(self.count_runs(), 1); self.assertTrue((self.target/'bootstrap-failed.json').exists())
        code, result = self.run_child()
        self.assertEqual(code, 70); self.assertEqual(result['reason'], 'target_exists'); self.assertEqual(self.count_runs(), 1)

    def test_client_close_is_also_inside_owned_process_deadline(self):
        code, result = self.run_child('hung_close', startup_seconds=3, hard_seconds=4)
        self.assertEqual(code, 124); self.assertEqual(result['reason'], 'bootstrap_deadline_ended')
        self.assertTrue(result['client_close_invoked']); self.assertTrue(result['native_run_registered'])

    def test_unexpected_child_protocol_fields_or_secret_text_are_not_returned(self):
        code, result = self.run_child(); self.assertEqual(code, 0)
        for raw in (SECRET.encode(), json.dumps(dict(result, extra=SECRET)).encode(),
                json.dumps(dict(result, quote_dispatches_started=1)).encode(),
                json.dumps(dict(result, native_run_registered=False)).encode()):
            with self.assertRaises(BootstrapError) as caught: parse_receipt(raw, self.plan.configuration_sha256)
            self.assertNotIn(SECRET, str(caught.exception))
