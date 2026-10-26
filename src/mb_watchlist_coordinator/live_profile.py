"""Operator composition of the accepted fresh bootstrap/runtime/profile APIs.

All injection arguments are trusted offline API seams, never configuration or
CLI modes. Existing runtime, native collector, budgets and timing gates remain
unchanged. A fresh outer owner is required for every separately invoked trial.
"""
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import threading
import time
import uuid

from .authenticated_startup import SessionPassword, receive_password
from .controller_bootstrap import (BootstrapSettings, EXPECTED_HELPERS,
    bootstrap_fresh, strict_json, _proposal)
from .installed_startup_probe import inspect_dependencies
from .outer_harness import OuterHarness, OuterSchedule
from .recovery_workers import atomic_json
from .sampling_requests import digest, plain, timestamp, utc_text
from .sampling_service import owner_lock

CONTRACT = 'credential-bound-live-hot-profile-v1'
PROFILES = ('ordinary', 'owned_worker_recovery')
STOP_REASONS = ('operator_stop', 'native_budget_exhausted')
CONFIG_KEYS = frozenset(('contract', 'settings', 'preflight_sha256', 'outer_root',
    'nonce', 'entry_path', 'source_root', 'source_inventory_sha256'))


def source_guard(root, expected_sha256=None):
    """The delivered inventory is immutable; only its runs tree is mutable."""
    root = Path(root).resolve()
    inventory = root/'SOURCE_INVENTORY.json'
    if inventory.is_symlink(): raise ValueError('Source inventory differs')
    raw = inventory.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    if expected_sha256 is not None and sha != expected_sha256:
        raise ValueError('Source inventory differs')
    expected = strict_json(raw)['files']
    actual = {p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()
        and p.relative_to(root).parts[0] != 'runs' and p != inventory}
    if set(expected) != actual: raise ValueError('Source set differs')
    for name, h in expected.items():
        p = root/name
        if (p.is_symlink() or not p.resolve().is_relative_to(root)
                or hashlib.sha256(p.read_bytes()).hexdigest() != h):
            raise ValueError('Source bytes differ')
    return sha


def bounded_json(path, maximum=2_000_000):
    p = Path(path)
    if not p.is_file() or p.is_symlink() or p.stat().st_size > maximum:
        raise ValueError('Bounded regular configuration required')
    return strict_json(p.read_text(encoding='utf-8'))


def configuration(settings, outer_root, source_root, source_inventory_sha256):
    plan = settings.plan()
    entry = Path(__file__).with_name('live_profile_entry.py').resolve()
    value = {'contract': CONTRACT, 'settings': asdict(settings),
        'preflight_sha256': plan.configuration_sha256, 'outer_root': str(Path(outer_root)),
        'nonce': settings.nonce, 'entry_path': str(entry), 'source_root': str(Path(source_root)),
        'source_inventory_sha256': source_inventory_sha256}
    value['settings']['catalog_symbols'] = list(settings.catalog_symbols)
    return value


def validate_configuration(value, expected_sha256, *, verify_source=source_guard):
    if (set(value) != CONFIG_KEYS or value['contract'] != CONTRACT
            or digest(value) != expected_sha256
            or not re.fullmatch('[0-9a-f]{64}', value['source_inventory_sha256'])):
        raise ValueError('Original launch configuration differs')
    raw = dict(value['settings']); raw['catalog_symbols'] = tuple(raw['catalog_symbols'])
    settings = BootstrapSettings(**raw); plan = settings.plan()
    outer, root = Path(value['outer_root']), Path(settings.experiment_root)
    source = Path(value['source_root'])
    if (plan.configuration_sha256 != value['preflight_sha256']
            or settings.catalog_mode != 'owned_directory' or settings.profile not in PROFILES
            or value['nonce'] != settings.nonce
            or not outer.is_absolute() or outer != outer.resolve() or not outer.name.startswith('outer_')
            or outer.parent != root.parent or source != source.resolve()
            or Path(value['entry_path']) != Path(__file__).with_name('live_profile_entry.py').resolve()):
        raise ValueError('Original entry/root binding differs')
    verify_source(source, value['source_inventory_sha256'])
    return plan


