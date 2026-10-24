"""Private gated process scope for the outer experimental controller.

Windows uses one unnamed Job Object, with no breakaway permission. POSIX uses
one newly created session/process group (trusted children must not escape it).
Only this scope's handle/group is controlled. No process-name/PID discovery.
The trusted entry must call receive_gate before credentials or child creation.
"""
import ctypes
import json
import os
import signal
import subprocess
import time


def receive_gate(stream, nonce):
    line = stream.readline(513)
    if line != (json.dumps({'outer_gate': nonce}, sort_keys=True)+'\n').encode():
        raise ValueError('Outer process ownership gate rejected')


class WindowsJob:
    def __init__(self):
        from ctypes import wintypes as w
        k = self.api = ctypes.WinDLL('kernel32', use_last_error=True)
        class Basic(ctypes.Structure):
            _fields_ = [('process_time',ctypes.c_int64),('job_time',ctypes.c_int64),
                ('flags',w.DWORD),('min_working',ctypes.c_size_t),('max_working',ctypes.c_size_t),
                ('active_limit',w.DWORD),('affinity',ctypes.c_size_t),('priority',w.DWORD),('scheduling',w.DWORD)]
        class Extended(ctypes.Structure):
            _fields_ = [('basic',Basic),('io',ctypes.c_uint64*6),
                ('process_memory',ctypes.c_size_t),('job_memory',ctypes.c_size_t),
                ('peak_process',ctypes.c_size_t),('peak_job',ctypes.c_size_t)]
        class Accounting(ctypes.Structure):
            _fields_ = [('times',ctypes.c_int64*4),('faults',w.DWORD),('total',w.DWORD),
                ('active',w.DWORD),('terminated',w.DWORD)]
        self.accounting = Accounting
        for name,args,restype in (
            ('CreateJobObjectW',[ctypes.c_void_p,w.LPCWSTR],w.HANDLE),
            ('SetInformationJobObject',[w.HANDLE,ctypes.c_int,ctypes.c_void_p,w.DWORD],w.BOOL),
            ('AssignProcessToJobObject',[w.HANDLE,w.HANDLE],w.BOOL),
            ('IsProcessInJob',[w.HANDLE,w.HANDLE,ctypes.POINTER(w.BOOL)],w.BOOL),
            ('TerminateJobObject',[w.HANDLE,w.UINT],w.BOOL),
            ('QueryInformationJobObject',[w.HANDLE,ctypes.c_int,ctypes.c_void_p,w.DWORD,ctypes.c_void_p],w.BOOL),
            ('CloseHandle',[w.HANDLE],w.BOOL)):
            getattr(k,name).argtypes=args;getattr(k,name).restype=restype
        self.handle = k.CreateJobObjectW(None,None)
        if not self.handle:raise ctypes.WinError(ctypes.get_last_error())
        limits=Extended();limits.basic.flags=0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not k.SetInformationJobObject(self.handle,9,ctypes.byref(limits),ctypes.sizeof(limits)):
            error=ctypes.get_last_error();self.close();raise ctypes.WinError(error)

    def assign(self, child):
        from ctypes import wintypes as w
        if not self.api.AssignProcessToJobObject(self.handle,int(child._handle)):
            raise ctypes.WinError(ctypes.get_last_error())
        inside=w.BOOL()
        if not self.api.IsProcessInJob(int(child._handle),self.handle,ctypes.byref(inside)) or not inside.value:
            raise OSError('Owned controller Job Object assignment unconfirmed')

    def empty(self):
        result=self.accounting()
        if not self.api.QueryInformationJobObject(self.handle,1,ctypes.byref(result),ctypes.sizeof(result),None):
            raise ctypes.WinError(ctypes.get_last_error())
        return result.active==0

    def terminate(self):
        if not self.api.TerminateJobObject(self.handle,124):
            raise ctypes.WinError(ctypes.get_last_error())

    def close(self):
        if self.handle:
            handle,self.handle=self.handle,None
            if not self.api.CloseHandle(handle):raise ctypes.WinError(ctypes.get_last_error())


class OwnedProcessScope:
    """One spawn, gated before user entry. close() never renews a deadline."""
    def __init__(self, command, nonce, *, monotonic=time.monotonic):
        import re
        if (not isinstance(command,tuple) or not command or
                not all(type(s) is str and s for s in command) or
                not isinstance(nonce,str) or not re.fullmatch('[0-9a-f]{32}',nonce)):
            raise ValueError('Explicit command and nonce required')
        self.command,self.nonce,self.monotonic=command,nonce,monotonic
        self.child=self.job=None
        self.gate_sent=False;self.closed=False
        self.backend='windows_job' if os.name=='nt' else 'posix_process_group'

    def launch(self):
        if self.child is not None or self.closed:raise ValueError('Scope cannot be reused')
        try:
            if os.name=='nt':self.job=WindowsJob()
            self.child=subprocess.Popen(self.command,stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                start_new_session=os.name!='nt',close_fds=True)
            if self.job:self.job.assign(self.child)
            return self
        except BaseException:
            if self.child is not None:
                if self.child.poll() is None:self.child.kill()
                self.child.wait(timeout=2)
                self.child.stdin.close()
            if self.job:self.job.close()
            self.closed=True
            raise

    def open_gate(self):
        if self.gate_sent or self.child is None or self.closed:raise ValueError('Invalid ownership gate')
        raw=(json.dumps({'outer_gate':self.nonce},sort_keys=True)+'\n').encode()
        self.child.stdin.write(raw);self.child.stdin.flush();self.gate_sent=True

    def empty(self):
        if self.child is None:return True
        self.child.poll()  # Reap the known direct child; do not adopt descendants.
        if self.job:return self.job.empty()
        try:os.killpg(self.child.pid,0)
        except ProcessLookupError:return True
        return False  # Includes unreaped orphan zombies; never claim confirmed empty.

    def terminate(self):
        if self.child is None or self.closed:raise ValueError('No owned process scope')
        if self.job:self.job.terminate()
        else:
            try:os.killpg(self.child.pid,signal.SIGKILL)
            except ProcessLookupError:pass

    def finish(self, deadline, *, sleep=time.sleep):
        if self.closed:raise ValueError('Scope already closed')
        forced=False;error=None;empty=False
        try:
            empty=self.empty()
            if not empty:
                self.terminate();forced=True
            while not empty and self.monotonic()<deadline:
                empty=self.empty()
                if not empty:sleep(min(.01,max(0,deadline-self.monotonic())))
        except OSError:
            error='owned_scope_operation_failed'
        finally:
            if self.child is not None:self.child.stdin.close()
            if self.job:
                try:self.job.close()
                except OSError:error='owned_scope_close_failed'
            self.closed=True
            if self.child is not None and self.child.poll() is None:
                # Reap only this already-terminated handle asynchronously. No
                # extra foreground deadline or confirmed-exit claim is added.
                import threading
                threading.Thread(target=self.child.wait,daemon=True).start()
        return {'status':'EXIT_OBSERVED' if empty and not error else 'CLEANUP_INCOMPLETE',
            'backend':self.backend,'scope_empty_observed':empty,'forced':forced,
            'controller_returncode':None if self.child is None else self.child.poll(),
            'reason':error}
