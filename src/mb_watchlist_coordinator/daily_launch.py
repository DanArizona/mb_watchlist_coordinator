"""Public daily Hot composition; approval precedes the private password prompt.

The backend owns all authentication, publication, budgets and recovery. This
module binds its existing APIs to fixed delivered entries and a review digest.
Injection arguments are trusted offline test seams, never file or CLI options.
"""
from datetime import datetime, timezone
from contextlib import closing
from pathlib import Path
import sqlite3
import sys

from .authenticated_startup import AuthStartupSettings, SessionPassword
from .controller_bootstrap import EXPECTED_HELPERS
from .daily_collector import DailyCollectorSettings
from .daily_operating import DailyOperatingOwner, load_binding
from .daily_operating_review import build_operating_review
from .daily_session import DailySettings, regular_path
from .daily_supervision import DailyProcessState, DailyWorkerConfiguration, read_json
from .installed_startup_probe import inspect_dependencies
from .live_profile import source_guard
from .sampling_requests import digest

CONTRACT = 'daily-hot-public-launch-review-v1'


def configuration(raw):
    if set(raw) != {'contract', 'publication', 'catalog_path', 'collector', 'authentication'}:
        raise ValueError('Original daily configuration required')
    result = DailyWorkerConfiguration(DailySettings(**raw['publication']), raw['catalog_path'],
        DailyCollectorSettings(**raw['collector']), AuthStartupSettings(**raw['authentication']))
    if result.payload() != raw:
        raise ValueError('Original daily configuration differs')
    return result


def fixed_entries(source_root, inventory_sha256, dependency_sha256, state_root):
    source = regular_path(source_root)
    entry = source/'coordinator/src/mb_watchlist_coordinator/daily_launch_entry.py'
    # The caller cannot select an executable script from a review file.
    if entry.resolve() != Path(__file__).with_name('daily_launch_entry.py').resolve():
        raise ValueError('Use the delivered daily launch entry')
    prefix = (str(Path(sys.executable).resolve()), '-I', '-B', str(entry))
    config = str(regular_path(state_root)/'daily-worker.json')
    commands = {role: (*prefix, role, inventory_sha256, dependency_sha256, config)
        for role in ('collector', 'identity', 'report')}
    controller = (*prefix, 'controller', inventory_sha256, dependency_sha256)
    reporter = (*prefix, 'reporter', inventory_sha256, dependency_sha256)
    return commands, controller, reporter


