from contextlib import closing
from datetime import datetime,timezone
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
import unittest

from live_profile_fixtures import config,Clock,SECRET
from mb_watchlist_coordinator.authenticated_startup import SessionPassword
from mb_watchlist_coordinator.outer_harness import OuterHarness,OuterSchedule
from mb_watchlist_coordinator.owned_process_scope import OwnedProcessScope
from mb_watchlist_coordinator.sampling_requests import timestamp

PROBE=Path(__file__).parent/'fixtures/live_profile_probe.py'


class NewEntryProcessTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup);self.root=Path(t.name)
        self.value,self.path,self.sha=config(self.root)
    def command(self,role):return (sys.executable,'-I','-B',str(PROBE),role,str(self.path),self.sha)
    def test_ownership_gate_precedes_credentials_and_any_native_creation(self):
        scope=OwnedProcessScope(self.command('controller'),self.value['nonce']).launch()
        try:
            time.sleep(.15)
            self.assertFalse(Path(self.value['settings']['experiment_root']).exists())
            self.assertFalse((self.root/'stages.json').exists())
        finally:scope.finish(time.monotonic()+3)
    def test_private_pipe_wait_is_independently_bounded_and_records_no_secret(self):
        outer=Path(self.value['outer_root']);outer.mkdir()
        scope=OwnedProcessScope(self.command('credential_hang'),self.value['nonce']).launch()
        try:
            scope.open_gate();scope.child.wait(timeout=4)
            self.assertEqual(scope.child.returncode,124)
            self.assertEqual(json.loads((outer/'entry-failure.json').read_text())['code'],'credential_deadline_ended')
            self.assertFalse(Path(self.value['settings']['experiment_root']).exists())
        finally:scope.finish(time.monotonic()+3)
    def test_fresh_private_credentials_catalog_runtime_native_worker_and_bound_read_only_report(self):
        initial=Clock(self.value['settings']['password_submitted_at_utc'])
        def clock():
            path=self.root/'logical-clock.json'
            if path.exists():
                raw=json.loads(path.read_text())
                return timestamp(raw['logical'])+(datetime.now(timezone.utc)-timestamp(raw['real']))
            return initial()
        plan_settings=self.value['settings'];from mb_watchlist_coordinator.controller_bootstrap import BootstrapSettings
        raw=dict(plan_settings);raw['catalog_symbols']=tuple(raw['catalog_symbols']);plan=BootstrapSettings(**raw).plan()
        harness=OuterHarness(Path(self.value['outer_root']),OuterSchedule(plan_settings['password_submitted_at_utc'],
            plan.public['start_at_utc'],plan.public['stop_at_utc']),self.value['nonce'],clock=clock,
            expected_preflight_sha256=plan.configuration_sha256)
        secret=SessionPassword(SECRET,self.sha);frame=secret.frame(self.value['nonce']);secret.close()
        began=time.monotonic()
        def completed_one():
            if time.monotonic()-began>14:return True
            p=Path(plan_settings['experiment_root'])/'quotes.sqlite3'
            if not p.is_file():return False
            try:
                with closing(sqlite3.connect(p.as_uri()+'?mode=ro',uri=True,timeout=.02)) as c:
                    return c.execute('SELECT count(*) FROM quote_acquisition').fetchone()[0]>=1
            except sqlite3.OperationalError:return False
        result=harness.run(self.command('controller'),reporter_command=self.command('report'),
            credential_frame=frame,stop_requested=completed_one)
        outer=Path(self.value['outer_root']);failure=outer/'entry-failure.json'
        report_path=outer/'native-profile-report.json'
        report=json.loads(report_path.read_text()) if report_path.exists() else {}
        self.failure_evidence={'outer':result,'entry_failure':json.loads(failure.read_text()) if failure.exists() else None,
            'report':report}
        self.assertLess(time.monotonic()-began,20)
        self.assertEqual(result['cleanup']['status'],'EXIT_OBSERVED',self.failure_evidence)
        self.assertTrue(result['reporting_complete'],self.failure_evidence)
        self.assertGreaterEqual(report.get('raw_native_audit',{}).get('table_counts',{}).get('quote_acquisition',0),1,self.failure_evidence)
        self.assertTrue(report['identical_fresh_replays']);self.assertTrue(report['reporting_read_only'])
        self.assertFalse(report['credential_access']);self.assertFalse(report['goals']['goal_complete'])
        self.assertIn(report['result'],('FAILED','INCOMPLETE'))
        self.assertEqual(result['result'],report['result'])
        self.qualification_evidence={'outer':result,'native_report':report,
            'scope':'One synthetic native quote through the new entry; logical source history, elapsed native worker. Not a completed full profile.'}
        stages=json.loads((self.root/'stages.json').read_text())
        self.assertLess(stages.index('credentials_accepted'),stages.index('initial_poll_run_registered'))
        from saved_artifact_scan import scan_saved_artifacts
        scan_saved_artifacts(self.root,(SECRET.encode(),))
