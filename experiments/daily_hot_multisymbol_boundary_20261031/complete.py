"""Complete p85 qualification without repeating its 109 checks or paced run."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import socket
import sys
import time
import unittest
from uuid import uuid4

ROOT = Path(__file__).resolve().parent
ORIGINAL_INVENTORY = '0c5f9d7a2dfcdd72ffc9d3d07b7ea2e4b9528139a948496e4fd921476fdf6ffe'
ORIGINAL_COMMIT = 'e7cb9b6fa786170455dbfe7c3226d8b18227487e'
ORIGINAL_RUN = '20261031T021243Z_46ab7a08'
FAILED_TEST = ('test_daily_multisymbol_owned.MultiOwnedTests.'
    'test_paced_forty_symbol_admissions_cross_period_while_uni_focus_keep_writing')
sys.dont_write_bytecode = True


def guard(root, expected=None):
    """Bootstrap before importing the frozen packet's source."""
    root = Path(root).resolve()
    path = root/'SOURCE_INVENTORY.json'
    if path.is_symlink(): raise ValueError('Regular source inventory required')
    raw = path.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    if expected is not None and sha != expected: raise ValueError('Frozen packet inventory differs')
    files = json.loads(raw)['files']
    actual = {p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()
        and p.relative_to(root).parts[0] != 'runs' and p != path}
    if set(files) != actual: raise ValueError('Source file set differs')
    for name, checksum in files.items():
        file = root/name
        if file.is_symlink() or not file.resolve().is_relative_to(root) or hashlib.sha256(file.read_bytes()).hexdigest() != checksum:
            raise ValueError('Source bytes differ: '+name)
    return sha


def validate_prior(report):
    """Reuse only this exact failed test after all 109 focused cases passed."""
    required = {'contract': 'daily-hot-multisymbol-offline-qualification-v1',
        'result': 'FAILED', 'tests': 110, 'passed': 109, 'failures': 1,
        'errors': 0, 'skipped': 0, 'focused_checks': 109, 'platform': 'win32',
        'python': [3, 12, 13], 'source_inventory_sha256': ORIGINAL_INVENTORY,
        'failed_tests': [FAILED_TEST], 'network': 'denied', 'synthetic_sdk_only': True,
        'actual_vault_access': False, 'actual_provider_used': False,
        'production_changes': False, 'production_hot_enabled': False}
    if any(report.get(k) != v for k, v in required.items()):
        raise ValueError('Original 109/110 Windows qualification does not match')
    source = report.get('source', {})
    if source.get('coordinator_commit') != ORIGINAL_COMMIT or source.get('market_data_commit') != 'd37d2c37e3ac9cc2c860d0a2313a1526e30fd23e':
        raise ValueError('Original source commits differ')
    if report.get('capacity_proof') is not None or report.get('paced_proof', {}).get('result') != 'FAILED':
        raise ValueError('Original missing-capacity/failed-owned disposition differs')
    return {'original_result': 'FAILED', 'original_tests': 110, 'original_passed': 109,
        'original_failures': 1, 'reused_focused_checks': 109, 'focused_checks_repeated': False,
        'paced_run_repeated': False, 'original_failed_test': FAILED_TEST}


def deny_network():
    def denied(*args, **kwargs): raise OSError('Network denied in offline completion')
    socket.socket.connect = socket.socket.connect_ex = socket.create_connection = socket.getaddrinfo = denied


