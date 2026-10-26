"""Fresh-session coupling of accepted bootstrap, source authority and Hot worker.

Explicit trusted feed/worker drivers only. No live launcher, fresh-controller
resume, profile-goal verdict, historical quote catch-up or production access.
The synchronous pump belongs inside an independently bounded owned controller.
"""
from datetime import timedelta
from pathlib import Path
import threading
import time

from .authenticated_startup import PreparedSchwabClient
from .controller_bootstrap import strict_json
from .integrated_identity import IdentityGatedDelivery, IdentityStopRequired
from .nasdaq_recovery_supervisor import NasdaqRecoverySupervisor
from .recovery_workers import ManagedRecoveryWorker, atomic_json
from .sampling_requests import canonical, digest, freeze, plain, timestamp, utc_text
from .sampling_service import owner_lock
from .supervised_hot_worker import progress_receipt

CONTRACT = 'fresh-authenticated-nasdaq-hot-runtime-v1'
CLOSE_REASONS = frozenset(('operator_stop', 'window_or_stop', 'pump_interrupted',
    'runtime_integrity_or_driver_failure', 'identity_provider_stop_required',
    'controller_provider_stopped', 'runtime_blocked_or_stopped',
    'worker_credentials_rejected', 'worker_startup_deadline_ended',
    'native_blocked', 'native_budget_exhausted', 'native_window_ended',
    'native_bounded_deadline_ended'))


class _PreparedDelivery:
    """Adapt the ordinary supervisor API without bypassing the identity gate."""
    def __init__(self, runtime, gate):
        self.runtime, self.gate = runtime, gate
        self.path, self.live, self.recovery, self.requests = gate.path, gate.live, gate.recovery, gate.requests
        self.identity = freeze({'contract': 'prepared-client-shared-delivery-v1',
            'gate': plain(gate.identity), 'configuration_sha256': runtime.session.plan.configuration_sha256})
        if runtime.session.plan.settings.profile == 'owned_worker_recovery':
            self.identity = freeze({**plain(self.identity),
                'request_delivery_policy': 'after_valid_dated_and_strictly_later_current_cutover'})

    def snapshot(self):
        return self.gate.snapshot()

    def reconcile(self, **kwargs):
        return self.gate.reconcile(**kwargs)

    def deliver_pending(self):
        self.runtime.validate()
        if self.runtime.session.plan.settings.profile == 'owned_worker_recovery':
            # Retain every source/outbox command while the recovery profile
            # reserves its unchanged 60 Hot permits for the 12/24 proof. The
            # native roster is genuinely empty until NORMAL request admission
            # and publication after the same validated source cutover.
            state = self.runtime.session.feed.snapshot()
            valid = [a for a in state['attempts'] if a['outcome']['status'] == 'valid']
            dated = [a for a in valid if a['query_id'] != 'CURRENT']
            currents = [a for a in valid if a['query_id'] == 'CURRENT']
            completed = {a['query_id'] for a in dated}
            latest = state['attempts'][-1] if state['attempts'] else None
            if (state['pending'] or state['stop_reason'] or not dated or not currents
                    or any(q.query_id not in completed for q in self.runtime.session.feed.queries)
                    or latest is None or latest['query_id'] != 'CURRENT'
                    or latest['outcome']['status'] != 'valid'
                    or timestamp(currents[-1]['completed_at_utc']) <= max(timestamp(a['completed_at_utc']) for a in dated)
                    or not 0 <= (self.runtime.clock()-timestamp(currents[-1]['completed_at_utc'])).total_seconds()
                        <= 2*self.runtime.session.feed.limits.interval_seconds+10):
                return ()
        return self.gate.deliver_pending(client=self.runtime.session.client)


