"""Multi-symbol publication reads with complete current-value comparisons.

Only derived parsing/replay is reused. Every read compares every persisted
membership value and every request/publication ledger row. No timestamp, size,
head-only shortcut or persistent trust cache is used. New data uses the original
native membership parser and original publication/request semantic validators.
"""
from contextlib import closing
import json
import os
import sqlite3
from threading import RLock

from mb_market_data.quote_observation_store import QuoteObservationStore, _require_aware
from .sampling_journal import SamplingJournal
from .sampling_service import SamplingPublicationService
from .sampling_requests import canonical, timestamp, utc_text, freeze
from .sampling_service import owner_lock

TABLES = ('sampling_membership_revision', 'sampling_channel_revision', 'sampling_channel_member')


def q(value):
    return '"'+value.replace('"', '""')+'"'


class MultiMembershipStore(QuoteObservationStore):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self._multi_lock = RLock()
        self._mirror = sqlite3.connect(':memory:',uri=True,check_same_thread=False)
        self._mirror.row_factory = sqlite3.Row
        self._mirror.execute('PRAGMA temp_store=MEMORY')
        self._columns, self._parsed = {}, {}
        self.proof_generation, self._proof_file = 0, None

    def _proof(self):
        self._require_schema_version(2)
        with self._multi_lock:
            c = self._mirror
            if self._proof_file is None:self._proof_file = self._file_id()
            if self._file_id() != self._proof_file:
                raise ValueError('Previously verified membership file was replaced')
            c.execute('ATTACH DATABASE ? AS source',
                (self.database_path.resolve().as_uri()+'?mode=ro',))
            try:
                c.execute('BEGIN')
                changed = False
                old_revision = max((key[1] for key in self._parsed), default=-1)
                for table in TABLES:
                    info = c.execute('PRAGMA source.table_info('+q(table)+')').fetchall()
                    columns = tuple(row['name'] for row in info)
                    if not columns or '_source_rowid' in columns:
                        raise ValueError('Membership schema differs')
                    if table in self._columns:
                        if self._columns[table] != tuple(tuple(r) for r in info):
                            raise ValueError('Previously verified membership schema changed')
                        different = ' OR '.join(
                            'a.'+q(col)+' IS NOT b.'+q(col)+
                            ' OR typeof(a.'+q(col)+') IS NOT typeof(b.'+q(col)+')'
                            for col in columns)
                        if c.execute('SELECT 1 FROM main.'+q(table)+' b LEFT JOIN source.'+q(table)+
                                ' a ON a.rowid=b._source_rowid WHERE a.rowid IS NULL OR '+different+' LIMIT 1').fetchone():
                            raise ValueError('Previously verified membership values changed')
                        where = ' WHERE a.rowid NOT IN (SELECT _source_rowid FROM main.'+q(table)+')'
                        if c.execute('SELECT 1 FROM source.'+q(table)+' a'+where+
                                ' AND a.revision<=? LIMIT 1', (old_revision,)).fetchone():
                            raise ValueError('An old verified revision gained new membership data')
                        if c.execute('SELECT 1 FROM source.'+q(table)+' a'+where+' LIMIT 1').fetchone():
                            c.execute('INSERT INTO main.'+q(table)+' SELECT a.rowid,a.* FROM source.'+q(table)+' a'+where)
                            changed = True
                    else:
                        c.execute('CREATE TABLE main.'+q(table)+' AS SELECT a.rowid AS _source_rowid,a.* FROM source.'+q(table)+' a')
                        c.execute('CREATE UNIQUE INDEX '+q(table+'_proof_rowid')+' ON '+q(table)+'(_source_rowid)')
                        keys = [r['name'] for r in sorted(info,key=lambda r:r['pk']) if r['pk']]
                        if keys:
                            c.execute('CREATE UNIQUE INDEX '+q(table+'_proof_keys')+' ON '+q(table)+
                                '('+','.join(map(q,keys))+')')
                        self._columns[table] = tuple(tuple(r) for r in info)
                        changed = True
                rows = c.execute('SELECT * FROM sampling_membership_revision ORDER BY effective_at_utc,revision').fetchall()
                result = []
                for row in rows:
                    key = (row['session_date'],row['revision'])
                    if key not in self._parsed:
                        self._parsed[key] = QuoteObservationStore._membership_revision_from_row(self,c,row)
                    result.append(self._parsed[key])
                if self._file_id() != self._proof_file:
                    raise ValueError('Membership file changed during verification')
                c.commit()
                if changed: self.proof_generation += 1
                return tuple(result)
            except BaseException:
                c.rollback()
                self._columns.clear(); self._parsed.clear()
                for table in TABLES: c.execute('DROP TABLE IF EXISTS main.'+q(table))
                c.commit()
                raise
            finally:
                # No real journal handle is retained between reads (Windows).
                c.execute('DETACH DATABASE source')

    def _file_id(self):
        value = os.stat(self.database_path,follow_symlinks=False)
        return value.st_dev,value.st_ino,value.st_mode

    def membership_revisions_in_effective_order(self):
        return self._proof()

    def latest_membership_revision_effective_at(self,value):
        _require_aware(value,'value')
        at = value
        return max((r for r in self._proof() if r.effective_at<=at),
            key=lambda r:(r.effective_at,r.revision),default=None)

    def __del__(self):
        if hasattr(self,'_mirror'):
            try:self._mirror.close()
            except sqlite3.Error:pass


