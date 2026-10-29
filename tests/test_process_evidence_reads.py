"""Windows control-file open races; current evidence and original fences survive."""
from datetime import datetime,timedelta,timezone
import errno
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from mb_watchlist_coordinator import recovery_workers as records
from mb_watchlist_coordinator.daily_supervision import read_json
from mb_watchlist_coordinator.sampling_requests import digest


class ProcessEvidenceReadTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name);self.path=self.root/'record.json'
        self.path.write_text('{"current": 1}')
        self.elapsed=0.;self.sleeps=[]

    def sleep(self,seconds):self.sleeps.append(seconds);self.elapsed+=seconds

    def error(self,code=None,err=errno.EACCES):
        value=PermissionError(err,'synthetic read conflict',str(self.path))
        if code is not None:value.winerror=code
        return value

    def read(self):
        return records.read_process_text(self.path,monotonic=lambda:self.elapsed,sleep=self.sleep)

    def test_bare_eacces_and_known_windows_codes_read_new_complete_value_after_conflict(self):
        original=Path.read_text
        for code in (None,5,32,33):
            with self.subTest(winerror=code):
                self.elapsed=0.;calls=[]
                def attempt(path,*args,**kwargs):
                    calls.append(path)
                    if len(calls)==1:
                        self.path.write_text('{"current": 2}')
                        raise self.error(code)
                    return original(path,*args,**kwargs)
                with patch.object(records,'_WINDOWS_PROCESS_READS',True),patch.object(Path,'read_text',autospec=True,side_effect=attempt):
                    self.assertEqual(json.loads(self.read()),{'current':2})
                self.assertEqual(calls,[self.path,self.path]);self.assertAlmostEqual(self.elapsed,.01)

    def test_persistent_permission_error_is_bounded_and_raised_without_cached_success(self):
        error=self.error()
        with patch.object(records,'_WINDOWS_PROCESS_READS',True),patch.object(Path,'read_text',side_effect=error) as attempt:
            with self.assertRaises(PermissionError) as result:self.read()
        self.assertIs(result.exception,error);self.assertGreater(attempt.call_count,1)
        self.assertLessEqual(attempt.call_count,26);self.assertLessEqual(self.elapsed,.25)
        self.assertEqual(json.loads(self.path.read_text()),{'current':1})

    def test_attempt_ceiling_holds_if_injected_clock_does_not_advance(self):
        with patch.object(records,'_WINDOWS_PROCESS_READS',True),patch.object(Path,'read_text',side_effect=self.error()) as attempt:
            with self.assertRaises(PermissionError):
                records.read_process_text(self.path,monotonic=lambda:0.,sleep=lambda _:None)
        self.assertEqual(attempt.call_count,26)

    def test_elapsed_budget_is_not_restarted_and_no_open_occurs_after_oversleep(self):
        def oversleep(seconds):self.elapsed+=1.
        with patch.object(records,'_WINDOWS_PROCESS_READS',True),patch.object(Path,'read_text',side_effect=self.error()) as attempt:
            with self.assertRaises(PermissionError):
                records.read_process_text(self.path,monotonic=lambda:self.elapsed,sleep=oversleep)
        self.assertEqual(attempt.call_count,1)

    def test_non_windows_permission_failure_is_not_retried(self):
        with patch.object(records,'_WINDOWS_PROCESS_READS',False),patch.object(Path,'read_text',side_effect=self.error(32)) as attempt:
            with self.assertRaises(PermissionError):self.read()
        self.assertEqual(attempt.call_count,1);self.assertFalse(self.sleeps)

    def test_unrelated_and_missing_file_errors_are_not_retried(self):
        for error in (self.error(87),self.error(err=errno.EPERM),PermissionError('unclassified'),
                FileNotFoundError('missing'),OSError(errno.EIO,'I/O failure')):
            with self.subTest(error=type(error).__name__),patch.object(records,'_WINDOWS_PROCESS_READS',True),patch.object(Path,'read_text',side_effect=error) as attempt:
                with self.assertRaises(type(error)):self.read()
                self.assertEqual(attempt.call_count,1)
        self.assertFalse(self.sleeps)

    def test_malformed_and_duplicate_json_are_not_retried_or_accepted(self):
        for raw in ('{','{"x":1,"x":2}'):
            with self.subTest(raw=raw),patch.object(records,'_WINDOWS_PROCESS_READS',True),patch.object(Path,'read_text',return_value=raw) as attempt:
                with self.assertRaises(ValueError):read_json(self.path)
                self.assertEqual(attempt.call_count,1)

    def heartbeat(self,*,age=0.,wrong_token=False):
        at=datetime(2026,10,30,14,tzinfo=timezone.utc)
        worker=records.ManagedRecoveryWorker(self.root/'workers',role='experimental_hot',
            command=('synthetic-unused',),binding={},clock=lambda:at+timedelta(seconds=self.elapsed))
        job={'heartbeat_path':str(self.path),'token':'a'*32,'generation':1}
        self.path.write_text(json.dumps({'token':'b'*32 if wrong_token else job['token'],
            'identity_sha256':digest(worker.identity),'generation':1,'progress':'completed',
            'pid':123,'completed_at_utc':(at-timedelta(seconds=age)).isoformat()}))
        original=records.read_process_text;read=Path.read_text;calls=[]
        def attempt(path,*args,**kwargs):
            calls.append(1)
            if len(calls)<=3:raise self.error()
            return read(path,*args,**kwargs)
        def bounded(path):return original(path,monotonic=lambda:self.elapsed,sleep=self.sleep)
        with patch.object(records,'_WINDOWS_PROCESS_READS',True),patch.object(Path,'read_text',autospec=True,side_effect=attempt),patch.object(records,'read_process_text',side_effect=bounded):
            result=worker._heartbeat(job)
        self.assertEqual(len(calls),4)
        return result,worker.last_heartbeat_check

    def test_retry_does_not_refresh_old_heartbeat_or_reset_original_three_second_limit(self):
        beat,check=self.heartbeat(age=2.99)
        self.assertIsNone(beat);self.assertEqual(check['status'],'invalid')
        self.assertGreater(check['age_seconds'],3);self.assertEqual(check['stale_seconds'],3)

    def test_fresh_heartbeat_remains_bound_and_wrong_token_is_rejected_after_retry(self):
        beat,check=self.heartbeat()
        self.assertIsNotNone(beat);self.assertEqual(check['status'],'valid')
        self.elapsed=0.;beat,check=self.heartbeat(wrong_token=True)
        self.assertIsNone(beat);self.assertEqual(check['status'],'invalid')


