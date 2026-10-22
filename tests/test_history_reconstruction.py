"""Wire equivalence and corruption boundaries for reconstruction changes."""
from collections import UserDict
from datetime import datetime
import hashlib
import json
import random
from types import MappingProxyType
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from mb_watchlist_coordinator.sampling_requests import canonical, digest, plain
from test_sampling_service import fixture, request


class CanonicalWireTests(unittest.TestCase):
    def assert_wire_unchanged(self, value):
        expected = json.dumps(plain(value), sort_keys=True,
                              separators=(',', ':'), allow_nan=False)
        self.assertEqual(canonical(value), expected)
        self.assertEqual(digest(value), hashlib.sha256(expected.encode('utf-8')).hexdigest())

    def test_nested_frozen_and_general_mappings_preserve_exact_wire(self):
        self.assert_wire_unchanged(MappingProxyType({
            'unicode': '東京/é', 'rows': (None, True, False, 1, 1.0, -0.0,
                UserDict(nested=MappingProxyType({'empty': (), 'text': 'x'}))),
        }))

    def test_boolean_integer_and_float_identity_remains_distinct(self):
        self.assertEqual(len({canonical({'value': v}) for v in (True, 1, 1.0)}), 3)
        self.assertEqual(len({digest({'value': v}) for v in (False, 0, 0.0)}), 3)

    def test_container_subclass_iteration_keeps_existing_encoding(self):
        class ListOverride(list):
            def __iter__(self):
                return iter(['overridden'])
        class TupleOverride(tuple):
            def __iter__(self):
                return iter(['overridden'])
        class DictOverride(dict):
            def items(self):
                return {'overridden': 1}.items()
        for value in (ListOverride([1, 2]), TupleOverride((1, 2)), DictOverride(x=2)):
            with self.subTest(kind=type(value).__name__):
                self.assert_wire_unchanged(value)

    def test_nonfinite_and_unsupported_nested_values_remain_rejected(self):
        for value in (float('nan'), float('inf'), float('-inf'), object(), {1, 2}, datetime.now()):
            wrapped = MappingProxyType({'rows': (UserDict(value=value),)})
            with self.subTest(kind=type(value).__name__), self.assertRaises((ValueError, TypeError)):
                canonical(wrapped)

    def test_mutable_input_is_reencoded_on_every_call(self):
        nested = {'rows': [1, {'value': 2}]}
        frozen_view = MappingProxyType(nested)
        before = digest(frozen_view)
        nested['rows'][1]['value'] = 3
        self.assertNotEqual(digest(frozen_view), before)
        self.assert_wire_unchanged(frozen_view)

    def test_seeded_nested_json_and_mapping_variants_match_original_wire(self):
        rng = random.Random(417)
        def value(depth):
            if depth == 0:
                return rng.choice([None, True, False, 1, 2.5, '東京', 'é'])
            kind = rng.randrange(5)
            items = [value(depth-1) for _ in range(rng.randrange(5))]
            if kind == 0:
                return items
            if kind == 1:
                return tuple(items)
            mapping = {str(i): item for i, item in enumerate(items)}
            return MappingProxyType(mapping) if kind == 2 else UserDict(mapping) if kind == 3 else mapping
        for i in range(250):
            with self.subTest(case=i):
                self.assert_wire_unchanged(value(4))


class FreshReadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.ledger, self.store, self.service, self.clock = fixture(Path(self.temp.name))

    def test_recurring_membership_keeps_new_request_provenance_and_fresh_reads(self):
        request(self.ledger, rid='first')
        self.ledger.cancel_request('cancel-first', owner_id='manual', request_id='first', actor_id='manual')
        request(self.ledger, rid='second')
        states = self.ledger.states()
        self.assertEqual(states[1].applied, states[3].applied)
        self.assertEqual(states[1].reasons_for('MSFT', 'hot'), (('manual', 'first'),))
        self.assertEqual(states[3].reasons_for('MSFT', 'hot'), (('manual', 'second'),))
        expected = [s.payload() for s in states]
        object.__setattr__(states[1].applied, 'hot', frozenset({'FORGED'}))
        self.assertEqual([s.payload() for s in self.ledger.states()], expected)

    def test_plain_journal_metadata_is_detached_from_subsequent_reads(self):
        request(self.ledger)
        self.service.cycle()
        rows = self.service.journal.revisions()
        expected = canonical(rows)
        rows[-1]['proposal']['metadata']['request_state']['desired']['uni'].append('FORGED')
        rows[-1]['proposal']['metadata']['request_state']['active_requests'].clear()
        self.assertEqual(canonical(self.service.journal.revisions()), expected)
        self.assertIsNone(self.service.snapshot()['pending'])

    def test_new_native_plain_receipts_still_get_an_independent_wire_hash_check(self):
        rows = list(self.store.validated_membership_revision_payloads())
        rows[0]['proposal']['reason'] = 'changed without a new hash'
        with patch.object(self.store, 'validated_membership_revision_payloads', return_value=rows):
            with self.assertRaisesRegex(ValueError, 'content hash'):
                self.service.journal.revisions()


if __name__ == '__main__':
    unittest.main()
