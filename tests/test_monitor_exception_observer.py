"""The diagnostic wrapper must preserve both the original failure and cleanup."""
from datetime import datetime,timezone
import errno
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import test_daily_operating as operating
from mb_watchlist_coordinator.daily_controller import DailyController

SOURCE=Path(__file__).resolve().parents[1]/'experiments/daily_hot_source_reliability_20261029/monitor_observer_child.py'
spec=importlib.util.spec_from_file_location('monitor_observer_unit',SOURCE)
observer=importlib.util.module_from_spec(spec);spec.loader.exec_module(observer)
parent_spec=importlib.util.spec_from_file_location('monitor_observer_parent_unit',SOURCE.with_name('observe_monitor.py'))
parent_helper=importlib.util.module_from_spec(parent_spec);parent_spec.loader.exec_module(parent_helper)


class MonitorExceptionObserverTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        self.controller=SimpleNamespace(root=self.root,clock=lambda:datetime.now(timezone.utc),
            invocation='synthetic-invocation',last_live=time.monotonic(),monotonic=time.monotonic,
            worker_report={'status':'RUNNING'},worker=SimpleNamespace(last_heartbeat_check={'status':'valid'}))

    def call(self,function):
        with patch.object(DailyController,'_monitor_once',function):
            observer.install(DailyController)
            return DailyController._monitor_once(self.controller)

    def error(self):
        error=PermissionError(errno.EACCES,'SYNTHETIC-PRIVATE-TEXT',str(self.root/'public-status.json'))
        error.winerror=32
        return error

    def test_original_exception_object_and_single_call_are_preserved(self):
        error=self.error();calls=[]
        def original(controller):calls.append(1);raise error
        with self.assertRaises(PermissionError) as result:self.call(original)
        self.assertIs(result.exception,error);self.assertEqual(calls,[1])
        raw=(self.root/observer.RECEIPT).read_text();value=json.loads(raw)
        self.assertEqual(value['error_type'],'PermissionError');self.assertEqual(value['winerror'],32)
        self.assertNotIn('SYNTHETIC-PRIVATE-TEXT',raw)
        self.assertEqual(value['previous_heartbeat_check'],{'status':'valid'})

    def test_success_return_and_no_receipt_are_preserved(self):
        result=object();self.assertIs(self.call(lambda controller:result),result)
        self.assertFalse((self.root/observer.RECEIPT).exists())

    def test_diagnostic_write_failure_does_not_replace_primary_error(self):
        error=self.error();(self.root/observer.RECEIPT).mkdir()
        def original(controller):raise error
        with self.assertRaises(PermissionError) as result:self.call(original)
        self.assertIs(result.exception,error)

    def test_first_failure_receipt_cannot_be_overwritten(self):
        first=self.error()
        def original(controller):raise first
        with self.assertRaises(PermissionError):self.call(original)
        before=(self.root/observer.RECEIPT).read_bytes()
        def second(controller):raise ValueError('second')
        with self.assertRaises(ValueError):self.call(second)
        self.assertEqual((self.root/observer.RECEIPT).read_bytes(),before)

    def test_underlying_os_code_is_retained_without_exception_text(self):
        cause=self.error()
        def original(controller):
            try:raise cause
            except PermissionError as failure:raise RuntimeError('SYNTHETIC-PRIVATE-TEXT') from failure
        with self.assertRaises(RuntimeError):self.call(original)
        value=json.loads((self.root/observer.RECEIPT).read_text())
        self.assertEqual(value['causes'][0]['winerror'],32)


class ActualObservedControllerTests(unittest.TestCase):
    def setUp(self):
        self.fixture=operating.DailyOperatingTests('test_read_only_status_does_not_create_a_missing_outer')
        self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        parent_helper.setup_observed(self.fixture,lambda instance:None)

    def test_owned_controller_runs_and_cleans_up_without_an_injected_error(self):
        owner=self.fixture.owner();began=time.monotonic()
        result=owner.run(self.fixture.secret(),stop_requested_callback=lambda:time.monotonic()-began>1.5)
        self.assertEqual(result['result'],'STOPPED',result)
        self.assertEqual(result['cleanup']['status'],'EXIT_OBSERVED',result)
        self.assertFalse((Path(self.fixture.fixture.config.publication.state_root)/observer.RECEIPT).exists())

    def test_monitor_fault_is_captured_and_original_terminal_cleanup_still_occurs(self):
        root=self.fixture.case.root;fault=root/'inject-monitor-error.py'
        fault.write_text('''import sys,json,runpy,errno
from pathlib import Path
observer,fixture,scene,*rest=sys.argv[1:]
config=json.loads(Path(scene).read_text())
sys.path[:0]=[str(Path(fixture).resolve().parents[2]/'src'),config['native_src']]
from mb_watchlist_coordinator.daily_controller import DailyController
original=DailyController._monitor_once
def injected(self):
    if self.worker_report.get('status')=='RUNNING':
        error=PermissionError(errno.EACCES,'SYNTHETIC-PRIVATE-TEXT','synthetic-evidence.json')
        error.winerror=32
        raise error
    return original(self)
DailyController._monitor_once=injected
sys.argv=[observer,fixture,scene,*rest]
runpy.run_path(observer,run_name='__main__')
''')
        command=self.fixture.controller_entry
        self.fixture.controller_entry=(*command[:3],str(fault),*command[3:])
        owner=self.fixture.owner();began=time.monotonic()
        result=owner.run(self.fixture.secret(),stop_requested_callback=lambda:time.monotonic()-began>8)
        self.assertEqual(result['result'],'FAILED',result)
        self.assertEqual(result['cleanup']['status'],'EXIT_OBSERVED',result)
        state=Path(self.fixture.fixture.config.publication.state_root)
        raw=(state/observer.RECEIPT).read_text();value=json.loads(raw)
        self.assertEqual(value['error_type'],'PermissionError');self.assertEqual(value['winerror'],32)
        self.assertNotIn('SYNTHETIC-PRIVATE-TEXT',raw)
        self.assertEqual(json.loads((state/'driver-state.json').read_text())['terminal'],'worker_evidence_or_supervision_failed')


if __name__=='__main__':unittest.main()
