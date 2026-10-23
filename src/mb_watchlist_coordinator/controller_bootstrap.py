"""Authenticate before creating a fresh, explicitly isolated recovery session.

This prepares native state only. It starts no feed request, quote, worker or
supervision loop. The eventual bounded controller owns the returned session.
Callers must put blocking startup in an owned process with a hard deadline;
bootstrap_entry supplies that boundary for the offline process qualification.
"""
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re

from .authenticated_startup import AuthStartupSettings, SessionPassword, StartupError
from .authenticated_startup import prepare_authenticated_client
from .installed_startup_probe import inspect_dependencies
from .sampling_requests import canonical, digest, freeze, plain, timestamp, utc_text
from .recovery_workers import atomic_json

CONTRACT = 'authenticated-recovery-bootstrap-v1'
OWNER = 'nasdaq-shared-integrated'
EXPECTED_HELPERS = {
    '__init__.py': 'a4f32c299d9eac0a0c0fda4f8fc3ea6779364f6830d28c04ca92bde99b618bf7',
    'schwab_secure/__init__.py': '4598710eb0c749366a632a4f8282614f243dfcd9226afa31b032de161aaff712',
    'schwab_secure/client.py': '2bad76d4d86aad31e9186e8e7c87028c04f6ae629f0e741bc5d230f3a8c4e6ea',
    'schwab_secure/config.py': '7da559d38a29ce3cf771e1524d160ca41d4671eb25221abaf11342347b00b2fa',
    'schwab_secure/status.py': '6b264ac2ca99aaefc54b9da2b0a7cf7501a0702608000582e1e5861cfc21a141',
    'schwab_secure/reauthorize.py': 'd1faaf0547730dbe7d9949dc90747e2f14e371e028dba00bf095376141dba1d6',
    'secure_config/__init__.py': 'b234604319b99e0fa98e486ec30e8f120419688a8587af13270b76c1d18d0581',
    'secure_config/ecfg.py': '0bd6c3d2160876cb5d428723694b9c38ba63f64780a1782690d74e33e4f4da6e',
}
CODES = frozenset(('configuration_invalid', 'dependency_rejected', 'inputs_changed',
    'target_exists', 'bootstrap_window_ended', 'initialization_failed', 'bootstrap_pass',
    'bootstrap_deadline_ended', 'credential_deadline_ended', 'operator_interrupted'))


class BootstrapError(RuntimeError):
    def __init__(self, code):
        self.code = code if code in CODES else 'initialization_failed'
        super().__init__(self.code)


