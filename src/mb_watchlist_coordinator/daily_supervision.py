"""Durable daily process ownership, private credential pipes and provider fences."""
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import threading
import time
import uuid

from .authenticated_startup import AuthStartupSettings, SessionPassword, StartupError
from .controller_bootstrap import strict_json
from .daily_collector import DailyCollectorSettings
from .daily_session import DailySettings, regular_path
from .recovery_workers import ManagedRecoveryWorker, atomic_json, next_future_slot, _write_handoff, HOT_SECONDS
from .sampling_requests import canonical, digest, plain, timestamp, utc_text
from .sampling_service import ServiceBusy, owner_lock

CONTRACT = 'daily-hot-controller-v1'


def read_json(path):
    path = regular_path(path, exists=True)
    if path.stat().st_size > 2_000_000:
        raise ValueError('Oversized daily process evidence')
    return strict_json(path.read_text(encoding='utf-8'))


def sealed(value):
    return dict(value, content_sha256=digest(value))


def unseal(value):
    value = dict(value)
    sha = value.pop('content_sha256')
    if digest(value) != sha:
        raise ValueError('Daily process evidence checksum differs')
    return value


@dataclass(frozen=True)
class DailyWorkerConfiguration:
    publication: DailySettings
    catalog_path: str
    collector: DailyCollectorSettings
    authentication: AuthStartupSettings

    def payload(self):
        self.collector.payload()
        self.authentication.payload()
        if (self.publication.preview() != plain(self.collector.daily_binding)
                or self.collector.journal_path != self.publication.journal_path
                or timestamp(self.authentication.stop_at_utc) != timestamp(self.collector.stop_at_utc)
                or self.authentication.request_timeout_seconds != 3
                or self.authentication.startup_timeout_seconds != 8):
            raise ValueError('Daily authentication/window/publication configuration differs')
        regular_path(self.catalog_path)
        return {'contract': CONTRACT, **asdict(self)}

    @classmethod
    def load(cls, path):
        raw = read_json(path)
        if set(raw) != {'contract', 'publication', 'catalog_path', 'collector', 'authentication'} or raw['contract'] != CONTRACT:
            raise ValueError('Daily worker configuration differs')
        result = cls(DailySettings(**raw['publication']), raw['catalog_path'],
            DailyCollectorSettings(**raw['collector']), AuthStartupSettings(**raw['authentication']))
        if result.payload() != raw:
            raise ValueError('Noncanonical daily configuration')
        return result


class DailyProcessState:
    """Small sealed state: at most three charged starts; never reset on reopen."""
    def __init__(self, root, identity):
        self.root, self.identity = Path(root), plain(identity)
        self.path, self.lock = self.root/'driver-state.json', self.root/'driver-state.lock'

    def read(self):
        s = unseal(read_json(self.path))
        if (set(s) != {'contract', 'identity_sha256', 'active_invocation', 'invocations',
                'starts', 'hold_until_utc', 'terminal', 'initialized', 'stop'}
                or s['contract'] != CONTRACT or s['identity_sha256'] != digest(self.identity)
                or len(s['starts']) > 3 or len(s['invocations']) > 3):
            raise ValueError('Original daily process state differs')
        for i, start in enumerate(s['starts'], 1):
            if start['generation'] != i or len(start['token']) != 32:
                raise ValueError('Daily worker start history differs')
        return s

    def change(self, edit):
        with owner_lock(self.lock):
            s = self.read()
            edit(s)
            atomic_json(self.path, sealed(s))
            return self.read()

    def create(self):
        if self.path.exists():
            raise ValueError('Original daily process state already exists')
        atomic_json(self.path, sealed({'contract': CONTRACT, 'identity_sha256': digest(self.identity),
            'active_invocation': None, 'invocations': [], 'starts': [], 'hold_until_utc': None,
            'terminal': None, 'initialized': False, 'stop': None}))