def worker_command(value, launch_path, launch_sha256):
    return (sys.executable, '-I', '-B', value['entry_path'], 'worker',
        str(launch_path), launch_sha256,
        str(Path(value['settings']['experiment_root'])/'authenticated-worker.json'))


def stop_request(value, launch_sha256):
    path = Path(value['outer_root']).parent/'STOP_REQUEST.json'
    if not path.exists(): return None
    request = bounded_json(path, 8192)
    if (set(request) != {'contract', 'nonce', 'launch_sha256', 'reason'}
            or request['contract'] != CONTRACT or request['nonce'] != value['nonce']
            or request['launch_sha256'] != launch_sha256 or request['reason'] not in STOP_REASONS):
        raise ValueError('Stop request binding differs')
    return request


def request_stop(value, launch_sha256, reason='operator_stop'):
    if reason not in STOP_REASONS: raise ValueError('Stop reason differs')
    path = Path(value['outer_root']).parent/'STOP_REQUEST.json'
    request = {'contract': CONTRACT, 'nonce': value['nonce'],
        'launch_sha256': launch_sha256, 'reason': reason}
    with owner_lock(path.with_suffix('.owner.lock')):
        if path.exists(): return stop_request(value, launch_sha256)
        atomic_json(path, request)
    return request


def previous_invocation_quiescent(runs):
    pointer = Path(runs)/'active_live_profile.json'
    if not pointer.exists(): return
    previous = bounded_json(pointer, 8192)
    path = Path(previous['launch_path'])
    if (previous.get('contract') != CONTRACT or previous.get('phase') != 'CLOSED'
            or not path.resolve().is_relative_to(Path(runs).resolve())):
        raise ValueError('Review the previous unclosed invocation before a new trial')
    result = bounded_json(path.parent/'summary.json')['outer']
    if any((result.get(name) or {}).get('status') != 'EXIT_OBSERVED'
            for name in ('cleanup', 'reporter_cleanup')):
        raise ValueError('Previous owned scope exits are not confirmed')


