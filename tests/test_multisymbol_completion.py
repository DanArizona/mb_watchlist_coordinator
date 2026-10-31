"""Only the exact prior Windows result can supply reused qualification."""
from copy import deepcopy
import importlib.util
from pathlib import Path
import unittest

path = Path(__file__).with_name('complete.py')
if not path.is_file():
    path = Path(__file__).resolve().parents[1]/'experiments/daily_hot_multisymbol_boundary_20261031/complete.py'
spec = importlib.util.spec_from_file_location('completion_under_test', path)
completion = importlib.util.module_from_spec(spec)
spec.loader.exec_module(completion)


class CompletionEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.report = {'contract': 'daily-hot-multisymbol-offline-qualification-v1',
            'result': 'FAILED', 'tests': 110, 'passed': 109, 'failures': 1, 'errors': 0,
            'skipped': 0, 'focused_checks': 109, 'platform': 'win32', 'python': [3, 12, 13],
            'source_inventory_sha256': completion.ORIGINAL_INVENTORY,
            'source': {'coordinator_commit': completion.ORIGINAL_COMMIT,
                'market_data_commit': 'd37d2c37e3ac9cc2c860d0a2313a1526e30fd23e'},
            'failed_tests': [completion.FAILED_TEST], 'network': 'denied',
            'synthetic_sdk_only': True, 'actual_vault_access': False,
            'actual_provider_used': False, 'production_changes': False,
            'production_hot_enabled': False, 'capacity_proof': None,
            'paced_proof': {'result': 'FAILED'}}

    def test_matching_result_reuses_109_and_preserves_the_failure(self):
        before = deepcopy(self.report)
        result = completion.validate_prior(self.report)
        self.assertEqual(result['reused_focused_checks'], 109)
        self.assertEqual(result['original_result'], 'FAILED')
        self.assertEqual(self.report, before)

    def test_a_different_failed_test_cannot_use_this_completion(self):
        self.report['failed_tests'] = ['test_unrelated_failure']
        with self.assertRaises(ValueError): completion.validate_prior(self.report)

    def test_failed_or_skipped_focused_checks_cannot_be_reused(self):
        for edit in ({'errors': 1}, {'skipped': 1}, {'passed': 108}, {'failures': 2}):
            with self.subTest(edit=edit), self.assertRaises(ValueError):
                completion.validate_prior(dict(self.report, **edit))

    def test_a_different_packet_inventory_or_native_commit_is_refused(self):
        for edit in ({'source_inventory_sha256': '0'*64},
                     {'source': dict(self.report['source'], market_data_commit='f'*40)}):
            with self.subTest(edit=edit), self.assertRaises(ValueError):
                completion.validate_prior(dict(self.report, **edit))

    def test_another_original_disposition_is_not_silently_relabelled(self):
        for edit in ({'result': 'PASS'}, {'capacity_proof': {'result': 'FAILED'}},
                     {'paced_proof': {'result': 'PASS'}}):
            with self.subTest(edit=edit), self.assertRaises(ValueError):
                completion.validate_prior(dict(self.report, **edit))


if __name__ == '__main__': unittest.main()
