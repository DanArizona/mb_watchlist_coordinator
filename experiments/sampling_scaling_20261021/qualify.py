"""Offline old/new replay and publication-cycle comparison; no provider access."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import socket
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
BASELINE_COMMIT = '0417b345e2725f4e1e184d3b3202bedb846dbfca'
MARKET = ROOT / 'experiments/sampling_promotion_20261016/market_data/src'
TESTS = ('test_sampling_scaling', 'test_sampling_requests', 'test_sampling_policy',
         'test_sampling_admission', 'test_sampling_service', 'test_nasdaq_sampling')


def verify_inventory():
    path = ROOT / 'SCALING_SOURCE_INVENTORY.json'
    if not path.is_file():
        return  # Source-tree invocation; delivered bundles always include it.
    inventory = json.loads(path.read_text())
    for name, expected in inventory['files'].items():
        source = ROOT / name
        if not source.resolve().is_relative_to(ROOT.resolve()) or source.is_symlink():
            raise ValueError('Source inventory path escape')
        if hashlib.sha256(source.read_bytes()).hexdigest() != expected:
            raise ValueError('Bundled qualification source differs: ' + name)


def deny_network():
    def denied(*args, **kwargs):
        raise RuntimeError('Network is disabled in Coordinator scaling qualification')
    socket.socket.connect = socket.socket.connect_ex = denied
    socket.create_connection = socket.getaddrinfo = denied


def fixture(path):
    from mb_watchlist_coordinator.models import IntentType, ProducerIntent
    from mb_watchlist_coordinator.sampling_projection import SamplingMembership
    from mb_watchlist_coordinator.sampling_policy import SamplingPolicy
    from mb_watchlist_coordinator.sampling_admission import AdmissionPolicy
    from mb_watchlist_coordinator.sampling_request_store import SamplingRequestStore
    from mb_watchlist_coordinator.sampling_requests import RequestEvent, canonical, digest, utc_text
    from mb_watchlist_coordinator.session import session_expiration
    start = (datetime.now(ZoneInfo('America/New_York')) + timedelta(days=2)).replace(
        hour=10, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    close = session_expiration(start.astimezone(ZoneInfo('America/New_York')).date())
    now = [start]
    symbols = tuple(f'S{i:04d}' for i in range(532))
    baseline = SamplingMembership(frozenset(symbols[:531]), frozenset(symbols[:40]), frozenset())
    policy = SamplingPolicy('admin', 2, 4, 'immediate_cap')
    admission = AdmissionPolicy('synthetic-scaling-catalog', frozenset(symbols),
        frozenset({'manual', 'algorithm', 'nasdaq'}), 1, 'session')
    store = SamplingRequestStore(path, session_date=start.date(), baseline=baseline,
        policy=policy, admission=admission, clock=lambda: now[0])
    store.initialize()
    def request(rid, owner, requested, target):
        store.submit_request(ProducerIntent(rid, owner, IntentType.ENSURE_PRESENT,
            frozenset(requested), now[0], expires_at=close,
            metadata={'sampling_channel': target, 'session_date': start.date().isoformat()}), actor_id=owner)
    request('manual-hot', 'manual', symbols[:40], 'hot')
    now[0] = start + timedelta(seconds=1)
    request('algorithm-focus', 'algorithm', [symbols[40]], 'focus')
    now[0] = start + timedelta(seconds=2)
    request('nasdaq-hot', 'nasdaq', [symbols[531]], 'hot')
    now[0] = start + timedelta(seconds=3)
    store.restrict_symbol('cap', symbol=symbols[531], max_group='uni', actor_id='admin',
                          expires_at=start + timedelta(seconds=10))
    now[0] = start + timedelta(seconds=4)
    store.cancel_request('wrong-owner', owner_id='nasdaq', request_id='nasdaq-hot', actor_id='algorithm')
    now[0] = start + timedelta(seconds=11)
    store.tick('cap-expired')
    now[0] = start + timedelta(seconds=12)
    store.cancel_request('withdraw-algorithm', owner_id='algorithm', request_id='algorithm-focus', actor_id='algorithm')
    now[0] = start + timedelta(seconds=13)
    store.cancel_request('withdraw-nasdaq', owner_id='nasdaq', request_id='nasdaq-hot', actor_id='nasdaq')
    now[0] = start + timedelta(seconds=16)
    store.tick('demotion-boundary')
    now[0] = start + timedelta(seconds=17)
    store.cancel_request('withdraw-manual', owner_id='manual', request_id='manual-hot', actor_id='manual')
    now[0] = start + timedelta(seconds=20)
    store.tick('manual-demotion')
    events = store.events()
    assert len(events) == 11
    # Logical history extension, not elapsed market operation. The ordinary
    # native reader fully verifies every generated tick before measurement.
    inserts = []
    previous = events[-1].event_sha256
    for sequence in range(12, 302):
        at = start + timedelta(seconds=20 + sequence)
        event = RequestEvent(sequence, f'logical-tick-{sequence}', 'tick', '__coordinator__',
                             {}, at, True, None, previous, '')
        event = replace(event, event_sha256=digest(event.hash_payload()))
        previous = event.event_sha256
        inserts.append((sequence, event.command_id, event.kind, event.actor_id,
                        canonical(event.payload), utc_text(at), 1, None,
                        event.previous_sha256, event.event_sha256))
    with sqlite3.connect(path) as c:
        c.executemany('INSERT INTO request_event VALUES (?,?,?,?,?,?,?,?,?,?)', inserts)
    assert len(store.events()) == 301


def worker(source, payload):
    sys.path[:0] = [str(source), str(MARKET)]
    from mb_watchlist_coordinator import sampling_projection as projection
    from mb_watchlist_coordinator.sampling_projection import SamplingMembership
    from mb_watchlist_coordinator.sampling_policy import SamplingPolicy
    from mb_watchlist_coordinator.sampling_admission import AdmissionPolicy
    from mb_watchlist_coordinator.sampling_request_store import SamplingRequestStore
    from mb_watchlist_coordinator.sampling_requests import canonical, digest, replay_requests, plain
    from mb_watchlist_coordinator.sampling_journal import SamplingJournal
    from mb_watchlist_coordinator.sampling_service import SamplingPublicationService, PublicationSettings
    from mb_watchlist_coordinator.session import session_expiration
    from mb_market_data.quote_observation_store import QuoteObservationStore
    from mb_market_data.sampling_membership import SamplingHierarchyRevision
    records = []
    for prefix in (11, 101, 301):
        folder = Path(payload['folder']) / str(prefix)
        folder.mkdir()
        path = folder / 'requests.sqlite3'
        shutil.copyfile(payload['fixture'], path)
        with sqlite3.connect(path) as c:
            c.execute('DELETE FROM request_event WHERE sequence > ?', (prefix,))
            identity = json.loads(c.execute('SELECT payload FROM request_identity').fetchone()[0])
        baseline = SamplingMembership(**{k: frozenset(v) for k, v in identity['baseline'].items()})
        config = identity['admission']
        admission = AdmissionPolicy(config['catalog_id'], frozenset(config['catalog_symbols']),
            frozenset(config['allowed_sources']), config['max_additional_symbols'], config['uni_retention'])
        policy = SamplingPolicy(**identity['policy'])
        from datetime import date
        session = date.fromisoformat(identity['session_date'])
        store = SamplingRequestStore(path, session_date=session, baseline=baseline,
                                     policy=policy, admission=admission)
        if hasattr(projection, '_canonical_text'):
            projection._canonical_text.cache_clear()
        before = time.perf_counter()
        states = store.states()
        cold_ms = (time.perf_counter() - before) * 1000
        expected = digest([s.payload() for s in states])
        events = store.events()
        def measure(call):
            times = []
            for _ in range(payload['repeats']):
                before = time.perf_counter()
                value = call()
                times.append((time.perf_counter() - before) * 1000)
            return round(statistics.mean(times), 3), value
        read_ms, read_states = measure(store.states)
        pure_ms, pure_states = measure(lambda: replay_requests(session, baseline, events, policy=policy, admission=admission))
        assert expected == digest([s.payload() for s in read_states]) == digest([s.payload() for s in pure_states])
        now = states[-1].as_of
        store.clock = lambda: now
        journal = QuoteObservationStore(folder / 'membership.sqlite3', session_date=session, schema_version=2)
        journal.initialize()
        journal.record_membership_revision(SamplingHierarchyRevision(session_date=session, revision=0,
            effective_at=now-timedelta(seconds=1), uni_symbols=baseline.uni, focus_symbols=baseline.focus,
            hot_symbols=(), source='synthetic-scaling-proof'))
        service = SamplingPublicationService(folder / 'publication.sqlite3', request_store=store,
            journal=SamplingJournal(journal), settings=PublicationSettings('scaling-proof', 1, .5,
            session_expiration(session)), clock=lambda: now)
        service.initialize()
        service.cycle()
        cycle_ms, decision = measure(service.cycle)
        snapshot = plain(service.snapshot())
        reopened = SamplingPublicationService(service.path, request_store=store,
            journal=SamplingJournal(journal), settings=service.settings, clock=lambda: now)
        reopened.initialize()
        assert snapshot == plain(reopened.snapshot())
        latest = SamplingJournal(journal).revisions()[-1]['proposal']
        records.append({'events': prefix, 'state_digest': expected, 'cold_read_ms': round(cold_ms, 3),
            'warm_read_mean_ms': read_ms, 'pure_replay_mean_ms': pure_ms, 'idle_cycle_mean_ms': cycle_ms,
            'decision': decision, 'final_membership': {k: len(latest[k+'_symbols']) for k in ('uni','focus','hot')},
            'cold_publication_reopen_identical': True})
    return records


def main():
    deny_network()
    verify_inventory()
    parser = argparse.ArgumentParser()
    parser.add_argument('--baseline-source', type=Path, default=ROOT/'baseline_coordinator_src')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--worker-source', type=Path)
    parser.add_argument('--worker-input', type=Path)
    args = parser.parse_args()
    if args.worker_source:
        print(json.dumps(worker(args.worker_source, json.loads(args.worker_input.read_text()))))
        return 0
    if (ROOT/'SCALING_SOURCE_INVENTORY.json').is_file() and args.baseline_source.resolve() != (ROOT/'baseline_coordinator_src').resolve():
        parser.error('Delivered qualification requires its pinned bundled baseline')
    if not (args.baseline_source/'mb_watchlist_coordinator/sampling_projection.py').is_file():
        parser.error('Use the complete qualification bundle with its pinned baseline source')
    sys.path[:0] = [str(ROOT/'src'), str(MARKET), str(ROOT/'tests')]
    suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(name) for name in TESTS)
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    if not result.wasSuccessful():
        return 1
    with tempfile.TemporaryDirectory(prefix='coordinator scaling proof ') as temporary:
        folder = Path(temporary)
        database = folder/'fixture.sqlite3'
        fixture(database)
        records = {}
        for label, source in [('baseline', args.baseline_source), ('optimized', ROOT/'src')]:
            work = folder/label
            work.mkdir()
            payload = work/'input.json'
            payload.write_text(json.dumps({'fixture': str(database), 'folder': str(work), 'repeats': 5}))
            command = [sys.executable, '-I', '-B', str(Path(__file__).resolve()), '--worker-source', str(source),
                       '--worker-input', str(payload)]
            child = subprocess.run(command, capture_output=True, text=True, timeout=120)
            if child.returncode:
                raise RuntimeError(child.stderr[-4000:])
            records[label] = json.loads(child.stdout)
        for old, new in zip(records['baseline'], records['optimized']):
            assert old['events'] == new['events']
            assert old['state_digest'] == new['state_digest']
            assert old['decision'] == new['decision']
            assert old['final_membership'] == new['final_membership']
        report = {'result': 'PASS', 'source': 'synthetic_only', 'network': 'denied', 'tests': result.testsRun,
            'baseline_commit': BASELINE_COMMIT, 'benchmarks': records, 'replay_and_decisions_identical': True,
            'scope': 'Logical 531-member history sizes, five measured calls per size; not elapsed market/full-day capacity.',
            'integrity': 'Every history read still fully validates; bounded cache stores only short built-in string predicates.',
            'remaining': 'Full history is still replayed; history growth and real-provider production qualification remain pending.'}
        output = args.output or (ROOT/'runs/scaling_qualification'/
            (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8])/'report.json')
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2)+'\n')
        print(json.dumps(report, indent=2))
        print('Saved report: ' + str(output))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
