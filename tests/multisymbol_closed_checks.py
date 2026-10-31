"""Qualification-only checks of a completed synthetic owned run.

Use the original source/feed validators and read-only publication/native views.
Never start a process, dispatch, initialize/attach, recover, or rewrite this run.
The source's active readiness and its later stop status are different facts.
"""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace

from mb_watchlist_coordinator.daily_supervision import (DailyProcessState,
    DailyWorkerConfiguration, read_json, unseal)
from mb_watchlist_coordinator.sampling_requests import digest, timestamp

WARNINGS = {'intermediate_feed_mutations_not_reconstructible',
            'older_unknown_carryovers_not_proven_complete'}


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def active_source_at_stop(events, stopped_at, *, started_at):
    """Require the latest active status, not any earlier successful status.

    Three seconds is the unchanged progress freshness bound, not a new wait or
    a grace extension. Post-stop BLOCKED/errors remain failures. Only an explicit
    normal stop may omit the readiness fields after the cutoff.
    """
    stop, start = timestamp(stopped_at), timestamp(started_at)
    require(start < stop, 'Dated active interval required')
    statuses = [e for e in events if e['kind'] == 'status']
    active = [e for e in statuses if start <= timestamp(e['at_utc']) < stop]
    require(bool(active), 'No active source status before Stop')
    last = active[-1]
    require(last['status'] in ('READY', 'READY_WITH_GAPS') and
        last.get('discovery_scope_reconciled') is True and
        last.get('local_membership_effective') is True and
        not last.get('feed_stop_required') and
        not last.get('pending_window_query_ids') and
        set(last.get('reasons', ())) <= WARNINGS,
        'Latest active source status was not reconciled: '+json.dumps(last))
    age = (stop-timestamp(last['at_utc'])).total_seconds()
    require(0 < age < 3, 'Active source evidence is stale at Stop')
    later = [e for e in statuses if timestamp(e['at_utc']) >= stop]
    for event in later:
        normal = event['status'] == 'INCOMPLETE' and event.get('reasons') == ['stop_requested']
        ready = (event['status'] in ('READY', 'READY_WITH_GAPS') and
            event.get('discovery_scope_reconciled') is True and
            event.get('local_membership_effective') is True and
            not event.get('feed_stop_required') and
            not event.get('pending_window_query_ids') and
            set(event.get('reasons', ())) <= WARNINGS)
        require(normal or ready, 'Unexpected post-stop source failure: '+json.dumps(event))
    return {'active_status': last['status'], 'active_at_utc': last['at_utc'],
        'active_event_sha256': last['event_sha256'], 'age_at_stop_seconds': age,
        'discovery_scope_reconciled': True, 'local_membership_effective': True,
        'after_stop_status': later[-1]['status'] if later else None,
        'after_stop_reasons': later[-1].get('reasons') if later else None,
        'stop_requested_at_utc': stopped_at, 'feed_head_sha256': last['feed_head_sha256']}


def retained_fingerprints(root):
    """Protect persistent evidence; SQLite's volatile shared-memory file is not data."""
    result = {}
    for path in sorted(Path(root).rglob('*')):
        if path.is_symlink():
            raise ValueError('Closed evidence may not contain symlinks')
        if not path.is_file() or path.name.endswith('-shm'):
            continue
        sha = hashlib.sha256()
        with path.open('rb') as file:
            for block in iter(lambda: file.read(1024*1024), b''):
                sha.update(block)
        result[path.relative_to(root).as_posix()] = sha.hexdigest()
    return result


def assess_closed_owned(root):
    root = Path(root).resolve()
    before = retained_fingerprints(root)
    require(bool(before), 'Original closed run is absent')
    try:
        result = _assess_closed_owned(root)
    finally:
        require(retained_fingerprints(root) == before, 'Closed evidence changed during read-only reassessment')
    result['persistent_files_unchanged'] = True
    result['persistent_evidence_sha256'] = digest(before)
    return result