def _invocation_preflight(config, commands, mode, previous_outer, clock):
    state = Path(config.publication.state_root)
    claim = Path(config.publication.journal_path).with_suffix('.daily-hot-session.json')
    if mode == 'fresh':
        if previous_outer is not None or state.exists() or claim.exists():
            raise ValueError('Fresh mode cannot reset existing or partial daily state')
        from .controller_bootstrap import strict_json
        journal = Path(config.publication.journal_path)
        with closing(sqlite3.connect(journal.as_uri()+'?mode=ro', uri=True)) as connection:
            if (connection.execute('SELECT count(*) FROM sampling_membership_revision').fetchone()[0] != 2
                    or any(strict_json(row[0]).get('watchlist_kind') == 'hot' for row in
                        connection.execute('SELECT configuration_json FROM poll_run'))):
                raise ValueError('Existing native Hot or membership history requires original-ledger recovery')
        if any(p.exists() for p in (journal.with_suffix('.daily-hot-provider-stop.json'),
                journal.with_suffix('.hot.poller.daily-collector.json'))):
            raise ValueError('Existing Hot collector evidence requires original-ledger recovery')
        return None
    if mode != 'manual_resume' or previous_outer is None:
        raise ValueError('Manual resume requires the original completed outer invocation')
    previous = load_binding(regular_path(previous_outer))
    from .daily_supervision import unseal
    result = unseal(read_json(Path(previous_outer)/'operating-result.json'))
    if (previous['state_root'] != str(state)
            or previous['configuration_sha256'] != digest(config.payload())
            or previous['commands'] != {k: list(v) for k, v in commands.items()}
            or result['nonce'] != previous['nonce']
            or result['configuration_sha256'] != previous['configuration_sha256']
            or result['cleanup']['status'] != 'EXIT_OBSERVED'
            or result['cleanup'].get('scope_empty_observed') is not True):
        raise ValueError('Original configuration and observed empty owned scope required')
    binding = read_json(state/'driver-binding.json')
    saved = DailyProcessState(state, binding).read()
    if (binding['configuration_sha256'] != digest(config.payload())
            or binding['commands'] != {k: list(v) for k, v in commands.items()}
            or read_json(state/'daily-worker.json') != config.payload()
            or not saved['initialized'] or saved['terminal']
            or len(saved['starts']) >= 3 or len(saved['invocations']) >= 3):
        raise ValueError('Original resumable driver state and remaining budgets required')
    # A saved cleanup receipt precedes final reporting. Wait for the original
    # outer owner to finish as well; never overlap it with a manual resume.
    from .sampling_service import owner_lock
    paths = (Path(previous_outer)/'operating-owner.lock', state/'driver-owner.lock',
        Path(config.publication.journal_path).with_suffix('.daily-hot-owner.lock'))
    for path in paths:
        regular_path(path, exists=True)
        if path.stat().st_size < 1:
            raise ValueError('Original nonempty ownership evidence required')
        with owner_lock(path):
            pass
    for path in (state/'workers/worker.lock', state/'identity-owner.lock'):
        if path.exists():
            regular_path(path, exists=True)
            with owner_lock(path):
                pass
    from .daily_worker_view import DailyPublicationReader
    reader = DailyPublicationReader(config.publication, config.catalog_path,
        binding=config.collector.daily_binding, claim=config.collector.daily_claim,
        publication_binding=config.collector.publication_binding, fence=lambda: None, clock=clock)
    _, gate = reader.validate(with_state=True)
    stop = Path(config.publication.journal_path).with_suffix('.daily-hot-provider-stop.json')
    manifest = Path(config.publication.journal_path).with_suffix('.hot.poller.daily-collector.json')
    if (gate['identity_gate']['provider_stop_required'] or stop.exists()
            or manifest.exists() and read_json(manifest).get('provider_stop')):
        raise ValueError('Original provider stop remains latched; review it before resume')
    return {'previous_outer': str(previous_outer), 'previous_nonce': previous['nonce'],
        'charged_worker_starts': len(saved['starts']), 'maximum_worker_starts': 3,
        'budgets_reset': False, 'minimum_replacement_hold_seconds': 15}


def build_launch_review(source_root, opening, focus, *, journal, catalog, state_root,
                        ecfg, outer_root, mode='fresh', previous_outer=None,
                        clock=None, dependency_reader=inspect_dependencies,
                        collection_window=None):
    clock = clock or (lambda: datetime.now(timezone.utc))
    source = regular_path(source_root)
    inventory = source_guard(source)
    observed = dependency_reader(EXPECTED_HELPERS)
    if observed.get('qualified') is not True:
        raise ValueError('Installed dependencies are not qualified: '+str(observed.get('reason')))
    backend = build_operating_review(opening, focus, journal=journal, catalog=catalog,
        state_root=state_root, ecfg=ecfg, clock=clock, collection_window=collection_window)
    config = configuration(backend['configuration'])
    commands, controller, reporter = fixed_entries(source, inventory, digest(observed), state_root)
    resume = _invocation_preflight(config, commands, mode, previous_outer, clock)
    # Constructor validates a separate fresh outer path and the original dated
    # window. It creates no state, starts no process and accepts no password.
    DailyOperatingOwner(outer_root, config, commands=commands, controller_entry=controller,
        reporter_entry=reporter, mode=mode, allow_network=True, activation_approved=True, clock=clock)
    value = {'contract': CONTRACT, 'source_root': str(source),
        'source_inventory_sha256': inventory, 'dependencies': observed,
        'dependency_sha256': digest(observed), 'backend_review': backend,
        'configuration_sha256': backend['configuration_sha256'],
        'outer_root': str(regular_path(outer_root)), 'mode': mode, 'resume': resume,
        'commands': {k: list(v) for k, v in commands.items()},
        'controller_entry': list(controller), 'reporter_entry': list(reporter),
        'approval_scope': 'this source, configuration, operating limits and invocation mode',
        'status': 'REVIEW_CANDIDATE', 'activation_allowed': False,
        'actual_vault_access': False, 'provider_access': False, 'production_changes': False}
    return dict(value, review_sha256=digest(value))


