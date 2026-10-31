"""Dated operator packaging around the accepted public daily Hot launcher.

Prepare saved reviews/commands; never publish opening membership, install code,
reset state, or start a poller implicitly. Authentication stays in run_launch.
"""
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import re
import subprocess
import sys
from zoneinfo import ZoneInfo

from .controller_bootstrap import _proposal, EXPECTED_HELPERS
from .daily_launch import build_launch_review, run_launch, CONTRACT as LAUNCH_CONTRACT
from .daily_operating import inspect_operating_status, request_stop
from .daily_session import regular_path
from .daily_supervision import read_json, sealed
from .installed_startup_probe import inspect_dependencies
from .live_profile import source_guard
from .operating_plan import proposed_policy, SINGLE_PROFILE
from .sampling_requests import digest, timestamp, utc_text

CONTRACT = 'daily-hot-operator-delivery-v1'
MARKET_BASE = '6b53ab1d12e4e1fdaf4deb1d70b717e13570358c'
WATCHLIST_BASE = 'e2ef6f62856ba3226c41456b7779951aa8640cbf'
DEPENDENCIES = {'mb-tools': '0.6.0', 'schwabdev': '4.0.0', 'cryptography': '49.0.0'}
MAX_OPENING_UNI = 600
FRESH_START_LEAD_SECONDS = 60
ET = ZoneInfo('America/New_York')
UNSAFE_CMD = re.compile(r'[\r\n\x00&|<>^%!\"]')


class OperatorError(ValueError):
    """Controlled operator-facing refusal; never includes SDK or file content."""


def _text(value):
    value = str(value)
    if not value or UNSAFE_CMD.search(value):
        raise OperatorError('Path or argument contains unsupported CMD metacharacters')
    return value


def cmdline(argv):
    """Quote every argument for CMD/C-runtime parsing; forbid expansion syntax."""
    quoted = []
    for arg in argv:
        text = _text(arg)
        trailing = len(text)-len(text.rstrip('\\'))
        quoted.append('"'+text+'\\'*trailing+'"')
    return ' '.join(quoted)


def _path(value, *, exists=False):
    _text(value)
    return regular_path(value, exists=exists)


def release_info(source):
    source = _path(source)
    sha = source_guard(source)
    manifest = read_json(source/'SOURCE_INVENTORY.json')
    release = read_json(source/'RELEASE.json')
    policy = proposed_policy(release.get('policy_profile', SINGLE_PROFILE))
    if (manifest['contract'] != 'daily-hot-operating-release-source-v1'
            or release['contract'] != CONTRACT
            or release['policy_sha256'] != digest(policy)
            or release['dependency_versions'] != DEPENDENCIES
            or release['production_baselines'] != {'market_data': MARKET_BASE, 'watchlists': WATCHLIST_BASE}):
        raise OperatorError('Original operating release and policy required')
    return source, sha, release


def windows_qualification(source, inventory):
    report = read_json(source/'runs/windows-qualification.json')
    if (report.get('contract') != 'daily-hot-operator-offline-qualification-v1'
            or report.get('result') != 'PASS' or report.get('windows_checks_passed') is not True
            or report.get('source_inventory_sha256') != inventory
            or report.get('failures') or report.get('errors') or report.get('skipped')):
        raise OperatorError('Matching Windows operating-package qualification required')
    return report


def git_state(root):
    root = _path(root)
    def git(*args):
        return subprocess.check_output(['git', '--no-optional-locks', '-C', str(root), *args], timeout=10,
                                       stderr=subprocess.DEVNULL, text=True).strip()
    return {'root': str(root), 'branch': git('branch', '--show-current'),
            'head': git('rev-parse', 'HEAD'), 'tracked_clean': not bool(git('status', '--porcelain', '--untracked-files=no'))}


