"""Human console acknowledgements from synthetic prompts and owned processes."""
from contextlib import redirect_stdout, redirect_stderr
import io
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from mb_watchlist_coordinator.authenticated_startup import (
    PasswordFeedback, SessionPassword, StartupError)
from mb_watchlist_coordinator.daily_operating import inspect_operating_status
import test_daily_operating as operating_fixtures
import test_installed_startup_probe as installed_fixtures
import test_after_hours_profile as after_hours_fixtures
import test_daily_launch as launch_fixtures
import test_live_profile as live_fixtures


ACCEPTED = 'Encrypted configuration accepted.'
SECRET = 'SYNTHETIC-PRIVATE-CANARY-62'


class PasswordFeedbackTests(unittest.TestCase):
    def test_prompt_acknowledges_submission_without_claiming_decryption(self):
        out = io.StringIO()
        with patch('getpass.getpass', return_value=SECRET), redirect_stdout(out):
            secret = SessionPassword.prompt('a'*64)
        self.addCleanup(secret.close)
        self.assertIn('Password received.', out.getvalue())
        self.assertIn('Verifying encrypted configuration', out.getvalue())
        self.assertNotIn(ACCEPTED, out.getvalue())
        self.assertNotIn(SECRET, out.getvalue())

    def test_acceptance_is_flushed_once_and_submission_remains_distinct(self):
        class Console(io.StringIO):
            def __init__(self): super().__init__(); self.flushes = 0
            def flush(self): self.flushes += 1
        out = Console(); feedback = PasswordFeedback(visible=True, stream=out)
        feedback.submitted(); feedback.submitted()
        feedback.accepted(); feedback.accepted(); feedback.finish()
        self.assertEqual(out.getvalue().count('Password received.'), 1)
        self.assertEqual(out.getvalue().count(ACCEPTED), 1)
        self.assertEqual(out.flushes, 2)
        self.assertNotIn('before encrypted configuration acceptance', out.getvalue())

    def test_unconfirmed_startup_does_not_blame_the_password_or_claim_acceptance(self):
        out = io.StringIO(); feedback = PasswordFeedback(visible=True, stream=out)
        feedback.submitted(); feedback.finish(); feedback.finish(); feedback.accepted()
        self.assertIn('Startup ended before encrypted configuration acceptance was confirmed.', out.getvalue())
        self.assertNotIn(ACCEPTED, out.getvalue())
        self.assertNotIn('incorrect', out.getvalue())
        self.assertEqual(len(out.getvalue().splitlines()), 2)

    def test_programmatic_and_child_sessions_remain_silent(self):
        out = io.StringIO()
        with redirect_stdout(out):
            secret = SessionPassword(SECRET, 'a'*64)
            secret.feedback.submitted(); secret.feedback.accepted(); secret.feedback.finish()
            secret.close()
        self.assertEqual(out.getvalue(), '')

    def test_password_and_private_frame_are_not_part_of_console_messages(self):
        out = io.StringIO()
        with patch('getpass.getpass', return_value=SECRET), redirect_stdout(out):
            secret = SessionPassword.prompt('a'*64)
            frame = secret.frame('b'*32)
            secret.feedback.accepted(); secret.close()
        self.assertEqual(json.loads(frame)['password'], SECRET)
        self.assertNotIn(SECRET, out.getvalue())
        self.assertNotIn('b'*32, out.getvalue())
        self.assertNotIn('a'*64, out.getvalue())

    def test_empty_input_reports_entry_failure_without_acceptance(self):
        out = io.StringIO()
        with patch('getpass.getpass', return_value=''), redirect_stdout(out):
            with self.assertRaises(StartupError): SessionPassword.prompt('a'*64)
        self.assertIn('Password entry was not accepted', out.getvalue())
        self.assertNotIn(ACCEPTED, out.getvalue())
        self.assertNotIn('Password received.', out.getvalue())

    def test_unavailable_private_terminal_does_not_echo_or_claim_acceptance(self):
        import getpass
        out, err = io.StringIO(), io.StringIO()
        with patch('getpass.getpass', side_effect=getpass.GetPassWarning(SECRET)), \
                redirect_stdout(out), redirect_stderr(err):
            with self.assertRaises(StartupError): SessionPassword.prompt('a'*64)
        self.assertNotIn(SECRET, out.getvalue()+err.getvalue())
        self.assertNotIn(ACCEPTED, out.getvalue()+err.getvalue())

    def test_cancelled_prompt_remains_cancelled_and_is_visible(self):
        out = io.StringIO()
        with patch('getpass.getpass', side_effect=KeyboardInterrupt), redirect_stdout(out):
            with self.assertRaises(KeyboardInterrupt): SessionPassword.prompt('a'*64)
        self.assertIn('startup did not continue', out.getvalue())
        self.assertNotIn(ACCEPTED, out.getvalue())

    def test_closed_or_broken_console_does_not_interrupt_the_owned_lifecycle(self):
        for failure in (BrokenPipeError, ValueError):
            class Broken:
                def write(self, value): raise failure('Synthetic output unavailable')
                def flush(self): raise failure('Synthetic output unavailable')
            feedback = PasswordFeedback(visible=True, stream=Broken())
            feedback.submitted(); feedback.accepted(); feedback.finish()
            self.assertTrue(feedback.confirmed)

    def test_acceptance_cannot_precede_submission(self):
        out = io.StringIO(); feedback = PasswordFeedback(visible=True, stream=out)
        feedback.accepted()
        self.assertEqual(out.getvalue(), '')
        self.assertFalse(feedback.confirmed)


