"""Authenticated native worker with the earlier three-second progress gate.

There is deliberately no live operator launcher. A trusted controller supplies
the source-pinned entry, public configuration, fenced job and private pipe.
"""
from datetime import datetime, timezone
import os
from pathlib import Path
import sys
import threading
import time

from .authenticated_hot_worker import load_configuration, _silence_sdk_output
from .authenticated_startup import StartupError, prepare_authenticated_client, receive_password
from .controller_bootstrap import strict_json
from .hot_recovery_collector import validate_job, run_worker
from .recovery_workers import atomic_json
from .sampling_requests import digest, timestamp, utc_text

STARTUP_SECONDS = 3
CONTRACT = 'supervised-authenticated-hot-worker-v1'


def progress_path(job):
    return Path(job['job_path']).parent/(job['token']+'.startup.json')


def progress_receipt(job):
    """A credential receipt alone never satisfies the first-work gate."""
    value = strict_json(progress_path(job).read_text(encoding='utf-8'))
    if (set(value) != {'contract', 'token', 'generation', 'configuration_sha256',
            'status', 'observed_at_utc', 'pid'} or value['contract'] != CONTRACT
            or value['token'] != job['token'] or value['generation'] != job['generation']
            or type(value['generation']) is not int
            or value['configuration_sha256'] != job['identity']['startup_context']['configuration_sha256']
            or type(value['pid']) is not int
            or value['status'] not in ('first_completed_work_observed', 'worker_startup_deadline_ended')):
        raise ValueError('Supervised startup receipt differs')
    elapsed = (timestamp(value['observed_at_utc'])-timestamp(job['started_at_utc'])).total_seconds()
    if elapsed < 0 or value['status'] == 'first_completed_work_observed' and elapsed >= STARTUP_SECONDS:
        raise ValueError('First completed work missed its original startup gate')
    return value


class RuntimeQuoteClient:
    """Preserve accepted redaction and stop on rate-limit/authentication replies."""
    def __init__(self, prepared):
        self.prepared = prepared
        self.halt_reason = None

    def quotes(self, symbols, *, fields):
        if self.halt_reason:
            raise StartupError('provider_failed')
        response = self.prepared.quotes(symbols, fields=fields)
        self.halt_reason = getattr(self.prepared, 'halt_reason', None)
        if response.status_code == 429:
            self.halt_reason = 'provider_rate_limited'
        return response

    def close(self):
        self.prepared.close()


def run_supervised(configuration_path, job_path, *, secret_stream=None,
                   clock=None, secure_api=None, native_runner=run_worker):
    """Keep both original deadlines; the first native work must win by 3s.

    The independent watchdog starts with the remaining job-start budget, not
    a new three seconds after credential construction. A trusted test runner
    can inject synthetic SDK/configuration and the native fault hook only.
    """
    _silence_sdk_output()
    raw, collector, authentication = load_configuration(configuration_path)
    job = validate_job(job_path, collector.publication_binding)
    if (authentication.request_timeout_seconds != 3 or authentication.startup_timeout_seconds != 8
            or job['identity']['contract'] != 'experimental-recovery-worker-v2'
            or job['identity']['startup_seconds'] != 3 or job['identity']['stale_seconds'] != 3
            or job['identity']['max_starts'] != 3
            or job['identity']['startup_context']['configuration_sha256'] != digest(raw)):
        raise StartupError('secret_handoff_invalid')
    clock = clock or (lambda: datetime.now(timezone.utc))
    finished, authenticated = threading.Event(), threading.Event()
    gate = time.monotonic()+max(0, 3-(clock()-timestamp(job['started_at_utc'])).total_seconds())
    auth_path = Path(job['job_path']).parent/(job['token']+'.auth.json')

    def auth_status(code):
        atomic_json(auth_path, {'contract': 'authenticated-hot-startup-v1', 'token': job['token'],
            'configuration_sha256': digest(raw), 'status': code, 'observed_at_utc': utc_text(clock())})

    def progress_status(code):
        atomic_json(progress_path(job), {'contract': CONTRACT, 'token': job['token'],
            'generation': job['generation'], 'configuration_sha256': digest(raw),
            'status': code, 'observed_at_utc': utc_text(clock()), 'pid': os.getpid()})

    def first_work_deadline():
        while not finished.is_set():
            if time.monotonic() >= gate:
                try:
                    progress_status('worker_startup_deadline_ended')
                finally:
                    os._exit(124)
            try:
                beat = strict_json(Path(job['heartbeat_path']).read_text(encoding='utf-8'))
                elapsed = (timestamp(beat['completed_at_utc'])-timestamp(job['started_at_utc'])).total_seconds()
                if (beat['token'] == job['token'] and beat['generation'] == job['generation']
                        and beat['identity_sha256'] == digest(job['identity'])
                        and beat['pid'] == os.getpid() and beat['progress'] == 'completed'
                        and 0 <= elapsed < 3 and authenticated.is_set()):
                    progress_status('first_completed_work_observed')
                    return
            except (OSError, ValueError, KeyError, TypeError):
                pass
            finished.wait(.01)

    def credential_deadline():
        if not authenticated.wait(authentication.startup_timeout_seconds) and not finished.is_set():
            try:
                auth_status('startup_deadline_ended')
            finally:
                os._exit(124)

    if clock() < timestamp(job['started_at_utc']) or time.monotonic() >= gate:
        progress_status('worker_startup_deadline_ended')
        raise StartupError('startup_failed')
    first = threading.Thread(target=first_work_deadline, daemon=True)
    first.start()
    threading.Thread(target=credential_deadline, daemon=True).start()
    password = None
    try:
        password = receive_password(sys.stdin.buffer if secret_stream is None else secret_stream, job['token'])

        def startup():
            client = None
            try:
                client = prepare_authenticated_client(authentication, password, clock=clock, secure_api=secure_api)
                auth_status('credentials_accepted')
                authenticated.set()
                return RuntimeQuoteClient(client)
            except BaseException:
                if client is not None:
                    client.close()
                raise
            finally:
                password[:] = b'\0'*len(password)

        def forbidden():
            raise StartupError('startup_failed')

        return native_runner(job_path, collector, client_factory=forbidden, clock=clock, startup_client=startup)
    except StartupError as error:
        auth_status(error.code)
        raise
    except Exception:
        auth_status('startup_failed')
        raise StartupError('startup_failed') from None
    finally:
        finished.set()
        authenticated.set()
        first.join(timeout=.1)
        if password is not None:
            password[:] = b'\0'*len(password)
            password.clear()
