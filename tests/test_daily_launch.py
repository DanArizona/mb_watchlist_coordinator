"""Public launch composition checks; synthetic files only, never a vault or API."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
from unittest.mock import patch

import test_daily_session as fixtures
from mb_watchlist_coordinator import daily_launch as launch
from mb_watchlist_coordinator.authenticated_startup import SessionPassword
from mb_watchlist_coordinator.daily_controller import DailyController
from mb_watchlist_coordinator.daily_operating import DailyOperatingOwner
from mb_watchlist_coordinator.daily_supervision import sealed
from mb_watchlist_coordinator.recovery_workers import atomic_json
from mb_watchlist_coordinator.sampling_requests import digest
from mb_watchlist_coordinator.sampling_service import owner_lock, ServiceBusy

DEPENDENCIES = {'qualified': True, 'reason': 'offline_fixture', 'versions': {'schwabdev': '4.5.0'}}
SECRET = 'SYNTHETIC-LAUNCH-PRIVATE-CANARY'


class DailyLaunchTests(unittest.TestCase):
    def setUp(self):
        self.case = fixtures.DailySessionTests('test_preview_reads_published_anchor_and_creates_no_application_state_or_client')
        self.case.setUp(); self.addCleanup(self.case.doCleanups)
        self.source = self.case.root/'packet with spaces'
        coordinator = self.source/'coordinator/src/mb_watchlist_coordinator'
        shutil.copytree(Path(launch.__file__).parent, coordinator, ignore=shutil.ignore_patterns('__pycache__'))
        self.entry = coordinator/'daily_launch_entry.py'
        self.patch = patch.object(launch, '__file__', str(coordinator/'daily_launch.py'))
        self.patch.start(); self.addCleanup(self.patch.stop)
        self.inventory()
        self.outer = self.case.root/'daily_outer_test'

    def inventory(self):
        files = {p.relative_to(self.source).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(self.source.rglob('*')) if p.is_file() and p.name != 'SOURCE_INVENTORY.json'}
        (self.source/'SOURCE_INVENTORY.json').write_text(json.dumps({'files': files}), encoding='utf-8')

    def review(self, **kw):
        args = dict(journal=str(self.case.journal), catalog=str(self.case.root/'catalog'),
            state_root=self.case.settings.state_root, ecfg=str(self.case.root/'unused.ecfg'),
            outer_root=str(self.outer), clock=lambda: self.case.now,
            dependency_reader=lambda _: DEPENDENCIES)
        args.update(kw)
        return launch.build_launch_review(str(self.source), str(self.case.r0), str(self.case.r1), **args)

    def run_review(self, review, **kw):
        args = dict(approved_review_sha256=review['review_sha256'], activation_approved=True,
            clock=lambda: self.case.now, dependency_reader=lambda _: DEPENDENCIES)
        args.update(kw)
        return launch.run_launch(review, **args)

    def test_review_binds_fixed_entries_and_limits_without_credentials_or_application_state(self):
        result = self.review()
        self.assertFalse(Path(self.case.settings.state_root).exists())
        self.assertFalse(self.outer.exists()); self.assertFalse((self.case.root/'unused.ecfg').exists())
        content = dict(result); sha = content.pop('review_sha256')
        self.assertEqual(digest(content), sha)
        for role, command in result['commands'].items():
            self.assertEqual(command[1:3], ['-I', '-B'])
            self.assertEqual(command[3], str(self.entry)); self.assertEqual(command[4], role)
        cfg = result['backend_review']['configuration']
        self.assertEqual(cfg['collector']['max_quote_calls'], 9360)
        self.assertEqual(cfg['collector']['max_symbols'], 1)
        self.assertFalse(result['activation_allowed'])
        self.assertFalse(result['actual_vault_access']); self.assertFalse(result['provider_access'])

    def test_approval_is_required_before_prompt_or_owner_construction(self):
        review = self.review()
        for kw in ({'activation_approved': False}, {'approved_review_sha256': '0'*64}):
            with self.subTest(kw=kw), patch.object(SessionPassword, 'prompt') as prompt, \
                    patch.object(launch, 'DailyOperatingOwner') as owner:
                with self.assertRaises(ValueError): self.run_review(review, **kw)
                prompt.assert_not_called(); owner.assert_not_called()
        self.assertFalse(self.outer.exists())

    def test_changed_source_is_rejected_before_password_prompt(self):
        review = self.review(); self.entry.write_text(self.entry.read_text()+'\n')
        with patch.object(SessionPassword, 'prompt') as prompt:
            with self.assertRaises(ValueError): self.run_review(review)
            prompt.assert_not_called()

    def test_changed_dependencies_are_rejected_before_password_prompt(self):
        review = self.review()
        with patch.object(SessionPassword, 'prompt') as prompt:
            with self.assertRaises(ValueError):
                self.run_review(review, dependency_reader=lambda _: dict(DEPENDENCIES, versions={'schwabdev': '4.6.0'}))
            prompt.assert_not_called()

    def test_changed_proposal_bytes_require_a_new_review_even_with_same_published_content(self):
        review = self.review(); self.case.r1.write_text(self.case.r1.read_text()+'\n')
        with patch.object(SessionPassword, 'prompt') as prompt:
            with self.assertRaises(ValueError): self.run_review(review)
            prompt.assert_not_called()

    def test_changed_catalog_is_rejected_before_password_prompt(self):
        review = self.review()
        path = self.case.root/'catalog/nasdaq.txt'; path.write_bytes(path.read_bytes()+b'changed')
        with patch.object(SessionPassword, 'prompt') as prompt:
            with self.assertRaises(ValueError): self.run_review(review)
            prompt.assert_not_called()

    def test_rehashed_arbitrary_command_is_rejected_by_rebuilding_fixed_entries(self):
        review = self.review(); review['commands']['collector'][3] = '/unreviewed.py'
        content = dict(review); content.pop('review_sha256'); review['review_sha256'] = digest(content)
        with patch.object(SessionPassword, 'prompt') as prompt:
            with self.assertRaises(ValueError): self.run_review(review)
            prompt.assert_not_called()

    def test_expired_original_session_is_refused_before_prompt(self):
        review = self.review()
        with patch.object(SessionPassword, 'prompt') as prompt:
            with self.assertRaises(ValueError):
                self.run_review(review, clock=lambda: self.case.now.replace(hour=16, minute=0))
            prompt.assert_not_called()

    def test_input_change_while_typing_clears_secret_without_starting_an_owner(self):
        review = self.review(); secret = SessionPassword(SECRET, review['configuration_sha256'])
        def prompt(_):
            self.case.r1.write_text(self.case.r1.read_text()+'\n'); return secret
        with patch.object(launch, 'DailyOperatingOwner', wraps=DailyOperatingOwner):
            # The read-only preflight constructs and discards an owner; no run.
            with self.assertRaises(ValueError): self.run_review(review, prompt=prompt)
        self.assertFalse(secret._value); self.assertFalse(self.outer.exists())

    def test_approved_launch_hands_only_private_secret_and_exact_review_to_existing_owner(self):
        review = self.review(); secret = SessionPassword(SECRET, review['configuration_sha256'])
        observed = {}
        class Owner:
            def __init__(self, root, config, **kw):
                self.binding = {}; observed.update(root=root, config=config.payload(), options=kw, binding=self.binding)
            def run(self, password, **kw):
                self_password = bytes(password._value)
                observed['secret_matches'] = self_password == SECRET.encode()
                return {'result': 'STOPPED'}
        self.assertEqual(self.run_review(review, prompt=lambda _: secret, owner_factory=Owner)['result'], 'STOPPED')
        self.assertTrue(observed['secret_matches']); self.assertFalse(secret._value)
        self.assertEqual(observed['binding']['public_launch']['review'], review)
        self.assertTrue(observed['options']['allow_network'])
        self.assertNotIn(SECRET, json.dumps(review))
        self.assertNotIn(SECRET, str(observed['options']))

    def test_owner_failure_also_clears_the_private_secret(self):
        review = self.review(); secret = SessionPassword(SECRET, review['configuration_sha256'])
        class Owner:
            def __init__(self, *a, **k): self.binding = {}
            def run(self, *a, **k): raise RuntimeError('offline failure')
        with self.assertRaises(RuntimeError): self.run_review(review, prompt=lambda _: secret, owner_factory=Owner)
        self.assertFalse(secret._value)

    def test_fresh_mode_refuses_partial_or_existing_state_without_reset(self):
        state = Path(self.case.settings.state_root); state.mkdir(); marker = state/'keep.txt'; marker.write_text('original')
        with self.assertRaises(ValueError): self.review()
        self.assertEqual(marker.read_text(), 'original')

    def test_fresh_mode_refuses_an_unbound_native_hot_run_before_password(self):
        from mb_market_data.quote_observation_store import PollRunProvenance
        from mb_market_data.polling_cadence import RESERVED_HOT_SECONDS
        self.case.store.record_run(PollRunProvenance('old-hot', self.case.now, 'synthetic',
            {'watchlist_kind': 'hot', 'poll_seconds': list(RESERVED_HOT_SECONDS)}))
        with patch.object(SessionPassword, 'prompt') as prompt:
            with self.assertRaises(ValueError): self.review()
            prompt.assert_not_called()
        self.assertFalse(Path(self.case.settings.state_root).exists())

    def resumable(self):
        review = self.review(); config = launch.configuration(review['backend_review']['configuration'])
        commands, controller, reporter = launch.fixed_entries(str(self.source),
            review['source_inventory_sha256'], review['dependency_sha256'], config.publication.state_root)
        self.case.attach()
        secret = SessionPassword(SECRET, review['configuration_sha256']); self.addCleanup(secret.close)
        driver = DailyController(self.case.session, config, commands=commands,
            password=secret, activation_approved=True, clock=lambda: self.case.now)
        root = Path(config.publication.state_root)
        atomic_json(root/'driver-binding.json', driver.identity)
        atomic_json(root/'daily-worker.json', config.payload())
        driver.state.create()
        def initialize(s):
            s.update(initialized=True, active_invocation='a'*32,
                invocations=[{'invocation': 'a'*32}], starts=[{'generation': 1, 'token': 'b'*32,
                    'exit_observed_at_utc': self.case.now.isoformat()}])
        driver.state.change(initialize)
        previous = DailyOperatingOwner(self.outer, config, commands=commands,
            controller_entry=controller, reporter_entry=reporter, activation_approved=True,
            allow_network=True, clock=lambda: self.case.now)
        self.outer.mkdir()
        atomic_json(self.outer/'configuration.json', config.payload())
        atomic_json(self.outer/'operating-binding.json', sealed(previous.binding))
        atomic_json(self.outer/'operating-result.json', sealed({'nonce': previous.binding['nonce'],
            'configuration_sha256': review['configuration_sha256'],
            'cleanup': {'status': 'EXIT_OBSERVED', 'scope_empty_observed': True}}))
        for path in (self.outer/'operating-owner.lock', root/'driver-owner.lock'):
            with owner_lock(path): pass
        self.case.session.close()
        return driver

    def resume_review(self):
        return self.review(outer_root=str(self.case.root/'daily_outer_resume'),
            mode='manual_resume', previous_outer=str(self.outer))

    def test_manual_resume_keeps_fixed_commands_start_charges_and_hold(self):
        driver = self.resumable(); before = driver.state.path.read_bytes()
        result = self.resume_review()
        self.assertEqual(result['commands'], driver.identity['commands'])
        self.assertEqual(result['resume']['charged_worker_starts'], 1)
        self.assertEqual(result['resume']['minimum_replacement_hold_seconds'], 15)
        self.assertFalse(result['resume']['budgets_reset'])
        self.assertEqual(driver.state.path.read_bytes(), before)

    def test_resume_requires_observed_empty_scope(self):
        self.resumable()
        from mb_watchlist_coordinator.daily_supervision import read_json, unseal
        path = self.outer/'operating-result.json'; value = unseal(read_json(path))
        value['cleanup']['scope_empty_observed'] = False; atomic_json(path, sealed(value))
        with self.assertRaises(ValueError): self.resume_review()

    def test_resume_waits_for_previous_outer_reporting_to_release_owner(self):
        self.resumable()
        with owner_lock(self.outer/'operating-owner.lock'):
            with self.assertRaises(ServiceBusy): self.resume_review()

    def test_resume_refuses_exhausted_worker_budget_without_rewriting_history(self):
        driver = self.resumable()
        def exhaust(s):
            s['starts'] += [{'generation': i, 'token': str(i)*32} for i in (2, 3)]
        driver.state.change(exhaust); before = driver.state.path.read_bytes()
        with self.assertRaises(ValueError): self.resume_review()
        self.assertEqual(driver.state.path.read_bytes(), before)

    def test_resume_refuses_missing_original_publication_ledger_before_password(self):
        self.resumable()
        (Path(self.case.settings.state_root)/'identity.sqlite3').unlink()
        with patch.object(SessionPassword, 'prompt') as prompt:
            with self.assertRaises(ValueError): self.resume_review()
            prompt.assert_not_called()

    def test_resume_keeps_a_provider_stop_latched(self):
        self.resumable()
        stop = Path(self.case.journal).with_suffix('.daily-hot-provider-stop.json')
        stop.write_text('{"preserve":"original receipt"}')
        before = stop.read_bytes()
        with self.assertRaises(ValueError): self.resume_review()
        self.assertEqual(stop.read_bytes(), before)

    def test_fixed_entry_rejects_unowned_real_process_before_reading_secret(self):
        review = self.review()
        # A real isolated child with the correct inventory but no owning gate.
        command = review['controller_entry']+[str(self.outer), '0'*32]
        result = subprocess.run(command, input=b'PRIVATE-CANARY-MUST-NOT-BE-PRINTED',
            capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 70)
        self.assertNotIn(b'PRIVATE-CANARY', result.stdout+result.stderr)
        self.assertFalse(self.outer.exists())

    def test_fixed_entry_rejects_unknown_role_and_synthetic_mode(self):
        for role in ('synthetic', 'arbitrary-command'):
            result = subprocess.run([sys.executable, '-I', '-B', str(self.entry), role,
                '0'*64, '0'*64, '/unused', 'unused'], capture_output=True, timeout=5)
            self.assertEqual(result.returncode, 64)

    def bind_owned_review(self):
        review = self.review(); config = launch.configuration(review['backend_review']['configuration'])
        commands, controller, reporter = launch.fixed_entries(str(self.source),
            review['source_inventory_sha256'], review['dependency_sha256'], config.publication.state_root)
        owner = DailyOperatingOwner(self.outer, config, commands=commands, controller_entry=controller,
            reporter_entry=reporter, clock=lambda: self.case.now, allow_network=True, activation_approved=True)
        owner.binding['public_launch'] = {'review': review, 'approved_review_sha256': review['review_sha256'],
            'settings_approved_for_this_invocation': True}
        self.outer.mkdir(); atomic_json(self.outer/'configuration.json', config.payload())
        atomic_json(self.outer/'operating-binding.json', sealed(owner.binding))
        return owner, review

    def test_owned_entry_validates_the_exact_review_and_cannot_rebind_outer(self):
        owner, review = self.bind_owned_review()
        self.assertEqual(launch.validate_owned_launch(self.outer, review['source_inventory_sha256'],
            review['dependency_sha256']), owner.binding)
        changed = dict(owner.binding); changed['public_launch'] = dict(changed['public_launch'],
            approved_review_sha256='0'*64)
        atomic_json(self.outer/'operating-binding.json', sealed(changed))
        with self.assertRaises(ValueError):
            launch.validate_owned_launch(self.outer, review['source_inventory_sha256'], review['dependency_sha256'])

    def test_fixed_controller_dispatch_passes_original_nonce_to_existing_owned_entry(self):
        owner, review = self.bind_owned_review()
        from mb_watchlist_coordinator import daily_launch_entry as entry
        with patch.object(entry, 'SOURCE', self.source), \
                patch('mb_watchlist_coordinator.installed_startup_probe._silence'), \
                patch('mb_watchlist_coordinator.installed_startup_probe.inspect_dependencies', return_value=DEPENDENCIES), \
                patch('mb_watchlist_coordinator.daily_operating_worker.controller_entry') as dispatch:
            code = entry.main(['controller', review['source_inventory_sha256'], review['dependency_sha256'],
                str(self.outer), owner.binding['nonce']])
        self.assertEqual(code, 0)
        dispatch.assert_called_once_with(str(self.outer), owner.binding['nonce'])

    def test_report_dispatch_remains_available_after_dependencies_change_without_provider_access(self):
        owner, review = self.bind_owned_review()
        from mb_watchlist_coordinator import daily_launch_entry as entry
        with patch.object(entry, 'SOURCE', self.source), \
                patch('mb_watchlist_coordinator.installed_startup_probe._silence'), \
                patch('mb_watchlist_coordinator.installed_startup_probe.inspect_dependencies') as dependencies, \
                patch('mb_watchlist_coordinator.daily_operating_worker.reporter_entry') as dispatch:
            code = entry.main(['reporter', review['source_inventory_sha256'], review['dependency_sha256'],
                str(self.outer), owner.binding['nonce'], '/original/report.job.json'])
        self.assertEqual(code, 0); dependencies.assert_not_called()
        dispatch.assert_called_once_with(str(self.outer), owner.binding['nonce'], '/original/report.job.json')

    def test_changed_installed_dependencies_block_fixed_controller_dispatch(self):
        owner, review = self.bind_owned_review()
        from mb_watchlist_coordinator import daily_launch_entry as entry
        with patch.object(entry, 'SOURCE', self.source), \
                patch('mb_watchlist_coordinator.installed_startup_probe._silence'), \
                patch('mb_watchlist_coordinator.installed_startup_probe.inspect_dependencies', return_value={'qualified': False}), \
                patch('mb_watchlist_coordinator.daily_operating_worker.controller_entry') as dispatch:
            code = entry.main(['controller', review['source_inventory_sha256'], review['dependency_sha256'],
                str(self.outer), owner.binding['nonce']])
        self.assertEqual(code, 70); dispatch.assert_not_called()

    def test_fixed_worker_dispatch_reuses_original_configuration_and_job_checks(self):
        self.resumable()
        from mb_watchlist_coordinator import daily_launch_entry as entry
        review = self.resume_review()
        config = str(Path(self.case.settings.state_root)/'daily-worker.json')
        with patch.object(entry, 'SOURCE', self.source), \
                patch('mb_watchlist_coordinator.installed_startup_probe._silence'), \
                patch('mb_watchlist_coordinator.installed_startup_probe.inspect_dependencies', return_value=DEPENDENCIES), \
                patch('mb_watchlist_coordinator.daily_authenticated_worker.run_collector') as dispatch:
            code = entry.main(['collector', review['source_inventory_sha256'], review['dependency_sha256'],
                config, '/original/worker.job.json'])
        self.assertEqual(code, 0)
        dispatch.assert_called_once_with(config, '/original/worker.job.json')

    def test_fixed_worker_dispatch_refuses_rebound_commands(self):
        self.resumable()
        from mb_watchlist_coordinator import daily_launch_entry as entry
        from mb_watchlist_coordinator.daily_supervision import read_json
        review = self.resume_review()
        root = Path(self.case.settings.state_root); value = read_json(root/'driver-binding.json')
        value['commands']['collector'][3] = '/other-entry.py'; atomic_json(root/'driver-binding.json', value)
        with patch.object(entry, 'SOURCE', self.source), \
                patch('mb_watchlist_coordinator.installed_startup_probe._silence'), \
                patch('mb_watchlist_coordinator.installed_startup_probe.inspect_dependencies', return_value=DEPENDENCIES), \
                patch('mb_watchlist_coordinator.daily_authenticated_worker.run_collector') as dispatch:
            code = entry.main(['collector', review['source_inventory_sha256'], review['dependency_sha256'],
                str(root/'daily-worker.json'), '/unused/worker.job.json'])
        self.assertEqual(code, 70); dispatch.assert_not_called()


if __name__ == '__main__': unittest.main()