def complete(source, prior):
    source, prior = Path(source).resolve(), Path(prior).resolve()
    own_inventory = guard(ROOT)
    guard(source, ORIGINAL_INVENTORY)
    if prior.parent != source/'runs' or prior.name != ORIGINAL_RUN:
        raise ValueError('Exact preserved Windows85 run required')
    sys.path[:0] = [str(ROOT), str(source/'coordinator/src'),
        str(source/'market_data/src'), str(source/'coordinator/tests')]
    from mb_watchlist_coordinator.daily_operator import release_info
    from mb_watchlist_coordinator.recovery_workers import atomic_json
    from multisymbol_closed_checks import assess_closed_owned, retained_fingerprints
    deny_network()
    release_info(source)
    original_bytes = (prior/'verification.json').read_bytes()
    original = json.loads(original_bytes)
    reused = validate_prior(original)
    before = retained_fingerprints(prior)
    folder = ROOT/'runs'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ_')+uuid4().hex[:8])
    folder.mkdir(parents=True, exist_ok=False)
    (folder/'original-verification.json').write_bytes(original_bytes)
    marker = source/'runs/windows-qualification.json'
    if marker.exists(): shutil.copyfile(marker, folder/'previous-windows-qualification.json')
    print('OFFLINE completion: 17 boundary/evidence checks, read-only reassessment of the retained Windows run, then the missing full-size synthetic history proof.', flush=True)
    print('The 109 passing checks and the 200-second paced burst are reused. No password, API or production changes.', flush=True)
    print('Allow several minutes and about 1.1 GB of new synthetic evidence. Original deadlines and cadence remain.', flush=True)
    began = time.monotonic()
    reassessed = capacity = None
    problem = None
    suite = unittest.defaultTestLoader.loadTestsFromNames(['test_multisymbol_closed_checks',
        'test_daily_source_stop_boundary', 'test_multisymbol_completion'])
    class Log:
        def __init__(self, file): self.file = file
        def write(self, value): self.file.write(value); sys.stdout.write(value)
        def flush(self): self.file.flush(); sys.stdout.flush()
    with (folder/'tests.log').open('w', encoding='utf-8') as log:
        output = Log(log)
        checked = unittest.TextTestRunner(stream=output, verbosity=1).run(suite)
        try:
            if not checked.wasSuccessful() or checked.skipped:
                raise AssertionError('Boundary qualification tests failed')
            reassessed = assess_closed_owned(prior/'owned')
            if (reassessed['owner'] != original['paced_proof']['owner'] or
                    reassessed['background_acquisitions'] != original['paced_proof']['background_acquisitions'] or
                    original['paced_proof']['writer_errors']):
                raise ValueError('Retained owner/writer evidence differs from original report')
            print(json.dumps({'phase': 'retained_owned_reassessment', 'result': 'PASS',
                'readiness': reassessed['source_readiness_before_stop'],
                'full_roster_before_rollover': reassessed['full_roster_acquisitions_before_rollover'],
                'full_roster_after_rollover': reassessed['full_roster_acquisitions_after_rollover']}), flush=True)
            path = source/'coordinator/experiments/daily_hot_multisymbol_20261030/history_probe.py'
            spec = importlib.util.spec_from_file_location('unchanged_multi_history_proof', path)
            history = importlib.util.module_from_spec(spec); spec.loader.exec_module(history)
            capacity = history.run(folder/'multi_history_full', slots=9312, periods=True, background=True)
        except Exception as error:
            import traceback
            traceback.print_exc(file=output)
            problem = type(error).__name__
    guard(source, ORIGINAL_INVENTORY); guard(ROOT, own_inventory)
    unchanged = retained_fingerprints(prior) == before
    passed = (checked.wasSuccessful() and not checked.skipped and problem is None and unchanged and
        reassessed is not None and capacity is not None and capacity['result'] == 'PASS')
    report = {'contract': 'daily-hot-multisymbol-offline-qualification-v1',
        'qualification_revision': 'retained-run-stop-boundary-completion-v1',
        'result': 'PASS' if passed else 'FAILED', 'tests': checked.testsRun,
        'passed': checked.testsRun-len(checked.failures)-len(checked.errors)-len(checked.skipped),
        'failures': len(checked.failures), 'errors': len(checked.errors), 'skipped': len(checked.skipped),
        'failed_tests': [t.id() for t, _ in checked.failures+checked.errors],
        'completion_error_type': problem, 'seconds': time.monotonic()-began,
        'platform': sys.platform, 'python': list(sys.version_info[:3]),
        'windows_checks_passed': bool(passed and os.name == 'nt'),
        'source_inventory_sha256': ORIGINAL_INVENTORY, 'completion_inventory_sha256': own_inventory,
        'source': original['source'], 'original_run': str(prior),
        'original_verification_sha256': hashlib.sha256(original_bytes).hexdigest(),
        'original_evidence_preserved': unchanged, 'prior_windows_components': reused,
        'corrected_owned_reassessment': reassessed, 'capacity_proof': capacity,
        'controller_runtime_changed': False, 'original_deadlines_and_cadence_unchanged': True,
        'network': 'denied', 'actual_vault_access': False, 'actual_provider_used': False,
        'production_changes': False, 'production_hot_enabled': False, 'proposed_values_adopted': False,
        'provider_capacity_qualified': False, 'full_day_capacity_qualified': False,
        'operating_release_qualified': False, 'production_activation_approved': False,
        'remaining': ['Exact-candidate read-only deployment review',
            'Concrete 40-symbol settings/integrity scope and first production activation approval']}
    atomic_json(folder/'verification.json', report)
    # This is a mutable acceptance pointer, not the original failed verdict.
    # Preserve its previous bytes above; never rewrite the closed run.
    if passed and os.name == 'nt': atomic_json(marker, report)
    print(json.dumps(report, indent=2), flush=True)
    print('Saved report:', folder/'verification.json', flush=True)
    print('Original Windows85 verification.json remains FAILED and unchanged.', flush=True)
    return 0 if passed else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', default=r'C:\Users\danla\hot85\p85')
    parser.add_argument('--prior-run', default=r'C:\Users\danla\hot85\p85\runs\20261031T021243Z_46ab7a08')
    args = parser.parse_args()
    return complete(args.source_root, args.prior_run)


if __name__ == '__main__':
    try: raise SystemExit(main())
    except KeyboardInterrupt: raise SystemExit(130)
    except Exception as error:
        print('Offline completion refused:', type(error).__name__, str(error), flush=True)
        raise SystemExit(1)
