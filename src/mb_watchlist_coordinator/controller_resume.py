"""Explicit human-started reopen; never reset a partial/missing experiment.

Synchronous library API inside an owned, independently bounded process. The
original bootstrap/runtime records remain immutable; new resume receipts have
their own ledger and stop paths. No live launcher or outer profile harness.
"""
from contextlib import ExitStack, closing
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
import sqlite3
import time
from types import SimpleNamespace

from .authenticated_startup import (AuthStartupSettings, SessionPassword, StartupError,
    prepare_authenticated_client)
from .catalog_startup import CatalogStartupLedger, bind_catalog
from .controller_bootstrap import BootstrapSettings, BootstrapSession, EXPECTED_HELPERS, OWNER, strict_json
from .integrated_catalog import DirectoryCatalog
from .integrated_identity import IdentityGatedDelivery
from .integrated_runtime import IntegratedRuntime, _PreparedDelivery, _RuntimeWorker
from .installed_startup_probe import inspect_dependencies
from .recovery_workers import ManagedRecoveryWorker, atomic_json
from .sampling_requests import canonical, digest, freeze, plain, timestamp, utc_text
from .sampling_service import owner_lock, ServiceBusy
from .supervised_hot_worker import progress_receipt

CONTRACT = 'manual-authenticated-controller-resume-v1'
CODES = frozenset(('configuration_invalid', 'state_invalid', 'ownership_busy',
    'dependency_rejected', 'resume_deadline_ended', 'worker_not_quiescent',
    'terminal_evidence', 'budget_exhausted', 'resume_failed', 'operator_interrupted'))


class ResumeError(RuntimeError):
    def __init__(self, code):
        self.code = code if code in CODES else 'resume_failed'
        super().__init__(self.code)


@dataclass(frozen=True)
class ResumeSettings:
    experiment_root: str
    original_configuration_sha256: str
    original_runtime_sha256: str
    submitted_at_utc: str
    nonce: str
    worker_command: tuple[str, ...]

    def public(self):
        root = Path(self.experiment_root)
        if (not root.is_absolute() or root != root.resolve() or not root.is_dir()
                or not root.name.startswith('integrated_hot_')
                or any(p.lower().startswith('quote_observation_journal') for p in root.parts)
                or not re.fullmatch('[0-9a-f]{32}', self.nonce)
                or any(not re.fullmatch('[0-9a-f]{64}', h) for h in
                    (self.original_configuration_sha256, self.original_runtime_sha256))
                or type(self.worker_command) is not tuple or not self.worker_command
                or any(type(s) is not str or not s for s in self.worker_command)):
            raise ResumeError('configuration_invalid')
        timestamp(self.submitted_at_utc)
        return {'contract': CONTRACT, **self.__dict__, 'worker_command': list(self.worker_command)}


def _file(path, maximum=2_000_000):
    path = Path(path)
    if not path.is_file() or path.is_symlink() or path.stat().st_size > maximum:
        raise ResumeError('state_invalid')
    return strict_json(path.read_text(encoding='utf-8'))


def _count_record(value):
    limits={'directory_source_permits':2,'feed_attempts':10,'identity_quote_permits':3,
        'hot_quote_permits':60,'worker_starts':3}
    if (set(value)!=set(limits)|{'selected_symbol'}
            or any(type(value[k]) is not int or not 0<=value[k]<=n for k,n in limits.items())
            or value['directory_source_permits']!=2
            or value['selected_symbol'] is not None and (not value['identity_quote_permits']
                or not re.fullmatch('[A-Z][A-Z0-9]{0,9}',value['selected_symbol']))):
        raise ResumeError('state_invalid')


