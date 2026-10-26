"""Regression coverage for the October 26 Windows live-profile failure."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from mb_watchlist_coordinator.outer_harness import OuterHarness, OuterSchedule
from mb_watchlist_coordinator.recovery_workers import ManagedRecoveryWorker, atomic_json

PROBE = Path(__file__).parent/'fixtures/recovery_probe_worker.py'


class CompactAtomicPathTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name).resolve()
        remaining = 190-len(str(root))-1
        self.assertGreater(remaining, 0, 'Temporary root must permit the recorded 190-character parent')
        self.parent = root/('w'*remaining)
        self.parent.mkdir()
        self.assertEqual(len(str(self.parent)), 190)

    def test_worker_job_and_heartbeat_publish_under_the_recorded_parent_length(self):
        replace = __import__('os').replace
        for suffix in ('.job.json', '.heartbeat.json', '.startup.json', '.auth.json', '.exit.json'):
            with self.subTest(suffix=suffix):
                target = self.parent/('a'*32+suffix)
                legacy = target.with_name(target.name+'.'+'b'*32+'.tmp')
                self.assertGreater(len(str(legacy)), 259)
                seen = []
                def publish(source, destination):
                    seen.append(Path(source))
                    self.assertEqual(Path(source).parent, target.parent)
                    self.assertLessEqual(len(str(source)), 259)
                    self.assertEqual(json.loads(Path(source).read_text()), {'complete': True})
                    return replace(source, destination)
                with patch('mb_watchlist_coordinator.recovery_workers.os.replace', side_effect=publish):
                    atomic_json(target, {'complete': True})
                self.assertEqual(json.loads(target.read_text()), {'complete': True})
                self.assertEqual(len(seen), 1)
                self.assertFalse(list(self.parent.glob('*.tmp')))
        self.qualification_evidence = {
            'parent_characters': 190, 'recorded_legacy_job_temporary_characters': 269,
            'compact_temporary_characters': len(str(seen[0])),
            'native_file_io': True, 'provider_requests': 0,
        }

    def test_legacy_length_guard_reproduces_failure_but_compact_publication_succeeds(self):
        target = self.parent/('a'*32+'.job.json')
        legacy = target.with_name(target.name+'.'+'b'*32+'.tmp')
        original_open = Path.open
        def legacy_open(path, *args, **kwargs):
            if len(str(path)) > 259:
                raise FileNotFoundError(2, 'Synthetic legacy MAX_PATH boundary', str(path))
            return original_open(path, *args, **kwargs)
        with patch.object(Path, 'open', legacy_open):
            with self.assertRaises(FileNotFoundError):
                with legacy.open('x'):
                    pass
            atomic_json(target, {'published': True})
        self.assertEqual(json.loads(target.read_text()), {'published': True})

    def test_managed_worker_registers_progress_and_stops_at_the_recorded_parent_length(self):
        worker = ManagedRecoveryWorker(self.parent, role='experimental_hot',
            command=(sys.executable, '-I', '-B', str(PROBE)), binding={'synthetic_only': True},
            max_starts=3, startup_seconds=3, stale_seconds=3)
        self.addCleanup(worker.stop_owned)
        at = datetime.now(timezone.utc).isoformat()
        started = worker.ensure(start_allowed=True, resume_after_utc=at)
        self.assertEqual(started['status'], 'STARTING')
        until = time.monotonic()+3
        while True:
            ready = worker.ensure(start_allowed=True, resume_after_utc=at)
            if ready['status'] == 'RUNNING':
                break
            if time.monotonic() >= until:
                self.fail('Owned synthetic worker did not publish completed progress within its original 3s gate')
            time.sleep(.02)
        self.assertEqual(ready['pid'], started['pid'])
        job = worker._job()
        self.assertEqual(job['generation'], 1)
        self.assertGreater(datetime.fromisoformat(job['first_eligible_slot_utc']), datetime.fromisoformat(at))
        self.assertEqual(worker.stop_owned()['status'], 'OWNED_WORKER_STOPPED')
        self.assertIsNotNone(worker.last_exit['returncode'])
        self.assertFalse(list(self.parent.glob('*.tmp')))
        self.qualification_evidence = {
            'parent_characters': 190, 'worker_generation': 1,
            'owned_exit_observed': True, 'provider_requests': 0,
        }

    def test_missing_parent_is_still_an_error_and_is_not_created(self):
        target = self.parent/'missing'/'job.json'
        with self.assertRaises(FileNotFoundError):
            atomic_json(target, {'complete': True})
        self.assertFalse(target.parent.exists())


class OuterFailurePrecedenceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.nonce = 'a'*32

    def run_case(self, phase, returncode, *, operator_stop=False, active_ended=False):
        now = datetime.now(timezone.utc)
        start = now-timedelta(seconds=721 if active_ended else 2)
        # Construct inside the frozen window, then advance to the exact end in
        # the active-deadline case. No production limit is widened.
        observed = [start+timedelta(seconds=1) if active_ended else now]
        schedule = OuterSchedule((start-timedelta(seconds=60)).isoformat(),
            start.isoformat(), (start+timedelta(seconds=720)).isoformat())
        harness = OuterHarness(self.root/'outer_case', schedule, self.nonce,
            clock=lambda: observed[0])
        if active_ended:
            observed[0] = start+timedelta(seconds=720)
        class Scope:
            def __init__(self, *args, **kwargs):
                self.closed = False
                self.child = SimpleNamespace(poll=lambda: returncode)
            def launch(self):
                return self
            def open_gate(self):
                pass
            def finish(self, *args, **kwargs):
                self.closed = True
                return {'status': 'EXIT_OBSERVED', 'forced': False,
                    'scope_empty_observed': True, 'controller_returncode': returncode}
        status = {'phase': phase} if phase is not None else None
        with patch('mb_watchlist_coordinator.outer_harness.OwnedProcessScope', Scope), patch(
                'mb_watchlist_coordinator.outer_harness.read_status', return_value=status):
            return harness.run(('synthetic-controller',), stop_requested=lambda: operator_stop)

    def test_failed_controller_after_preparation_retains_controller_failure(self):
        result = self.run_case('FAILED', 70)
        self.assertEqual(result['stop_reason'], 'controller_failed')
        self.assertEqual(result['controller_phase'], 'FAILED')
        self.assertEqual(result['result'], 'FAILED')

    def test_exited_controller_after_preparation_retains_unexpected_exit(self):
        result = self.run_case(None, 77)
        self.assertEqual(result['stop_reason'], 'controller_exited_before_goal')
        self.assertEqual(result['result'], 'FAILED')

    def test_live_unprepared_controller_still_stops_at_original_preparation_bound(self):
        result = self.run_case('BOOTSTRAPPING', None)
        self.assertEqual(result['stop_reason'], 'bootstrap_deadline_ended')
        self.assertEqual(result['result'], 'FAILED')

    def test_operator_stop_keeps_its_existing_precedence(self):
        result = self.run_case('FAILED', 70, operator_stop=True)
        self.assertEqual(result['stop_reason'], 'operator_stop')
        self.assertFalse(result['reporting_complete'])

    def test_original_active_deadline_still_preempts_controller_state(self):
        result = self.run_case('FAILED', 70, active_ended=True)
        self.assertEqual(result['stop_reason'], 'active_deadline_ended')
        self.assertFalse(result['reporting_complete'])