def review_deployment(source, market_data_root, watchlists_root, *, repo_reader=git_state,
                      qualification_reader=windows_qualification, dependency_reader=inspect_dependencies):
    source, inventory, release = release_info(source)
    qualification_reader(source, inventory)
    dependencies = dependency_reader(EXPECTED_HELPERS)
    if dependencies.get('qualified') is not True or dependencies.get('versions') != DEPENDENCIES:
        raise OperatorError('Installed credential helpers/dependencies differ')
    repositories = {'market_data': repo_reader(_path(market_data_root)),
                    'watchlists': repo_reader(_path(watchlists_root))}
    for key, expected in (('market_data', MARKET_BASE), ('watchlists', WATCHLIST_BASE)):
        value = repositories[key]
        if value['branch'] != 'main' or value['head'] != expected or value['tracked_clean'] is not True:
            raise OperatorError('Installed production baseline differs: '+key)
    return {'contract': CONTRACT, 'result': 'REVIEW_READY', 'source_root': str(source),
            'source_inventory_sha256': inventory, 'release': release, 'repositories': repositories,
            'dependencies': dependencies, 'source_installation_required': False,
            'production_changes': False, 'provider_access': False, 'actual_vault_access': False}


def acquire_daily_catalog(source, session_date, *, clock=None, acquire=None,
                          qualification_reader=windows_qualification):
    """One durable two-download preparation allowance for the ET date."""
    from .integrated_catalog import DirectoryCatalog, acquire_catalog
    source, inventory, _ = release_info(source)
    qualification_reader(source, inventory)
    now = (clock or (lambda: datetime.now(timezone.utc)))()
    day = date.fromisoformat(str(session_date))
    if now.astimezone(ET).date() != day or day.weekday() >= 5:
        raise OperatorError('Catalog acquisition requires the target trading weekday in ET')
    runs = source/'runs'
    runs.mkdir(exist_ok=True)
    destination = runs/('daily_catalog_'+day.strftime('%Y%m%d'))
    attempt = runs/('catalog_'+day.strftime('%Y%m%d')+'.json')
    identity = {'contract': CONTRACT, 'source_inventory_sha256': inventory,
                'session_date': str(day), 'catalog_root': str(destination), 'maximum_downloads': 2}
    if attempt.exists():
        previous = read_json(attempt)
        if any(previous.get(k) != v for k, v in identity.items()):
            raise OperatorError('Original catalog attempt identity differs')
        catalog = DirectoryCatalog.load(destination)
        if any(timestamp(s['retrieved_at_utc']).astimezone(ET).date() != day
               for s in catalog.public['sources'].values()):
            raise OperatorError('Retained catalog date differs')
        return {'result': 'REUSED', 'catalog_root': str(destination), 'new_directory_requests': 0}
    if destination.exists():
        raise OperatorError('Unbound catalog directory already exists')
    # Charge before either request. An incomplete/unknown attempt cannot reset.
    with attempt.open('x', encoding='utf-8') as out:
        json.dump(dict(identity, reserved_at_utc=utc_text(now)), out, sort_keys=True)
    catalog = (acquire or acquire_catalog)(deadline=now+timedelta(seconds=60), allow_network=True)
    if any(timestamp(s['retrieved_at_utc']).astimezone(ET).date() != day
           or timestamp(s['retrieved_at_utc']) > (clock or (lambda: datetime.now(timezone.utc)))()
           for s in catalog.public['sources'].values()):
        raise OperatorError('Downloaded catalog is not from the target ET date')
    catalog.persist(destination)
    return {'result': 'SAVED', 'catalog_root': str(destination), 'new_directory_requests': 2}


def _batch(path, source, command, *, arguments=(), approval_arguments=False):
    argv = [str(Path(sys.executable).resolve()), '-I', '-B', str(source/'run.py'), command, *arguments]
    line = cmdline(argv)+(' %*' if approval_arguments else '')
    with path.open('x', encoding='utf-8', newline='') as out:
        out.write('@echo off\r\nsetlocal DisableDelayedExpansion\r\n'+line+'\r\nexit /b %errorlevel%\r\n')


