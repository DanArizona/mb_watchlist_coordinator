"""Owned daily worker roles. A trusted controller supplies public config and a private pipe."""
from dataclasses import asdict
from contextlib import contextmanager, ExitStack
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import sys
import threading
import time

from .authenticated_hot_worker import _silence_sdk_output
from .authenticated_startup import StartupError, prepare_authenticated_client, receive_password
from .daily_epoch_collector import make_daily_collector
from .daily_supervision import (DailyWorkerConfiguration, DailyProcessState,
    assert_controller_fence, read_json, sealed, unseal, validate_daily_job)
from .daily_worker_view import DailyPublicationReader
from .recovery_workers import atomic_json
from .sampling_requests import digest, timestamp, utc_text
from .sampling_service import owner_lock, ServiceBusy
from .supervised_hot_worker import RuntimeQuoteClient, CONTRACT as PROGRESS_CONTRACT, progress_path


@contextmanager
def owned_role_lease(path, *, monotonic=time.monotonic, sleep=time.sleep):
    """Tolerate a short health-probe collision only while entering the OS lease.

    The independent startup watchdog keeps its original job deadline. Work
    inside an acquired lease is never replayed, including ServiceBusy failures.
    """
    deadline = monotonic()+.2
    while True:
        lease = ExitStack()
        try:
            lease.enter_context(owner_lock(path))
        except ServiceBusy:
            remaining = deadline-monotonic()
            if remaining <= 0: raise
            sleep(min(.005, remaining))
        else:
            break
    with lease:
        yield


class _Lifetime:
    def __init__(self, config, binding, *, token, invocation, stop_path, clock,
                 job=None, identity=False):
        self.config, self.binding, self.token, self.invocation = config, binding, token, invocation
        self.stop_path, self.clock, self.job = Path(stop_path), clock, job
        self.finished, self.authenticated, self.first_work = (threading.Event() for _ in range(3))
        self.root = Path(config.publication.state_root)
        started = timestamp(job['started_at_utc']) if job else clock()
        age = (clock()-started).total_seconds()
        if age < 0:
            raise ValueError('Daily process clock moved backwards')
        self.progress_deadline = time.monotonic()+max(0, 3-age)
        self.credential_deadline = time.monotonic()+max(0, 8-age)
        self.identity = identity

    def fence(self):
        if self.stop_path.exists():
            raise ValueError('Daily process stop requested')
        return assert_controller_fence(self.config, self.binding,
            None if self.identity else self.token, self.invocation, clock=self.clock)

    def auth_status(self, code):
        if self.job:
            value = {'contract': 'authenticated-hot-startup-v1', 'token': self.token,
                'configuration_sha256': digest(self.config.payload()), 'status': code,
                'observed_at_utc': utc_text(self.clock())}
            path = self.root/'workers'/(self.token+'.auth.json')
        else:
            value = sealed({'token': self.token, 'invocation': self.invocation,
                'configuration_sha256': digest(self.config.payload()), 'status': code})
            path = self.root/(self.token+'.ready.json')
        atomic_json(path, value)

    def progress(self, status):
        if self.job:
            atomic_json(progress_path(self.job), {'contract': PROGRESS_CONTRACT,
                'token': self.token, 'generation': self.job['generation'],
                'configuration_sha256': digest(self.config.payload()), 'status': status,
                'observed_at_utc': utc_text(self.clock()), 'pid': os.getpid()})

    def watch(self):
        try:
            while not self.finished.wait(.02):
                self.fence()
                now = time.monotonic()
                if not self.authenticated.is_set() and now >= self.credential_deadline:
                    self.auth_status('startup_deadline_ended')
                    os._exit(124)
                if self.job and not self.first_work.is_set() and now >= self.progress_deadline:
                    self.progress('worker_startup_deadline_ended')
                    os._exit(124)
                if self.job and self.first_work.is_set():
                    beat = read_json(Path(self.job['heartbeat_path']))
                    if (self.clock()-timestamp(beat['completed_at_utc'])).total_seconds() >= 3:
                        os._exit(124)
        except BaseException:
            if not self.finished.is_set():
                os._exit(124)

    def start(self):
        self.fence()
        self.thread = threading.Thread(target=self.watch, daemon=True)
        self.thread.start()

    def authenticate(self, stream, secure_api):
        password = receive_password(stream, self.token)
        try:
            self.fence()
            prepared = prepare_authenticated_client(self.config.authentication, password,
                clock=self.clock, secure_api=secure_api)
            self.fence()
            self.auth_status('credentials_accepted')
            self.authenticated.set()
            return RuntimeQuoteClient(prepared)
        except StartupError as error:
            self.auth_status(error.code)
            raise
        finally:
            password[:] = b'\0'*len(password)
            password.clear()

    def close(self):
        self.finished.set()
        if hasattr(self, 'thread'):
            self.thread.join(timeout=.1)


