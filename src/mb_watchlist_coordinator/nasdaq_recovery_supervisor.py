"""Isolated recovery authority: evidence -> requests -> publication -> health.

No broker client, production process discovery, Uni/Focus control or historical
quote catch-up. A configured worker must implement the experimental protocol.
"""
from __future__ import annotations

from contextlib import closing
from datetime import timedelta
import json
from pathlib import Path
import sqlite3
import time

from .nasdaq_recovery import regular_window
from .sampling_requests import canonical, digest, freeze, membership_payload, plain, timestamp, utc_text
from .sampling_service import owner_lock, ServiceBusy


class NasdaqRecoverySupervisor:
    def __init__(self, path, *, feed_client, delivery, service, worker=None, clock=None):
        self.path = Path(path)
        self.client, self.feed, self.delivery, self.service = feed_client, feed_client.transport, delivery, service
        self.live, self.recovery, self.requests = delivery.live, delivery.recovery, delivery.requests
        self.worker = worker
        self.clock = clock or service.clock
        if (self.requests.path.resolve() != service.requests.path.resolve()
                or self.feed.session_date != self.requests.session_date
                or tuple(self.feed.queries) != self.recovery.settings.queries):
            raise ValueError('Recovery components do not share session/request/query identity')
        if worker and canonical(worker.identity['binding']) != canonical(service.identity):
            raise ValueError('Managed worker is not bound to this publication/journal identity')
        paths = [self.path, self.feed.path, delivery.path, service.path,
                 self.live.path, self.recovery.path, self.requests.path, Path(service.journal.identity['path'])]
        if len({p.resolve() for p in paths}) != len(paths):
            raise ValueError('Recovery authority files must be distinct')
        self.identity = freeze(self._identity())

    def _identity(self):
        return {'contract': 'isolated-nasdaq-recovery-supervisor-v1',
            'feed_identity': plain(self.feed.identity), 'delivery_identity': plain(self.delivery.identity),
            'publication_identity': plain(self.service.identity),
            'worker_identity': self.worker.identity if self.worker else None,
            'readiness_scope': 'declared_feed_reconciliation_native_publication_and_registered_worker_protocol',
            'production_access': False, 'unmanaged_channels': ['uni', 'focus']}

    def _connect(self, write=False):
        return sqlite3.connect(self.path.resolve().as_uri()+('?mode=rw' if write else '?mode=ro'), uri=True, timeout=5)

    def initialize(self, *, create=False):
        if create:
            self._validate_dependencies()
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open('xb'):
                pass
            with closing(self._connect(True)) as c, c:
                c.execute('CREATE TABLE recovery_supervisor_identity (id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL)')
                c.execute('INSERT INTO recovery_supervisor_identity VALUES(1,?)', (canonical(self.identity),))
                c.execute('CREATE TABLE recovery_supervisor_event (sequence INTEGER PRIMARY KEY, payload TEXT NOT NULL)')
        elif not self.path.is_file():
            raise FileNotFoundError('Missing supervisor ledger; restore instead of resetting recovery state')
        self._read()
        return self.snapshot()

    def _read(self):
        if canonical(self._identity()) != canonical(self.identity):
            raise ValueError('Supervisor configuration changed')
        previous, events, ingested, last = digest(self.identity), [], {}, None
        with closing(self._connect()) as c:
            c.execute('BEGIN')
            if c.execute('SELECT payload FROM recovery_supervisor_identity WHERE id=1').fetchone() != (canonical(self.identity),):
                raise ValueError('Supervisor identity differs')
            for n, raw in c.execute('SELECT * FROM recovery_supervisor_event ORDER BY sequence'):
                e = json.loads(raw); body = dict(e); sha = body.pop('event_sha256')
                at = timestamp(e['at_utc'])
                if (n != len(events)+1 or e['sequence'] != n or e['previous_sha256'] != previous
                        or digest(body) != sha or last is not None and at < last):
                    raise ValueError('Supervisor event chain or clock differs')
                if e['kind'] == 'ingested':
                    if e['attempt_id'] in ingested:
                        raise ValueError('Duplicate feed ingestion acknowledgement')
                    ingested[e['attempt_id']] = e
                elif e['kind'] != 'status':
                    raise ValueError('Unknown supervisor event')
                events.append(e); previous, last = sha, at
        return events, ingested, previous

    def _append(self, kind, **data):
        events, _, previous = self._read()
        at = self.clock()
        if events and at < timestamp(events[-1]['at_utc']):
            raise ValueError('Supervisor clock moved backwards')
        e = {'sequence': len(events)+1, 'kind': kind, 'at_utc': utc_text(at),
             'previous_sha256': previous, **data}
        e['event_sha256'] = digest(e)
        with closing(self._connect(True)) as c, c:
            c.execute('BEGIN IMMEDIATE')
            head = c.execute('SELECT sequence FROM recovery_supervisor_event ORDER BY sequence DESC LIMIT 1').fetchone()
            if head != ((len(events),) if events else None):
                raise ValueError('Supervisor event head changed')
            c.execute('INSERT INTO recovery_supervisor_event VALUES(?,?)', (e['sequence'], canonical(e)))
        return e

    def snapshot(self):
        events, ingested, _ = self._read()
        statuses = [e for e in events if e['kind'] == 'status']
        return freeze({'last_report': statuses[-1] if statuses else None,
            'ingested_attempt_ids': sorted(ingested), 'events': events})

    def _validate_dependencies(self):
        if self.worker:
            self.worker._job()
        state = self.feed.snapshot()
        live, recovery = plain(self.live.snapshot()), plain(self.recovery.snapshot())
        self.delivery.snapshot()
        publication = plain(self.service.snapshot())
        if self.path.is_file():
            _, ingested, _ = self._read()
            attempts = {a['attempt_id']: a for a in state['attempts']}
            for aid, ack in ingested.items():
                a = attempts.get(aid)
                if a is None or a['outcome']['status'] != 'valid':
                    raise ValueError('Ingested transport prefix changed')
                snap = self.feed.halt_snapshot(a)
                receipts = (live if a['query_id'] == 'CURRENT' else recovery)['receipts']
                receipt = next((r for r in receipts if r['snapshot']['capture_id'] == snap.capture_id), None)
                if (receipt is None or receipt['snapshot'] != snap.payload()
                        or receipt['event_sha256'] != ack['source_receipt_sha256']):
                    raise ValueError('Ingested source receipt binding differs')
        return state, publication

    def _ingest(self, *, fault_hook=None):
        state = self.feed.snapshot()
        _, ingested, _ = self._read()
        for a in state['attempts']:
            if a['attempt_id'] in ingested or a['outcome']['status'] != 'valid':
                continue
            snap = self.feed.halt_snapshot(a)
            if a['query_id'] == 'CURRENT':
                receipt, _ = self.live.record_snapshot(snap)
            else:
                q = next(q for q in self.feed.queries if q.query_id == a['query_id'])
                receipt, _ = self.recovery.record(q, snap)
            if fault_hook:
                fault_hook('after_source_receipt')
            self._append('ingested', attempt_id=a['attempt_id'], source_receipt_sha256=receipt['event_sha256'])

    def _local(self, *, fault_hook=None, service_fault_hook=None):
        _, ingested, _ = self._read()
        window_queries = {a['query_id'] for a in self.feed.snapshot()['attempts']
            if a['attempt_id'] in ingested and a['outcome']['status'] == 'valid'}
        window_complete = all(q.query_id in window_queries for q in self.feed.queries)
        self.delivery.reconcile(include_recovery=window_complete)
        self.delivery.deliver_pending()
        if fault_hook:
            fault_hook('after_request_delivery')
        self.service.cycle(fault_hook=service_fault_hook)
        publication = plain(self.service.snapshot())
        if fault_hook:
            fault_hook('after_publication')
        events, states = self.requests.validated_history()
        current = states[-1]
        last = publication['journal'][-1]
        members = {k: last['proposal'][k+'_symbols'] for k in ('uni', 'focus', 'hot')}
        effective = timestamp(last['proposal']['effective_at_utc'])
        ready = (not publication['pending'] and not publication['unacknowledged']
            and publication['processed_sequence'] == current.sequence
            and members == membership_payload(current.applied) and self.clock() >= effective
            and not self.delivery.snapshot()['pending'])
        return ready, publication, current

    def _next_query(self, state):
        # Establish CURRENT baseline before dated catch-up; require a later
        # CURRENT cutover before readiness so new events do not fall in a handoff hole.
        if not any(a['query_id'] == 'CURRENT' and a['outcome']['status'] == 'valid' for a in state['attempts']):
            return None
        completed = {a['query_id'] for a in state['attempts'] if a['outcome']['status'] == 'valid'}
        return next((q for q in self.feed.queries if q.query_id not in completed), None)

    def _report(self, status, reasons, **details):
        report = {'status': status, 'reasons': sorted(set(reasons)),
            'readiness_scope': self.identity['readiness_scope'],
            'unmanaged_channels_untouched': ['uni', 'focus'], 'production_access': False, **details}
        events, _, _ = self._read()
        previous = next((e for e in reversed(events) if e['kind'] == 'status'), None)
        if (previous is None or {k: previous.get(k) for k in report} != report
                or (self.clock()-timestamp(previous['at_utc'])).total_seconds() >= 1):
            e = self._append('status', **report)
            return dict(report, observed_at_utc=e['at_utc'], status_persisted=True)
        return dict(report, observed_at_utc=previous['at_utc'], status_persisted=True)

    def _cycle(self, *, synthetic=None, stop_requested=lambda: False, fault_hook=None, service_fault_hook=None):
        self._read()
        self._validate_dependencies()
        if stop_requested():
            if hasattr(self.client, 'close_owned'):
                self.client.close_owned()
            if self.worker:
                self.worker.stop_owned()
            return self._report('INCOMPLETE', ['stop_requested'])
        start, stop = regular_window(self.requests.session_date)
        if not start <= self.clock() < stop:
            if hasattr(self.client, 'close_owned'):
                self.client.close_owned()
            if self.worker:
                self.worker.stop_owned()
            return self._report('INCOMPLETE', ['outside_target_regular_session'])
        self._ingest(fault_hook=fault_hook)
        local, pub, current = self._local(fault_hook=fault_hook, service_fault_hook=service_fault_hook)
        state = self.feed.snapshot()
        if not stop_requested():
            acquire = getattr(self.client, 'step', None) or self.client.attempt
            acquire(self._next_query(state), synthetic=synthetic, stop_requested=stop_requested)
        if not start <= self.clock() < stop:
            if hasattr(self.client, 'close_owned'):
                self.client.close_owned()
            if self.worker:
                self.worker.stop_owned()
            return self._report('INCOMPLETE', ['session_ended_during_feed_attempt'])
        if stop_requested():
            if self.worker:
                self.worker.stop_owned()
            return self._report('INCOMPLETE', ['stop_requested'])
        self._ingest(fault_hook=fault_hook)
        local, pub, current = self._local(fault_hook=fault_hook, service_fault_hook=service_fault_hook)
        state, _ = self._validate_dependencies()
        recovery = self.recovery.snapshot()
        reasons = list(recovery['known_gaps'])
        if any(a['outcome']['status'] != 'valid' for a in state['attempts']):
            reasons.append('unavailable_feed_intervals_not_reconstructible')
        unresolved = [f['event_id'] for f in recovery['candidates'] if f['decision'] == 'unresolved_original_reason']
        if unresolved:
            reasons.append('unresolved_original_reason_candidates')
        decisions = self.delivery.snapshot()['deliveries']
        rejected = [k for k, v in decisions.items() if not v['accepted']]
        if rejected:
            reasons.append('normal_admission_rejections_retained')
        dated = [timestamp(a['completed_at_utc']) for a in state['attempts'] if a['query_id'] != 'CURRENT' and a['outcome']['status'] == 'valid']
        currents = [timestamp(a['completed_at_utc']) for a in state['attempts'] if a['query_id'] == 'CURRENT' and a['outcome']['status'] == 'valid']
        cutover = bool(currents and dated and max(currents) >= max(dated))
        fresh = bool(currents and 0 <= (self.clock()-max(currents)).total_seconds() <= 2*self.feed.limits.interval_seconds+10)
        bounded_stop = (state['stop_reason'] or
            ('attempt_budget_ended' if len(state['attempts']) >= self.feed.limits.max_attempts else None) or
            ('feed_deadline_ended' if state['deadline_utc'] and self.clock() >= timestamp(state['deadline_utc']) else None))
        latest_bad = bool(state['attempts'] and state['attempts'][-1]['outcome']['status'] != 'valid')
        worker = self.worker.ensure(start_allowed=local, resume_after_utc=utc_text(self.clock())) if self.worker else {'status': 'NOT_CONFIGURED'}
        if self.worker:
            reasons.append('provider_collector_driver_qualification_pending')
        complete_queries = {a['query_id'] for a in state['attempts'] if a['outcome']['status'] == 'valid'}
        window_complete = all(q.query_id in complete_queries for q in self.feed.queries)
        discovery = window_complete and not recovery['pending_query_ids'] and cutover and fresh and not latest_bad and not bounded_stop and not state['pending']
        if bounded_stop:
            reasons.append(bounded_stop)
        if not cutover:
            reasons.append('post_recovery_current_cutover_pending')
        if not fresh:
            reasons.append('fresh_current_capture_pending')
        if latest_bad:
            reasons.append('latest_feed_attempt_unavailable')
        owned_pending = bool(getattr(self.client, 'owns_attempt', False))
        if state['pending']:
            reasons.append('owned_feed_attempt_in_progress' if owned_pending else 'in_flight_attempt_outcome_unknown')
        if worker['status'] == 'BLOCKED':
            status = 'BLOCKED'
        elif bounded_stop or latest_bad or state['pending'] and not owned_pending:
            status = 'INCOMPLETE'
        elif not local or not discovery or worker['status'] not in ('RUNNING', 'EXTERNAL_HEALTHY'):
            status = 'RECOVERING'
        else:
            status = 'READY_WITH_GAPS' if reasons else 'READY'
        return self._report(status, reasons, local_membership_effective=local, discovery_scope_reconciled=discovery,
            feed_stop_required=bool(bounded_stop or state['pending'] and not owned_pending),
            worker=worker, unresolved_candidates=unresolved, rejected_requests=rejected,
            query_scope=recovery['query_scope'],
            pending_window_query_ids=[q.query_id for q in self.feed.queries if q.query_id not in complete_queries],
            native_content_sha256=pub['journal'][-1]['content_sha256'],
            feed_head_sha256=state['head_sha256'])

    def cycle(self, **kwargs):
        try:
            with owner_lock(self.path.with_suffix('.owner.lock')):
                return self._cycle(**kwargs)
        except ServiceBusy:
            return {'status': 'BLOCKED', 'detail': 'Authority already owned', 'status_persisted': False}
        except (ValueError, OSError, sqlite3.Error, KeyError, TypeError) as error:
            # Integrity failures must not start/restart a worker or publish more
            # membership. A blocked report is best effort when its own ledger is damaged.
            try:
                if hasattr(self.client, 'close_owned'):
                    self.client.close_owned()
            except (ValueError, OSError, sqlite3.Error, KeyError, TypeError):
                pass
            try:
                return self._report('BLOCKED', [type(error).__name__], detail=str(error))
            except (ValueError, OSError, sqlite3.Error, KeyError, TypeError):
                return {'status': 'BLOCKED', 'detail': type(error).__name__, 'status_persisted': False}

    def run(self, *, stop_requested, max_seconds=720, synthetic=None):
        if not 0 < max_seconds <= 720:
            raise ValueError('Recovery run must be explicitly bounded')
        deadline = time.monotonic()+max_seconds
        acquired = False
        try:
            with owner_lock(self.path.with_suffix('.owner.lock')):
                acquired = True
                while time.monotonic() < deadline and not stop_requested():
                    try:
                        report = self._cycle(synthetic=synthetic,
                            stop_requested=lambda: stop_requested() or time.monotonic() >= deadline)
                    except (ValueError, OSError, sqlite3.Error, KeyError, TypeError) as error:
                        return self._report('BLOCKED', [type(error).__name__], detail=str(error))
                    retryable_feed_gap = (report['status'] == 'INCOMPLETE'
                        and 'latest_feed_attempt_unavailable' in report['reasons']
                        and not report.get('feed_stop_required', True))
                    if report['status'] == 'BLOCKED' or report['status'] == 'INCOMPLETE' and not retryable_feed_gap:
                        if time.monotonic() >= deadline and not stop_requested():
                            return self._report('INCOMPLETE', ['supervisor_deadline_ended'])
                        return report
                    time.sleep(.05)
                return self._report('INCOMPLETE', ['stop_requested' if stop_requested() else 'supervisor_deadline_ended'])
        finally:
            if acquired and hasattr(self.client, 'close_owned'):
                try:
                    self.client.close_owned()
                except (ValueError, OSError, sqlite3.Error, KeyError, TypeError):
                    pass
            if self.worker and acquired:
                self.worker.stop_owned()
