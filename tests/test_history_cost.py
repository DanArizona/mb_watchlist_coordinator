"""Changed read paths must retain corruption, admission and crash checks."""
from __future__ import annotations

from contextlib import closing
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
import sqlite3
import tempfile
from pathlib import Path
from types import MappingProxyType
import unittest
from unittest.mock import patch

from test_sampling_service import fixture, request, interruption
from mb_watchlist_coordinator.models import ProducerIntent, IntentType
from mb_watchlist_coordinator.sampling_journal import SamplingJournal
from mb_watchlist_coordinator.sampling_projection import SamplingMembership
from mb_watchlist_coordinator.sampling_requests import (
    RequestEvent, baseline_payload, canonical, digest, plain, replay_requests, request_payload)
from mb_market_data.sampling_membership import SamplingHierarchyRevision
from mb_market_data.quote_observation_store import QuoteObservationStoreError


class JournalReadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.ledger, self.store, self.service, self.clock = fixture(Path(self.temp.name))

    def rehash_publications(self, edit):
        with closing(sqlite3.connect(self.service.path)) as c, c:
            rows = c.execute('SELECT sequence,payload,previous_sha256 FROM publication_event ORDER BY sequence').fetchall()
            previous = rows[0][2]
            for sequence, raw, _ in rows:
                payload = json.loads(raw)
                edit(sequence, payload)
                sha = digest({'sequence': sequence, 'payload': payload, 'previous_sha256': previous})
                c.execute('UPDATE publication_event SET payload=?,previous_sha256=?,event_sha256=? WHERE sequence=?',
                          (canonical(payload), previous, sha, sequence))
                previous = sha

    def test_wire_hash_matches_native_constructor_with_offset_unicode_and_nested_metadata(self):
        payload = {
            'session_date': self.ledger.session_date.isoformat(), 'revision': 9,
            'effective_at_utc': self.clock[0].astimezone(timezone(timedelta(hours=5, minutes=30))).isoformat(),
            'uni_symbols': ['AAPL', 'MSFT'], 'focus_symbols': ['MSFT'], 'hot_symbols': [],
            'source': 'test', 'reason': 'résumé',
            'metadata': {'text': '東京', 'items': [None, True, 1, 1.25, {'nested': []}]} }
        bridge = self.service.journal
        self.assertEqual(bridge._reconstructed_hash(payload), bridge.content_hash(payload))
        payload['effective_at_utc'] = self.clock[0].replace(microsecond=123456).isoformat()
        self.assertEqual(bridge._reconstructed_hash(payload), bridge.content_hash(payload))

    def test_reconstructed_hash_refuses_stale_or_altered_native_value(self):
        original = self.store.membership_revisions_in_effective_order()[0]
        object.__setattr__(original, 'reason', 'changed without updating hash')
        with patch.object(self.store, 'validated_membership_revision_payloads', None), patch.object(
                self.store, 'membership_revisions_in_effective_order', return_value=(original,)):
            with self.assertRaisesRegex(ValueError, 'content hash'):
                self.service.journal.revisions()

    def test_warm_read_cannot_hide_changed_channel_members(self):
        self.service.snapshot()
        with closing(sqlite3.connect(self.store.database_path)) as c, c:
            c.execute("UPDATE sampling_channel_member SET symbol='ZZZZ' WHERE channel='uni' AND ordinal=0")
        with self.assertRaisesRegex(QuoteObservationStoreError, 'content hash'):
            self.service.snapshot()

    def test_rehashed_request_checkpoint_still_fails_with_matching_native_journal(self):
        request(self.ledger)
        self.service.cycle()
        self.service.snapshot()
        def edit(sequence, payload):
            if sequence == 1:
                payload['request_state_sha256'] = '0' * 64
        self.rehash_publications(edit)
        with self.assertRaisesRegex(ValueError, 'request prefix'):
            self.service.snapshot()

    def test_rehashed_plan_hash_still_fails_with_matching_native_journal(self):
        request(self.ledger)
        self.service.cycle()
        def edit(sequence, payload):
            if sequence == 1:
                payload['content_sha256'] = '0' * 64
        self.rehash_publications(edit)
        with self.assertRaisesRegex(ValueError, 'revision/content'):
            self.service.snapshot()

    def test_uncommitted_plan_still_uses_native_validation(self):
        request(self.ledger)
        with self.assertRaises(RuntimeError):
            self.service.cycle(fault_hook=interruption('after_plan'))
        native = self.service.journal.content_hash
        with patch.object(self.service.journal, 'content_hash', wraps=native) as checked:
            self.assertIsNotNone(self.service.snapshot()['pending'])
        self.assertGreater(checked.call_count, 0)

    def test_boolean_revision_cannot_borrow_integer_revision_validation(self):
        request(self.ledger)
        self.service.cycle()
        def edit(sequence, payload):
            if sequence == 1:
                payload['proposal']['revision'] = True
        self.rehash_publications(edit)
        with self.assertRaisesRegex(TypeError, 'revision must be an integer'):
            self.service.snapshot()

    def test_float_request_sequence_cannot_borrow_integer_metadata_hash(self):
        request(self.ledger)
        self.service.cycle()
        def edit(sequence, payload):
            if sequence == 1:
                payload['proposal']['metadata']['request_state']['sequence'] = 1.0
        self.rehash_publications(edit)
        with self.assertRaisesRegex(ValueError, 'revision/content'):
            self.service.snapshot()

    def test_committed_without_ack_still_reconciles_once(self):
        request(self.ledger)
        with self.assertRaises(RuntimeError):
            self.service.cycle(fault_hook=interruption('after_commit'))
        before = self.store.membership_revisions_in_effective_order()
        self.clock[0] += timedelta(seconds=5)
        self.service.cycle()
        self.assertEqual(before, self.store.membership_revisions_in_effective_order())
        self.assertIsNone(self.service.snapshot()['pending'])