class ResumeLedger:
    """Separate attempt history; no directory/feed/quote permits originate here."""
    def __init__(self, root, binding, *, clock):
        self.root, self.path, self.marker = root, root/'resume.sqlite3', root/'resume-binding.json'
        self.identity = {'contract': CONTRACT, 'runtime_sha256': digest(binding),
            'configuration_sha256': binding['configuration_sha256'],
            'start_at_utc': binding['start_at_utc'], 'stop_at_utc': binding['stop_at_utc']}
        self.clock = clock

    def initialize(self):
        if self.path.exists() or self.marker.exists():
            if _file(self.marker) != self.identity or not self.path.is_file() or self.path.is_symlink():
                raise ResumeError('state_invalid')
        else:
            # Marker first: a crash cannot turn a partial resume ledger into a
            # fresh empty history on the next attempt.
            with self.marker.open('x', encoding='utf-8') as out:
                out.write(canonical(self.identity)); out.flush()
                import os
                os.fsync(out.fileno())
            with self.path.open('xb'): pass
            with closing(self._connect(True)) as c, c:
                c.execute('CREATE TABLE resume_identity(id INTEGER PRIMARY KEY CHECK(id=1),payload TEXT NOT NULL)')
                c.execute('INSERT INTO resume_identity VALUES(1,?)', (canonical(self.identity),))
                c.execute('CREATE TABLE resume_event(sequence INTEGER PRIMARY KEY,payload TEXT NOT NULL)')
        return self.snapshot()

    def _connect(self, write=False):
        if self.path.is_symlink(): raise ResumeError('state_invalid')
        return sqlite3.connect(self.path.resolve().as_uri()+('?mode=rw' if write else '?mode=ro'), uri=True, timeout=5)

    def _read(self, c):
        if (_file(self.marker) != self.identity
                or c.execute('SELECT payload FROM resume_identity WHERE id=1').fetchone() != (canonical(self.identity),)):
            raise ResumeError('state_invalid')
        events, states, submissions, previous, last = [], {}, {}, digest(self.identity), None
        original=_file(self.root/'runtime-binding.json')
        if digest(original)!=self.identity['runtime_sha256']:raise ResumeError('state_invalid')
        for n, raw in c.execute('SELECT * FROM resume_event ORDER BY sequence'):
            e = strict_json(raw); body = dict(e); sha = body.pop('event_sha256')
            at = timestamp(e['at_utc']); nonce = e['nonce']; prior = states.get(nonce)
            if (set(e) != {'sequence','kind','nonce','at_utc','data','previous_sha256','event_sha256'}
                    or canonical(e) != raw or e['sequence'] != n or n != len(events)+1
                    or not re.fullmatch('[0-9a-f]{32}', nonce) or e['previous_sha256'] != previous
                    or digest(body) != sha or last is not None and at < last):
                raise ResumeError('state_invalid')
            if e['kind'] == 'requested':
                if prior is not None or set(e['data']) != {'submission','original_counts'}:
                    raise ResumeError('state_invalid')
                submission = e['data']['submission']
                value = dict(submission); value['worker_command'] = tuple(value['worker_command']); value.pop('contract')
                settings = ResumeSettings(**value)
                if (settings.public() != submission or settings.nonce != nonce
                        or settings.experiment_root != str(self.root)
                        or list(settings.worker_command) != original['worker_command']
                        or settings.original_runtime_sha256 != self.identity['runtime_sha256']
                        or settings.original_configuration_sha256 != self.identity['configuration_sha256']
                        or not timestamp(settings.submitted_at_utc) <= at < min(
                            timestamp(settings.submitted_at_utc)+timedelta(seconds=60), timestamp(self.identity['stop_at_utc']))):
                    raise ResumeError('state_invalid')
                _count_record(e['data']['original_counts'])
                submissions[nonce]=e
            elif (e['kind'], prior) not in {
                    ('authenticated','requested'), ('ready','authenticated'),
                    ('failed','requested'), ('failed','authenticated'),
                    ('abandoned','requested'), ('abandoned','authenticated'), ('abandoned','ready'),
                    ('stopped','ready')}:
                raise ResumeError('state_invalid')
            if e['kind'] in ('authenticated','abandoned') and e['data']!={}:raise ResumeError('state_invalid')
            if e['kind']=='ready':
                data=e['data'];submission=submissions[nonce]
                if (set(data)!={'counts','native_recovery','full_manual_controller_resume','outer_profile_harness_qualified'}
                        or data['full_manual_controller_resume'] is not True or data['outer_profile_harness_qualified'] is not False
                        or at>=min(timestamp(submission['data']['submission']['submitted_at_utc'])+timedelta(seconds=60),
                            timestamp(self.identity['stop_at_utc']))):raise ResumeError('state_invalid')
                _count_record(data['counts'])
                before=submission['data']['original_counts']
                if (data['counts']['selected_symbol']!=before['selected_symbol']
                        or any(data['counts'][k]<before[k] for k in before if k!='selected_symbol')):
                    raise ResumeError('state_invalid')
            if e['kind']=='stopped' and (set(e['data'])!={'stop_receipt'}
                    or e['data']['stop_receipt'].get('status')!='STOPPED'):
                raise ResumeError('state_invalid')
            if e['kind'] == 'failed' and e['data'] not in ({'code': code} for code in CODES | {'credentials_rejected'}):
                raise ResumeError('state_invalid')
            events.append(e); states[nonce] = e['kind']; previous, last = sha, at
        return events, states, previous

    def snapshot(self):
        with closing(self._connect()) as c:
            c.execute('BEGIN'); events, states, head = self._read(c)
        return freeze({'events': events, 'states': states, 'head_sha256': head})

    def append(self, kind, nonce, data=None):
        with closing(self._connect(True)) as c, c:
            c.execute('BEGIN IMMEDIATE'); events, _, previous = self._read(c)
            e = {'sequence': len(events)+1, 'kind': kind, 'nonce': nonce,
                'at_utc': utc_text(self.clock()), 'data': data or {}, 'previous_sha256': previous}
            e['event_sha256'] = digest(e)
            c.execute('INSERT INTO resume_event VALUES(?,?)', (e['sequence'], canonical(e)))
            self._read(c)
        return freeze(e)


