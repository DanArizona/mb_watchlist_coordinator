"""Meaningful negative cases for the corrected before-stop qualification."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import unittest

from multisymbol_closed_checks import active_source_at_stop


class ClosedSourceBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.stop = datetime(2026, 10, 31, 14, 5, 19, tzinfo=timezone.utc)
        self.start = self.stop-timedelta(minutes=3)
        self.ready = {'kind': 'status', 'at_utc': (self.stop-timedelta(seconds=1)).isoformat(),
            'status': 'READY_WITH_GAPS', 'discovery_scope_reconciled': True,
            'local_membership_effective': True, 'feed_stop_required': False,
            'pending_window_query_ids': [], 'event_sha256': 'a'*64, 'feed_head_sha256': 'b'*64,
            'reasons': ['intermediate_feed_mutations_not_reconstructible',
                        'older_unknown_carryovers_not_proven_complete']}
        self.stopped = {'kind': 'status', 'at_utc': (self.stop+timedelta(milliseconds=49)).isoformat(),
            'status': 'INCOMPLETE', 'reasons': ['stop_requested']}

    def check(self, *events):
        return active_source_at_stop(list(events), self.stop.isoformat(), started_at=self.start.isoformat())

    def test_ready_then_normal_stop_uses_active_fact_and_preserves_stopped_status(self):
        result = self.check(self.ready, self.stopped)
        self.assertEqual(result['active_status'], 'READY_WITH_GAPS')
        self.assertEqual(result['after_stop_reasons'], ['stop_requested'])
        self.assertEqual(result['age_at_stop_seconds'], 1)

    def test_shutdown_without_a_new_source_report_can_retain_last_active_ready(self):
        self.assertIsNone(self.check(self.ready)['after_stop_status'])

    def test_stop_without_reconciliation_cannot_pass(self):
        with self.assertRaisesRegex(AssertionError, 'No active source'):
            self.check(self.stopped)

    def test_a_later_active_failure_cannot_borrow_an_earlier_ready_status(self):
        bad = dict(self.stopped, at_utc=(self.stop-timedelta(milliseconds=100)).isoformat(),
            status='BLOCKED', reasons=['OperationalError'])
        with self.assertRaisesRegex(AssertionError, 'Latest active source'):
            self.check(self.ready, bad, self.stopped)

    def test_a_stop_reason_before_the_owner_cutoff_is_not_ignored(self):
        early = dict(self.stopped, at_utc=(self.stop-timedelta(milliseconds=10)).isoformat())
        with self.assertRaisesRegex(AssertionError, 'Latest active source'):
            self.check(self.ready, early)

    def test_old_ready_status_cannot_mask_a_stale_source_at_stop(self):
        old = dict(self.ready, at_utc=(self.stop-timedelta(seconds=3)).isoformat())
        with self.assertRaisesRegex(AssertionError, 'stale'):
            self.check(old, self.stopped)

    def test_ready_label_without_both_verified_flags_or_with_pending_work_fails(self):
        for edit in ({'discovery_scope_reconciled': False}, {'local_membership_effective': False},
                     {'pending_window_query_ids': ['CURRENT']}, {'feed_stop_required': True},
                     {'reasons': ['latest_feed_attempt_unavailable']}):
            with self.subTest(edit=edit), self.assertRaisesRegex(AssertionError, 'Latest active source'):
                self.check(dict(self.ready, **edit), self.stopped)

    def test_post_stop_database_or_provider_error_is_not_treated_as_normal_stop(self):
        for status, reason in (('BLOCKED', 'OperationalError'), ('INCOMPLETE', 'latest_feed_attempt_unavailable')):
            bad = dict(self.stopped, status=status, reasons=[reason])
            with self.subTest(reason=reason), self.assertRaisesRegex(AssertionError, 'Unexpected post-stop'):
                self.check(self.ready, bad)

    def test_a_status_outside_the_original_active_invocation_is_insufficient(self):
        old = dict(self.ready, at_utc=(self.start-timedelta(seconds=1)).isoformat())
        with self.assertRaisesRegex(AssertionError, 'No active source'):
            self.check(old, self.stopped)

    def test_qualification_does_not_mutate_the_recorded_statuses(self):
        before = deepcopy((self.ready, self.stopped))
        self.check(self.ready, self.stopped)
        self.assertEqual((self.ready, self.stopped), before)


if __name__ == '__main__':
    unittest.main()
