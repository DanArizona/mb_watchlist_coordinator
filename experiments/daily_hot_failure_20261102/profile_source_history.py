"""Offline source-ledger growth profile; no feed transport or live provider.

Retains repeated synthetic CURRENT receipts and eleven authorized symbols in
the real publication/identity/request ledgers. The collector's publication
reader compares the persisted graph after each new receipt. Logical spacing
does not qualify real feed pacing or Windows/provider capacity.
"""
import argparse
import cProfile
from datetime import timedelta
import io
import json
from pathlib import Path
import pstats
import socket
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tests'))
from test_daily_multisymbol import MultiFixture, SYMBOLS
from mb_watchlist_coordinator.daily_worker_view import DailyPublicationReader


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--captures', type=int, default=90)
    parser.add_argument('--rows-per-capture', type=int, default=11)
    parser.add_argument('--at-open', action='store_true')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.captures <= 390:
        parser.error('Use 1 through 390 synthetic source receipts')
    if not 11 <= args.rows_per_capture <= len(SYMBOLS):
        parser.error('Use 11 through 150 source rows per synthetic capture')
    if args.output.exists():
        parser.error('Preserve the prior report; choose a new output path')

    def denied(*args, **kwargs):
        raise OSError('Network denied in offline source-history profile')

    socket.socket.connect = socket.socket.connect_ex = socket.create_connection = socket.getaddrinfo = denied
    fixture = MultiFixture(background=True, at_open=args.at_open)
    case, session = fixture.case, fixture.session
    checkpoints = sorted({1, 10, 30, 60, args.captures} & set(range(1, args.captures+1)))
    began = time.perf_counter()
    observations = []
    try:
        session.live.record_snapshot(case.snapshot('CURRENT', (), 'current-000'))
        if args.at_open:
            # The synthetic halt rows precede their recovery receipt. This is
            # a logical fixture clock only; no live clock override exists.
            fixture.advance(15)
        fixture.queue(SYMBOLS[:11])
        for _ in range(11):
            fixture.pump()
            fixture.advance(2)
        fixture.advance(12)
        session.service.cycle()
        reader = DailyPublicationReader(case.settings, case.root / 'catalog',
            binding=session.binding, claim=session.claim,
            publication_binding=session.service.identity, clock=lambda:case.now,
            fence=lambda:None)
        rows = [case.row(s, seconds=n % 50) for n, s in enumerate(SYMBOLS[:args.rows_per_capture])]
        for number in range(1, args.captures+1):
            case.now += timedelta(seconds=60)
            started = time.perf_counter()
            session.live.record_snapshot(case.snapshot('CURRENT', rows, f'current-{number:03}'))
            append_seconds = time.perf_counter() - started
            started = time.perf_counter()
            verified = reader.validate(with_state=True)
            fresh_seconds = time.perf_counter() - started
            started = time.perf_counter()
            second = reader.validate(with_state=True)
            warm_seconds = time.perf_counter() - started
            assert verified == second
            assert tuple(verified[1]['identity_gate']['authorized_symbols']) == tuple(SYMBOLS[:11])
            if number in checkpoints:
                item = {'retained_current_captures': number+1,
                    'append_seconds': append_seconds,
                    'first_collector_publication_read_seconds': fresh_seconds,
                    'unchanged_collector_publication_read_seconds': warm_seconds}
                observations.append(item)
                print(json.dumps(item), flush=True)
        # Collect call attribution separately: profiler overhead must not be
        # included in the uninstrumented duration samples above. Invalidating
        # only this derived gate cache repeats the same full replay path; it
        # changes no persisted evidence or validation rule.
        reader.gate._validated_read = None
        profile = cProfile.Profile()
        profile.runcall(reader.validate, with_state=True)
        stream = io.StringIO()
        pstats.Stats(profile, stream=stream).sort_stats('cumulative').print_stats(30)
        from mb_watchlist_coordinator.nasdaq_sampling import _event_time_value, _event_identity_value
        _event_time_value.cache_clear()
        _event_identity_value.cache_clear()
        started = time.perf_counter()
        cold = DailyPublicationReader(case.settings, case.root / 'catalog',
            binding=session.binding, claim=session.claim,
            publication_binding=session.service.identity, clock=lambda:case.now,
            fence=lambda:None)
        fresh_reader_seconds = time.perf_counter()-started
        assert cold.validate(with_state=True) == verified
        report = {'contract':'source-history-growth-offline-profile-v1',
            'result':'PROFILE_COMPLETED', 'captures_added':args.captures,
            'rows_per_capture':args.rows_per_capture,
            'logical_final_at_utc':case.now.isoformat(),
            'logical_at_open':args.at_open,
            'authorized_symbols':11, 'identity_quote_permits':len(case.calls),
            'opening_uni_symbols':600, 'opening_focus_symbols':40,
            'elapsed_seconds':time.perf_counter()-began,
            'measurements':observations, 'last_changed_read_profile':stream.getvalue(),
            'profile_scope':'Separate full gate replay after clearing its derived in-memory cache; duration samples above are not profiled',
            'fresh_publication_reader_initialization_seconds':fresh_reader_seconds,
            'fresh_reader_includes_cleared_pure_timestamp_identity_caches':True,
            'scope':'Actual persisted source/request/publication reader; synthetic receipts and logical 60-second spacing; Linux microprofile',
            'feed_transport_or_owned_process_qualified':False,
            'original_windows_delay_cause_proven':False,
            'runtime_fix_applied':False, 'actual_provider_used':False,
            'actual_vault_access':False, 'network':'denied',
            'frozen_p85_modified':False,'production_changes':False}
        with args.output.open('x',encoding='utf-8') as out:
            json.dump(report,out,indent=2)
            out.write('\n')
        print(json.dumps({'result':report['result'],'elapsed_seconds':report['elapsed_seconds']}),flush=True)
    finally:
        fixture.close()


if __name__ == '__main__':
    main()
