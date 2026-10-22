"""Versioned, offline recovery receipts and candidate derivation.

This is the first recovery stage, not a process supervisor or request delivery
adapter. It records normalized dated snapshots supplied by a trusted transport.
It does not fetch a feed, publish membership, or change CURRENT/HISTORICAL
semantics in the existing live producer. Raw-body parsing/retention belongs to
that transport; the receipt retains its supplied hash and provenance.
"""
from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
import json
from pathlib import Path
import sqlite3

from .nasdaq_sampling import ET, HaltSnapshot, event_time, halt_event_id
from .sampling_projection import require_aware
from .sampling_requests import canonical, digest, freeze, identifier, plain, timestamp, utc_text


def regular_window(session):
    return datetime.combine(session, time(9, 30), ET), datetime.combine(session, time(16), ET)


@dataclass(frozen=True, slots=True)
class RecoveryQuery:
    halt_date: date | None
    resume_date: date | None

    def __post_init__(self):
        if self.halt_date is None and self.resume_date is None:
            raise ValueError('Recovery query requires an explicit date')
        for value in (self.halt_date, self.resume_date):
            if value is not None and (type(value) is not date):
                raise ValueError('Query dates must be exact dates')

    def payload(self):
        return {'halt_date': self.halt_date.isoformat() if self.halt_date else None,
                'resume_date': self.resume_date.isoformat() if self.resume_date else None}

    @property
    def query_id(self):
        return 'nasdaq-query-' + digest(self.payload())


@dataclass(frozen=True, slots=True)
class RecoverySettings:
    session_date: date
    mode: str
    queries: tuple[RecoveryQuery, ...]
    carryover_history_verified: bool
    reason_codes: tuple[str, ...] = ('LUDP', 'M')

    def __post_init__(self):
        if type(self.session_date) is not date or self.mode not in ('resume_saved', 'late_start'):
            raise ValueError('Explicit recovery session and mode required')
        if type(self.carryover_history_verified) is not bool:
            raise ValueError('Carryover verification must be explicit')
        queries = tuple(self.queries)
        if (not queries or any(type(q) is not RecoveryQuery for q in queries)
                or len({q.query_id for q in queries}) != len(queries)
                or RecoveryQuery(self.session_date, self.session_date) not in queries):
            raise ValueError('Unique queries must include the target-day halt/resumption union')
        if any(d and d > self.session_date for q in queries for d in (q.halt_date, q.resume_date)):
            raise ValueError('Recovery query cannot follow target session')
        if tuple(self.reason_codes) != ('LUDP', 'M'):
            raise ValueError('This receipt increment retains the explicit LUDP/M trial selection')
        object.__setattr__(self, 'queries', queries)
        object.__setattr__(self, 'reason_codes', ('LUDP', 'M'))

    def payload(self):
        return {'session_date': self.session_date.isoformat(), 'mode': self.mode,
                'queries': [q.payload() for q in self.queries],
                'carryover_history_verified': self.carryover_history_verified,
                'reason_codes': list(self.reason_codes), 'request_lifetime': 'regular_close'}


def reduce_receipts(identity, receipts):
    """Validate the entire prefix and derive facts without issuing requests."""
    settings = identity['settings']
    session = date.fromisoformat(settings['session_date'])
    regular_start, regular_close = regular_window(session)
    queries = {RecoveryQuery(date.fromisoformat(q['halt_date']) if q['halt_date'] else None,
        date.fromisoformat(q['resume_date']) if q['resume_date'] else None).query_id
        for q in settings['queries']}
    previous, last_at = digest(identity), None
    captures, completed, facts = set(), set(), {}
    for n, receipt in enumerate(receipts, 1):
        value = dict(receipt)
        checksum = value.pop('event_sha256')
        if (value['sequence'] != n or value['previous_sha256'] != previous
                or digest(value) != checksum or value['query_id'] not in queries):
            raise ValueError('Recovery receipt chain or query identity differs')
        at = timestamp(value['received_at_utc'])
        if last_at and at < last_at:
            raise ValueError('Recovery receipt clock moved backwards')
        if at < regular_start or at >= regular_close:
            raise ValueError('Recovery receipts must arrive during the target regular session')
        payload = value['snapshot']
        snapshot = HaltSnapshot(payload['capture_id'], timestamp(payload['retrieved_at_utc']),
            payload['retrieval_mode'], payload['raw_sha256'], tuple(payload['records']), payload['provenance'])
        if (snapshot.payload() != payload or snapshot.retrieval_mode != 'HISTORICAL'
                or snapshot.retrieved_at > at or snapshot.capture_id in captures):
            raise ValueError('Recovery requires a unique canonical available HISTORICAL snapshot')
        captures.add(snapshot.capture_id); completed.add(value['query_id'])
        unique = {}
        for row in snapshot.records:
            eid = halt_event_id(row)
            if event_time(row) > snapshot.retrieved_at:
                raise ValueError('Halt follows available recovery evidence')
            if eid in unique and canonical(unique[eid]) != canonical(row):
                raise ValueError('Conflicting rows for one halt in a recovery capture')
            unique[eid] = row
        for eid, row in sorted(unique.items()):
            fact = facts.setdefault(eid, {'event_id': eid, 'symbol': row['symbol'],
                'halt_at_utc': utc_text(event_time(row)), 'first_reason_code': row['reason_code'],
                'first_recovered_at_utc': utc_text(at), 'first_capture_id': snapshot.capture_id,
                'observations': []})
            fact['observations'].append({'capture_id': snapshot.capture_id,
                'retrieved_at_utc': utc_text(snapshot.retrieved_at), 'recovered_at_utc': utc_text(at),
                'query_id': value['query_id'], 'raw_sha256': snapshot.raw_sha256,
                'row': plain(row), 'receipt_sha256': checksum})
        previous, last_at = checksum, at
    candidates = []
    for eid, fact in sorted(facts.items()):
        halt = timestamp(fact['halt_at_utc'])
        if not regular_start <= halt < regular_close:
            decision = 'context_only_other_session_or_off_hours'
        elif fact['first_reason_code'] not in settings['reason_codes']:
            decision = 'unresolved_original_reason'
        else:
            decision = 'eligible_for_normal_admission_review'
        candidates.append(dict(fact, decision=decision))
    pending = sorted(queries - completed)
    gaps = ['intermediate_feed_mutations_not_reconstructible']
    if not settings['carryover_history_verified']:
        gaps.append('older_unknown_carryovers_not_proven_complete')
    return {'stage': 'RECEIPTS_ONLY', 'status': 'RECOVERING',
        'query_scope': 'INCOMPLETE' if pending else 'COMPLETE_WITH_TRACE_GAPS',
        'completed_query_ids': sorted(completed), 'pending_query_ids': pending,
        'last_receipt_at_utc': utc_text(last_at) if last_at else None,
        'candidates': candidates, 'known_gaps': gaps, 'head_sha256': previous,
        'delivery': 'NOT_IMPLEMENTED', 'publication': 'NOT_ATTEMPTED'}


