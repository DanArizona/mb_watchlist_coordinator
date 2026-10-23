"""Durable catalog-invocation ownership before native bootstrap initialization.

One invocation reserves both directory permits conservatively. An interrupted
or failed invocation cannot be retried under the same experiment identity.
Captured successful bytes can be reconstructed without network; full manual
controller resume remains a separate integration boundary.
"""
import base64
from contextlib import closing
from dataclasses import replace
from datetime import datetime, timezone, timedelta
from pathlib import Path
import re
import sqlite3

from .integrated_catalog import DirectoryCatalog, SOURCES, MAX_BYTES
from .sampling_admission import AdmissionPolicy
from .sampling_requests import canonical, digest, freeze, plain, timestamp, utc_text

CONTRACT = 'catalog-authenticated-recovery-bootstrap-v2'


class CatalogStartupLedger:
    def __init__(self, path, *, preflight, clock=None):
        self.path = Path(path)
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.preflight = freeze(preflight)
        self.identity = freeze({'contract': 'startup-directory-reservation-v1',
            'preflight_configuration_sha256': digest(preflight),
            'sources': SOURCES, 'maximum_invocations': 1, 'reserved_source_permits': 2,
            'directory_path': str(self.path.parent.resolve()/'catalog'),
            'started_at_utc': preflight['settings']['password_submitted_at_utc'],
            'deadline_utc': utc_text(min(timestamp(preflight['start_at_utc']),
                timestamp(preflight['settings']['password_submitted_at_utc'])+timedelta(seconds=60))),
            'retry_unknown': False})

    def _connect(self, write=False):
        if self.path.is_symlink():
            raise ValueError('Catalog reservation ledger cannot be a symlink')
        return sqlite3.connect(self.path.resolve().as_uri()+('?mode=rw' if write else '?mode=ro'),
            uri=True, timeout=5)

    def initialize(self, *, create=False):
        if create:
            with self.path.open('xb'):
                pass
            with closing(self._connect(True)) as c, c:
                c.execute('CREATE TABLE catalog_startup_identity(id INTEGER PRIMARY KEY CHECK(id=1),payload TEXT NOT NULL)')
                c.execute('INSERT INTO catalog_startup_identity VALUES(1,?)', (canonical(self.identity),))
                c.execute('CREATE TABLE catalog_startup_event(sequence INTEGER PRIMARY KEY,payload TEXT NOT NULL)')
        elif not self.path.is_file():
            raise FileNotFoundError('Restore missing catalog reservation evidence; no automatic reset')
        return self.snapshot()

    @staticmethod
    def _decode(payload):
        if set(payload) != {'sources', 'catalog_id', 'catalog_sha256'} or set(payload['sources']) != set(SOURCES):
            raise ValueError('Catalog capture source set differs')
        bodies, receipts = {}, {}
        for label, source in payload['sources'].items():
            if set(source) != {'body_b64', 'receipt'} or len(source['body_b64']) > 5_333_340:
                raise ValueError('Invalid bounded catalog capture')
            bodies[label] = base64.b64decode(source['body_b64'], validate=True)
            if len(bodies[label]) > MAX_BYTES:
                raise ValueError('Catalog capture exceeds body bound')
            receipts[label] = source['receipt']
        catalog = DirectoryCatalog(bodies, receipts)
        if catalog.catalog_id != payload['catalog_id'] or digest(catalog.public) != payload['catalog_sha256']:
            raise ValueError('Captured catalog identity differs')
        return catalog

    def _read(self, c):
        from .controller_bootstrap import strict_json
        if digest(self.preflight) != self.identity['preflight_configuration_sha256']:
            raise ValueError('Catalog preflight binding changed')
        if c.execute('SELECT payload FROM catalog_startup_identity WHERE id=1').fetchone() != (canonical(self.identity),):
            raise ValueError('Catalog reservation identity differs')
        events, previous, last, catalog = [], digest(self.identity), None, None
        for n, raw in c.execute('SELECT * FROM catalog_startup_event ORDER BY sequence'):
            if len(raw.encode()) > 12_000_000:
                raise ValueError('Catalog reservation event exceeds bound')
            e = strict_json(raw); body = dict(e); sha = body.pop('event_sha256')
            at = timestamp(e['at_utc'])
            if (set(e) != {'sequence', 'kind', 'at_utc', 'payload', 'previous_sha256', 'event_sha256'}
                    or n != len(events)+1 or e['sequence'] != n or canonical(e) != raw
                    or e['previous_sha256'] != previous or sha != digest(body)
                    or at < timestamp(self.identity['started_at_utc'])
                    or last is not None and at < last):
                raise ValueError('Catalog reservation history differs')
            if n == 1:
                if (e['kind'] != 'reserved' or e['payload'] != {'source_permits': 2}
                        or at >= timestamp(self.identity['deadline_utc'])):
                    raise ValueError('Invalid catalog invocation reservation')
            elif n == 2 and e['kind'] == 'captured':
                catalog = self._decode(e['payload'])
                if at >= timestamp(self.identity['deadline_utc']):
                    raise ValueError('Catalog capture missed bootstrap window')
                for r in catalog.receipts.values():
                    if not timestamp(events[0]['at_utc']) <= timestamp(r['started_at_utc']) <= timestamp(r['retrieved_at_utc']) <= at:
                        raise ValueError('Catalog retrieval predates reservation or receipt')
            elif n == 2 and e['kind'] == 'failed':
                p = e['payload']
                if (set(p) != {'code', 'receipts'} or not re.fullmatch('[a-z_]{1,80}', p['code'])
                        or len(canonical(p['receipts']).encode()) > 12_000_000):
                    raise ValueError('Invalid retained catalog failure')
            elif n == 3 and e['kind'] == 'bound' and events[-1]['kind'] == 'captured':
                if (at >= timestamp(self.identity['deadline_utc']) or e['payload'] != {
                        'catalog_id': catalog.catalog_id, 'catalog_sha256': digest(catalog.public)}):
                    raise ValueError('Catalog binding differs')
                saved = DirectoryCatalog.load(self.identity['directory_path'])
                if saved.catalog_id != catalog.catalog_id:
                    raise ValueError('Persisted directory differs from captured evidence')
            else:
                raise ValueError('Catalog invocation repeated or history stage differs')
            events.append(e); previous, last = sha, at
        return events, catalog, previous

    def snapshot(self):
        with closing(self._connect()) as c:
            c.execute('BEGIN'); events, catalog, _ = self._read(c)
        status = ('UNRESERVED' if not events else 'PENDING_UNKNOWN' if len(events) == 1
            else 'CAPTURED' if events[-1]['kind'] == 'captured'
            else 'BOUND' if events[-1]['kind'] == 'bound' else 'FAILED')
        return freeze({'status': status, 'events': events, 'reserved_source_permits': 2 if events else 0,
            'catalog_id': catalog.catalog_id if catalog else None, 'retry_allowed': False})

    def _append(self, kind, payload):
        with closing(self._connect(True)) as c, c:
            c.execute('BEGIN IMMEDIATE'); events, _, previous = self._read(c)
            e = {'sequence': len(events)+1, 'kind': kind, 'at_utc': utc_text(self.clock()),
                'payload': payload, 'previous_sha256': previous}
            e['event_sha256'] = digest(e)
            c.execute('INSERT INTO catalog_startup_event VALUES(?,?)', (e['sequence'], canonical(e)))
            self._read(c)
        return freeze(e)

    def reserve(self):
        return self._append('reserved', {'source_permits': 2})

    def captured(self, catalog):
        catalog.validate()
        sources = {label: {'body_b64': base64.b64encode(catalog.bodies[label]).decode(),
            'receipt': plain(catalog.receipts[label])} for label in SOURCES}
        return self._append('captured', {'sources': sources, 'catalog_id': catalog.catalog_id,
            'catalog_sha256': digest(catalog.public)})

    def failed(self, error):
        return self._append('failed', {'code': error.code, 'receipts': plain(error.receipts)})

    def bound(self, catalog):
        return self._append('bound', {'catalog_id': catalog.catalog_id, 'catalog_sha256': digest(catalog.public)})

    def recovered_catalog(self):
        """Reconstruct captured public facts only; never start network or native state."""
        with closing(self._connect()) as c:
            c.execute('BEGIN'); _, catalog, _ = self._read(c)
        if catalog is None:
            raise ValueError('Catalog outcome is unknown or failed; no retry is authorized')
        return catalog


def bind_catalog(plan, catalog):
    from .controller_bootstrap import OWNER
    admission = AdmissionPolicy(catalog.catalog_id, frozenset(catalog.symbols), frozenset({OWNER}), 1, 'session')
    public = {**plain(plan.public), 'admission': admission.payload(),
        'preflight_configuration_sha256': plan.configuration_sha256,
        'catalog_scope': 'captured_exact_directory_bound_before_native_initialization',
        'catalog_binding': {'catalog_id': catalog.catalog_id, 'catalog_sha256': digest(catalog.public)}}
    return replace(plan, admission=admission, public=freeze(public), configuration_sha256=digest(public))
