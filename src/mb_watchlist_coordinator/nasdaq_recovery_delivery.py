"""Explicit shared live/recovery request outbox; no HTTP or process control.

Fresh v3 observation and recovery ledgers are read-only evidence inputs. One
new, distinct source owner delivers their common halt IDs through normal request
admission. This does not migrate a direct-delivery producer or declare READY.
"""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

from .nasdaq_recovery import reduce_receipts, regular_window
from .nasdaq_sampling import _intent, _reduce
from .sampling_projection import require_aware
from .sampling_requests import canonical, digest, freeze, identifier, plain, request_payload, timestamp, utc_text


class NasdaqRecoveryDelivery:
    """Trusted local adapter, with request commit before durable outbox ACK.

    The owner is reserved to this outbox; manual/algorithmic demand is separate.
    Every read validates current source prefixes, queued commands, request
    receipts and reuse bindings. No verified prefix survives a read.
    """
    def __init__(self, path, *, live_producer, recovery_receipts, producer_id, clock=None):
        identifier(producer_id, 'producer_id')
        if producer_id == '__coordinator__' or producer_id == live_producer.settings.producer_id:
            raise ValueError('Shared delivery requires a distinct nonreserved source owner')
        if live_producer.settings.delivery_mode != 'external' or live_producer.settings.replay_mode:
            raise ValueError('Shared delivery requires a live external observation producer')
        if canonical(live_producer.request_store.identity) != canonical(recovery_receipts.requests.identity):
            raise ValueError('Live and recovery request identities differ')
        if live_producer.request_store.path.resolve() != recovery_receipts.requests.path.resolve():
            raise ValueError('Live and recovery must use the same request ledger')
        if live_producer.settings.reason_codes != recovery_receipts.settings.reason_codes:
            raise ValueError('Live and recovery reason selections differ')
        self.path = Path(path)
        self.live, self.recovery = live_producer, recovery_receipts
        self.requests = live_producer.request_store
        self.producer_id = producer_id
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        paths = [self.path, self.live.path, self.recovery.path, self.requests.path]
        if len({p.resolve() for p in paths}) != len(paths):
            raise ValueError('Delivery, sources and request ledgers must be distinct')
        self.identity = freeze(self._identity())

    def _identity(self):
        return {'contract': 'nasdaq-live-recovery-delivery-v1', 'producer_id': self.producer_id,
            'request_identity': plain(self.requests.identity), 'live_identity': plain(self.live.identity),
            'recovery_identity': plain(self.recovery.identity), 'request_lifetime': 'regular_close',
            'recovery_gate': 'declared_queries_complete', 'publication': 'external_not_verified'}

    def _sources(self):
        if canonical(self._identity()) != canonical(self.identity):
            raise ValueError('Shared delivery configuration changed')
        live, recovery = plain(self.live.snapshot()), plain(self.recovery.snapshot())
        if live['deliveries']:
            raise ValueError('External observation source cannot have direct delivery acknowledgements')
        return {'live': live, 'recovery': recovery}

    def _connect(self, *, write=False):
        return sqlite3.connect(self.path.resolve().as_uri() + ('?mode=rw' if write else '?mode=ro'), uri=True, timeout=5)

    def initialize(self, *, create=False):
        self._sources()
        events, _, aliases = self.requests.validated_reuse_history()
        if create:
            if (any(e.actor_id == self.producer_id for e in events)
                    or any(owner == self.producer_id for owner, _ in aliases)):
                raise ValueError('Fresh shared delivery cannot adopt unbound source demand')
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open('xb'):
                pass
            with closing(self._connect(write=True)) as c, c:
                c.execute('CREATE TABLE delivery_identity (id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL)')
                c.execute('INSERT INTO delivery_identity VALUES(1,?)', (canonical(self.identity),))
                c.execute('CREATE TABLE delivery_command (sequence INTEGER PRIMARY KEY, event_id TEXT UNIQUE NOT NULL, payload TEXT NOT NULL)')
                c.execute('CREATE TABLE delivery_ack (event_id TEXT PRIMARY KEY, payload TEXT NOT NULL)')
        elif not self.path.is_file():
            raise FileNotFoundError('Missing shared delivery ledger; restore or explicitly create a new experiment')
        return self.snapshot()

    def _prefix_candidates(self, kind, receipts):
        if kind == 'live':
            commands, _ = _reduce(self.live.identity, receipts)
            return commands
        state = reduce_receipts(self.recovery.identity, receipts)
        if state['pending_query_ids']:
            return {}
        return {f['event_id']: f for f in state['candidates']
                if f['decision'] == 'eligible_for_normal_admission_review'}

    def _command(self, event_id, proof, at, sources, cache):
        if set(proof) != {'kind', 'prefix_length', 'prefix_sha256'}:
            raise ValueError('Invalid source prefix proof fields')
        kind, n = proof['kind'], proof['prefix_length']
        if kind not in ('live', 'recovery') or type(n) is not int or n <= 0:
            raise ValueError('Invalid source prefix proof')
        receipts = sources[kind]['receipts']
        if n > len(receipts) or receipts[n-1]['event_sha256'] != proof['prefix_sha256']:
            raise ValueError('Delivery source prefix changed or is incomplete')
        prefix = receipts[:n]
        key = (kind, n)
        if key not in cache:
            cache[key] = self._prefix_candidates(kind, prefix)
        fact = cache[key].get(event_id)
        if fact is None:
            raise ValueError('Queued event is not eligible in its source prefix')
        last_at = timestamp(prefix[-1]['recorded_at_utc' if kind == 'live' else 'received_at_utc'])
        if at < last_at:
            raise ValueError('Queued command predates available source prefix')
        if kind == 'live':
            metadata = fact['metadata']
            row, known = metadata['halt_event'], metadata['adapter_first_seen_at_utc']
            receipt_sha = metadata['producer_receipt_sha256']
            captured = metadata['capture_retrieved_at_utc']
            raw_sha = metadata['capture_raw_sha256']
        else:
            observation = fact['observations'][0]
            row, known = observation['row'], fact['first_recovered_at_utc']
            receipt_sha, captured = observation['receipt_sha256'], observation['retrieved_at_utc']
            raw_sha = observation['raw_sha256']
        start, stop = regular_window(self.requests.session_date)
        if not start <= at < stop or timestamp(known) > at:
            raise ValueError('Delivery commands require current-session available knowledge')
        return {'intent_id': event_id, 'producer_id': self.producer_id, 'symbol': fact['symbol'],
            'created_at_utc': utc_text(at), 'expires_at_utc': utc_text(stop),
            'source_event_id': event_id, 'reason': 'Nasdaq halt ' + row['reason_code'],
            'metadata': {'sampling_channel': 'hot', 'session_date': self.requests.session_date.isoformat(),
                'halt_event': plain(row), 'halt_at_utc': (fact['metadata']['halt_at_utc'] if kind == 'live' else fact['halt_at_utc']),
                'source_kind': kind, 'source_first_observed_at_utc': known,
                'capture_retrieved_at_utc': captured, 'capture_raw_sha256': raw_sha,
                'source_receipt_sha256': receipt_sha, 'source_prefix_proof': plain(proof),
                'request_lifetime': 'regular_close'}}

    def _read(self, c):
        if c.execute('SELECT payload FROM delivery_identity WHERE id=1').fetchone() != (canonical(self.identity),):
            raise ValueError('Shared delivery ledger identity differs')
        sources = self._sources()
        events, _, aliases = self.requests.validated_reuse_history()
        if any(e.actor_id == self.live.settings.producer_id for e in events):
            raise ValueError('External observation owner must not submit direct requests')
        previous, last_at, queued, cache = digest(self.identity), None, {}, {}
        for n, event_id, raw in c.execute('SELECT * FROM delivery_command ORDER BY sequence'):
            value = json.loads(raw)
            body = dict(value); sha = body.pop('event_sha256')
            at = timestamp(value['queued_at_utc'])
            if (value['sequence'] != len(queued)+1 or n != value['sequence']
                    or value['event_id'] != event_id or value['previous_sha256'] != previous
                    or sha != digest(body) or last_at is not None and at < last_at):
                raise ValueError('Shared delivery command chain differs')
            expected = self._command(event_id, value['source_proof'], at, sources, cache)
            if canonical(expected) != canonical(value['command']):
                raise ValueError('Shared delivery command differs from source evidence')
            queued[event_id] = value
            previous, last_at = sha, at
        request_events = {e.command_id: e for e in events if e.kind == 'request' and e.actor_id == self.producer_id}
        owned_aliases = {cid: a for (owner, cid), a in aliases.items() if owner == self.producer_id}
        # The dedicated owner cannot silently adopt unrelated or direct demand.
        if set(request_events) - set(queued) or set(owned_aliases) - set(queued):
            raise ValueError('Shared source owner has unbound request history')
        for cid, event in request_events.items():
            if canonical(event.payload) != canonical(request_payload(_intent(queued[cid]['command']))):
                raise ValueError('Shared pending request payload differs')
        for cid, alias in owned_aliases.items():
            expected = {'command_id': cid, 'kind': 'request', 'actor_id': self.producer_id,
                        'payload': request_payload(_intent(queued[cid]['command']))}
            target = events[alias['request_sequence']-1]
            if (canonical(alias['command']) != canonical(expected) or target.command_id not in request_events
                    or not target.accepted or target.command_id == cid):
                raise ValueError('Shared reuse origin differs')
        acks = {}
        for cid, raw in c.execute('SELECT * FROM delivery_ack'):
            ack = json.loads(raw)
            if cid not in queued:
                raise ValueError('Unknown shared delivery acknowledgement')
            alias = owned_aliases.get(cid)
            target = events[alias['request_sequence']-1] if alias else request_events.get(cid)
            if target is None or canonical(ack) != canonical(self._ack(queued[cid], target, alias)):
                raise ValueError('Shared delivery acknowledgement differs')
            acks[cid] = ack
        return sources, queued, acks, previous

    @staticmethod
    def _ack(queued, event, alias):
        result = {'command_sha256': digest(queued['command']), 'request_sequence': event.sequence,
            'request_event_sha256': event.event_sha256, 'accepted': event.accepted,
            'rejection_reason': event.rejection_reason}
        if alias:
            result.update(reused_request_id=event.command_id, reuse_receipt_sha256=alias['receipt_sha256'])
        return result

    def snapshot(self):
        with closing(self._connect()) as c:
            c.execute('BEGIN')
            sources, queued, acks, _ = self._read(c)
            return freeze({'stage': 'REQUEST_DELIVERY', 'status': 'RECOVERING',
                'query_scope': sources['recovery']['query_scope'], 'known_gaps': sources['recovery']['known_gaps'],
                'commands': queued, 'deliveries': acks, 'pending': [k for k in queued if k not in acks],
                'publication': 'EXTERNAL_NOT_VERIFIED', 'process_recovery': 'NOT_IMPLEMENTED'})

    def reconcile(self):
        """Durably queue new known events; recovery waits for all declared queries.

        Existing queue entries are immutable, so recovery/live overlap, changed
        feed versions and cancellation can never replace an original command.
        The normal CURRENT startup baseline and HISTORICAL meanings are intact.
        """
        added = []
        with closing(self._connect(write=True)) as c, c:
            c.execute('BEGIN IMMEDIATE')
            sources, queued, _, previous = self._read(c)
            at = self.clock(); require_aware(at, 'delivery queue clock')
            start, stop = regular_window(self.requests.session_date)
            if not start <= at < stop:
                raise ValueError('Reconciliation must run in the target regular session')
            if queued and at < timestamp(next(reversed(queued.values()))['queued_at_utc']):
                raise ValueError('Delivery queue clock moved backwards')
            cache = {}
            # Prefer live provenance when both sources are known in this read.
            for kind in ('live', 'recovery'):
                receipts = sources[kind]['receipts']
                if not receipts:
                    continue
                proof = {'kind': kind, 'prefix_length': len(receipts), 'prefix_sha256': receipts[-1]['event_sha256']}
                candidates = self._prefix_candidates(kind, receipts)
                cache[kind, len(receipts)] = candidates
                for eid in sorted(candidates):
                    if eid in queued:
                        continue
                    command = self._command(eid, proof, at, sources, cache)
                    entry = {'sequence': len(queued)+1, 'event_id': eid, 'source_proof': proof,
                        'queued_at_utc': utc_text(at), 'command': command, 'previous_sha256': previous}
                    entry['event_sha256'] = digest(entry)
                    c.execute('INSERT INTO delivery_command VALUES(?,?,?)', (entry['sequence'], eid, canonical(entry)))
                    queued[eid] = entry; previous = entry['event_sha256']; added.append(eid)
        return tuple(added)

    def deliver_pending(self, *, after_submit=None):
        results = []
        with closing(self._connect(write=True)) as c, c:
            c.execute('BEGIN IMMEDIATE')
            _, queued, acks, _ = self._read(c)
            for cid, entry in queued.items():
                if cid in acks:
                    continue
                candidates = [key for key, value in acks.items()
                              if value['accepted'] and 'reused_request_id' not in value]
                alias = self.requests.reuse_active_request(_intent(entry['command']),
                    actor_id=self.producer_id, candidate_request_ids=candidates)
                result = self.requests.submit_request(_intent(entry['command']), actor_id=self.producer_id)
                if after_submit:
                    after_submit(result)
                ack = self._ack(entry, result.event, alias)
                c.execute('INSERT INTO delivery_ack VALUES(?,?)', (cid, canonical(ack)))
                acks[cid] = ack; results.append(result)
        return tuple(results)