class OwnedPasswordFeedbackTests(unittest.TestCase):
    def setUp(self):
        self.case = operating_fixtures.DailyOperatingTests('test_unapproved_launch_is_refused_before_creating_state')
        self.case.setUp(); self.addCleanup(self.case.doCleanups)
        self.out = io.StringIO()

    def secret(self, password=SECRET):
        from mb_watchlist_coordinator.sampling_requests import digest
        with patch('getpass.getpass', return_value=password), redirect_stdout(self.out):
            return SessionPassword.prompt(digest(self.case.fixture.config.payload()))

    def run_owner(self, password, *, reject_active=False):
        owner = self.case.owner(); began = time.monotonic()
        if reject_active: owner._driver_fresh = lambda: False
        result = owner.run(password, stop_requested_callback=lambda: time.monotonic()-began >= 2.5)
        self.assertEqual(result['cleanup']['status'], 'EXIT_OBSERVED', result)
        self.assertFalse(password._value)
        self.assertNotIn(SECRET, self.out.getvalue())
        self.assertNotIn('SYNTHETIC-CODE-CANARY', self.out.getvalue())
        return owner, result

    def test_actual_owned_startup_confirms_acceptance_while_the_owner_is_still_active(self):
        secret = self.secret(); owner = self.case.owner(); began = time.monotonic(); observed = []
        def stop():
            if secret.feedback.confirmed and not observed:
                observed.append(inspect_operating_status(owner.root, clock=owner.clock)['state'])
            return bool(observed) or time.monotonic()-began >= 5
        result = owner.run(secret, stop_requested_callback=stop)
        self.assertEqual(result['cleanup']['status'], 'EXIT_OBSERVED', result)
        # The outer's saved phase can trail the child's first ACTIVE receipt by
        # its existing half-second publication interval.
        self.assertTrue(observed, result)
        self.assertIn(observed[0], ('BOOTSTRAPPING', 'ACTIVE'))
        self.assertEqual(self.out.getvalue().count(ACCEPTED), 1)
        self.assertNotIn(SECRET, self.out.getvalue())
        self.assertFalse(secret._value)

    def test_wrong_password_never_prints_acceptance_and_preserves_cleanup(self):
        _, result = self.run_owner(self.secret('SYNTHETIC-WRONG-PASSWORD'))
        self.assertEqual(result['result'], 'FAILED', result)
        self.assertNotIn(ACCEPTED, self.out.getvalue())
        self.assertIn('acceptance was confirmed', self.out.getvalue())

    def test_stale_controller_evidence_does_not_confirm_credentials(self):
        _, result = self.run_owner(self.secret(), reject_active=True)
        self.assertEqual(result['stop_reason'], 'controller_progress_stale', result)
        self.assertNotIn(ACCEPTED, self.out.getvalue())

    def test_authorization_required_never_prints_acceptance(self):
        scene = json.loads(self.case.scene.read_text())
        scene.update(mode='authorization', target_role='identity')
        self.case.scene.write_text(json.dumps(scene))
        role_scene = json.loads(self.case.fixture.scenario_path.read_text())
        role_scene.update(mode='authorization', target_role='identity')
        self.case.fixture.scenario_path.write_text(json.dumps(role_scene))
        _, result = self.run_owner(self.secret())
        self.assertEqual(result['result'], 'FAILED', result)
        self.assertNotIn(ACCEPTED, self.out.getvalue())