@unittest.skipUnless(os.name=='nt','Native Windows share-window proof requires Windows')
class NativeWindowsEvidenceReadTests(unittest.TestCase):
    evidence=[]

    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.path=Path(temp.name)/'heartbeat.json'
        records.atomic_json(self.path,{'sequence':0,'mirror':0})

    def delete_handle(self):
        import ctypes
        from ctypes import wintypes
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        create=kernel.CreateFileW
        create.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,ctypes.c_void_p,
            wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE];create.restype=wintypes.HANDLE
        close=kernel.CloseHandle;close.argtypes=[wintypes.HANDLE];close.restype=wintypes.BOOL
        handle=create(str(self.path),0x10000,7,None,3,0x80,None)
        if handle==ctypes.c_void_p(-1).value:raise ctypes.WinError(ctypes.get_last_error())
        handles=[handle];lock=threading.Lock()
        def release():
            with lock:
                if handles:
                    value=handles.pop()
                    if not close(value):raise ctypes.WinError(ctypes.get_last_error())
        self.addCleanup(release)
        return release

    def test_native_delete_sharing_window_reproduces_old_reader_failure_and_new_reader_recovers(self):
        release=self.delete_handle()
        with self.assertRaises(PermissionError) as old:self.path.read_text(encoding='utf-8')
        timer=threading.Timer(.04,release);timer.start();began=time.monotonic();sleeps=[]
        try:
            def sleep(seconds):sleeps.append(seconds);time.sleep(seconds)
            value=json.loads(records.read_process_text(self.path,sleep=sleep))
            elapsed=time.monotonic()-began
            self.assertEqual(value,{'sequence':0,'mirror':0});self.assertTrue(sleeps)
            self.evidence.append({'case':'native_delete_share_window','result':'PASS',
                'original_reader_error':type(old.exception).__name__,'errno':old.exception.errno,
                'winerror':getattr(old.exception,'winerror',None),'retry_sleeps':len(sleeps),
                'elapsed_seconds':elapsed,'payload_preserved':True})
        finally:timer.join(timeout=1);release()

    def test_persistent_native_share_conflict_still_raises_with_fixed_budget(self):
        release=self.delete_handle();began=time.monotonic();sleeps=[]
        try:
            def sleep(seconds):sleeps.append(seconds);time.sleep(seconds)
            with self.assertRaises(PermissionError):records.read_process_text(self.path,sleep=sleep)
            elapsed=time.monotonic()-began
            self.assertLess(elapsed,.75);self.assertLessEqual(len(sleeps),25)
            self.assertLessEqual(sum(sleeps),.25)
            self.evidence.append({'case':'persistent_native_conflict','result':'PASS',
                'elapsed_seconds':elapsed,'retry_sleeps':len(sleeps),'error_propagated':True})
        finally:release()

    def test_actual_atomic_publication_and_concurrent_readers_preserve_complete_records(self):
        stop=threading.Event();failures=[];counts=[0]*4
        def read(index):
            try:
                while not stop.is_set():
                    value=json.loads(records.read_process_text(self.path))
                    if set(value)!={'sequence','mirror'} or value['sequence']!=value['mirror']:
                        raise AssertionError('Incomplete control record')
                    counts[index]+=1;stop.wait(.001)
            except BaseException as error:failures.append(type(error).__name__);stop.set()
        threads=[threading.Thread(target=read,args=(i,),daemon=True) for i in range(4)]
        for thread in threads:thread.start()
        began=time.monotonic()
        try:
            for sequence in range(1,65):
                self.assertFalse(failures,failures)
                records.atomic_json(self.path,{'sequence':sequence,'mirror':sequence})
                time.sleep(.001)
        finally:
            stop.set()
            for thread in threads:thread.join(timeout=2)
        self.assertFalse(any(t.is_alive() for t in threads));self.assertFalse(failures,failures)
        self.assertTrue(all(counts),counts)
        self.assertEqual(json.loads(records.read_process_text(self.path)),{'sequence':64,'mirror':64})
        self.evidence.append({'case':'native_atomic_writer_four_readers','result':'PASS',
            'publications':64,'reads_per_thread':counts,'elapsed_seconds':time.monotonic()-began})


if __name__=='__main__':unittest.main()
