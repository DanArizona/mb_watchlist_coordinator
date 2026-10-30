"""Isolated off-hours provider measurements using the shared native engine.

This is not the daily launcher. Its regular-session guards remain unchanged.
Only trusted Python test seams can substitute dependencies, clocks or entries.
"""
from contextlib import closing
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import statistics
import sys
import threading
import time
import traceback
from uuid import uuid4
from zoneinfo import ZoneInfo

from .authenticated_startup import AuthStartupSettings, SessionPassword, StartupError, prepare_authenticated_client, receive_password
from .controller_bootstrap import EXPECTED_HELPERS
from .daily_session import regular_path
from .daily_supervision import read_json, sealed, unseal
from .installed_startup_probe import inspect_dependencies
from .live_profile import source_guard
from .owned_process_scope import OwnedProcessScope, receive_gate
from .recovery_workers import HOT_SECONDS, atomic_json, next_future_slot, _write_handoff
from .sampling_requests import digest, timestamp, utc_text
from .sampling_service import owner_lock, ServiceBusy

CONTRACT = 'after-hours-provider-performance-v1'
ET = ZoneInfo('America/New_York')
SYMBOL = 'SPY'
LIMITS = {'symbol': SYMBOL, 'maximum_quote_requests': 24, 'active_seconds': 120,
    'request_timeout_seconds': 3, 'credential_seconds': 8, 'progress_seconds': 3,
    'cleanup_seconds': 10, 'report_seconds': 60, 'automatic_restarts': 0,
    'nasdaq_requests': 0, 'directory_requests': 0, 'maximum_dispatch_lateness_seconds': .75}


def closed_window(start, stop):
    """Conservative clock gate, not an exchange holiday-calendar assertion."""
    a, b = start.astimezone(ET), stop.astimezone(ET)
    if (a.date() != b.date() or not 0 < (stop.astimezone(timezone.utc)-start.astimezone(timezone.utc)).total_seconds() <= 120
            or a.weekday() < 5 and a < a.replace(hour=16, minute=0, second=0, microsecond=0)
            and b > a.replace(hour=9, minute=30, second=0, microsecond=0)):
        raise ValueError('Profile must stay outside weekday 09:30-16:00 ET and within one ET date')


def entries(source):
    source = regular_path(source)
    entry = source/'coordinator/src/mb_watchlist_coordinator/after_hours_entry.py'
    if entry.resolve() != Path(__file__).with_name('after_hours_entry.py').resolve():
        raise ValueError('Use the delivered off-hours entry')
    return (str(Path(sys.executable).resolve()), '-I', '-B', str(entry))


def build_review(source_root, ecfg, *, clock=None, dependency_reader=inspect_dependencies):
    clock = clock or (lambda: datetime.now(timezone.utc))
    now = clock(); closed_window(now, now+timedelta(seconds=120))
    source = regular_path(source_root); inventory = source_guard(source)
    observed = dependency_reader(EXPECTED_HELPERS)
    if observed.get('qualified') is not True:
        raise ValueError('Installed dependencies are not qualified')
    entries(source)
    nonce = uuid4().hex
    root = source/'runs'/('after_hours_provider_'+nonce)
    value = {'contract': CONTRACT, 'source_root': str(source), 'source_inventory_sha256': inventory,
        'dependencies': observed, 'dependency_sha256': digest(observed),
        'ecfg_path': str(regular_path(ecfg)), 'root': str(root), 'nonce': nonce,
        'limits': dict(LIMITS), 'hot_seconds': list(HOT_SECONDS),
        'selection': 'explicit SPY measurement roster; not a Nasdaq admission',
        'clock': 'actual UTC wall time and elapsed monotonic time; no shifted live clock',
        'journal_scope': 'fresh isolated native schema-v2 journal under this invocation',
        'production_hot_enabled': False, 'daily_launcher_changed': False,
        'shared_sdk_token_refresh_possible': True,
        'scope': 'off-hours provider and shared native acquisition timing; not daily-controller or market-open qualification'}
    return dict(value, review_sha256=digest(value))