def _restore(settings, clock):
    """Read-only reconstruction. None of the native initialize/create APIs run."""
    from mb_market_data.quote_observation_store import QuoteObservationStore
    from .sampling_projection import SamplingMembership
    from .sampling_policy import SamplingPolicy
    from .sampling_request_store import SamplingRequestStore
    from .sampling_journal import SamplingJournal
    from .sampling_service import SamplingPublicationService, PublicationSettings
    from .nasdaq_sampling import NasdaqSamplingProducer, HaltProducerSettings
    from .nasdaq_recovery import NasdaqRecoveryReceipts, RecoverySettings, RecoveryQuery
    from .nasdaq_recovery_delivery import NasdaqRecoveryDelivery
    from .nasdaq_feed_recovery import FeedRecoveryTransport, FeedLimits
    from .hot_recovery_collector import HotCollectorSettings, HotRecoveryCollector
    root = Path(settings.experiment_root)
    required = ('bootstrap.json','runtime-binding.json','authenticated-worker.json','directory.sqlite3',
        'quotes.sqlite3','requests.sqlite3','publication.sqlite3','feed.sqlite3','live.sqlite3',
        'recovery.sqlite3','delivery.sqlite3','identity.sqlite3','runtime.sqlite3',
        'quotes.hot.poller.sqlite3','quotes.hot.poller.recovery.json')
    if (any(not (root/p).is_file() or (root/p).is_symlink() for p in required)
            or not (root/'workers').is_dir() or (root/'workers').is_symlink()):
        raise ResumeError('state_invalid')
    receipt, binding, worker_config = (_file(root/n) for n in required[:3])
    if (receipt.get('status') != 'BOOTSTRAPPED_NOT_RUNNING'
            or receipt.get('configuration_sha256') != settings.original_configuration_sha256
            or digest(binding) != settings.original_runtime_sha256
            or binding['configuration_sha256'] != settings.original_configuration_sha256
            or tuple(binding['worker_command']) != settings.worker_command):
        raise ResumeError('state_invalid')
    raw = dict(receipt['configuration']['settings']); raw['catalog_symbols'] = tuple(raw['catalog_symbols'])
    preflight = BootstrapSettings(**raw).plan()
    if (preflight.settings.catalog_mode != 'owned_directory'
            or preflight.settings.experiment_root != str(root)
            or settings.nonce == preflight.settings.nonce):
        raise ResumeError('state_invalid')
    directory = CatalogStartupLedger(root/'directory.sqlite3', preflight=preflight.public, clock=clock)
    if directory.snapshot()['status'] != 'BOUND': raise ResumeError('state_invalid')
    catalog = DirectoryCatalog.load(root/'catalog'); plan = bind_catalog(preflight, catalog)
    if (plain(plan.public) != receipt['configuration'] or plan.configuration_sha256 != settings.original_configuration_sha256
            or receipt['preflight_configuration_sha256'] != preflight.configuration_sha256
            or receipt['worker_configuration_sha256'] != digest(worker_config)):
        raise ResumeError('state_invalid')
    auth = AuthStartupSettings(plan.settings.ecfg_path, plan.public['stop_at_utc'])
    if worker_config['authentication'] != auth.__dict__: raise ResumeError('state_invalid')
    s = BootstrapSession(); s.plan, s.receipt, s.catalog, s.catalog_ledger = plan, receipt, catalog, directory
    s.client = s.password = None; s.closed = False
    s.store = QuoteObservationStore(root/'quotes.sqlite3', session_date=plan.opening.session_date, schema_version=2)
    revisions = s.store.membership_revisions_in_effective_order()
    if not revisions or revisions[0].content_sha256 != receipt['initial_membership_sha256']:
        raise ResumeError('state_invalid')
    with closing(sqlite3.connect((root/'quotes.sqlite3').as_uri()+'?mode=ro', uri=True)) as c:
        if c.execute('SELECT count(*) FROM poll_run WHERE run_id=?', (receipt['native_run_id'],)).fetchone() != (1,):
            raise ResumeError('state_invalid')
    baseline = SamplingMembership(frozenset(plan.focus.uni_symbols), frozenset(plan.focus.focus_symbols), frozenset())
    s.requests = SamplingRequestStore(root/'requests.sqlite3', session_date=plan.opening.session_date,
        baseline=baseline, policy=SamplingPolicy('integrated-bootstrap-admin',0,0,'immediate_cap'), admission=plan.admission, clock=clock)
    s.requests.validated_history()
    s.service = SamplingPublicationService(root/'publication.sqlite3', request_store=s.requests, journal=SamplingJournal(s.store),
        settings=PublicationSettings('integrated-hot-recovery',1,.5,timestamp(plan.public['stop_at_utc'])), clock=clock)
    s.service.snapshot()
    query = RecoveryQuery(plan.opening.session_date, plan.opening.session_date)
    s.feed = FeedRecoveryTransport(root/'feed.sqlite3', session_date=plan.opening.session_date, queries=(query,), limits=FeedLimits(), clock=clock)
    s.feed.snapshot()
    s.live = NasdaqSamplingProducer(root/'live.sqlite3', request_store=s.requests,
        settings=HaltProducerSettings('nasdaq-observations-integrated',('LUDP','M'),'regular_close',False,False,'external'), clock=clock)
    s.live.snapshot()
    s.recovery = NasdaqRecoveryReceipts(root/'recovery.sqlite3', request_store=s.requests,
        settings=RecoverySettings(plan.opening.session_date,'late_start',(query,),False), clock=clock)
    s.recovery.snapshot()
    s.base_delivery = NasdaqRecoveryDelivery(root/'delivery.sqlite3', live_producer=s.live,
        recovery_receipts=s.recovery, producer_id=OWNER, clock=clock)
    s.base_delivery.snapshot()
    s.gated_delivery = IdentityGatedDelivery(root/'identity.sqlite3', delivery=s.base_delivery, catalog=catalog,
        start_at=plan.public['start_at_utc'], stop_at=plan.public['stop_at_utc'], clock=clock)
    s.gated_delivery.snapshot(); s.delivery = s.gated_delivery
    collector_settings = HotCollectorSettings(str(root/'quotes.sqlite3'), plain(s.service.identity),
        plan.public['start_at_utc'], plan.public['stop_at_utc'], max_quote_calls=60, max_symbols=1)
    if worker_config['collector'] != collector_settings.__dict__: raise ResumeError('state_invalid')
    s.collector = HotRecoveryCollector(collector_settings, client_factory=lambda: s.client, clock=clock)
    s.collector._check(); s.collector.poller.snapshot()
    return s, binding


