from datetime import timedelta
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from runtime_fixtures import RuntimeFixture, SECRET
from runtime_process_evidence import (FailureEvidenceResult, runtime_failure_evidence,
    subsequent_halt_snapshot)
from mb_watchlist_coordinator.nasdaq_sampling import HaltSnapshot, event_time
from mb_watchlist_coordinator.sampling_requests import digest


class SubsequentObservationTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.f = RuntimeFixture(tmp.name); self.addCleanup(self.f.session.close)
        self.f.now = self.f.start
        baseline = HaltSnapshot('boundary-baseline', self.f.now, 'CURRENT', digest([]), (), {'synthetic_only': True})
        self.f.session.live.record_snapshot(baseline)
        self.baseline = baseline.payload()

    def test_old_ten_millisecond_backdating_can_exclude_a_new_observation(self):
        self.f.now += timedelta(milliseconds=5)
        # Model the old fixture's 10ms subtraction while keeping the accepted
        # producer's actual classification authoritative.
        old_event = self.f.now-timedelta(milliseconds=10)
        from mb_watchlist_coordinator.nasdaq_sampling import ET
        et = old_event.astimezone(ET)
        row = {'symbol': 'NVDA', 'halt_date': et.strftime('%m/%d/%Y'),
            'halt_time': et.strftime('%H:%M:%S.%f'), 'reason_code': 'LUDP'}
        self.f.session.live.record_snapshot(HaltSnapshot('old-backdated-fixture',
            self.f.now, 'CURRENT', digest([row]), (row,), {'synthetic_only': True}))
        state = self.f.session.live.snapshot()
        self.assertEqual(state['outcomes'][-1]['events'][0]['status'], 'predates_startup')
        self.assertFalse(state['commands'])

    def test_five_millisecond_later_observation_queues_without_future_knowledge(self):
        self.f.now += timedelta(milliseconds=5)
        snapshot = subsequent_halt_snapshot(self.baseline, observed_at=self.f.now, capture_id='causal-fixture')
        self.assertEqual(event_time(snapshot.records[0]), snapshot.retrieved_at)
        self.assertGreater(snapshot.retrieved_at, self.f.start)
        self.f.session.live.record_snapshot(snapshot)
        state = self.f.session.live.snapshot()
        self.assertEqual(state['outcomes'][-1]['events'][0]['status'], 'request_queued')
        self.assertEqual(len(state['commands']), 1)

    def test_same_tick_or_earlier_clock_is_refused_instead_of_backdated(self):
        for observed in (self.f.now, self.f.now-timedelta(microseconds=1)):
            with self.subTest(observed=observed), self.assertRaises(ValueError):
                subsequent_halt_snapshot(self.baseline, observed_at=observed, capture_id='refused')
        self.assertEqual(len(self.f.session.live.snapshot()['receipts']), 1)

    def test_one_microsecond_later_clock_keeps_the_baseline_floor(self):
        self.f.now += timedelta(microseconds=1)
        snap = subsequent_halt_snapshot(self.baseline, observed_at=self.f.now, capture_id='next-tick')
        self.f.session.live.record_snapshot(snap)
        self.assertEqual(self.f.session.live.snapshot()['outcomes'][-1]['events'][0]['status'], 'request_queued')


class FailureEvidenceTests(unittest.TestCase):
    def fake(self):
        return SimpleNamespace(id=lambda: 'synthetic.first_native_acquisition',
            phase='first_native_acquisition',
            r=SimpleNamespace(closed=True, last_report={'status': 'STOPPED',
                'reason': 'runtime_blocked_or_stopped', 'detail': SECRET,
                'callback': 'SYNTHETIC-CODE-CANARY-44'}),
            authority_observation={'status': 'BLOCKED', 'detail': SECRET,
                'worker': {'status': 'STARTING', 'exception': SECRET}})

    def test_allowlisted_facts_exclude_arbitrary_exception_and_callback_values(self):
        data = runtime_failure_evidence(self.fake())
        self.assertEqual(data['phase'], 'first_native_acquisition')
        self.assertEqual(data['runtime']['reason'], 'runtime_blocked_or_stopped')
        self.assertEqual(data['authority']['status'], 'BLOCKED')
        text = json.dumps(data)
        self.assertNotIn(SECRET, text); self.assertNotIn('SYNTHETIC-CODE-CANARY-44', text)

    def test_unavailable_source_read_is_reported_without_its_exception_text(self):
        fake = self.fake()
        def broken(): raise ValueError(SECRET)
        fake.f = SimpleNamespace(session=SimpleNamespace(live=SimpleNamespace(snapshot=broken)))
        data = runtime_failure_evidence(fake)
        self.assertEqual(data['source'], {'evidence_available': False})
        self.assertNotIn(SECRET, json.dumps(data))

    def test_reaped_worker_exit_is_retained_without_copying_stderr(self):
        fake = self.fake()
        fake.r.managed = SimpleNamespace(_job=lambda: None, child=None,
            last_exit={'pid': 123, 'returncode': 70, 'stderr_tail': SECRET,
                'observed_at_utc': '2026-10-23T14:00:00+00:00'})
        data = runtime_failure_evidence(fake)
        self.assertEqual(data['worker']['last_exit']['returncode'], 70)
        self.assertNotIn(SECRET, json.dumps(data))

    def test_failure_evidence_is_saved_before_fixture_cleanup_and_does_not_mask_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = self.fake()
            class ExpectedFailure(unittest.TestCase):
                def runTest(case):
                    case.phase = fake.phase; case.r = fake.r
                    case.addCleanup(lambda: setattr(case, 'r', None))
                    case.fail('Expected nested diagnostic proof')
            case = ExpectedFailure()
            result = unittest.TextTestRunner(stream=io.StringIO(), resultclass=lambda *a, **kw:
                FailureEvidenceResult(*a, evidence_root=tmp, **kw)).run(case)
            self.assertEqual(len(result.failures), 1); self.assertFalse(result.wasSuccessful())
            self.assertIsNone(case.r)
            self.assertEqual(len(result.evidence_files), 1)
            saved = json.loads((Path(tmp)/result.evidence_files[0]).read_text())
            self.assertTrue(saved['runtime_created'])
            self.assertEqual(saved['phase'], 'first_native_acquisition')
            self.assertNotIn(SECRET, json.dumps(saved))

    def test_evidence_write_failure_never_relabels_the_original_test_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'blocked'; path.write_text('file')
            class ExpectedFailure(unittest.TestCase):
                def runTest(case):
                    case.phase = 'wait'; case.fail('Expected nested diagnostic proof')
            result = unittest.TextTestRunner(stream=io.StringIO(), resultclass=lambda *a, **kw:
                FailureEvidenceResult(*a, evidence_root=path, **kw)).run(ExpectedFailure())
            self.assertFalse(result.wasSuccessful()); self.assertEqual(len(result.failures), 1)
            self.assertEqual(result.evidence_write_errors, 1)
