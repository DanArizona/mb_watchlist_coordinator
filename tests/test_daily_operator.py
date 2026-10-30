"""Operating delivery paths and commands; small synthetic journals, no SDK."""
from contextlib import closing
from dataclasses import replace
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

import test_daily_launch as fixture
from mb_watchlist_coordinator import daily_operator as operator
from mb_watchlist_coordinator.authenticated_startup import SessionPassword
from mb_watchlist_coordinator.operating_plan import proposed_policy
from mb_watchlist_coordinator.daily_supervision import atomic_json
from mb_watchlist_coordinator.sampling_requests import digest


class OperatorTests(unittest.TestCase):
    def setUp(self):
        self.old = fixture.DailyLaunchTests('test_review_binds_fixed_entries_and_limits_without_credentials_or_application_state')
        self.old.setUp()
        self.addCleanup(self.old.doCleanups)
        self.case, self.source = self.old.case, self.old.source
        self.case.now = self.case.at.replace(hour=9, minute=20)
        output = self.case.root/'output'
        output.mkdir()
        original = self.case.journal.parent
        moved = Path(shutil.move(str(original), str(output/original.name)))
        self.case.journal = moved/self.case.journal.name
        self.case.store.database_path = self.case.journal
        self.case.settings = replace(self.case.settings, journal_path=str(self.case.journal))
        self.runs = self.source/'runs'
        self.runs.mkdir()
        self.day = self.case.at.date().strftime('%Y%m%d')
        self.catalog = self.runs/('daily_catalog_'+self.day)
        shutil.copytree(self.case.root/'catalog', self.catalog)
        self.watchlists = self.case.root/'watchlists'
        self.watchlists.mkdir()
        (self.source/'run.py').write_text('# synthetic delivered entry\n')
        release = {'contract': operator.CONTRACT, 'policy_sha256': digest(proposed_policy()),
            'production_baselines': {'market_data': operator.MARKET_BASE, 'watchlists': operator.WATCHLIST_BASE},
            'dependency_versions': operator.DEPENDENCIES}
        (self.source/'RELEASE.json').write_text(json.dumps(release))
        self.inventory()
        self.dependencies = {'qualified': True, 'reason': 'offline_fixture', 'versions': dict(operator.DEPENDENCIES)}

    def inventory(self):
        path = self.source/'SOURCE_INVENTORY.json'
        value = {'contract': 'daily-hot-operating-release-source-v1',
            'files': {p.relative_to(self.source).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in self.source.rglob('*') if p.is_file() and p != path
                and p.relative_to(self.source).parts[0] != 'runs'}}
        path.write_text(json.dumps(value))

    def repo(self, root):
        return {'root': str(root), 'head': operator.MARKET_BASE if root == self.case.root else operator.WATCHLIST_BASE,
                'branch': 'main', 'tracked_clean': True}

    def qualification(self, source, inventory):
        return {'result': 'PASS', 'windows_checks_passed': True, 'source_inventory_sha256': inventory}

    def options(self):
        return dict(repo_reader=self.repo, qualification_reader=self.qualification,
                    dependency_reader=lambda _: self.dependencies)

    def prepare(self, **changes):
        args = dict(journal=self.case.journal, ecfg=self.case.root/'never-open.ecfg',
            market_data_root=self.case.root, watchlists_root=self.watchlists,
            clock=lambda: self.case.now, **self.options())
        args.update(changes)
        return operator.prepare_day(self.source, self.case.r0, self.case.r1, **args)

    def test_deployment_review_is_read_only_and_requires_exact_clean_baselines(self):
        before = set(self.case.root.rglob('*'))
        result = operator.review_deployment(self.source, self.case.root, self.watchlists, **self.options())
        self.assertEqual(result['result'], 'REVIEW_READY')
        self.assertFalse(result['source_installation_required'])
        self.assertFalse(result['actual_vault_access'])
        self.assertEqual(before, set(self.case.root.rglob('*')))

    def test_wrong_installed_baseline_is_rejected_before_preparation(self):
        def wrong(root): return dict(self.repo(root), head='0'*40)
        with self.assertRaises(ValueError): self.prepare(repo_reader=wrong)
        self.assertFalse(list(self.runs.glob('review_*')))

    def test_dirty_or_non_main_production_is_rejected(self):
        for changed in ({'branch': 'other'}, {'tracked_clean': False}):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                self.prepare(repo_reader=lambda root: dict(self.repo(root), **changed))

    def test_unqualified_windows_marker_cannot_prepare_or_prompt(self):
        def missing(*args): raise ValueError('qualification missing')
        with patch.object(SessionPassword, 'prompt') as prompt:
            with self.assertRaises(ValueError): self.prepare(qualification_reader=missing)
            prompt.assert_not_called()

    def test_changed_dependency_version_is_rejected_before_authentication(self):
        self.dependencies['versions']['schwabdev'] = '4.1.0'
        with self.assertRaises(ValueError): self.prepare()
        self.assertFalse(list(self.runs.glob('review_*')))

    def test_preparation_creates_review_and_commands_only_never_membership_or_runs(self):
        with closing(sqlite3.connect(self.case.journal)) as c:
            before = c.execute('SELECT count(*) FROM sampling_membership_revision').fetchone()[0], c.execute('SELECT count(*) FROM poll_run').fetchone()[0]
        with patch.object(SessionPassword, 'prompt', side_effect=AssertionError('password forbidden')):
            result = self.prepare()
        folder = Path(result['review_path']).parent
        self.assertEqual({p.name for p in folder.iterdir()}, {'launch-review.json', 'operating-summary.json',
            'deployment-review.json', 'START_HOT.cmd', 'STATUS.cmd', 'MEMBERSHIP.cmd', 'STOP_HOT.cmd', 'ROLLBACK_HOT.cmd'})
        self.assertFalse(Path(result['state_root']).exists())
        self.assertFalse(Path(result['outer_root']).exists())
        self.assertFalse((self.case.root/'never-open.ecfg').exists())
        with closing(sqlite3.connect(self.case.journal)) as c:
            self.assertEqual(before, (c.execute('SELECT count(*) FROM sampling_membership_revision').fetchone()[0], c.execute('SELECT count(*) FROM poll_run').fetchone()[0]))

    def test_generated_start_requires_explicit_approval_arguments(self):
        result = self.prepare()
        raw = (Path(result['review_path']).parent/'START_HOT.cmd').read_text()
        self.assertNotIn('--activation-approved', raw)
        self.assertIn('%*', raw)
        self.assertIn('--approved-review-sha256', result['start_command_after_approval'])
        self.assertIn('--activation-approved', result['start_command_after_approval'])

    def test_generated_commands_bind_fixed_python_entry_and_review(self):
        result = self.prepare()
        folder = Path(result['review_path']).parent
        for name in ('START_HOT', 'STOP_HOT', 'ROLLBACK_HOT', 'MEMBERSHIP', 'STATUS'):
            value = (folder/(name+'.cmd')).read_text()
            self.assertIn('"'+str(self.source/'run.py')+'"', value)
            self.assertIn('"'+result['review_path']+'"', value)
            self.assertIn('DisableDelayedExpansion', value)
            self.assertNotIn('git ', value)
            self.assertNotIn('conda ', value)

    def test_new_review_preserves_an_unused_earlier_draft_without_resetting_state(self):
        first = self.prepare()
        original = Path(first['review_path']).read_bytes()
        second = self.prepare()
        self.assertNotEqual(first['review_path'], second['review_path'])
        self.assertEqual(Path(first['review_path']).read_bytes(), original)
        self.assertEqual(first['state_root'], second['state_root'])
        self.assertFalse(Path(second['state_root']).exists())

    def test_existing_controller_state_is_not_reset_by_another_fresh_review(self):
        first = self.prepare()
        state = Path(first['state_root'])
        state.mkdir()
        keep = state/'keep.txt'; keep.write_text('original')
        with self.assertRaises(ValueError): self.prepare()
        self.assertEqual(keep.read_text(), 'original')

    def test_fresh_late_start_is_refused_without_creating_a_review(self):
        self.case.now = self.case.at
        with self.assertRaises(ValueError): self.prepare()
        self.assertFalse(list(self.runs.glob('review_*')))

    def test_journal_must_be_the_reviewed_production_root_daily_journal(self):
        other = self.case.root/'other'/self.case.journal.parent.name
        other.mkdir(parents=True)
        path = other/self.case.journal.name
        shutil.copyfile(self.case.journal, path)
        with self.assertRaises(ValueError): self.prepare(journal=path)

    def test_raw_review_tampering_is_refused_by_status_and_stop(self):
        result = self.prepare()
        path = Path(result['review_path'])
        value = json.loads(path.read_text())
        value['outer_root'] = str(self.source/'runs/daily_outer_other')
        path.write_text(json.dumps(value))
        for read in (operator.day_status, operator.stop_day):
            with self.assertRaises(ValueError): read(self.source, path)

    def test_status_before_start_does_not_create_runtime_roots(self):
        result = self.prepare()
        value = operator.day_status(self.source, result['review_path'])
        self.assertEqual(value['outer']['state'], 'UNKNOWN')
        self.assertFalse(Path(result['outer_root']).exists())
        self.assertFalse(Path(result['state_root']).exists())

    def test_no_approval_means_no_password_or_owner(self):
        result = self.prepare()
        with patch.object(SessionPassword, 'prompt') as prompt:
            with self.assertRaises(ValueError): operator.start_day(self.source, result['review_path'],
                qualification_reader=self.qualification, clock=lambda: self.case.now)
            prompt.assert_not_called()

    def test_original_public_launcher_receives_private_secret_and_exact_review(self):
        result = self.prepare()
        secret = SessionPassword('synthetic-only', json.loads(Path(result['review_path']).read_text())['configuration_sha256'])
        observed = {}
        class Owner:
            def __init__(self, root, config, **kwargs): self.binding = {}; observed['root'] = root
            def run(self, password, **kwargs):
                observed['secret'] = bytes(password._value)
                return {'result': 'STOPPED'}
        value = operator.start_day(self.source, result['review_path'],
            approved_review_sha256=result['approved_review_sha256_required'], activation_approved=True,
            qualification_reader=self.qualification, clock=lambda: self.case.now,
            dependency_reader=lambda _: self.dependencies, prompt=lambda _: secret, owner_factory=Owner)
        self.assertEqual(value['result'], 'STOPPED')
        self.assertEqual(observed['secret'], b'synthetic-only')
        self.assertFalse(secret._value)
        self.assertFalse(Path(result['outer_root']).exists())

    def test_password_entry_cannot_extend_fresh_preopen_window_and_secret_is_cleared(self):
        result = self.prepare()
        review = json.loads(Path(result['review_path']).read_text())
        secret = SessionPassword('synthetic-only', review['configuration_sha256'])
        def prompt(_):
            self.case.now = self.case.at.replace(hour=9, minute=30)
            return secret
        with self.assertRaises(ValueError): operator.start_day(self.source, result['review_path'],
            approved_review_sha256=review['review_sha256'], activation_approved=True,
            qualification_reader=self.qualification, clock=lambda: self.case.now,
            dependency_reader=lambda _: self.dependencies, prompt=prompt)
        self.assertFalse(secret._value)
        self.assertFalse(Path(result['outer_root']).exists())

    def test_cmd_paths_with_expansion_or_control_characters_are_refused(self):
        for value in ('C:\\bad%PATH%\\file', 'C:\\bad!name\\file', 'one&two', 'a|b', 'a\nb', 'a"b', 'x^y'):
            with self.subTest(value=value), self.assertRaises(ValueError): operator.cmdline([value])

    def test_cmd_quoting_preserves_spaces_parentheses_and_trailing_backslashes(self):
        self.assertEqual(operator.cmdline(['C:\\root (one)\\file.py', 'C:\\root\\']),
                         '"C:\\root (one)\\file.py" "C:\\root\\\\"')

    def test_catalog_reservation_is_charged_before_network_and_is_not_retried(self):
        # Use an explicit synthetic weekday; no provider or clock is changed.
        when = datetime(2026, 11, 2, 9, 0, tzinfo=ZoneInfo('America/New_York'))
        calls = []
        def fail(**kwargs): calls.append(kwargs); raise OSError('synthetic')
        for _ in range(2):
            with self.assertRaises((OSError, ValueError)):
                operator.acquire_daily_catalog(self.source, when.date(), clock=lambda: when,
                    acquire=fail, qualification_reader=self.qualification)
        self.assertEqual(len(calls), 1)

    def test_catalog_from_wrong_et_date_is_refused_without_a_network_call(self):
        with self.assertRaises(ValueError): operator.acquire_daily_catalog(self.source, '1999-01-01',
            acquire=lambda **_: self.fail('network forbidden'), qualification_reader=self.qualification)

    def test_opening_universe_above_600_is_refused_before_launch_review(self):
        proposal, sha = operator._proposal(self.case.r1)
        proposal = replace(proposal, uni_symbols=('MSFT', *(f'C{n:05d}' for n in range(600))))
        with patch.object(operator, '_proposal', return_value=(proposal, sha)), \
                patch.object(operator, 'build_launch_review') as build:
            with self.assertRaisesRegex(ValueError, 'capacity'):
                self.prepare()
            build.assert_not_called()

    def test_windows_marker_is_bound_to_the_current_source_inventory(self):
        _, inventory, _ = operator.release_info(self.source)
        value = {'contract': 'daily-hot-operator-offline-qualification-v1', 'result': 'PASS',
                 'windows_checks_passed': True, 'source_inventory_sha256': inventory,
                 'failures': 0, 'errors': 0, 'skipped': 0}
        atomic_json(self.runs/'windows-qualification.json', value)
        self.assertEqual(operator.windows_qualification(self.source, inventory), value)
        with self.assertRaises(ValueError): operator.windows_qualification(self.source, '0'*64)

    def saved_driver(self):
        first = self.prepare()
        self.case.settings = replace(self.case.settings, state_root=first['state_root'])
        self.old.outer = Path(first['outer_root'])
        original_review = self.old.review
        with patch.object(self.old, 'review', side_effect=lambda **kw: original_review(
                catalog=str(self.catalog), ecfg=str(self.case.root/'never-open.ecfg'),
                dependency_reader=lambda _: self.dependencies, **kw)):
            driver = self.old.resumable()
        return first, driver

    def test_real_resume_preflight_preserves_charged_starts_and_configuration(self):
        first, driver = self.saved_driver()
        before = driver.state.path.read_bytes()
        self.case.now = self.case.at
        resumed = operator.prepare_resume(self.source, first['review_path'],
            qualification_reader=self.qualification, dependency_reader=lambda _: self.dependencies,
            clock=lambda: self.case.now)
        value, _ = operator.load_review(self.source, resumed['review_path'])
        self.assertEqual(value['resume']['charged_worker_starts'], 1)
        self.assertEqual(value['resume']['minimum_replacement_hold_seconds'], 15)
        self.assertFalse(value['resume']['budgets_reset'])
        self.assertEqual(value['configuration_sha256'], json.loads(Path(first['review_path']).read_text())['configuration_sha256'])
        self.assertEqual(driver.state.path.read_bytes(), before)

    def test_exhausted_original_worker_budget_cannot_be_reset_by_operator_resume(self):
        first, driver = self.saved_driver()
        def exhaust(value):
            value['starts'] += [{'generation': n, 'token': str(n)*32} for n in (2, 3)]
        driver.state.change(exhaust)
        before = driver.state.path.read_bytes()
        with self.assertRaises(ValueError): operator.prepare_resume(self.source, first['review_path'],
            qualification_reader=self.qualification, dependency_reader=lambda _: self.dependencies,
            clock=lambda: self.case.now)
        self.assertEqual(driver.state.path.read_bytes(), before)

    def test_rollback_requests_only_bound_hot_stop_and_retains_membership(self):
        first, _ = self.saved_driver()
        self.case.now = self.case.at
        self.case.attach(create=False)
        self.case.admit()
        self.case.close()
        before = self.case.store.membership_revisions_in_effective_order()
        result = operator.stop_day(self.source, first['review_path'])
        self.assertEqual(result['status'], 'STOP_REQUESTED')
        self.assertFalse(result['processes_signaled'])
        self.assertEqual(result['unmanaged_channels_untouched'], ['uni', 'focus', 'health'])
        self.assertEqual(before, self.case.store.membership_revisions_in_effective_order())

    def test_monday_est_review_uses_1430_to_2100_utc_without_a_clock_cli_override(self):
        import test_daily_session as session_fixture
        class Sunday(datetime):
            @classmethod
            def now(cls, tz=None):
                value = datetime(2026, 11, 1, 12, tzinfo=ZoneInfo('America/New_York'))
                return value.astimezone(tz) if tz else value.replace(tzinfo=None)
        self.old.doCleanups()
        with patch.object(session_fixture, 'datetime', Sunday):
            self.setUp()
        result = self.prepare()
        self.assertEqual(result['session_date'], '2026-11-02')
        self.assertEqual(result['window_et']['start'], '2026-11-02T09:30:00-05:00')
        self.assertEqual(result['window_utc'], {'start': '2026-11-02T14:30:00+00:00', 'stop': '2026-11-02T21:00:00+00:00'})


if __name__ == '__main__':
    unittest.main()