class _RuntimeWorker:
    def __init__(self, runtime, managed):
        self.runtime, self.managed, self.identity = runtime, managed, managed.identity
        self.terminal_reason = None

    def _job(self):
        return self.managed._job()

    def stop_owned(self, **kwargs):
        return self.managed.stop_owned(**kwargs)

    def ensure(self, *, start_allowed, resume_after_utc):
        self.runtime.validate()
        job = self._job()
        if self.terminal_reason:
            return {'status': 'BLOCKED', 'reason': self.terminal_reason}
        if job:
            auth_path = self.managed.root/(job['token']+'.auth.json')
            if auth_path.is_file():
                auth = strict_json(auth_path.read_text())
                if (set(auth) != {'contract','token','configuration_sha256','status','observed_at_utc'}
                        or auth.get('contract') != 'authenticated-hot-startup-v1'
                        or auth.get('token') != job['token']
                        or auth.get('configuration_sha256') != job['identity']['startup_context']['configuration_sha256']
                        or not timestamp(job['started_at_utc']) <= timestamp(auth['observed_at_utc']) <= self.runtime.clock()):
                    raise ValueError('Authenticated worker receipt differs')
                if auth.get('status') != 'credentials_accepted':
                    self.terminal_reason = 'worker_credentials_rejected'
            beat_path = Path(job['heartbeat_path'])
            if beat_path.is_file():
                beat = strict_json(beat_path.read_text())
                if (beat.get('token') != job['token'] or beat.get('generation') != job['generation']
                        or beat.get('identity_sha256') != digest(job['identity'])):
                    raise ValueError('Worker completed-work identity differs')
                if beat.get('collector_status') in ('blocked', 'budget_exhausted', 'window_ended', 'bounded_deadline_ended'):
                    self.terminal_reason = 'native_'+beat['collector_status']
            startup_path = self.managed.root/(job['token']+'.startup.json')
            first = progress_receipt(job) if startup_path.is_file() else None
            age = (self.runtime.clock()-timestamp(job['started_at_utc'])).total_seconds()
            if (first and first['status'] != 'first_completed_work_observed'
                    or not first and age >= 3):
                self.terminal_reason = 'worker_startup_deadline_ended'
            if self.terminal_reason:
                self.stop_owned(reason=self.terminal_reason)
                return {'status': 'BLOCKED', 'reason': self.terminal_reason}
        result = self.managed.ensure(start_allowed=start_allowed and not self.runtime.stopped(),
            resume_after_utc=resume_after_utc)
        if result['status'] == 'EXTERNAL_HEALTHY':
            return {'status': 'BLOCKED', 'reason': 'unowned_worker_not_adopted'}
        if result['status'] == 'RUNNING':
            job = self._job()
            path = self.managed.root/(job['token']+'.startup.json')
            if not path.is_file():
                return {'status': 'STARTING', 'generation': job['generation'], 'credentials_are_not_progress': True}
            first = progress_receipt(job)
            if (first['status'] != 'first_completed_work_observed'
                    or timestamp(first['observed_at_utc']) > self.runtime.clock()
                    or self.managed.child is None or first['pid'] != self.managed.child.pid):
                raise ValueError('First completed work does not belong to the owned child')
            result['first_completed_work'] = first
        return result