def run_controller(value, launch_path, launch_sha256, stream, *, clock=None,
        inventory=None, secure_api=None, catalog_acquirer=None, feed_factory=None,
        verify_source=source_guard, on_stage=None, sleep=time.sleep,
        command_factory=worker_command, credential_seconds=8):
    """Called only after the OS-owned gate. Real factories are the defaults."""
    from .integrated_catalog import acquire_catalog
    from .integrated_runtime import IntegratedRuntime
    from .nasdaq_feed_recovery import BoundedFeedClient
    from .profile_runtime import BoundProfile
    clock = clock or (lambda: datetime.now(timezone.utc))
    outer = Path(value['outer_root']); nonce = value['nonce']
    def status(phase):
        atomic_json(outer/'controller-status.json',
            {'contract': 'outer-controller-status-v1', 'nonce': nonce, 'phase': phase})
    authenticated, finished = threading.Event(), threading.Event()
    session = runtime = profile = password = None
    phase = 'configuration'; failure = None
    def watchdog():
        if not authenticated.wait(credential_seconds) and not finished.is_set():
            atomic_json(outer/'entry-failure.json', {'phase': 'credentials',
                'code': 'credential_deadline_ended', 'contract': CONTRACT})
            os._exit(124)
    try:
        if not 0 < credential_seconds <= 8: raise ValueError('Credential maximum is eight seconds')
        threading.Thread(target=watchdog, daemon=True).start()
        plan = validate_configuration(value, launch_sha256, verify_source=verify_source)
        plan.fresh(clock); status('BOOTSTRAPPING')
        password = receive_password(stream, nonce)
        def stage(name):
            if name == 'credentials_accepted': authenticated.set()
            if on_stage: on_stage(name)
        phase = 'bootstrap'
        session = bootstrap_fresh(plan, password, clock=clock, inventory=inventory,
            secure_api=secure_api, fault_hook=stage,
            catalog_acquirer=catalog_acquirer or (lambda **kw: acquire_catalog(**kw, allow_network=True)))
        password = None
        phase = 'runtime'
        feed = (feed_factory or (lambda t: BoundedFeedClient(t, allow_network=True)))(session.feed)
        runtime = IntegratedRuntime(session, feed_client=feed,
            worker_command=command_factory(value, launch_path, launch_sha256), clock=clock,
            stop_requested=lambda: (outer/'STOP.json').exists())
        runtime.initialize(); profile = BoundProfile(runtime, plan.settings.profile)
        if on_stage: on_stage('runtime_initialized')
        runtime.prepare_worker(sleep=sleep)
        if on_stage: on_stage('worker_prepared')
        status('ACTIVE'); phase = 'profile'
        if on_stage: on_stage('runtime_ready')
        while not (outer/'STOP.json').exists():
            result = profile.step()
            if result['status'] == 'GOAL_COMPLETE':
                status('GOAL_COMPLETE'); break
            if runtime.closed:
                reason = (runtime.last_report or {}).get('reason')
                if reason == 'native_budget_exhausted':
                    request_stop(value, launch_sha256, reason)
                    break
                if clock() >= runtime.stop: break
                raise ValueError('Runtime stopped before the profile goal')
            sleep(.05)
        # The outer's first stop endpoint governs final reporting. Waiting here
        # never runs another controller cycle or starts another quote request.
        while not (outer/'STOP.json').exists(): sleep(.01)
        return 0
    except BaseException as error:
        if isinstance(error, (KeyboardInterrupt, SystemExit)): code = 'controller_interrupted'
        else: code = getattr(error, 'code', 'controller_failed')
        allowed = {'controller_interrupted', 'controller_failed', 'credential_horizon',
            'authorization_required', 'startup_failed', 'credentials_unavailable',
            'secret_handoff_invalid', 'bootstrap_window_ended', 'catalog_failed',
            'dependency_rejected', 'inputs_changed', 'target_exists', 'configuration_invalid'}
        failure = {'contract': CONTRACT, 'phase': phase,
            'code': code if code in allowed else 'controller_failed',
            'exception_type': type(error).__name__}
        atomic_json(outer/'entry-failure.json', failure)
        status('FAILED'); return 70
    finally:
        try:
            if profile is not None: profile.close()
            elif runtime is not None: runtime.close()
            elif session is not None: session.close()
        finally:
            if isinstance(password, bytearray): password[:] = b'\0'*len(password); password.clear()
            authenticated.set(); finished.set()


def run_reporter(value, launch_sha256, *, verify_source=source_guard):
    """Read-only report in a separate owned process; no credential factory."""
    from .profile_report import report_saved_profile
    plan = validate_configuration(value, launch_sha256, verify_source=verify_source)
    outer = Path(value['outer_root'])
    try:
        report = report_saved_profile(plan.settings.experiment_root,
            outer_stop_path=outer/'STOP.json', nonce=value['nonce'])
    except Exception:
        report = {'result': 'FAILED', 'reason': 'native_reporting_unavailable',
            'outer_nonce': value['nonce'], 'preflight_configuration_sha256': plan.configuration_sha256,
            'reporting_read_only': True, 'credential_access': False}
    atomic_json(outer/'native-profile-report.json', report)
    return 0


