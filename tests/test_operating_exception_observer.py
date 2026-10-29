"""First outer failure provenance, unchanged exception handling and owned cleanup."""
from datetime import datetime,timezone
import errno
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import test_daily_operating as operating
from mb_watchlist_coordinator.daily_operating import DailyOperatingOwner

HELPERS=Path(os.environ.get('MB_OPERATING_OBSERVER_HELPERS',
    str(Path(__file__).resolve().parents[1]/'experiments/daily_hot_source_reliability_20261029')))


def load(name):
    spec=importlib.util.spec_from_file_location(name,HELPERS/(name+'.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


observer=load('operating_exception_observer');parent=load('observe_operating')


class OriginalHandler:
    def _run(self,failure,events):
        phase='ACTIVE'
        try:
            events.append('operation')
            if failure is not None:raise failure
            return 'original-success'
        except Exception as error:
            reason='operating_evidence_or_launch_failed'
            events.append(('handled',error))
        finally:
            events.append('original-cleanup')
        return reason


class OperatingExceptionObserverTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        self.owner=OriginalHandler();self.owner.root=self.root
        self.owner.clock=lambda:datetime.now(timezone.utc)
        self.owner.binding={'nonce':'synthetic-only','configuration_sha256':'synthetic-configuration'}

    def error(self):
        error=PermissionError(errno.EACCES,'SYNTHETIC-PRIVATE-TEXT',str(self.root/'source.json'),None,str(self.root/'destination.json'))
        error.winerror=32
        return error

    def run_observed(self,error):
        events=[]
        result=observer.instrument(OriginalHandler._run)(self.owner,error,events)
        return result,events

    def test_same_error_single_operation_and_original_cleanup_are_preserved(self):
        error=self.error();result,events=self.run_observed(error)
        self.assertEqual(result,'operating_evidence_or_launch_failed')
        self.assertEqual(events,['operation',('handled',error),'original-cleanup'])
        self.assertIs(events[1][1],error)
        raw=(self.root/observer.RECEIPT).read_text();saved=json.loads(raw)
        self.assertEqual(saved['winerror'],32);self.assertEqual(saved['errno'],errno.EACCES)
        self.assertEqual(saved['filename'],error.filename);self.assertEqual(saved['filename2'],error.filename2)
        self.assertTrue(saved['failure_observed_before_original_handler'])
        self.assertNotIn('SYNTHETIC-PRIVATE-TEXT',raw)
        self.assertIn({'module':__name__,'function':'_run','line':error.__traceback__.tb_lineno},saved['frames'])

    def test_success_does_not_call_capture_or_add_a_record(self):
        with patch.object(observer,'capture') as capture:
            result,events=self.run_observed(None)
        self.assertEqual(result,'original-success');self.assertEqual(events,['operation','original-cleanup'])
        capture.assert_not_called();self.assertFalse((self.root/observer.RECEIPT).exists())

    def test_diagnostic_failure_keeps_primary_error_and_cleanup(self):
        error=self.error()
        with patch.object(observer,'capture',side_effect=RuntimeError('diagnostic failure')):
            result,events=self.run_observed(error)
        self.assertEqual(result,'operating_evidence_or_launch_failed');self.assertIs(events[1][1],error)
        self.assertEqual(events[-1],'original-cleanup')

    def test_first_record_is_not_overwritten_by_a_later_failure(self):
        self.run_observed(self.error());before=(self.root/observer.RECEIPT).read_bytes()
        result,events=self.run_observed(ValueError('second'))
        self.assertEqual(result,'operating_evidence_or_launch_failed');self.assertEqual(events[-1],'original-cleanup')
        self.assertEqual((self.root/observer.RECEIPT).read_bytes(),before)

    def test_context_os_error_and_original_runtime_location_are_preserved(self):
        try:
            try:raise self.error()
            except PermissionError:raise RuntimeError('SYNTHETIC-PRIVATE-TEXT')
        except RuntimeError as error:self.run_observed(error)
        saved=json.loads((self.root/observer.RECEIPT).read_text())
        self.assertEqual(saved['causes'][0]['winerror'],32)
        original=DailyOperatingOwner._run;observed=observer.instrument(original)
        self.assertEqual(observed.__code__.co_filename,original.__code__.co_filename)
        self.assertEqual(observed.__code__.co_firstlineno,original.__code__.co_firstlineno)
        self.assertIs(observed._owner_observer_original,original)

    def test_final_report_exposes_owner_error_and_keeps_failed_verdict(self):
        report=self.root/'verification.json'
        report.write_text(json.dumps({'result':'FAILED','monitor_exception':None,
            'runtime_changes':True,'original_runtime_source_files_unchanged':True}))
        receipt=self.root/'paced/closed-state/daily_outer_test'/observer.RECEIPT
        receipt.parent.mkdir(parents=True);receipt.write_text(json.dumps({'error_type':'PermissionError','winerror':32}))
        result=parent.finish_report(report)
        self.assertEqual(result['result'],'FAILED');self.assertEqual(result['diagnostic_result'],'CAPTURED')
        self.assertEqual(result['operating_exception']['winerror'],32)
        self.assertTrue(result['owner_original_handler_and_cleanup_unchanged'])
        self.assertFalse(result['root_cause_fixed']);self.assertFalse(result['active_owner_checks_added'])


class ActualObservedOwnerTests(unittest.TestCase):
    def setUp(self):
        self.fixture=operating.DailyOperatingTests('test_read_only_status_does_not_create_a_missing_outer')
        self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        parent.setup_observed(self.fixture,lambda case:None)
        original=parent.install_owner(DailyOperatingOwner)
        self.addCleanup(setattr,DailyOperatingOwner,'_run',original)

    def test_real_owned_start_and_operator_stop_keep_original_cleanup(self):
        owner=self.fixture.owner();began=time.monotonic()
        result=owner.run(self.fixture.secret(),stop_requested_callback=lambda:time.monotonic()-began>1.5)
        self.assertEqual(result['result'],'STOPPED',result)
        self.assertEqual(result['cleanup']['status'],'EXIT_OBSERVED',result)
        self.assertFalse((owner.root/observer.RECEIPT).exists())

    def test_outer_callback_permission_error_is_captured_before_original_owned_cleanup(self):
        owner=self.fixture.owner();began=time.monotonic();raised=[];active_seen=[]
        filename=Path(self.fixture.fixture.config.publication.state_root)/'hot-status.json'
        def stop():
            if time.monotonic()-began>8:return True
            status=owner._child_status()
            if status and status['phase']=='ACTIVE':
                active_seen.append(1)
                # The original loop calls the callback before updating its
                # phase. Let it observe ACTIVE once before injecting failure.
                if len(active_seen)<2:return False
                error=PermissionError(errno.EACCES,'SYNTHETIC-PRIVATE-TEXT',str(filename))
                error.winerror=32;raised.append(error);raise error
            return False
        result=owner.run(self.fixture.secret(),stop_requested_callback=stop)
        self.assertEqual(len(raised),1);self.assertEqual(result['result'],'FAILED',result)
        self.assertEqual(result['stop_reason'],'operating_evidence_or_launch_failed',result)
        self.assertEqual(result['failure_type'],'PermissionError',result)
        self.assertEqual(result['cleanup']['status'],'EXIT_OBSERVED',result)
        raw=(owner.root/observer.RECEIPT).read_text();saved=json.loads(raw)
        self.assertEqual(saved['winerror'],32);self.assertEqual(saved['filename'],str(filename))
        self.assertEqual(saved['owner_phase_at_last_check'],'ACTIVE');self.assertNotIn('SYNTHETIC-PRIVATE-TEXT',raw)
        self.assertTrue(any(f['module']=='mb_watchlist_coordinator.daily_operating' and f['function']=='_run' for f in saved['frames']))
        self.assertTrue(any(f['module']==__name__ and f['function']=='stop' for f in saved['frames']))
        self.assertFalse((Path(self.fixture.fixture.config.publication.state_root)/'controller-monitor-error.json').exists())


if __name__=='__main__':unittest.main()
