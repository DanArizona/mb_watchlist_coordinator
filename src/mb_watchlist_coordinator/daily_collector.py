"""Daily native collector API; no live launcher or credential storage.

The publication session and an independent bounded owner remain prerequisites.
The accepted collector response/ACK recovery and permit counting are reused.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path

from .hot_recovery_collector import HotRecoveryCollector
from .sampling_requests import digest, plain, timestamp
from .sampling_service import owner_lock
from .recovery_workers import atomic_json


@dataclass(frozen=True)
class DailyCollectorSettings:
    journal_path: str
    publication_binding: dict
    daily_binding: dict
    daily_claim: dict
    start_at_utc: str
    stop_at_utc: str
    max_quote_calls: int
    max_symbols: int

    def payload(self):
        from mb_market_data.polling_cadence import RESERVED_HOT_SECONDS
        start, stop = timestamp(self.start_at_utc), timestamp(self.stop_at_utc)
        binding = plain(self.daily_binding)
        window_start, window_stop = map(timestamp, (binding['start_at_utc'], binding['stop_at_utc']))
        policy = binding['policy']
        if (not window_start <= start < stop <= window_stop
                or type(self.max_quote_calls) is not int or not 1 <= self.max_quote_calls <= 9360
                or self.max_quote_calls > policy['limits']['maximum_hot_quote_calls']
                or type(self.max_symbols) is not int or not 1 <= self.max_symbols <= 400
                or self.max_symbols != policy['limits']['maximum_active_hot_symbols']
                or self.journal_path != binding['settings']['journal_path']
                or self.publication_binding['journal']['path'] != self.journal_path):
            raise ValueError('Explicit daily collector window, sealed symbol limit and call ceiling required')
        return {'contract':'daily-hot-collector-v1', 'journal_path':self.journal_path,
            'publication_binding':plain(self.publication_binding),
            'daily_binding':binding, 'daily_claim':plain(self.daily_claim),
            'start_at_utc':start.isoformat(), 'stop_at_utc':stop.isoformat(),
            'max_quote_calls':self.max_quote_calls, 'max_symbols':self.max_symbols,
            'seconds':list(RESERVED_HOT_SECONDS), 'batch_size':400, 'fields':'all',
            'max_dispatch_lateness_seconds':.75, 'no_past_slot_catchup':True}


class DailyHotCollector(HotRecoveryCollector):
    def __init__(self, settings, *, publication_session, client_factory, clock=None,
                 activation_approved=False, _epoch_spec=None):
        from mb_market_data.daily_hot_acquisition import DailyHotPoller
        from mb_market_data.sampling_acquisition import AcquisitionSettings
        from mb_market_data.sampling_membership import SamplingChannel
        from mb_market_data.polling_cadence import RESERVED_HOT_SECONDS
        from mb_market_data.watchlist_polling import PollWindow
        self.settings, self.identity = settings, settings.payload()
        self.session = publication_session
        self.clock = clock or (lambda:datetime.now(timezone.utc))
        if not callable(client_factory): raise ValueError('A prepared bounded client factory is required')
        self.client_factory, self.client = client_factory, None
        self.collector_lease=None
        self.provider_stop_path=Path(settings.journal_path).with_suffix('.daily-hot-provider-stop.json')
        self.job_path = self.job = None
        if (plain(self.session.binding) != plain(settings.daily_binding)
                or plain(self.session.claim) != plain(settings.daily_claim)
                or plain(self.session.service.identity) != plain(settings.publication_binding)):
            raise ValueError('Collector must share the owned publication session')
        poller_type=DailyHotPoller
        extra={}
        if _epoch_spec is not None:
            from .daily_epoch_collector import EpochHotPoller
            poller_type=EpochHotPoller;extra={'epoch_spec':_epoch_spec}
        self.poller = poller_type(self.session.store,
            settings=AcquisitionSettings(SamplingChannel.HOT, RESERVED_HOT_SECONDS,
                PollWindow(timestamp(settings.start_at_utc),timestamp(settings.stop_at_utc)),
                400, 'all', 'daily-native-hot-v1', .75, .05), client=self,
            daily_binding=settings.daily_binding, daily_claim=settings.daily_claim,
            publication_binding=settings.publication_binding,
            validate_publication=self.validate_publication, clock=self.clock,
            activation_approved=activation_approved,max_quote_calls=settings.max_quote_calls,**extra)
        self.manifest = self.poller.path.with_suffix('.daily-collector.json')
        self.next, self.refused_call = None, False

    def prepare(self,*,create=False):
        if self.collector_lease is not None:raise ValueError('Collector is already prepared')
        self._provider_stop()
        lease=owner_lock(Path(self.settings.journal_path).with_suffix('.daily-hot-collector.lock'))
        lease.__enter__();self.collector_lease=lease
        try:
            from mb_market_data.sampling_acquisition import next_slot
            content={'settings':self.identity,'poller_identity':plain(self.poller.identity)}
            expected=dict(content,content_sha256=digest(content))
            if self.manifest.exists():
                if json.loads(self.manifest.read_text())!=expected or not self.poller.path.is_file():
                    raise ValueError('Restore original collector manifest and acquisition evidence')
            elif not create or self.poller.path.exists():
                raise ValueError('Missing collector manifest; no automatic adoption/reset')
            recovered=self.poller.initialize_and_recover()
            if not self.manifest.exists():atomic_json(self.manifest,expected)
            self.next=next_slot(self.poller.settings,after=self.clock())
            return recovered
        except BaseException:
            self.close();raise

    def close(self):
        try:super().close()
        finally:
            self.poller.close_read_cache()
            if self.collector_lease is not None:
                lease,self.collector_lease=self.collector_lease,None
                lease.__exit__(None,None,None)

    def _publication(self):
        verified = self.session.validate(with_state=True)
        publication, gate = (verified if self.settings.daily_binding['settings'].get('policy_profile') == 'multi-40-v1'
                             else map(plain, verified))
        gate = gate['identity_gate']
        if gate['provider_stop_required']:
            raise ValueError('Identity provider stop prevents new collection')
        return publication,gate

    def validate_publication(self, dispatch, *, verified_state=None):
        publication,gate = self._publication() if verified_state is None else verified_state
        if dispatch is not None:
            revision = next((r for r in publication['journal']
                if r['proposal']['revision'] == dispatch['revision']), None)
            if (revision is None or
                    list(revision['proposal']['hot_symbols']) != dispatch['symbols'] or
                    (not set(dispatch['symbols']) <= set(gate['authorized_symbols'])
                        if 'authorized_symbols' in gate else dispatch['symbols'] != [gate['selected_symbol']])):
                raise ValueError('Native dispatch does not match verified selected membership')
        if dispatch is None:self._native_publication_state=(publication,gate)
        return True

    def _check(self,*,publication=True):
        if self.collector_lease is None:raise ValueError('Owned prepared daily collector required')
        self._provider_stop()
        super()._check()
        return self._publication() if publication else None

    def quotes(self, symbols, *, fields):
        # This executes after the native durable dispatch, inside its owner lock.
        state=self.poller.provider_dispatch_state()
        multi=self.settings.daily_binding['settings'].get('policy_profile')=='multi-40-v1'
        if multi:
            # The synchronous native provider state comes from the checked read
            # after durable dispatch. Its callback just validated this exact
            # publication/gate view. Reuse that immutable view, with no blocking
            # factory work between it and this call. No persisted cache bypass.
            self._check(publication=False)
            verified=self._native_publication_state
        else:verified=self._check()
        dispatch=state['pending']['dispatch']
        self.validate_publication(dispatch,verified_state=verified)
        consumed=sum(e['kind']=='dispatch' and bool(e['symbols']) for e in state['events'])
        if (consumed>self.settings.max_quote_calls or len(symbols)>self.settings.max_symbols
                or tuple(symbols)!=tuple(dispatch['symbols']) or fields!='all'
                or not timestamp(self.settings.start_at_utc)<=self.clock()<timestamp(self.settings.stop_at_utc)
                or (self.clock()-timestamp(dispatch['scheduled_at_utc'])).total_seconds()>.75):
            self.refused_call=True
            raise ValueError('Collector call budget, roster, slot or window gate refused')
        new_client = self.client is None
        if new_client:self.client=self.client_factory()
        # The owned daily worker authenticates before prepare/tick. A prepared
        # multi-symbol client introduces no blocking work after the exact
        # publication check above; avoid repeating that same whole graph here.
        # Deferred factories and the unchanged single-symbol profile still
        # recheck after client preparation, before the original time gate.
        if new_client or self.settings.daily_binding['settings'].get('policy_profile') != 'multi-40-v1':
            self._check()
        if (self.clock()>=timestamp(self.settings.stop_at_utc)
                or (self.clock()-timestamp(dispatch['scheduled_at_utc'])).total_seconds()>.75):
            self.refused_call=True
            raise ValueError('Collector gate expired during client preparation')
        response=self.client.quotes(symbols,fields=fields)
        if response.status_code in (401,403,429):
            self.refused_call=True
            content={'contract':'daily-hot-provider-stop-v1','collector_identity_sha256':digest(self.identity),
                'status_code':response.status_code,'observed_at_utc':self.clock().isoformat()}
            receipt=dict(content,receipt_sha256=digest(content))
            atomic_json(self.provider_stop_path,receipt)
            manifest=json.loads(self.manifest.read_text())
            manifest['provider_stop']=receipt
            atomic_json(self.manifest,manifest)
        return response

    def tick(self,*,fault_hook=None):
        from mb_market_data.sampling_acquisition import next_slot
        self._check(publication=self.settings.daily_binding['settings'].get('policy_profile')!='multi-40-v1')
        if self.clock()>=timestamp(self.settings.stop_at_utc):return {'status':'window_ended'}
        if self.next is None or self.clock()<self.next.scheduled_at:
            state=self.poller.snapshot()
            if self.next is None:
                # No future slot remains. Keep verified idle progress until the
                # dated stop; the final permitted call is normal completion,
                # not exhaustion while another dispatch is still scheduled.
                return {'status':'schedule_complete'}
            if sum(e['kind']=='dispatch' and bool(e['symbols']) for e in state['events'])>=self.settings.max_quote_calls:
                return {'status':'budget_exhausted'}
            return {'status':'idle'}
        slot=self.next
        result=self.poller.sample(slot,fault_hook=fault_hook)
        if self.refused_call or getattr(self.client,'halt_reason',None):
            return dict(result,status='blocked',reason='provider_dispatch_gate_or_client_stopped')
        self.next=next_slot(self.poller.settings,after=max(slot.scheduled_at,self.clock()))
        return result

    def _provider_stop(self):
        value=None
        if self.provider_stop_path.exists():
            if self.provider_stop_path.is_symlink():raise ValueError('Invalid provider-stop evidence')
            value=json.loads(self.provider_stop_path.read_text())
        elif getattr(self,'manifest',None) is not None and self.manifest.exists():
            value=json.loads(self.manifest.read_text()).get('provider_stop')
        if value is not None:
            body=dict(value);sha=body.pop('receipt_sha256')
            if (sha!=digest(body) or body['contract']!='daily-hot-provider-stop-v1'
                    or body['collector_identity_sha256']!=digest(self.identity)
                    or body['status_code'] not in (401,403,429)
                    or timestamp(body['observed_at_utc'])>self.clock()):
                raise ValueError('Provider-stop identity differs')
            raise ValueError('Daily Hot provider stop is latched; review original evidence')
