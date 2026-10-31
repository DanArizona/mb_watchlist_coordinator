"""Daily Hot publication backend attached to an existing schema-v2 session.

The CLI is read-only. The trusted API connects verified source receipts and
identity admission to native publication; it does not launch a collector or
authenticate. The original bounded experiment is unchanged.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
from contextlib import closing
from functools import lru_cache
from threading import RLock
import time

from .controller_bootstrap import _proposal, strict_json
from .integrated_identity import IdentityGatedDelivery
from .nasdaq_recovery import regular_window
from .operating_plan import proposed_policy, validate_policy, SINGLE_PROFILE, MULTI_PROFILE
from .sampling_requests import digest, freeze, plain, timestamp, utc_text
from .sampling_service import owner_lock
from .recovery_workers import atomic_json, read_process_text

CONTRACT = 'daily-hot-publication-session-v1'
OWNER = 'nasdaq-shared-daily'


@lru_cache(maxsize=8)
def _preview_journal(path, day, profile):
    """Reuse only the native raw-value-checked membership parser, not a read.

    Each preview still opens a current read transaction and compares every
    header/member value. Its per-store immutable parse cache previously got
    discarded by every preview, reparsing all600-symbol historical revisions.
    Serialize access to that derived parser when monitor/owner threads overlap.
    """
    Store, Journal, _ = publication_types(profile)
    return RLock(), Journal(Store(path, session_date=day, schema_version=2))


def regular_path(value, *, exists=False):
    path = Path(value)
    if (not path.is_absolute() or path != path.resolve()
            or exists and (not path.is_file() or path.is_symlink())):
        raise ValueError('Explicit canonical absolute path required')
    return path


@dataclass(frozen=True)
class DailySettings:
    state_root: str
    journal_path: str
    opening_proposal: str
    focus_proposal: str
    policy_sha256: str
    policy_profile: str = SINGLE_PROFILE

    def preview(self):
        """Read published bytes/cadence; create no application state or requests.

        SQLite may create its normal WAL/SHM coordination files for a read.
        """
        from mb_market_data.polling_cadence import check_before_credentials
        from mb_market_data.daily_journal import DailyQuoteObservationStore as QuoteObservationStore
        from .sampling_journal import SamplingJournal
        root = regular_path(self.state_root)
        journal = regular_path(self.journal_path, exists=True)
        opening, h0 = _proposal(regular_path(self.opening_proposal, exists=True))
        focus, h1 = _proposal(regular_path(self.focus_proposal, exists=True))
        start, stop = regular_window(opening.session_date)
        policy = validate_policy(proposed_policy(self.policy_profile))
        if self.policy_sha256 != digest(policy):
            raise ValueError('Explicit proposed operating-policy hash differs')
        if (not root.name.startswith('daily_hot_') or not root.parent.is_dir()
                or root == journal.parent or root in journal.parents or journal.parent in root.parents
                or any(p.lower().startswith('quote_observation_journal') for p in root.parts)
                or journal.name != f'{opening.session_date}.sqlite3'
                or journal.parent.name != f'quote_observation_journal_v2_api_opening_{opening.session_date}'
                or any(root == p or root in p.parents for p in
                    (Path(self.opening_proposal), Path(self.focus_proposal)))
                or opening.revision != 0 or focus.revision != 1
                or opening.session_date != focus.session_date
                or opening.effective_at != start or focus.effective_at != start
                or not opening.uni_symbols or opening.uni_symbols != focus.uni_symbols
                or opening.focus_symbols or opening.hot_symbols or focus.hot_symbols
                or not 1 <= len(focus.focus_symbols) <= 40):
            raise ValueError('Daily session paths or opening/Focus binding differ')
        lock, bridge = _preview_journal(str(journal), opening.session_date,self.policy_profile)
        with lock:
            revisions = (bridge.revisions(opening_only=True) if self.policy_profile == MULTI_PROFILE
                         else bridge.revisions())
        if (len(revisions) < 2 or
                [r['content_sha256'] for r in revisions[:2]] !=
                [opening.content_sha256, focus.content_sha256]):
            raise ValueError('Published r0/r1 do not match the supplied proposals')
        check_before_credentials(journal, 'interleaved-v1')
        content = {'contract': CONTRACT, 'settings': asdict(self),
            'session_date': str(opening.session_date), 'policy': policy,
            'source_files': {'opening': h0, 'focus': h1},
            'published_anchor': [r['content_sha256'] for r in revisions[:2]],
            'start_at_utc': utc_text(start), 'stop_at_utc': utc_text(stop),
            'source_owner': OWNER, 'cadence_profile': 'interleaved-v1',
            'collector_included': False, 'live_launch_available': False,
            'unmanaged_channels': ['uni', 'focus', 'health']}
        return dict(content, binding_sha256=digest(content))


class DailyIdentityGate(IdentityGatedDelivery):
    """Reuse durable three-permit/one-symbol admission with a daily identity.

    The experiment's original 720-second constructor remains sealed. Only the
    window/contract setup differs; reservation, unknown-outcome and admission
    replay are the accepted implementation.
    """
    def __init__(self, gate_path, *, delivery, catalog, start_at, stop_at,
                 clock, monotonic=time.monotonic, stop_requested=lambda: False):
        self.gate_path, self.delivery, self.catalog = Path(gate_path), delivery, catalog
        self.path = delivery.path
        self.live, self.recovery, self.requests = delivery.live, delivery.recovery, delivery.requests
        self.producer_id = delivery.producer_id
        self.start, self.stop = timestamp(start_at), timestamp(stop_at)
        self.clock, self.monotonic, self.stop_requested = clock, monotonic, stop_requested
        start, stop = regular_window(self.requests.session_date)
        if (self.start != start or self.stop != stop or delivery.producer_id != OWNER
                or self.gate_path.resolve() in {p.resolve() for p in
                    (delivery.path, self.requests.path, self.live.path, self.recovery.path)}
                or self.requests.admission is None
                or self.requests.admission.catalog_id != catalog.catalog_id
                or self.requests.admission.catalog_symbols != frozenset(catalog.symbols)):
            raise ValueError('Daily identity gate requires the bound regular session and catalog')
        self.identity = freeze({'contract': 'daily-nasdaq-identity-gate-v1',
            'gate_path': str(self.gate_path.resolve()), 'delivery': plain(delivery.identity),
            'catalog_id': catalog.catalog_id, 'catalog_sha256': digest(catalog.public),
            'start_at_utc': utc_text(self.start), 'stop_at_utc': utc_text(self.stop),
            'maximum_identity_quote_permits': 3, 'maximum_distinct_authorized_symbols': 1,
            'request_timeout_seconds': 3, 'selection': 'first_exact_broker_confirmation',
            'normal_admission_required': True, 'production_access': True})

    def _catalog_sha256(self,catalog):
        return catalog.verified_public_sha256()


class DailySession:
    """One explicit journal owner; missing ledgers are never initialized on reopen.

    A future authenticated controller calls this API only after its approval,
    dependency and credential checks. No live CLI or implicit activation exists.
    Closing releases this object's lease; it never stops another process or
    withdraws persisted source demand.
    """
    def __init__(self, settings, catalog, *, clock=None):
        self.settings, self.catalog = settings, catalog
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.binding = settings.preview()
        self.root, self.journal_path = Path(settings.state_root), Path(settings.journal_path)
        self.claim_path = self.journal_path.with_suffix('.daily-hot-session.json')
        self.lock_path = self.journal_path.with_suffix('.daily-hot-owner.lock')
        self.lease, self.closed, self.attached = None, False, False
        self._time()
        self.catalog.validate()
        from mb_market_data.watchlist_polling import ET
        if any(timestamp(source['retrieved_at_utc']).astimezone(ET).date().isoformat()
                != self.binding['session_date'] or timestamp(source['retrieved_at_utc']) > self.clock()
                for source in catalog.public['sources'].values()):
            raise ValueError('Daily catalog must have been acquired on the target ET date')
        self.claim = {'contract': CONTRACT, 'binding_sha256': self.binding['binding_sha256'],
            'state_root': str(self.root), 'catalog_id': catalog.catalog_id,
            'catalog_sha256': digest(catalog.public)}

    def _time(self):
        now = self.clock()
        if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
            raise ValueError('Daily clock must be timezone-aware')
        start, stop = timestamp(self.binding['start_at_utc']), timestamp(self.binding['stop_at_utc'])
        if now.date() != start.astimezone(now.tzinfo).date() or now >= stop:
            raise ValueError('Daily session has ended or belongs to another date')
        return now

    def attach(self, *, create=False, publication_approved=False, fault_hook=None):
        if publication_approved is not True:
            raise ValueError('Explicit publication authorization is required by the trusted API')
        if self.closed or self.attached:
            raise ValueError('A fresh unclosed session object is required')
        self._time()
        if self.settings.preview() != self.binding:
            raise ValueError('Daily inputs changed')
        lease = owner_lock(self.lock_path); lease.__enter__(); self.lease = lease
        try:
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
            QuoteObservationStore, SamplingJournal, SamplingPublicationService = publication_types(self.settings.policy_profile)
            self._time()
            if self.settings.preview() != self.binding:
                raise ValueError('Daily inputs changed while acquiring ownership')
            opening, _ = _proposal(self.settings.opening_proposal)
            focus, _ = _proposal(self.settings.focus_proposal)
            self.store = QuoteObservationStore(self.journal_path,
                session_date=opening.session_date, schema_version=2)
            self.journal = SamplingJournal(self.store)
            if create:
                if self.root.exists() or self.claim_path.exists() or len(self.journal.revisions()) != 2:
                    raise ValueError('Existing daily state or journal requires original-ledger recovery')
                with closing(sqlite3.connect(self.journal_path.as_uri()+'?mode=ro', uri=True)) as connection:
                    if any(strict_json(row[0]).get('watchlist_kind') == 'hot' for row in
                            connection.execute('SELECT configuration_json FROM poll_run')):
                        raise ValueError('An unbound Hot run already exists in this journal')
                # Reserve one immutable state location per journal before creating ledgers.
                # A partial initialization remains claimed and cannot reset its budgets.
                with self.claim_path.open('x', encoding='utf-8') as out:
                    json.dump(self.claim, out, sort_keys=True); out.write('\n')
                    out.flush(); os.fsync(out.fileno())
                self.root.mkdir(exist_ok=False)
                atomic_json(self.root/'session.json', {'claim': self.claim, 'binding': self.binding,
                    'status': 'INITIALIZING'})
            elif (strict_json(self.claim_path.read_text()) != self.claim or
                    strict_json((self.root/'session.json').read_text()) !=
                    {'claim': self.claim, 'binding': self.binding, 'status': 'ATTACHED'}):
                raise ValueError('Original complete daily session binding is required')
            self.catalog.validate()
            policy = self.binding['policy']
            self.requests = SamplingRequestStore(self.root/'requests.sqlite3',
                session_date=opening.session_date, baseline=SamplingMembership(
                    frozenset(focus.uni_symbols), frozenset(focus.focus_symbols), frozenset()),
                policy=SamplingPolicy(policy['operator_actor_id'], **policy['stabilization']),
                admission=AdmissionPolicy(self.catalog.catalog_id, frozenset(self.catalog.symbols),
                    frozenset({OWNER}), policy['limits']['maximum_distinct_added_symbols_per_session'],
                    'session'), clock=self.clock)
            self.service = SamplingPublicationService(self.root/'publication.sqlite3',
                request_store=self.requests, journal=self.journal,
                settings=PublicationSettings('daily-hot-publication', 1, .5,
                    timestamp(self.binding['stop_at_utc'])), clock=self.clock)
            self.live = NasdaqSamplingProducer(self.root/'live.sqlite3', request_store=self.requests,
                settings=HaltProducerSettings('nasdaq-observations-daily', ('LUDP', 'M'),
                    'regular_close', False, False, 'external'), clock=self.clock)
            query = RecoveryQuery(opening.session_date, opening.session_date)
            self.recovery = NasdaqRecoveryReceipts(self.root/'recovery.sqlite3', request_store=self.requests,
                settings=RecoverySettings(opening.session_date, 'late_start', (query,), False), clock=self.clock)
            self.delivery = NasdaqRecoveryDelivery(self.root/'delivery.sqlite3', live_producer=self.live,
                recovery_receipts=self.recovery, producer_id=OWNER, clock=self.clock)
            self.gate = identity_gate_type(self.settings)(self.root/'identity.sqlite3', delivery=self.delivery,
                catalog=self.catalog, start_at=self.binding['start_at_utc'],
                stop_at=self.binding['stop_at_utc'], clock=self.clock)
            if create:
                self.requests.initialize(); self.service.initialize(); self.live.initialize()
                self.recovery.initialize(create=True); self.delivery.initialize(create=True)
                self.gate.initialize(create=True)
                if fault_hook: fault_hook('after_ledgers_initialized')
                atomic_json(self.root/'session.json', {'claim': self.claim, 'binding': self.binding,
                    'status': 'ATTACHED'})
            else:
                required = ('requests.sqlite3', 'publication.sqlite3', 'live.sqlite3',
                    'recovery.sqlite3', 'delivery.sqlite3', 'identity.sqlite3', 'status.json')
                if any(not regular_path(self.root/name, exists=True).is_file() for name in required):
                    raise ValueError('Restore every original daily ledger before reopening')
            self.attached = True
            self.validate()
            return self.status()
        except BaseException:
            self.close(); raise

    def validate(self, *, with_state=False):
        if not self.attached or self.closed or self.lease is None:
            raise ValueError('Attached owned daily session required')
        if (self.settings.preview() != self.binding or
                strict_json(self.claim_path.read_text()) != self.claim or
                strict_json((self.root/'session.json').read_text()) !=
                {'claim': self.claim, 'binding': self.binding, 'status': 'ATTACHED'}):
            raise ValueError('Daily attachment binding changed')
        self.catalog.validate()
        if self.catalog.catalog_id != self.claim['catalog_id'] or self.catalog.verified_public_sha256() != self.claim['catalog_sha256']:
            raise ValueError('Daily catalog changed')
        if (self.root/'status.json').exists():
            previous = strict_json(read_process_text(self.root/'status.json'))
            content = dict(previous); sha = content.pop('content_sha256')
            if (sha != digest(content) or previous['binding_sha256'] != self.binding['binding_sha256']
                    or self.clock() < timestamp(previous['observed_at_utc'])):
                raise ValueError('Daily status binding or clock differs')
        gate, publication = self.gate.snapshot(), self.service.snapshot()
        return (publication, gate) if with_state else True

    def status(self):
        self.validate()
        pub, gate = plain(self.service.snapshot()), plain(self.gate.snapshot())
        revision = pub['journal'][-1]
        effective = [r for r in pub['journal'] if timestamp(r['proposal']['effective_at_utc']) <= self.clock()]
        content = {'contract': CONTRACT, 'binding_sha256': self.binding['binding_sha256'],
            'observed_at_utc': utc_text(self.clock()),
            'state': ('IDENTITY_PROVIDER_STOP_REQUIRED' if gate['identity_gate']['provider_stop_required']
                else 'ATTACHED_NOT_COLLECTING'),
            'latest_published_revision': revision['proposal']['revision'],
            'latest_published_effective_at_utc': revision['proposal']['effective_at_utc'],
            'effective_revision': effective[-1]['proposal']['revision'] if effective else None,
            'publication_pending': pub['pending'] is not None or bool(pub['unacknowledged']),
            'identity_quote_permits': gate['identity_gate']['quote_permits'],
            'selected_symbol': gate['identity_gate']['selected_symbol'],
            'authorized_symbols': gate['identity_gate'].get('authorized_symbols',
                [gate['identity_gate']['selected_symbol']] if gate['identity_gate']['selected_symbol'] else []),
            'pending_source_commands': len(gate['identity_gate']['all_outbox_pending']),
            'source_warnings': self.binding['policy']['source_warnings'],
            'collector_running': False, 'live_launch_available': False,
            'unmanaged_channels': self.binding['unmanaged_channels']}
        result = dict(content, content_sha256=digest(content))
        atomic_json(self.root/'status.json', result)
        return result

    def cycle(self, *, client, current_snapshot=None, historical_snapshot=None,
              identity_fault_hook=None, service_fault_hook=None):
        self.validate()
        now = self._time()
        if now < timestamp(self.binding['start_at_utc']):
            return self.status()
        if current_snapshot is not None:
            if current_snapshot.retrieval_mode != 'CURRENT':
                raise ValueError('Explicit CURRENT source capture required')
            self.live.record_snapshot(current_snapshot)
        if historical_snapshot is not None:
            self.recovery.record(self.recovery.settings.queries[0], historical_snapshot)
        self.gate.reconcile()
        self.gate.deliver_pending(client=client, fault_hook=identity_fault_hook)
        self.service.cycle(fault_hook=service_fault_hook)
        return self.status()

    def close(self):
        self.closed = True
        if self.lease is not None:
            lease, self.lease = self.lease, None
            lease.__exit__(None, None, None)


def identity_gate_type(settings):
    if settings.policy_profile == MULTI_PROFILE:
        from .daily_multi_identity import MultiIdentityGate
        return MultiIdentityGate
    if settings.policy_profile != SINGLE_PROFILE:
        raise ValueError('Unknown daily identity profile')
    return DailyIdentityGate


def publication_types(profile):
    if profile == MULTI_PROFILE:
        from .daily_multi_publication import MultiMembershipStore, MultiSamplingJournal, MultiPublicationService
        return MultiMembershipStore, MultiSamplingJournal, MultiPublicationService
    if profile != SINGLE_PROFILE:raise ValueError('Unknown daily publication profile')
    from mb_market_data.daily_journal import DailyQuoteObservationStore
    from .sampling_journal import SamplingJournal
    from .sampling_service import SamplingPublicationService
    return DailyQuoteObservationStore, SamplingJournal, SamplingPublicationService


def main(argv=None):
    parser = argparse.ArgumentParser(description='Read-only daily Hot session-attachment preview')
    parser.add_argument('opening', type=Path)
    parser.add_argument('focus', type=Path)
    parser.add_argument('--journal', type=Path, required=True)
    parser.add_argument('--state-root', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        settings = DailySettings(str(args.state_root), str(args.journal), str(args.opening),
            str(args.focus), digest(proposed_policy()))
        print(json.dumps(settings.preview(), indent=2))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        print('Daily session preview refused:', type(error).__name__)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