class InstalledPasswordFeedbackTests(unittest.TestCase):
    def setUp(self):
        self.case = installed_fixtures.InstalledProbeProcessTests('test_real_entry_uses_one_private_password_frame_and_one_quote_only')
        self.case.setUp(); self.addCleanup(self.case.doCleanups)
        self.out = io.StringIO()

    def prompt(self, binding):
        with patch('getpass.getpass', return_value=installed_fixtures.SECRET), redirect_stdout(self.out):
            return SessionPassword.prompt(binding)

    def test_validated_private_probe_receipt_confirms_acceptance(self):
        result = self.case.run_case(prompt=self.prompt)
        self.assertEqual(result['result'], 'PASS', result)
        self.assertEqual(self.out.getvalue().count(ACCEPTED), 1)
        self.assertNotIn(installed_fixtures.SECRET, self.out.getvalue())

    def test_rejected_private_probe_receipt_has_no_acceptance_message(self):
        result = self.case.run_case('constructor_error', prompt=self.prompt)
        self.assertEqual(result['result'], 'FAILED', result)
        self.assertNotIn(ACCEPTED, self.out.getvalue())
        self.assertIn('Startup ended before', self.out.getvalue())


class PublicLaunchPasswordFeedbackTests(unittest.TestCase):
    def test_changed_inputs_after_submission_report_unconfirmed_and_clear_the_secret(self):
        case = launch_fixtures.DailyLaunchTests('test_review_binds_fixed_entries_and_limits_without_credentials_or_application_state')
        case.setUp(); self.addCleanup(case.doCleanups)
        review = case.review(); out = io.StringIO(); secrets = []
        def prompt(binding):
            with patch('getpass.getpass', return_value=launch_fixtures.SECRET), redirect_stdout(out):
                secret = SessionPassword.prompt(binding)
            secrets.append(secret)
            case.case.r1.write_text(case.case.r1.read_text()+'\n')
            return secret
        with self.assertRaises(ValueError): case.run_review(review, prompt=prompt)
        self.assertFalse(secrets[0]._value)
        self.assertIn('Startup ended before', out.getvalue())
        self.assertNotIn(ACCEPTED, out.getvalue())
        self.assertFalse(case.outer.exists())


class MarketOpenPasswordFeedbackTests(unittest.TestCase):
    def aborted_submission(self, detail):
        # This targets the changed private-prompt wrapper. The old p75
        # preparation fixture has an unrelated historical publication clock;
        # source/window validation itself retains its accepted qualification.
        from mb_watchlist_coordinator import market_open_check as check
        out = io.StringIO(); secrets = []
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        review = {'root': temporary.name,
            'launch_review': {'review_sha256': 'b'*64, 'configuration_sha256': 'a'*64}}
        def prompt(binding):
            with patch('getpass.getpass', return_value=SECRET), redirect_stdout(out):
                secret = SessionPassword.prompt(binding)
            secrets.append(secret); return secret
        def launch(value, **kwargs):
            kwargs['prompt'](value['configuration_sha256'])
            self.fail('Changed or expired review must stop before owner startup')
        with patch.object(check, 'validate_trial_review', side_effect=[None, ValueError(detail)]), \
                patch.object(check, 'run_launch', side_effect=launch):
            with self.assertRaises(ValueError):
                check.run_trial(review, trial_approved=True, market_open_confirmed=True, prompt=prompt)
        self.assertFalse(secrets[0]._value)
        self.assertNotIn(ACCEPTED, out.getvalue())
        self.assertIn('Startup ended before', out.getvalue())
        self.assertNotIn(SECRET, out.getvalue())

    def test_bounded_trial_expiry_during_prompt_is_visible_and_clears_secret(self):
        self.aborted_submission('Synthetic bounded trial expired')

    def test_bounded_trial_input_change_during_prompt_is_visible_and_clears_secret(self):
        self.aborted_submission('Synthetic retained input changed')


