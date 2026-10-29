"""Daily outer lifecycle, real owned scopes and no production resources."""
from datetime import timedelta
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
import unittest
from unittest.mock import patch
from contextlib import closing

import test_daily_controller as daily
from mb_watchlist_coordinator.authenticated_startup import SessionPassword
from mb_watchlist_coordinator.daily_operating import DailyOperatingOwner,inspect_operating_status,request_stop,load_binding
from mb_watchlist_coordinator.daily_operating_worker import ParentFence
from mb_watchlist_coordinator.daily_supervision import read_json,unseal
from mb_watchlist_coordinator.recovery_workers import atomic_json
from mb_watchlist_coordinator.sampling_requests import digest
from mb_watchlist_coordinator.sampling_service import owner_lock


class DailyOperatingTests(unittest.TestCase):
    def setUp(self):
        self.fixture=daily.DailyControllerTests('test_read_only_view_requires_an_explicit_fence')
        if self._testMethodName=='test_complete_collection_proof_preserves_native_journal_and_never_reports_in_the_active_scope':
            self.fixture.proof_directory_override=os.environ.get('MB_DAILY_OPERATING_OWNER_DIR')
        self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.case=self.fixture.case
        self.fixture.scenario.update(mode='normal',target_role='collector')
        self.fixture.scenario_path.write_text(json.dumps(self.fixture.scenario))
        self.case.session.close()
        self.scene=self.case.root/'outer-scene.json'
        self.scene.write_text(json.dumps(self.fixture.scenario))
        entry=str(Path(__file__).parent/'fixtures/daily_operating_process.py')
        self.controller_entry=(sys.executable,'-I','-B',entry,str(self.scene),'controller')
        self.reporter_entry=(sys.executable,'-I','-B',entry,str(self.scene),'report')

    def owner(self,**kwargs):
        return DailyOperatingOwner(self.case.root/'daily_outer_test',self.fixture.config,
            commands=self.fixture.commands,controller_entry=self.controller_entry,
            reporter_entry=self.reporter_entry,clock=self.fixture.clock,activation_approved=True,**kwargs)

    def secret(self):return SessionPassword('SYNTHETIC-PRIVATE-CANARY-62',digest(self.fixture.config.payload()))

    def test_unapproved_launch_is_refused_before_creating_state(self):
        with self.assertRaises(ValueError):
            DailyOperatingOwner(self.case.root/'daily_outer_test',self.fixture.config,
                commands=self.fixture.commands,controller_entry=self.controller_entry,
                reporter_entry=self.reporter_entry,clock=self.fixture.clock)
        self.assertFalse((self.case.root/'daily_outer_test').exists())

    def test_read_only_status_does_not_create_a_missing_outer(self):
        root=self.case.root/'daily_outer_missing'
        self.assertEqual(inspect_operating_status(root)['state'],'UNKNOWN')
        self.assertFalse(root.exists())

    def test_actual_owner_stops_only_its_scope_then_runs_a_fresh_native_report(self):
        owner=self.owner();secret=self.secret();began=time.monotonic()
        other=subprocess.Popen([sys.executable,'-I','-B','-c','import time;time.sleep(30)'])
        try:
            result=owner.run(secret,stop_requested_callback=lambda:time.monotonic()-began>1.5)
            self.assertEqual(result['result'],'STOPPED',result)
            self.assertEqual(result['cleanup']['status'],'EXIT_OBSERVED')
            self.assertEqual(result['reporting']['status'],'COMPLETE',result)
            self.assertTrue(result['reporting']['two_fresh_replays_equal'])
            self.assertIsNone(other.poll())
        finally:
            other.terminate();other.wait(timeout=3)
        self.assertFalse(secret._value)
        self.assertEqual(inspect_operating_status(owner.root)['state'],'STOPPED')
        with owner_lock(self.case.session.lock_path):pass
        with owner_lock(Path(self.fixture.config.publication.state_root)/'driver-owner.lock'):pass
        self.assertEqual(unseal(read_json(Path(self.fixture.config.publication.state_root)/'driver-stop.json'))['reporting']['status'],'NOT_REQUESTED')

    def test_held_controller_is_forced_out_by_the_original_cleanup_budget(self):
        scene=json.loads(self.scene.read_text());scene['controller_hang']=True;self.scene.write_text(json.dumps(scene))
        owner=self.owner();began=time.monotonic()
        result=owner.run(self.secret(),stop_requested_callback=lambda:time.monotonic()-began>1.2)
        self.assertLess(result['cleanup_seconds'],10.5)
        self.assertTrue(result['cleanup']['forced'])
        self.assertIsNotNone(owner.child.poll())

    def test_complete_collection_proof_preserves_native_journal_and_never_reports_in_the_active_scope(self):
        scene=json.loads(self.scene.read_text());scene['admit']=True;self.scene.write_text(json.dumps(scene))
        owner=self.owner();began=time.monotonic()
        def stop():
            if time.monotonic()-began>15:return True
            with closing(sqlite3.connect(self.case.journal)) as c:
                return c.execute('SELECT count(*) FROM quote_acquisition WHERE channel="hot"').fetchone()[0]>=2
        result=owner.run(self.secret(),stop_requested_callback=stop)
        self.assertEqual(result['reporting']['status'],'COMPLETE',result)
        self.assertTrue(result['reporting']['native_audit_passed'],result)
        self.assertTrue(result['reporting']['two_fresh_replays_equal'])
        with closing(sqlite3.connect(self.case.journal)) as c:
            self.assertEqual(c.execute('SELECT count(*) FROM quote_acquisition WHERE channel="hot"').fetchone()[0],2)
            self.assertEqual(c.execute('SELECT count(*) FROM poll_run WHERE run_id IN ("existing-uni","existing-focus")').fetchone()[0],2)

    def test_stop_request_cannot_be_applied_to_a_different_invocation(self):
        owner=self.owner();began=time.monotonic()
        owner.run(self.secret(),stop_requested_callback=lambda:time.monotonic()-began>.8)
        result=request_stop(owner.root)
        self.assertEqual(result['nonce'],load_binding(owner.root)['nonce'])
        value=unseal(read_json(owner.root/'STOP.json'));value['nonce']='0'*32
        from mb_watchlist_coordinator.daily_supervision import sealed
        atomic_json(owner.root/'STOP.json',sealed(value))
        from mb_watchlist_coordinator.daily_operating import stop_requested
        with self.assertRaises(ValueError):stop_requested(owner.root,owner.binding)

    def test_parent_lease_and_freshness_are_required_even_when_saved_files_exist(self):
        from mb_watchlist_coordinator.daily_supervision import sealed
        owner=self.owner();owner.root.mkdir()
        atomic_json(owner.root/'configuration.json',owner.raw)
        atomic_json(owner.root/'operating-binding.json',sealed(owner.binding))
        owner._live('ACTIVE')
        fence=ParentFence(owner.root,owner.binding,self.fixture.clock)
        # Existence of the lock file alone never confers ownership.
        with owner_lock(owner.root/'operating-owner.lock'):
            self.assertTrue(fence.check())
            old=unseal(read_json(owner.root/'operating-live.json'))
            old['observed_at_utc']=(self.fixture.clock()-timedelta(seconds=4)).isoformat()
            atomic_json(owner.root/'operating-live.json',sealed(old))
            with self.assertRaisesRegex(ValueError,'absent or stale'):fence.check()
            self.assertEqual(inspect_operating_status(owner.root,clock=self.fixture.clock)['state'],'STALE_WATCHDOG')
            owner._live('ACTIVE')
        with self.assertRaisesRegex(ValueError,'ownership absent'):fence.check()
        self.assertEqual(inspect_operating_status(owner.root,clock=self.fixture.clock)['state'],'OWNER_LOST')

    def test_detected_stop_keeps_its_original_cleanup_deadline_if_parent_recovers(self):
        fence=ParentFence(self.case.root,{},self.fixture.clock)
        with patch.object(fence,'check',side_effect=(False,True)), \
                patch.object(fence.finished,'wait',return_value=False), \
                patch('mb_watchlist_coordinator.daily_operating_worker.time.monotonic',side_effect=(0.,0.,11.)), \
                patch('mb_watchlist_coordinator.daily_operating_worker.os._exit',side_effect=SystemExit(124)):
            with self.assertRaises(SystemExit):fence.watch()
        self.assertTrue(fence.stop.is_set())

    def test_separately_owned_hung_reporter_is_bounded_and_keeps_saved_cleanup(self):
        owner=self.owner();began=time.monotonic()
        result=owner.run(self.secret(),stop_requested_callback=lambda:time.monotonic()-began>1.5)
        self.assertEqual(result['cleanup']['status'],'EXIT_OBSERVED')
        before=(owner.root/'operating-result.json').read_bytes()
        scene=json.loads(self.scene.read_text());scene['report_hang']=True;self.scene.write_text(json.dumps(scene))
        cutoff=self.fixture.clock()
        # The independently owned reporter may receive the remaining original
        # report budget. This drill supplies a shorter remaining deadline.
        started=time.monotonic()
        report=owner._report(cutoff,time.monotonic()+1.5)
        self.assertEqual(report['status'],'REPORT_INCOMPLETE')
        self.assertTrue(report['cleanup']['forced'])
        self.assertLess(time.monotonic()-started,2.5)
        self.assertEqual((owner.root/'operating-result.json').read_bytes(),before)

    def test_actual_outer_loss_releases_only_its_known_owned_children(self):
        scene=json.loads(self.scene.read_text())
        config=self.case.root/'parent-loss-configuration.json';atomic_json(config,self.fixture.config.payload())
        outer=self.case.root/'daily_outer_parent_loss'
        scene.update(configuration_path=str(config),outer_root=str(outer),commands=self.fixture.commands,
            controller_entry=self.controller_entry,reporter_entry=self.reporter_entry)
        launch=self.case.root/'parent-loss-scene.json';atomic_json(launch,scene)
        entry=str(Path(__file__).parent/'fixtures/daily_outer_owner_process.py')
        parent=subprocess.Popen([sys.executable,'-I','-B',entry,str(launch)],
            stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        handle=None
        try:
            deadline=time.monotonic()+8
            while not (outer/'test-owned-controller.json').exists() and time.monotonic()<deadline:
                self.assertIsNone(parent.poll());time.sleep(.02)
            child=read_json(outer/'test-owned-controller.json')
            self.assertEqual(child['nonce'],load_binding(outer)['nonce'])
            if os.name=='nt':
                import ctypes
                from ctypes import wintypes
                api=ctypes.WinDLL('kernel32',use_last_error=True)
                api.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
                api.OpenProcess.restype=wintypes.HANDLE
                api.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD]
                api.CloseHandle.argtypes=[wintypes.HANDLE]
                handle=api.OpenProcess(0x100000,False,child['pid'])
                self.assertTrue(handle)
            parent.kill();parent.wait(timeout=3)
            deadline=time.monotonic()+12
            while time.monotonic()<deadline:
                if os.name=='nt':
                    if api.WaitForSingleObject(handle,0)==0:break
                elif (outer/'test-owned-controller-finally.json').exists():break
                time.sleep(.02)
            else:self.fail('Known owned controller did not exit after its outer owner was lost')
            for path in (self.case.session.lock_path,Path(self.fixture.config.publication.state_root)/'driver-owner.lock'):
                with owner_lock(path):pass
            self.assertEqual(inspect_operating_status(outer,clock=self.fixture.clock)['state'],'OWNER_LOST')
        finally:
            if handle is not None:api.CloseHandle(handle)
            if parent.poll() is None:
                if (outer/'operating-binding.json').exists():request_stop(outer)
                try:parent.wait(timeout=13)
                except subprocess.TimeoutExpired:parent.kill();parent.wait(timeout=3)


if __name__=='__main__':unittest.main()