def validate_review(review, *, clock=None, dependency_reader=inspect_dependencies):
    value = dict(review); sha = value.pop('review_sha256')
    now = (clock or (lambda: datetime.now(timezone.utc)))()
    closed_window(now, now+timedelta(seconds=120))
    source = regular_path(value['source_root']); root = regular_path(value['root'])
    if (value['contract'] != CONTRACT or digest(value) != sha or value['limits'] != LIMITS
            or value['hot_seconds'] != list(HOT_SECONDS) or not re.fullmatch('[0-9a-f]{32}', value['nonce'])
            or root.parent != source/'runs' or root.name != 'after_hours_provider_'+value['nonce']
            or root.exists()):
        raise ValueError('Original fresh bounded off-hours review required')
    regular_path(value['ecfg_path']); entries(source)
    source_guard(source, value['source_inventory_sha256'])
    observed = dependency_reader(EXPECTED_HELPERS)
    if observed.get('qualified') is not True or observed != value['dependencies'] or digest(observed) != value['dependency_sha256']:
        raise ValueError('Reviewed installed dependencies changed')
    return review


def load_config(root):
    root = regular_path(root)
    config = unseal(read_json(root/'profile.json'))
    review = config['review']; content = dict(review); sha = content.pop('review_sha256')
    if (config['contract'] != CONTRACT or digest(content) != sha or review['limits'] != LIMITS
            or review['hot_seconds'] != list(HOT_SECONDS) or review['root'] != str(root)
            or root != Path(review['source_root'])/'runs'/('after_hours_provider_'+review['nonce'])
            or config['nonce'] != review['nonce']
            or timestamp(config['stop_at_utc'])-timestamp(config['started_at_utc']) != timedelta(seconds=120)):
        raise ValueError('Original off-hours invocation binding differs')
    closed_window(timestamp(config['started_at_utc']), timestamp(config['stop_at_utc']))
    return config


def safe_error(error):
    return {'error_type': type(error).__name__, 'errno': getattr(error, 'errno', None),
        'winerror': getattr(error, 'winerror', None),
        'sqlite_errorcode': getattr(error, 'sqlite_errorcode', None),
        'sqlite_errorname': getattr(error, 'sqlite_errorname', None),
        'frames': [{'file': Path(f.filename).name, 'function': f.name, 'line': f.lineno}
            for f in traceback.extract_tb(error.__traceback__)
            if 'mb_watchlist_coordinator' in Path(f.filename).parts or 'mb_market_data' in Path(f.filename).parts]}


def record(root, config, phase, *, clock=None, **fields):
    atomic_json(Path(root)/'worker-status.json', sealed({'contract': CONTRACT, 'nonce': config['nonce'],
        'configuration_sha256': digest(config), 'observed_at_utc': utc_text((clock or (lambda: datetime.now(timezone.utc)))()),
        'phase': phase, **fields}))


def bound_status(root, config):
    value = unseal(read_json(Path(root)/'worker-status.json'))
    if (value['contract'] != CONTRACT or value['nonce'] != config['nonce']
            or value['configuration_sha256'] != digest(config)):
        raise ValueError('Worker progress binding differs')
    return value


def stop_requested(root, config):
    path = Path(root)/'STOP.json'
    if not path.exists(): return False
    value = unseal(read_json(path))
    if value != {'nonce': config['nonce'], 'configuration_sha256': digest(config)}:
        raise ValueError('Off-hours stop belongs to another invocation')
    return True


def request_stop(root):
    config = load_config(root)
    atomic_json(Path(root)/'STOP.json', sealed({'nonce': config['nonce'], 'configuration_sha256': digest(config)}))
    return {'status': 'STOP_REQUESTED', 'production_processes_signaled': False}


