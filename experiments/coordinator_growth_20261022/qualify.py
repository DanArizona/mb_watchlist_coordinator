"""Native rich-history construction and bounded offline measurement.

This first increment measures idle/read/cold-reopen costs. State-changing real
clock, burst and memory-soak gates remain explicitly NOT_RUN. No provider I/O.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import closing
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import socket
import sqlite3
import statistics
import subprocess
import sys
import time
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'experiments/sampling_promotion_20261016/market_data/src')]

from mb_market_data.quote_observation_store import QuoteObservationStore
from mb_market_data.sampling_membership import SamplingHierarchyRevision
from mb_watchlist_coordinator.models import IntentType, ProducerIntent
from mb_watchlist_coordinator.sampling_admission import AdmissionPolicy
from mb_watchlist_coordinator.sampling_journal import SamplingJournal
from mb_watchlist_coordinator.sampling_policy import SamplingPolicy
from mb_watchlist_coordinator.sampling_projection import SamplingMembership
from mb_watchlist_coordinator.sampling_request_store import RequestConflictError, SamplingRequestStore
from mb_watchlist_coordinator.sampling_requests import digest, plain, timestamp, utc_text
from mb_watchlist_coordinator.sampling_service import PublicationSettings, SamplingPublicationService

REFERENCE_RUNTIME = '192eeb516c5011cd404313197e5e95e3ee05a79b'
SESSION = date(2026, 11, 2)  # fixed future synthetic date, not a market-calendar assertion
START = datetime(2026, 11, 2, 9, 30, tzinfo=ZoneInfo('America/New_York')).astimezone(timezone.utc)
STOP = START + timedelta(minutes=390)
UNI = tuple(f'S{i:04d}' for i in range(543))
EXTRA = tuple(f'X{i:04d}' for i in range(64))
BASELINE = SamplingMembership(frozenset(UNI), frozenset(UNI[:40]), frozenset())


def deny_network():
    def denied(*args, **kwargs):
        raise RuntimeError('Network denied in Coordinator growth qualification')
    socket.socket.connect = socket.socket.connect_ex = denied
    socket.create_connection = socket.getaddrinfo = denied


def dump(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    temporary.replace(path)


def open_fixture(folder, now):
    folder = Path(folder)
    requests = SamplingRequestStore(folder / 'requests.sqlite3', session_date=SESSION,
        baseline=BASELINE, policy=SamplingPolicy('admin', 2, 4, 'immediate_cap'),
        admission=AdmissionPolicy('growth-synthetic-v1', frozenset(UNI + EXTRA),
            frozenset({'manual', 'algorithm', 'nasdaq'}), 64, 'session'), clock=lambda: now[0])
    journal = QuoteObservationStore(folder / 'membership.sqlite3', session_date=SESSION, schema_version=2)
    service = SamplingPublicationService(folder / 'publication.sqlite3', request_store=requests,
        journal=SamplingJournal(journal), settings=PublicationSettings('growth-proof', 1, .5, STOP),
        clock=lambda: now[0])
    return requests, journal, service


def intent(rid, owner, symbols, at, *, target='hot', effective=None, expiry=STOP):
    return ProducerIntent(rid, owner, IntentType.ENSURE_PRESENT, frozenset(symbols), at,
        effective_from=effective, expires_at=expiry,
        metadata={'sampling_channel': target, 'session_date': SESSION.isoformat()})


def files_digest(folder):
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(Path(folder).glob('*.sqlite3'))}


def build_fixture(folder, *, rounds=50, budget_seconds=3600, progress=None):
    """Exactly 20 durable receipts and four real membership changes per round.

    Every receipt and publication uses the native API. Logical time advances
    over a session; periods between checkpoints are not elapsed service runs.
    """
    if type(rounds) is not int or not 1 <= rounds <= 50:
        raise ValueError('This first profile supports 1..50 rounds only')
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=False)
    now = [START]
    requests, journal, service = open_fixture(folder, now)
    requests.initialize(); journal.initialize()
    journal.record_membership_revision(SamplingHierarchyRevision(session_date=SESSION,
        revision=0, effective_at=START - timedelta(seconds=1), uni_symbols=UNI,
        focus_symbols=UNI[:40], hot_symbols=(), source='growth-fixture-anchor',
        metadata={'synthetic_only': True, 'logical_clock': True}))
    service.initialize()
    begin = time.perf_counter()
    expected = []
    transport = Counter()
    receipt_dispositions = Counter()
    timing = []
    additions = set()

    def record(call, *, accepted=True):
        before = time.perf_counter()
        value = call()
        timing.append(time.perf_counter() - before)
        if not value.inserted or value.event.accepted is not accepted:
            raise AssertionError('Unexpected native receipt disposition')
        transport['inserted'] += 1
        receipt_dispositions[value.event.rejection_reason or 'accepted'] += 1
        return value

    def request(rid, owner, symbols, **kw):
        value = intent(rid, owner, symbols, now[0], **kw)
        record(lambda: requests.submit_request(value, actor_id=owner))
        return value

    def publish(hot, focus):
        decision = service.cycle()
        if decision['status'] != 'published':
            raise AssertionError('Expected changed native publication: ' + repr(decision))
        value = journal.membership_revisions_in_effective_order()[-1]
        wanted = {'uni': sorted(set(UNI) | additions), 'focus': sorted(focus), 'hot': sorted(hot)}
        actual = {k: list(getattr(value, k + '_symbols')) for k in wanted}
        if actual != wanted or value.revision != len(expected) + 1:
            raise AssertionError('Hand-specified hierarchy checkpoint differs')
        expected.append({'revision': value.revision, 'membership': wanted})

    for n in range(rounds):
        if time.perf_counter() - begin > budget_seconds:
            raise TimeoutError('Native fixture construction exceeded declared budget')
        base = START + timedelta(seconds=n * 468)
        outside, focus = EXTRA[n], UNI[40 + n % 40]
        rid = lambda name: f'r{n:02d}-{name}'
        def at(seconds):
            now[0] = base + timedelta(seconds=seconds)
        at(0); primary = request(rid('manual'), 'manual', UNI[:40])
        at(1); request(rid('focus'), 'algorithm', [focus], target='focus')
        at(2); record(lambda: requests.cancel_request(rid('wrong-cancel'), owner_id='manual',
            request_id=rid('manual'), actor_id='algorithm'), accepted=False)
        at(3); bad = intent(rid('unknown'), 'manual', ['UNKNOWN'], now[0])
        record(lambda: requests.submit_request(bad, actor_id='manual'), accepted=False)
        at(4); record(lambda: requests.restrict_symbol(rid('wrong-cap'), symbol=UNI[0],
            max_group='uni', actor_id='algorithm'), accepted=False)
        publish(UNI[:40], set(UNI[:40]) | {focus})

        # Identical transport retry and conflicting ID do not invent receipts.
        result = requests.submit_request(primary, actor_id='manual')
        if result.inserted:
            raise AssertionError('Retry inserted another request')
        transport['already_recorded'] += 1
        try:
            requests.submit_request(replace(primary, symbols=frozenset({UNI[41]})), actor_id='manual')
        except RequestConflictError:
            transport['conflicting_id'] += 1
        else:
            raise AssertionError('Conflicting transport reuse was accepted')

        at(60); request(rid('outside'), 'nasdaq', [outside]); additions.add(outside)
        at(61); request(rid('outside-overlap'), 'algorithm', [outside])
        at(62); request(rid('future'), 'manual', [UNI[0]],
            effective=base + timedelta(seconds=100), expiry=base + timedelta(seconds=110))
        at(63); record(lambda: requests.cancel_request(rid('wrong-nasdaq'), owner_id='nasdaq',
            request_id=rid('outside'), actor_id='manual'), accepted=False)
        at(64); expired = intent(rid('expired'), 'manual', [UNI[0]], base,
            expiry=base + timedelta(seconds=1))
        record(lambda: requests.submit_request(expired, actor_id='manual'), accepted=False)
        publish(set(UNI[:40]) | {outside}, set(UNI[:40]) | {focus, outside})

        at(120); record(lambda: requests.restrict_symbol(rid('cap'), symbol=outside,
            max_group='uni', actor_id='admin', expires_at=base + timedelta(seconds=170)))
        at(121); record(lambda: requests.cancel_request(rid('withdraw-nasdaq'), owner_id='nasdaq',
            request_id=rid('outside'), actor_id='nasdaq'))
        at(122); request(rid('inside-overlap'), 'algorithm', UNI[:40])
        at(123); record(lambda: requests.clear_restriction(rid('wrong-clear'), symbol=outside,
            restriction_id=rid('cap'), actor_id='algorithm'), accepted=False)
        at(124); request(rid('harmless'), 'algorithm', [UNI[1]], target='focus',
            expiry=base + timedelta(seconds=150))
        publish(UNI[:40], set(UNI[:40]) | {focus})

        at(180); record(lambda: requests.cancel_request(rid('withdraw-manual'), owner_id='manual',
            request_id=rid('manual'), actor_id='manual'))
        at(181); record(lambda: requests.cancel_request(rid('withdraw-outside-overlap'), owner_id='algorithm',
            request_id=rid('outside-overlap'), actor_id='algorithm'))
        at(182); record(lambda: requests.cancel_request(rid('withdraw-inside-overlap'), owner_id='algorithm',
            request_id=rid('inside-overlap'), actor_id='algorithm'))
        at(183); record(lambda: requests.cancel_request(rid('withdraw-focus'), owner_id='algorithm',
            request_id=rid('focus'), actor_id='algorithm'))
        now[0] = STOP - timedelta(seconds=1) if n == rounds - 1 else base + timedelta(seconds=190)
        record(lambda: requests.tick(rid('timers')))
        publish((), UNI[:40])
        if progress:
            progress({'round': n + 1, 'receipts': 20 * (n + 1), 'publications': 4 * (n + 1),
                      'elapsed_seconds': round(time.perf_counter() - begin, 3)})

    events, states = requests.validated_history()
    snapshot = plain(service.snapshot())
    assert len(events) == rounds * 20
    assert len(snapshot['journal']) == rounds * 4 + 1
    assert Counter(e.kind for e in events)['tick'] == rounds
    assert not snapshot['pending'] and not snapshot['unacknowledged']
    metadata = {'contract': 'coordinator-rich-history-fixture-v1', 'reference_runtime': REFERENCE_RUNTIME,
        'synthetic_only': True, 'clock': 'logical_session', 'seed': 0, 'rounds': rounds,
        'session': SESSION.isoformat(), 'final_clock_utc': utc_text(now[0]),
        'receipts': len(events), 'publications': len(expected), 'quote_acquisitions': 0,
        'receipt_kinds': dict(Counter(e.kind for e in events)), 'receipt_dispositions': dict(receipt_dispositions),
        'transport_submissions': dict(transport), 'construction_seconds': time.perf_counter() - begin,
        'construction_submission_seconds': stats(timing),
        'request_states_sha256': digest([s.payload() for s in states]),
        'publication_snapshot_sha256': digest(snapshot), 'expected_checkpoints': expected,
        'active_requests_high_water': max(len(s.active_requests) for s in states),
        'files_sha256': files_digest(folder)}
    dump(folder / 'fixture.json', metadata)
    return metadata


def stats(values):
    values = sorted(values)
    if not values:
        return {'count': 0}
    return {'count': len(values), 'median': statistics.median(values),
        'p95': values[max(0, math.ceil(.95 * len(values)) - 1)], 'maximum': values[-1]}


def measure(folder, repeats):
    metadata = json.loads((Path(folder) / 'fixture.json').read_text())
    before_hashes = files_digest(folder)
    if before_hashes != metadata['files_sha256']:
        raise ValueError('Fixture database bytes changed before measurement')
    now = [timestamp(metadata['final_clock_utc'])]
    requests, journal, service = open_fixture(folder, now)
    times, cpu = [], []
    for _ in range(repeats):
        start, start_cpu = time.perf_counter(), time.process_time()
        result = service.cycle()
        times.append(time.perf_counter() - start); cpu.append(time.process_time() - start_cpu)
        if result['status'] != 'idle' or result['processed_sequence'] != metadata['receipts']:
            raise AssertionError('Measured cycle mutated or did not consume the expected prefix')
    if digest(plain(service.snapshot())) != metadata['publication_snapshot_sha256']:
        raise AssertionError('Publication replay differs after measurement')
    if digest([s.payload() for s in requests.states()]) != metadata['request_states_sha256']:
        raise AssertionError('Complete request states differ after measurement')
    if files_digest(folder) != before_hashes:
        raise AssertionError('Idle measurement changed the fixture bytes')
    elapsed = stats(times)
    return {'idle_cycle_seconds': elapsed, 'idle_cycle_cpu_seconds': stats(cpu),
        'gate': 'PASS' if elapsed['p95'] <= .5 and elapsed['maximum'] <= 1 else 'FAILED',
        'complete_replay_identical': True, 'fixture_bytes_unchanged': True}


def cold_reopen(folder):
    metadata = json.loads((Path(folder) / 'fixture.json').read_text())
    before = files_digest(folder)
    if before != metadata['files_sha256']:
        raise ValueError('Cold fixture bytes differ')
    start = time.perf_counter()
    now = [timestamp(metadata['final_clock_utc'])]
    requests, journal, service = open_fixture(folder, now)
    # snapshot() requires pre-existing state; initialize() could create missing files.
    snapshot = plain(service.snapshot())
    elapsed = time.perf_counter() - start
    if digest(snapshot) != metadata['publication_snapshot_sha256'] or files_digest(folder) != before:
        raise AssertionError('Cold snapshot or original bytes differ')
    return {'seconds': elapsed, 'gate': 'PASS' if elapsed <= 10 else 'FAILED',
            'snapshot_identical': True, 'fixture_bytes_unchanged': True}


def main():
    deny_network()
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path)
    parser.add_argument('--rounds', type=int, default=50)
    parser.add_argument('--repeats', type=int, default=100)
    parser.add_argument('--worker', choices=('measure', 'cold'))
    parser.add_argument('--fixture', type=Path)
    args = parser.parse_args()
    if args.worker:
        result = cold_reopen(args.fixture) if args.worker == 'cold' else measure(args.fixture, args.repeats)
        print(json.dumps(result)); return 0
    if args.output is None or args.repeats < 1:
        parser.error('--output and positive --repeats are required')
    args.output.mkdir(parents=True, exist_ok=False)
    report = {'contract': 'coordinator-rich-growth-report-v1', 'status': 'RUNNING',
        'source': 'synthetic_only', 'network': 'denied', 'reference_runtime': REFERENCE_RUNTIME,
        'platform': platform.platform(), 'python': sys.version, 'pid': os.getpid(),
        'scope': 'Native logical fixture plus elapsed idle/cold measurement; not full qualification.',
        'not_run': ['real_clock_state_changing', 'burst', 'ten_minute_memory',
                    'growth_axis_isolation', 'busy_and_stress', 'recovery_fault_matrix', 'Windows', 'provider']}
    dump(args.output / 'report.json', report)
    try:
        fixture = args.output / 'fixture'
        metadata = build_fixture(fixture, rounds=args.rounds,
            progress=lambda value: (dump(args.output / 'progress.json', value), print(json.dumps(value), flush=True)))
        report['fixture'] = {k: v for k, v in metadata.items() if k != 'expected_checkpoints'}
        dump(args.output / 'report.json', report)
        results = []
        for worker in ['measure', 'cold', 'cold', 'cold']:
            command = [sys.executable, '-I', '-B', str(Path(__file__).resolve()), '--worker', worker,
                       '--fixture', str(fixture.resolve()), '--repeats', str(args.repeats)]
            child = subprocess.run(command, text=True, capture_output=True, timeout=600)
            if child.returncode:
                raise RuntimeError(child.stderr[-5000:])
            results.append(json.loads(child.stdout))
        report.update(status='MEASURED', correctness='PASS', idle=results[0], cold_reopens=results[1:],
            performance='PASS' if all(r['gate'] == 'PASS' for r in results) else 'FAILED',
            qualification='INCOMPLETE')
    except BaseException as exc:
        report.update(status='INTERRUPTED' if isinstance(exc, KeyboardInterrupt) else 'FAILED',
                      error_type=type(exc).__name__, error=str(exc), qualification='INCOMPLETE')
        dump(args.output / 'report.json', report)
        raise
    dump(args.output / 'report.json', report)
    print(json.dumps({k: v for k, v in report.items() if k != 'fixture'}, indent=2))
    return 0 if report['performance'] == 'PASS' else 2


if __name__ == '__main__':
    raise SystemExit(main())
