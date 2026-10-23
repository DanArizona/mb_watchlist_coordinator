"""Experimental worker adapter for the native schema-v2 Hot collector.

No authentication or provider discovery lives here. An explicit caller supplies
a bounded-timeout client factory implementing the Schwab quotes interface.
Saved assembled responses are recovered before that factory can be invoked.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time

from .recovery_workers import HOT_SECONDS, atomic_json, next_future_slot
from .sampling_requests import canonical, digest, plain, timestamp
from .sampling_service import owner_lock


@dataclass(frozen=True)
class HotCollectorSettings:
    journal_path: str
    publication_binding: dict
    start_at_utc: str
    stop_at_utc: str
    max_quote_calls: int = 30
    max_symbols: int = 40

    def payload(self):
        from mb_market_data.watchlist_polling import ET
        start, stop = timestamp(self.start_at_utc), timestamp(self.stop_at_utc)
        path = Path(self.journal_path).resolve()
        binding = plain(self.publication_binding)
        if (any(p.lower().startswith('quote_observation_journal') for p in path.parts)
                or not path.is_file() or binding['journal'] != {
                    'path': str(path), 'schema_version': 2,
                    'session_date': start.astimezone(ET).date().isoformat()}):
            raise ValueError('Explicit experimental journal/publication binding required')
        if (start >= stop or (stop-start).total_seconds() > 900
                or start.astimezone(ET).date() != stop.astimezone(ET).date()
                or start.astimezone(ET).hour < 9
                or start.astimezone(ET).hour == 9 and start.astimezone(ET).minute < 30
                or stop.astimezone(ET) > stop.astimezone(ET).replace(hour=16, minute=0, second=0, microsecond=0)):
            raise ValueError('Explicit bounded regular-session acquisition window required')
        if (type(self.max_quote_calls) is not int or not 1 <= self.max_quote_calls <= 720
                or type(self.max_symbols) is not int or not 1 <= self.max_symbols <= 400):
            raise ValueError('Explicit bounded call/roster limits required')
        return {'contract': 'experimental-native-hot-recovery-v1',
            'journal_path': str(path), 'publication_binding': binding,
            'start_at_utc': start.isoformat(), 'stop_at_utc': stop.isoformat(),
            'max_quote_calls': self.max_quote_calls, 'max_symbols': self.max_symbols,
            'seconds': list(HOT_SECONDS), 'batch_size': 400, 'fields': 'all',
            'max_dispatch_lateness_seconds': .75, 'no_past_slot_catchup': True}


def validate_job(job_path, binding):
    path = Path(job_path).resolve()
    job = json.loads(path.read_text(encoding='utf-8'))
    content = dict(job); sha = content.pop('content_sha256')
    if (digest(content) != sha or canonical(job['identity']['binding']) != canonical(binding)
            or job['identity']['contract'] != 'experimental-recovery-worker-v1'
            or job['identity']['role'] != 'experimental_hot'
            or type(job['generation']) is not int or not 1 <= job['generation'] <= 3
            or job['identity']['experimental_hot_seconds'] != list(HOT_SECONDS)
            or job['experimental_hot_seconds'] != list(HOT_SECONDS)
            or job['no_past_slot_catchup'] is not True
            or job['first_eligible_slot_utc'] != next_future_slot(timestamp(job['resume_after_utc'])).isoformat()
            or path != Path(job['job_path'])
            or path.name != job['token']+'.job.json'
            or Path(job['registry_path']) != path.parent/'worker.json'
            or Path(job['lease_path']) != path.parent/'worker.lock'
            or Path(job['heartbeat_path']) != path.parent/(job['token']+'.heartbeat.json')
            or Path(job['stop_path']) != path.parent/(job['token']+'.stop')
            or Path(job['registry_path']).read_text(encoding='utf-8') != canonical(job)):
        raise ValueError('Experimental collector job identity/fence differs')
    return job


class HotRecoveryCollector:
    def __init__(self, settings, *, client_factory, clock=None):
        from mb_market_data.quote_observation_store import QuoteObservationStore
        from mb_market_data.sampling_acquisition import AcquisitionSettings, IsolatedSamplingPoller
        from mb_market_data.sampling_membership import SamplingChannel
        from mb_market_data.watchlist_polling import PollWindow, ET
        self.settings, self.identity = settings, settings.payload()
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        if not callable(client_factory):
            raise ValueError('An explicit prepared-client factory is required')
        self.client_factory, self.client = client_factory, None
        self.job_path = self.job = None
        start, stop = timestamp(settings.start_at_utc), timestamp(settings.stop_at_utc)
        store = QuoteObservationStore(settings.journal_path,
            session_date=start.astimezone(ET).date(), schema_version=2)
        self.poller = IsolatedSamplingPoller(store, settings=AcquisitionSettings(
            SamplingChannel.HOT, HOT_SECONDS, PollWindow(start, stop), 400, 'all',
            'experimental-native-hot-recovery-v1', .75, .05), client=self, clock=self.clock)
        self.manifest = self.poller.path.with_suffix('.recovery.json')
        self.next = None
        self.refused_call = False

    def prepare(self, *, create=False):
        from mb_market_data.sampling_acquisition import next_slot
        content = {'settings': self.identity, 'poller_identity': plain(self.poller.identity)}
        expected = dict(content, content_sha256=digest(content))
        if self.manifest.exists():
            if json.loads(self.manifest.read_text(encoding='utf-8')) != expected or not self.poller.path.is_file():
                raise ValueError('Restore original collector manifest and acquisition evidence')
            self.poller.snapshot()  # Validate original evidence before adding run provenance.
        else:
            if not create or self.poller.path.exists():
                raise ValueError('Missing collector manifest; no automatic adoption/reset')
        self.poller.initialize()
        if not self.manifest.exists():
            atomic_json(self.manifest, expected)
        recovered = self.poller.recover()
        self.next = next_slot(self.poller.settings, after=self.clock())
        return recovered

    def _check(self):
        if self.settings.payload() != self.identity:
            raise ValueError('Collector configuration changed')
        content = {'settings': self.identity, 'poller_identity': plain(self.poller.identity)}
        if json.loads(self.manifest.read_text(encoding='utf-8')) != dict(content, content_sha256=digest(content)):
            raise ValueError('Collector manifest changed')
        if self.job_path:
            current = validate_job(self.job_path, self.settings.publication_binding)
            if current != self.job or Path(current['stop_path']).exists():
                raise ValueError('Collector generation stopped or fenced')

    def quotes(self, symbols, *, fields):
        # Called inside the native poller's lock after its durable dispatch.
        self._check()
        state = self.poller._read()
        consumed = sum(1 for e in state['events'] if e['kind'] == 'dispatch' and e['symbols'])
        if (consumed > self.settings.max_quote_calls or len(symbols) > self.settings.max_symbols
                or list(symbols) != state['pending']['dispatch']['symbols'] or fields != 'all'
                or not timestamp(self.settings.start_at_utc) <= self.clock() < timestamp(self.settings.stop_at_utc)
                or (self.clock()-timestamp(state['pending']['dispatch']['scheduled_at_utc'])).total_seconds() > .75):
            self.refused_call = True
            raise ValueError('Collector call budget, roster, slot or window gate refused')
        if self.client is None:
            self.client = self.client_factory()
        return self.client.quotes(symbols, fields=fields)

    def tick(self, *, fault_hook=None):
        from mb_market_data.sampling_acquisition import next_slot
        self._check()
        if self.clock() >= timestamp(self.settings.stop_at_utc):
            return {'status': 'window_ended'}
        state = self.poller.snapshot()
        if sum(1 for e in state['events'] if e['kind'] == 'dispatch' and e['symbols']) >= self.settings.max_quote_calls:
            return {'status': 'budget_exhausted'}
        if self.next is None or self.clock() < self.next.scheduled_at:
            # The snapshot above completed validation; this is not a quote heartbeat.
            return {'status': 'idle'}
        slot = self.next
        result = self.poller.sample(slot, fault_hook=fault_hook)
        if self.refused_call:
            return dict(result, status='blocked', reason='provider_dispatch_gate_refused')
        self.next = next_slot(self.poller.settings, after=max(slot.scheduled_at, self.clock()))
        return result

    def close(self):
        if self.client is not None:
            close = getattr(self.client, 'close', None)
            if close:
                close()


def run_worker(job_path, settings, *, client_factory, clock=None, stop_requested=lambda: False,
               fault_hook=None, sleep=time.sleep, monotonic=time.monotonic):
    """Hold the fenced role lease throughout recovery and actual acquisition.

    No passwords, SDK imports, account discovery or implicit authorization. The
    client factory is lazy and must enforce its own bounded provider timeout.
    """
    job = validate_job(job_path, settings.publication_binding)
    with owner_lock(Path(job['lease_path'])):
        job = validate_job(job_path, settings.publication_binding)
        collector = HotRecoveryCollector(settings, client_factory=client_factory, clock=clock)
        collector.job_path, collector.job = job_path, job
        try:
            if stop_requested() or Path(job['stop_path']).exists():
                return {'status': 'stopped'}
            collector._check()  # Missing evidence blocks before recovery or client creation.
            recovery = collector.prepare()
            from mb_market_data.sampling_acquisition import next_slot
            collector.next = next_slot(collector.poller.settings,
                after=max(collector.clock(), timestamp(job['resume_after_utc'])))
            deadline = monotonic()+min(900, max(0, (timestamp(settings.stop_at_utc)-collector.clock()).total_seconds()))
            while not stop_requested() and not Path(job['stop_path']).exists():
                if monotonic() >= deadline:
                    return {'status': 'bounded_deadline_ended'}
                result = collector.tick(fault_hook=fault_hook)
                atomic_json(Path(job['heartbeat_path']), {'token': job['token'],
                    'generation': job['generation'], 'identity_sha256': digest(job['identity']),
                    'completed_at_utc': datetime.now(timezone.utc).isoformat(), 'pid': os.getpid(),
                    'progress': 'completed', 'collector_status': result['status'],
                    'slot_id': result.get('slot_id'), 'recovery': recovery,
                    'qualification': 'native_collector_offline_integration_live_provider_pending'})
                if result['status'] in ('window_ended', 'budget_exhausted', 'blocked'):
                    return result
                remaining = (collector.next.scheduled_at-collector.clock()).total_seconds() if collector.next else .25
                sleep(min(.25, max(.01, remaining)))
            return {'status': 'stopped'}
        finally:
            collector.close()