class ResumedRuntime(IntegratedRuntime):
    """Original runtime identity with a separate manual-reopen lifetime record."""
    def initialize_saved(self, *, lease, ledger, settings):
        from .nasdaq_recovery_supervisor import NasdaqRecoverySupervisor
        if self.initialized or self.closed: raise ResumeError('state_invalid')
        self.lease, self.resume_ledger, self.resume_settings = lease, ledger, settings
        self.stop_path = self.root/('resume-'+settings.nonce+'.stop.json')
        if self.stop_path.exists(): raise ResumeError('state_invalid')
        if plain(self.identity) != _file(self.binding_path): raise ResumeError('state_invalid')
        self.initialized = True
        s = self.session
        gate = IdentityGatedDelivery(s.gated_delivery.gate_path, delivery=s.base_delivery, catalog=s.catalog,
            start_at=utc_text(self.start), stop_at=utc_text(self.stop), clock=self.clock,
            monotonic=self.monotonic, stop_requested=self.stopped)
        gate.initialize()
        self.delivery = _PreparedDelivery(self, gate)
        self.managed = ManagedRecoveryWorker(self.root/'workers', role='experimental_hot', command=self.command,
            binding=plain(s.service.identity), max_starts=3, startup_seconds=3, stale_seconds=3,
            clock=self.clock, monotonic=self.monotonic, startup_handoff=s.password)
        self.worker = _RuntimeWorker(self, self.managed)
        self.authority = NasdaqRecoverySupervisor(self.root/'runtime.sqlite3', feed_client=self.feed_client,
            delivery=self.delivery, service=s.service, worker=self.worker, clock=self.clock)
        self.authority.initialize()
        self.validate()

    def validate(self):
        super().validate()
        if hasattr(self, 'resume_ledger'):
            state = self.resume_ledger.snapshot()['states'].get(self.resume_settings.nonce)
            if state not in ('authenticated','ready'):
                raise ResumeError('state_invalid')
        return True

    def close(self, *, reason='operator_stop'):
        was_closed = self.closed
        value = super().close(reason=reason)
        if not was_closed and hasattr(self, 'resume_ledger'):
            state = self.resume_ledger.snapshot()['states'].get(self.resume_settings.nonce)
            if state == 'ready':
                self.resume_ledger.append('stopped', self.resume_settings.nonce, {'stop_receipt': plain(value)})
        return value