def run_collector(configuration_path, job_path, *, secret_stream=None, clock=None,
                  secure_api=None, fault_hook=None):
    _silence_sdk_output()
    config, job, binding = validate_daily_job(configuration_path, job_path)
    clock = clock or (lambda: datetime.now(timezone.utc))
    state = DailyProcessState(Path(config.publication.state_root), binding).read()
    start = state['starts'][job['generation']-1]
    if start['token'] != job['token']:
        raise ValueError('Daily reserved worker differs')
    lifetime = _Lifetime(config, binding, token=job['token'], invocation=start['invocation'],
        stop_path=job['stop_path'], clock=clock, job=job)
    lifetime.start()
    collector = None
    try:
        with owned_role_lease(Path(job['lease_path'])):
            validate_daily_job(configuration_path, job_path)
            view = DailyPublicationReader(config.publication, config.catalog_path,
                binding=config.collector.daily_binding, claim=config.collector.daily_claim,
                publication_binding=config.collector.publication_binding,
                clock=clock, fence=lifetime.fence)
            def forbidden():
                raise StartupError('startup_failed')
            collector = make_daily_collector(config.collector, publication_session=view,
                client_factory=forbidden, clock=clock, activation_approved=True)
            if collector.poller.path.exists():
                collector.poller.snapshot()
            collector.client = lifetime.authenticate(
                sys.stdin.buffer if secret_stream is None else secret_stream, secure_api)
            recovery = collector.prepare(create=not collector.manifest.exists())
            from mb_market_data.sampling_acquisition import next_slot
            selected_at = clock()
            collector.next = next_slot(collector.poller.settings,
                after=max(selected_at, timestamp(job['resume_after_utc'])))
            # A launch job supplies a lower bound, not a promise that startup
            # finishes before that slot. Preserve the actual post-auth/recovery
            # selection so startup gaps cannot be confused with running gaps.
            atomic_json(Path(job['job_path']).with_name(job['token']+'.schedule.json'), sealed({
                'contract': 'daily-hot-worker-schedule-v1', 'token': job['token'],
                'generation': job['generation'], 'invocation': start['invocation'],
                'configuration_sha256': digest(config.payload()),
                'selected_at_utc': utc_text(selected_at),
                'resume_after_utc': job['resume_after_utc'],
                'launch_first_eligible_slot_utc': job['first_eligible_slot_utc'],
                'first_scheduled_slot_utc': utc_text(collector.next.scheduled_at) if collector.next else None}))
            while clock() < timestamp(config.collector.stop_at_utc):
                lifetime.fence()
                try:
                    result = collector.tick(fault_hook=fault_hook)
                except ServiceBusy:
                    time.sleep(.01)
                    continue  # A publication cycle may briefly own its read lock.
                atomic_json(Path(job['heartbeat_path']), {'token': job['token'],
                    'generation': job['generation'], 'identity_sha256': digest(job['identity']),
                    'completed_at_utc': utc_text(clock()), 'pid': os.getpid(),
                    'progress': 'completed', 'collector_status': result['status'],
                    'slot_id': result.get('slot_id'), 'recovery': recovery})
                if not lifetime.first_work.is_set():
                    if time.monotonic() >= lifetime.progress_deadline:
                        lifetime.progress('worker_startup_deadline_ended')
                        raise StartupError('startup_failed')
                    lifetime.progress('first_completed_work_observed')
                    lifetime.first_work.set()
                if result['status'] in ('blocked', 'budget_exhausted', 'window_ended'):
                    return result
                time.sleep(.1)
            return {'status': 'window_ended'}
    finally:
        # Keep the independent fence/deadline watchdog alive during SDK close.
        if collector is not None:
            collector.close()
        lifetime.close()


def run_identity(configuration_path, job_path, *, secret_stream=None, clock=None, secure_api=None):
    config = DailyWorkerConfiguration.load(configuration_path)
    with owned_role_lease(Path(config.publication.state_root)/'identity-owner.lock'):
        return _run_identity(configuration_path, job_path, secret_stream=secret_stream,
            clock=clock, secure_api=secure_api)