def recheck_review(review, *, clock=None, dependency_reader=inspect_dependencies):
    if not isinstance(review, dict):
        raise ValueError('Original public launch review object required')
    content = dict(review)
    sha = content.pop('review_sha256')
    if content['contract'] != CONTRACT or digest(content) != sha:
        raise ValueError('Original public launch review checksum differs')
    raw = content['backend_review']['configuration']
    pub = raw['publication']
    rebuilt = build_launch_review(content['source_root'], pub['opening_proposal'], pub['focus_proposal'],
        journal=pub['journal_path'], catalog=raw['catalog_path'], state_root=pub['state_root'],
        ecfg=raw['authentication']['ecfg_path'], outer_root=content['outer_root'],
        mode=content['mode'], previous_outer=(content['resume'] or {}).get('previous_outer'),
        clock=clock, dependency_reader=dependency_reader,
        collection_window=content['backend_review'].get('collection_window'))
    if rebuilt != review:
        raise ValueError('Reviewed source, dependencies, inputs or invocation state changed')
    return configuration(raw)


def run_launch(review, *, approved_review_sha256=None, activation_approved=False,
               clock=None, prompt=None, dependency_reader=inspect_dependencies,
               owner_factory=DailyOperatingOwner, stop_requested_callback=lambda: False):
    if (not isinstance(review, dict) or activation_approved is not True
            or approved_review_sha256 != review.get('review_sha256')):
        raise ValueError('Explicit approval of this exact daily launch review required')
    config = recheck_review(review, clock=clock, dependency_reader=dependency_reader)
    commands, controller, reporter = fixed_entries(review['source_root'],
        review['source_inventory_sha256'], review['dependency_sha256'], config.publication.state_root)
    password = None
    try:
        password = (prompt or SessionPassword.prompt)(review['configuration_sha256'])
        # Time can pass and input bytes can change while the operator types.
        recheck_review(review, clock=clock, dependency_reader=dependency_reader)
        owner = owner_factory(review['outer_root'], config, commands=commands,
            controller_entry=controller, reporter_entry=reporter, mode=review['mode'],
            allow_network=True, activation_approved=True, clock=clock)
        owner.binding['public_launch'] = {'review': review,
            'approved_review_sha256': approved_review_sha256,
            'settings_approved_for_this_invocation': True}
        return owner.run(password, stop_requested_callback=stop_requested_callback)
    finally:
        if password is not None:
            password.close()


def validate_owned_launch(root, inventory_sha256, dependency_sha256):
    """Bind a fixed controller/reporter entry to the original approved owner."""
    binding = load_binding(root)
    approval = binding['public_launch']
    review = approval['review']
    content = dict(review)
    sha = content.pop('review_sha256')
    if (digest(content) != sha or sha != approval['approved_review_sha256']
            or approval['settings_approved_for_this_invocation'] is not True
            or review['contract'] != CONTRACT or review['outer_root'] != str(root)
            or review['configuration_sha256'] != binding['configuration_sha256']
            or review['configuration_sha256'] != digest(review['backend_review']['configuration'])
            or review['source_inventory_sha256'] != inventory_sha256
            or review['dependency_sha256'] != dependency_sha256
            or review['mode'] != binding['mode'] or binding['allow_network'] is not True
            or review['commands'] != binding['commands']):
        raise ValueError('Owned launch does not match the approved review')
    source_guard(review['source_root'], inventory_sha256)
    commands, controller, reporter = fixed_entries(review['source_root'], inventory_sha256,
        dependency_sha256, binding['state_root'])
    if (review['commands'] != {k: list(v) for k, v in commands.items()}
            or review['controller_entry'] != list(controller)
            or review['reporter_entry'] != list(reporter)):
        raise ValueError('Fixed process entries differ')
    return binding