class ReplayWindowTests(unittest.TestCase):
    def test_same_request_key_uses_replacement_activation_and_expiry(self):
        at = datetime(2026, 11, 2, 15, tzinfo=timezone.utc)
        baseline = SamplingMembership({'AAPL'}, set(), set())
        value = ProducerIntent('same-key', 'manual', IntentType.ENSURE_PRESENT, frozenset({'AAPL'}), at,
            metadata={'sampling_channel': 'hot', 'session_date': at.date().isoformat()})
        first = request_payload(value)
        second = request_payload(replace(value, effective_from=at+timedelta(seconds=10),
                                         expires_at=at+timedelta(seconds=12)))
        previous = digest(baseline_payload(at.date(), baseline))
        events = []
        for index, (seconds, payload) in enumerate([(0, first), (1, second), (10, None), (12, None)]):
            event = RequestEvent(index+1, 'command-'+str(index), 'request' if payload else 'tick',
                'manual' if payload else '__coordinator__', payload or {}, at+timedelta(seconds=seconds),
                True, None, previous, '')
            event = replace(event, event_sha256=digest(event.hash_payload()))
            events.append(event); previous = event.event_sha256
        states = replay_requests(at.date(), baseline, tuple(events))
        self.assertEqual([bool(s.desired.hot) for s in states[1:]], [True, False, True, False])

    def test_plain_scalar_lists_detach_and_keep_nested_mapping_normalization(self):
        values = ['AAPL', 1, True, None, 1.25]
        result = plain({'values': values, 'nested': (MappingProxyType({'x': ['MSFT']}),)})
        values.append('changed')
        self.assertEqual(result, {'values': ['AAPL', 1, True, None, 1.25], 'nested': [{'x': ['MSFT']}]})
        for value in (float('inf'), float('-inf'), float('nan')):
            with self.assertRaises(ValueError):
                canonical({'values': [value]})


if __name__ == '__main__':
    unittest.main()