class IntegratedRuntime:
    """Use one successful command-43 session; partial roots are never reset.

    feed_client and worker_command are explicit trusted API seams, not ordinary
    configuration modes. initialize() takes a lifetime controller lease and
    creates a fresh binding/authority only. Full manual reopen is separate.
    """
    def __init__(self, session, *, feed_client, worker_command, clock=None,
                 monotonic=time.monotonic, stop_requested=lambda: False):
        self.session, self.feed_client = session, feed_client
        self.clock, self.monotonic = clock or session.service.clock, monotonic
        self.stop_requested = stop_requested
        self.event = threading.Event()
        self.root = Path(session.plan.settings.experiment_root)
        self.start, self.stop = timestamp(session.plan.public['start_at_utc']), timestamp(session.plan.public['stop_at_utc'])
        self.configuration_path = self.root/'authenticated-worker.json'
        self.binding_path, self.stop_path = self.root/'runtime-binding.json', self.root/'runtime-stop.json'
        self.closed, self.initialized, self.lease, self.last_report = False, False, None, None
        self.pump_deadline = None
        if (session.plan.settings.catalog_mode != 'owned_directory' or session.gated_delivery is None
                or session.closed or not isinstance(session.client, PreparedSchwabClient)
                or feed_client.transport is not session.feed
                or not callable(getattr(feed_client, 'step', None))
                or not callable(getattr(feed_client, 'close_owned', None))
                or not isinstance(worker_command, tuple) or not worker_command
                or not all(type(s) is str and s for s in worker_command)
                or self.stop-self.start != timedelta(seconds=720)):
            raise ValueError('Explicit authenticated catalog-bound runtime drivers required')
        self.command = worker_command
        self.prepared_client, self.manual_secret = session.client, session.password
        self.original_components = (session.feed, session.gated_delivery, session.service, session.collector)
        config = strict_json(self.configuration_path.read_text())
        if (digest(config) != session.password.identity['configuration_sha256']
                or config['authentication']['request_timeout_seconds'] != 3
                or config['authentication']['startup_timeout_seconds'] != 8):
            raise ValueError('Original authenticated worker configuration differs')
        self.identity = freeze({'contract': CONTRACT, 'configuration_sha256': session.plan.configuration_sha256,
            'worker_configuration_sha256': digest(config), 'worker_command': list(worker_command),
            'feed_identity': plain(session.feed.identity), 'gate_identity': plain(session.gated_delivery.identity),
            'publication_identity': plain(session.service.identity), 'collector_identity': plain(session.collector.identity),
            'start_at_utc': utc_text(self.start), 'stop_at_utc': utc_text(self.stop),
            'worker_startup_seconds': 3, 'worker_stale_seconds': 3, 'credential_timeout_seconds': 8,
            'max_worker_starts': 3, 'max_hot_quote_permits': 60, 'max_identity_quote_permits': 3,
            'production_access': False, 'full_manual_controller_resume': False})
        self.validate()

    def validate(self):
        s = self.session
        receipt = strict_json((self.root/'bootstrap.json').read_text())
        if (s.closed or s.plan.configuration_sha256 != self.identity['configuration_sha256']
                or s.client is not self.prepared_client or s.password is not self.manual_secret
                or self.feed_client.transport is not s.feed
                or any(a is not b for a, b in zip(self.original_components,
                    (s.feed, s.gated_delivery, s.service, s.collector)))
                or digest(s.plan.public) != s.plan.configuration_sha256
                or receipt != s.receipt or receipt['status'] != 'BOOTSTRAPPED_NOT_RUNNING'
                or receipt['configuration_sha256'] != s.plan.configuration_sha256
                or digest(strict_json(self.configuration_path.read_text())) != self.identity['worker_configuration_sha256']
                or canonical(s.feed.identity) != canonical(self.identity['feed_identity'])
                or canonical(s.gated_delivery.identity) != canonical(self.identity['gate_identity'])
                or canonical(s.service.identity) != canonical(self.identity['publication_identity'])
                or canonical(s.collector.identity) != canonical(self.identity['collector_identity'])
                or self.command != tuple(self.identity['worker_command'])
                or s.catalog_ledger.snapshot()['status'] != 'BOUND'):
            raise ValueError('Original runtime bootstrap/catalog/configuration binding differs')
        s.catalog.validate()
        if self.initialized:
            if strict_json(self.binding_path.read_text()) != plain(self.identity):
                raise ValueError('Restore original runtime binding; no automatic adoption/reset')
        return True

    def stopped(self):
        return (self.closed or self.event.is_set() or bool(self.stop_requested())
            or self.clock() >= self.stop
            or self.pump_deadline is not None and self.monotonic() >= self.pump_deadline)

    def initialize(self):
        if self.closed or self.initialized or self.binding_path.exists() or self.stop_path.exists():
            raise ValueError('Existing/partial runtime requires explicit future manual resume')
        self.validate()
        if self.clock() >= self.session.plan.bootstrap_deadline:
            raise ValueError('Runtime preparation missed the original bootstrap deadline')
        # The lifetime controller lease must differ from the authority's
        # per-cycle runtime.owner.lock; otherwise the controller blocks itself.
        self.lease = owner_lock(self.root/'controller.owner.lock')
        self.lease.__enter__()
        try:
            # Exclusive binding creation precedes worker directories/authority.
            with self.binding_path.open('x', encoding='utf-8') as out:
                out.write(canonical(self.identity))
                out.flush()
                import os
                os.fsync(out.fileno())
            self.initialized = True
            s = self.session
            gate = IdentityGatedDelivery(s.gated_delivery.gate_path, delivery=s.base_delivery,
                catalog=s.catalog, start_at=utc_text(self.start), stop_at=utc_text(self.stop), clock=self.clock,
                monotonic=self.monotonic, stop_requested=self.stopped)
            gate.initialize()
            self.delivery = _PreparedDelivery(self, gate)
            self.managed = ManagedRecoveryWorker(self.root/'workers', role='experimental_hot',
                command=self.command, binding=plain(s.service.identity), max_starts=3,
                startup_seconds=3, stale_seconds=3, clock=self.clock, monotonic=self.monotonic,
                startup_handoff=s.password)
            self.worker = _RuntimeWorker(self, self.managed)
            self.authority = NasdaqRecoverySupervisor(self.root/'runtime.sqlite3', feed_client=self.feed_client,
                delivery=self.delivery, service=s.service, worker=self.worker, clock=self.clock)
            self.authority.initialize(create=True)
            if self.clock() >= self.session.plan.bootstrap_deadline:
                raise ValueError('Runtime preparation missed the original bootstrap deadline')
            return self
        except BaseException:
            self._release()
            raise

    def step(self, *, synthetic=None):
        if not self.initialized:
            raise ValueError('Fresh runtime initialization required')
        if self.closed:
            return self.last_report
        try:
            self.validate()
            if self.stopped():
                return self.close(reason='window_or_stop')
            if self.clock() < self.start:
                return {'status': 'WAITING', 'reason': 'original_T0', 'quote_calls': 0, 'feed_attempts': 0}
            if self.session.client.halt_reason:
                return self.close(reason='controller_provider_stopped')
            report = self.authority.cycle(synthetic=synthetic, stop_requested=self.stopped)
            # Feed-only loss never cancels verified demand or kills a healthy
            # collector. The fixed profile window still governs all dispatches.
            if report['status'] == 'BLOCKED' or self.stopped():
                return self.close(reason=self.worker.terminal_reason or 'runtime_blocked_or_stopped')
            self.last_report = dict(report, runtime_contract=CONTRACT,
                qualification='synthetic_coupled_runtime_live_profiles_pending',
                full_manual_controller_resume=False)
            return self.last_report
        except IdentityStopRequired:
            return self.close(reason='identity_provider_stop_required')
        except Exception:
            return self.close(reason='runtime_integrity_or_driver_failure')

    def prepare_worker(self, *, sleep=time.sleep):
        """Fresh-profile preparation only; no feed or quote dispatch before T0.

        Authenticate and observe completed native idle validation before the
        original preparation endpoint. The future-slot fence includes T0 when
        it is an allowed Hot second; it never permits a pre-window sample.
        """
        if not self.initialized or self.closed:
            raise ValueError('Initialized fresh runtime required for worker preparation')
        resume_after = utc_text(self.start-timedelta(microseconds=1))
        while True:
            if (self.stopped() or self.clock() >= self.session.plan.bootstrap_deadline):
                raise ValueError('Worker preparation missed the original preparation bound')
            result = self.worker.ensure(start_allowed=True, resume_after_utc=resume_after)
            if result['status'] == 'RUNNING':
                return result
            if result['status'] not in ('STARTING',):
                raise ValueError('Owned worker preparation did not establish completed work')
            sleep(.01)

    def run(self, *, synthetic=None, max_seconds=720, sleep=time.sleep):
        if not 0 < max_seconds <= 720:
            raise ValueError('Explicit bounded active runtime required')
        remaining = max(0, (self.stop-max(self.clock(), self.start)).total_seconds())
        self.pump_deadline = self.monotonic()+max(0, (self.start-self.clock()).total_seconds())+min(max_seconds, remaining)
        try:
            while not self.stopped():
                report = self.step(synthetic=synthetic)
                if self.closed:
                    return report
                sleep(.05)
            return self.close(reason='window_or_stop')
        finally:
            if not self.closed:
                self.close(reason='pump_interrupted')

    def _release(self):
        if self.lease is not None:
            lease, self.lease = self.lease, None
            lease.__exit__(None, None, None)

    def close(self, *, reason='operator_stop'):
        if self.closed:
            return self.last_report
        if not self.initialized:
            self.closed = True
            self.last_report = {'status': 'NOT_INITIALIZED', 'owned_processes_unchanged': True}
            return self.last_report
        self.event.set()
        reason = reason if reason in CLOSE_REASONS else 'runtime_integrity_or_driver_failure'
        stopped_at = utc_text(self.clock())
        verified, counts = False, {}
        cleanup = []
        try:
            for stop in ([lambda: self.managed.stop_owned(reason='runtime_stop')] if hasattr(self, 'managed') else []) + [self.feed_client.close_owned]:
                try:
                    stop()
                except Exception:
                    cleanup.append('owned_cleanup_incomplete')
            # Read final reservations only after owned work has stopped.
            try:
                gate = plain(self.session.gated_delivery.snapshot())['identity_gate']
                native = self.session.collector.poller.snapshot()
                counts = {'identity_quote_permits': gate['quote_permits'],
                    'hot_quote_permits': sum(e['kind'] == 'dispatch' and bool(e['symbols']) for e in native['events']),
                    'selected_symbol': gate['selected_symbol']}
                verified = True
            except Exception:
                pass
        finally:
            try:
                if not self.session.closed:
                    self.session.closed = True
                    self.manual_secret.close()
                    self.prepared_client.close()
            finally:
                self.closed = True
                self._release()
        self.last_report = {'contract': CONTRACT, 'status': 'STOPPED', 'reason': reason,
            'acquisition_stop_requested_at_utc': stopped_at, 'counts_verified': verified, **counts,
            'cleanup_findings': cleanup, 'profile_verdict': 'NOT_QUALIFIED_BY_RUNTIME_PUMP',
            'production_access': False, 'full_manual_controller_resume': False}
        atomic_json(self.stop_path, self.last_report)
        return self.last_report
