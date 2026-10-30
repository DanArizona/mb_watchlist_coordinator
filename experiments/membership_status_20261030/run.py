"""Independent membership display and short offline Windows qualification."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import socket
import sys
import time
import unittest
from uuid import uuid4

ROOT = Path(__file__).resolve().parent
CHECKS = 30
sys.dont_write_bytecode = True
sys.path[:0] = [str(ROOT/'coordinator/src'), str(ROOT/'market_data/src'), str(ROOT/'coordinator/tests')]


def guard():
    manifest = json.loads((ROOT/'SOURCE_INVENTORY.json').read_text())
    if manifest['contract'] != 'membership-status-source-v1':
        raise ValueError('Membership status source inventory required')
    for name, expected in manifest['files'].items():
        path = ROOT/name
        if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError('Membership status source bytes differ')
    return manifest


def deny_network():
    def denied(*args, **kwargs):
        raise OSError('Network access is disabled in the membership display process')
    socket.socket.connect = socket.socket.connect_ex = socket.create_connection = socket.getaddrinfo = denied


def gui_proof(folder):
    """Actual Tk window with synthetic files, five observed phases and auto-close."""
    from test_daily_membership_status import SyntheticMembership
    from mb_watchlist_coordinator.daily_membership_status import MembershipStatusReader, MembershipDisplayModel
    from mb_watchlist_coordinator.daily_membership_window import MembershipWindow
    from mb_watchlist_coordinator.daily_supervision import atomic_json
    scene = SyntheticMembership(folder/'gui-fixture')
    model = MembershipDisplayModel(MembershipStatusReader(scene.state_root, clock=lambda: scene.now))
    window = MembershipWindow(model, title='OFFLINE DEMO - synthetic membership only', interval_ms=100)
    tk_version = str(window.root.tk.call('info', 'patchlevel'))
    phases, errors = [], []
    began = time.monotonic()
    last_change = began
    original = json.loads((scene.state_root/'session.json').read_text())

    def advance():
        nonlocal last_change
        try:
            now = time.monotonic()
            if now-began > 25:
                raise AssertionError('GUI phases did not finish within 25 seconds')
            value = window.last_value
            ready = value is not None and now-last_change >= 1
            if ready and len(phases) == 0 and value.get('fresh') and value['counts']['hot'] == 0:
                phases.append('opening_empty_lists')
                scene.add(); scene.quote()
                last_change = now
            elif ready and len(phases) == 1 and value.get('fresh') and value['counts'] == {'hot': 1, 'focus': 1, 'uni': 1}:
                phases.append('new_symbol_visible_in_all_three_lists')
                atomic_json(scene.state_root/'session.json', {})
                last_change = now
            elif ready and len(phases) == 2 and not value.get('fresh') and value.get('last_verified'):
                if value['last_verified']['counts']['hot'] != 1:
                    raise AssertionError('Failed read lost the last verified Hot list')
                phases.append('failed_read_retains_lists_with_error_banner')
                atomic_json(scene.state_root/'session.json', original)
                last_change = now
            elif ready and len(phases) == 3 and value.get('fresh'):
                phases.append('read_recovered_without_baseline_reset')
                scene.controller(stop={'reason': 'offline_demo_complete'})
                last_change = now
            elif ready and len(phases) == 4 and value.get('fresh') and value['controller']['state'] == 'STOPPED':
                phases.append('stopped_controller_and_membership_retained')
                window.close()
                return
            if not window.closed:
                window.root.after(50, advance)
        except Exception as error:
            errors.append(type(error).__name__)
            window.close()

    window.root.after(50, advance)
    try:
        window.run()
    finally:
        window.close()
        window.pool.shutdown(wait=True, cancel_futures=True)
    complete = len(phases) == 5 and not errors
    return {'result': 'PASS' if complete else 'FAILED', 'actual_tk_window': True,
        'tk_version': tk_version, 'observed_phases': phases, 'errors': errors,
        'display_refreshes': window.read_count, 'auto_closed': complete,
        'read_executor_stopped': True, 'synthetic_only': True,
        'provider_requests': 0, 'controller_or_poller_started': False}


def verify(manifest):
    from mb_watchlist_coordinator.daily_membership_status import MembershipDisplayModel, MembershipStatusReader
    from test_daily_membership_status import SyntheticMembership
    folder = ROOT/'runs'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ_')+uuid4().hex[:8])
    folder.mkdir(parents=True, exist_ok=False)
    print('OFFLINE persistent membership display: synthetic journals and saved health only.', flush=True)
    print('30 focused checks. On Windows, a synthetic preview window opens for about six seconds and closes itself.', flush=True)
    began = time.monotonic()
    suite = unittest.defaultTestLoader.loadTestsFromNames([
        'test_daily_membership_status.MembershipStatusTests', 'test_daily_membership_window.WindowTests'])
    if suite.countTestCases() != CHECKS:
        raise ValueError('Focused membership display check count differs')
    class Log:
        def __init__(self, file): self.file = file
        def write(self, value): self.file.write(value); sys.stdout.write(value)
        def flush(self): self.file.flush(); sys.stdout.flush()
    with (folder/'tests.log').open('w', encoding='utf-8') as output:
        result = unittest.TextTestRunner(stream=Log(output), verbosity=2).run(suite)
    scene = SyntheticMembership(folder/'native-proof', universe=('MSFT', *('Z'+str(i).zfill(4) for i in range(550))))
    scene.add(); scene.quote()
    proof = MembershipDisplayModel(MembershipStatusReader(scene.state_root, clock=lambda: scene.now)).refresh()
    (folder/'membership-snapshot.json').write_text(json.dumps(proof, indent=2)+'\n')
    gui = {'result': 'NOT_EXERCISED', 'reason': 'No local desktop; actual Windows preview remains due'}
    if result.wasSuccessful() and (os.name == 'nt' or os.environ.get('DISPLAY')):
        try:
            gui = gui_proof(folder)
        except Exception as error:
            gui = {'result': 'FAILED', 'error_type': type(error).__name__}
    guard()
    passed = result.wasSuccessful() and not result.skipped and proof['fresh'] and (os.name != 'nt' or gui['result'] == 'PASS')
    report = {'contract': 'membership-status-offline-qualification-v1',
        'result': 'PASS' if passed else 'FAILED', 'tests': result.testsRun,
        'passed': result.testsRun-len(result.failures)-len(result.errors)-len(result.skipped),
        'failures': len(result.failures), 'errors': len(result.errors), 'skipped': len(result.skipped),
        'failed_tests': [t.id() for t, _ in result.failures+result.errors],
        'seconds': time.monotonic()-began, 'platform': sys.platform, 'python': list(sys.version_info[:3]),
        'source': manifest['source'], 'windows_checks_passed': bool(passed and os.name == 'nt'),
        'clock_scope': 'Logical future session in synthetic fixtures only; the normal display uses actual UTC',
        'source_inventory_sha256': hashlib.sha256((ROOT/'SOURCE_INVENTORY.json').read_bytes()).hexdigest(),
        'display_summary': {'hot': 'complete current list', 'focus': 'current additions beyond opening r1',
            'uni': 'current additions beyond opening r1'},
        'native_membership_proof': {'effective_revision': proof.get('effective_revision'),
            'counts': proof.get('counts'), 'last_hot_acquisition': proof.get('last_hot_acquisition'),
            'original_r1_preserved': proof.get('baseline_sha256') == scene.r1.content_sha256},
        'gui_proof': gui, 'network': 'denied', 'actual_vault_access': False,
        'actual_provider_used': False, 'production_changes': False, 'production_hot_enabled': False,
        'controller_runtime_changed': False, 'native_source_changed': False,
        'unchanged_provider_recovery_and_capacity_proofs_repeated': False,
        'remaining': ['Actual Windows qualification and returned CMD prompt',
            'Remaining daily operating delivery, settings and deployment/rollback review']}
    (folder/'verification.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2), flush=True)
    print('Saved report:', folder/'verification.json', flush=True)
    return 0 if passed else 1


def main(argv):
    manifest = guard()
    deny_network()
    if argv == ['verify']:
        return verify(manifest)
    if not argv or argv[0] != 'show':
        raise ValueError('Use verify or show --state-root ABSOLUTE_PATH [--once]')
    from mb_watchlist_coordinator.daily_membership_window import main as show
    return show(argv[1:])


if __name__ == '__main__':
    try:
        raise SystemExit(main(sys.argv[1:]))
    except Exception as error:
        print('Membership display refused:', type(error).__name__, flush=True)
        raise SystemExit(1)
