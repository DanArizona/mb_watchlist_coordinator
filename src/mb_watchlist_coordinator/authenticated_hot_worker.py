"""Private-pipe entry for an explicitly human-started experimental Hot worker."""
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import sys
import threading

from .authenticated_startup import (AuthStartupSettings, StartupError,
    prepare_authenticated_client, receive_password)
from .hot_recovery_collector import HotCollectorSettings, validate_job, run_worker
from .recovery_workers import atomic_json
from .sampling_requests import digest


def load_configuration(path):
    value=json.loads(Path(path).read_text(encoding='utf-8'))
    if set(value)!={'collector','authentication'}:raise ValueError('Explicit non-secret startup configuration required')
    collector=HotCollectorSettings(**value['collector'])
    authentication=AuthStartupSettings(**value['authentication'])
    collector.payload();authentication.payload()
    if authentication.stop_at_utc!=collector.stop_at_utc:
        from .sampling_requests import timestamp
        if timestamp(authentication.stop_at_utc)!=timestamp(collector.stop_at_utc):
            raise ValueError('Authentication and acquisition windows differ')
    return value,collector,authentication


def _silence_sdk_output():
    # No SDK output/exception body can reach the parent's retained stderr tail.
    logging.disable(logging.CRITICAL)
    fd=os.open(os.devnull,os.O_WRONLY)
    try:
        os.dup2(fd,1);os.dup2(fd,2)
    finally:os.close(fd)


def run_authenticated(configuration_path,job_path,*,secret_stream=None,clock=None,secure_api=None):
    """No secret argv/environment/files; a fresh controller needs manual entry."""
    _silence_sdk_output()
    raw,collector,authentication=load_configuration(configuration_path)
    job=validate_job(job_path,collector.publication_binding)
    if (job['identity']['contract']!='experimental-recovery-worker-v2'
            or job['identity']['startup_context']['configuration_sha256']!=digest(raw)):
        raise StartupError('secret_handoff_invalid')
    clock=clock or (lambda:datetime.now(timezone.utc))
    done=threading.Event()
    status_path=Path(job['job_path']).parent/(job['token']+'.auth.json')
    def status(code):
        atomic_json(status_path,{'contract':'authenticated-hot-startup-v1','token':job['token'],
            'configuration_sha256':digest(raw),'status':code,
            'observed_at_utc':datetime.now(timezone.utc).isoformat()})
    def deadline():
        if not done.wait(authentication.startup_timeout_seconds):
            try:status('startup_deadline_ended')
            finally:os._exit(124)
    threading.Thread(target=deadline,daemon=True).start()
    password=None
    try:
        password=receive_password(sys.stdin.buffer if secret_stream is None else secret_stream,job['token'])
        def start():
            client=None
            try:
                client=prepare_authenticated_client(authentication,password,clock=clock,secure_api=secure_api)
                status('credentials_accepted')
                done.set()
                return client
            except BaseException:
                if client is not None:client.close()
                raise
            finally:
                password[:]=b'\0'*len(password)
        def forbidden_factory():raise StartupError('startup_failed')
        return run_worker(job_path,collector,client_factory=forbidden_factory,clock=clock,startup_client=start)
    except StartupError as error:
        status(error.code)
        raise
    except Exception:
        status('startup_failed')
        raise StartupError('startup_failed') from None
    finally:
        done.set()
        if password is not None:
            password[:]=b'\0'*len(password)
            password.clear()


def main():
    try:
        if len(sys.argv)!=3:return 64
        run_authenticated(sys.argv[1],sys.argv[2])
        return 0
    except KeyboardInterrupt:return 130
    except Exception:return 70


if __name__=='__main__':raise SystemExit(main())
