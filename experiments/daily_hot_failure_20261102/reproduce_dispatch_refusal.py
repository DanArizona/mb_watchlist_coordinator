"""Reproduce the last pre-provider gate and tick classification offline.

Uses the actual batch normalizer, DailyHotCollector.quotes and collector tick.
Publication/ledger preparation is a trusted synthetic seam, not a new native,
ownership, authentication, timing-capacity or Windows qualification. No live
credential or provider mode exists. The logical clock advances explicitly;
these are boundary tests, not elapsed-time or production-jitter measurements.
"""
import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import socket
from types import SimpleNamespace

from mb_market_data.polling_cadence import RESERVED_HOT_SECONDS
from mb_market_data.sampling_acquisition import AcquisitionSettings, ExplicitPollSlot
from mb_market_data.sampling_membership import SamplingChannel
from mb_market_data.schwab_quotes import fetch_quotes_batched
from mb_market_data.watchlist_polling import PollWindow
from mb_watchlist_coordinator.daily_collector import DailyHotCollector


def denied(*args, **kwargs):
    raise OSError('Network denied in offline last-gate reproduction')


def scenario(name, *, local_check_milliseconds=0, symbols=11, charged_calls=56):
    scheduled = datetime(2026, 11, 2, 15, 57, 18, tzinfo=timezone.utc)
    moment = [scheduled+timedelta(microseconds=748125)]
    clock = lambda: moment[0]
    roster = [f'X{i:03}' for i in range(symbols)]
    state = {'pending': {'dispatch': {'revision': 12, 'symbols': roster,
        'scheduled_at_utc': scheduled.isoformat(),
        'dispatched_at_utc': (scheduled+timedelta(microseconds=655506)).isoformat()}},
        'events': [{'kind': 'dispatch', 'symbols': roster} for _ in range(charged_calls)]}
    verified = ({'journal': [{'proposal': {'revision': 12, 'hot_symbols': roster}}]},
        {'authorized_symbols': roster})
    settings = SimpleNamespace(max_quote_calls=120, max_symbols=40,
        start_at_utc=scheduled.replace(minute=55, second=0).isoformat(),
        stop_at_utc=scheduled.replace(hour=16, minute=0, second=0).isoformat(),
        daily_binding={'settings': {'policy_profile': 'multi-40-v1'}})
    acquisition = AcquisitionSettings(SamplingChannel.HOT, RESERVED_HOT_SECONDS,
        PollWindow(datetime.fromisoformat(settings.start_at_utc),
            datetime.fromisoformat(settings.stop_at_utc)),
        400, 'all', 'daily-native-hot-v1', .75, .05)
    collector = object.__new__(DailyHotCollector)
    collector.settings, collector.clock = settings, clock
    collector.next = ExplicitPollSlot(SamplingChannel.HOT, scheduled, RESERVED_HOT_SECONDS)
    collector.refused_call = False
    collector._native_publication_state = verified
    activity = {'inside_sample': False, 'provider_calls': 0, 'result': None,
        'callback_entered_at_lateness_milliseconds': None}

    def check(*, publication=True):
        if activity['inside_sample']:
            activity['callback_entered_at_lateness_milliseconds'] = (
                clock()-scheduled).total_seconds()*1000
            moment[0] += timedelta(milliseconds=local_check_milliseconds)
        return verified
    collector._check = check

    class SyntheticClient:
        halt_reason = None
        def quotes(self, symbols, *, fields):
            assert fields == 'all'
            activity['provider_calls'] += 1
            return SimpleNamespace(status_code=200, ok=True, text='',
                json=lambda: {s: {'symbol': s, 'assetMainType': 'EQUITY',
                    'assetSubType': 'COE', 'quote': {'lastPrice': 12.0}} for s in symbols})
    collector.client = SyntheticClient()

    def sample(slot, **kwargs):
        activity['inside_sample'] = True
        try:
            result = fetch_quotes_batched(collector, roster, fields='all', batch_size=400)
            activity['result'] = result
            return {'status': 'acquired', 'slot_id': slot.slot_id}
        finally:
            activity['inside_sample'] = False
    collector.poller = SimpleNamespace(settings=acquisition, sample=sample,
        provider_dispatch_state=lambda: state)
    outcome = collector.tick()
    result = activity['result']
    return {'scenario': name, 'synthetic_symbols': symbols,
        'local_check_clock_advance_milliseconds': local_check_milliseconds,
        'callback_entered_at_lateness_milliseconds': activity['callback_entered_at_lateness_milliseconds'],
        'clock_after_check_lateness_milliseconds': (clock()-scheduled).total_seconds()*1000,
        'batch_attempt_counter': result.request_count,
        'synthetic_provider_calls': activity['provider_calls'],
        'observation_status_counts': dict(Counter(r.status.value for r in result.results)),
        'details': sorted({r.detail for r in result.results if r.detail is not None}),
        'refused_call_latched': collector.refused_call,
        'collector_tick_status': outcome['status'], 'collector_tick_reason': outcome.get('reason')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    socket.socket.connect = socket.socket.connect_ex = socket.create_connection = socket.getaddrinfo = denied
    normal = scenario('still_before_750ms')
    crossed = scenario('three_ms_local_check_crosses_750ms', local_check_milliseconds=3)
    roster = scenario('real_symbol_limit_violation', symbols=41)
    budget = scenario('real_call_limit_violation', charged_calls=121)
    assert normal['collector_tick_status'] == 'acquired' and normal['synthetic_provider_calls'] == 1
    assert normal['observation_status_counts'] == {'quote': 11}
    assert crossed['collector_tick_status'] == 'blocked' and crossed['synthetic_provider_calls'] == 0
    assert crossed['observation_status_counts'] == {'request_error': 11}
    assert crossed['details'] == ['ValueError: Collector call budget, roster, slot or window gate refused']
    assert roster['collector_tick_status'] == budget['collector_tick_status'] == 'blocked'
    assert roster['synthetic_provider_calls'] == budget['synthetic_provider_calls'] == 0
    report = {'contract': 'hot-final-dispatch-gate-offline-reproduction-v1',
        'result': 'PASS_REPRODUCTION_OF_EXISTING_BEHAVIOR', 'cases': [normal, crossed, roster, budget],
        'scope': 'Actual quote callback, normalization and collector tick; synthetic prepared publication/ledger seam',
        'demonstrated': 'A local deadline crossing after entry at 748.125ms can produce one refused batch, 11 request_error observations, and blocked tick with no provider call',
        'actual_windows_failing_predicate_independently_measured': False,
        'cause_of_original_extra_local_delay_proven': False,
        'root_cause_of_28_earlier_missing_slots_proven': False,
        'actual_vault_access': False, 'actual_provider_used': False,
        'network': 'denied', 'production_changes': False,
        'frozen_p85_modified': False, 'runtime_fix_applied': False,
        'deadlines_relaxed': False}
    if args.output:
        with args.output.open('x', encoding='utf-8') as out:
            json.dump(report, out, indent=2); out.write('\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__': main()