class Lifetime:
    def __init__(self, root, config, clock):
        self.root, self.config, self.clock = Path(root), config, clock
        self.done, self.authenticated, self.ready, self.stop = (threading.Event() for _ in range(4))
        age = (clock()-timestamp(config['started_at_utc'])).total_seconds()
        if age < 0: raise ValueError('Clock moved backwards')
        self.began = time.monotonic()-age; self.progress = time.monotonic()

    def fence(self):
        if load_config(self.root) != self.config: raise ValueError('Profile binding changed')
        if stop_requested(self.root, self.config): self.stop.set(); return False
        pulse = unseal(read_json(self.root/'owner-live.json'))
        if (pulse['nonce'] != self.config['nonce'] or pulse['configuration_sha256'] != digest(self.config)
                or not 0 <= (self.clock()-timestamp(pulse['observed_at_utc'])).total_seconds() < 3):
            raise ValueError('Off-hours owner heartbeat missing or stale')
        path = regular_path(self.root/'owner.lock', exists=True)
        try:
            with owner_lock(path): pass
        except ServiceBusy: return True
        raise ValueError('Off-hours owner lease absent')

    def watch(self):
        try:
            while not self.done.wait(.02):
                if not self.fence(): continue
                now = time.monotonic()
                if (self.clock() >= timestamp(self.config['stop_at_utc'])
                        or not self.authenticated.is_set() and now-self.began >= 8
                        or not self.ready.is_set() and now-self.began >= 3
                        or self.ready.is_set() and now-self.progress >= 3):
                    os_exit('progress_or_deadline_ended', self.root, self.config, self.clock)
        except BaseException:
            if not self.done.is_set(): os_exit('owner_fence_failed', self.root, self.config, self.clock)

    def start(self):
        if not self.fence(): raise ValueError('Stopped before credentials')
        self.thread = threading.Thread(target=self.watch, daemon=True); self.thread.start()

    def completed(self): self.progress = time.monotonic()
    def close(self): self.done.set(); self.thread.join(timeout=.1)


def os_exit(reason, root, config, clock):
    import os
    try: record(root, config, 'FAILED', reason=reason, clock=clock)
    finally: os._exit(124)


class CachedResponse:
    text = 'Off-hours quote response'
    def __init__(self, status, value): self.status_code, self.ok, self.value = status, status == 200, value
    def json(self): return self.value


class MeasuredClient:
    def __init__(self, client, root, config, lifetime, clock):
        self.client, self.root, self.config, self.lifetime, self.clock = client, Path(root), config, lifetime, clock
        self.measurements, self.blocked = [], None

    def quotes(self, symbols, *, fields):
        if (self.blocked or not self.lifetime.fence() or symbols != [SYMBOL] or fields != 'all'
                or self.clock() >= timestamp(self.config['stop_at_utc'])):
            raise ValueError('Bounded off-hours quote gate refused')
        permits = unseal(read_json(self.root/'quote-permits.json'))
        if (permits['nonce'] != self.config['nonce'] or type(permits['count']) is not int
                or permits['count'] != len(self.measurements) or not 0 <= permits['count'] < 24):
            raise ValueError('Off-hours quote ceiling exhausted')
        permits['count'] += 1; atomic_json(self.root/'quote-permits.json', sealed(permits))
        began = time.perf_counter(); measurement = {'sequence': permits['count'], 'valid': False}
        try:
            response = self.client.quotes(symbols, fields=fields)
            returned = time.perf_counter(); measurement['request_seconds'] = returned-began
            measurement['http_status'] = response.status_code
            value = response.json() if response.ok else {}
            measurement['decode_seconds'] = time.perf_counter()-returned
            entry = value.get(SYMBOL) if isinstance(value, dict) else None
            price = entry.get('quote', {}).get('lastPrice') if isinstance(entry, dict) and isinstance(entry.get('quote'), dict) else None
            measurement['valid'] = bool(response.status_code == 200 and not self.client.halt_reason
                and isinstance(entry, dict) and entry.get('symbol') == SYMBOL
                and type(price) in (int, float) and math.isfinite(price) and price > 0)
            if not measurement['valid']: self.blocked = 'provider_or_quote_invalid'
            return CachedResponse(response.status_code, value)
        except Exception:
            self.blocked = 'provider_request_failed'
            measurement['request_seconds'] = time.perf_counter()-began
            raise StartupError('provider_failed') from None
        finally:
            self.measurements.append(measurement)
            atomic_json(self.root/'provider-measurements.json', sealed({'nonce': self.config['nonce'], 'measurements': self.measurements}))