class AfterHoursPasswordFeedbackTests(unittest.TestCase):
    def process(self, mode):
        case = after_hours_fixtures.OwnedProcessTests('test_operator_stop_before_first_quote_cleans_only_this_owned_scope')
        case.setUp(); self.addCleanup(case.doCleanups)
        out = io.StringIO(); secrets = []
        def prompted(password, binding):
            with patch('getpass.getpass', return_value=password), redirect_stdout(out):
                secret = SessionPassword.prompt(binding)
            secrets.append(secret)
            return secret
        with patch.object(after_hours_fixtures, 'SessionPassword', side_effect=prompted):
            root, result, report = case.process(mode,
                stop=lambda _: bool(secrets and secrets[0].feedback.confirmed))
        self.assertNotIn(after_hours_fixtures.SECRET, out.getvalue())
        return out.getvalue(), result, report

    def test_actual_off_hours_owned_startup_confirms_acceptance_before_first_quote(self):
        text, result, report = self.process('normal')
        self.assertEqual(text.count(ACCEPTED), 1)
        self.assertEqual(result['stop_reason'], 'operator_stop', result)
        self.assertEqual(report['quote_dispatch_permits'], 0, report)

    def test_off_hours_authorization_rejection_never_prints_acceptance(self):
        text, result, report = self.process('authorization')
        self.assertNotIn(ACCEPTED, text)
        self.assertIn('Startup ended before', text)
        self.assertEqual(report['quote_dispatch_permits'], 0, report)


class LiveProfilePasswordFeedbackTests(unittest.TestCase):
    def invoke(self, phase):
        case = live_fixtures.OperatorParentTests('test_parent_wires_private_frame_two_fixed_roles_and_original_frozen_bounds')
        case.setUp(); self.addCleanup(case.doCleanups)
        out = io.StringIO(); secrets = []
        def prompt(binding):
            with patch('getpass.getpass', return_value=live_fixtures.SECRET), redirect_stdout(out):
                secret = SessionPassword.prompt(binding)
            secrets.append(secret); return secret
        class Harness:
            def __init__(self, root, schedule, nonce, **kw):
                self.root, self.nonce = root, nonce; root.mkdir()
            def run(self, command, **kw):
                from mb_watchlist_coordinator.recovery_workers import atomic_json
                atomic_json(self.root/'controller-status.json', {
                    'contract': 'outer-controller-status-v1', 'nonce': self.nonce, 'phase': phase})
                kw['stop_requested']()
                return {'result': 'INCOMPLETE', 'stop_reason': 'operator_stop'}
        case.invoke(prompt=prompt, harness_factory=Harness)
        self.assertFalse(secrets[0]._value)
        self.assertNotIn(live_fixtures.SECRET, out.getvalue())
        return out.getvalue()

    def test_original_live_profile_parent_relays_bound_active_status_after_secret_clear(self):
        self.assertEqual(self.invoke('ACTIVE').count(ACCEPTED), 1)

    def test_live_profile_bootstrapping_does_not_claim_acceptance(self):
        text = self.invoke('BOOTSTRAPPING')
        self.assertNotIn(ACCEPTED, text)
        self.assertIn('Startup ended before', text)
