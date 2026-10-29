"""Synthetic daily-layout journals; no credentials, network or production files."""
from contextlib import closing, redirect_stdout
from dataclasses import replace
from dataclasses import asdict
from datetime import datetime, timedelta
from io import StringIO
import json
import os
import hashlib
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from zoneinfo import ZoneInfo

from mb_market_data.quote_journal_audit import audit_quote_journal
from mb_market_data.quote_observation_store import PollRunProvenance, QuoteObservationStore
from mb_market_data.sampling_membership import SamplingHierarchyRevision
from mb_watchlist_coordinator.daily_session import DailySession, DailySettings, main
from mb_watchlist_coordinator.integrated_identity import IdentityGatedDelivery, IdentityStopRequired
from mb_watchlist_coordinator.nasdaq_sampling import HaltSnapshot
from mb_watchlist_coordinator.operating_plan import proposed_policy
from mb_watchlist_coordinator.sampling_requests import digest, plain
from mb_watchlist_coordinator.sampling_service import ServiceBusy
from test_integrated_catalog import catalog
from test_integrated_identity import Response


class DailySessionTests(unittest.TestCase):
    def setUp(self):
        proof = getattr(self,'proof_directory_override',None) or (os.environ.get('MB_DAILY_SESSION_PROOF_DIR') if self._testMethodName == 'test_existing_uni_focus_acquisitions_continue_across_daily_publication' else None)
        if proof:
            self.root = Path(proof).resolve(); self.root.mkdir(exist_ok=False)
        else:
            temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
            self.root = Path(temporary.name).resolve()
        self.at = (datetime.now(ZoneInfo('America/New_York'))+timedelta(days=1)).replace(
            hour=10, minute=0, second=0, microsecond=0)
        self.now = self.at
        day = self.at.date()
        self.journal = self.root/f'quote_observation_journal_v2_api_opening_{day}'/f'{day}.sqlite3'
        self.store = QuoteObservationStore(self.journal, session_date=day, schema_version=2)
        self.store.initialize()
        common = {'session_date': str(day), 'effective_at': self.at.replace(hour=9, minute=30).isoformat(),
            'uni_symbols': getattr(self,'universe_symbols_override',['IBM','MSFT']),
            'hot_symbols': [], 'source': 'synthetic daily opening'}
        self.r0, self.r1 = self.root/'r0.json', self.root/'r1.json'
        for path, rev, focus in ((self.r0, 0, []), (self.r1, 1, getattr(self,'focus_symbols_override',['MSFT']))):
            payload = dict(common, revision=rev, focus_symbols=focus)
            path.write_text(json.dumps(payload))
            self.store.record_membership_revision(SamplingHierarchyRevision(**dict(payload,
                session_date=day, effective_at=datetime.fromisoformat(payload['effective_at']))))
        for channel, seconds in (('uni', [0, 30]), ('focus', [10, 20, 40, 50])):
            configuration={'watchlist_kind':channel,'poll_seconds':seconds,'cadence_profile':'interleaved-v1'}
            if getattr(self,'full_window_run_configs',False):
                configuration.update(poll_window_start_et=self.at.replace(hour=9,minute=30).isoformat(),
                    poll_window_end_et=self.at.replace(hour=16,minute=0).isoformat())
            self.store.record_run(PollRunProvenance('existing-'+channel,self.at.replace(hour=9,minute=20),
                'synthetic-current-source',configuration))
        self.catalog = getattr(self,'catalog_factory_override',catalog)(self.at.replace(hour=9)).persist(self.root/'catalog')
        self.settings = DailySettings(str(self.root/'daily_hot_test'), str(self.journal),
            str(self.r0), str(self.r1), digest(proposed_policy()))
        self.calls = []
        case = self
        class Client:
            def quotes(self, symbols, *, fields):
                case.calls.append(list(symbols))
                return Response(symbols[0])
        self.client = Client()
        self.session = None
        self.addCleanup(self.close)

    def close(self):
        if self.session: self.session.close()

    def make(self, **changes):
        return DailySession(replace(self.settings, **changes), self.catalog, clock=lambda: self.now)

    def attach(self, create=True):
        self.session = self.make()
        return self.session.attach(create=create, publication_approved=True)

    def snapshot(self, mode='CURRENT', rows=(), capture='first'):
        return HaltSnapshot(capture, self.now, mode, digest(list(rows)), tuple(rows), {'synthetic_only': True})

    def row(self, symbol='NVDA', seconds=0):
        return {'symbol': symbol, 'halt_date': self.at.strftime('%m/%d/%Y'),
            'halt_time': (self.at-timedelta(minutes=1)+timedelta(seconds=seconds)).strftime('%H:%M:%S.%f'),
            'reason_code': 'LUDP'}

    def admit(self, symbol='NVDA', capture='history'):
        return self.session.cycle(client=self.client,
            historical_snapshot=self.snapshot('HISTORICAL', [self.row(symbol)], capture))

    def test_preview_reads_published_anchor_and_creates_no_application_state_or_client(self):
        before = set(self.root.rglob('*'))
        result = self.settings.preview()
        self.assertEqual(result['session_date'], str(self.at.date()))
        self.assertFalse(result['collector_included'])
        added = set(self.root.rglob('*'))-before
        self.assertTrue(added <= {Path(str(self.journal)+'-wal'), Path(str(self.journal)+'-shm')})
        self.assertEqual(len(self.store.membership_revisions_in_effective_order()), 2)
        self.assertFalse(self.calls)

    def test_cli_is_read_only_and_has_no_live_launch_switch(self):
        with redirect_stdout(StringIO()) as output:
            self.assertEqual(main([str(self.r0), str(self.r1), '--journal', str(self.journal),
                '--state-root', self.settings.state_root]), 0)
        self.assertFalse(json.loads(output.getvalue())['live_launch_available'])
        self.assertFalse(Path(self.settings.state_root).exists())

    def test_policy_hash_and_boolean_widening_are_refused(self):
        for sha in ('0'*64, True):
            with self.assertRaises(ValueError): replace(self.settings, policy_sha256=sha).preview()

    def test_wrong_published_proposal_is_refused_before_state_creation(self):
        original = json.loads(self.r1.read_text()); original['reason'] = 'different saved bytes'
        self.r1.write_text(json.dumps(original))
        with self.assertRaises(ValueError): self.attach()
        self.assertFalse(Path(self.settings.state_root).exists())

    def test_source_file_byte_change_invalidates_an_existing_binding(self):
        self.attach()
        self.r0.write_text(self.r0.read_text()+'\n')
        with self.assertRaises(ValueError): self.session.cycle(client=self.client)
        self.assertFalse(self.calls)

    def test_wrong_journal_path_or_date_is_refused(self):
        for value in (str(self.root/'missing.sqlite3'), str(self.journal.parent/('other.sqlite3'))):
            with self.assertRaises(ValueError): replace(self.settings, journal_path=value).preview()

    def test_unsafe_state_location_is_refused(self):
        for root in (self.journal.parent/'daily_hot_state', self.root/'ordinary_state', self.root/'missing'/'daily_hot_state'):
            with self.assertRaises(ValueError): replace(self.settings, state_root=str(root)).preview()

    def test_legacy_cadence_is_refused_before_claim(self):
        with closing(sqlite3.connect(self.journal)) as connection, connection:
            connection.execute('UPDATE poll_run SET configuration_json=?',
                (json.dumps({'watchlist_kind': 'focus', 'poll_seconds': [5,20,35,50]}),))
        with self.assertRaises(ValueError): self.attach()
        self.assertFalse(Path(self.settings.state_root).exists())

    def test_fresh_unbound_hot_run_is_refused(self):
        self.store.record_run(PollRunProvenance('unowned-hot', self.now, 'synthetic', {'watchlist_kind': 'hot'}))
        with self.assertRaises(ValueError): self.attach()
        self.assertFalse(Path(self.settings.state_root).exists())

    def test_explicit_api_authorization_is_required_without_creating_files(self):
        for value in (False, 1, 'yes'):
            session = self.make()
            with self.assertRaises(ValueError): session.attach(create=True, publication_approved=value)
        self.assertFalse(Path(self.settings.state_root).exists())

    def test_attach_preserves_original_membership_and_polling_runs(self):
        hashes = [r.content_sha256 for r in self.store.membership_revisions_in_effective_order()]
        result = self.attach()
        self.assertEqual(result['state'], 'ATTACHED_NOT_COLLECTING')
        self.assertEqual([r.content_sha256 for r in self.store.membership_revisions_in_effective_order()], hashes)
        with closing(sqlite3.connect(self.journal)) as connection:
            self.assertEqual(connection.execute('SELECT run_id FROM poll_run ORDER BY run_id').fetchall(),
                [('existing-focus',), ('existing-uni',)])
        self.assertFalse(self.calls)

    def test_same_journal_different_state_roots_cannot_hold_parallel_ownership(self):
        self.attach()
        other = self.make(state_root=str(self.root/'daily_hot_other'))
        with self.assertRaises(ServiceBusy): other.attach(create=True, publication_approved=True)
        self.assertFalse(other.root.exists())

    def test_new_state_root_cannot_reset_prior_daily_budgets(self):
        self.attach(); self.close()
        other = self.make(state_root=str(self.root/'daily_hot_other'))
        with self.assertRaises(ValueError): other.attach(create=True, publication_approved=True)
        self.assertFalse(other.root.exists())

    def test_partial_initialization_is_retained_and_cannot_be_silently_reopened(self):
        self.session = self.make()
        def fault(stage): raise RuntimeError('synthetic interruption')
        with self.assertRaises(RuntimeError):
            self.session.attach(create=True, publication_approved=True, fault_hook=fault)
        for create in (True, False):
            with self.assertRaises(ValueError): self.make().attach(create=create, publication_approved=True)
        self.assertEqual(json.loads((self.session.root/'session.json').read_text())['status'], 'INITIALIZING')

    def test_missing_original_ledger_is_refused_without_recreation(self):
        self.attach(); path = self.session.root/'identity.sqlite3'; self.close(); path.unlink()
        with self.assertRaises((ValueError, FileNotFoundError)):
            self.make().attach(publication_approved=True)
        self.assertFalse(path.exists())

    def test_daily_identity_is_distinct_and_original_experiment_window_stays_sealed(self):
        self.attach(); gate = self.session.gate
        self.assertEqual(gate.identity['contract'], 'daily-nasdaq-identity-gate-v1')
        with self.assertRaises(ValueError):
            IdentityGatedDelivery(self.root/'forbidden.sqlite3', delivery=self.session.delivery,
                catalog=self.catalog, start_at=gate.start.isoformat(), stop_at=gate.stop.isoformat())

    def test_historical_receipt_identity_admission_and_native_publication_are_coupled(self):
        self.attach(); result = self.admit()
        self.assertEqual(self.calls, [['NVDA']])
        self.assertEqual(result['latest_published_revision'], 2)
        self.assertEqual(result['effective_revision'], 1)
        self.now += timedelta(seconds=1)
        self.assertEqual(self.session.status()['effective_revision'], 2)
        latest = self.store.membership_revisions_in_effective_order()[-1]
        self.assertEqual(latest.hot_symbols, ('NVDA',))
        self.assertEqual(set(latest.uni_symbols), {'IBM','MSFT','NVDA'})
        self.assertEqual(set(latest.focus_symbols), {'MSFT','NVDA'})
        self.assertTrue(audit_quote_journal(self.journal).passed)

    def test_restart_replays_same_identity_permit_and_publication_without_duplicate(self):
        self.attach(); self.admit(); self.close(); self.now += timedelta(seconds=2)
        self.attach(create=False)
        self.assertEqual(self.session.status()['identity_quote_permits'], 1)
        self.admit(capture='same-event-new-capture')
        self.assertEqual(self.calls, [['NVDA']])
        self.assertEqual(len(self.store.membership_revisions_in_effective_order()), 3)

    def test_second_distinct_symbol_is_retained_but_never_admitted_or_queried(self):
        self.attach(); self.admit(); self.now += timedelta(seconds=1)
        self.admit('AMD', capture='second-symbol')
        self.assertEqual(self.calls, [['NVDA']])
        self.assertEqual(self.store.membership_revisions_in_effective_order()[-1].hot_symbols, ('NVDA',))
        self.assertIn('one_symbol_limit', plain(self.session.gate.snapshot())['identity_gate']['dispositions'].values())

    def test_unknown_identity_reservation_is_not_retried_after_restart(self):
        self.attach()
        def fault(stage):
            if stage == 'after_identity_reservation': raise RuntimeError('synthetic interruption')
        with self.assertRaises(RuntimeError):
            self.session.cycle(client=self.client, historical_snapshot=self.snapshot('HISTORICAL', [self.row()]),
                identity_fault_hook=fault)
        self.close(); self.attach(create=False); self.session.cycle(client=self.client)
        self.assertFalse(self.calls)
        self.assertEqual(self.session.status()['identity_quote_permits'], 1)
        self.assertEqual(len(self.store.membership_revisions_in_effective_order()), 2)

    def test_rate_limit_stops_before_publication_and_survives_reopen(self):
        self.attach()
        class RateLimited:
            def quotes(self, symbols, *, fields): return Response(symbols[0], status=429)
        with self.assertRaises(IdentityStopRequired):
            self.session.cycle(client=RateLimited(), historical_snapshot=self.snapshot('HISTORICAL', [self.row()]))
        self.close(); self.attach(create=False)
        with self.assertRaises(IdentityStopRequired): self.session.cycle(client=self.client)
        self.assertFalse(self.calls)
        self.assertEqual(len(self.store.membership_revisions_in_effective_order()), 2)

    def test_after_commit_interruption_reconciles_same_native_revision_on_resume(self):
        self.attach()
        def fault(stage):
            if stage == 'after_commit': raise RuntimeError('synthetic interruption')
        with self.assertRaises(RuntimeError):
            self.session.cycle(client=self.client, historical_snapshot=self.snapshot('HISTORICAL', [self.row()]),
                service_fault_hook=fault)
        original = self.store.membership_revisions_in_effective_order()[-1]
        self.close(); self.now += timedelta(seconds=2); self.attach(create=False)
        self.session.cycle(client=self.client)
        self.assertEqual(self.store.membership_revisions_in_effective_order()[-1], original)
        self.assertEqual(len(self.calls), 1)

    def test_foreign_publication_is_not_adopted(self):
        self.attach()
        latest = self.store.membership_revisions_in_effective_order()[-1]
        self.store.record_membership_revision(replace(latest, revision=2,
            effective_at=self.now+timedelta(seconds=1), source='unrelated-publisher', published_at=None))
        with self.assertRaises(ValueError): self.session.cycle(client=self.client)
        self.assertFalse(self.calls)

    def test_clock_rollback_is_refused_before_source_identity_or_publication(self):
        self.attach(); self.now -= timedelta(seconds=1)
        with self.assertRaises(ValueError): self.admit()
        self.assertFalse(self.calls)

    def test_close_and_window_end_never_cancel_source_demand_or_stop_other_channels(self):
        self.attach(); self.admit(); event_count = len(self.session.requests.events())
        self.now = self.at.replace(hour=16)
        with self.assertRaises(ValueError): self.session.cycle(client=self.client)
        self.close()
        self.assertEqual(len(self.session.requests.events()), event_count)
        self.assertEqual(len(self.calls), 1)
        with closing(sqlite3.connect(self.journal)) as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM poll_run').fetchone()[0], 2)

    def test_before_open_attach_has_no_effective_membership_or_provider_call(self):
        self.now = self.at.replace(hour=9, minute=15)
        result = self.attach()
        self.assertIsNone(result['effective_revision'])
        self.session.cycle(client=self.client)
        self.assertFalse(self.calls)

    def test_current_startup_history_is_retained_without_being_promoted(self):
        self.attach()
        self.session.cycle(client=self.client, current_snapshot=self.snapshot(rows=[self.row()]))
        self.assertFalse(self.calls)
        self.assertEqual(len(self.store.membership_revisions_in_effective_order()), 2)

    def test_corrupt_binding_or_status_is_refused(self):
        self.attach()
        status = self.session.root/'status.json'
        payload = json.loads(status.read_text()); payload['identity_quote_permits'] = 0
        payload['selected_symbol'] = 'FORGED'; status.write_text(json.dumps(payload))
        with self.assertRaises(ValueError): self.admit()
        self.assertFalse(self.calls)

    def test_bad_snapshot_kind_is_refused(self):
        self.attach()
        with self.assertRaises(ValueError):
            self.session.cycle(client=self.client, current_snapshot=self.snapshot('HISTORICAL'))

    def test_native_readers_follow_future_hierarchy_and_original_baseline_is_retained(self):
        self.attach(); anchors = self.store.membership_revisions_in_effective_order()
        self.admit(); future = self.store.membership_revisions_in_effective_order()[-1]
        self.assertEqual(self.store.latest_membership_revision_effective_at(self.now).revision, 1)
        self.assertEqual(self.store.latest_membership_revision_effective_at(future.effective_at).hot_symbols, ('NVDA',))
        self.assertEqual(self.store.membership_revisions_in_effective_order()[:2], anchors)

    def test_existing_uni_focus_acquisitions_continue_across_daily_publication(self):
        from mb_market_data.schwab_quotes import QuoteBatchResult, QuoteResult, QuoteStatus
        from mb_market_data.watchlist_polling import PollRequest, PollSlot, WatchlistKind
        def acquire(channel, second):
            at = self.at.replace(second=second)
            hierarchy = self.store.latest_membership_revision_effective_at(at)
            symbols = getattr(hierarchy, channel+'_symbols')
            request = PollRequest(PollSlot(WatchlistKind(channel), at, 'interleaved-v1'),
                hierarchy.revision, symbols, at)
            results = QuoteBatchResult(tuple(QuoteResult(s, QuoteStatus.QUOTE,
                {'symbol':s, 'quote':{'lastPrice':12.0}}, None, 1, at, at) for s in symbols), 1, 400, ())
            self.store.record_acquisition('existing-'+channel, request, results, completed_at=at)
        acquire('uni', 0)
        self.attach(); self.admit()
        acquire('focus', 10); acquire('uni', 30); acquire('focus', 40)
        self.close()
        with closing(sqlite3.connect(self.journal)) as connection:
            self.assertEqual(connection.execute('SELECT channel,count(*) FROM quote_acquisition GROUP BY channel').fetchall(),
                [('focus',2),('uni',2)])
            self.assertEqual(connection.execute('SELECT count(*) FROM quote_observation').fetchone()[0], 9)
        audit = audit_quote_journal(self.journal)
        self.assertTrue(audit.passed)
        from mb_market_data.quote_journal_replay import QuoteJournalReplayReader
        events = tuple(QuoteJournalReplayReader(self.journal).events())
        self.assertEqual(events, tuple(QuoteJournalReplayReader(self.journal).events()))
        self.assertEqual(len(events), 7)
        if os.environ.get('MB_DAILY_SESSION_PROOF_DIR'):
            result = {'contract':'daily-publication-native-proof-v1', 'result':'PASS',
                'synthetic_only':True, 'clock':'logical', 'journal':str(self.journal),
                'events':7, 'membership_revisions':3, 'uni_acquisitions':2, 'focus_acquisitions':2,
                'hot_acquisitions':0, 'observations':9, 'native_audit_passed':True,
                'two_fresh_replays_equal':True,
                'sequence_sha256':hashlib.sha256(''.join(e.event_id+'\n' for e in events).encode()).hexdigest(),
                'original_poll_runs_preserved':True, 'live_or_full_session_qualification':False}
            (self.root/'proof.json').write_text(json.dumps(result,indent=2)+'\n')

    def test_three_identity_permits_are_cumulative_across_daily_reopen(self):
        self.attach()
        case = self
        class Unconfirmed:
            def quotes(self, symbols, *, fields):
                case.calls.append(list(symbols)); return Response(symbols[0], body={})
        self.client = Unconfirmed()
        self.admit('NVDA', 'one'); self.admit('AMD', 'two')
        self.close(); self.attach(create=False)
        self.admit('MSFT', 'three'); self.admit('IBM', 'four')
        self.assertEqual(len(self.calls), 3)
        self.assertEqual(self.session.status()['identity_quote_permits'], 3)
        self.assertIn('identity_budget_exhausted',
            plain(self.session.gate.snapshot())['identity_gate']['dispositions'].values())

    def test_provider_exception_text_is_not_retained_in_daily_ledgers(self):
        self.attach()
        class Broken:
            def quotes(self, symbols, *, fields): raise RuntimeError('SYNTHETIC-DAILY-PRIVATE-CANARY')
        self.client = Broken(); self.admit()
        for path in self.session.root.rglob('*'):
            if path.is_file(): self.assertNotIn(b'SYNTHETIC-DAILY-PRIVATE-CANARY', path.read_bytes())

    def test_catalog_from_another_day_or_future_time_is_refused(self):
        for at in (self.at-timedelta(days=1), self.at+timedelta(minutes=1)):
            with self.assertRaises(ValueError): DailySession(self.settings, catalog(at), clock=lambda:self.now)

    def test_tampered_claim_is_refused_on_reopen(self):
        self.attach(); self.close()
        self.session.claim_path.write_text('{}')
        with self.assertRaises(ValueError): self.make().attach(publication_approved=True)

    def test_same_closed_object_cannot_reacquire_a_session(self):
        self.attach(); self.close()
        with self.assertRaises(ValueError): self.session.attach(publication_approved=True)

    def crash_child(self, stage):
        import mb_market_data
        job = {'settings': asdict(self.settings), 'catalog': str(self.root/'catalog'),
            'at': self.now.isoformat(), 'stage': stage,
            'native_src': str(Path(mb_market_data.__file__).resolve().parents[1])}
        result = subprocess.run([sys.executable, '-I', '-B',
            str(Path(__file__).parent/'fixtures/daily_session_worker.py')],
            input=json.dumps(job).encode(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15)
        self.assertEqual(result.returncode, 75, result.stderr.decode(errors='replace'))

    def test_actual_process_loss_preserves_unknown_daily_identity_and_releases_lease(self):
        self.crash_child('after_identity_reservation')
        self.now += timedelta(seconds=2); self.attach(create=False)
        self.session.cycle(client=self.client)
        self.assertEqual(self.session.status()['identity_quote_permits'], 1)
        self.assertFalse(self.calls)
        self.assertFalse((Path(self.settings.state_root)/'quote-calls.txt').exists())

    def test_actual_process_loss_after_native_commit_replays_exact_publication(self):
        self.crash_child('after_commit')
        original = self.store.membership_revisions_in_effective_order()[-1]
        self.now += timedelta(seconds=2); self.attach(create=False)
        self.session.cycle(client=self.client)
        self.assertEqual(self.store.membership_revisions_in_effective_order()[-1], original)
        self.assertEqual((Path(self.settings.state_root)/'quote-calls.txt').read_text().splitlines(), ['NVDA'])
        self.assertFalse(self.calls)

    def test_two_fresh_native_replays_match_after_recovered_publication(self):
        from mb_market_data.quote_journal_replay import QuoteJournalReplayReader
        self.attach(); self.admit(); self.close(); self.now += timedelta(seconds=2)
        self.attach(create=False); self.session.cycle(client=self.client)
        first = tuple(QuoteJournalReplayReader(self.journal).events())
        second = tuple(QuoteJournalReplayReader(self.journal).events())
        self.assertEqual(first, second)
        self.assertEqual(len(first), 3)

    def test_naive_clock_is_refused_before_state_or_claim_creation(self):
        self.now = self.now.replace(tzinfo=None)
        with self.assertRaises(ValueError): self.attach()
        self.assertFalse(Path(self.settings.state_root).exists())


if __name__ == '__main__': unittest.main()