def _run_identity(configuration_path, job_path, *, secret_stream=None, clock=None, secure_api=None):
    _silence_sdk_output()
    config = DailyWorkerConfiguration.load(configuration_path)
    root = Path(config.publication.state_root)
    job = unseal(read_json(job_path))
    if (set(job) != {'contract', 'invocation', 'token', 'configuration_sha256', 'started_at_utc'}
            or job['contract'] != 'daily-identity-process-v1'
            or job['configuration_sha256'] != digest(config.payload())
            or Path(job_path) != root/(job['token']+'.identity.json')):
        raise ValueError('Daily identity job differs')
    binding = read_json(root/'driver-binding.json')
    clock = clock or (lambda: datetime.now(timezone.utc))
    lifetime = _Lifetime(config, binding, token=job['token'], invocation=job['invocation'],
        stop_path=root/(job['token']+'.stop'), clock=clock, identity=True)
    lifetime.start()
    client = None
    try:
        client = lifetime.authenticate(sys.stdin.buffer if secret_stream is None else secret_stream, secure_api)
        completed = 0
        while clock() < timestamp(config.collector.stop_at_utc):
            lifetime.fence()
            path = root/(job['token']+'.request.json')
            if not path.exists():
                time.sleep(.02); continue
            request = unseal(read_json(path))
            if (set(request) != {'token', 'invocation', 'sequence', 'symbols', 'fields'}
                    or request['token'] != job['token'] or request['invocation'] != job['invocation']
                    or type(request['sequence']) is not int or not completed <= request['sequence'] <= completed+1
                    or request['sequence'] > config.collector.daily_binding['policy']['limits']['maximum_identity_quote_calls']
                    or len(request['symbols']) != 1 or request['fields'] != 'all'):
                raise ValueError('Daily identity request differs')
            if request['sequence'] == completed:
                time.sleep(.02); continue
            lifetime.fence()
            response = client.quotes(request['symbols'], fields='all')
            value = {'token': job['token'], 'invocation': job['invocation'],
                'configuration_sha256': job['configuration_sha256'], 'sequence': request['sequence'],
                'status': 'completed', 'status_code': response.status_code, 'ok': response.ok,
                'quotes': response.json()}
            atomic_json(root/(job['token']+f'.response{request["sequence"]}.json'), sealed(value))
            completed += 1
            if client.halt_reason:
                return
    finally:
        if client is not None:
            client.close()
        lifetime.close()


def run_report(configuration_path, job_path):
    """Read-only native audit/replay after owned producers have stopped."""
    from mb_market_data.quote_journal_audit import audit_quote_journal
    from mb_market_data.quote_journal_replay import QuoteJournalReplayReader
    job = read_json(job_path)
    raw = read_json(configuration_path)
    root = Path(raw['publication']['state_root'])
    if (job['configuration_sha256'] != digest(raw)
            or len(job['report_id']) != 32
            or Path(job_path) != root/'reports'/(job['report_id']+'.job.json')
            or Path(job['output']) != root/'reports'/(job['report_id']+'.json')):
        raise ValueError('Daily reporter configuration differs')
    path = Path(raw['collector']['journal_path'])
    audit = audit_quote_journal(path, audited_at=timestamp(job['audited_at_utc']))
    def replay():
        count = 0
        sha = hashlib.sha256()
        for event in QuoteJournalReplayReader(path).events():
            count += 1; sha.update((event.event_id+'\n').encode())
        return {'events': count, 'sequence_sha256': sha.hexdigest()}
    from .operating_plan import MULTI_PROFILE
    multi=raw['publication'].get('policy_profile')==MULTI_PROFILE
    integrity=None
    if multi:
        from .daily_epoch_integrity import verify_journal_content,replay_sequence_digest
        from .daily_collector import DailyCollectorSettings
        integrity=verify_journal_content(path,expected_settings=DailyCollectorSettings(**raw['collector']).payload())
        first,second=replay_sequence_digest(path),replay_sequence_digest(path)
    else:first,second=replay(),replay()
    value = {'contract': 'daily-hot-native-final-report-v1',
        'configuration_sha256': digest(raw), 'status': 'COMPLETE',
        'report_id': job['report_id'], 'invocation': job['invocation'], 'audited_at_utc': job['audited_at_utc'],
        'native_audit_passed': audit.passed, 'native_audit': asdict(audit),
        'hot_content_integrity':integrity,
        'validation_passed':audit.passed and first==second and (integrity is None or integrity['passed']),
        'replay_method':'native ordered event IDs; Hot payloads checked separately' if multi else 'native full event reader',
        'first_replay': first, 'second_replay': second, 'two_fresh_replays_equal': first == second,
        'full_day_capacity_qualified': False, 'production_activation_inferred': False}
    # Native audit dataclasses contain date/datetime values.
    import json
    value = json.loads(json.dumps(value, default=str))
    atomic_json(Path(job['output']), sealed(value))


def main():
    try:
        if len(sys.argv) != 4:
            return 64
        role, configuration, job = sys.argv[1:]
        if role == 'collector': run_collector(configuration, job)
        elif role == 'identity': run_identity(configuration, job)
        elif role == 'report': run_report(configuration, job)
        else: return 64
        return 0
    except KeyboardInterrupt:
        return 130
    except BaseException:
        return 70


if __name__ == '__main__':
    raise SystemExit(main())