def _counts(session, managed):
    native = session.collector.poller.snapshot(); gate = session.gated_delivery.snapshot()['identity_gate']
    feed = session.feed.snapshot(); job = managed._job()
    return {'directory_source_permits': session.catalog_ledger.snapshot()['reserved_source_permits'],
        'feed_attempts': len(feed['attempts'])+bool(feed['pending']),
        'identity_quote_permits': gate['quote_permits'], 'selected_symbol': gate['selected_symbol'],
        'hot_quote_permits': sum(e['kind']=='dispatch' and bool(e['symbols']) for e in native['events']),
        'worker_starts': job['generation'] if job else 0}


def _generation_history(managed):
    if managed.registry.is_symlink():raise ResumeError('state_invalid')
    job = managed._job()
    files = sorted(managed.root.glob('*.job.json'))
    jobs = [_file(p) for p in files]
    if (job is None and jobs or job and (len(jobs) != job['generation']
            or sorted(j['generation'] for j in jobs) != list(range(1,job['generation']+1)))):
        raise ResumeError('state_invalid')
    for old in jobs:
        body = dict(old); sha = body.pop('content_sha256')
        if (old['identity'] != managed.identity or sha != digest(body)
                or old['job_path']!=str((managed.root/(old['token']+'.job.json')).resolve())
                or not re.fullmatch('[0-9a-f]{32}',old['token'])): raise ResumeError('state_invalid')
    return job


def _previous_progress(managed, job, clock):
    if not job: return
    first = progress_receipt(job)
    auth = _file(managed.root/(job['token']+'.auth.json'))
    if (first['status'] != 'first_completed_work_observed'
            or set(auth) != {'contract','token','configuration_sha256','status','observed_at_utc'}
            or auth['contract'] != 'authenticated-hot-startup-v1' or auth['token'] != job['token']
            or auth['configuration_sha256'] != job['identity']['startup_context']['configuration_sha256']
            or auth['status'] != 'credentials_accepted'
            or not timestamp(job['started_at_utc']) <= timestamp(auth['observed_at_utc']) <= clock()):
        raise ResumeError('terminal_evidence')
    heartbeat = Path(job['heartbeat_path'])
    if heartbeat.exists():
        beat = _file(heartbeat)
        if (beat.get('token') != job['token'] or beat.get('generation') != job['generation']
                or beat.get('identity_sha256') != digest(job['identity']) or beat.get('pid') != first['pid']
                or timestamp(beat['completed_at_utc'])>clock()):
            raise ResumeError('state_invalid')
        if beat.get('collector_status') in ('blocked','budget_exhausted','window_ended','bounded_deadline_ended'):
            raise ResumeError('terminal_evidence')