def _write_review(source, review, number):
    day = review['backend_review']['session_date'].replace('-', '')
    folder = source/'runs'/f'review_{day}_{number:02d}'
    folder.mkdir(exist_ok=False)
    path = folder/'launch-review.json'
    with path.open('x', encoding='utf-8') as out:
        json.dump(review, out, indent=2)
        out.write('\n')
    common = ('--review', str(path))
    for name, command in (('START_HOT.cmd', 'start'), ('STATUS.cmd', 'status'),
                          ('MEMBERSHIP.cmd', 'membership'), ('STOP_HOT.cmd', 'stop'),
                          ('ROLLBACK_HOT.cmd', 'stop')):
        _batch(folder/name, source, command, arguments=common, approval_arguments=command == 'start')
    raw = review['backend_review']['configuration']
    start, stop = timestamp(raw['collector']['start_at_utc']), timestamp(raw['collector']['stop_at_utc'])
    summary = {
        'contract': CONTRACT, 'result': 'PREPARED_NOT_ACTIVATED', 'review_path': str(path),
        'approved_review_sha256_required': review['review_sha256'], 'mode': review['mode'],
        'session_date': review['backend_review']['session_date'], 'source_root': str(source),
        'source_inventory_sha256': review['source_inventory_sha256'],
        'window_et': {'start': start.astimezone(ET).isoformat(), 'stop': stop.astimezone(ET).isoformat()},
        'window_utc': {'start': utc_text(start), 'stop': utc_text(stop)},
        'fresh_password_deadline_et': (start-timedelta(seconds=FRESH_START_LEAD_SECONDS)).astimezone(ET).isoformat() if review['mode']=='fresh' else None,
        'state_root': raw['publication']['state_root'], 'outer_root': review['outer_root'],
        'journal_path': raw['publication']['journal_path'],
        'policy': raw['collector']['daily_binding']['policy'],
        'start_command_after_approval': cmdline([str(folder/'START_HOT.cmd'), '--approved-review-sha256',
                                              review['review_sha256'], '--activation-approved']),
        'production_changes': False, 'provider_access': False, 'actual_vault_access': False,
        'rollback': 'STOP_HOT/ROLLBACK_HOT, then STATUS until owned cleanup is EXIT_OBSERVED with scope_empty_observed=true; keep Uni/Focus/Health running and preserve membership/state.'}
    (folder/'operating-summary.json').write_text(json.dumps(summary, indent=2)+'\n', encoding='utf-8')
    return summary


def _next_review(source, day, first=1):
    for number in range(first, 100):
        if not (source/'runs'/f'review_{day}_{number:02d}').exists():
            return number
    raise OperatorError('Review draft locations exhausted; preserve all existing drafts')


def prepare_day(source, opening, focus, *, journal, ecfg, market_data_root, watchlists_root,
                clock=None, repo_reader=git_state, qualification_reader=windows_qualification,
                dependency_reader=inspect_dependencies):
    source, _, release = release_info(source)
    deployment = review_deployment(source, market_data_root, watchlists_root, repo_reader=repo_reader,
        qualification_reader=qualification_reader, dependency_reader=dependency_reader)
    opening, focus, journal, ecfg = (_path(opening, exists=True), _path(focus, exists=True),
                                     _path(journal, exists=True), _path(ecfg))
    proposal, _ = _proposal(focus)
    if len(proposal.uni_symbols) > MAX_OPENING_UNI:
        raise OperatorError('Opening Uni exceeds the initial 600-symbol operating capacity')
    now = (clock or (lambda: datetime.now(timezone.utc)))()
    if now >= proposal.effective_at-timedelta(seconds=FRESH_START_LEAD_SECONDS):
        raise OperatorError('Fresh Hot startup requires the pre-open window; no earlier slots are backfilled')
    expected_journal = _path(market_data_root)/'output'/f'quote_observation_journal_v2_api_opening_{proposal.session_date}'/f'{proposal.session_date}.sqlite3'
    if journal != expected_journal:
        raise OperatorError('Operating journal must be the installed market-data daily journal')
    day = proposal.session_date.strftime('%Y%m%d')
    runs = source/'runs'
    number = _next_review(source, day)
    state, catalog, outer = (runs/('daily_hot_'+day), runs/('daily_catalog_'+day), runs/f'daily_outer_{day}_{number:02d}')
    review = build_launch_review(source, opening, focus, journal=journal, catalog=catalog, state_root=state,
        ecfg=ecfg, outer_root=outer, clock=clock, dependency_reader=dependency_reader,
        policy_profile=release.get('policy_profile', SINGLE_PROFILE))
    summary = _write_review(source, review, number)
    (Path(summary['review_path']).parent/'deployment-review.json').write_text(
        json.dumps(deployment, indent=2)+'\n', encoding='utf-8')
    return summary


