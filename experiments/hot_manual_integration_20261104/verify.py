"""Bounded offline qualification of the pinned Nasdaq/manual/Hot composition.

This runner does not create an operating review or activate production. All
provider responses and credentials used by selected fixtures are synthetic.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest
from uuid import uuid4

NATIVE_COMMIT = '53fc9d62155063b3ae2bc5f0bacfd604866241e0'
COORDINATOR_BASE = '5b04b479164eb01e6d8eb2b142f70bb9dabf629c'
TESTS = (
    'test_combined_hot_reliability.CombinedHotReliabilityTests.test_mixed_admission_native_quotes_audit_and_replay',
    'test_combined_hot_reliability.CombinedHotReliabilityTests.test_mixed_deadline_restart_retains_gap_and_never_retries_slot',
    'test_daily_manual_identity_owned.ManualIdentityOwnedTests.test_owned_controller_collects_manual_and_nasdaq_roster_and_fences_ui_after_stop',
    'test_daily_manual_identity.DailyManualIdentityTests.test_forty_mixed_outside_admissions_share_capacity_and_overflow_without_extra_call',
    'test_daily_manual.DailyManualTests.test_concurrent_sources_cannot_both_take_fortieth_slot',
    'test_daily_manual_identity.DailyManualIdentityTests.test_outside_own_demotion_and_restriction_reuse_original_identity',
    'test_daily_manual_identity.DailyManualIdentityTests.test_nasdaq_and_manual_reuse_one_exact_symbol_confirmation',
    'test_daily_manual_owned.DailyManualOwnedTests.test_manual_resume_retains_budgets_and_fences_the_old_window',
)


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(['git', '-C', str(root), *args], text=True).strip()


def check_checkout(root: Path) -> str:
    if not root.is_dir():
        raise ValueError(f'Checkout missing: {root}')
    if Path(git(root, 'rev-parse', '--show-toplevel')).resolve() != root:
        raise ValueError(f'Expected a repository root: {root}')
    if git(root, 'status', '--porcelain', '--untracked-files=no'):
        raise ValueError(f'Tracked checkout changes must be preserved/reviewed first: {root}')
    for name in git(root, 'ls-files', '--others', '--exclude-standard').splitlines():
        if name.endswith('.py') and name.split('/')[0] in {'src', 'tests', 'probes'}:
            raise ValueError(f'Untracked importable source must be reviewed first: {root / name}')
    return git(root, 'rev-parse', 'HEAD')


def evidence_paths(coord: Path, stamp: str, nonce: str) -> dict[str, Path]:
    """Compact retained evidence under this checkout; never reuse an old run."""
    root = coord / 'output' / 'hmi' / (stamp + '-' + nonce)
    return {'run': root, 'mixed': root / 'p' / 'm',
            'owned': root / 'p' / 'o', 'burst': root / 'p' / 'b.json'}


def check_windows_path_budget(paths) -> None:
    """Reserve space for unchanged journal, sidecar and worker filenames.

    This conservative runner budget avoids depending on system long-path
    settings. It does not shorten or change native evidence filenames.
    """
    fixture_roots = (paths['mixed'] / 'ok', paths['mixed'] / 'gap', paths['owned'])
    for root in fixture_roots:
        units = len(str(root).encode('utf-16-le')) // 2
        if units + 128 > 240:
            raise ValueError(
                f'Windows evidence path budget exceeded: {root}. '
                'Use a shorter isolated checkout path; no fixture has started.')


class Tee:
    def __init__(self, *streams):
        self.streams = streams

    def write(self, text):
        for stream in self.streams:
            stream.write(text)
            stream.flush()
        return len(text)

    def flush(self):
        for stream in self.streams:
            stream.flush()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native', required=True, type=Path)
    parser.add_argument('--coordinator', required=True, type=Path)
    args = parser.parse_args()
    native, coord = args.native.resolve(), args.coordinator.resolve()
    run_root = None
    try:
        native_head, coord_head = check_checkout(native), check_checkout(coord)
        if native_head != NATIVE_COMMIT:
            raise ValueError(f'Wrong native checkpoint: {native_head}; expected {NATIVE_COMMIT}')
        if not git(coord, 'branch', '--show-current').startswith('experiment/'):
            raise ValueError('Use an isolated Coordinator experiment branch, never main')
        subprocess.run(['git', '-C', str(coord), 'merge-base', '--is-ancestor',
                        COORDINATOR_BASE, 'HEAD'], check=True)
        changed = git(coord, 'diff', '--name-only', COORDINATOR_BASE, 'HEAD', '--', 'src', 'tests')
        if any(p != 'tests/test_combined_hot_reliability.py' for p in changed.splitlines()):
            raise ValueError('Runtime or accepted fixtures differ from the pinned Coordinator base')
        code_paths = [coord / 'src', native / 'src', coord / 'tests', native / 'tests', coord]
        sys.path[:0] = [str(p) for p in code_paths]
        os.environ['PYTHONPATH'] = os.pathsep.join(map(str, code_paths))
        for module, expected in (('mb_market_data', native), ('mb_watchlist_coordinator', coord)):
            actual = Path(importlib.import_module(module).__file__).resolve()
            if not actual.is_relative_to(expected / 'src'):
                raise ValueError(f'Wrong import source for {module}: {actual}')
        # Resolve every exact selector before starting any test fixture.
        for selector in TESTS:
            module_name, class_name, method_name = selector.rsplit('.', 2)
            test_class = getattr(importlib.import_module(module_name), class_name)
            if not issubclass(test_class, unittest.TestCase) or not callable(getattr(test_class, method_name)):
                raise ValueError(f'Invalid test selector: {selector}')
        suite = unittest.defaultTestLoader.loadTestsFromNames(TESTS)
        if suite.countTestCases() != len(TESTS):
            raise ValueError('Unexpected discovered test count; no partial qualification')
        started_at = datetime.now(timezone.utc)
        stamp = started_at.strftime('%Y%m%dT%H%M%SZ')
        paths = evidence_paths(coord, stamp, uuid4().hex[:8])
        if os.name == 'nt':
            check_windows_path_budget(paths)
        paths['run'].mkdir(parents=True, exist_ok=False)
        run_root = paths['run']
        mixed_root = paths['mixed']
        mixed_root.mkdir(parents=True, exist_ok=False)
        # No broad environment can redirect test fixtures into production.
        for key in tuple(os.environ):
            if key.startswith('MB_') and ('PROOF' in key or key.endswith('_PROOF_DIR')):
                del os.environ[key]
        os.environ['MB_COMBINED_HOT_PROOF_ROOT'] = str(mixed_root)
        os.environ['MB_MANUAL_IDENTITY_PROOF_DIR'] = str(paths['owned'])
        os.environ['MB_MANUAL_IDENTITY_BURST_PROOF'] = str(paths['burst'])
        report = {
            'contract': 'nasdaq-manual-corrected-hot-integration-v1',
            'native_commit': native_head, 'coordinator_commit': coord_head,
            'coordinator_runtime_base': COORDINATOR_BASE,
            'python': sys.version, 'platform': sys.platform,
            'selectors': list(TESTS), 'result': 'STARTED',
            'started_at_utc': started_at.isoformat(),
            'evidence_layout': 'compact-windows-v2',
            'proof_paths': {'mixed_healthy': str(mixed_root / 'ok'),
                            'mixed_deadline': str(mixed_root / 'gap'),
                            'owned_outside_uni': str(paths['owned']),
                            'mixed_40_burst': str(paths['burst'])},
            'scope': 'synthetic inputs, real journals/native collector and owned test processes',
            'production_activation': False, 'real_provider_calls_requested': False,
            'full_day_provider_capacity_qualified': False,
        }
        report_path = run_root / 'result.json'
        report_path.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        print(f'Native checkpoint: {native_head}')
        print(f'Coordinator checkpoint: {coord_head}')
        print('OFFLINE COMBINED PROOF: no real credentials, live feed, or production journal.')
        print(f'Evidence: {run_root}', flush=True)
        start = time.monotonic()
        stdout, stderr = sys.stdout, sys.stderr
        try:
            with (run_root / 'console.txt').open('x', encoding='utf-8') as log:
                sys.stdout, sys.stderr = Tee(stdout, log), Tee(stderr, log)
                result = unittest.TextTestRunner(verbosity=2, failfast=True, stream=sys.stderr).run(suite)
        finally:
            sys.stdout, sys.stderr = stdout, stderr
        success = result.wasSuccessful() and result.testsRun == len(TESTS) and not result.skipped
        report.update(result='PASS' if success else 'FAIL', tests_run=result.testsRun,
                      failures=len(result.failures), errors=len(result.errors),
                      skipped=len(result.skipped), elapsed_seconds=time.monotonic() - start)
        report_path.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(report, indent=2))
        print(f'COMBINED OFFLINE QUALIFICATION: {report["result"]}')
        print('A deliberate missing slot must remain an underlying native audit FAIL.')
        print(f'Retained evidence: {report_path}')
        return 0 if success else 1
    except Exception as error:
        print(f'COMBINED OFFLINE QUALIFICATION: BLOCKED ({type(error).__name__}: {error})', file=sys.stderr)
        if run_root is not None:
            (run_root / 'runner_error.txt').write_text(
                f'{type(error).__name__}: {error}\n', encoding='utf-8')
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