def validate_daily_job(configuration_path, job_path):
    config = DailyWorkerConfiguration.load(configuration_path)
    path = regular_path(job_path, exists=True)
    job = read_json(path)
    body = dict(job); sha = body.pop('content_sha256')
    identity = job['identity']
    root = Path(config.publication.state_root)
    binding = read_json(root/'driver-binding.json')
    if (digest(body) != sha or identity['contract'] != 'daily-recovery-worker-v1'
            or identity['role'] != 'daily_hot' or identity['max_starts'] != 3
            or identity['startup_seconds'] != 3 or identity['stale_seconds'] != 3
            or identity['startup_context'] != {'contract': 'anonymous-stdin-secret-v1',
                'configuration_sha256': digest(config.payload())}
            or identity['binding'] != binding
            or binding['configuration_sha256'] != digest(config.payload())
            or identity['command'] != binding['commands']['collector']
            or type(job['generation']) is not int or not 1 <= job['generation'] <= 3
            or job['no_past_slot_catchup'] is not True
            or job['experimental_hot_seconds'] != list(HOT_SECONDS)
            or job['first_eligible_slot_utc'] != next_future_slot(timestamp(job['resume_after_utc'])).isoformat()):
        raise ValueError('Daily collector job binding differs')
    workers = root/'workers'
    for key, expected in {'job_path': workers/(job['token']+'.job.json'),
            'registry_path': workers/'worker.json', 'lease_path': workers/'worker.lock',
            'heartbeat_path': workers/(job['token']+'.heartbeat.json'),
            'stop_path': workers/(job['token']+'.stop')}.items():
        if Path(job[key]) != expected or path != Path(job['job_path']):
            raise ValueError('Daily worker job path differs')
    if read_json(workers/'worker.json') != job:
        raise ValueError('Daily worker registry differs')
    return config, job, binding


def assert_controller_fence(config, binding, token, invocation, *, clock):
    root = Path(config.publication.state_root)
    if read_json(root/'driver-binding.json') != binding:
        raise ValueError('Daily controller identity changed')
    s = DailyProcessState(root, binding).read()
    guard = unseal(read_json(root/'driver-live.json'))
    if (s['active_invocation'] != invocation or s['terminal'] or s['stop']
            or guard['identity_sha256'] != digest(binding) or guard['invocation'] != invocation
            or guard['state'] != 'RUNNING'
            or not 0 <= (clock()-timestamp(guard['observed_at_utc'])).total_seconds() < 3
            or clock() >= timestamp(config.collector.stop_at_utc)
            or token and not any(e['token'] == token and e['invocation'] == invocation for e in s['starts'])):
        raise ValueError('Daily controller stopped, stale or generation fenced')
    lock = regular_path(root/'driver-owner.lock', exists=True)
    try:
        with owner_lock(lock):
            pass
    except ServiceBusy:
        return True
    raise ValueError('Daily controller owner is absent')


class _Handoff:
    def __init__(self, owner, password):
        self.owner, self.password, self.identity = owner, password, password.identity

    def frame(self, token):
        def reserve(s):
            if s['terminal'] or s['stop'] or len(s['starts']) >= 3:
                raise ValueError('Daily worker budget exhausted or stopped')
            s['starts'].append({'token': token, 'generation': len(s['starts'])+1,
                'invocation': s['active_invocation'], 'reserved_at_utc': utc_text(self.owner.clock()),
                'exit_observed_at_utc': None})
        self.owner.state.change(reserve)  # Charge before writing a job or creating a process.
        return self.password.frame(token)


class DailyManagedWorker(ManagedRecoveryWorker):
    def __init__(self, root, *, command, binding, state, password, clock, monotonic=time.monotonic):
        self.state, self.hold_monotonic = state, None
        super().__init__(root, role='experimental_hot', command=command, binding=binding,
            startup_handoff=_Handoff(self, password), clock=clock, monotonic=monotonic)
        self.identity.update(contract='daily-recovery-worker-v1', role='daily_hot',
            qualification='daily_native_collector_supervision')

    def confirm_exit(self):
        at = self.clock()
        job = self._job()
        if job is None or self.last_exit is None or self.last_exit['token']!=job['token']:
            raise ValueError('Confirmed owned exit must match the original reserved job')
        def edit(s):
            if job:
                e = s['starts'][job['generation']-1]
                if e['token'] != job['token']:
                    raise ValueError('Daily exit token differs')
                e['exit_observed_at_utc'] = utc_text(at)
            s['hold_until_utc'] = utc_text(at+timedelta(seconds=15))
        self.state.change(edit)
        self.hold_monotonic = self.monotonic()+15

    def ensure(self, *, start_allowed, resume_after_utc):
        s = self.state.read()
        job = self._job()
        if len(s['starts']) != (job['generation'] if job else 0):
            return {'status': 'BLOCKED', 'reason': 'original_worker_start_evidence_missing'}
        if self.child is not None and self.child.poll() is not None:
            self._reap_owned('exited_before_health_check')
            self.confirm_exit()
            s = self.state.read()
        hold = s['hold_until_utc']
        if hold and (self.clock() < timestamp(hold) or
                self.hold_monotonic is not None and self.monotonic() < self.hold_monotonic):
            return {'status': 'REPLACEMENT_HOLD', 'hold_until_utc': hold, 'minimum_elapsed_seconds': 15}
        if s['terminal'] or s['stop']:
            return {'status': 'BLOCKED', 'reason': s['terminal'] or 'stopped'}
        old_exit = self.last_exit
        # If a child exists at entry, this call may only inspect/reap it. The
        # base helper has its own poll; an exit between the two polls must not
        # let it launch a replacement before we record the original exit/hold.
        had_owned_child=self.child is not None
        result = super().ensure(start_allowed=start_allowed and not had_owned_child,
            resume_after_utc=utc_text(max(timestamp(resume_after_utc), self.clock())))
        if result.get('reason')=='owned_child_not_holding_required_lease' and self.child is not None:
            # OS lease release can precede the process handle becoming signaled.
            # Only this known handle may confirm exit. No signal, discovery,
            # heartbeat adoption, deadline reset or replacement is allowed here.
            try:self.child.wait(timeout=.05)
            except subprocess.TimeoutExpired:return result
            self._reap_owned('exit_confirmed_after_lease_release')
            result={'status':'REPLACEMENT_HOLD'}
        if self.last_exit is not old_exit:
            self.confirm_exit()
            if result['status'] not in ('BLOCKED','EXTERNAL_HEALTHY'):
                current=self.state.read()
                return {'status':'REPLACEMENT_HOLD','hold_until_utc':current['hold_until_utc'],
                    'minimum_elapsed_seconds':15,'previous_worker_exit':dict(self.last_exit)}
        if result['status'] == 'EXTERNAL_HEALTHY':
            return {'status': 'BLOCKED', 'reason': 'unowned_worker_not_adopted'}
        return result