def run_worker(root, nonce, *, stream=None, clock=None, secure_api=None, synthetic_only=False):
    from mb_market_data.quote_observation_store import QuoteObservationStore
    from mb_market_data.sampling_membership import SamplingHierarchyRevision, SamplingChannel
    from mb_market_data.sampling_acquisition import AcquisitionSettings, IsolatedSamplingPoller, next_slot, MARKER
    from mb_market_data.watchlist_polling import PollWindow
    clock = clock or (lambda: datetime.now(timezone.utc)); root = Path(root)
    stream = sys.stdin.buffer if stream is None else stream
    receive_gate(stream, nonce); config = load_config(root)
    if config['nonce'] != nonce: raise ValueError('Owned off-hours gate differs')
    lifetime = Lifetime(root, config, clock); lifetime.start()
    client = password = None; metrics = []; phase = 'FAILED'; reason = 'startup_failed'; timings = {}; error_info = None
    try:
        record(root, config, 'AUTHENTICATING', synthetic_only=synthetic_only, clock=clock)
        password = receive_password(stream, nonce); began = time.perf_counter()
        client = prepare_authenticated_client(AuthStartupSettings(config['review']['ecfg_path'], config['stop_at_utc']),
            password, clock=clock, secure_api=secure_api)
        password[:] = b'\0'*len(password); password.clear(); password = None
        timings['authentication_seconds'] = time.perf_counter()-began; lifetime.authenticated.set()
        prepared = time.perf_counter(); now = clock(); first = next_future_slot(now+timedelta(seconds=3)); last = first
        for _ in range(23): last = next_future_slot(last)
        # Retain the accepted .75s dispatch allowance on the final slot too.
        # The next grid second is at least 2s away, so this still has 24 slots.
        end = last+timedelta(seconds=1)
        if end >= timestamp(config['stop_at_utc']): raise ValueError('Insufficient original off-hours window')
        journal = root/'isolated-quotes.sqlite3'
        store = QuoteObservationStore(journal, session_date=now.astimezone(ET).date(), schema_version=2)
        store.initialize()
        store.record_membership_revision(SamplingHierarchyRevision(session_date=store.session_date, revision=0,
            effective_at=first, uni_symbols=(SYMBOL,), focus_symbols=(SYMBOL,), hot_symbols=(SYMBOL,),
            source='explicit off-hours measurement roster; not Nasdaq admission', metadata={MARKER: True, 'after_hours_only': True}))
        measured = MeasuredClient(client, root, config, lifetime, clock)
        settings = AcquisitionSettings(SamplingChannel.HOT, HOT_SECONDS, PollWindow(first, end),
            400, 'all', CONTRACT, .75, .05)
        poller = IsolatedSamplingPoller(store, settings=settings, client=measured, clock=clock)
        poller.initialize(); poller.snapshot()
        timings['native_prepare_seconds'] = time.perf_counter()-prepared
        timings['launch_to_first_completed_native_work_seconds'] = (clock()-timestamp(config['started_at_utc'])).total_seconds()
        if time.monotonic()-lifetime.began >= 3: raise ValueError('Original cold progress budget ended')
        lifetime.completed(); lifetime.ready.set(); slot = next_slot(settings, after=clock())
        while slot is not None and not lifetime.stop.is_set():
            if not lifetime.fence(): break
            if clock() < slot.scheduled_at:
                poller.snapshot(); lifetime.completed()
                record(root, config, 'ACTIVE', synthetic_only=synthetic_only, timings=timings, completed_slots=len(metrics), clock=clock)
                lifetime.stop.wait(.1); continue
            result = poller.sample(slot); lifetime.completed(); metrics.append(result)
            atomic_json(root/'native-measurements.json', sealed({'nonce': nonce, 'measurements': metrics}))
            record(root, config, 'ACTIVE', synthetic_only=synthetic_only, timings=timings, completed_slots=len(metrics), clock=clock)
            if measured.blocked or result['status'] != 'acquired':
                reason = measured.blocked or 'native_slot_not_acquired'; break
            slot = next_slot(settings, after=max(slot.scheduled_at, clock()))
        if len(metrics) == 24 and all(m['status'] == 'acquired' for m in metrics) and not measured.blocked:
            phase, reason = 'COMPLETE', 'goal_complete'
        elif lifetime.stop.is_set(): reason = 'operator_stop'
    except StartupError as error:
        reason = error.code
    except Exception as error:
        reason = 'worker_evidence_or_processing_failed'; error_info = safe_error(error)
    finally:
        if password is not None: password[:] = b'\0'*len(password); password.clear()
        if client is not None: client.close()
        record(root, config, phase, reason=reason, synthetic_only=synthetic_only,
            timings=timings, completed_slots=len(metrics), client_close_completed=client is not None,
            clock=clock, error=error_info)
        lifetime.close()
    return 0 if phase == 'COMPLETE' else 70


def stats(values):
    values = sorted(values)
    return None if not values else {'count': len(values), 'min': values[0],
        'median': statistics.median(values), 'p95_nearest_rank': values[math.ceil(.95*len(values))-1], 'max': values[-1]}


