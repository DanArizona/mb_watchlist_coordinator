from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from mb_watchlist_coordinator.outer_harness import OuterSchedule,OuterHarness,read_status
from mb_watchlist_coordinator.owned_process_scope import OwnedProcessScope,receive_gate
from mb_watchlist_coordinator.recovery_workers import atomic_json

PROBE=Path(__file__).parent/'fixtures/outer_scope_probe.py'


class OuterHarnessTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup);self.root=Path(t.name)
        self.nonce='a'*32

    def settings(self,remaining=2,bootstrap=False):
        now=datetime.now(timezone.utc)
        if bootstrap:
            submitted=now-timedelta(seconds=60-remaining);start=submitted+timedelta(seconds=60)
        else:start=now-timedelta(seconds=720-remaining);submitted=start-timedelta(seconds=60)
        return OuterSchedule(submitted.isoformat(),start.isoformat(),(start+timedelta(seconds=720)).isoformat())

    def command(self,mode,folder,**extra):
        p=self.root/(mode+'.json');p.write_text(json.dumps({'nonce':self.nonce,'root':str(folder),'mode':mode,**extra}))
        return (sys.executable,'-I','-B',str(PROBE),str(p))

    def run_case(self,mode,remaining=2,report='report',**kwargs):
        folder=self.root/'outer_case'
        h=OuterHarness(folder,self.settings(remaining),self.nonce,entry_mode='manual_resume',
            preparation_submitted_at_utc=datetime.now(timezone.utc).isoformat())
        scenario={k:kwargs.pop(k) for k in ('complete_after',) if k in kwargs}
        return h,h.run(self.command(mode,folder,**scenario),reporter_command=self.command(report,folder) if report else None,**kwargs)

    def test_goal_stops_owned_scope_and_runs_separate_reporter(self):
        h,r=self.run_case('goal')
        self.assertEqual(r['stop_reason'],'profile_goal');self.assertEqual(r['cleanup']['status'],'EXIT_OBSERVED')
        self.assertTrue(r['reporting_complete']);self.assertTrue((h.root/'report-ready.json').is_file())

    def test_blocked_controller_is_preempted_by_original_active_deadline(self):
        began=time.monotonic();h,r=self.run_case('hang',remaining=.8)
        self.assertLess(time.monotonic()-began,3)
        self.assertEqual(r['stop_reason'],'active_deadline_ended');self.assertTrue(r['cleanup']['forced'])
        self.assertEqual(r['cleanup']['status'],'EXIT_OBSERVED')

    def test_bootstrap_deadline_wins_before_T0(self):
        folder=self.root/'outer_case';h=OuterHarness(folder,self.settings(.8,bootstrap=True),self.nonce)
        began=time.monotonic();r=h.run(self.command('bootstrap_hang',folder))
        self.assertLess(time.monotonic()-began,3);self.assertEqual(r['stop_reason'],'bootstrap_deadline_ended')
        self.assertEqual(r['result'],'FAILED')

    def test_normal_descendant_cleanup_leaves_unrelated_child_running(self):
        other=subprocess.Popen([sys.executable,'-I','-B','-c','import time;time.sleep(30)'])
        try:
            h,r=self.run_case('descendant',complete_after=.2)
            self.assertEqual(r['cleanup']['status'],'EXIT_OBSERVED');self.assertIsNone(other.poll())
        finally:other.terminate();other.wait(timeout=2)

    def test_unexpected_controller_exit_cannot_become_pass(self):
        h,r=self.run_case('crash')
        self.assertEqual(r['result'],'FAILED');self.assertEqual(r['stop_reason'],'controller_exited_before_goal')

    def test_wrong_status_binding_is_failure_without_echoing_content(self):
        h,r=self.run_case('bad_status')
        self.assertEqual(r['result'],'FAILED');self.assertNotIn('SYNTHETIC-OUTER-SECRET',h.result_path.read_text())

    def test_operator_stop_has_frozen_early_cleanup_and_no_restart(self):
        h,r=self.run_case('hang',stop_requested=lambda:True)
        self.assertEqual(r['stop_reason'],'operator_stop')
        with self.assertRaises(ValueError):h.run(self.command('goal',h.root))

    def test_secret_handoff_is_ram_only_and_arbitrary_child_output_is_discarded(self):
        frame=bytearray(b'SYNTHETIC-OUTER-SECRET')
        h,r=self.run_case('echo',credential_frame=frame)
        self.assertTrue(r['reporting_complete']);self.assertFalse(any(frame))
        for p in h.root.rglob('*'):
            if p.is_file():self.assertNotIn(b'SYNTHETIC-OUTER-SECRET',p.read_bytes())

    def test_job_assignment_failure_blocks_gate_and_child_work(self):
        # The platform-specific real process test covers the native backend.
        class Refused:
            def assign(self,child):raise OSError('SYNTHETIC-OUTER-SECRET')
            def close(self):pass
        command=self.command('goal',self.root/'outer_never_started')
        with patch('mb_watchlist_coordinator.owned_process_scope.os.name','nt'),patch(
                'mb_watchlist_coordinator.owned_process_scope.WindowsJob',return_value=Refused()):
            scope=OwnedProcessScope(command,self.nonce)
            with self.assertRaises(OSError):scope.launch()
            self.assertFalse(scope.gate_sent);self.assertIsNotNone(scope.child.poll())

    def test_invalid_original_window_or_production_path_is_rejected(self):
        s=self.settings()
        with self.assertRaises(ValueError):OuterSchedule(s.submitted_at_utc,s.start_at_utc,s.start_at_utc).validate()
        with self.assertRaises(ValueError):OuterHarness(self.root/'quote_observation_journal_prod'/'outer_case',s,self.nonce)

    def test_gated_entry_rejects_wrong_nonce_and_oversized_frame(self):
        import io
        for raw in [b'{}\n',b'x'*600]:
            with self.assertRaises(ValueError):receive_gate(io.BytesIO(raw),self.nonce)

    def test_missing_reporter_never_claims_profile_pass(self):
        h,r=self.run_case('goal',report=None)
        self.assertEqual(r['result'],'STOPPED_EVIDENCE_REQUIRED');self.assertFalse(r['reporting_complete'])

    @unittest.skipUnless(os.name=='nt','Actual Windows Job Object orphan containment requires Windows')
    def test_windows_job_contains_orphan_descendant_after_controller_exit(self):
        h,r=self.run_case('orphan')
        self.assertEqual(r['cleanup']['backend'],'windows_job')
        self.assertEqual(r['cleanup']['status'],'EXIT_OBSERVED')
        self.assertTrue(r['cleanup']['scope_empty_observed']);self.assertTrue(r['cleanup']['forced'])
        self.assertEqual(r['result'],'FAILED')

    @unittest.skipUnless(os.name=='nt','Actual Windows kill-on-job-close owner death requires Windows')
    def test_windows_owner_death_releases_its_descendant_lease(self):
        from mb_watchlist_coordinator.sampling_service import owner_lock,ServiceBusy
        root=self.root/'outer_owner_death';root.mkdir()
        c=subprocess.Popen(self.command('owner_death',root),stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        try:c.communicate((json.dumps({'outer_gate':self.nonce},sort_keys=True)+'\n').encode(),timeout=6)
        finally:
            if c.poll() is None:c.kill();c.wait(timeout=2)
        self.assertEqual(c.returncode,79);self.assertTrue((root/'lease-ready').exists())
        until=time.monotonic()+3
        while True:
            try:
                with owner_lock(root/'owned-descendant.lock'):break
            except ServiceBusy:
                if time.monotonic()>=until:self.fail('Owned Job descendant lease remained held after owner death')
                time.sleep(.01)

    def test_reporter_deadline_is_independent_of_controller_completion(self):
        from mb_watchlist_coordinator.outer_deadline import OuterBounds
        folder=self.root/'outer_case'
        h=OuterHarness(folder,self.settings(2),self.nonce,entry_mode='manual_resume',
            preparation_submitted_at_utc=datetime.now(timezone.utc).isoformat())
        # An earlier test-only reporting bound, never a wider production limit.
        h.bounds=OuterBounds(h.bounds.active_end,cleanup_seconds=.3,report_seconds=.25)
        began=time.monotonic();r=h.run(self.command('goal',folder),reporter_command=self.command('report_hang',folder))
        self.assertLess(time.monotonic()-began,2)
        self.assertEqual(r['result'],'INCOMPLETE');self.assertFalse(r['reporting_complete'])

    def test_stop_receipt_write_failure_still_stops_the_owned_child(self):
        original=atomic_json
        def write(path,value):
            if path.name=='STOP.json':raise OSError('synthetic disk failure')
            return original(path,value)
        with patch('mb_watchlist_coordinator.outer_harness.atomic_json',side_effect=write):
            h,r=self.run_case('goal',report=None)
        self.assertFalse(r['stop_receipt_saved']);self.assertEqual(r['result'],'FAILED')
        self.assertEqual(r['cleanup']['status'],'EXIT_OBSERVED')
