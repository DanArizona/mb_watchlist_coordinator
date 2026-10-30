"""A bounded, isolated invocation of the public daily Hot composition.

Preparation copies only the supplied opening proposals. The actual source,
admission, authentication, native collector, owner and reporter are the daily
implementations. No symbol or halt is injected by the live entry.
"""
from contextlib import closing
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from zoneinfo import ZoneInfo

from .controller_bootstrap import _proposal
from .authenticated_startup import SessionPassword
from .daily_feed import DailyFeedTransport, collection_feed_limits
from .daily_launch import build_launch_review, configuration, run_launch
from .daily_operating import DailyOperatingOwner, load_binding
from .daily_session import regular_path
from .daily_supervision import read_json, sealed, unseal
from .daily_worker_view import DailyPublicationReader
from .installed_startup_probe import inspect_dependencies
from .integrated_catalog import DirectoryCatalog
from .live_profile import source_guard
from .recovery_workers import atomic_json
from .sampling_requests import digest, plain, timestamp, utc_text

CONTRACT = 'market-open-daily-path-check-v1'
ET = ZoneInfo('America/New_York')
LIMITS = {'collection_window_seconds':180, 'minimum_startup_lead_seconds':45,
    'maximum_startup_lead_seconds':55, 'maximum_seconds_from_review_to_stop':235,
    'latest_launch_before_collection_seconds':8,
    'maximum_hot_quote_calls': 72,
    'maximum_active_hot_symbols': 1, 'maximum_distinct_added_symbols': 1,
    'maximum_identity_quote_calls': 3, 'maximum_feed_attempts': 4,
    'feed_seconds_after_completion': 60, 'maximum_directory_downloads': 2,
    'maximum_worker_starts': 3, 'maximum_outer_invocations': 1,
    'request_timeout_seconds': 3, 'credential_seconds': 8,
    'progress_seconds': 3, 'replacement_hold_seconds': 15,
    'cleanup_seconds': 10, 'report_seconds': 60, 'maximum_dispatch_lateness_seconds': .75}


class CheckRefused(ValueError):
    """A fixed, credential-free explanation suitable for the public command."""


def market_window(now, *, stop=None):
    """Clock gate plus operator confirmation; this is not a holiday calendar."""
    now = timestamp(now if isinstance(now,str) else utc_text(now))
    stop = timestamp(stop if isinstance(stop,str) else utc_text(stop)) if stop is not None else now+timedelta(seconds=235)
    local, end = now.astimezone(ET), stop.astimezone(ET)
    if (local.weekday() >= 5 or local.date() != end.date()
            or local < local.replace(hour=9, minute=30, second=0, microsecond=0)
            or end > local.replace(hour=16, minute=0, second=0, microsecond=0)
            or not 0 < (stop-now).total_seconds() <= 235):
        raise CheckRefused('A weekday 09:30-16:00 ET interval of at most 235 seconds is required')
    return local.date()