def _assess_closed_owned(root):
    """Check all original paced assertions, with the corrected source cutoff."""
    from mb_watchlist_coordinator.daily_operating import load_binding
    from mb_watchlist_coordinator.daily_worker_view import DailyPublicationReader
    from mb_watchlist_coordinator.daily_feed import collection_feed_limits
    from mb_watchlist_coordinator.daily_source import DailySourcePump
    from mb_market_data.quote_journal_audit import audit_quote_journal
    from mb_market_data.quote_observation_store import _utc_text
    root = Path(root).resolve()
    outer, state = root/'daily_outer_multi', root/'daily_hot_test'
    binding = load_binding(outer)
    owner = unseal(read_json(outer/'operating-result.json'))
    config = DailyWorkerConfiguration.load(state/'daily-worker.json')
    raw = config.payload()
    require(owner['nonce'] == binding['nonce'] and
        owner['configuration_sha256'] == binding['configuration_sha256'] == digest(raw),
        'Original closed owner/configuration binding required')
    require(Path(config.publication.state_root).resolve() == state and
        Path(raw['collector']['journal_path']).resolve().is_relative_to(root) and
        config.publication.policy_profile == 'multi-40-v1', 'Original multi fixture paths required')
    require(owner['result'] == 'STOPPED' and owner['stop_reason'] == 'operator_stop' and
        owner['failure_type'] is None, 'Owned run did not stop normally')
    for cleanup in (owner['cleanup'], owner['reporting']['cleanup']):
        require(cleanup['status'] == 'EXIT_OBSERVED' and cleanup['scope_empty_observed'] is True and
            cleanup['forced'] is False and cleanup['controller_returncode'] == 0,
            'Original owned cleanup did not finish')
    require(0 <= owner['cleanup_seconds'] < 10 and owner['reporting']['status'] == 'COMPLETE' and
        owner['reporting']['validation_passed'] is True, 'Closed native reporting was incomplete')
    driver_binding = read_json(state/'driver-binding.json')
    require(driver_binding['configuration_sha256'] == digest(raw), 'Driver configuration differs')
    driver = DailyProcessState(state, driver_binding).read()
    status = unseal(read_json(state/'hot-status.json'))
    require(status['identity_sha256'] == digest(driver_binding) and
        status['invocation'] == driver['active_invocation'] and status['state'] == 'STOPPED' and
        len(driver['starts']) == 1 and driver['terminal'] is None and
        len(status['hot_symbols']) == 40 and len(set(status['hot_symbols'])) == 40,
        'Closed driver/membership state differs')
    stopped = owner['acquisition_stop_requested_at_utc']
    clock = lambda: timestamp(stopped)
    view = DailyPublicationReader(config.publication, config.catalog_path,
        binding=config.collector.daily_binding, claim=config.collector.daily_claim,
        publication_binding=config.collector.publication_binding, fence=lambda: None, clock=clock)
    session = SimpleNamespace(root=view.root, settings=view.settings, binding=view.binding,
        gate=view.gate, requests=view.requests, recovery=view.gate.recovery,
        service=view.service._service, clock=clock, validate=view.validate)
    def forbidden(*args, **kwargs):
        raise AssertionError('Closed qualification must never access a provider')
    pump = DailySourcePump(session, identity_client=SimpleNamespace(quotes=forbidden),
        limits=collection_feed_limits(config.collector), clock=clock)
    require(read_json(pump.claim_path) == pump.claim and
        read_json(pump.ready_path) == {'claim': pump.claim, 'status': 'INITIALIZED'},
        'Original source invocation binding differs')
    feed_state, _ = pump.authority._validate_dependencies()
    source_events, _, source_head = pump.authority._read()
    readiness = active_source_at_stop(source_events, stopped,
        started_at=driver['invocations'][0]['at_utc'])
    # The feed reader verifies every retained response and its entire event chain.
    attempts = feed_state['attempts']
    require(feed_state['pending'] is None and len(attempts) in (3, 4) and
        all(a['synthetic'] and a['outcome']['status'] == 'valid' for a in attempts),
        'Expected three/four complete valid synthetic feed attempts')
    require(attempts[0]['query_id'] == 'CURRENT' and attempts[1]['query_id'] != 'CURRENT' and
        attempts[2]['query_id'] == 'CURRENT', 'CURRENT/history/fresh CURRENT sequence missing')
    feed = feed_state['events']
    starts, finishes = ([e for e in feed if e['kind'] == k] for k in ('start', 'finish'))
    require(len(starts) == len(finishes) == len(attempts), 'Feed start/finish count differs')
    gaps = [(timestamp(starts[n+1]['at_utc'])-timestamp(finishes[n]['at_utc'])).total_seconds()
        for n in range(len(starts)-1)]
    require(all(x >= 60 for x in gaps), 'Original sixty-second feed spacing failed')
    # A later feed change cannot borrow an older ready report.
    require(readiness['feed_head_sha256'] == feed_state['head_sha256'],
        'Feed changed after the last verified active readiness report')
    events = [json.loads(line) for line in (root/'multi-process-events.jsonl').read_text().splitlines()]
    require(all(e['event'] != 'failed' for e in events), 'Synthetic role recorded a failure')
    identity = [e for e in events if e['role'] == 'identity' and e['event'] == 'quote']
    intervals = [(timestamp(b['at'])-timestamp(a['at'])).total_seconds() for a, b in zip(identity, identity[1:])]
    require(len(identity) == 40 and all(x >= 2 for x in intervals), 'Identity call count/spacing failed')
    scene = read_json(root/'multi-scene.json')
    logical = timestamp(scene['logical_anchor'])
    boundary = logical.replace(minute=5, second=0)
    journal = Path(config.collector.journal_path)
    with closing(sqlite3.connect(journal.as_uri()+'?mode=ro', uri=True)) as db:
        db.execute('BEGIN')
        maximum, full = db.execute('SELECT max(requested_symbol_count), sum(requested_symbol_count=40) '
            'FROM quote_acquisition WHERE channel="hot"').fetchone()
        errors = db.execute('SELECT count(*) FROM quote_observation o JOIN quote_acquisition h '
            'ON h.acquisition_id=o.acquisition_id WHERE h.channel="hot" AND o.status!="quote"').fetchone()[0]
        before = db.execute('SELECT count(*) FROM quote_acquisition WHERE channel="hot" AND requested_symbol_count=40 '
            'AND scheduled_at_utc<?', (_utc_text(boundary, 'fixture'),)).fetchone()[0]
        after = db.execute('SELECT count(*) FROM quote_acquisition WHERE channel="hot" AND requested_symbol_count=40 '
            'AND scheduled_at_utc>=?', (_utc_text(boundary, 'fixture'),)).fetchone()[0]
        background = {channel: db.execute('SELECT count(*) FROM quote_acquisition WHERE run_id=?',
            ('concurrent-'+channel,)).fetchone()[0] for channel in ('uni', 'focus')}
    require(maximum == 40 and full >= 2 and errors == 0 and before >= 2 and after >= 2,
        'Full-roster native collection/period boundary assertions failed')
    require(len(list(journal.parent.glob('*.hot.e*.poller.sqlite3'))) >= 2 and
        all(n > 0 for n in background.values()), 'Period/concurrent writer evidence absent')
    audit = audit_quote_journal(journal, audited_at=clock())
    require(audit.passed, 'Retained native coverage audit failed')
    report_path = Path(owner['reporting']['report_path'])
    require(report_path.resolve().is_relative_to(state/'reports'), 'Original native report path differs')
    report = unseal(read_json(report_path))
    require(report['configuration_sha256'] == digest(raw) and
        report['invocation'] == driver['active_invocation'] and report['audited_at_utc'] == stopped and
        report['validation_passed'] is True and report['hot_content_integrity']['passed'] is True and
        report['first_replay'] == report['second_replay'] == owner['reporting']['first_replay'],
        'Original native final report binding/integrity differs')
    from mb_watchlist_coordinator.daily_epoch_integrity import verify_journal_content, replay_sequence_digest, verified_period_digest
    from mb_watchlist_coordinator.daily_epoch_collector import make_daily_collector
    verifier = make_daily_collector(config.collector, publication_session=view,
        client_factory=forbidden, clock=clock, activation_approved=True)
    def unfinished(index):
        active = verifier._make(next(w for w in verifier.windows if w[0] == index))
        try:
            snapshot = active.poller.verified_shutdown_snapshot()
            require(snapshot['pending'] is None, 'Unacknowledged native period outcome')
            return verified_period_digest(active.poller)
        finally:
            active.close()
    try:
        integrity = verify_journal_content(journal, expected_settings=config.collector.payload(), unfinished_validator=unfinished)
    finally:
        verifier.close()
    require(integrity['passed'] is True and integrity == report['hot_content_integrity'],
        'Retained Hot stored values differ from verified final report')
    require(replay_sequence_digest(journal) == report['first_replay'], 'Retained native event order changed')
    return {'contract': 'closed-multisymbol-owned-reassessment-v1', 'result': 'PASS',
        'source_readiness_before_stop': readiness, 'source_event_head_sha256': source_head,
        'source_attempts': len(starts), 'source_intervals_seconds': gaps,
        'identity_calls': len(identity), 'minimum_identity_interval_seconds': min(intervals),
        'hot_symbols': 40, 'full_roster_hot_acquisitions': full,
        'full_roster_acquisitions_before_rollover': before, 'full_roster_acquisitions_after_rollover': after,
        'background_acquisitions': background, 'worker_starts': 1,
        'native_audit_passed': True, 'hot_content_integrity': integrity,
        'first_replay': report['first_replay'], 'owner': owner,
        'qualification_clock': 'retained original owner Stop cutoff; no live clock changed',
        'original_run_written': False, 'processes_started': 0, 'provider_calls': 0,
        'full_day_capacity_qualified': False, 'production_changes': False}