class NasdaqRecoveryReceipts:
    """Append-only dated-recovery input ledger, bound to a verified request identity.

    initialize(create=True) is an explicit new experiment. Normal reopen never
    recreates a lost file. Candidate derivation grants no admission authority.
    """
    def __init__(self, path, *, request_store, settings: RecoverySettings, clock=None):
        if settings.session_date != request_store.session_date:
            raise ValueError('Recovery and request sessions differ')
        self.path = Path(path)
        if self.path.resolve() == request_store.path.resolve():
            raise ValueError('Recovery and request ledgers must be different files')
        self.requests, self.settings = request_store, settings
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.identity = freeze({'contract': 'nasdaq-halt-recovery-receipts-v1',
            'request_identity': plain(request_store.identity), 'settings': settings.payload()})

    def _check(self):
        self.requests._check_configuration()
        current = {'contract': 'nasdaq-halt-recovery-receipts-v1',
            'request_identity': plain(self.requests.identity), 'settings': self.settings.payload()}
        if canonical(current) != canonical(self.identity):
            raise ValueError('Recovery configuration changed')
        self.requests.validated_history()

    def initialize(self, *, create=False):
        self._check()
        if not self.path.is_file() and not create:
            raise FileNotFoundError('Missing recovery ledger; restore or explicitly declare a new experiment')
        if create:
            # Exclusive creation: a second creator cannot silently adopt a file.
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open('xb'):
                pass
            with closing(sqlite3.connect(self.path)) as c, c:
                c.execute('CREATE TABLE recovery_identity (id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL)')
                c.execute('INSERT INTO recovery_identity VALUES(1,?)', (canonical(self.identity),))
                c.execute('CREATE TABLE recovery_receipt (sequence INTEGER PRIMARY KEY, capture_id TEXT UNIQUE NOT NULL, payload TEXT NOT NULL)')
        return self.snapshot()

    def _connect(self, *, write=False):
        return sqlite3.connect(self.path.resolve().as_uri() + ('?mode=rw' if write else '?mode=ro'), uri=True)

    def _read(self, c):
        self._check()
        row = c.execute('SELECT payload FROM recovery_identity WHERE id=1').fetchone()
        if row != (canonical(self.identity),):
            raise ValueError('Recovery ledger identity differs')
        receipts = []
        for sequence, capture_id, raw in c.execute('SELECT * FROM recovery_receipt ORDER BY sequence'):
            value = json.loads(raw)
            if value['sequence'] != sequence or value['snapshot']['capture_id'] != capture_id:
                raise ValueError('Recovery receipt columns differ from payload')
            receipts.append(value)
        return receipts, reduce_receipts(self.identity, receipts)

    def snapshot(self):
        with closing(self._connect()) as c:
            receipts, state = self._read(c)
            return freeze(dict(state, receipts=receipts))

    def record(self, query: RecoveryQuery, snapshot: HaltSnapshot):
        with closing(self._connect(write=True)) as c, c:
            c.execute('BEGIN IMMEDIATE')
            receipts, state = self._read(c)
            for receipt in receipts:
                if receipt['snapshot']['capture_id'] == snapshot.capture_id:
                    if receipt['query_id'] != query.query_id or receipt['snapshot'] != snapshot.payload():
                        raise ValueError('Recovery capture ID already has different content')
                    return freeze(receipt), False
            at = self.clock()
            require_aware(at, 'recovery receipt clock')
            value = {'sequence': len(receipts) + 1, 'query_id': query.query_id,
                'received_at_utc': utc_text(at), 'snapshot': snapshot.payload(),
                'previous_sha256': state['head_sha256']}
            value['event_sha256'] = digest(value)
            reduce_receipts(self.identity, receipts + [value])
            c.execute('INSERT INTO recovery_receipt VALUES (?,?,?)',
                (value['sequence'], snapshot.capture_id, canonical(value)))
            return freeze(value), True