def run_live(source_root, opening, focus, ecfg, profile, *, market_open_confirmed=False,
        clock=None, prompt=None, inventory=None, harness_factory=OuterHarness, progress=print):
    """Manual fresh invocation only; no automatic retries or controller resume."""
    clock = clock or (lambda: datetime.now(timezone.utc))
    source_root = Path(source_root).resolve()
    inventory_sha = source_guard(source_root)
    if market_open_confirmed is not True or profile not in PROFILES:
        raise ValueError('Explicit separate market-open profile required')
    opening, focus, ecfg = (Path(p).resolve() for p in (opening, focus, ecfg))
    r0, _ = _proposal(opening); r1, _ = _proposal(focus)
    # Pre-prompt validation and the post-prompt plan both bind exact source bytes.
    if r0.session_date.weekday() >= 5: raise ValueError('Weekday regular session required')
    observed = (inventory or inspect_dependencies)(EXPECTED_HELPERS)
    if observed.get('qualified') is not True: raise ValueError('Installed dependencies rejected')
    runs = source_root/'runs'; runs.mkdir(exist_ok=True)
    with owner_lock(runs/'live-profile.owner.lock'):
        previous_invocation_quiescent(runs)
        nonce = uuid.uuid4().hex
        folder = runs/('profile_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_'+nonce[:8])
        folder.mkdir()
        def settings(at):
            return BootstrapSettings(str(folder/('integrated_hot_'+nonce)), str(opening), str(focus),
                r0.content_sha256, r1.content_sha256, str(ecfg), utc_text(at), nonce,
                digest(observed), '', (), profile=profile, catalog_mode='owned_directory')
        before = settings(clock()).plan()
        password = frame = None
        pointer = None
        try:
            password = (prompt or SessionPassword.prompt)(digest({'contract': CONTRACT,
                'source_files': plain(before.public['source_file_sha256']), 'nonce': nonce}))
            plan = settings(clock()).plan()
            if before.public['source_file_sha256'] != plan.public['source_file_sha256']:
                raise ValueError('Inputs changed while waiting for the human prompt')
            value = configuration(plan.settings, folder/'outer_controller', source_root, inventory_sha)
            sha = digest(value); path = folder/'launch.json'; atomic_json(path, value)
            frame = password.frame(nonce); password.close(); password = None
            pointer = {'contract': CONTRACT, 'phase': 'ACTIVE', 'launch_path': str(path), 'launch_sha256': sha}
            atomic_json(runs/'active_live_profile.json', pointer)
            harness = harness_factory(Path(value['outer_root']),
                OuterSchedule(plan.settings.password_submitted_at_utc,
                    plan.public['start_at_utc'], plan.public['stop_at_utc']), nonce,
                clock=clock, expected_preflight_sha256=plan.configuration_sha256)
            progress('Output: '+str(folder), flush=True)
            progress('Ctrl+C here or command 53 stops only this experiment.', flush=True)
            last = [time.monotonic()-10]
            def stopping():
                if time.monotonic()-last[0] >= 10:
                    from .outer_harness import read_status
                    state = read_status(Path(value['outer_root'])/'controller-status.json', nonce)
                    progress('Live Hot profile: '+(state['phase'] if state else 'STARTING'), flush=True)
                    last[0] = time.monotonic()
                return stop_request(value, sha) is not None
            command = (sys.executable, '-I', '-B', value['entry_path'])
            result = harness.run((*command, 'controller', str(path), sha),
                reporter_command=(*command, 'report', str(path), sha),
                credential_frame=frame, stop_requested=stopping)
            request = stop_request(value, sha)
            summary = {'contract': CONTRACT, 'profile': profile, 'outer': result,
                'stop_request_origin': request['reason'] if request else None,
                'production_access': False, 'maximum_quote_permits': 63,
                'shared_sdk_token_refresh_possible': True}
            atomic_json(folder/'summary.json', summary)
            atomic_json(runs/'active_live_profile.json', dict(pointer, phase='CLOSED'))
            return folder, summary
        except BaseException as error:
            # Never leave a live-looking pointer after a failed parent setup.
            # No claim of child cleanup is inferred from an exception here.
            atomic_json(folder/'parent-failure.json', {'contract': CONTRACT,
                'code': 'parent_entry_failed', 'exception_type': type(error).__name__,
                'completed_outer_result': False})
            if pointer is not None:
                atomic_json(runs/'active_live_profile.json', dict(pointer, phase='CLOSED'))
            raise
        finally:
            if frame is not None: frame[:] = b'\0'*len(frame)
            if password is not None: password.close()


def stop_live(source_root):
    root = Path(source_root).resolve(); source_guard(root)
    pointer = bounded_json(root/'runs/active_live_profile.json', 8192)
    if pointer.get('contract') != CONTRACT or pointer.get('phase') not in ('ACTIVE', 'CLOSED'):
        raise ValueError('Active experiment pointer differs')
    if pointer['phase'] == 'CLOSED': return 'Experiment already closed.'
    path = Path(pointer['launch_path'])
    if not path.resolve().is_relative_to(root/'runs'): raise ValueError('Experiment pointer escaped its runs root')
    value = bounded_json(path); validate_configuration(value, pointer['launch_sha256'])
    request_stop(value, pointer['launch_sha256'])
    return 'Stop requested for this isolated experiment.'