def resume_manual(settings, password, *, feed_factory, clock=None, monotonic=time.monotonic,
                  sleep=time.sleep, inventory=None, secure_api=None, fault_hook=None):
    """Prepare a new human-started controller; never perform a feed/quote call.

    The original controller lease spans validation, authentication and reopening.
    Orphan children are fenced through their existing protocol, never PID-killed.
    A separately owned process must preempt blocking credential/native calls.
    """
    clock = clock or (lambda: datetime.now(timezone.utc))
    lease = session = runtime = ledger = None; transferred = False; nonce = settings.nonce
    original_stop = None
    begun = monotonic()
    def check():
        now = clock()
        stop = original_stop or timestamp(settings.submitted_at_utc)+timedelta(seconds=60)
        if (not timestamp(settings.submitted_at_utc) <= now < min(stop,timestamp(settings.submitted_at_utc)+timedelta(seconds=60))
                or monotonic()-begun >= 60): raise ResumeError('resume_deadline_ended')
    def stage(name):
        if fault_hook: fault_hook(name)
        check()
    def acquire(path, stack):
        while True:
            check()
            context = owner_lock(path)
            try: context.__enter__()
            except ServiceBusy: sleep(.01); continue
            stack.callback(context.__exit__,None,None,None); return
    def read_saved():
        from mb_market_data.sampling_acquisition import AcquisitionBusy
        while True:
            check()
            try:return _restore(settings,clock)
            except (ServiceBusy,AcquisitionBusy):
                # An orphan native worker can finish its current bounded
                # request while preflight reads. This waits for a read lease;
                # it never repeats a provider call or renews a deadline.
                sleep(.01)
    try:
        settings.public(); check()
        if not isinstance(password,bytearray) or not password: raise StartupError('credentials_unavailable')
        root = Path(settings.experiment_root)
        original_binding=_file(root/'runtime-binding.json')
        if digest(original_binding)!=settings.original_runtime_sha256:raise ResumeError('state_invalid')
        original_stop=timestamp(original_binding['stop_at_utc'])
        check()
        lease = owner_lock(root/'controller.owner.lock')
        try: lease.__enter__()
        except ServiceBusy: lease = None; raise ResumeError('ownership_busy') from None
        session,binding = read_saved()
        if clock() < timestamp(session.plan.settings.password_submitted_at_utc): raise ResumeError('state_invalid')
        check()
        observed = (inventory or inspect_dependencies)(EXPECTED_HELPERS)
        if observed.get('qualified') is not True or digest(observed) != session.plan.settings.dependency_sha256:
            raise ResumeError('dependency_rejected')
        # A disposable reader exposes the original worker identity but owns no
        # handle, secret or additional native run.
        reader = ManagedRecoveryWorker(root/'workers',role='experimental_hot',command=settings.worker_command,
            binding=plain(session.service.identity),max_starts=3,startup_seconds=3,stale_seconds=3,clock=clock,
            startup_handoff=SimpleNamespace(identity={'contract':'anonymous-stdin-secret-v1',
                'configuration_sha256':digest(_file(root/'authenticated-worker.json'))}))
        job = _generation_history(reader)
        before = _counts(session,reader)
        if before['worker_starts'] >= 3 or before['hot_quote_permits'] >= 60: raise ResumeError('budget_exhausted')
        if session.gated_delivery.snapshot()['identity_gate']['provider_stop_required']: raise ResumeError('terminal_evidence')
        stop_files = [root/'runtime-stop.json', *root.glob('resume-*.stop.json')]
        for p in stop_files:
            if not p.exists():continue
            stop_record=_file(p)
            if timestamp(stop_record['acquisition_stop_requested_at_utc'])>clock():raise ResumeError('state_invalid')
            if stop_record.get('reason') in ('identity_provider_stop_required','controller_provider_stopped',
                    'worker_credentials_rejected','worker_startup_deadline_ended','native_blocked',
                    'native_budget_exhausted','native_window_ended','native_bounded_deadline_ended'):
                raise ResumeError('terminal_evidence')
        ledger = ResumeLedger(root,binding,clock=clock); state=ledger.initialize()
        if nonce in state['states']: raise ResumeError('configuration_invalid')
        for prior,kind in state['states'].items():
            if kind in ('requested','authenticated','ready'): ledger.append('abandoned',prior)
        ledger.append('requested',nonce,{'submission':settings.public(),'original_counts':before})
        stage('resume_reserved')
        auth = AuthStartupSettings(session.plan.settings.ecfg_path,session.plan.public['stop_at_utc'])
        session.client = prepare_authenticated_client(auth,password,clock=clock,secure_api=secure_api)
        stage('credentials_accepted')
        ledger.append('authenticated',nonce)
        session.password = SessionPassword(password,digest(_file(root/'authenticated-worker.json')))
        with ExitStack() as fences:
            if job:
                p=Path(job['stop_path'])
                if not p.exists():
                    with p.open('x',encoding='ascii') as out: out.write(job['token'])
            acquire(reader.lease,fences)
            acquire(session.feed.path.with_suffix('.controller.lock'),fences)
            acquire(session.feed.path.with_suffix('.network.lock'),fences)
            acquire(root/'runtime.owner.lock',fences)
            # Publication snapshots take their own non-reentrant lease. The
            # controller/authority leases serialize this reopen; holding the
            # publication lease here would block those accepted snapshot APIs.
            stage('previous_roles_quiescent')
            # Revalidate after any concurrent old work completed. Native saved
            # assembled evidence is committed without a provider or new poll_run.
            refreshed,new_binding=read_saved()
            if new_binding!=binding: raise ResumeError('state_invalid')
            refreshed.client,refreshed.password=session.client,session.password
            session=refreshed
            job=_generation_history(reader)
            _previous_progress(reader,job,clock)
            final_counts=_counts(session,reader)
            if final_counts['worker_starts']>=3 or final_counts['hot_quote_permits']>=60:
                raise ResumeError('budget_exhausted')
            pending=session.feed.snapshot()['pending']
            if pending: session.feed.finish(pending,unknown='interrupted')
            recovery=session.collector.poller.recover()
            stage('saved_native_work_recovered')
            runtime=ResumedRuntime(session,feed_client=feed_factory(session.feed),worker_command=settings.worker_command,
                clock=clock,monotonic=monotonic)
            runtime.initialize_saved(lease=lease,ledger=ledger,settings=settings)
            stage('runtime_reopened')
            after=_counts(session,runtime.managed)
            ledger.append('ready',nonce,{'counts':after,'native_recovery':plain(recovery),
                'full_manual_controller_resume':True,'outer_profile_harness_qualified':False})
            runtime.manual_resume_receipt=plain(ledger.snapshot()['events'][-1])
        transferred=True
        return runtime
    except (ResumeError,StartupError) as error:
        if ledger is not None:
            try:
                state=ledger.snapshot()['states'].get(nonce)
                if state in ('requested','authenticated'):
                    ledger.append('failed',nonce,{'code':error.code if isinstance(error,ResumeError) else 'credentials_rejected'})
            except Exception: pass
        raise
    except Exception:
        if ledger is not None:
            try:
                if ledger.snapshot()['states'].get(nonce) in ('requested','authenticated'):
                    ledger.append('failed',nonce,{'code':'state_invalid'})
            except Exception: pass
        raise ResumeError('state_invalid') from None
    finally:
        if isinstance(password,bytearray): password[:]=b'\0'*len(password);password.clear()
        if not transferred:
            if runtime is not None and runtime.initialized:
                runtime.close(reason='runtime_integrity_or_driver_failure');lease=None
            elif session is not None:
                if session.password is not None:session.password.close()
                if session.client is not None:session.client.close()
            if lease is not None:lease.__exit__(None,None,None)
