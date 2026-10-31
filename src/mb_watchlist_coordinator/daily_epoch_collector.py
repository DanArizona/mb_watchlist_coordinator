"""Bounded active collection periods in one full schema-v2 session journal.

All membership/admission history remains checked. Quote-payload verification is
explicitly scoped to the active five-minute period; the independent native audit
and replays check the complete journal after stop. Closed periods are not claimed
as freshly payload-verified by a current heartbeat. No history is deleted.
"""
from contextlib import closing
from dataclasses import asdict,replace
from datetime import timedelta
from functools import lru_cache
import json,os,sqlite3
from pathlib import Path
from uuid import uuid4

from mb_market_data.daily_hot_acquisition import DailyHotPoller
from mb_market_data.sampling_acquisition import IsolatedSamplingPoller,AcquisitionSettings
from mb_market_data.quote_observation_store import PollRunProvenance
from mb_market_data.watchlist_polling import PollWindow
from mb_market_data.sampling_membership import SamplingChannel
from mb_market_data.polling_cadence import RESERVED_HOT_SECONDS
from .daily_collector import DailyHotCollector,DailyCollectorSettings
from .nasdaq_recovery import regular_window
from .operating_plan import MULTI_PROFILE
from .recovery_workers import atomic_json,read_process_text
from .sampling_requests import digest,freeze,plain,timestamp,utc_text

CONTRACT='daily-hot-collection-periods-v1'
PERIOD_SECONDS=300


@lru_cache(maxsize=256)
def period_windows(start_text,stop_text):
    start,stop=timestamp(start_text),timestamp(stop_text)
    regular_start,_=regular_window(start.date())
    at=regular_start;result=[];index=0
    while at<stop:
        end=at+timedelta(seconds=PERIOD_SECONDS)
        lo,hi=max(start,at),min(stop,end)
        if lo<hi:
            minute=lo.replace(second=0,microsecond=0);count=0
            while minute<hi:
                count+=sum(lo<=minute.replace(second=s)<hi for s in RESERVED_HOT_SECONDS)
                minute+=timedelta(minutes=1)
            if count:result.append((index,utc_text(lo),utc_text(hi),count))
        at=end;index+=1
    return tuple(result)


class EpochHotPoller(DailyHotPoller):
    def __init__(self,*args,epoch_spec,**kwargs):
        from mb_market_data.daily_raw_history import SCOPED_DAILY_HISTORY_SUPPORTED
        if SCOPED_DAILY_HISTORY_SUPPORTED is not True:raise ValueError('Pinned scoped native reader required')
        self.epoch_spec=freeze(epoch_spec)
        self.history_scope=tuple(map(timestamp,(epoch_spec['start'],epoch_spec['stop'])))
        super().__init__(*args,**kwargs)
        self.path=self.journal.database_path.resolve().with_suffix(f'.hot.e{epoch_spec["index"]:02d}.poller.sqlite3')
        self.lock_path=self.path.with_suffix('.lock')
        self.identity.update(contract=CONTRACT,epoch_spec=plain(self.epoch_spec),
            history_scope=[utc_text(at)for at in self.history_scope])

    def _validate_daily(self):
        super()._validate_daily()
        parent=DailyCollectorSettings(**plain(self.epoch_spec['parent']))
        expected=next((p for p in period_windows(parent.start_at_utc,parent.stop_at_utc)
            if p[0]==self.epoch_spec['index']),None)
        if (expected is None or expected[1:3]!=(self.epoch_spec['start'],self.epoch_spec['stop'])
                or self.history_scope!=(self.settings.window.start_at,self.settings.window.end_at)
                or self.max_quote_calls!=expected[3]
                or self.daily_binding!=plain(parent.daily_binding)
                or parent.max_quote_calls<sum(p[3]for p in period_windows(parent.start_at_utc,parent.stop_at_utc))
                or self.epoch_spec['parent_sha256']!=digest(parent.payload())):
            raise ValueError('Fixed collection period or full-session binding differs')
        if hasattr(self,'identity') and (self.identity.get('epoch_spec')!=plain(self.epoch_spec)
                or self.identity.get('history_scope')!=[utc_text(at)for at in self.history_scope]):
            raise ValueError('Collection history scope changed')

    def verified_shutdown_snapshot(self):
        """Read-only native content check after the live process fence stops.

        This never dispatches, recovers, registers runs or writes a ledger. The
        normal live validator remains mandatory for every new acquisition.
        """
        from mb_market_data.daily_acquisition_reader import read_daily_history
        from .sampling_service import owner_lock
        with owner_lock(self.lock_path):
            with closing(sqlite3.connect(self.path.as_uri()+'?mode=ro',uri=True))as c:
                return read_daily_history(self,c)

    def initialize(self):
        self._validate_daily()
        # The session-level manifest already checked foreign Hot registrations.
        # The native initializer refuses foreign outcomes within this period.
        return IsolatedSamplingPoller.initialize(self)


