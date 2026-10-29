"""Trusted daily controller API. No operator launch or production activation CLI."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import os
import subprocess
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from .authenticated_startup import SessionPassword
from .integrated_catalog import DirectoryCatalog
from .daily_source import DailySourcePump
from .daily_supervision import (CONTRACT, DailyIdentityClient, DailyManagedWorker,
    DailyProcessState, read_json, sealed, unseal, stop_process)
from .recovery_workers import atomic_json
from .sampling_requests import canonical, digest, plain, timestamp, utc_text
from .sampling_service import owner_lock, ServiceBusy
from .supervised_hot_worker import progress_receipt, progress_path


class _ControllerPublication:
    """Share short publication reads with the collector; retry only lock entry."""
    def __init__(self, service):
        self.service, self.identity = service, service.identity
    def __getattr__(self, name): return getattr(self.service, name)
    def _call(self, method, **kwargs):
        deadline = time.monotonic()+.2
        while True:
            try: return getattr(self.service, method)(**kwargs)
            except ServiceBusy:
                if time.monotonic() >= deadline: raise
                time.sleep(.005)
    def snapshot(self): return self._call('snapshot')
    def cycle(self, **kwargs): return self._call('cycle', **kwargs)


class DailyHotHealth:
    """Saved status and persistent warnings/errors; no quote-age heartbeat."""
    def __init__(self, root, identity, clock):
        self.root, self.identity, self.clock = Path(root), identity, clock
        self.last_signature, self.last_write = None, None

    def publish(self, report):
        signature = digest({k: v for k, v in report.items() if k not in ('observed_at_utc', 'worker')})
        if (self.last_signature == signature and self.last_write is not None
                and time.monotonic()-self.last_write < 1): return report
        path = self.root/'hot-incidents.json'
        previous = unseal(read_json(path)) if path.exists() else None
        if previous is not None and previous['identity_sha256'] != digest(self.identity):
            raise ValueError('Hot alert identity differs')
        incidents = previous['incidents'] if previous else {}
        active = {}
        if report['state'] == 'RUNNING_WITH_SOURCE_GAPS': active['source:gap'] = 'warning'
        if report['state'] in ('REPLACEMENT_HOLD', 'RESTART_WAIT'): active['worker:recovery'] = 'warning'
        if report.get('terminal'): active['controller:blocked'] = 'error'
        now = utc_text(self.clock())
        for key, severity in active.items():
            if key not in incidents or incidents[key]['resolved_at_utc'] is not None:
                previous = incidents.get(key)
                incidents[key] = {'severity': severity, 'first_detected_at_utc': now,
                    'last_detected_at_utc': now, 'resolved_at_utc': None,
                    'occurrences': previous['occurrences']+1 if previous else 1}
            else: incidents[key]['last_detected_at_utc'] = now
        for key in incidents.keys()-active.keys():
            if incidents[key]['resolved_at_utc'] is None: incidents[key]['resolved_at_utc'] = now
        atomic_json(path, sealed({'identity_sha256': digest(self.identity), 'incidents': incidents}))
        atomic_json(self.root/'hot-status.json', sealed(report))
        # One atomic status file is authoritative. Text is an operator convenience.
        from mb_market_data.watchlist_polling import ET
        text = '\n'.join((f"Hot controller: {report['state']}",
            f"As of: {timestamp(now).astimezone(ET).isoformat()} ET", f"Worker starts: {report['worker_starts']}/3",
            f"Source reconciled: {report['source_reconciled']}",
            f"Reason: {report.get('terminal') or 'none'}",
            'Uni, Focus and independent Health are managed in their own windows.',
            'Trade/quote age is not a worker heartbeat.'))+'\n'
        temporary = self.root/'HOT_STATUS.tmp'
        temporary.write_text(text, encoding='utf-8')
        os.replace(temporary, self.root/'HOT_STATUS.txt')
        self.last_signature, self.last_write = signature, time.monotonic()
        return report


class DailyController:
    """Own daily source/identity/Hot roles; retain original ledgers on manual resume."""
    def __init__(self, session, configuration, *, commands, password, clock=None,
                 monotonic=time.monotonic, stop_requested=lambda: False,
                 feed_client_factory=None, allow_network=False, activation_approved=False):
        if activation_approved is not True:
            raise ValueError('Trusted activation assertion required; a file cannot enable Hot')
        self.session, self.configuration = session, configuration
        self.clock, self.monotonic = clock or session.clock, monotonic
        self.stop_requested, self.feed_factory, self.allow_network = stop_requested, feed_client_factory, allow_network
        self.root = Path(session.settings.state_root)
        session.validate()
        raw = configuration.payload()
        catalog = DirectoryCatalog.load(configuration.catalog_path)
        if (configuration.publication != session.settings
                or plain(configuration.collector.daily_binding) != plain(session.binding)
                or plain(configuration.collector.daily_claim) != plain(session.claim)
                or plain(configuration.collector.publication_binding) != plain(session.service.identity)
                or not isinstance(password, SessionPassword)
                or password.identity['configuration_sha256'] != digest(raw)
                or catalog.catalog_id != session.catalog.catalog_id
                or digest(catalog.public) != session.claim['catalog_sha256']
                or set(commands) != {'collector', 'identity', 'report'}
                or any(not isinstance(c, tuple) or not c or not all(type(v) is str and v for v in c)
                    for c in commands.values())):
            raise ValueError('Owned publication, private manual session and explicit role commands required')
        self.password, self.commands = password, commands
        self.identity = {'contract': CONTRACT, 'configuration_sha256': digest(raw),
            'configuration_path': str(self.root/'daily-worker.json'),
            'daily_binding_sha256': session.binding['binding_sha256'],
            'commands': {k: list(v) for k, v in commands.items()},
            'deadlines': {'progress': 3, 'credentials': 8, 'replacement_hold': 15,
                'cleanup': 10, 'reporting': 60}, 'maximum_worker_starts': 3}
        self.state = DailyProcessState(self.root, self.identity)
        self.health = DailyHotHealth(self.root, self.identity, self.clock)
        self.event, self.lock = threading.Event(), threading.RLock()
        self.worker = self.source = self.identity_client = self.lease = self.thread = None
        self.initialized = self.closed = False
        self.has_ownership = False
        self.worker_allowed = False
        self.worker_report, self.source_report, self.last_report = {'status': 'STARTING'}, {}, None

    def _live(self, state='RUNNING'):
        atomic_json(self.root/'driver-live.json', sealed({'contract': CONTRACT,
            'identity_sha256': digest(self.identity), 'invocation': self.invocation,
            'observed_at_utc': utc_text(self.clock()), 'state': state}))
        self.last_live = self.monotonic()

    def initialize(self, *, create=False, manual_resume_approved=False):
        if self.initialized or self.closed:
            raise ValueError('Fresh daily controller required')
        self.session.validate()
        if self.clock() >= timestamp(self.configuration.collector.stop_at_utc):
            raise ValueError('Daily controller window ended')
        if plain(self.session.gate.snapshot())['identity_gate']['provider_stop_required']:
            raise ValueError('Identity provider stop must be reviewed before startup')
        stop = Path(self.configuration.collector.journal_path).with_suffix('.daily-hot-provider-stop.json')
        manifest = Path(self.configuration.collector.journal_path).with_suffix('.hot.poller.daily-collector.json')
        if stop.exists() or manifest.exists() and read_json(manifest).get('provider_stop'):
            raise ValueError('Hot provider stop must be reviewed before startup')
        lease = owner_lock(self.root/'driver-owner.lock')
        lease.__enter__()
        self.lease, self.has_ownership = lease, True
        try:
            binding, config = self.root/'driver-binding.json', self.root/'daily-worker.json'
            if create:
                if any(p.exists() for p in (binding, config, self.state.path)):
                    raise ValueError('Existing or partial driver state cannot be reset')
                with binding.open('x', encoding='utf-8') as out:
                    out.write(canonical(self.identity)); out.flush(); os.fsync(out.fileno())
                with config.open('x', encoding='utf-8') as out:
                    out.write(canonical(self.configuration.payload())); out.flush(); os.fsync(out.fileno())
                self.state.create()
            else:
                if manual_resume_approved is not True:
                    raise ValueError('Fresh manual controller resume assertion required')
                s = self.state.read()
                if (read_json(binding) != self.identity or read_json(config) != self.configuration.payload()
                        or not s['initialized'] or s['terminal'] or len(s['starts']) >= 3):
                    raise ValueError('Original resumable daily state and remaining budgets required')
                # Never adopt or PID-kill an old process. Its own fence exits it.
                for path in (self.root/'workers'/'worker.lock', self.root/'identity-owner.lock'):
                    if path.exists():
                        with owner_lock(path): pass
            self.invocation = uuid.uuid4().hex
            def begin(s):
                if len(s['invocations']) >= 3:
                    raise ValueError('Daily invocation budget exhausted')
                s['active_invocation'] = self.invocation
                s['invocations'].append({'invocation': self.invocation, 'at_utc': utc_text(self.clock()),
                    'manual_resume': not create})
                s['stop'] = None
                if not create: s['hold_until_utc'] = utc_text(self.clock()+timedelta(seconds=15))
            self.state.change(begin)
            self._live()
            self.session.service = _ControllerPublication(self.session.service)
            self.worker = DailyManagedWorker(self.root/'workers', command=self.commands['collector'],
                binding=self.identity, state=self.state, password=self.password,
                clock=self.clock, monotonic=self.monotonic)
            if not create: self.worker.hold_monotonic = self.monotonic()+15
            self.initialized = True
            self.thread = threading.Thread(target=self._monitor, daemon=True)
            self.thread.start()
            self.identity_client = DailyIdentityClient(self.root, self.commands['identity'],
                password=self.password, invocation=self.invocation,
                configuration_sha256=self.identity['configuration_sha256'], clock=self.clock,
                stop_requested=self.stopped)
            self.source = DailySourcePump(self.session, identity_client=self.identity_client,
                clock=self.clock, feed_client_factory=self.feed_factory,
                allow_network=self.allow_network, stop_requested=self.stopped)
            self.source.initialize(create=create)
            self.identity_client.start()
            self.state.change(lambda s: s.update(initialized=True))
            self.worker_allowed = True
            return self.status()
        except BaseException:
            self.close(reason='initialization_failed', report=False)
            raise

    def stopped(self):
        return (self.closed or self.event.is_set() or self.stop_requested()
            or self.clock() >= timestamp(self.configuration.collector.stop_at_utc))

    def _terminal(self, reason):
        self.state.change(lambda s: s.update(terminal=reason))
        self.event.set()
        self.worker_report = {'status': 'BLOCKED', 'reason': reason}
        if self.worker is not None:
            self.worker.stop_owned(reason=reason)

    def _monitor_once(self):
        with self.lock:
            if self.stopped(): return
            if self.monotonic()-self.last_live >= .5: self._live()
            if not self.worker_allowed: return
            job = self.worker._job()
            if job:
                auth = Path(job['job_path']).parent/(job['token']+'.auth.json')
                if auth.exists():
                    value = read_json(auth)
                    if (value.get('token') != job['token']
                            or value.get('configuration_sha256') != self.identity['configuration_sha256']
                            or not timestamp(job['started_at_utc']) <= timestamp(value['observed_at_utc']) <= self.clock()):
                        raise ValueError('Daily credential receipt differs')
                    if value.get('status') != 'credentials_accepted':
                        return self._terminal('worker_credentials_rejected')
                startup = progress_receipt(job) if progress_path(job).exists() else None
                if (startup and startup['status'] != 'first_completed_work_observed'
                        or not startup and (self.clock()-timestamp(job['started_at_utc'])).total_seconds() >= 3):
                    return self._terminal('worker_startup_deadline_ended')
                beat_path = Path(job['heartbeat_path'])
                if beat_path.exists():
                    beat = read_json(beat_path)
                    if (beat.get('token') != job['token'] or beat.get('generation') != job['generation']
                            or beat.get('identity_sha256') != digest(job['identity'])):
                        raise ValueError('Daily native progress binding differs')
                    if beat.get('collector_status') in ('blocked', 'budget_exhausted'):
                        return self._terminal('native_'+beat['collector_status'])
            self.worker_report = self.worker.ensure(start_allowed=True, resume_after_utc=utc_text(self.clock()))
            if self.worker_report['status'] == 'BLOCKED':
                return self._terminal(self.worker_report.get('reason', 'worker_blocked'))
            if self.worker_report['status'] == 'RUNNING':
                job = self.worker._job()
                if not progress_path(job).exists():
                    self.worker_report = {'status': 'STARTING', 'credentials_are_not_progress': True}
                else:
                    first = progress_receipt(job)
                    if self.worker.child is None or first['pid'] != self.worker.child.pid:
                        raise ValueError('Daily progress did not originate in the owned worker')

    def _monitor(self):
        while not self.event.wait(.05):
            try:
                self._monitor_once()
            except BaseException:
                with self.lock:
                    try: self._terminal('worker_evidence_or_supervision_failed')
                    except BaseException:
                        self.event.set()
                        self.worker_report = {'status': 'BLOCKED', 'reason': 'original_state_unreadable'}
                        try: self._live('STOPPING')
                        except Exception: pass
                return

    def status(self):
        with self.lock:
            s = self.state.read()
            state = self.worker_report['status']
            if s['terminal']: state = 'BLOCKED'
            elif self.closed: state = 'STOPPED'
            elif state == 'RUNNING' and not self.source_report.get('discovery_scope_reconciled'):
                state = 'RUNNING_WITH_SOURCE_GAPS'
            report = {'contract': CONTRACT, 'identity_sha256': digest(self.identity),
                'observed_at_utc': utc_text(self.clock()), 'state': state,
                'worker': dict(self.worker_report), 'worker_starts': len(s['starts']),
                'source_reconciled': bool(self.source_report.get('discovery_scope_reconciled')),
                'source_status': self.source_report.get('status', 'STARTING'),
                'terminal': s['terminal'], 'invocation': s['active_invocation'],
                'unmanaged_channels': ['uni', 'focus', 'health'],
                'full_day_capacity_qualified': False, 'production_activation_inferred': False}
            hierarchy = self.session.store.latest_membership_revision_effective_at(self.clock())
            report['effective_revision'] = hierarchy.revision if hierarchy else None
            report['hot_symbols'] = list(hierarchy.hot_symbols) if hierarchy else []
            return self.health.publish(report)

    def step(self, *, synthetic=None):
        if not self.initialized or self.closed:
            raise ValueError('Initialized daily controller required')
        if self.stopped(): return self.close(reason='window_or_stop_requested')
        try:
            self.session.validate()
            if (read_json(self.root/'driver-binding.json') != self.identity
                    or read_json(self.root/'daily-worker.json') != self.configuration.payload()):
                raise ValueError('Daily controller inputs changed')
            self.source_report = self.source.cycle(synthetic=synthetic)
            if self.source_report['status'] == 'BLOCKED':
                with self.lock: self._terminal('source_integrity_blocked')
            if plain(self.session.gate.snapshot())['identity_gate']['provider_stop_required']:
                with self.lock: self._terminal('identity_provider_stop_required')
            if self.stopped(): return self.close(reason='controller_blocked_or_stopped')
            return self.status()
        except BaseException:
            with self.lock: self._terminal('daily_inputs_or_source_failed')
            self.close(reason='daily_inputs_or_source_failed')
            raise

    def run(self, *, synthetic=None, max_seconds=23400, sleep=time.sleep):
        if type(max_seconds) not in (int, float) or not 0 < max_seconds <= 23400:
            raise ValueError('Explicit bounded daily run required')
        deadline = self.monotonic()+max_seconds
        try:
            while not self.stopped() and self.monotonic() < deadline:
                self.step(synthetic=synthetic)
                if self.closed: return self.last_report
                sleep(.1)
        finally:
            self.close(reason='window_or_run_ended')
        return self.last_report

    def close(self, *, reason='operator_stop', report=True):
        if self.closed: return self.last_report
        if not self.has_ownership:
            self.closed = True
            self.event.set()
            self.password.close()
            self.last_report = {'contract': CONTRACT, 'status': 'NOT_OWNED',
                'owned_processes_and_existing_status_unchanged': True}
            return self.last_report
        began = self.monotonic()
        self.closed = True
        self.event.set()
        if self.thread is not None and threading.current_thread() is not self.thread:
            self.thread.join(timeout=4)
        cleanup, errors = {}, []
        try:
            if self.initialized:
                try:
                    self.state.change(lambda s: s.update(stop={'reason': reason, 'at_utc': utc_text(self.clock())}))
                except Exception as error: errors.append('stop_state:'+type(error).__name__)
                try: self._live('STOPPING')
                except Exception as error: errors.append('stop_fence:'+type(error).__name__)
            # Independent owned handles may close concurrently. SDK close never
            # runs in this process; the child close/terminate/kill bounds apply.
            with ThreadPoolExecutor(max_workers=3) as executor:
                closing = {}
                if self.source is not None: closing['source'] = executor.submit(self.source.close)
                if self.worker is not None: closing['hot'] = executor.submit(self.worker.stop_owned, reason=reason)
                if self.identity_client is not None: closing['identity'] = executor.submit(self.identity_client.close)
                for name, future in closing.items():
                    try: cleanup[name] = future.result(timeout=9)
                    except Exception as error:
                        cleanup[name] = {'status': 'EVIDENCE_INCOMPLETE', 'error_type': type(error).__name__}
        finally:
            self.password.close()
            if self.has_ownership: self.session.close()
            if self.lease is not None:
                lease, self.lease = self.lease, None
                lease.__exit__(None, None, None)
        cleanup_seconds = self.monotonic()-began
        self.last_report = {'contract': CONTRACT, 'status': 'STOPPED', 'reason': reason,
            'cleanup': cleanup, 'cleanup_seconds': cleanup_seconds,
            'cleanup_within_10_seconds': cleanup_seconds < 10,
            'evidence_errors': errors,
            'unmanaged_channels_untouched': ['uni', 'focus', 'health'],
            'reporting': {'status': 'PENDING' if report and self.initialized else 'NOT_REQUESTED'}}
        # The producer-stop receipt must survive reporter loss or invalid output.
        atomic_json(self.root/'driver-stop.json', sealed(self.last_report))
        if report and self.initialized:
            try: self.last_report['reporting'] = self._final_report()
            except Exception as error:
                self.last_report['reporting'] = {'status': 'REPORT_INCOMPLETE', 'error_type': type(error).__name__}
            atomic_json(self.root/'driver-stop.json', sealed(self.last_report))
        if self.initialized:
            try: self.status()
            except Exception: pass  # Cleanup receipt survives damaged source/state evidence.
        return self.last_report

    def _final_report(self):
        report_id = uuid.uuid4().hex
        directory = self.root/'reports'; directory.mkdir(exist_ok=True)
        job = {'configuration_sha256': self.identity['configuration_sha256'],
            'report_id': report_id, 'invocation': getattr(self, 'invocation', None),
            'output': str(directory/(report_id+'.json')), 'audited_at_utc': utc_text(self.clock())}
        path = directory/(report_id+'.job.json')
        atomic_json(path, job)
        began = time.monotonic()
        child = subprocess.Popen([*self.commands['report'], str(path)], stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            child.wait(timeout=56)
        except subprocess.TimeoutExpired:
            stop_process(child, cooperative=0)
            return {'status': 'REPORT_INCOMPLETE', 'reason': 'reporting_deadline',
                'seconds': time.monotonic()-began}
        output = Path(job['output'])
        if child.returncode != 0 or not output.is_file():
            return {'status': 'REPORT_INCOMPLETE', 'reason': 'reporter_failed'}
        result = unseal(read_json(output))
        if (result['configuration_sha256'] != self.identity['configuration_sha256']
                or result['report_id'] != report_id or result['invocation'] != job['invocation']
                or result['audited_at_utc'] != job['audited_at_utc']):
            raise ValueError('Daily final report binding differs')
        return {'status': 'COMPLETE', 'native_audit_passed': result['native_audit_passed'],
            'two_fresh_replays_equal': result['two_fresh_replays_equal'],
            'first_replay': result['first_replay'], 'report_path': job['output'],
            'seconds': time.monotonic()-began}
