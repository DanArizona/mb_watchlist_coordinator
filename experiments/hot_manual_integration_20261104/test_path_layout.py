"""Local path-layout checks only; these do not execute Hot integration fixtures."""
import ast
import importlib.util
from pathlib import Path, PureWindowsPath
from tempfile import TemporaryDirectory
import unittest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('hot_manual_verifier_paths', HERE / 'verify.py')
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)


class CompactEvidencePathTests(unittest.TestCase):
    def setUp(self):
        self.coord = PureWindowsPath(
            r'C:\Users\danla\hot_reliability_20261103\mb_watchlist_coordinator')
        self.paths = verifier.evidence_paths(self.coord, '20261104T155229Z', '65a2486c')

    def test_reported_old_directory_is_252_characters(self):
        old = (self.coord / 'output' / 'hot_manual_integration_20261104'
               / '20261104T155229681584Z-65a2486c' / 'proofs' / 'mixed'
               / 'test_mixed_admission_native_quotes_audit_and_replay'
               / 'quote_observation_journal_v2_api_opening_2026-11-05')
        self.assertEqual(len(str(old)), 252)
        self.assertGreater(len(str(old / '2026-11-05.sqlite3')), 260)

    def test_compact_layout_passes_with_native_journal_and_sidecars(self):
        verifier.check_windows_path_budget(self.paths)
        for root in (self.paths['mixed'] / 'ok', self.paths['mixed'] / 'gap',
                     self.paths['owned']):
            directory = root / 'quote_observation_journal_v2_api_opening_2026-11-05'
            self.assertLess(len(str(directory)), 240)
            for name in ('2026-11-05.sqlite3', '2026-11-05.sqlite3-wal',
                         '2026-11-05.sqlite3-shm',
                         '2026-11-05.hot.e77.poller.sqlite3-journal',
                         '2026-11-05.hot.e77.poller.daily-collector.json',
                         '2026-11-05.daily-hot-provider-stop.json'):
                self.assertLess(len(str(directory / name)), 240)

    def test_overlong_checkout_fails_before_any_fixture(self):
        paths = verifier.evidence_paths(self.coord / ('long_' * 12),
                                        '20261104T155229Z', '65a2486c')
        with self.assertRaisesRegex(ValueError, 'path budget exceeded'):
            verifier.check_windows_path_budget(paths)

    def test_all_paths_are_inside_the_isolated_checkout(self):
        for path in self.paths.values():
            self.assertTrue(path.is_relative_to(self.coord / 'output' / 'hmi'))
        self.assertFalse(self.paths['owned'].is_relative_to(self.paths['mixed']))
        self.assertNotEqual(self.paths['burst'], self.paths['owned'])

    def test_different_run_ids_do_not_reuse_failed_evidence(self):
        other = verifier.evidence_paths(self.coord, '20261104T155229Z', 'aaaaaaaa')
        self.assertTrue(set(other.values()).isdisjoint(self.paths.values()))

    def test_short_aliases_match_full_unchanged_selectors(self):
        tree = ast.parse((HERE.parents[1] / 'tests' /
                          'test_combined_hot_reliability.py').read_text(encoding='utf-8'))
        node = next(n for n in tree.body if isinstance(n, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == 'PROOF_CASE_DIRS'
                            for t in n.targets))
        aliases = ast.literal_eval(node.value)
        self.assertEqual(set(aliases), {t.rsplit('.', 1)[1] for t in verifier.TESTS[:2]})
        self.assertEqual(set(aliases.values()), {'ok', 'gap'})
        self.assertEqual(len(verifier.TESTS), 8)
        self.assertEqual(len(set(verifier.TESTS)), 8)

    def test_layout_and_preflight_do_not_create_output(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            paths = verifier.evidence_paths(root, '20261104T155229Z', '65a2486c')
            verifier.check_windows_path_budget(paths)
            self.assertEqual(list(root.iterdir()), [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
