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
                or type(self.max_symbols) is not int or self.max_symbols != 1
                or self.max_symbols != policy['limits']['maximum_active_hot_symbols']
                or self.journal_path != binding['settings']['journal_path']
                or self.publication_binding['journal']['path'] != self.journal_path):
            raise ValueError('Explicit daily collector window, one-symbol limit and call ceiling required')
        return {'contract':'daily-hot-collector-v1', 'journal_path':self.journal_path,
            'publication_binding':plain(self.publication_binding),
            'daily_binding':binding, 'daily_claim':plain(self.daily_claim),
            'start_at_utc':start.isoformat(), 'stop_at_utc':stop.isoformat(),
            'max_quote_calls':self.max_quote_calls, 'max_symbols':self.max_symbols,
            'seconds':list(RESERVED_HOT_SECONDS), 'batch_size':400, 'fields':'all',
            'max_dispatch_lateness_seconds':.75, 'no_past_slot_catchup':True}


class DailyHotCollector(HotRecoveryCollector):
    def __init__(self, settings, *, publication_session, client_factory, clock=None,
                 activation_approved=False):
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
        self.poller = DailyHotPoller(self.session.store,
            settings=AcquisitionSettings(SamplingChannel.HOT, RESERVED_HOT_SECONDS,
                PollWindow(timestamp(settings.start_at_utc),timestamp(settings.stop_at_utc)),
                400, 'all', 'daily-native-hot-v1', .75, .05), client=self,
            daily_binding=settings.daily_binding, daily_claim=settings.daily_claim,
            publication_binding=settings.publication_binding,
            validate_publication=self.validate_publication, clock=self.clock,
            activation_approved=activation_approved)
        self.manifest = self.poller.path.with_suffix('.daily-collector.json')
        self.next, self.refused_call = None, False

    def prepare(self,*,create=False):
        if self.collector_lease is not None:raise ValueError('Collector is already prepared')
        self._provider_stop()
        lease=owner_lock(Path(self.settings.journal_path).with_suffix('.daily-hot-collector.lock'))
        lease.__enter__();self.collector_lease=lease
        try:return super().prepare(create=create)
        except BaseException:
            self.close();raise

    def close(self):
        try:super().close()
        finally:
            if self.collector_lease is not None:
                lease,self.collector_lease=self.collector_lease,None
                lease.__exit__(None,None,None)

    def validate_publication(self, dispatch):
        self.session.validate()
        publication = plain(self.session.service.snapshot())
        gate = plain(self.session.gate.snapshot())['identity_gate']
        if gate['provider_stop_required']:
            raise ValueError('Identity provider stop prevents new collection')
        if dispatch is not None:
            revision = next((r for r in publication['journal']
                if r['proposal']['revision'] == dispatch['revision']), None)
            if (revision is None or
                    list(revision['proposal']['hot_symbols']) != dispatch['symbols'] or
                    dispatch['symbols'] != [gate['selected_symbol']]):
                raise ValueError('Native dispatch does not match verified selected membership')
        return True

    def _check(self):
        if self.collector_lease is None:raise ValueError('Owned prepared daily collector required')
        self._provider_stop()
        super()._check()
        self.validate_publication(None)

    def quotes(self, symbols, *, fields):
        # This executes after the native durable dispatch, inside its owner lock.
        self.validate_publication(self.poller._read()['pending']['dispatch'])
        response=super().quotes(symbols, fields=fields)
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