class IdentityResponse:
    text = 'Identity request failed'
    def __init__(self, value):
        self.status_code, self.ok = value['status_code'], value['ok']
        self.value = value['quotes']
    def json(self):
        return self.value


def stop_process(child, *, cooperative=.5):
    if child is None:
        return {'returncode': None, 'forced': False}
    forced = False
    try:
        child.wait(timeout=cooperative)
    except subprocess.TimeoutExpired:
        forced = True
        child.terminate()
        try:
            child.wait(timeout=1)
        except subprocess.TimeoutExpired:
            child.kill(); child.wait(timeout=2)
    return {'returncode': child.returncode, 'forced': forced}


class DailyIdentityClient:
    """Three bounded identity requests to one owned authenticated child."""
    def __init__(self, root, command, *, password, invocation, configuration_sha256,
                 clock, stop_requested=lambda: False):
        self.root, self.command = Path(root), tuple(command)
        self.password, self.invocation, self.clock = password, invocation, clock
        self.configuration_sha256, self.stop_requested = configuration_sha256, stop_requested
        self.child, self.token, self.calls = None, uuid.uuid4().hex, 0
        self.job = {'contract': 'daily-identity-process-v1', 'invocation': invocation,
            'token': self.token, 'configuration_sha256': configuration_sha256,
            'started_at_utc': utc_text(clock())}

    def start(self):
        self.path = self.root/(self.token+'.identity.json')
        atomic_json(self.path, sealed(self.job))
        frame = self.password.frame(self.token)
        self.child = subprocess.Popen([*self.command, str(self.path)], stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        outcome = {}
        threading.Thread(target=_write_handoff, args=(self.child.stdin, frame, outcome), daemon=True).start()
        try:
            value = self._wait(self.root/(self.token+'.ready.json'), 8)
            if value.get('status') != 'credentials_accepted':
                raise StartupError('credentials_unavailable')
        except BaseException:
            self.close(); raise

    def _wait(self, path, seconds):
        deadline = time.monotonic()+seconds
        while time.monotonic() < deadline:
            if path.is_file():
                value = unseal(read_json(path))
                if (value['token'] != self.token or value['invocation'] != self.invocation
                        or value['configuration_sha256'] != self.configuration_sha256):
                    raise ValueError('Identity process receipt differs')
                return value
            if self.stop_requested() or self.child.poll() is not None:
                raise StartupError('provider_failed')
            time.sleep(.01)
        raise StartupError('provider_failed')

    def quotes(self, symbols, *, fields):
        if self.calls >= 3 or len(symbols) != 1 or fields != 'all' or self.stop_requested():
            raise StartupError('provider_failed')
        self.calls += 1
        request = {'token': self.token, 'invocation': self.invocation,
            'sequence': self.calls, 'symbols': list(symbols), 'fields': fields}
        atomic_json(self.root/(self.token+'.request.json'), sealed(request))
        try:
            value = self._wait(self.root/(self.token+f'.response{self.calls}.json'), 3)
            if value['sequence'] != self.calls or value['status'] != 'completed':
                raise StartupError('provider_failed')
            return IdentityResponse(value)
        except BaseException:
            self.close(); raise

    def close(self):
        if self.child is not None:
            (self.root/(self.token+'.stop')).write_text(self.token)
            result = stop_process(self.child)
            self.child = None
            return result
        return {'returncode': None, 'forced': False}
