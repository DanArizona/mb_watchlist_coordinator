"""Daily outer lifecycle, real owned scopes and no production resources."""
from datetime import timedelta
import json
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


if __name__=='__main__':unittest.main()