class MultiSamplingJournal(SamplingJournal):
    def revisions(self,*,opening_only=False):
        self._check()
        if not hasattr(self,'_payloads'): self._payloads = {}
        result = []
        values = self.store.membership_revisions_in_effective_order()
        for value in (values[:2] if opening_only else values):
            key = value.session_date,value.revision
            old = self._payloads.get(key)
            if old is None or old[0] is not value:
                payload = {'session_date':value.session_date.isoformat(),'revision':value.revision,
                    'effective_at_utc':utc_text(value.effective_at),'uni_symbols':list(value.uni_symbols),
                    'focus_symbols':list(value.focus_symbols),'hot_symbols':list(value.hot_symbols),
                    'source':value.source,'reason':value.reason,
                    'metadata':json.loads(canonical(value.metadata))}
                if self._reconstructed_hash(payload)!=value.content_sha256:
                    raise ValueError('Native membership reconstruction differs')
                wire = json.dumps({'proposal':payload,'content_sha256':value.content_sha256,
                    'published_at_utc':utc_text(value.published_at)},separators=(',',':'),allow_nan=False)
                self._payloads[key] = (value,wire)
            # Detach mutable public values from the private derived cache.
            result.append(json.loads(self._payloads[key][1]))
        return result


class MultiPublicationService(SamplingPublicationService):
    @staticmethod
    def _rows(path, names=None):
        with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)) as c:
            c.execute('BEGIN')
            tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if names is None:names=tuple(sorted(n for n in tables if not n.startswith('sqlite_')))
            return tuple((name,tuple(c.execute('PRAGMA table_info('+q(name)+')')),
                tuple(c.execute('SELECT * FROM '+q(name)+' ORDER BY rowid')))
                if name in tables else (name,None,None) for name in names)

    def _inputs(self):
        self._configuration(); self.requests._check_configuration(); self.journal._check()
        self.journal.store.membership_revisions_in_effective_order()
        return (self.journal.store.proof_generation,
            self._rows(self.path,('publication_identity','publication_event')),
            self._rows(self.requests.path,('request_identity','request_event','request_reuse')))

    def _read(self):
        current = self._inputs()
        old = getattr(self,'_validated_read',None)
        if old is not None and old[0] == current:
            return old[1]
        value = super()._read()
        after = self._inputs()
        self._validated_read = (after,value) if after==current else None
        return value

    def snapshot(self):
        with owner_lock(self.lock_path):value=self._read()
        # _read returns a private completed replay, never modified by _append
        # or cycle. Pure copying/freezing need not retain the writer's lease.
        old=getattr(self,'_frozen_read',None)
        if old is not None and old[0]is value:return old[1]
        target=value['request_states'][-1].applied
        latest=value['journal'][-1]['proposal']
        additions_only=all(set(latest[channel+'_symbols'])<=getattr(target,channel)for channel in ('uni','focus','hot'))
        result=freeze({**{k:v for k,v in value.items()if k not in ('request_events','request_states')},
            'batchable_additions_only':additions_only})
        self._frozen_read=(value,result)
        return result

    def collector_snapshot(self):
        """Full original validation, compact immutable collector projection.

        No validation is omitted: _read still replays all changed inputs and
        compares every current value. The collector needs the verified revision
        and roster fields, rather than copies of historical plan/ACK metadata.
        """
        with owner_lock(self.lock_path):value=self._read()
        old=getattr(self,'_collector_read',None)
        if old is not None and old[0]is value:return old[1]
        result=freeze({'head_sha256':value['head_sha256'],'projection':'verified_collector_membership',
            'journal':[{'proposal':{k:r['proposal'][k]for k in ('session_date','revision','effective_at_utc',
                'uni_symbols','focus_symbols','hot_symbols')},'content_sha256':r['content_sha256'],
                'published_at_utc':r['published_at_utc']}for r in value['journal']]})
        self._collector_read=(value,result)
        return result