def trial_window(now):
    target=now+timedelta(seconds=45)
    start=target.replace(second=target.second//10*10,microsecond=0)+timedelta(seconds=10)
    # Start/end at a Uni/Focus second: the last Hot slot is two seconds before
    # stop, preserving its original dispatch/request bounds at normal closeout.
    return start,start+timedelta(seconds=180)


def _root(source, root, *, exists=False):
    source, root = regular_path(source), regular_path(root)
    if (exists and not root.is_dir() or root.parent != source/'runs'
            or not re.fullmatch(r'market_open_daily_[0-9]{8}_[0-9a-f]{8}',root.name)):
        raise CheckRefused('A separate delivered runs/market_open_daily_DATE_NONCE directory is required')
    return source, root


def describe():
    return {'contract':CONTRACT, 'limits':dict(LIMITS),
        'source':'real CURRENT, same-date history and fresh CURRENT; original admission rules',
        'selection':'first eligible exact broker-confirmed symbol; no forced roster or fabricated halt',
        'journal_scope':'new isolated daily-layout journal; copied r0/r1 baseline only',
        'production_hot_enabled':False, 'production_settings_adopted':False,
        'unmanaged_channels':['uni','focus','health'],
        'shared_sdk_token_refresh_possible':True,
        'clock':'actual UTC and elapsed monotonic time in the live entry',
        'quiet_run':'daily-path/source/idle checks can pass without an eligible admission; collection remains unobserved',
        'full_day_capacity_qualified':False, 'operating_release_qualified':False}


def prepare_trial(source_root, root, opening, focus, catalog, *, clock=None):
    """Local preparation only; the caller separately obtains the two public files.

    Never open the production journal or encrypted configuration. An interrupted
    preparation is retained, rather than reset or silently reused.
    """
    clock = clock or (lambda:datetime.now(timezone.utc))
    now = clock(); day = market_window(now)
    source, root = _root(source_root, root)
    inventory = source_guard(source)
    if root.exists(): raise CheckRefused('Existing or partial trial cannot be reused or reset')
    opening, focus = regular_path(opening, exists=True), regular_path(focus, exists=True)
    p0, h0 = _proposal(opening); p1, h1 = _proposal(focus)
    start = now.astimezone(ET).replace(hour=9,minute=30,second=0,microsecond=0)
    if (p0.session_date != day or p1.session_date != day or p0.revision != 0 or p1.revision != 1
            or p0.effective_at != start or p1.effective_at != start or not p0.uni_symbols
            or p0.uni_symbols != p1.uni_symbols or p0.focus_symbols or p0.hot_symbols or p1.hot_symbols
            or not 1 <= len(p1.focus_symbols) <= 40):
        raise CheckRefused('Today\'s real r0 and Focus r1 proposals with Hot empty are required')
    catalog.validate()
    if any(timestamp(s['retrieved_at_utc']).astimezone(ET).date()!=day
            or timestamp(s['retrieved_at_utc'])>now for s in catalog.public['sources'].values()):
        raise CheckRefused('Directory must have been retrieved on this ET date')
    # Read and bind exact bytes before creating any trial state.
    raw0, raw1 = opening.read_bytes(), focus.read_bytes()
    if [hashlib.sha256(b).hexdigest() for b in (raw0,raw1)] != [h0,h1]:
        raise CheckRefused('Proposal changed during preparation')
    root.mkdir(parents=True,exist_ok=False)
    inputs=root/'inputs'; inputs.mkdir()
    (inputs/'opening-r0.json').write_bytes(raw0); (inputs/'focus-r1.json').write_bytes(raw1)
    saved=catalog.persist(root/'daily_catalog')
    from mb_market_data.daily_journal import DailyQuoteObservationStore
    from mb_market_data.quote_observation_store import PollRunProvenance
    from mb_market_data.polling_cadence import CADENCE_PROFILES
    journal=root/f'quote_observation_journal_v2_api_opening_{day}'/f'{day}.sqlite3'
    store=DailyQuoteObservationStore(journal,session_date=day,schema_version=2);store.initialize()
    for proposal in (p0,p1):store.record_membership_revision(proposal)
    # These are cadence context descriptors, not live Uni/Focus collectors.
    # No full-session windows or acquisitions are invented for those channels.
    for channel,seconds in CADENCE_PROFILES['interleaved-v1'].items():
        store.record_run(PollRunProvenance('context-'+channel,now,'market-open-check-baseline',
            {'watchlist_kind':channel,'poll_seconds':list(seconds),'cadence_profile':'interleaved-v1',
             'context_only':True,'quote_collection_performed':False}))
    value={'contract':CONTRACT,'source_root':str(source),'root':str(root),
        'source_inventory_sha256':inventory,'session_date':str(day),'prepared_at_utc':utc_text(now),
        'original_inputs':{'opening':{'path':str(opening),'file_sha256':h0},
                           'focus':{'path':str(focus),'file_sha256':h1}},
        'copied_inputs':{'opening':str(inputs/'opening-r0.json'),'focus':str(inputs/'focus-r1.json')},
        'published_anchor':[p0.content_sha256,p1.content_sha256],
        'catalog_path':str(saved.path),'catalog_sha256':digest(saved.public),
        'journal_path':str(journal),'limits':dict(LIMITS),'production_journal_access':False}
    atomic_json(root/'prepared.json',sealed(value))
    return value


def load_prepared(source_root, root):
    source,root=_root(source_root,root,exists=True)
    value=unseal(read_json(root/'prepared.json'))
    day=value['session_date']
    if (value['contract']!=CONTRACT or value['source_root']!=str(source) or value['root']!=str(root)
            or not root.name.startswith('market_open_daily_'+day.replace('-','')+'_')
            or value['limits']!=LIMITS or value['production_journal_access'] is not False
            or value['copied_inputs']!={'opening':str(root/'inputs/opening-r0.json'),
                                      'focus':str(root/'inputs/focus-r1.json')}
            or value['catalog_path']!=str(root/'daily_catalog')
            or value['journal_path']!=str(root/f'quote_observation_journal_v2_api_opening_{day}'/f'{day}.sqlite3')):
        raise CheckRefused('Original isolated trial preparation is required')
    source_guard(source,value['source_inventory_sha256'])
    for key,path in value['copied_inputs'].items():
        if hashlib.sha256(regular_path(path,exists=True).read_bytes()).hexdigest()!=value['original_inputs'][key]['file_sha256']:
            raise CheckRefused('Copied opening proposal changed')
    catalog=DirectoryCatalog.load(value['catalog_path'])
    if digest(catalog.public)!=value['catalog_sha256']:raise CheckRefused('Prepared directory changed')
    return value


def build_trial_review(source_root, root, ecfg, *, clock=None, dependency_reader=inspect_dependencies):
    clock=clock or (lambda:datetime.now(timezone.utc))
    now=clock(); day=market_window(now)
    prepared=load_prepared(source_root,root)
    if prepared['session_date']!=str(day):raise CheckRefused('Trial belongs to another session date')
    start,stop=trial_window(now)
    window={'start_at_utc':utc_text(start),'stop_at_utc':utc_text(stop),
            'max_quote_calls':72}
    root=Path(prepared['root'])
    launch=build_launch_review(source_root,prepared['copied_inputs']['opening'],prepared['copied_inputs']['focus'],
        journal=prepared['journal_path'],catalog=prepared['catalog_path'],state_root=str(root/'daily_hot_check'),
        ecfg=ecfg,outer_root=str(root/'daily_outer_check'),collection_window=window,
        clock=clock,dependency_reader=dependency_reader)
    value={'contract':CONTRACT,'prepared_sha256':digest(prepared),**describe(),'root':str(root),
           'reviewed_at_utc':utc_text(now),
           'launch_review':launch}
    return dict(value,review_sha256=digest(value))


def validate_trial_review(review, *, clock=None):
    content=dict(review);sha=content.pop('review_sha256')
    launch=review['launch_review']; backend=launch['backend_review'];raw=backend['configuration']
    pub,collector=raw['publication'],raw['collector'];root=Path(review['root'])
    start,stop=timestamp(collector['start_at_utc']),timestamp(collector['stop_at_utc'])
    now=(clock or (lambda:datetime.now(timezone.utc)))()
    reviewed=timestamp(review['reviewed_at_utc'])
    market_window(start,stop=stop);market_window(now,stop=stop)
    if (digest(content)!=sha or any(review.get(k)!=v for k,v in describe().items())
            or stop-start!=timedelta(seconds=180)
            or (start,stop)!=trial_window(reviewed) or not reviewed<=now<=start-timedelta(seconds=8)
            or collector['max_quote_calls']!=72
            or collector['max_symbols']!=1 or launch['mode']!='fresh' or launch['resume'] is not None
            or pub['state_root']!=str(root/'daily_hot_check') or launch['outer_root']!=str(root/'daily_outer_check')
            or backend.get('collection_window')!={'start_at_utc':start.isoformat(),
                'stop_at_utc':stop.isoformat(),'max_quote_calls':72}):
        raise CheckRefused('Original fixed 180-second isolated fresh trial review required')
    prepared=load_prepared(launch['source_root'],root)
    if (digest(prepared)!=review['prepared_sha256'] or pub['journal_path']!=prepared['journal_path']
            or pub['opening_proposal']!=prepared['copied_inputs']['opening']
            or pub['focus_proposal']!=prepared['copied_inputs']['focus']
            or raw['catalog_path']!=prepared['catalog_path']):
        raise CheckRefused('Reviewed trial preparation differs')
    return review


def run_trial(review, *, trial_approved=False, market_open_confirmed=False, clock=None,
              prompt=None, dependency_reader=inspect_dependencies, owner_factory=DailyOperatingOwner,
              stop_requested_callback=lambda:False):
    if trial_approved is not True or market_open_confirmed is not True:
        raise CheckRefused('Explicit approval of this bounded trial and market-open confirmation are required')
    validate_trial_review(review,clock=clock)
    root=Path(review['root']);launch=review['launch_review']
    atomic_json(root/'approved-trial-review.json',sealed(review))
    def private_prompt(identity):
        secret=(prompt or SessionPassword.prompt)(identity)
        try:validate_trial_review(review,clock=clock)
        except BaseException:
            secret.close();raise
        return secret
    return run_launch(launch,approved_review_sha256=launch['review_sha256'],activation_approved=True,
        clock=clock,prompt=private_prompt,dependency_reader=dependency_reader,owner_factory=owner_factory,
        stop_requested_callback=stop_requested_callback)


def _empty_scope(cleanup):
    return (cleanup.get('status')=='EXIT_OBSERVED' and cleanup.get('scope_empty_observed') is True
        and cleanup.get('forced') is False and cleanup.get('controller_returncode')==0)


def summarize_trial(source_root, root, *, clock=None):
    """Read closed native/source evidence. Never authenticate, publish or repair."""
    prepared=load_prepared(source_root,root);root=Path(prepared['root'])
    review=unseal(read_json(root/'approved-trial-review.json'));launch=review['launch_review']
    # Expiry is expected here; the immutable launch binding and cleanup fence
    # replace live-entry freshness checks for post-stop reporting.
    saved=dict(review);sha=saved.pop('review_sha256')
    if digest(saved)!=sha or digest(prepared)!=review['prepared_sha256']:
        raise CheckRefused('Original approved trial record differs')
    config=configuration(launch['backend_review']['configuration'])
    outer=Path(launch['outer_root']);binding=load_binding(outer)
    owner=unseal(read_json(outer/'operating-result.json'))
    if (binding['public_launch']['review']!=launch or owner['nonce']!=binding['nonce']
            or owner['configuration_sha256']!=launch['configuration_sha256']):
        raise CheckRefused('Owner result does not match the approved trial')
    def closed():
        if not _empty_scope(owner['cleanup']):raise CheckRefused('Complete non-forced producer cleanup required')
    closed()
    reader=DailyPublicationReader(config.publication,config.catalog_path,
        binding=config.collector.daily_binding,claim=config.collector.daily_claim,
        publication_binding=config.collector.publication_binding,fence=closed,clock=clock)
    publication,gate=map(plain,reader.validate(with_state=True));identity=gate['identity_gate']
    state=Path(config.publication.state_root)
    driver=unseal(read_json(state/'driver-state.json'))
    driver_stop=unseal(read_json(state/'driver-stop.json'))
    def forced(value):
        if isinstance(value,dict):return value.get('forced') is True or any(forced(v) for v in value.values())
        if isinstance(value,list):return any(forced(v) for v in value)
        return False
    internal_cleanup=(driver_stop['cleanup_within_10_seconds'] is True
        and not driver_stop['evidence_errors'] and not forced(driver_stop['cleanup']))
    authentication=[]
    for path in state.glob('*.identity.json'):
        job=unseal(read_json(path));ready=unseal(read_json(path.with_name(job['token']+'.ready.json')))
        if (job['invocation']==driver['active_invocation'] and ready['token']==job['token']
                and ready['configuration_sha256']==launch['configuration_sha256']
                and ready['status']=='credentials_accepted'):
            authentication.append('identity')
    for start in driver['starts']:
        auth=read_json(state/'workers'/(start['token']+'.auth.json'))
        progress=read_json(state/'workers'/(start['token']+'.startup.json'))
        if (auth.get('token')==start['token'] and auth.get('status')=='credentials_accepted'
                and progress.get('status')=='first_completed_work_observed'):
            authentication.append('collector')
    feed=DailyFeedTransport(state/'daily-feed.sqlite3',session_date=reader.requests.session_date,
        queries=reader.gate.recovery.settings.queries,limits=collection_feed_limits(config.collector),clock=clock).snapshot()
    valid=[a for a in feed['attempts'] if a['outcome']['status']=='valid']
    currents=[timestamp(a['completed_at_utc']) for a in valid if a['query_id']=='CURRENT']
    dated=[timestamp(a['completed_at_utc']) for a in valid if a['query_id']!='CURRENT']
    # This is a bounded historical observation, not a current readiness promise.
    cutover=bool(len(currents)>=2 and dated and max(currents)>max(dated)
        and not feed['pending'] and not feed['stop_reason'] and len(valid)==len(feed['attempts']))
    with closing(sqlite3.connect(Path(config.collector.journal_path).as_uri()+'?mode=ro',uri=True)) as connection:
        hot=connection.execute('SELECT count(*) FROM quote_acquisition WHERE channel="hot"').fetchone()[0]
        statuses=dict(connection.execute('SELECT o.status,count(*) FROM quote_observation o '
            'JOIN quote_acquisition a ON a.acquisition_id=o.acquisition_id WHERE a.channel="hot" GROUP BY o.status'))
    reporting=owner['reporting']
    ok=(owner['result']=='STOPPED' and owner['stop_reason'] in ('window_ended','controller_stopped')
        and not driver['terminal'] and reporting.get('status')=='COMPLETE'
        and _empty_scope(reporting.get('cleanup',{})) and reporting.get('native_audit_passed') is True
        and reporting.get('two_fresh_replays_equal') is True and cutover
        and internal_cleanup
        and set(authentication)=={'identity','collector'} and not identity['provider_stop_required']
        and len(driver['starts'])<=3 and len(feed['attempts'])<=4 and identity['quote_permits']<=3
        and hot<=72 and all(k=='quote' for k in statuses))
    report={'contract':CONTRACT,**describe(),'root':str(root),'result':'PASS' if ok else 'INCOMPLETE',
        'daily_path_check_passed':bool(ok),'source_current_history_fresh_current_observed':cutover,
        'source_attempts':len(feed['attempts']),'source_valid_attempts':len(valid),
        'source_known_gaps':plain(reader.gate.recovery.snapshot())['known_gaps'],
        'authenticated_roles':sorted(set(authentication)),
        'identity_quote_permits':identity['quote_permits'],'selected_symbol':identity['selected_symbol'],
        'hot_acquisitions':hot,'hot_statuses':statuses,'worker_starts':len(driver['starts']),
        'internal_owned_role_cleanup_complete':internal_cleanup,
        'internal_owned_role_cleanup':driver_stop['cleanup'],
        'collection_observed':bool(hot and statuses and all(k=='quote' for k in statuses)),
        'owner':owner,'terminal':driver['terminal'],
        'native_membership_revisions':len(publication['journal']),
        'qualification_scope':'bounded market-open daily composition; only observed admissions/collection count',
        'production_journal_access':False}
    atomic_json(root/'daily-path-report.json',sealed(report))
    return report
