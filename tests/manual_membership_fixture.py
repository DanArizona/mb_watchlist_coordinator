"""Isolated manual/Nasdaq request fixture; no credentials, sockets or processes."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from mb_market_data.quote_observation_store import QuoteObservationStore
from mb_market_data.sampling_membership import SamplingHierarchyRevision
from mb_watchlist_coordinator.manual_membership import ManualMembershipControls
from mb_watchlist_coordinator.models import IntentType, ProducerIntent
from mb_watchlist_coordinator.sampling_admission import AdmissionPolicy
from mb_watchlist_coordinator.sampling_journal import SamplingJournal
from mb_watchlist_coordinator.sampling_policy import SamplingPolicy
from mb_watchlist_coordinator.sampling_projection import SamplingMembership
from mb_watchlist_coordinator.sampling_request_store import SamplingRequestStore
from mb_watchlist_coordinator.sampling_service import PublicationSettings, SamplingPublicationService


class ManualScene:
    def __init__(self, root, *, actor='manual:masterbot', privileged=False, grace=60, residence=120,
                 allowed_sources=None, clock=None):
        self.root = Path(root); self.root.mkdir(parents=True, exist_ok=False)
        self.now = (datetime.now(ZoneInfo('America/New_York'))+timedelta(days=1)).replace(
            hour=10, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
        self.start = self.now
        self.clock = clock or (lambda: self.now)
        self.day = self.now.astimezone(ZoneInfo('America/New_York')).date()
        self.actor = actor
        self.baseline = SamplingMembership(frozenset({'AAPL','MSFT','SPY'}), frozenset({'SPY'}), frozenset())
        self.policy = SamplingPolicy('operator:masterbot', grace, residence, 'immediate_cap')
        self.admission = AdmissionPolicy('synthetic-manual-catalog', self.baseline.uni|{'OUT'},
            frozenset(allowed_sources if allowed_sources is not None else {'manual:masterbot','operator:masterbot','nasdaq-shared-daily'}),
            40, 'session')
        self.requests = SamplingRequestStore(self.root/'requests.sqlite3', session_date=self.day,
            baseline=self.baseline, policy=self.policy, admission=self.admission, clock=self.clock)
        self.requests.initialize()
        self.store = QuoteObservationStore(self.root/'journal.sqlite3', session_date=self.day, schema_version=2)
        self.store.initialize()
        for revision, focus in ((0,()),(1,('SPY',))):
            self.store.record_membership_revision(SamplingHierarchyRevision(session_date=self.day,
                revision=revision, effective_at=self.now-timedelta(seconds=1),
                uni_symbols=tuple(sorted(self.baseline.uni)), focus_symbols=focus, hot_symbols=(),
                source='synthetic_manual_preview', metadata={'synthetic_only':True}))
        self.service = SamplingPublicationService(self.root/'publication.sqlite3', request_store=self.requests,
            journal=SamplingJournal(self.store), settings=PublicationSettings('synthetic-manual-publisher', .05, .25,
                self.now+timedelta(minutes=10)), clock=self.clock)
        self.service.initialize()
        self.controls = ManualMembershipControls(self.root/'manual.sqlite3', publication=self.service,
            actor_id=actor, allow_restrictions=privileged, clock=self.clock)
        self.controls.initialize()

    def reopen(self):
        self.controls = ManualMembershipControls(self.root/'manual.sqlite3', publication=self.service,
            actor_id=self.actor, allow_restrictions=self.controls.allow_restrictions, clock=self.clock)
        self.controls.initialize()
        return self.controls

    def advance(self, seconds):
        self.now += timedelta(seconds=seconds)

    def publish(self):
        result = self.service.cycle()
        self.advance(.3)
        return result

    def nasdaq(self, request_id='nasdaq-1', symbol='MSFT'):
        return self.requests.submit_request(ProducerIntent(request_id,'nasdaq-shared-daily', IntentType.ENSURE_PRESENT,
            frozenset({symbol}), self.clock(), expires_at=self.service.settings.publish_until,
            metadata={'sampling_channel':'hot','session_date':str(self.day)}), actor_id='nasdaq-shared-daily')

    def row(self, command_id):
        return next(r for r in self.controls.snapshot()['commands'] if r['command_id']==command_id)
