"""Small native journals and saved process evidence; no SDK or credentials."""
from contextlib import closing
from dataclasses import replace
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

from mb_market_data.quote_observation_store import QuoteObservationStore
from mb_market_data.sampling_membership import SamplingHierarchyRevision
from mb_watchlist_coordinator.daily_membership_status import (
    MembershipStatusReader, MembershipDisplayModel, display_lines, et_text)
from mb_watchlist_coordinator.daily_supervision import atomic_json, sealed
from mb_watchlist_coordinator.sampling_requests import digest, utc_text


class SyntheticMembership:
    def __init__(self, root, *, universe=('IBM', 'MSFT')):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.now = (datetime.now(ZoneInfo('America/New_York'))+timedelta(days=2)).replace(
            hour=10, minute=0, second=0, microsecond=0)
        self.start = self.now.replace(hour=9, minute=30)
        self.journal = self.root/f'{self.now.date()}.sqlite3'
        self.store = QuoteObservationStore(self.journal, session_date=self.now.date(), schema_version=2)
        self.store.initialize()
        self.r0 = SamplingHierarchyRevision(session_date=self.now.date(), revision=0,
            effective_at=self.start, uni_symbols=universe, focus_symbols=(), hot_symbols=(), source='synthetic opening')
        self.r1 = replace(self.r0, revision=1, focus_symbols=('MSFT',), source='synthetic opening Focus')
        for r in (self.r0, self.r1):
            self.store.record_membership_revision(r)
        self.state_root = self.root/'daily_hot_synthetic'
        self.state_root.mkdir()
        settings = {'state_root': str(self.state_root), 'journal_path': str(self.journal)}
        raw = {'contract': 'daily-hot-publication-session-v1', 'settings': settings,
            'session_date': str(self.now.date()), 'start_at_utc': utc_text(self.start),
            'published_anchor': [self.r0.content_sha256, self.r1.content_sha256]}
        self.binding = dict(raw, binding_sha256=digest(raw))
        self.claim = {'state_root': str(self.state_root), 'binding_sha256': self.binding['binding_sha256']}
        self.save_session()
        self.controller()

    def save_session(self):
        atomic_json(self.state_root/'session.json', {'status': 'ATTACHED', 'binding': self.binding, 'claim': self.claim})
        atomic_json(self.journal.with_suffix('.daily-hot-session.json'), self.claim)

    def controller(self, *, state='RUNNING_WITH_SOURCE_GAPS', age=0, invocation='synthetic', terminal=None, stop=None):
        raw = {'contract': 'daily-hot-controller-v1', 'collector': {'daily_binding': self.binding}}
        identity = {'configuration_path': str(self.state_root/'daily-worker.json'), 'configuration_sha256': digest(raw)}
        self.identity = identity
        sha = digest(identity)
        at = utc_text(self.now-timedelta(seconds=age))
        atomic_json(self.state_root/'daily-worker.json', raw)
        atomic_json(self.state_root/'driver-binding.json', identity)
        atomic_json(self.state_root/'driver-state.json', sealed({'identity_sha256': sha,
            'active_invocation': invocation, 'terminal': terminal, 'stop': stop}))
        atomic_json(self.state_root/'driver-live.json', sealed({'identity_sha256': sha,
            'invocation': invocation, 'observed_at_utc': at, 'state': 'RUNNING'}))
        atomic_json(self.state_root/'hot-status.json', sealed({'identity_sha256': sha,
            'invocation': invocation, 'observed_at_utc': at, 'state': state, 'worker': {'status': 'RUNNING'},
            'source_status': 'INCOMPLETE', 'source_reconciled': False, 'terminal': terminal}))
        atomic_json(self.state_root/'hot-incidents.json', sealed({'identity_sha256': sha,
            'incidents': {'source:gap': {'resolved_at_utc': None}}}))

    def add(self, symbol='NVDA', *, effective=None):
        current = self.store.membership_revisions_in_effective_order()[-1]
        at = effective or self.now
        value = replace(current, revision=current.revision+1, effective_at=at, published_at=None,
            uni_symbols=tuple(set(current.uni_symbols)|{symbol}),
            focus_symbols=tuple(set(current.focus_symbols)|{symbol}),
            hot_symbols=tuple(set(current.hot_symbols)|{symbol}), source='synthetic Nasdaq admission',
            reason='Synthetic LUDP identity accepted')
        self.store.record_membership_revision(value)
        return value

    def quote(self):
        from mb_market_data.quote_observation_store import PollRunProvenance
        from mb_market_data.schwab_quotes import QuoteBatchResult, QuoteResult, QuoteStatus
        from mb_market_data.watchlist_polling import PollRequest
        from mb_market_data.sampling_acquisition import ExplicitPollSlot
        from mb_market_data.sampling_membership import SamplingChannel
        r = self.store.latest_membership_revision_effective_at(self.now)
        self.store.record_run(PollRunProvenance('synthetic-hot', self.now, 'offline', {'watchlist_kind': 'hot'}))
        request = PollRequest(ExplicitPollSlot(SamplingChannel.HOT, self.now, (self.now.second,)), r.revision, r.hot_symbols, self.now)
        batch = QuoteBatchResult(tuple(QuoteResult(s, QuoteStatus.QUOTE,
            {'symbol': s, 'synthetic_private_payload': 'MUST-NOT-BE-READ'}, None, 1, self.now, self.now)
            for s in r.hot_symbols), 1, 400, ())
        self.store.record_acquisition('synthetic-hot', request, batch, completed_at=self.now)


class MembershipStatusTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.scene = SyntheticMembership(temp.name)
        self.reader = MembershipStatusReader(self.scene.state_root, clock=lambda: self.scene.now)
        self.model = MembershipDisplayModel(self.reader)

    def symbols(self, value):
        return {k: [r['symbol'] for r in rows] for k, rows in value['groups'].items()}

    def test_opening_rosters_are_not_repeated_in_delta_panels(self):
        result = self.model.refresh()
        self.assertTrue(result['fresh'])
        self.assertEqual(result['effective_revision'], 1)
        self.assertEqual(self.symbols(result), {'hot': [], 'focus': [], 'uni': []})
        self.assertEqual(result['opening_counts'], {'hot': 0, 'focus': 1, 'uni': 2})

    def test_new_symbol_appears_in_all_three_panels_with_native_effective_time(self):
        r = self.scene.add()
        result = self.model.refresh()
        self.assertEqual(self.symbols(result), {'hot': ['NVDA'], 'focus': ['NVDA'], 'uni': ['NVDA']})
        self.assertEqual(result['groups']['hot'][0]['joined_at_utc'], utc_text(r.effective_at))
        self.assertEqual(result['groups']['focus'][0]['reason'], r.reason)

    def test_symbol_already_in_opening_uni_does_not_appear_as_a_uni_addition(self):
        self.scene.add('IBM')
        self.assertEqual(self.symbols(self.model.refresh()), {'hot': ['IBM'], 'focus': ['IBM'], 'uni': []})

    def test_symbol_already_in_opening_focus_appears_only_in_hot(self):
        self.scene.add('MSFT')
        self.assertEqual(self.symbols(self.model.refresh()), {'hot': ['MSFT'], 'focus': [], 'uni': []})

    def test_future_revision_is_not_displayed_before_it_becomes_effective(self):
        self.scene.add(effective=self.scene.now+timedelta(seconds=2))
        self.assertEqual(self.model.refresh()['effective_revision'], 1)
        self.scene.now += timedelta(seconds=2)
        self.assertEqual(self.model.refresh()['effective_revision'], 2)

    def test_pinned_r1_survives_later_revisions_and_a_new_display_reader(self):
        self.model.refresh()
        self.scene.add()
        self.scene.now += timedelta(seconds=2)
        self.scene.add('AMD')
        first = self.model.refresh()
        second = MembershipStatusReader(self.scene.state_root, clock=lambda: self.scene.now).snapshot()
        self.assertEqual(self.symbols(first), self.symbols(second))
        self.assertEqual(first['baseline_sha256'], self.scene.r1.content_sha256)
        self.assertEqual(first['counts'], {'hot': 2, 'focus': 2, 'uni': 2})
        self.assertEqual(first['groups']['hot'][1]['joined_at_utc'], utc_text(self.scene.now-timedelta(seconds=2)))

    def test_missing_root_or_database_is_not_created(self):
        root = self.scene.root/'missing'
        missing = MembershipDisplayModel(MembershipStatusReader(root)).refresh()
        self.assertFalse(missing['fresh'])
        self.assertFalse(root.exists())
        self.scene.journal.unlink()
        self.assertFalse(self.model.refresh()['fresh'])
        self.assertFalse(self.scene.journal.exists())

    def test_failed_read_keeps_visible_lists_but_marks_them_last_verified(self):
        self.scene.add()
        first = self.model.refresh()
        path = self.scene.state_root/'session.json'
        original = path.read_bytes()
        path.write_text('{}')
        failed = self.model.refresh()
        self.assertFalse(failed['fresh'])
        self.assertEqual(failed['last_verified']['groups'], first['groups'])
        self.assertIn('LAST VERIFIED', display_lines(failed)['banner'])
        self.assertIn('current health unavailable', display_lines(failed)['health'])
        path.write_bytes(original)
        self.assertTrue(self.model.refresh()['fresh'])

    def test_initial_error_does_not_display_empty_lists_as_verified_membership(self):
        (self.scene.state_root/'session.json').write_text('{}')
        view = display_lines(self.model.refresh())
        self.assertIn('UNAVAILABLE', view['banner'])
        self.assertEqual(view['panels']['uni'], ['Unavailable'])

    def test_changed_binding_is_not_silently_adopted_by_an_open_window(self):
        self.model.refresh()
        binding = dict(self.scene.binding)
        binding.pop('binding_sha256')
        binding['new_metadata'] = 'changed'
        self.scene.binding = dict(binding, binding_sha256=digest(binding))
        self.scene.claim['binding_sha256'] = self.scene.binding['binding_sha256']
        self.scene.save_session()
        self.assertFalse(self.model.refresh()['fresh'])

    def test_native_membership_tampering_is_unavailable(self):
        self.scene.add()
        with closing(sqlite3.connect(self.scene.journal)) as c, c:
            c.execute("UPDATE sampling_channel_member SET symbol='AMD' WHERE channel='hot' AND revision=2")
        self.assertFalse(self.model.refresh()['fresh'])

    def test_wrong_session_identity_is_unavailable(self):
        with closing(sqlite3.connect(self.scene.journal)) as c, c:
            c.execute("UPDATE store_identity SET session_date='1999-01-01'")
        self.assertFalse(self.model.refresh()['fresh'])

    def test_one_read_transaction_never_mixes_revisions_when_writer_commits(self):
        original = sqlite3.connect
        wrote = []
        def connect(*args, **kwargs):
            c = original(*args, **kwargs)
            if kwargs.get('uri'):
                def trace(sql):
                    if 'SELECT * FROM sampling_membership_revision' in sql and not wrote:
                        wrote.append(True)
                        self.scene.add()
                c.set_trace_callback(trace)
            return c
        with patch('mb_watchlist_coordinator.daily_membership_status.sqlite3.connect', side_effect=connect):
            first = self.model.refresh()
        self.assertTrue(wrote)
        self.assertTrue(first['fresh'])
        self.assertEqual(first['effective_revision'], 1)
        self.assertEqual(self.model.refresh()['effective_revision'], 2)

    def test_reader_uses_mode_ro_and_never_reads_quote_payloads_or_writes_sql(self):
        self.scene.add()
        self.scene.quote()
        original = sqlite3.connect
        reads = set()
        arguments = []
        def connect(*args, **kwargs):
            arguments.append((args, kwargs))
            c = original(*args, **kwargs)
            def authorize(action, table, column, db, trigger):
                if action == sqlite3.SQLITE_READ:
                    reads.add(table)
                    if table in ('quote_observation', 'poll_run'):
                        return sqlite3.SQLITE_DENY
                if action in (sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE):
                    return sqlite3.SQLITE_DENY
                return sqlite3.SQLITE_OK
            c.set_authorizer(authorize)
            return c
        before = hashlib.sha256(self.scene.journal.read_bytes()).hexdigest()
        with patch('mb_watchlist_coordinator.daily_membership_status.sqlite3.connect', side_effect=connect):
            result = self.model.refresh()
        self.assertTrue(result['fresh'], result)
        self.assertEqual(len(arguments), 1)
        self.assertIn('mode=ro', arguments[0][0][0])
        self.assertTrue(arguments[0][1]['uri'])
        self.assertNotIn('quote_observation', reads)
        self.assertIn('quote_acquisition', reads)
        self.assertEqual(result['last_hot_acquisition']['requested_symbol_count'], 1)
        self.assertEqual(hashlib.sha256(self.scene.journal.read_bytes()).hexdigest(), before)

    def test_stale_controller_and_fresh_membership_are_separate(self):
        self.scene.controller(age=4)
        result = self.model.refresh()
        self.assertTrue(result['fresh'])
        self.assertEqual(result['controller']['state'], 'STALE')
        self.assertIn('stale', result['controller']['detail'])

    def test_normal_stop_remains_visible_without_claiming_active_collection(self):
        self.scene.add()
        self.scene.controller(age=60, stop={'reason': 'window_ended'})
        result = self.model.refresh()
        self.assertTrue(result['fresh'])
        self.assertEqual(result['controller']['state'], 'STOPPED')
        self.assertEqual(self.symbols(result)['hot'], ['NVDA'])

    def test_blocked_recovery_and_source_gaps_are_visible(self):
        self.scene.controller(state='REPLACEMENT_HOLD')
        value = self.model.refresh()
        self.assertIn('REPLACEMENT_HOLD', display_lines(value)['health'])
        self.assertIn('Known gaps in Nasdaq feed history', display_lines(value)['warning'])
        self.scene.controller(terminal='provider_stop')
        value = self.model.refresh()
        self.assertEqual(value['controller']['state'], 'BLOCKED')
        self.assertIn('provider_stop', display_lines(value)['warning'])

    def test_inconsistent_controller_invocations_are_unknown_not_running(self):
        live = unsealed = json.loads((self.scene.state_root/'driver-live.json').read_text())
        unsealed.pop('content_sha256')
        live['invocation'] = 'other'
        atomic_json(self.scene.state_root/'driver-live.json', sealed(live))
        self.assertEqual(self.model.refresh()['controller']['state'], 'UNAVAILABLE')

    def test_window_can_wait_for_controller_without_starting_or_creating_it(self):
        path = self.scene.state_root/'driver-binding.json'
        path.unlink()
        before = set(self.scene.root.rglob('*'))
        result = self.model.refresh()
        self.assertTrue(result['fresh'])
        self.assertEqual(result['controller']['state'], 'NOT_STARTED')
        self.assertFalse(path.exists())
        added = set(self.scene.root.rglob('*'))-before
        self.assertTrue(added <= {Path(str(self.scene.journal)+'-wal'), Path(str(self.scene.journal)+'-shm')})

    def test_preopen_status_is_waiting_and_never_invents_opening_membership(self):
        self.scene.now = self.scene.start-timedelta(minutes=1)
        result = self.model.refresh()
        self.assertEqual(result['state'], 'WAITING_FOR_OPEN')
        self.assertIsNone(result['effective_revision'])
        self.assertIn('WAITING', display_lines(result)['banner'])

    def test_est_and_edt_labels_use_eastern_zone_without_changing_clock(self):
        self.assertEqual(et_text('2026-10-30T13:30:00+00:00'), '2026-10-30 09:30:00 EDT')
        self.assertEqual(et_text('2026-11-02T14:30:00+00:00'), '2026-11-02 09:30:00 EST')

    def test_blank_lists_have_explicit_empty_states_and_counts(self):
        view = display_lines(self.model.refresh())
        self.assertEqual(view['panels']['hot'], ['No current Hot members'])
        self.assertEqual(view['panels']['focus'], ['None added since r1'])
        self.assertEqual(view['counts'], {'hot': 0, 'focus': 0, 'uni': 0})

    def test_current_hot_list_does_not_keep_a_removed_symbol_as_current(self):
        r = self.scene.add()
        self.scene.now += timedelta(seconds=1)
        self.scene.store.record_membership_revision(replace(r, revision=3, hot_symbols=(),
            effective_at=self.scene.now, published_at=None))
        result = self.model.refresh()
        self.assertEqual(self.symbols(result)['hot'], [])
        self.assertEqual(self.symbols(result)['focus'], ['NVDA'])


if __name__ == '__main__':
    unittest.main()
