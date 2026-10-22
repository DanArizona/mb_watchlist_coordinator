from __future__ import annotations

from contextlib import closing
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('growth_qualification',
    ROOT / 'experiments/coordinator_growth_20261022/qualify.py')
growth = importlib.util.module_from_spec(spec)
spec.loader.exec_module(growth)


class NativeGrowthTests(unittest.TestCase):
    def test_native_small_history_has_expected_dispositions_and_read_only_measurement(self):
        with tempfile.TemporaryDirectory(prefix='growth qualification with spaces ') as folder:
            path = Path(folder) / 'fixture'
            metadata = growth.build_fixture(path, rounds=2)
            self.assertEqual(metadata['receipts'], 40)
            self.assertEqual(metadata['publications'], 8)
            self.assertEqual(metadata['transport_submissions'],
                {'inserted': 40, 'already_recorded': 2, 'conflicting_id': 2})
            self.assertEqual(metadata['receipt_kinds']['tick'], 2)
            self.assertGreater(metadata['receipt_dispositions']['accepted'], 20)
            sizes = [len(x['membership']['hot']) for x in metadata['expected_checkpoints']]
            self.assertEqual(sizes, [40, 41, 40, 0] * 2)
            self.assertTrue(growth.measure(path, 2)['fixture_bytes_unchanged'])
            self.assertTrue(growth.cold_reopen(path)['snapshot_identical'])

    def test_altered_fixture_refused_before_measurement(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'fixture'
            growth.build_fixture(path, rounds=1)
            with closing(sqlite3.connect(path / 'requests.sqlite3')) as c, c:
                c.execute("UPDATE request_event SET event_sha256='broken' WHERE sequence=1")
            before = growth.files_digest(path)
            with self.assertRaisesRegex(ValueError, 'bytes changed'):
                growth.measure(path, 1)
            self.assertEqual(growth.files_digest(path), before)

    def test_overbudget_construction_is_failure_and_does_not_claim_final_fixture(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'fixture'
            with self.assertRaises(TimeoutError):
                growth.build_fixture(path, rounds=1, budget_seconds=-1)
            self.assertFalse((path / 'fixture.json').exists())

    def test_updated_inventory_does_not_hide_native_history_corruption(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'fixture'
            growth.build_fixture(path, rounds=1)
            with closing(sqlite3.connect(path / 'publication.sqlite3')) as c, c:
                c.execute("UPDATE publication_event SET event_sha256='broken' WHERE sequence=1")
            manifest = json.loads((path / 'fixture.json').read_text())
            manifest['files_sha256'] = growth.files_digest(path)
            growth.dump(path / 'fixture.json', manifest)
            with self.assertRaisesRegex(ValueError, 'sequence/hash chain'):
                growth.cold_reopen(path)


if __name__ == '__main__':
    unittest.main()
