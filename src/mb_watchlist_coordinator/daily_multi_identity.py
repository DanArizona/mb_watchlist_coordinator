"""Versioned multi-symbol daily identity gate; the bounded single gate is unchanged.

One pending command per pump cycle and durable two-second quote spacing keep
burst admission separate from collector progress. Every broker call is charged
before dispatch. Unknown outcomes are retained and never requested again.
"""
from collections import Counter
from contextlib import closing
import json

from .authenticated_startup import StartupError
from .daily_session import DailyIdentityGate
from .integrated_identity import IdentityStopRequired, MAX_RESPONSE_BYTES
from .nasdaq_sampling import _intent
from .sampling_requests import canonical, digest, freeze, plain, timestamp, utc_text
from .sampling_service import owner_lock

MAX_SYMBOLS = 40
MAX_CALLS = 120
PER_SYMBOL_CALLS = 3
CALL_INTERVAL = 2


class MultiIdentityGate(DailyIdentityGate):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        identity = plain(self.identity)
        identity.update(contract='daily-multi-nasdaq-identity-gate-v1',
            maximum_identity_quote_permits=MAX_CALLS,
            maximum_distinct_authorized_symbols=MAX_SYMBOLS,
            maximum_calls_per_symbol=PER_SYMBOL_CALLS,
            minimum_quote_interval_seconds=CALL_INTERVAL,
            maximum_commands_per_cycle=1,
            selection='first_40_exact_broker_confirmations')
        self.identity = freeze(identity)
        self.last_call_monotonic = None

    def _no_call(self, symbol, *, selected, reservations, decisions, at, stopped):
        if stopped:
            return 'stopped', None
        if not self.start <= at < self.stop:
            return 'window_ended', None
        if symbol in selected:
            return 'approved', selected[symbol]
        if len(selected) >= MAX_SYMBOLS:
            return 'authorization_capacity', None
        if symbol not in self.catalog.symbols:
            return 'catalog_unresolved', None
        if any(r['symbol'] == symbol and cid not in decisions for cid, r in reservations.items()):
            return 'identity_symbol_unknown_no_retry', None
        if sum(r['symbol'] == symbol for r in reservations.values()) >= PER_SYMBOL_CALLS:
            return 'symbol_identity_budget_exhausted', None
        if len(reservations) >= MAX_CALLS:
            return 'identity_budget_exhausted', None
        return None, None

    def _code(self, e, *, reservations, decisions, selected, permits):
        data = e['outcome']
        if e['command_id'] in reservations:
            return super()._code(e, reservations=reservations, decisions=decisions,
                selected=None, permits=permits)
        if (set(data) != {'transport', 'status', 'response', 'elapsed_seconds', 'stopped', 'reuse_of'}
                or data['transport'] != 'not_called' or type(data['stopped']) is not bool
                or any(data[k] is not None for k in ('status', 'response', 'elapsed_seconds'))):
            raise ValueError('Unreserved identity outcome differs')
        code, reuse = self._no_call(e['symbol'], selected=selected,
            reservations=reservations, decisions=decisions,
            at=timestamp(e['at_utc']), stopped=data['stopped'])
        if code is None or data['reuse_of'] != reuse:
            raise ValueError('Identity disposition requires its original reservation/reuse')
        return code

    def _inputs(self,c):
        from .daily_multi_publication import MultiPublicationService
        self.catalog.validate(); self.requests._check_configuration(); self.live._check()
        recovery = {'contract':'nasdaq-halt-recovery-receipts-v1',
            'request_identity':plain(self.requests.identity),'settings':self.recovery.settings.payload()}
        if (canonical(recovery)!=canonical(self.recovery.identity)
                or canonical(self.delivery._identity())!=canonical(self.delivery.identity)
                or self.delivery.live is not self.live or self.delivery.recovery is not self.recovery
                or self.delivery.requests is not self.requests):
            raise ValueError('Multi-symbol source configuration changed')
        own = tuple((name,tuple(c.execute('PRAGMA table_info('+name+')')),
            tuple(c.execute('SELECT * FROM '+name+' ORDER BY rowid')))
            for name in ('identity_binding','identity_event'))
        others = tuple((str(path.resolve()),MultiPublicationService._rows(path,None))
            for path in (self.delivery.path,self.live.path,self.recovery.path,self.requests.path))
        return (canonical(self.identity),str(self.gate_path.resolve()),self.catalog.catalog_id,
            utc_text(self.start),utc_text(self.stop),self.producer_id,own,others)

    def _read(self,c):
        current = self._inputs(c)
        old = getattr(self,'_validated_read',None)
        if old is not None and old[0]==current:
            return old[1]
        value = self._read_uncached(c)
        after = self._inputs(c)
        self._validated_read = (after,value) if current==after else None
        return value

    def _read_uncached(self, c):
        fresh = self.catalog.validate()
        if (fresh.catalog_id != self.identity['catalog_id']
                or self._catalog_sha256(fresh) != self.identity['catalog_sha256']
                or canonical(self.delivery.identity) != canonical(self.identity['delivery'])
                or utc_text(self.start) != self.identity['start_at_utc']
                or utc_text(self.stop) != self.identity['stop_at_utc']
                or str(self.gate_path.resolve()) != self.identity['gate_path']
                or self.producer_id != self.identity['delivery']['producer_id']
                or self.identity['maximum_identity_quote_permits'] != MAX_CALLS
                or self.identity['maximum_distinct_authorized_symbols'] != MAX_SYMBOLS
                or self.identity['minimum_quote_interval_seconds'] != CALL_INTERVAL):
            raise ValueError('Multi-symbol identity dependencies changed')
        source = plain(self.delivery.snapshot())
        if c.execute('SELECT payload FROM identity_binding WHERE id=1').fetchone() != (canonical(self.identity),):
            raise ValueError('Multi-symbol identity binding differs')
        events, reservations, decisions, selected = [], {}, {}, {}
        previous, last, last_quote, terminal = digest(self.identity), None, None, False
        fields = {'sequence', 'kind', 'command_id', 'command_sha256', 'symbol', 'at_utc',
                  'previous_sha256', 'event_sha256'}
        attempts = Counter()
        for n, raw in c.execute('SELECT * FROM identity_event ORDER BY sequence'):
            from .controller_bootstrap import strict_json
            e = strict_json(raw)
            at, cid = timestamp(e['at_utc']), e['command_id']
            command = source['commands'].get(cid, {}).get('command')
            body = dict(e); sha = body.pop('event_sha256')
            if (canonical(e) != raw or command is None or e['sequence'] != len(events)+1
                    or n != e['sequence'] or e['previous_sha256'] != previous or sha != digest(body)
                    or e['command_sha256'] != digest(command) or e['symbol'] != command['symbol']
                    or at < timestamp(command['created_at_utc']) or last is not None and at < last):
                raise ValueError('Multi-symbol identity event chain differs')
            if e['kind'] == 'reservation':
                code, _ = self._no_call(e['symbol'], selected=selected,
                    reservations=reservations, decisions=decisions, at=at, stopped=False)
                if (set(e) != fields or cid in reservations or cid in decisions or terminal
                        or code is not None or last_quote is not None and
                        (at-last_quote).total_seconds() < CALL_INTERVAL):
                    raise ValueError('Multi-symbol identity reservation, spacing or budget differs')
                reservations[cid] = e; attempts[e['symbol']] += 1; last_quote = at
            elif e['kind'] == 'decision':
                if set(e) != fields | {'code', 'outcome'} or cid in decisions or terminal:
                    raise ValueError('Multi-symbol identity decision differs')
                code = self._code(e, reservations=reservations, decisions=decisions,
                    selected=selected, permits=len(reservations))
                if e['code'] != code:
                    raise ValueError('Multi-symbol identity disposition differs')
                if code == 'approved':
                    if e['symbol'] not in selected and len(selected) >= MAX_SYMBOLS:
                        raise ValueError('Multi-symbol authorization capacity exceeded')
                    selected.setdefault(e['symbol'], cid)
                decisions[cid] = e
                terminal = code == 'provider_stop_required'
            else:
                raise ValueError('Unknown multi-symbol identity event')
            events.append(e); previous, last = sha, at
        approved = {cid for cid, e in decisions.items() if e['code'] == 'approved'}
        if (set(source['deliveries'])-approved or any(e.kind == 'request'
                and e.actor_id == self.producer_id and e.command_id not in approved
                for e in self.requests.events())):
            raise ValueError('Request delivery bypassed multi-symbol identity gate')
        return source, events, reservations, decisions, selected, terminal, previous

    def snapshot(self):
        with closing(self._connect()) as c:
            c.execute('BEGIN')
            verified=self._read(c)
        cached=getattr(self,'_frozen_snapshot',None)
        if cached is not None and cached[0]is verified:return cached[1]
        source, events, reservations, decisions, selected, terminal, _ = verified
        outcomes = {cid: e['code'] for cid, e in decisions.items()}
        outcomes.update({cid: 'identity_outcome_unknown_no_retry'
            for cid in reservations if cid not in decisions})
        pending = [cid for cid in source['pending'] if cid not in outcomes or outcomes[cid] == 'approved']
        result=freeze({**source, 'pending': pending, 'identity_gate': {
            'events': events, 'dispositions': outcomes, 'quote_permits': len(reservations),
            'authorized_symbols': sorted(selected),
            'selected_symbol': next(iter(selected), None), 'provider_stop_required': terminal,
            'all_outbox_pending': source['pending'], 'catalog_id': self.catalog.catalog_id,
            'scope': 'broker_identity_and_bounded_authorization_not_tradability_or_publication'}})
        self._frozen_snapshot=(verified,result)
        return result

    def _authorize(self, cid, client, *, fault_hook=None):
        snap = plain(self.snapshot()); state = snap['identity_gate']
        if cid not in snap['commands']:
            raise ValueError('Validated source outbox command required')
        if cid in state['dispositions']:
            return state['dispositions'][cid]
        if state['provider_stop_required']:
            raise IdentityStopRequired('provider_stop_required')
        symbol = snap['commands'][cid]['command']['symbol']
        reservations = {e['command_id']: e for e in state['events'] if e['kind'] == 'reservation'}
        decisions = {e['command_id']: e for e in state['events'] if e['kind'] == 'decision'}
        selected = {e['symbol']: e['command_id'] for e in reversed(state['events'])
                    if e.get('code') == 'approved'}
        stopped = bool(self.stop_requested())
        code, reuse = self._no_call(symbol, selected=selected, reservations=reservations,
            decisions=decisions, at=self.clock(), stopped=stopped)
        if code is not None:
            self._append('decision', cid, code=code, outcome={'transport': 'not_called',
                'status': None, 'response': None, 'elapsed_seconds': None,
                'stopped': stopped, 'reuse_of': reuse})
            return code
        if (reservations and (self.clock()-timestamp(next(reversed(reservations.values()))['at_utc'])).total_seconds() < CALL_INTERVAL
                or self.last_call_monotonic is not None and self.monotonic()-self.last_call_monotonic < CALL_INTERVAL):
            return 'deferred_identity_spacing'
        self._append('reservation', cid)
        self.last_call_monotonic = self.monotonic()
        if fault_hook: fault_hook('after_identity_reservation')
        began = self.monotonic()
        status, payload, transport = None, None, 'not_called'
        stopped = bool(self.stop_requested())
        if not stopped and self.start <= self.clock() < self.stop:
            try:
                response = client.quotes([symbol], fields='all')
                if type(response.status_code) is not int:
                    raise ValueError('Invalid identity status')
                status = response.status_code
                body = response.json()
                if len(canonical(body).encode()) > MAX_RESPONSE_BYTES:
                    raise ValueError('Oversized identity response')
                payload, transport = json.loads(canonical(body)), 'returned'
            except StartupError:
                transport = 'authorization_required'
            except Exception:
                transport = 'failed'
        if fault_hook: fault_hook('after_identity_response')
        outcome = {'transport': transport, 'status': status, 'response': payload,
            'elapsed_seconds': self.monotonic()-began,
            'stopped': stopped or bool(self.stop_requested()), 'reuse_of': None}
        probe = {'command_id': cid, 'at_utc': utc_text(self.clock()), 'symbol': symbol, 'outcome': outcome}
        code = self._code(probe, reservations={cid: True}, decisions={}, selected={}, permits=1)
        self._append('decision', cid, code=code, outcome=outcome)
        return code

    def deliver_pending(self, *, client, after_submit=None, fault_hook=None):
        # Bounded work per cycle; the pump returns to publication/feed/status.
        with owner_lock(self.gate_path.with_suffix('.identity-owner.lock')):
            pending = plain(self.snapshot())['pending']
            if not pending:
                return ()
            cid = pending[0]
            code = self._authorize(cid, client, fault_hook=fault_hook)
            if code == 'provider_stop_required':
                raise IdentityStopRequired(code)
            if code != 'approved':
                return ()
            with closing(self.delivery._connect(write=True)) as c, c:
                c.execute('BEGIN IMMEDIATE')
                _, queued, acks, _ = self.delivery._read(c)
                if cid in acks:
                    return ()
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
        self.snapshot()
        return (result,)
