"""Meaningful negative cases for the corrected before-stop qualification."""
from copy import deepcopy
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
import tempfile
import traceback
from types import SimpleNamespace
import unittest

from multisymbol_closed_checks import (active_source_at_stop, checked_read,
    classify_role_events, fingerprint_changes, retained_fingerprints)


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


class IdentityStopClassificationTests(unittest.TestCase):
    def setUp(self):
        self.stop = datetime(2026, 10, 31, 14, 5, 19, 29114, tzinfo=timezone.utc)
        self.owner = {'result': 'STOPPED', 'stop_reason': 'operator_stop', 'failure_type': None,
            'acquisition_stop_requested_at_utc': self.stop.isoformat(), 'cleanup_seconds': .156,
            'cleanup': {'status': 'EXIT_OBSERVED', 'scope_empty_observed': True}}
        self.closed = {'role': 'identity', 'event': 'closed',
            'at': (self.stop+timedelta(seconds=.072810)).isoformat()}
        self.failed = {'role': 'identity', 'event': 'failed', 'error_type': 'ValueError',
            'frames': ['<module>', 'run_identity', '_run_identity', 'fence'],
            'at': (self.stop+timedelta(seconds=.074320)).isoformat()}

    def check(self, events=None, *, verified=True):
        return classify_role_events(events if events is not None else [self.closed, self.failed],
            self.owner, identity_stop_verified=verified)

    def test_exact_post_stop_identity_exception_is_reported_as_expected_shutdown(self):
        result = self.check()
        self.assertEqual(len(result), 1)
        self.assertAlmostEqual(result[0]['seconds_after_stop'], .074320)
        self.assertEqual(result[0]['qualification_classification'], 'explicit_identity_stop_after_owner_stop')

    def test_inline_runtime_stop_branch_raises_value_error_directly_in_fence(self):
        from mb_watchlist_coordinator.daily_authenticated_worker import _Lifetime
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'identity.stop'; path.write_text('synthetic-token')
            config = SimpleNamespace(publication=SimpleNamespace(state_root=tmp))
            lifetime = _Lifetime(config, {}, token='synthetic-token', invocation='synthetic-invocation',
                stop_path=path, clock=lambda: self.stop, identity=True)
            try: lifetime.fence()
            except ValueError as error:
                self.assertEqual(str(error), 'Daily process stop requested')
                self.assertEqual(traceback.extract_tb(error.__traceback__)[-1].name, 'fence')
            else: self.fail('Explicit identity stop must fence the process')

    def test_failure_before_stop_or_after_cleanup_is_not_accepted(self):
        for at in (self.stop-timedelta(microseconds=1), self.stop+timedelta(seconds=.2)):
            with self.subTest(at=at), self.assertRaisesRegex(AssertionError, 'Unexpected synthetic role'):
                self.check([self.closed, dict(self.failed, at=at.isoformat())])

    def test_other_role_error_type_or_deeper_fence_failure_is_not_accepted(self):
        for edit in ({'role': 'collector'}, {'error_type': 'PermissionError'},
                     {'frames': self.failed['frames']+['assert_controller_fence']}):
            with self.subTest(edit=edit), self.assertRaisesRegex(AssertionError, 'Unexpected synthetic role'):
                self.check([self.closed, dict(self.failed, **edit)])

    def test_unverified_stop_or_missing_client_close_is_not_accepted(self):
        with self.assertRaisesRegex(AssertionError, 'Unexpected synthetic role'):
            self.check(verified=False)
        with self.assertRaisesRegex(AssertionError, 'Unexpected synthetic role'):
            self.check([self.failed])

    def test_multiple_failures_or_dispatch_after_stop_remain_blocking(self):
        with self.assertRaisesRegex(AssertionError, 'Multiple synthetic role'):
            self.check([self.closed, self.failed, dict(self.failed)])
        with self.assertRaisesRegex(AssertionError, 'Provider dispatch recorded after'):
            self.check([{'role': 'collector', 'event': 'quote', 'at': self.failed['at']}])

    def test_failed_owner_cannot_reclassify_a_role_error(self):
        self.owner['result'] = 'FAILED'
        with self.assertRaisesRegex(AssertionError, 'Unexpected synthetic role'):
            self.check()


class DurableEvidenceChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.db = self.root/'journal.sqlite3'
        with closing(sqlite3.connect(self.db)) as connection, connection:
            connection.execute('CREATE TABLE retained (value TEXT)')
            connection.execute('INSERT INTO retained VALUES ("original")')
        self.wal = self.db.with_name(self.db.name+'-wal')
        self.shm = self.db.with_name(self.db.name+'-shm')

    def test_absent_and_empty_sqlite_wal_are_equivalent_without_db_change(self):
        before = retained_fingerprints(self.root)
        self.wal.write_bytes(b''); self.shm.write_bytes(b'shared coordination')
        self.assertEqual(retained_fingerprints(self.root), before)
        self.wal.unlink(); self.shm.unlink()
        self.assertEqual(retained_fingerprints(self.root), before)

    def test_new_nonempty_wal_is_recorded_by_name_and_blocks(self):
        before = retained_fingerprints(self.root)
        self.wal.write_bytes(b'nonempty retained WAL bytes')
        delta = fingerprint_changes(before, retained_fingerprints(self.root))
        self.assertEqual([(d['path'], d['change']) for d in delta], [('journal.sqlite3-wal', 'added')])

    def test_truncating_or_removing_nonempty_wal_is_not_ignored(self):
        self.wal.write_bytes(b'retained WAL bytes')
        before = retained_fingerprints(self.root)
        self.wal.write_bytes(b'')
        self.assertTrue(fingerprint_changes(before, retained_fingerprints(self.root)))
        self.wal.unlink()
        self.assertTrue(fingerprint_changes(before, retained_fingerprints(self.root)))

    def test_database_or_ordinary_file_change_is_not_ignored(self):
        ordinary = self.root/'status.json'; ordinary.write_text('original')
        before = retained_fingerprints(self.root)
        ordinary.write_text('changed')
        with closing(sqlite3.connect(self.db)) as connection, connection:
            connection.execute('UPDATE retained SET value="changed"')
        delta = fingerprint_changes(before, retained_fingerprints(self.root))
        self.assertEqual({d['path'] for d in delta}, {'journal.sqlite3', 'status.json'})

    def test_sidecar_named_file_without_a_real_sqlite_database_stays_protected(self):
        ordinary = self.root/'not-a-database'; ordinary.write_text('ordinary bytes')
        named = self.root/'not-a-database-wal'; named.write_bytes(b'')
        before = retained_fingerprints(self.root); named.unlink()
        self.assertEqual(fingerprint_changes(before, retained_fingerprints(self.root))[0]['path'], named.name)

    def test_preservation_failure_keeps_primary_exception_and_names_changed_file(self):
        path = self.root/'status.json'; path.write_text('original')
        def failed_read():
            path.write_text('changed')
            raise ValueError('primary source failure')
        with self.assertRaisesRegex(ValueError, 'primary source failure') as caught:
            checked_read(self.root, failed_read)
        self.assertEqual(caught.exception.closed_evidence_changes[0]['path'], 'status.json')
        self.assertTrue(caught.exception.__notes__)

    def test_successful_read_cannot_hide_a_durable_write(self):
        def changed_read():
            (self.root/'status.json').write_text('new')
            return {'result': 'PASS'}
        with self.assertRaisesRegex(AssertionError, 'Durable closed evidence changed'):
            checked_read(self.root, changed_read)


if __name__ == '__main__': unittest.main()