def load_review(source, path):
    source, inventory, _ = release_info(source)
    path = _path(path, exists=True)
    value = read_json(path)
    raw = dict(value)
    sha = raw.pop('review_sha256')
    if (digest(raw) != sha or raw['contract'] != LAUNCH_CONTRACT
            or value['source_root'] != str(source) or value['source_inventory_sha256'] != inventory
            or not path.is_relative_to(source/'runs') or path.name != 'launch-review.json'):
        raise OperatorError('Original prepared launch review required')
    cfg = value['backend_review']['configuration']
    day = value['backend_review']['session_date'].replace('-', '')
    name = re.fullmatch('review_'+day+r'_([0-9]{2})', path.parent.name)
    if (not name or name[1] == '00' or cfg['publication']['state_root'] != str(source/'runs'/('daily_hot_'+day))
            or cfg['catalog_path'] != str(source/'runs'/('daily_catalog_'+day))
            or value['outer_root'] != str(source/'runs'/('daily_outer_'+day+'_'+name[1]))):
        raise OperatorError('Prepared review paths differ')
    return value, int(name[1])


def prepare_resume(source, previous_review, *, clock=None, qualification_reader=windows_qualification,
                   dependency_reader=inspect_dependencies):
    source, inventory, _ = release_info(source)
    qualification_reader(source, inventory)
    previous, number = load_review(source, previous_review)
    raw = previous['backend_review']['configuration']
    pub = raw['publication']
    day = previous['backend_review']['session_date'].replace('-', '')
    number = _next_review(source, day, number+1)
    review = build_launch_review(source, pub['opening_proposal'], pub['focus_proposal'],
        journal=pub['journal_path'], catalog=raw['catalog_path'], state_root=pub['state_root'],
        ecfg=raw['authentication']['ecfg_path'], outer_root=source/'runs'/f'daily_outer_{day}_{number:02d}',
        mode='manual_resume', previous_outer=previous['outer_root'], clock=clock,
        dependency_reader=dependency_reader, policy_profile=pub.get('policy_profile', SINGLE_PROFILE))
    return _write_review(source, review, number)


def start_day(source, path, *, approved_review_sha256=None, activation_approved=False,
              qualification_reader=windows_qualification, **trusted_test_seams):
    source, inventory, _ = release_info(source)
    qualification_reader(source, inventory)
    value, _ = load_review(source, path)
    if value['backend_review']['opening_counts']['uni'] > MAX_OPENING_UNI:
        raise OperatorError('Opening Uni exceeds the initial 600-symbol operating capacity')
    clock = trusted_test_seams.get('clock') or (lambda: datetime.now(timezone.utc))
    from .authenticated_startup import SessionPassword
    def startup_window():
        if (value['mode'] == 'fresh' and clock() >=
                timestamp(value['backend_review']['configuration']['collector']['start_at_utc'])-timedelta(seconds=FRESH_START_LEAD_SECONDS)):
            raise OperatorError('Fresh Hot pre-open startup window ended; no catch-up or reset')
    startup_window()
    private_prompt = trusted_test_seams.pop('prompt', None) or SessionPassword.prompt
    def prompt(configuration_sha256):
        secret = private_prompt(configuration_sha256)
        try:
            startup_window()
            return secret
        except BaseException:
            secret.close()
            raise
    return run_launch(value, approved_review_sha256=approved_review_sha256,
                      activation_approved=activation_approved, prompt=prompt, **trusted_test_seams)


def day_status(source, path):
    from .daily_hot_status import inspect_hot_status
    value, _ = load_review(source, path)
    return {'outer': inspect_operating_status(value['outer_root']),
            'hot': inspect_hot_status(value['backend_review']['configuration']['publication']['state_root']),
            'provider_access': False, 'restart_performed': False}


def stop_day(source, path):
    value, _ = load_review(source, path)
    return request_stop(value['outer_root'])
