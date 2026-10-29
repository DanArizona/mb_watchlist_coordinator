"""Failure cleanup and fresh reporting at the daily ownership boundary."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import unittest

import test_daily_controller as fixture
from mb_watchlist_coordinator.daily_controller import DailyHotHealth
from mb_watchlist_coordinator.daily_supervision import read_json, sealed, unseal
from mb_watchlist_coordinator.recovery_workers import atomic_json
from mb_watchlist_coordinator.sampling_requests import digest
from mb_watchlist_coordinator.sampling_service import ServiceBusy, owner_lock


class DailyShutdownTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture.DailyControllerTests('test_read_only_view_requires_an_explicit_fence')
        self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)

    def start(self):
        self.fixture.start(); self.fixture.wait(self.fixture.running)
        return self.fixture.controller

    def test_refused_duplicate_close_cannot_stop_or_relabel_the_active_owner(self):
        first = self.start()
        other = self.fixture.make()
        with self.assertRaises(ServiceBusy): other.initialize()
        other.close(report=False)
        self.assertTrue(first.session.validate())
        self.assertIsNone(first.worker.child.poll())
        self.assertFalse((first.root/'driver-stop.json').exists())

    def test_missing_controller_state_does_not_prevent_owned_cleanup_or_reset_the_budget(self):
        owner = self.start()
        hot, identity = owner.worker.child, owner.identity_client.child
        owner.state.path.unlink()
        result = owner.close(report=False)
        self.assertIsNotNone(hot.poll()); self.assertIsNotNone(identity.poll())
        self.assertFalse(owner.state.path.exists())
        self.assertTrue(result['evidence_errors'])
        with owner_lock(owner.root/'driver-owner.lock'): pass
        with owner_lock(owner.session.lock_path): pass

    def test_source_finalization_failure_leaves_other_owned_roles_stopped_and_leases_free(self):
        owner = self.start()
        hot, identity = owner.worker.child, owner.identity_client.child
        with patch.object(owner.source, 'close', side_effect=ValueError('synthetic source receipt fault')):
            result = owner.close(report=False)
        self.assertEqual(result['cleanup']['source']['status'], 'EVIDENCE_INCOMPLETE')
        self.assertIsNotNone(hot.poll()); self.assertIsNotNone(identity.poll())
        with owner_lock(owner.root/'driver-owner.lock'): pass
        with owner_lock(owner.session.lock_path): pass

    def test_prior_report_cannot_satisfy_a_fresh_reporting_invocation(self):
        owner = self.fixture.make()
        self.addCleanup(owner.password.close)
        atomic_json(owner.root/'daily-worker.json', owner.configuration.payload())
        atomic_json(owner.root/'native-final-report.json', sealed({
            'configuration_sha256': owner.identity['configuration_sha256'],
            'native_audit_passed': True, 'two_fresh_replays_equal': True}))
        child = SimpleNamespace(returncode=0, wait=lambda timeout: None)
        with patch('mb_watchlist_coordinator.daily_controller.subprocess.Popen', return_value=child):
            result = owner._final_report()
        self.assertEqual(result['status'], 'REPORT_INCOMPLETE')

    def test_wrong_report_nonce_cannot_be_treated_as_the_current_native_result(self):
        owner = self.fixture.make()
        self.addCleanup(owner.password.close)
        atomic_json(owner.root/'daily-worker.json', owner.configuration.payload())
        def launch(argv, **kwargs):
            job = read_json(Path(argv[-1]))
            atomic_json(Path(job['output']), sealed({'configuration_sha256': job['configuration_sha256'],
                'report_id': '0'*32, 'invocation': job['invocation'], 'audited_at_utc': job['audited_at_utc']}))
            return SimpleNamespace(returncode=0, wait=lambda timeout: None)
        with patch('mb_watchlist_coordinator.daily_controller.subprocess.Popen', side_effect=launch):
            with self.assertRaises(ValueError): owner._final_report()

    def test_hot_warning_resolution_and_recurrence_are_durable(self):
        root = self.fixture.case.session.root
        identity = {'fixture': 'saved-hot-health'}
        health = DailyHotHealth(root, identity, self.fixture.clock)
        report = {'state': 'RUNNING_WITH_SOURCE_GAPS', 'terminal': None, 'worker_starts': 1,
            'source_reconciled': False}
        health.publish(report)
        health.publish({**report, 'state': 'RUNNING', 'source_reconciled': True})
        one = unseal(read_json(root/'hot-incidents.json'))['incidents']['source:gap']
        self.assertIsNotNone(one['resolved_at_utc'])
        DailyHotHealth(root, identity, self.fixture.clock).publish(report)
        two = unseal(read_json(root/'hot-incidents.json'))['incidents']['source:gap']
        self.assertEqual(two['occurrences'], 2)
        self.assertIsNone(two['resolved_at_utc'])

    def test_cleanup_receipt_precedes_reporting_and_survives_a_reporting_error(self):
        owner = self.start()
        hot, identity = owner.worker.child, owner.identity_client.child
        def failed_report():
            receipt = unseal(read_json(owner.root/'driver-stop.json'))
            self.assertEqual(receipt['reporting']['status'], 'PENDING')
            self.assertIsNotNone(hot.poll()); self.assertIsNotNone(identity.poll())
            self.assertFalse(owner.password._value)
            raise ValueError('synthetic malformed native report')
        with patch.object(owner, '_final_report', side_effect=failed_report):
            result = owner.close()
        saved = unseal(read_json(owner.root/'driver-stop.json'))
        self.assertEqual(saved, result)
        self.assertEqual(saved['reporting']['status'], 'REPORT_INCOMPLETE')
        self.assertTrue(saved['cleanup_within_10_seconds'])


if __name__ == '__main__': unittest.main()
