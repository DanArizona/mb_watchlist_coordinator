"""Durable identity gate over the ordinary shared Nasdaq request outbox.

The first exact broker-confirmed symbol claims this bounded experiment's single
authorization. Normal admission may still reject or restrict its request; the
gate never replaces that decision or substitutes another symbol afterwards.
Every source observation and unselected command remains in the original store.
"""
from contextlib import closing
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
import sqlite3
import time

from .authenticated_startup import StartupError
from .controller_bootstrap import strict_json
from .nasdaq_sampling import _intent
from .sampling_requests import canonical, digest, freeze, plain, timestamp, utc_text
from .sampling_service import owner_lock

MAX_RESPONSE_BYTES = 1_000_000


class IdentityStopRequired(RuntimeError):
    pass


def _confirmed(status, body, symbol):
    item = body.get(symbol) if isinstance(body, dict) else None
    return (status == 200 and isinstance(item, dict) and item.get('symbol') == symbol
        and item.get('assetMainType') == 'EQUITY' and item.get('assetSubType') == 'COE')


class IdentityGatedDelivery:
    """Bound catalog, three cumulative permits, one symbol and normal admission.

    Owns no credential/client lifetime or runtime loop. The caller supplies its
    prepared timeout=3s client and an independent controller hard deadline.
    Missing/corrupt evidence is refused; initialize(create=False) cannot reset it.
    """
    def __init__(self, gate_path, *, delivery, catalog, start_at, stop_at,
                 clock=None, monotonic=time.monotonic, stop_requested=lambda: False):
        self.gate_path, self.delivery, self.catalog = Path(gate_path), delivery, catalog
        self.path = delivery.path  # The existing supervisor's outbox identity.
        self.live, self.recovery, self.requests = delivery.live, delivery.recovery, delivery.requests
        self.producer_id = delivery.producer_id
        self.start, self.stop = timestamp(start_at), timestamp(stop_at)
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.monotonic, self.stop_requested = monotonic, stop_requested
        if (self.stop-self.start != timedelta(seconds=720)
                or self.gate_path.resolve() in {delivery.path.resolve(), self.requests.path.resolve(),
                    self.live.path.resolve(), self.recovery.path.resolve()}
                or self.requests.admission is None
                or self.requests.admission.catalog_id != catalog.catalog_id
                or self.requests.admission.catalog_symbols != frozenset(catalog.symbols)):
            raise ValueError('Identity gate requires a distinct ledger and the bound request catalog/window')
        self.identity = freeze({'contract': 'integrated-nasdaq-identity-gate-v1',
            'gate_path': str(self.gate_path.resolve()), 'delivery': plain(delivery.identity),
            'catalog_id': catalog.catalog_id, 'catalog_sha256': digest(catalog.public),
            'start_at_utc': utc_text(self.start), 'stop_at_utc': utc_text(self.stop),
            'maximum_identity_quote_permits': 3, 'maximum_distinct_authorized_symbols': 1,
            'request_timeout_seconds': 3, 'selection': 'first_exact_broker_confirmation',
            'normal_admission_required': True, 'production_access': False})

    def _connect(self, write=False):
        return sqlite3.connect(self.gate_path.resolve().as_uri()+('?mode=rw' if write else '?mode=ro'),
            uri=True, timeout=5)

    def initialize(self, *, create=False):
        source = plain(self.delivery.snapshot())
        self.catalog.validate()
        if create:
            if source['commands'] or source['deliveries']:
                raise ValueError('Fresh gate cannot adopt existing outbox commands or deliveries')
            with self.gate_path.open('xb'):
                pass
            with closing(self._connect(True)) as c, c:
                c.execute('CREATE TABLE identity_binding(id INTEGER PRIMARY KEY CHECK(id=1),payload TEXT NOT NULL)')
                c.execute('INSERT INTO identity_binding VALUES(1,?)', (canonical(self.identity),))
                c.execute('CREATE TABLE identity_event(sequence INTEGER PRIMARY KEY,payload TEXT NOT NULL)')
        elif not self.gate_path.is_file() or self.gate_path.is_symlink():
            raise FileNotFoundError('Missing identity gate; restore instead of resetting permits or selection')
        return self.snapshot()

    def _code(self, e, *, reservations, decisions, selected, permits):
        cid, at = e['command_id'], timestamp(e['at_utc'])
        data = e['outcome']
        if set(data) != {'transport', 'status', 'response', 'elapsed_seconds', 'stopped', 'reuse_of'}:
            raise ValueError('Identity outcome fields differ')
        if (type(data['stopped']) is not bool or data['status'] is not None and type(data['status']) is not int
                or data['transport'] not in ('returned', 'failed', 'authorization_required', 'not_called')):
            raise ValueError('Invalid identity outcome')
        if cid in reservations:
            if data['reuse_of'] is not None:
                raise ValueError('Reserved lookup cannot borrow a different response')
            elapsed = data['elapsed_seconds']
            if (isinstance(elapsed, bool) or not isinstance(elapsed, (int, float))
                    or not math.isfinite(elapsed) or elapsed < 0
                    or len(canonical(data['response']).encode()) > MAX_RESPONSE_BYTES):
                raise ValueError('Invalid bounded identity response')
            if data['transport'] == 'authorization_required' or data['status'] in (401, 403, 429):
                return 'provider_stop_required'
            if data['stopped']:
                return 'stopped'
            if not self.start <= at < self.stop:
                return 'window_ended'
            if elapsed > 3:
                return 'identity_timeout'
            return ('approved' if data['transport'] == 'returned'
                and _confirmed(data['status'], data['response'], e['symbol']) else 'identity_unconfirmed')
        if (data['transport'] != 'not_called' or any(data[k] is not None
                for k in ('status', 'response', 'elapsed_seconds'))):
            raise ValueError('Identity response without a durable reservation')
        if data['stopped']:
            expected = 'stopped'
        elif not self.start <= at < self.stop:
            expected = 'window_ended'
        elif selected and selected[0] != e['symbol']:
            expected = 'one_symbol_limit'
        elif e['symbol'] not in self.catalog.symbols:
            expected = 'catalog_unresolved'
        elif selected:
            if data['reuse_of'] != selected[1]:
                raise ValueError('Exact session identity reuse origin differs')
            return 'approved'
        elif permits >= 3:
            expected = 'identity_budget_exhausted'
        else:
            raise ValueError('Identity decision lacks required broker reservation')
        if data['reuse_of'] is not None:
            raise ValueError('Nonapproval cannot borrow identity')
        return expected

    def _catalog_sha256(self,catalog):
        return digest(catalog.public)

    def _read(self, c):
        fresh = self.catalog.validate()
        if (fresh.catalog_id != self.identity['catalog_id'] or self._catalog_sha256(fresh) != self.identity['catalog_sha256']
                or canonical(self.delivery.identity) != canonical(self.identity['delivery'])
                or utc_text(self.start) != self.identity['start_at_utc']
                or utc_text(self.stop) != self.identity['stop_at_utc']
                or str(self.gate_path.resolve()) != self.identity['gate_path']
                or self.producer_id != self.identity['delivery']['producer_id']):
            raise ValueError('Identity gate dependencies changed')
        source = plain(self.delivery.snapshot())
        if c.execute('SELECT payload FROM identity_binding WHERE id=1').fetchone() != (canonical(self.identity),):
            raise ValueError('Identity gate binding differs')
        events, reservations, decisions, selected = [], {}, {}, None
        previous, last, terminal = digest(self.identity), None, False
        fields = {'sequence', 'kind', 'command_id', 'command_sha256', 'symbol', 'at_utc',
            'previous_sha256', 'event_sha256'}
        for n, raw in c.execute('SELECT * FROM identity_event ORDER BY sequence'):
            e = strict_json(raw)
            at = timestamp(e['at_utc']); cid = e['command_id']
            command = source['commands'].get(cid, {}).get('command')
            body = dict(e); sha = body.pop('event_sha256')
            if (canonical(e) != raw or command is None or e['sequence'] != len(events)+1 or n != e['sequence']
                    or e['previous_sha256'] != previous or sha != digest(body)
                    or e['command_sha256'] != digest(command) or e['symbol'] != command['symbol']
                    or at < timestamp(command['created_at_utc']) or last is not None and at < last):
                raise ValueError('Identity event chain or source command differs')
            if e['kind'] == 'reservation':
                if (set(e) != fields or cid in reservations or cid in decisions or len(reservations) >= 3
                        or terminal or selected or e['symbol'] not in self.catalog.symbols
                        or not self.start <= at < self.stop):
                    raise ValueError('Invalid identity reservation or cumulative budget')
                reservations[cid] = e
            elif e['kind'] == 'decision':
                if set(e) != fields | {'code', 'outcome'} or cid in decisions or terminal:
                    raise ValueError('Invalid or repeated identity decision')
                code = self._code(e, reservations=reservations, decisions=decisions,
                    selected=selected, permits=len(reservations))
                if e['code'] != code:
                    raise ValueError('Identity disposition differs from retained evidence')
                if code == 'approved':
                    if selected and selected[0] != e['symbol']:
                        raise ValueError('More than one symbol authorized')
                    selected = selected or (e['symbol'], cid)
                decisions[cid] = e
                terminal = code == 'provider_stop_required'
            else:
                raise ValueError('Unknown identity event')
            events.append(e); previous, last = sha, at
        approved = {cid for cid, e in decisions.items() if e['code'] == 'approved'}
        # A bypass of this adapter is detected before further API or delivery.
        request_events = self.requests.events()
        if (set(source['deliveries']) - approved or any(e.kind == 'request'
                and e.actor_id == self.producer_id and e.command_id not in approved for e in request_events)):
            raise ValueError('Shared request delivery bypassed the identity gate')
        return source, events, reservations, decisions, selected, terminal, previous

    def snapshot(self):
        with closing(self._connect()) as c:
            c.execute('BEGIN')
            source, events, reservations, decisions, selected, terminal, _ = self._read(c)
        outcomes = {cid: e['code'] for cid, e in decisions.items()}
        outcomes.update({cid: 'identity_outcome_unknown_no_retry' for cid in reservations if cid not in decisions})
        pending = [cid for cid in source['pending'] if cid not in outcomes or outcomes[cid] == 'approved']
        return freeze({**source, 'pending': pending, 'identity_gate': {
            'events': events, 'dispositions': outcomes, 'quote_permits': len(reservations),
            'selected_symbol': selected[0] if selected else None, 'provider_stop_required': terminal,
            'all_outbox_pending': source['pending'], 'catalog_id': self.catalog.catalog_id,
            'scope': 'broker_identity_and_bounded_authorization_not_tradability_or_publication'}})

    def _append(self, kind, cid, **data):
        with closing(self._connect(True)) as c, c:
            c.execute('BEGIN IMMEDIATE')
            source, events, _, _, _, _, previous = self._read(c)
            command = source['commands'][cid]['command']
            e = {'sequence': len(events)+1, 'kind': kind, 'command_id': cid,
                'command_sha256': digest(command), 'symbol': command['symbol'],
                'at_utc': utc_text(self.clock()), 'previous_sha256': previous, **data}
            e['event_sha256'] = digest(e)
            c.execute('INSERT INTO identity_event VALUES(?,?)', (e['sequence'], canonical(e)))
            self._read(c)  # Validate this proposed append before its transaction commits.
        return freeze(e)

    def reconcile(self, *, include_recovery=True):
        self.snapshot()  # Missing/corrupt gate blocks even ordinary source queuing.
        return self.delivery.reconcile(include_recovery=include_recovery)

    def authorize(self, cid, client, *, fault_hook=None):
        with owner_lock(self.gate_path.with_suffix('.identity-owner.lock')):
            return self._authorize(cid, client, fault_hook=fault_hook)

    def _authorize(self, cid, client, *, fault_hook=None):
        snap = plain(self.snapshot()); state = snap['identity_gate']
        if cid not in snap['commands']:
            raise ValueError('Identity decision requires a validated source outbox command')
        if cid in state['dispositions']:
            return state['dispositions'][cid]
        if state['provider_stop_required']:
            raise IdentityStopRequired('provider_stop_required')
        symbol = snap['commands'][cid]['command']['symbol']
        stopped = bool(self.stop_requested())
        reuse = next((e['command_id'] for e in state['events'] if e.get('code') == 'approved'), None)
        if (stopped or not self.start <= self.clock() < self.stop
                or state['selected_symbol'] or symbol not in self.catalog.symbols or state['quote_permits'] >= 3):
            code = ('stopped' if stopped else 'window_ended' if not self.start <= self.clock() < self.stop else
                'one_symbol_limit' if state['selected_symbol'] and symbol != state['selected_symbol'] else
                'catalog_unresolved' if symbol not in self.catalog.symbols else
                'approved' if state['selected_symbol'] else 'identity_budget_exhausted')
            self._append('decision', cid, code=code, outcome={'transport': 'not_called', 'status': None,
                'response': None, 'elapsed_seconds': None, 'stopped': stopped,
                'reuse_of': reuse if code == 'approved' else None})
            return code
        self._append('reservation', cid)
        if fault_hook: fault_hook('after_identity_reservation')
        began = self.monotonic()
        status, payload, transport = None, None, 'not_called'
        stopped = bool(self.stop_requested())
        if not stopped and self.start <= self.clock() < self.stop:
            try:
                response = client.quotes([symbol], fields='all')
                if type(response.status_code) is not int:
                    raise ValueError()
                status = response.status_code
                body = response.json()
                if len(canonical(body).encode()) > MAX_RESPONSE_BYTES:
                    raise ValueError()
                payload = json.loads(canonical(body))
                transport = 'returned'
            except StartupError:
                transport = 'authorization_required'
            except Exception:
                transport = 'failed'  # Never retain arbitrary SDK exception values.
        if fault_hook: fault_hook('after_identity_response')
        outcome = {'transport': transport, 'status': status, 'response': payload,
            'elapsed_seconds': self.monotonic()-began, 'stopped': stopped or bool(self.stop_requested()), 'reuse_of': None}
        probe = {'command_id': cid, 'at_utc': utc_text(self.clock()), 'symbol': symbol, 'outcome': outcome}
        code = self._code(probe, reservations={cid: True}, decisions={}, selected=None, permits=1)
        self._append('decision', cid, code=code, outcome=outcome)
        return code

    def deliver_pending(self, *, client, after_submit=None, fault_hook=None):
        """Commit the same native request/reuse/ACK as the accepted adapter.

        Only the event-selection gate is new. Request admission/restrictions,
        original command metadata, same-source reuse and exact retries remain
        owned by the normal request store and base outbox's validators.
        """
        results = []
        with owner_lock(self.gate_path.with_suffix('.identity-owner.lock')):
            for cid in plain(self.delivery.snapshot())['pending']:
                code = self._authorize(cid, client, fault_hook=fault_hook)
                if code == 'provider_stop_required':
                    raise IdentityStopRequired(code)
                if code != 'approved':
                    continue
                with closing(self.delivery._connect(write=True)) as c, c:
                    c.execute('BEGIN IMMEDIATE')
                    _, queued, acks, _ = self.delivery._read(c)
                    if cid in acks:
                        continue
                    if self.stop_requested() or not self.start <= self.clock() < self.stop:
                        raise IdentityStopRequired('profile_window_or_stop')
                    entry = queued[cid]
                    candidates = [k for k, v in acks.items() if v['accepted'] and 'reused_request_id' not in v]
                    alias = self.requests.reuse_active_request(_intent(entry['command']),
                        actor_id=self.producer_id, candidate_request_ids=candidates)
                    result = self.requests.submit_request(_intent(entry['command']), actor_id=self.producer_id)
                    if after_submit: after_submit(result)
                    ack = self.delivery._ack(entry, result.event, alias)
                    c.execute('INSERT INTO delivery_ack VALUES(?,?)', (cid, canonical(ack)))
                    results.append(result)
        self.snapshot()
        return tuple(results)
