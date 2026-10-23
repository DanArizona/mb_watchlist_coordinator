"""One explicitly registered experimental Hot worker; never discover PIDs.

Drivers must implement the fenced role-lease and heartbeat protocol. This
increment qualifies that protocol with a no-provider fixture, not a broker SDK
driver. Uni/Focus are deliberately not accepted as managed roles.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
import re
from pathlib import Path
import subprocess
import threading
import time
import uuid

from .sampling_requests import canonical, digest, timestamp
from .sampling_service import owner_lock, ServiceBusy

HOT_SECONDS = tuple(s for s in range(2, 60, 2) if s % 10)


def next_future_slot(at, seconds=HOT_SECONDS):
    if at.tzinfo is None or not seconds or any(type(s) is not int or not 0 <= s < 60 for s in seconds):
        raise ValueError('Aware time and explicit slot seconds required')
    minute = at.replace(second=0, microsecond=0)
    for offset in (0, 1):
        for second in sorted(set(seconds)):
            candidate = minute+timedelta(minutes=offset, seconds=second)
            if candidate > at:
                return candidate
    raise ValueError('No future slot')


def atomic_json(path, payload, *, monotonic=time.monotonic, sleep=time.sleep):
    """Publish one complete value; tolerate brief Windows rename sharing races.

    A reader can temporarily deny rename/delete sharing on Windows. Retrying
    the already-flushed temporary file preserves the last complete value. This
    is bounded by both elapsed time and attempts; unrelated errors still fail.
    """
    path = Path(path)
    temporary = path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        with temporary.open('x', encoding='utf-8') as out:
            out.write(canonical(payload)); out.flush(); os.fsync(out.fileno())
        deadline = monotonic()+.25
        for attempt in range(26):
            try:
                os.replace(temporary, path)
                break
            except OSError as error:
                remaining = deadline-monotonic()
                if getattr(error, 'winerror', None) not in (5, 32, 33) or attempt == 25 or remaining <= 0:
                    raise
                sleep(min(.01, remaining))
    finally:
        temporary.unlink(missing_ok=True)


def _drain_stderr(stream, tail, lock):
    """Drain without blocking the child; retain only the final 8 KiB."""
    try:
        while chunk := stream.read(4096):
            with lock:
                tail.extend(chunk)
                del tail[:-8192]
    finally:
        stream.close()


class ManagedRecoveryWorker:
    def __init__(self, root, *, role, command, binding, max_starts=3, startup_seconds=3,
                 stale_seconds=3, clock=None, monotonic=time.monotonic):
        if role != 'experimental_hot' or not command or not all(isinstance(s, str) and s for s in command):
            raise ValueError('Only an explicit experimental Hot worker command is supported')
        if (type(max_starts) is not int or not 1 <= max_starts <= 3
                or not 0 < startup_seconds <= 10 or not 0 < stale_seconds <= 10):
            raise ValueError('Invalid bounded worker limits')
        self.root, self.command = Path(root), tuple(command)
        self.root.mkdir(parents=True, exist_ok=True)
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.monotonic = monotonic
        self.max_starts, self.startup_seconds, self.stale_seconds = max_starts, startup_seconds, stale_seconds
        self.identity = {'contract': 'experimental-recovery-worker-v1', 'role': role,
            'command': list(command), 'binding': binding, 'max_starts': max_starts,
            'startup_seconds': startup_seconds, 'stale_seconds': stale_seconds,
            'experimental_hot_seconds': list(HOT_SECONDS),
            'qualification': 'process_protocol_only_provider_driver_pending'}
        self.registry = self.root/'worker.json'
        self.lease = self.root/'worker.lock'
        self.child, self.owned_token = None, None
        self.last_start = None
        self.last_exit = None
        self.last_heartbeat_check = None
        self._stderr_tail, self._stderr_lock, self._stderr_thread = None, None, None

    def _reap_owned(self, reason):
        child = self.child
        code = child.wait()
        self._stderr_thread.join(timeout=.2)
        with self._stderr_lock:
            stderr = bytes(self._stderr_tail).decode('utf-8', errors='backslashreplace')
        self.last_exit = {'token': self.owned_token, 'pid': child.pid,
            'returncode': code, 'reason': reason, 'observed_at_utc': self.clock().isoformat(),
            'stderr_tail': stderr, 'stderr_limit_bytes': 8192}
        self.child = None
        atomic_json(self.root/(self.owned_token+'.exit.json'), self.last_exit)

    def _job(self):
        if not self.registry.is_file():
            if any(self.root.glob('*.job.json')) or any(self.root.glob('*.heartbeat.json')) or any(self.root.glob('*.stop')):
                raise FileNotFoundError('Missing worker registry; restore instead of resetting ownership/budget')
            return None
        job = json.loads(self.registry.read_text(encoding='utf-8'))
        value = dict(job); sha = value.pop('content_sha256')
        if (digest(value) != sha or job['identity'] != self.identity
                or type(job['generation']) is not int or not 1 <= job['generation'] <= self.max_starts
                or not isinstance(job['token'], str) or not re.fullmatch('[0-9a-f]{32}', job['token'])):
            raise ValueError('Worker registry identity or checksum differs')
        for key, suffix in (('heartbeat_path', '.heartbeat.json'), ('stop_path', '.stop')):
            if Path(job[key]) != self.root.resolve()/(job['token']+suffix):
                raise ValueError('Worker registry path differs')
        if Path(job['job_path']) != self.root.resolve()/(job['token']+'.job.json'):
            raise ValueError('Worker job path differs')
        if (Path(job['registry_path']) != self.registry.resolve()
                or job['experimental_hot_seconds'] != list(HOT_SECONDS)
                or job['first_eligible_slot_utc'] != next_future_slot(timestamp(job['resume_after_utc'])).isoformat()
                or job['no_past_slot_catchup'] is not True
                or not Path(job['job_path']).is_file()
                or Path(job['job_path']).read_text(encoding='utf-8') != canonical(job)):
            raise ValueError('Worker durable job or future-slot gate differs')
        if Path(job['lease_path']) != self.lease.resolve():
            raise ValueError('Worker lease path differs')
        return job

    def _lease_busy(self):
        try:
            with owner_lock(self.lease):
                return False
        except ServiceBusy:
            return True

    def _heartbeat(self, job):
        path = Path(job['heartbeat_path'])
        if not path.is_file():
            self.last_heartbeat_check = {'status': 'missing', 'token': job['token']}
            return None
        beat = json.loads(path.read_text(encoding='utf-8'))
        age = (self.clock()-timestamp(beat['completed_at_utc'])).total_seconds()
        self.last_heartbeat_check = {'status': 'invalid', 'token': job['token'],
            'completed_at_utc': beat['completed_at_utc'], 'age_seconds': age,
            'stale_seconds': self.stale_seconds}
        if (beat.get('token') != job['token'] or beat.get('identity_sha256') != digest(self.identity)
                or beat.get('generation') != job['generation'] or beat.get('progress') != 'completed'
                or type(beat.get('pid')) is not int or not 0 <= age <= self.stale_seconds):
            return None
        if self.child is not None and self.owned_token == job['token'] and beat['pid'] != self.child.pid:
            return None
        self.last_heartbeat_check['status'] = 'valid'
        return beat

    def ensure(self, *, start_allowed, resume_after_utc):
        result = self._ensure(start_allowed=start_allowed, resume_after_utc=resume_after_utc)
        if self.last_exit is not None:
            result['previous_worker_exit'] = dict(self.last_exit)
        if self.last_heartbeat_check is not None and result['status'] not in ('RUNNING', 'EXTERNAL_HEALTHY'):
            result['heartbeat_check'] = dict(self.last_heartbeat_check)
        return result

    def _ensure(self, *, start_allowed, resume_after_utc):
        # The recovery authority serializes this method across controllers.
        job = self._job()
        if self.child is not None and self.child.poll() is not None:
            self._reap_owned('exited_before_health_check')
        busy = self._lease_busy()
        beat = self._heartbeat(job) if job else None
        if busy:
            if not beat and job and (self.clock()-timestamp(job['started_at_utc'])).total_seconds() < self.startup_seconds:
                return {'status': 'STARTING', 'generation': job['generation']}
            if not beat and self.child is not None:
                self.stop_owned(reason='owned_worker_progress_overdue')
                return {'status': 'RESTART_WAIT', 'reason': 'owned_worker_progress_overdue'}
            return {'status': ('RUNNING' if self.child is not None else 'EXTERNAL_HEALTHY') if beat else 'BLOCKED',
                'generation': job['generation'] if job else None,
                'pid': beat['pid'] if beat else None, 'ownership': 'owned' if self.child is not None else 'observed_only'}
        if job and (self.clock()-timestamp(job['started_at_utc'])).total_seconds() < self.startup_seconds:
            return {'status': 'STARTING', 'generation': job['generation']}
        if self.child is not None:
            # A live child without its lease must not be duplicated or PID-killed.
            return {'status': 'BLOCKED', 'reason': 'owned_child_not_holding_required_lease'}
        if not start_allowed:
            return {'status': 'WAITING_FOR_VERIFIED_MEMBERSHIP'}
        if job and job['generation'] >= self.max_starts:
            return {'status': 'BLOCKED', 'reason': 'worker_restart_budget_exhausted'}
        token = uuid.uuid4().hex
        job = {'identity': self.identity, 'generation': (job['generation']+1 if job else 1),
            'token': token, 'started_at_utc': self.clock().isoformat(),
            'resume_after_utc': resume_after_utc, 'no_past_slot_catchup': True,
            'first_eligible_slot_utc': next_future_slot(timestamp(resume_after_utc)).isoformat(),
            'experimental_hot_seconds': list(HOT_SECONDS),
            'registry_path': str(self.registry.resolve()), 'lease_path': str(self.lease.resolve()),
            'job_path': str((self.root/(token+'.job.json')).resolve()),
            'heartbeat_path': str((self.root/(token+'.heartbeat.json')).resolve()),
            'stop_path': str((self.root/(token+'.stop')).resolve())}
        job['content_sha256'] = digest(job)
        atomic_json(Path(job['job_path']), job)
        atomic_json(self.registry, job)
        self.owned_token = token
        self._stderr_tail, self._stderr_lock = bytearray(), threading.Lock()
        self.child = subprocess.Popen([*self.command, job['job_path']], stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        self._stderr_thread = threading.Thread(target=_drain_stderr,
            args=(self.child.stderr, self._stderr_tail, self._stderr_lock), daemon=True)
        self._stderr_thread.start()
        self.last_start = self.monotonic()
        return {'status': 'STARTING', 'generation': job['generation'], 'pid': self.child.pid}

    def stop_owned(self, *, reason='owned_stop_requested'):
        if self.child is None:
            return {'status': 'EXTERNAL_WORKER_UNCHANGED'}
        try:
            job = self._job()
        except (ValueError, OSError, KeyError, TypeError):
            job = None  # The exact Popen handle still proves which child is ours.
        if job and job['token'] == self.owned_token:
            try:
                Path(job['stop_path']).write_text(job['token'], encoding='ascii')
            except OSError:
                pass  # Bounded termination below targets only our exact handle.
        try:
            self.child.wait(timeout=.5)
        except subprocess.TimeoutExpired:
            self.child.terminate()
            try:
                self.child.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self.child.kill(); self.child.wait(timeout=2)
        self._reap_owned(reason)
        return {'status': 'OWNED_WORKER_STOPPED'}
