"""Off-hours limits/ownership/native measurements. No real credentials or API."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

from mb_watchlist_coordinator import after_hours_profile as profile
from mb_watchlist_coordinator.authenticated_startup import SessionPassword, StartupError
from mb_watchlist_coordinator.daily_supervision import read_json, sealed, unseal
from mb_watchlist_coordinator.recovery_workers import atomic_json

DEPENDENCIES = {'qualified': True, 'reason': 'synthetic_offline'}
SECRET = 'SYNTHETIC-OFF-HOURS-SECRET'


class WindowTests(unittest.TestCase):
    def test_weekday_regular_interval_and_crossing_open_are_excluded(self):
        for h, m in ((9, 29), (9, 30), (12, 0), (15, 59)):
            at = datetime(2026, 10, 29, h, m, tzinfo=profile.ET)
            with self.assertRaises(ValueError): profile.closed_window(at, at+timedelta(seconds=120))
        at = datetime(2026, 10, 29, 16, tzinfo=profile.ET)
        profile.closed_window(at, at+timedelta(seconds=120))

    def test_weekends_are_allowed_but_cross_date_and_extended_windows_are_refused(self):
        at = datetime(2026, 10, 31, 12, tzinfo=profile.ET)
        profile.closed_window(at, at+timedelta(seconds=120))
        for start, end in ((at, at+timedelta(seconds=121)), (at.replace(hour=23, minute=59), at+timedelta(days=1))):
            with self.assertRaises(ValueError): profile.closed_window(start, end)

    def test_statistics_report_sample_count_and_nearest_rank(self):
        self.assertIsNone(profile.stats([]))
        result = profile.stats(list(range(1, 25)))
        self.assertEqual(result['count'], 24); self.assertEqual(result['median'], 12.5)
        self.assertEqual(result['p95_nearest_rank'], 23)


class ProfileFixture(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup); self.temp = Path(temp.name)
        self.source = self.temp/'source with spaces'
        code = self.source/'coordinator/src/mb_watchlist_coordinator'; code.mkdir(parents=True)
        original = Path(profile.__file__).parent
        for name in ('after_hours_profile.py', 'after_hours_entry.py'):
            shutil.copyfile(original/name, code/name)
        files = {p.relative_to(self.source).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in self.source.rglob('*') if p.is_file()}
        (self.source/'SOURCE_INVENTORY.json').write_text(json.dumps({'files': files}))
        patched = patch.object(profile, '__file__', str(code/'after_hours_profile.py'))
        patched.start(); self.addCleanup(patched.stop)
        self.at = datetime(2026, 10, 29, 21, tzinfo=profile.ET)
        self.ecfg = str(self.temp/'unused.ecfg')

    def review(self):
        return profile.build_review(str(self.source), self.ecfg, clock=lambda: self.at,
            dependency_reader=lambda _: DEPENDENCIES)


class ReviewTests(ProfileFixture):
    def test_review_has_fixed_limits_no_production_paths_and_creates_no_runtime_state(self):
        review = self.review()
        self.assertEqual(review['limits']['maximum_quote_requests'], 24)
        self.assertEqual(review['limits']['active_seconds'], 120)
        self.assertEqual(review['limits']['symbol'], 'SPY')
        self.assertFalse((self.source/'runs').exists()); self.assertFalse(Path(self.ecfg).exists())
        self.assertFalse(review['production_hot_enabled']); self.assertFalse(review['daily_launcher_changed'])

    def test_unapproved_trial_does_not_prompt_or_create_state(self):
        with patch.object(SessionPassword, 'prompt') as prompt:
            with self.assertRaises(ValueError): profile.run_profile(self.review())
            prompt.assert_not_called()
        self.assertFalse((self.source/'runs').exists())

    def test_limits_cannot_be_extended_even_with_recomputed_digest(self):
        review = self.review(); review['limits']['maximum_quote_requests'] = 25
        value = dict(review); value.pop('review_sha256'); review['review_sha256'] = profile.digest(value)
        with self.assertRaises(ValueError):
            profile.validate_review(review, clock=lambda: self.at, dependency_reader=lambda _: DEPENDENCIES)

    def test_changed_source_and_dependencies_block_before_credentials(self):
        review = self.review()
        with self.assertRaises(ValueError):
            profile.validate_review(review, clock=lambda: self.at, dependency_reader=lambda _: {'qualified': False})
        (self.source/'coordinator/src/mb_watchlist_coordinator/after_hours_entry.py').write_text('changed')
        with self.assertRaises(ValueError):
            profile.validate_review(review, clock=lambda: self.at, dependency_reader=lambda _: DEPENDENCIES)

    def test_clock_gate_is_rechecked_after_typing_and_secret_is_cleared(self):
        review = self.review(); secret = SessionPassword(SECRET, review['review_sha256']); at = [self.at]
        def prompt(_): at[0] = self.at.replace(hour=10); return secret
        with self.assertRaises(ValueError):
            profile.run_profile(review, trial_approved=True, market_closed_confirmed=True,
                clock=lambda: at[0], prompt=prompt, dependency_reader=lambda _: DEPENDENCIES)
        self.assertFalse(secret._value); self.assertFalse((self.source/'runs').exists())

    def test_existing_root_is_never_reused_or_reset(self):
        review = self.review(); root = Path(review['root']); root.mkdir(parents=True)
        marker = root/'original'; marker.write_text('retain')
        with self.assertRaises(ValueError):
            profile.validate_review(review, clock=lambda: self.at, dependency_reader=lambda _: DEPENDENCIES)
        self.assertEqual(marker.read_text(), 'retain')


class DispatchTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup); self.root = Path(temp.name)
        self.now = datetime.now(timezone.utc)
        self.config = {'nonce': 'a'*32, 'stop_at_utc': (self.now+timedelta(seconds=120)).isoformat()}
        atomic_json(self.root/'quote-permits.json', sealed({'nonce': 'a'*32, 'count': 0}))
        self.calls = 0
        test = self
        class Client:
            halt_reason = None
            def quotes(self, symbols, *, fields):
                test.calls += 1
                return profile.CachedResponse(200, {'SPY': {'symbol': 'SPY', 'quote': {'lastPrice': 12.3}}})
        self.client = profile.MeasuredClient(Client(), self.root, self.config,
            SimpleNamespace(fence=lambda: True), lambda: self.now)

    def test_one_symbol_and_fields_are_enforced_before_permit_or_provider(self):
        for symbols, fields in ((['MSFT'], 'all'), (['SPY', 'MSFT'], 'all'), (['SPY'], 'quote')):
            with self.assertRaises(ValueError): self.client.quotes(symbols, fields=fields)
        self.assertEqual(self.calls, 0); self.assertEqual(unseal(read_json(self.root/'quote-permits.json'))['count'], 0)

    def test_twenty_fourth_dispatch_is_allowed_and_twenty_fifth_is_refused(self):
        for _ in range(24): self.client.quotes(['SPY'], fields='all')
        with self.assertRaises(ValueError): self.client.quotes(['SPY'], fields='all')
        self.assertEqual(self.calls, 24); self.assertEqual(len(self.client.measurements), 24)

    def test_transport_failure_is_redacted_charged_and_latched_without_retry(self):
        with patch.object(self.client.client, 'quotes', side_effect=RuntimeError(SECRET)) as call:
            with self.assertRaises(StartupError): self.client.quotes(['SPY'], fields='all')
            with self.assertRaises(ValueError): self.client.quotes(['SPY'], fields='all')
            self.assertEqual(call.call_count, 1)
        self.assertEqual(unseal(read_json(self.root/'quote-permits.json'))['count'], 1)
        self.assertNotIn(SECRET, (self.root/'provider-measurements.json').read_text())

    def test_429_stops_before_a_second_provider_dispatch(self):
        self.client.client.quotes = lambda *a, **k: profile.CachedResponse(429, {})
        self.client.quotes(['SPY'], fields='all')
        with self.assertRaises(ValueError): self.client.quotes(['SPY'], fields='all')
        self.assertEqual(self.client.measurements[0]['http_status'], 429)

    def test_rewritten_permit_count_cannot_reset_the_budget(self):
        self.client.quotes(['SPY'], fields='all')
        atomic_json(self.root/'quote-permits.json', sealed({'nonce': 'a'*32, 'count': 0}))
        with self.assertRaises(ValueError): self.client.quotes(['SPY'], fields='all')
        self.assertEqual(self.calls, 1)


class OwnedProcessTests(ProfileFixture):
    def process(self, mode='normal', stop=lambda root: False):
        real = datetime.now(timezone.utc); logical = self.at
        clock = lambda: logical+(datetime.now(timezone.utc)-real)
        review = profile.build_review(str(self.source), self.ecfg, clock=clock,
            dependency_reader=lambda _: DEPENDENCIES)
        import mb_market_data
        scene = self.temp/'scene.json'
        scene.write_text(json.dumps({'real_anchor': real.isoformat(), 'logical_anchor': logical.isoformat(),
            'mode': mode, 'native_src': str(Path(mb_market_data.__file__).resolve().parents[1]),
            'events': str(self.temp/'events.log')}))
        entry = str(Path(__file__).parent/'fixtures/after_hours_process.py')
        secret = SessionPassword(SECRET, review['review_sha256'])
        root, result = profile.run_profile(review, trial_approved=True, market_closed_confirmed=True,
            clock=clock, prompt=lambda _: secret, dependency_reader=lambda _: DEPENDENCIES,
            command_factory=lambda role: (sys.executable, '-I', '-B', entry, str(scene), role),
            stop_callback=lambda: stop(Path(review['root'])))
        self.assertFalse(secret._value)
        for p in root.rglob('*'):
            if p.is_file(): self.assertNotIn(SECRET.encode(), p.read_bytes())
        self.assertEqual(result['cleanup']['status'], 'EXIT_OBSERVED', result)
        self.assertTrue(result['cleanup']['scope_empty_observed']); self.assertLess(result['cleanup_seconds'], 10.5)
        self.assertEqual(result['reporting']['status'], 'COMPLETE', result)
        report = unseal(read_json(root/'performance-report.json'))
        self.assertFalse(report['production_hot_enabled']); self.assertFalse(report['daily_live_launch_qualified'])
        return root, result, report

    def events(self):
        p = self.temp/'events.log'; return p.read_text().splitlines() if p.exists() else []

    def test_complete_actual_paced_native_profile_uses_twenty_four_synthetic_quotes(self):
        root, result, report = self.process()
        proof = __import__('os').environ.get('MB_AFTER_HOURS_PROOF')
        if proof:
            out = Path(proof); out.mkdir(parents=True, exist_ok=False)
            shutil.copytree(root, out/'closed-state')
            (out/'proof.json').write_text(json.dumps(report, indent=2)+'\n')
        self.assertEqual(report['result'], 'PASS', report)
        self.assertEqual(report['quote_dispatch_permits'], 24)
        self.assertEqual(self.events().count('quote'), 24)
        self.assertEqual(report['request_seconds']['count'], 24)
        self.assertTrue(report['native_audit_passed']); self.assertTrue(report['two_fresh_replays_equal'])
        self.assertEqual(report['first_replay']['events'], 25)
        self.assertFalse(report['actual_provider_used']); self.assertTrue(report['worker']['synthetic_only'])

    def test_rate_limit_is_one_recorded_request_and_no_retry(self):
        _, _, report = self.process('rate_limit')
        self.assertEqual(report['result'], 'FAILED'); self.assertEqual(self.events().count('quote'), 1)
        self.assertEqual(report['quote_dispatch_permits'], 1)

    def test_authorization_callback_prevents_all_quotes(self):
        _, _, report = self.process('authorization')
        self.assertEqual(report['result'], 'FAILED'); self.assertNotIn('quote', self.events())
        self.assertEqual(report['quote_dispatch_permits'], 0)

    def test_hung_request_preserves_one_unknown_charged_outcome_and_cleans_up(self):
        _, _, report = self.process('quote_hang')
        self.assertEqual(report['result'], 'FAILED'); self.assertEqual(self.events().count('quote'), 1)
        self.assertEqual(report['quote_dispatch_permits'], 1); self.assertEqual(report['unknown_provider_outcomes'], 1)

    def test_operator_stop_before_first_quote_cleans_only_this_owned_scope(self):
        def stop(root):
            path = root/'worker-status.json'
            return path.exists() and unseal(read_json(path))['phase'] == 'ACTIVE'
        _, result, report = self.process(stop=stop)
        self.assertEqual(result['stop_reason'], 'operator_stop')
        self.assertEqual(report['quote_dispatch_permits'], 0)


if __name__ == '__main__': unittest.main()