def run_report(root, nonce, *, stream=None):
    from mb_market_data.quote_journal_audit import audit_quote_journal
    from mb_market_data.quote_journal_replay import QuoteJournalReplayReader
    root = Path(root); stream = sys.stdin.buffer if stream is None else stream
    receive_gate(stream, nonce); config = load_config(root)
    stopped = unseal(read_json(root/'owner-result.json'))
    if (stopped['nonce'] != nonce or stopped['configuration_sha256'] != digest(config)
            or stopped['cleanup']['status'] != 'EXIT_OBSERVED' or config['nonce'] != nonce):
        raise ValueError('Owned producer exit required before report')
    value = {'contract': CONTRACT, 'nonce': nonce, 'result': 'FAILED', 'qualification_scope': config['review']['scope'],
        'configuration_sha256': digest(config), 'cleanup': stopped['cleanup'], 'owner_stop_reason': stopped['stop_reason'],
        'native_audit_passed': False, 'two_fresh_replays_equal': False,
        'production_journal_or_process_access': False, 'production_hot_enabled': False,
        'daily_live_launch_qualified': False, 'market_open_performance_qualified': False,
        'provider_capacity_qualified': False, 'full_day_capacity_qualified': False}
    worker = bound_status(root, config) if (root/'worker-status.json').exists() else {}
    permits = unseal(read_json(root/'quote-permits.json'))
    measurements = unseal(read_json(root/'provider-measurements.json'))['measurements'] if (root/'provider-measurements.json').exists() else []
    native = unseal(read_json(root/'native-measurements.json'))['measurements'] if (root/'native-measurements.json').exists() else []
    if permits['nonce'] != nonce: raise ValueError('Original off-hours permit binding differs')
    value.update(worker=worker, quote_dispatch_permits=permits['count'], provider_outcomes_recorded=len(measurements),
        unknown_provider_outcomes=permits['count']-len(measurements),
        actual_provider_used=not worker.get('synthetic_only', False) and permits['count'] > 0,
        request_seconds=stats([m['request_seconds'] for m in measurements]),
        native_cycle_seconds=stats([m['cycle_seconds'] for m in native if 'cycle_seconds' in m]),
        before_api_gate_seconds=stats([m['before_api_gate_seconds'] for m in native if 'before_api_gate_seconds' in m]))
    journal = root/'isolated-quotes.sqlite3'
    if journal.exists():
        def replay():
            count, sha = 0, hashlib.sha256()
            for event in QuoteJournalReplayReader(journal).events():
                count += 1; sha.update((event.event_id+'\n').encode())
            return {'events': count, 'sequence_sha256': sha.hexdigest()}
        try:
            audit = audit_quote_journal(journal, audited_at=timestamp(stopped['stopped_at_utc']))
            first, second = replay(), replay()
            value.update(native_audit_passed=audit.passed, first_replay=first, second_replay=second,
                two_fresh_replays_equal=first == second)
        except Exception as error:
            value['native_report_error'] = safe_error(error)
    passed = (worker.get('phase') == 'COMPLETE' and worker.get('client_close_completed') is True
        and stopped['cleanup']['controller_returncode'] == 0 and not stopped['cleanup']['forced']
        and permits['count'] == len(measurements) == len(native) == 24
        and all(m['valid'] and m['http_status'] == 200 for m in measurements)
        and value['native_audit_passed'] and value['two_fresh_replays_equal'])
    value['result'] = 'PASS' if passed else 'FAILED'
    atomic_json(root/'performance-report.json', sealed(value))
    return 0