class _BorrowedClient:
    def __init__(self,owner):self.owner=owner
    @property
    def halt_reason(self):return getattr(self.owner.client,'halt_reason',None)
    def quotes(self,*args,**kwargs):return self.owner.client.quotes(*args,**kwargs)
    def close(self):pass # The shared authenticated client belongs to the full worker.


class EpochHotCollector:
    def __init__(self,settings,*,publication_session,client_factory,clock=None,activation_approved=False):
        if activation_approved is not True:raise ValueError('Explicit trusted activation required')
        self.settings,self.session=settings,publication_session
        self.identity=settings.payload()
        self.clock=clock or publication_session.clock
        self.client_factory,self._client=client_factory,None
        self.windows=period_windows(settings.start_at_utc,settings.stop_at_utc)
        if (not self.windows or settings.max_quote_calls<sum(p[3]for p in self.windows)
                or settings.daily_binding['settings'].get('policy_profile')!=MULTI_PROFILE):
            raise ValueError('Period schedule must fit the exact full-session call budget')
        self.manifest=Path(settings.journal_path).with_suffix('.hot.periods.json')
        self.provider_stop_path=Path(settings.journal_path).with_suffix('.daily-hot-provider-stop.json')
        self.prepared,self.closed=False,False
        self.active=self._make(self._window())

    def _window(self):
        now=self.clock()
        return next((p for p in self.windows if now<timestamp(p[2])),self.windows[-1])

    def _make(self,window):
        index,start,stop,calls=window
        spec={'index':index,'start':start,'stop':stop,'parent':asdict(self.settings),
              'parent_sha256':digest(self.identity)}
        def factory():
            if self._client is None:self._client=self.client_factory()
            return _BorrowedClient(self)
        active=DailyHotCollector(replace(self.settings,start_at_utc=start,stop_at_utc=stop,max_quote_calls=calls),
            publication_session=self.session,client_factory=factory,clock=lambda:self.clock(),
            activation_approved=True,_epoch_spec=spec)
        if self._client is not None:active.client=_BorrowedClient(self)
        return active

    @property
    def client(self):return self._client
    @client.setter
    def client(self,value):
        self._client=value
        if value is not None and hasattr(self,'active'):self.active.client=_BorrowedClient(self)
    @property
    def poller(self):return self.active.poller
    @property
    def next(self):return self.active.next
    @next.setter
    def next(self,value):self.active.next=value
    def validate_publication(self,*args,**kwargs):return self.active.validate_publication(*args,**kwargs)

    def _read_manifest(self):
        value=json.loads(read_process_text(self.manifest));body=dict(value);sha=body.pop('content_sha256')
        if (sha!=digest(body) or body['contract']!=CONTRACT or body['settings']!=self.identity
                or body['windows']!=[list(p)for p in self.windows]):
            raise ValueError('Original complete period manifest required')
        return body

    def _closed(self,window):
        return Path(self.settings.journal_path).with_suffix(f'.hot.e{window[0]:02d}.closed.json')

    def _finalize(self,active,window,*,closed=True,shutdown=False):
        state=(active.poller.verified_shutdown_snapshot() if shutdown else active.poller.snapshot())
        if state['pending'] is not None:raise ValueError('Cannot close a period with an unacknowledged outcome')
        from .daily_epoch_integrity import verified_period_digest
        receipt={'contract':CONTRACT,'parent_sha256':digest(self.identity),'index':window[0],
            'start':window[1],'stop':window[2],'identity_sha256':digest(active.poller.identity),
            'head_sha256':state['head_sha256'],'closed_at_utc':utc_text(self.clock()),
            'verified_stored_values':verified_period_digest(active.poller),
            'quote_dispatches':sum(e['kind']=='dispatch'and bool(e['symbols'])for e in state['events']),
            'payload_verification_scope':'this period at close; full journal independently audited after stop'}
        path=(self._closed(window) if closed else Path(self.settings.journal_path).with_suffix(f'.hot.e{window[0]:02d}.checkpoint.json'))
        if closed and path.exists():
            old=json.loads(read_process_text(path));body=dict(old);sha=body.pop('content_sha256')
            if sha!=digest(body) or any(body[k]!=receipt[k]for k in receipt if k!='closed_at_utc'):
                raise ValueError('Closed-period receipt differs')
        else:atomic_json(path,dict(receipt,content_sha256=digest(receipt)))

    def prepare(self,*,create=False):
        if self.prepared or self.closed:raise ValueError('Fresh unclosed period collector required')
        self.session.validate()
        if not self.manifest.exists():
            if not create:raise ValueError('Original period manifest required')
            if any(Path(self.settings.journal_path).parent.glob(Path(self.settings.journal_path).stem+'.hot.e*')):
                raise ValueError('Unbound period files cannot be reset')
            with closing(sqlite3.connect(Path(self.settings.journal_path).as_uri()+'?mode=ro',uri=True))as c:
                if any(json.loads(r[0]).get('watchlist_kind')=='hot'for r in c.execute('SELECT configuration_json FROM poll_run')):
                    raise ValueError('An unbound Hot schedule already exists')
            parent=self.poller.settings
            schedule=replace(parent,window=PollWindow(timestamp(self.settings.start_at_utc),timestamp(self.settings.stop_at_utc)))
            run=PollRunProvenance('daily-hot-schedule-'+uuid4().hex,self.clock(),CONTRACT,
                {**schedule.payload(),'daily_hot_contract':CONTRACT,'parent_cadence_profile':'interleaved-v1',
                 'history_scope':'active five-minute period; closed payloads audited independently'})
            body={'contract':CONTRACT,'settings':self.identity,'windows':[list(p)for p in self.windows],
                'schedule_run':{'run_id':run.run_id,'started_at_utc':utc_text(run.started_at),
                    'software_version':run.software_version,'configuration':run.configuration}}
            with self.manifest.open('x',encoding='utf-8')as out:
                json.dump(dict(body,content_sha256=digest(body)),out);out.flush();os.fsync(out.fileno())
        body=self._read_manifest()
        r=body['schedule_run']
        self.session.store.record_run(PollRunProvenance(r['run_id'],timestamp(r['started_at_utc']),
            r['software_version'],r['configuration']))
        for window in self.check_retained_files():
            old=self._make(window)
            try:old.prepare();self._finalize(old,window)
            finally:old.close()
        recovered=self.active.prepare(create=not self.active.manifest.exists())
        self.prepared=True
        return recovered

    def check_retained_files(self):
        """Read-only preflight; no ledger recovery, API, lease or run creation."""
        self._read_manifest();unfinished=[]
        for window in self.windows:
            path=Path(self.settings.journal_path).with_suffix(f'.hot.e{window[0]:02d}.poller.daily-collector.json')
            closed=self._closed(window)
            ledger=Path(self.settings.journal_path).with_suffix(f'.hot.e{window[0]:02d}.poller.sqlite3')
            if path.exists()!=ledger.exists():raise ValueError('Partial period state requires its original files')
            if not (path.is_file() and ledger.is_file()):
                from mb_market_data.quote_observation_store import _utc_text
                bounds=tuple(_utc_text(timestamp(at),'period')for at in window[1:3])
                with closing(sqlite3.connect(Path(self.settings.journal_path).as_uri()+'?mode=ro',uri=True))as c:
                    count=c.execute('SELECT count(*) FROM quote_acquisition WHERE channel="hot" AND scheduled_at_utc>=? AND scheduled_at_utc<?',bounds).fetchone()[0]
                    count+=c.execute('SELECT count(*) FROM poll_slot_skip WHERE channel="hot" AND scheduled_at_utc>=? AND scheduled_at_utc<?',bounds).fetchone()[0]
                if count:raise ValueError('Native period outcomes require their original manifest and ledger')
            if closed.exists():
                receipt=json.loads(read_process_text(closed));content=dict(receipt);sha=content.pop('content_sha256')
                if (sha!=digest(content) or content['parent_sha256']!=digest(self.identity)
                        or (content['index'],content['start'],content['stop'])!=window[:3]
                        or not ledger.is_file() or ledger.is_symlink() or not path.is_file()
                        or not 0<=content['quote_dispatches']<=window[3]):
                    raise ValueError('Original closed-period files/receipt required')
                with closing(sqlite3.connect(ledger.as_uri()+'?mode=ro',uri=True))as c:
                    binding=c.execute('SELECT payload FROM acquisition_identity WHERE id=1').fetchone()
                    head=c.execute('SELECT event_sha256 FROM acquisition_event ORDER BY sequence DESC LIMIT 1').fetchone()
                if (binding is None or digest(json.loads(binding[0]))!=content['identity_sha256']
                        or (head[0]if head else digest(json.loads(binding[0])))!=content['head_sha256']):
                    raise ValueError('Closed-period identity or sealed head differs; audit original evidence')
            if path.exists() and json.loads(read_process_text(path)).get('provider_stop'):
                raise ValueError('Provider stop from an earlier period remains latched')
            if timestamp(window[2])<=self.clock() and not closed.exists() and path.exists():
                unfinished.append(window)
        return tuple(unfinished)

    def tick(self,*,fault_hook=None):
        if not self.prepared or self.closed:raise ValueError('Prepared period collector required')
        if self.clock()>=timestamp(self.settings.stop_at_utc):return {'status':'window_ended'}
        self._read_manifest()
        if self.clock()>=self.active.poller.settings.window.end_at:
            old=self.active;old_window=next(p for p in self.windows if p[0]==old.poller.epoch_spec['index'])
            self._finalize(old,old_window);old.close()
            self.active=self._make(self._window())
            self.active.prepare(create=not self.active.manifest.exists())
        result=self.active.tick(fault_hook=fault_hook)
        return dict(result,collection_period=self.active.poller.epoch_spec['index'],
            history_validation_scope='active period; full-session audit/replay after stop')

    def close(self):
        if self.closed:return
        self.closed=True
        try:
            if self.prepared:
                window=next(p for p in self.windows if p[0]==self.active.poller.epoch_spec['index'])
                self._finalize(self.active,window,closed=self.clock()>=timestamp(window[2]),shutdown=True)
        finally:
            self.active.close()
            if self._client is not None:self._client.close();self._client=None


def make_daily_collector(settings,**kwargs):
    cls=EpochHotCollector if settings.daily_binding['settings'].get('policy_profile')==MULTI_PROFILE else DailyHotCollector
    return cls(settings,**kwargs)
