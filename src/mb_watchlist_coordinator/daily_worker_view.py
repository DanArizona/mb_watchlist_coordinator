"""Read the original daily publication ledgers without taking their owner lease."""
from datetime import datetime, timezone
from pathlib import Path
import time

from .daily_session import DailySettings, DailyIdentityGate, CONTRACT, OWNER, regular_path
from .controller_bootstrap import strict_json
from .integrated_catalog import DirectoryCatalog
from .sampling_requests import digest, plain, timestamp
from .sampling_service import ServiceBusy
from .recovery_workers import read_process_text


class _ReadPublication:
    def __init__(self, service):
        self._service, self.identity = service, service.identity

    def snapshot(self):
        deadline = time.monotonic()+.2
        while True:
            try:
                return self._service.snapshot()
            except ServiceBusy:
                if time.monotonic() >= deadline: raise
                time.sleep(.005)


class DailyPublicationReader:
    def __init__(self, settings, catalog_path, *, binding, claim, publication_binding,
                 fence, clock=None):
        from mb_market_data.daily_journal import DailyQuoteObservationStore as QuoteObservationStore
        from .sampling_journal import SamplingJournal
        from .sampling_projection import SamplingMembership
        from .sampling_policy import SamplingPolicy
        from .daily_admission import DailyAdmissionPolicy as AdmissionPolicy
        from .sampling_request_store import SamplingRequestStore
        from .sampling_service import SamplingPublicationService, PublicationSettings
        from .nasdaq_sampling import NasdaqSamplingProducer, HaltProducerSettings
        from .nasdaq_recovery import NasdaqRecoveryReceipts, RecoverySettings, RecoveryQuery
        from .nasdaq_recovery_delivery import NasdaqRecoveryDelivery
        from .controller_bootstrap import _proposal
        self.settings, self.binding, self.claim = settings, plain(binding), plain(claim)
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        if not callable(fence): raise ValueError('Explicit worker ownership fence required')
        self.fence, self.root = fence, Path(settings.state_root)
        self.catalog = DirectoryCatalog.load(regular_path(catalog_path, exists=False))
        self.claim_path = Path(settings.journal_path).with_suffix('.daily-hot-session.json')
        self._binding()
        focus, _ = _proposal(settings.focus_proposal)
        policy = self.binding['policy']
        # These constructors only describe existing ledgers. No initializer,
        # publication cycle, source command, or admission write is available here.
        self.store = QuoteObservationStore(settings.journal_path,
            session_date=focus.session_date, schema_version=2)
        self.requests = SamplingRequestStore(self.root/'requests.sqlite3',
            session_date=focus.session_date, baseline=SamplingMembership(
                frozenset(focus.uni_symbols), frozenset(focus.focus_symbols), frozenset()),
            policy=SamplingPolicy(policy['operator_actor_id'], **policy['stabilization']),
            admission=AdmissionPolicy(self.catalog.catalog_id, frozenset(self.catalog.symbols),
                frozenset({OWNER}), 1, 'session'), clock=self.clock)
        self.service = _ReadPublication(SamplingPublicationService(self.root/'publication.sqlite3',
            request_store=self.requests, journal=SamplingJournal(self.store),
            settings=PublicationSettings('daily-hot-publication', 1, .5,
                timestamp(self.binding['stop_at_utc'])), clock=self.clock))
        live = NasdaqSamplingProducer(self.root/'live.sqlite3', request_store=self.requests,
            settings=HaltProducerSettings('nasdaq-observations-daily', ('LUDP', 'M'),
                'regular_close', False, False, 'external'), clock=self.clock)
        recovery = NasdaqRecoveryReceipts(self.root/'recovery.sqlite3', request_store=self.requests,
            settings=RecoverySettings(focus.session_date, 'late_start',
                (RecoveryQuery(focus.session_date, focus.session_date),), False), clock=self.clock)
        delivery = NasdaqRecoveryDelivery(self.root/'delivery.sqlite3', live_producer=live,
            recovery_receipts=recovery, producer_id=OWNER, clock=self.clock)
        self.gate = DailyIdentityGate(self.root/'identity.sqlite3', delivery=delivery,
            catalog=self.catalog, start_at=self.binding['start_at_utc'],
            stop_at=self.binding['stop_at_utc'], clock=self.clock)
        if plain(self.service.identity) != plain(publication_binding):
            raise ValueError('Worker publication identity differs')
        self.validate()

    def _binding(self):
        self.fence()
        if self.settings.preview() != self.binding:
            raise ValueError('Worker daily inputs changed')
        expected = {'claim': self.claim, 'binding': self.binding, 'status': 'ATTACHED'}
        for path, value in ((self.claim_path, self.claim), (self.root/'session.json', expected)):
            regular_path(path, exists=True)
            if strict_json(path.read_text()) != value:
                raise ValueError('Original complete daily publication binding required')
        self.catalog.validate()
        if (self.claim != {'contract': CONTRACT, 'binding_sha256': self.binding['binding_sha256'],
                'state_root': str(self.root), 'catalog_id': self.catalog.catalog_id,
                'catalog_sha256': self.catalog.verified_public_sha256()}):
            raise ValueError('Worker catalog binding differs')
        for name in ('requests.sqlite3', 'publication.sqlite3', 'live.sqlite3',
                     'recovery.sqlite3', 'delivery.sqlite3', 'identity.sqlite3', 'status.json'):
            regular_path(self.root/name, exists=True)
        previous = strict_json(read_process_text(self.root/'status.json'))
        content = dict(previous); sha = content.pop('content_sha256')
        if (sha != digest(content) or previous['binding_sha256'] != self.binding['binding_sha256']
                or self.clock() < timestamp(previous['observed_at_utc'])):
            raise ValueError('Worker status binding or clock differs')

    def validate(self, *, with_state=False):
        self._binding()
        gate, publication = self.gate.snapshot(), self.service.snapshot()
        self.fence()
        return (publication, gate) if with_state else True
