"""Reproduce an unrecorded scheduled slot after a slow prior native cycle.

Uses the original native collector and a synthetic tail-window publication
fixture. A logical clock advance after a synthetic response models a slow
completed cycle; it does not measure or identify Windows production delay.
No production path, credential, provider, runtime edit or deadline change.
"""
import argparse
from datetime import timedelta
import json
from pathlib import Path
import socket
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tests'))
from test_daily_collector import DailyCollectorTests
from mb_market_data.quote_journal_audit import audit_quote_journal
from mb_market_data.quote_journal_replay import QuoteJournalReplayReader


def scenario(delay_seconds):
    case = DailyCollectorTests('test_tail_window_idle_then_three_hot_quotes_native_audit_and_replays')
    case.setUp()
    try:
        collector = case.collector
        collector.prepare(create=True)
        case.tick(52)
        case.admit()

        def advance(stage):
            if stage == 'after_response':
                case.case.now += timedelta(seconds=delay_seconds)

        first = case.tick(54, fault_hook=advance)
        next_second = collector.next.scheduled_at.second
        if next_second == 56:
            case.tick(56)
        case.tick(58)
        state = collector.poller.snapshot()
        audit = audit_quote_journal(case.case.journal,
            audited_at=case.case.now.replace(hour=16, minute=0, second=0))
        hot = next(c for c in audit.channels if c.channel == 'hot')
        missing = list(hot.missing_slot_ids)
        ledger = [{'kind': e['kind'], 'slot_id': e.get('slot_id'),
            'recorded_at_utc': e['recorded_at_utc']} for e in state['events']]
        first_replay = tuple(QuoteJournalReplayReader(case.case.journal).events())
        equal_replays = first_replay == tuple(QuoteJournalReplayReader(case.case.journal).events())
        assert first['status'] == 'acquired'
        assert equal_replays
        if delay_seconds:
            assert next_second == 58 and len(missing) == 1
            assert missing[0].endswith('15:59:56-05:00')
            assert not any(e['slot_id'] == missing[0] for e in ledger)
            assert len(case.calls) == 2 and not audit.passed
        else:
            assert next_second == 56 and not missing and audit.passed
            assert len(case.calls) == 3
        return {'synthetic_post_response_clock_advance_seconds': delay_seconds,
            'first_cycle_status': first['status'],
            'next_scheduled_second_after_first_cycle': next_second,
            'synthetic_provider_calls': len(case.calls),
            'native_audit_passed': audit.passed,
            'missing_slot_ids': missing,
            'missing_slots_with_any_ledger_event': [s for s in missing
                if any(e['slot_id'] == s for e in ledger)],
            'native_ledger_event_count': len(ledger),
            'two_fresh_native_replays_equal': equal_replays}
    finally:
        case.doCleanups()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()

    def denied(*args, **kwargs):
        raise OSError('Network denied in offline scheduler reproduction')

    socket.socket.connect = socket.socket.connect_ex = socket.create_connection = socket.getaddrinfo = denied
    report = {'contract': 'hot-scheduler-advance-native-reproduction-v1',
        'result': 'PASS_REPRODUCTION_OF_EXISTING_BEHAVIOR',
        'cases': [scenario(0), scenario(3)],
        'scope': 'Original collector tick, synthetic publication/SDK, actual native persistence/audit/replays; logical clock fault',
        'actual_windows_six_unmatched_slots_explained': False,
        'original_delay_cause_proven': False,
        'runtime_fix_applied': False, 'deadlines_relaxed': False,
        'frozen_p85_modified': False, 'production_changes': False,
        'actual_provider_used': False, 'actual_vault_access': False, 'network': 'denied'}
    if args.output:
        with args.output.open('x', encoding='utf-8') as out:
            json.dump(report, out, indent=2)
            out.write('\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
