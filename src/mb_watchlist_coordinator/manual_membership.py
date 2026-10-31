"""Local manual controls over existing request, policy and publication ledgers.

The attaching application supplies a trusted fixed actor, not a producer field
from a command. This is a local adapter, not network/OS authentication. It never
publishes membership, ticks policy, calls a provider or controls a process.
The first candidate accepts promotions only within the verified opening Uni;
outside-Uni manual identity/admission is deliberately not bypassed here.
"""
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from uuid import uuid4

from .models import IntentType, ProducerIntent
from .sampling_projection import SamplingMembership, require_aware
from .sampling_requests import canonical, digest, freeze, identifier, plain, timestamp, utc_text
from .sampling_service import owner_lock
from .session import session_expiration, session_start

CONTRACT = 'manual-membership-controls-v1'
RANK = {'absent': -1, 'uni': 0, 'focus': 1, 'hot': 2}
ACTIONS = ('promote', 'demote', 'withdraw', 'limit', 'clear_limit')


def group(members, symbol):
    return next((c for c in ('hot', 'focus', 'uni') if symbol in members[c]), 'absent')


class ManualMembershipControls:
    def __init__(self, path, *, publication, actor_id, allow_restrictions=False, clock=None):
        identifier(actor_id, 'actor_id')
        self.path = Path(path).resolve()
        self.publication, self.requests = publication, publication.requests
        self.clock = clock or publication.clock
        self.actor_id, self.allow_restrictions = actor_id, allow_restrictions
        if type(allow_restrictions) is not bool or actor_id == '__coordinator__':
            raise ValueError('Explicit local manual identity required')
        admission, policy = self.requests.admission, self.requests.policy
        if admission is not None and actor_id not in admission.allowed_sources:
            raise ValueError('Manual source is not enabled in this request session')
        if allow_restrictions and (policy is None or actor_id != policy.super_user_id):
            raise ValueError('The bound actor is not the restriction authority')
        if self.path in {self.requests.path.resolve(), publication.path.resolve(),
                        Path(publication.journal.identity['path']).resolve()}:
            raise ValueError('Manual receipts require a separate ledger')
        self.identity = freeze({'contract': CONTRACT, 'path': str(self.path),
            'actor_id': actor_id, 'allow_restrictions': allow_restrictions,
            'publication_identity': plain(publication.identity),
            'promotion_scope': 'opening_uni_only',
            'verified_symbols': sorted(self.requests.baseline.uni)})

    @property
    def lock_path(self):
        return self.path.with_suffix('.owner.lock')

    def _configuration(self):
        self.publication._configuration()
        if (self.actor_id != self.identity['actor_id']
                or self.allow_restrictions is not self.identity['allow_restrictions']
                or canonical(self.publication.identity) != canonical(self.identity['publication_identity'])
                or str(self.path) != self.identity['path']
                or sorted(self.requests.baseline.uni) != list(self.identity['verified_symbols'])):
            raise ValueError('Manual control binding changed')

    def now(self):
        value = self.clock()
        require_aware(value, 'manual clock')
        return value

    def initialize(self):
        """Create only manual receipts, after validating initialized backend state."""
        self._configuration()
        self.publication.snapshot()
        if not self.path.parent.is_dir():
            raise ValueError('Existing explicit manual receipt directory required')
        with owner_lock(self.lock_path), closing(sqlite3.connect(self.path)) as c, c:
            c.execute('BEGIN IMMEDIATE')
            tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if tables and tables != {'manual_identity', 'manual_event'}:
                raise ValueError('Existing file is not a manual receipt ledger')
            c.execute('CREATE TABLE IF NOT EXISTS manual_identity (id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL)')
            row = c.execute('SELECT payload FROM manual_identity WHERE id=1').fetchone()
            if row and row[0] != canonical(self.identity):
                raise ValueError('Manual receipt binding differs')
            c.execute('INSERT OR IGNORE INTO manual_identity VALUES(1,?)', (canonical(self.identity),))
            c.execute('CREATE TABLE IF NOT EXISTS manual_event (sequence INTEGER PRIMARY KEY, payload TEXT NOT NULL)')
        self.snapshot()

    @staticmethod
    def _command(action, *, symbol=None, target=None, request_id=None, reason=''):
        if action not in ACTIONS or not isinstance(reason, str) or len(reason) > 500:
            raise ValueError('Supported manual action and reason of at most 500 characters required')
        if action in ('promote', 'limit', 'clear_limit'):
            SamplingMembership(frozenset({symbol}), frozenset(), frozenset())
        elif symbol is not None:
            raise ValueError('Withdrawal selects an own request ID, not another symbol')
        if action == 'promote' and target not in ('focus', 'hot'):
            raise ValueError('Promotion target must be Focus or Hot')
        if action == 'limit' and target not in ('uni', 'focus'):
            raise ValueError('Demotion limit must be Uni or Focus')
        if action == 'demote' and target not in ('uni', 'focus'):
            raise ValueError('Own-request demotion target must be Uni or Focus')
        if action in ('demote', 'withdraw', 'clear_limit'):
            identifier(request_id, 'selected request/restriction ID')
        elif request_id is not None:
            raise ValueError('This action creates its own request ID')
        if action in ('withdraw', 'clear_limit') and target is not None:
            raise ValueError('Selected action has no target group')
        return {'action': action, 'symbol': symbol, 'target': target,
                'request_id': request_id, 'reason': reason}

    def _read(self):
        self._configuration()
        with closing(sqlite3.connect(self.path.as_uri()+'?mode=ro', uri=True)) as c:
            c.execute('PRAGMA query_only=ON'); c.execute('BEGIN')
            row = c.execute('SELECT payload FROM manual_identity WHERE id=1').fetchone()
            if not row or row[0] != canonical(self.identity):
                raise ValueError('Original manual receipt binding required')
            values = [json.loads(r[0]) for r in c.execute('SELECT payload FROM manual_event ORDER BY sequence')]
        previous, commands, results, last = digest(self.identity), {}, {}, None
        for number, value in enumerate(values, 1):
            unsigned = dict(value); sha = unsigned.pop('event_sha256')
            at = timestamp(value['at_utc'])
            if (value['sequence'] != number or value['previous_sha256'] != previous
                    or sha != digest(unsigned) or last is not None and at < last):
                raise ValueError('Manual receipt sequence/hash/time differs')
            cid = identifier(value['command_id'], 'command_id')
            if value['kind'] == 'requested':
                self._command(**value['command'])
                if cid in commands:
                    raise ValueError('Duplicate manual command')
                commands[cid] = value
            elif value['kind'] == 'result':
                if cid not in commands or cid in results:
                    raise ValueError('Manual result has no unique original command')
                results[cid] = value
            else:
                raise ValueError('Unknown manual receipt kind')
            previous, last = sha, at
        return values, commands, results

    def _append(self, kind, cid, **payload):
        values, _, _ = self._read()
        at = self.now()
        if values and at < timestamp(values[-1]['at_utc']):
            raise ValueError('Manual receipt clock moved backwards')
        value = {'sequence': len(values)+1, 'kind': kind, 'command_id': cid,
            'at_utc': utc_text(at), 'previous_sha256': values[-1]['event_sha256'] if values else digest(self.identity), **payload}
        value['event_sha256'] = digest(value)
        with closing(sqlite3.connect(self.path)) as c, c:
            c.execute('INSERT INTO manual_event VALUES(?,?)', (value['sequence'], canonical(value)))
        return value

    def submit(self, action, *, command_id=None, fault_hook=None, **kwargs):
        """Save intent before dispatch; exact retries retain the first timestamp/ID."""
        command = self._command(action, **kwargs)
        cid = identifier(command_id or 'manual-'+uuid4().hex, 'command_id')
        with owner_lock(self.lock_path):
            _, commands, results = self._read()
            old = commands.get(cid)
            if old and canonical(old['command']) != canonical(command):
                raise ValueError('Manual command ID already has different content')
            requested = old or self._append('requested', cid, command=command)
            if cid not in results:
                if fault_hook: fault_hook('after_requested')
                self._apply(requested, fault_hook=fault_hook)
        return cid

    def retry(self, command_id):
        with owner_lock(self.lock_path):
            _, commands, results = self._read()
            if command_id not in commands:
                raise ValueError('Unknown manual command')
            if command_id not in results:
                self._apply(commands[command_id])
        return command_id

    def _apply(self, requested, *, fault_hook=None):
        self._configuration()
        with owner_lock(self.publication.lock_path):
            self.publication._read()
        command, cid, now = requested['command'], requested['command_id'], self.now()
        action, symbol, target = command['action'], command['symbol'], command['target']
        # Reconstruct an already committed backend outcome before any fresh
        # preflight (including after close). A lost response cannot create demand.
        kind = {'promote': 'request', 'demote': 'cancel', 'withdraw': 'cancel', 'limit': 'restrict', 'clear_limit': 'clear_restriction'}[action]
        prior = next((e for e in self.requests.events()
                      if (e.actor_id, e.kind, e.command_id) == (self.actor_id, kind, cid)), None)
        blocked = None
        if prior is None:
            if not session_start(self.requests.session_date) <= now < self.publication.settings.publish_until:
                blocked = 'manual_session_closed'
            elif action == 'promote' and symbol not in self.requests.baseline.uni:
                blocked = 'manual_identity_confirmation_required'
            elif action in ('limit', 'clear_limit') and not self.allow_restrictions:
                blocked = 'not_restriction_authority'
        if blocked:
            self._append('result', cid, accepted=False, rejection_reason=blocked, backend_sequence=None, backend_sha256=None)
            return
        replacement = None
        # Even a recovered receipt goes through the backend's exact-content
        # idempotency check. Matching only its actor/ID would permit a collision.
        if action == 'promote':
            intent = ProducerIntent(cid, self.actor_id, IntentType.ENSURE_PRESENT,
                frozenset({symbol}), timestamp(requested['at_utc']),
                expires_at=min(self.publication.settings.publish_until, session_expiration(self.requests.session_date)),
                reason=command['reason'], metadata={'sampling_channel': target,
                    'session_date': str(self.requests.session_date), 'manual_controls': CONTRACT})
            prior = self.requests.submit_request(intent, actor_id=self.actor_id).event
        elif action == 'demote':
            events = self.requests.events()
            original = next((e for e in events if e.kind == 'request' and e.accepted
                and e.actor_id == self.actor_id and e.command_id == command['request_id']), None)
            cancelled = any(e.kind == 'cancel' and e.accepted and e.payload['owner_id'] == self.actor_id
                and e.payload['request_id'] == command['request_id'] and e.command_id != cid for e in events)
            expired = original is not None and original.payload['expires_at_utc'] is not None and now >= timestamp(original.payload['expires_at_utc'])
            if original is None or cancelled or expired and prior is None or len(original.payload['symbols']) != 1 or RANK[target] >= RANK[original.payload['sampling_channel']]:
                self._append('result', cid, accepted=False, rejection_reason='own_active_higher_request_required',
                    backend_sequence=None, backend_sha256=None)
                return
            if target == 'focus':
                # Add the lower demand first. An interruption cannot transiently
                # remove Focus before the original Hot demand is withdrawn.
                replacement = self.requests.submit_request(ProducerIntent(cid+':replacement', self.actor_id,
                    IntentType.ENSURE_PRESENT, frozenset(original.payload['symbols']), timestamp(requested['at_utc']),
                    expires_at=self.publication.settings.publish_until, reason=command['reason'],
                    metadata={'sampling_channel':'focus','session_date':str(self.requests.session_date),
                              'manual_controls':CONTRACT}), actor_id=self.actor_id).event
                if not replacement.accepted:
                    self._append('result', cid, accepted=False, rejection_reason=replacement.rejection_reason,
                        backend_sequence=None, backend_sha256=None,
                        replacement_sequence=replacement.sequence, replacement_sha256=replacement.event_sha256)
                    return
                if fault_hook: fault_hook('after_replacement')
            prior = self.requests.cancel_request(cid, owner_id=self.actor_id,
                request_id=command['request_id'], actor_id=self.actor_id, reason=command['reason']).event
        elif action == 'withdraw':
            prior = self.requests.cancel_request(cid, owner_id=self.actor_id,
                request_id=command['request_id'], actor_id=self.actor_id, reason=command['reason']).event
        elif action == 'limit':
            prior = self.requests.restrict_symbol(cid, symbol=symbol, max_group=target,
                actor_id=self.actor_id, expires_at=self.publication.settings.publish_until,
                reason=command['reason']).event
        else:
            prior = self.requests.clear_restriction(cid, symbol=symbol,
                restriction_id=command['request_id'], actor_id=self.actor_id, reason=command['reason']).event
        if fault_hook: fault_hook('after_backend')
        self._append('result', cid, accepted=prior.accepted, rejection_reason=prior.rejection_reason,
            backend_sequence=prior.sequence, backend_sha256=prior.event_sha256,
            **({'replacement_sequence':replacement.sequence, 'replacement_sha256':replacement.event_sha256}
               if replacement is not None else {}))

    def snapshot(self):
        """Validate durable receipts and one backend prefix; never drive publication."""
        with owner_lock(self.lock_path):
            _, commands, results = self._read()
            with owner_lock(self.publication.lock_path):
                source = self.publication._read()
            now = self.now()
            states, events = source['request_states'], source['request_events']
            state = states[-1]
            if state.as_of is not None and now < state.as_of:
                raise ValueError('Manual feedback clock precedes committed request evidence')
            effective = [r for r in source['journal'] if timestamp(r['proposal']['effective_at_utc']) <= now]
            current = effective[-1] if effective else None
            effective_hashes = {r['content_sha256'] for r in effective}
            effective_processed = 0
            for outcome in source['outcomes']:
                if outcome['kind'] == 'acknowledged':
                    proposal = outcome['journal_receipt']['proposal']
                    if timestamp(proposal['effective_at_utc']) <= now:
                        effective_processed = max(effective_processed, proposal['metadata']['request_state']['sequence'])
                elif outcome['kind'] == 'no_change' and outcome['journal_content_sha256'] in effective_hashes:
                    effective_processed = max(effective_processed, outcome['request_sequence'])
            members = {c: list(current['proposal'][c+'_symbols']) if current else [] for c in ('uni', 'focus', 'hot')}
            rows = []
            by_id = {(e.actor_id, e.command_id): e for e in events if e.kind == 'request'}
            for cid, requested in commands.items():
                command, receipt = requested['command'], results.get(cid)
                action, symbol, target = command['action'], command['symbol'], command['target']
                if action in ('withdraw', 'demote'):
                    original = by_id.get((self.actor_id, command['request_id']))
                    symbol = next(iter(original.payload['symbols'])) if original else None
                row = {'command_id': cid, 'action': action, 'symbol': symbol, 'requested_group': target,
                    'requested_at_utc': requested['at_utc'], 'request_id': command['request_id'],
                    'effective_group': group(members, symbol), 'status': 'REQUESTED',
                    'detail': 'Saved; backend receipt pending. Retry retains this command ID.',
                    'backend_sequence': None, 'publication_pending': True}
                row['own_request_id'] = cid if action == 'promote' else cid+':replacement' if action == 'demote' and target == 'focus' else None
                if receipt:
                    n = receipt['backend_sequence']
                    if n is not None:
                        if (type(n) is not int or not 1 <= n <= len(events)
                                or events[n-1].actor_id != self.actor_id or events[n-1].command_id != cid
                                or events[n-1].event_sha256 != receipt['backend_sha256']
                                or events[n-1].accepted != receipt['accepted']
                                or events[n-1].rejection_reason != receipt['rejection_reason']):
                            raise ValueError('Manual result differs from verified backend receipt')
                    replacement_n = receipt.get('replacement_sequence')
                    if replacement_n is not None:
                        if (type(replacement_n) is not int or not 1 <= replacement_n <= len(events)
                                or events[replacement_n-1].kind != 'request'
                                or events[replacement_n-1].actor_id != self.actor_id
                                or events[replacement_n-1].command_id != cid+':replacement'
                                or events[replacement_n-1].event_sha256 != receipt['replacement_sha256']):
                            raise ValueError('Manual replacement differs from its backend receipt')
                    row.update(backend_sequence=n, publication_pending=n is not None and n > effective_processed)
                    if not receipt['accepted']:
                        row.update(status='BLOCKED', detail=receipt['rejection_reason'], publication_pending=False)
                    else:
                        active = any(r['producer_id'] == self.actor_id and r['intent_id'] == cid for r in state.active_requests)
                        restrictions = [plain(r) for r in state.active_restrictions if r['symbol'] == symbol]
                        holds = [plain(h) for h in state.demotion_holds if h['symbol'] == symbol]
                        others = [r['producer_id'] for r in state.active_requests
                                  if symbol in r['symbols'] and r['producer_id'] != self.actor_id]
                        row.update(active_restrictions=restrictions, demotion_holds=holds, other_sources=sorted(set(others)))
                        pending = row['publication_pending']
                        if action == 'promote':
                            cancelled = any(e.accepted and e.kind == 'cancel' and e.payload['owner_id'] == self.actor_id
                                            and e.payload['request_id'] == cid for e in events)
                            blocked = any(RANK[target] > RANK[r['max_group']] for r in restrictions)
                            if cancelled:
                                row.update(status='WITHDRAWN', detail='Own request withdrawn; other demand, opening membership or timers may retain membership.')
                            elif now >= timestamp(events[n-1].payload['expires_at_utc']):
                                row.update(status='EXPIRED', detail='Request lifetime ended; effective membership is shown separately.')
                            elif blocked:
                                row.update(status='BLOCKED', detail='Active privileged restriction caps this request.')
                            elif active and not pending and RANK[row['effective_group']] >= RANK[target]:
                                row.update(status='EFFECTIVE', detail='Verified effective native membership satisfies this request.')
                            else:
                                row.update(status='PENDING', detail='Accepted; awaiting publication or its effective time.', publication_pending=True)
                        elif action == 'demote':
                            settled = not pending and RANK[row['effective_group']] <= RANK[target]
                            cancelled = target == 'focus' and any(e.accepted and e.kind == 'cancel'
                                and e.payload['owner_id'] == self.actor_id and e.payload['request_id'] == cid+':replacement' for e in events)
                            row.update(status='WITHDRAWN' if cancelled else 'PENDING' if pending else 'EFFECTIVE' if settled else 'LOWERED' if others else 'PENDING',
                                detail='Own higher request replaced by lower demand; other sources still request higher membership.' if others else
                                    'Own demand lowered; stabilization/publication may retain higher membership.' if not settled else
                                    'Own demand lowered and native effective membership confirms the demotion.',
                                publication_pending=pending or not settled and not others and not cancelled)
                        elif action == 'withdraw':
                            row.update(status='WITHDRAWN', detail=('Own demand withdrawn; other sources still request membership.' if others else
                                'Own demand withdrawn; stabilization or opening membership may retain the symbol.' if holds or row['effective_group'] != 'absent' else 'Own request withdrawn.'))
                        elif action == 'limit':
                            still_current = any(r['restriction_id'] == cid for r in restrictions)
                            settled = not pending and RANK[row['effective_group']] <= RANK[target]
                            row.update(status=('EFFECTIVE' if settled else 'PENDING') if still_current else 'INACTIVE',
                                detail='Privileged cap overrides ordinary source demand.' if still_current else 'Restriction cleared, replaced or expired.',
                                publication_pending=still_current and not settled)
                        else:
                            row.update(status='PENDING' if pending else 'CLEARED', detail='Restriction released; remaining source demand and policy determine membership.')
                rows.append(row)
            return {'contract': CONTRACT, 'observed_at_utc': utc_text(now),
                'session_date': str(self.requests.session_date), 'actor_id': self.actor_id,
                'allow_restrictions': self.allow_restrictions, 'promotion_scope': self.identity['promotion_scope'],
                'effective_revision': current['proposal']['revision'] if current else None,
                'members': members, 'commands': rows, 'processed_sequence': source['processed_sequence'],
                'publication_pending': source['pending'] is not None or source['processed_sequence']>effective_processed or any(r['publication_pending'] for r in rows),
                'provider_access': False, 'process_control': False}


class ManualMembershipModel:
    """Retain visible evidence on read failure, and disable edits until refreshed."""
    def __init__(self, controls):
        self.controls, self.last_verified, self.fresh = controls, None, False

    def refresh(self):
        try:
            value = self.controls.snapshot()
            self.last_verified, self.fresh = value, True
            return dict(value, fresh=True)
        except Exception as error:
            self.fresh = False
            return {'fresh': False, 'error': type(error).__name__, 'last_verified': self.last_verified}

    def submit(self, action, **kwargs):
        if not self.fresh:
            raise ValueError('Refresh verified membership before submitting an action')
        return self.controls.submit(action, **kwargs)