def strict_json(raw):
    def unique(pairs):
        out = {}
        for k, v in pairs:
            if k in out:
                raise ValueError('Duplicate JSON key')
            out[k] = v
        return out
    return json.loads(raw, object_pairs_hook=unique,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nonfinite JSON')))


def _proposal(path):
    from mb_market_data.sampling_membership import SamplingHierarchyRevision
    p = Path(path)
    if not p.is_absolute() or not p.is_file() or p.is_symlink() or p.stat().st_size > 2_000_000:
        raise ValueError('Explicit bounded proposal file required')
    raw = p.read_bytes()
    value = strict_json(raw.decode('utf-8-sig'))
    allowed = {'session_date', 'revision', 'effective_at', 'uni_symbols', 'focus_symbols',
        'hot_symbols', 'source', 'reason', 'metadata'}
    if not isinstance(value, dict) or set(value) - allowed or allowed - {'reason', 'metadata'} - set(value):
        raise ValueError('Strict proposal required')
    value['session_date'] = date.fromisoformat(value['session_date'])
    value['effective_at'] = timestamp(value['effective_at'])
    return SamplingHierarchyRevision(**value), hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class BootstrapSettings:
    experiment_root: str
    opening_proposal: str
    focus_proposal: str
    opening_content_sha256: str
    focus_content_sha256: str
    ecfg_path: str
    password_submitted_at_utc: str
    nonce: str
    dependency_sha256: str
    catalog_id: str
    catalog_symbols: tuple[str, ...]
    profile: str = 'ordinary'

    def plan(self):
        """Pure validation. Catalog eligibility is supplied by a trusted caller.

        Actual directory retrieval/broker identity qualification is a subsequent
        controller increment, not something inferred from this catalog ID.
        """
        from mb_market_data.watchlist_polling import ET
        from .sampling_admission import AdmissionPolicy
        try:
            root = Path(self.experiment_root)
            paths = [root, Path(self.opening_proposal), Path(self.focus_proposal), Path(self.ecfg_path)]
            if (any(not p.is_absolute() for p in paths)
                    or not root.name.startswith('integrated_hot_') or not root.parent.is_dir()
                    or root.absolute() != root.resolve()
                    or any(p.lower().startswith('quote_observation_journal') for p in root.parts)
                    or any(root == p or root in p.parents for p in paths[1:])
                    or self.profile not in ('ordinary', 'owned_worker_recovery')
                    or type(self.catalog_symbols) is not tuple
                    or not self.catalog_symbols
                    or not re.fullmatch('[0-9a-f]{32}', self.nonce)
                    or any(not re.fullmatch('[0-9a-f]{64}', h) for h in (
                        self.dependency_sha256, self.opening_content_sha256, self.focus_content_sha256))):
                raise ValueError()
            r0, h0 = _proposal(self.opening_proposal)
            r1, h1 = _proposal(self.focus_proposal)
            submitted = timestamp(self.password_submitted_at_utc)
            start = (submitted + timedelta(seconds=60)).replace(microsecond=0)
            if start < submitted + timedelta(seconds=60):
                start += timedelta(seconds=1)
            stop = start + timedelta(seconds=720)
            opening = datetime.combine(r0.session_date, datetime.min.time().replace(hour=9, minute=30), ET)
            close = opening.replace(hour=16, minute=0)
            if (r0.revision != 0 or r1.revision != 1 or r0.session_date != r1.session_date
                    or not r0.uni_symbols or r0.uni_symbols != r1.uni_symbols
                    or r0.focus_symbols or r0.hot_symbols or r1.hot_symbols
                    or not 1 <= len(r1.focus_symbols) <= 40
                    or r0.effective_at != opening or r1.effective_at != opening
                    or r0.content_sha256 != self.opening_content_sha256
                    or r1.content_sha256 != self.focus_content_sha256
                    or submitted.astimezone(ET).date() != r0.session_date
                    or start < opening or stop > close):
                raise ValueError()
            admission = AdmissionPolicy(self.catalog_id, frozenset(self.catalog_symbols),
                frozenset({OWNER}), 1, 'session')
            public = {'contract': CONTRACT, 'settings': asdict(self),
                'source_file_sha256': {'opening': h0, 'focus': h1},
                'session_date': r0.session_date.isoformat(), 'start_at_utc': utc_text(start),
                'stop_at_utc': utc_text(stop), 'admission': admission.payload(),
                'maximum_hot_quote_permits': 60, 'maximum_identity_quote_permits': 3,
                'catalog_scope': 'caller_supplied_identity_eligibility_not_live_source_qualification',
                'production_access': False}
            return BootstrapPlan(self, r0, r1, admission, freeze(public), digest(public))
        except Exception:
            raise BootstrapError('configuration_invalid') from None


@dataclass(frozen=True)
class BootstrapPlan:
    settings: BootstrapSettings
    opening: object
    focus: object
    admission: object
    public: object
    configuration_sha256: str

    def fresh(self, clock):
        root = Path(self.settings.experiment_root)
        if root.exists() or root.is_symlink():
            raise BootstrapError('target_exists')
        try:
            unchanged = self.settings.plan().configuration_sha256 == self.configuration_sha256
        except BootstrapError:
            unchanged = False
        if not unchanged:
            raise BootstrapError('inputs_changed')
        now = clock()
        if not timestamp(self.settings.password_submitted_at_utc) <= now < timestamp(self.public['start_at_utc']):
            raise BootstrapError('bootstrap_window_ended')


class BootstrapSession:
    """Own prepared client/manual RAM secret; no running processes or requests."""
    def __repr__(self):
        return '<BootstrapSession authenticated; secret redacted; not running>'

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.password.close()
        if self.collector.client is self.client:
            self.collector.close()
        else:
            self.client.close()


def bootstrap_fresh(plan, password, *, clock=None, inventory=None, secure_api=None, fault_hook=None):
    """Prepare native bindings after authentication, without feed/quote collection.

    The supplied credential API can perform normal SDK authentication/refresh.
    No feed transport is opened and no quote method is called here. A hard
    owned-process watchdog must surround this synchronous building block.
    """
    clock = clock or (lambda: datetime.now(timezone.utc))
    client = retained = None
    claimed = False
    stages = []
    root = Path(plan.settings.experiment_root)
    def stage(name):
        stages.append({'stage': name, 'observed_at_utc': utc_text(clock())})
        if fault_hook:
            fault_hook(name)
    def before_write():
        if not timestamp(plan.settings.password_submitted_at_utc) <= clock() < timestamp(plan.public['start_at_utc']):
            raise BootstrapError('bootstrap_window_ended')
        if plan.settings.plan().configuration_sha256 != plan.configuration_sha256:
            raise BootstrapError('inputs_changed')
    try:
        if not isinstance(password, bytearray) or not password:
            raise StartupError('credentials_unavailable')
        plan.fresh(clock)
        observed = (inventory or inspect_dependencies)(EXPECTED_HELPERS)
        if observed.get('qualified') is not True or digest(observed) != plan.settings.dependency_sha256:
            raise BootstrapError('dependency_rejected')
        auth = AuthStartupSettings(plan.settings.ecfg_path, plan.public['stop_at_utc'])
        client = prepare_authenticated_client(auth, password, clock=clock, secure_api=secure_api)
        stage('credentials_accepted')
        plan.fresh(clock)  # Recheck files, identity, deadline and target after blocked startup.
        try:
            root.mkdir(exist_ok=False)
        except FileExistsError:
            raise BootstrapError('target_exists') from None
        claimed = True
        receipt = {'contract': CONTRACT, 'status': 'INITIALIZING',
            'configuration': plain(plan.public), 'configuration_sha256': plan.configuration_sha256,
            'quote_dispatches_started': 0, 'feed_attempts_started': 0, 'stages': stages}
        atomic_json(root/'bootstrap.json', receipt)
        stage('root_claimed')
        from mb_market_data.quote_observation_store import QuoteObservationStore
        from mb_market_data.sampling_membership import SamplingHierarchyRevision
        from mb_market_data.sampling_acquisition import MARKER
        from .sampling_projection import SamplingMembership
        from .sampling_policy import SamplingPolicy
        from .sampling_request_store import SamplingRequestStore
        from .sampling_journal import SamplingJournal
        from .sampling_service import SamplingPublicationService, PublicationSettings
        from .nasdaq_sampling import NasdaqSamplingProducer, HaltProducerSettings
        from .nasdaq_recovery import NasdaqRecoveryReceipts, RecoverySettings, RecoveryQuery
        from .nasdaq_recovery_delivery import NasdaqRecoveryDelivery
        from .nasdaq_feed_recovery import FeedRecoveryTransport, FeedLimits
        from .hot_recovery_collector import HotCollectorSettings, HotRecoveryCollector
        before_write()
        store = QuoteObservationStore(root/'quotes.sqlite3', session_date=plan.opening.session_date, schema_version=2)
        store.initialize()
        anchor = SamplingHierarchyRevision(session_date=plan.opening.session_date, revision=0,
            effective_at=timestamp(plan.public['start_at_utc']), uni_symbols=plan.focus.uni_symbols,
            focus_symbols=plan.focus.focus_symbols, hot_symbols=(), source='authenticated-recovery-bootstrap',
            metadata={MARKER: True, 'experimental': True, 'configuration_sha256': plan.configuration_sha256,
                'opening_content_sha256': plan.settings.opening_content_sha256,
                'focus_content_sha256': plan.settings.focus_content_sha256})
        store.record_membership_revision(anchor)
        stage('journal_initialized')
        before_write()
        requests = SamplingRequestStore(root/'requests.sqlite3', session_date=plan.opening.session_date,
            baseline=SamplingMembership(frozenset(anchor.uni_symbols), frozenset(anchor.focus_symbols), frozenset()),
            policy=SamplingPolicy('integrated-bootstrap-admin', 0, 0, 'immediate_cap'),
            admission=plan.admission, clock=clock)
        requests.initialize()
        service = SamplingPublicationService(root/'publication.sqlite3', request_store=requests,
            journal=SamplingJournal(store), settings=PublicationSettings('integrated-hot-recovery', 1, .5,
                timestamp(plan.public['stop_at_utc'])), clock=clock)
        service.initialize()
        stage('coordinator_initialized')
        before_write()
        query = RecoveryQuery(plan.opening.session_date, plan.opening.session_date)
        feed = FeedRecoveryTransport(root/'feed.sqlite3', session_date=plan.opening.session_date,
            queries=(query,), limits=FeedLimits(), clock=clock)
        feed.initialize(create=True)
        live = NasdaqSamplingProducer(root/'live.sqlite3', request_store=requests,
            settings=HaltProducerSettings('nasdaq-observations-integrated', ('LUDP', 'M'),
                'regular_close', False, False, 'external'), clock=clock)
        live.initialize()
        recovery = NasdaqRecoveryReceipts(root/'recovery.sqlite3', request_store=requests,
            settings=RecoverySettings(plan.opening.session_date, 'late_start', (query,), False), clock=clock)
        recovery.initialize(create=True)
        delivery = NasdaqRecoveryDelivery(root/'delivery.sqlite3', live_producer=live,
            recovery_receipts=recovery, producer_id=OWNER, clock=clock)
        delivery.initialize(create=True)
        stage('source_ledgers_initialized')
        before_write()
        collector_settings = HotCollectorSettings(str(store.database_path.resolve()), plain(service.identity),
            plan.public['start_at_utc'], plan.public['stop_at_utc'], max_quote_calls=60, max_symbols=1)
        collector = HotRecoveryCollector(collector_settings, client_factory=lambda prepared=client: prepared, clock=clock)
        collector.prepare(create=True)  # Initial poll_run is now strictly after credential acceptance.
        stage('initial_poll_run_registered')
        worker_config = {'collector': asdict(collector_settings), 'authentication': asdict(auth)}
        retained = SessionPassword(password, digest(worker_config))
        before_write()
        atomic_json(root/'authenticated-worker.json', worker_config)
        stage('bootstrap_completed')
        receipt.update(status='BOOTSTRAPPED_NOT_RUNNING', stages=stages,
            initial_membership_sha256=anchor.content_sha256, native_run_id=collector.poller.run.run_id,
            worker_configuration_sha256=digest(worker_config),
            remaining='runtime loop, live catalog/resolution, cumulative identity budget and one-symbol fence, resume and coupled qualification')
        atomic_json(root/'bootstrap.json', receipt)
        session = BootstrapSession()
        session.plan, session.client, session.password = plan, client, retained
        session.store, session.requests, session.service = store, requests, service
        session.feed, session.live, session.recovery, session.delivery = feed, live, recovery, delivery
        session.collector, session.receipt, session.closed = collector, receipt, False
        client = retained = None
        return session
    except (BootstrapError, StartupError):
        raise
    except Exception:
        raise BootstrapError('initialization_failed') from None
    finally:
        if isinstance(password, bytearray):
            password[:] = b'\0'*len(password)
            password.clear()
        if client is not None:
            client.close()
        if retained is not None:
            retained.close()
        if claimed and client is not None:
            try:
                atomic_json(root/'bootstrap-failed.json', {'contract': CONTRACT,
                    'status': 'PARTIAL_REQUIRES_REVIEW', 'configuration_sha256': plan.configuration_sha256,
                    'stages': stages, 'automatic_reset': False})
            except Exception:
                pass
