"""Native publication and retained source facts remain equivalent after coalescing."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
import sqlite3
from contextlib import closing

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('nasdaq_reuse_qualification',ROOT/'experiments/nasdaq_request_reuse_20261022/qualify.py')
qualification=importlib.util.module_from_spec(spec);spec.loader.exec_module(qualification)

class NativeReuseWorkloadTests(unittest.TestCase):
    def test_paired_native_source_updates_and_membership_checkpoints_match(self):
        rows=[{'symbol':symbol,'halt_time_et':at,'reason_code':'LUDP'} for symbol,at in
              [('AAPL','09:31:00'),('MSFT','09:32:00'),('AAPL','09:33:00')]]
        with tempfile.TemporaryDirectory(prefix='native reuse with spaces ') as folder:
            a=qualification.build(Path(folder)/'per-event',rows,False,samples=2)
            b=qualification.build(Path(folder)/'reuse',rows,True,samples=2)
            self.assertEqual((a['coordinator_receipts'],b['coordinator_receipts']),(3,2))
            self.assertEqual(b['reuse_bindings'],1)
            self.assertEqual(a['source_facts_sha256'],b['source_facts_sha256'])
            self.assertEqual(a['membership_checkpoints_sha256'],b['membership_checkpoints_sha256'])
            self.assertTrue(a['native_audit'] and b['native_audit'])
            for mode,result in [('per-event',a),('reuse',b)]:
                with closing(sqlite3.connect(Path(folder)/mode/'membership.sqlite3')) as c:
                    self.assertEqual(c.execute('select count(*) from sampling_membership_revision').fetchone()[0],result['membership_revisions_including_anchor'])

    def test_measurement_window_is_before_active_request_expiry(self):
        self.assertEqual(qualification.STOP.strftime('%H:%M:%S'),'16:00:00')

    def test_workload_counts_match_observed_days_and_margin_is_explicit(self):
        cases=qualification.datasets()
        self.assertEqual({k:(len(v),len({r['symbol'] for r in v})) for k,v in cases.items()},
                         {'typical':(42,21),'busiest':(107,27),'margin':(160,40)})