def run_profile(review, *, trial_approved=False, market_closed_confirmed=False,
                clock=None, prompt=None, dependency_reader=inspect_dependencies,
                command_factory=None, stop_callback=lambda: False):
    if trial_approved is not True or market_closed_confirmed is not True:
        raise ValueError('Explicit bounded provider trial and closed-hours assertions required')
    clock = clock or (lambda: datetime.now(timezone.utc))
    validate_review(review, clock=clock, dependency_reader=dependency_reader)
    root = Path(review['root']); password = frame = None
    try:
        password = (prompt or SessionPassword.prompt)(review['review_sha256'])
        validate_review(review, clock=clock, dependency_reader=dependency_reader)
        start = clock(); end = start+timedelta(seconds=120)
        config = {'contract': CONTRACT, 'review': review, 'nonce': review['nonce'],
            'started_at_utc': utc_text(start), 'stop_at_utc': utc_text(end)}
        root.parent.mkdir(exist_ok=True); root.mkdir(exist_ok=False)
        atomic_json(root/'profile.json', sealed(config))
        atomic_json(root/'quote-permits.json', sealed({'nonce': config['nonce'], 'count': 0}))
        base = entries(review['source_root'])
        command = command_factory or (lambda role: (*base, role))
        scope = OwnedProcessScope((*command('worker'), str(root), config['nonce']), config['nonce'])
        began = time.monotonic(); active_end = began+120; reason = 'worker_failed'; status = None; error_info = None
        def pulse():
            atomic_json(root/'owner-live.json', sealed({'nonce': config['nonce'],
                'configuration_sha256': digest(config), 'observed_at_utc': utc_text(clock())}))
        with owner_lock(root/'owner.lock'):
            try:
                pulse(); scope.launch(); scope.open_gate(); frame = password.frame(config['nonce'])
                threading.Thread(target=_write_handoff, args=(scope.child.stdin, frame, {}), daemon=True).start()
                last = time.monotonic()
                while True:
                    now = time.monotonic()
                    if now-last >= .25: pulse(); last = now
                    if stop_callback() or stop_requested(root, config): reason = 'operator_stop'; break
                    if now >= active_end or clock() >= end: reason = 'active_deadline_ended'; break
                    if (root/'worker-status.json').exists():
                        status = bound_status(root, config)
                        if status['phase'] in ('COMPLETE', 'FAILED'): reason = status.get('reason', 'worker_failed'); break
                        if status['phase'] == 'ACTIVE' and not 0 <= (clock()-timestamp(status['observed_at_utc'])).total_seconds() < 3:
                            reason = 'worker_progress_stale'; break
                    if (not status or status['phase'] != 'ACTIVE') and now-began >= 3:
                        reason = 'cold_progress_deadline_ended'; break
                    if scope.child.poll() is not None: reason = 'worker_exited'; break
                    time.sleep(.02)
            except KeyboardInterrupt: reason = 'operator_stop'
            except Exception as error: reason = 'owner_evidence_or_launch_failed'; error_info = safe_error(error)
            finally:
                stopped = time.monotonic(); stopped_at = clock(); deadline = stopped+10
                try: request_stop(root)
                except Exception as error: error_info = safe_error(error)
                while scope.child is not None and scope.child.poll() is None and time.monotonic() < deadline-1:
                    time.sleep(.02)
                try: cleanup = scope.finish(deadline) if not scope.closed else {'status': 'CLEANUP_INCOMPLETE'}
                except Exception as error: cleanup = {'status': 'CLEANUP_INCOMPLETE', 'error': safe_error(error)}
                if frame is not None: frame[:] = b'\0'*len(frame)
                password.close()
                receipt = {'contract': CONTRACT, 'nonce': config['nonce'], 'configuration_sha256': digest(config),
                    'stop_reason': reason, 'stopped_at_utc': utc_text(stopped_at), 'cleanup': cleanup,
                    'cleanup_seconds': time.monotonic()-stopped, 'reporting': {'status': 'NOT_ATTEMPTED'}, 'error': error_info}
                atomic_json(root/'owner-result.json', sealed(receipt))
                if cleanup['status'] == 'EXIT_OBSERVED':
                    reporter = OwnedProcessScope((*command('report'), str(root), config['nonce']), config['nonce'])
                    report_end = min(stopped+70, time.monotonic()+60)
                    try:
                        reporter.launch(); reporter.open_gate()
                        while reporter.child.poll() is None and time.monotonic() < report_end-1: time.sleep(.02)
                    except Exception as error:
                        receipt['report_error'] = safe_error(error)
                    finally:
                        report_cleanup = reporter.finish(report_end) if not reporter.closed else {'status': 'CLEANUP_INCOMPLETE'}
                    receipt['reporting'] = {'status': 'COMPLETE' if report_cleanup['status'] == 'EXIT_OBSERVED'
                        and report_cleanup['controller_returncode'] == 0 and (root/'performance-report.json').is_file()
                        else 'REPORT_INCOMPLETE', 'cleanup': report_cleanup}
                    atomic_json(root/'owner-result.json', sealed(receipt))
        return root, receipt
    finally:
        if password is not None: password.close()
