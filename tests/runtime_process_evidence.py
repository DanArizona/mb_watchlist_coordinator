"""Synthetic process-fixture causality and allowlisted failure evidence only.

No runtime, SDK, scheduling or credential limits are changed by this module.
Never copy arbitrary files, SDK exceptions, configuration or private pipe data.
"""
import hashlib
import json
from pathlib import Path
import unittest

from mb_watchlist_coordinator.nasdaq_sampling import ET, HaltSnapshot
from mb_watchlist_coordinator.sampling_requests import digest, timestamp


def subsequent_halt_snapshot(baseline, *, observed_at, capture_id):
    floor = timestamp(baseline['retrieved_at_utc'])
    if observed_at <= floor:
        raise ValueError('Synthetic subsequent halt requires a later observed clock')
    et = observed_at.astimezone(ET)
    row = {'symbol': 'NVDA', 'halt_date': et.strftime('%m/%d/%Y'),
        'halt_time': et.strftime('%H:%M:%S.%f'), 'reason_code': 'LUDP'}
    # The event is known at this observation, strictly after the baseline.
    # Backdating by an arbitrary margin can move it before that baseline.
    return HaltSnapshot(capture_id, observed_at, 'CURRENT', digest([row]), (row,),
        {'synthetic_only': True, 'test_external_observation': True})


STATUSES = frozenset(('WAITING', 'STARTING', 'RUNNING', 'EXTERNAL_HEALTHY',
    'RESTART_WAIT', 'BLOCKED', 'RECOVERING', 'READY', 'READY_WITH_GAPS',
    'INCOMPLETE', 'STOPPED', 'NOT_INITIALIZED', 'initial_baseline', 'incremental',
    'baseline', 'repeat', 'updated', 'request_queued', 'predates_startup',
    'different_session', 'outside_receipt_window', 'outside_halt_window',
    'reason_not_selected', 'outside_fixed_uni', 'credentials_accepted',
    'first_completed_work_observed', 'worker_startup_deadline_ended',
    'completed', 'idle', 'acquired', 'blocked', 'budget_exhausted',
    'window_ended', 'bounded_deadline_ended'))
REASONS = frozenset(('operator_stop', 'window_or_stop', 'pump_interrupted',
    'runtime_integrity_or_driver_failure', 'identity_provider_stop_required',
    'controller_provider_stopped', 'runtime_blocked_or_stopped',
    'worker_credentials_rejected', 'worker_startup_deadline_ended',
    'native_blocked', 'native_budget_exhausted', 'native_window_ended',
    'native_bounded_deadline_ended'))
PHASES = frozenset(('setup', 'wait', 'worker_first_completed_work',
    'startup_baseline', 'later_observation_clock', 'source_request_queued',
    'first_native_acquisition', 'pre_fault_startup_age',
    'replacement_generation', 'post_fault_native_acquisition'))


def _enum(value, allowed=STATUSES):
    return value if type(value) is str and value in allowed else 'unrecognized'


def _integer(value):
    return value if type(value) is int else None


def _utc(value):
    try:
        return timestamp(value).isoformat()
    except Exception:
        return None


def _probe(read):
    try:
        return read()
    except Exception:
        return {'evidence_available': False}


def runtime_failure_evidence(test):
    """Read a small fixed set of synthetic facts before TemporaryDirectory cleanup."""
    result = {'contract': 'synthetic-runtime-failure-evidence-v1',
        'test': test.id(), 'phase': _enum(getattr(test, 'phase', None), PHASES),
        'network': 'denied', 'production_access': False,
        'arbitrary_configuration_files_or_exception_messages_copied': False}
    runtime = getattr(test, 'r', None)
    if runtime is None:
        result['runtime_created'] = False
        return result
    result['runtime_created'] = True
    last = runtime.last_report or {}
    result['runtime'] = {'closed': bool(runtime.closed),
        'status': _enum(last.get('status')), 'reason': _enum(last.get('reason'), REASONS)}
    authority = getattr(test, 'authority_observation', {})
    result['authority'] = {'status': _enum(authority.get('status')),
        'worker_status': _enum(authority.get('worker', {}).get('status'))}
    managed = getattr(runtime, 'managed', None)
    if managed is not None:
        def worker():
            job = managed._job()
            child = managed.child
            value = {'pid': child.pid if child is not None else None,
                'exit_code': child.poll() if child is not None else None,
                'generation': _integer(job.get('generation')) if job else None}
            last_exit = managed.last_exit or {}
            value['last_exit'] = {'pid': _integer(last_exit.get('pid')),
                'returncode': _integer(last_exit.get('returncode')),
                'observed_at_utc': _utc(last_exit.get('observed_at_utc'))}
            if job:
                value.update(started_at_utc=_utc(job.get('started_at_utc')),
                    first_eligible_slot_utc=_utc(job.get('first_eligible_slot_utc')))
                for name, path in (('authentication', managed.root/(job['token']+'.auth.json')),
                        ('first_work', managed.root/(job['token']+'.startup.json')),
                        ('heartbeat', Path(job['heartbeat_path']))):
                    def record(path=path):
                        if not path.is_file() or path.stat().st_size > 65536:
                            return {'present': False}
                        data = json.loads(path.read_text())
                        return {'present': True, 'status': _enum(data.get('status')),
                            'collector_status': _enum(data.get('collector_status')),
                            'progress': _enum(data.get('progress')),
                            'observed_at_utc': _utc(data.get('observed_at_utc')),
                            'completed_at_utc': _utc(data.get('completed_at_utc')),
                            'pid': _integer(data.get('pid'))}
                    value[name] = _probe(record)
            return value
        result['worker'] = _probe(worker)
    fixture = getattr(test, 'f', None)
    if fixture is not None:
        def source():
            snapshot = fixture.session.live.snapshot()
            return {'receipt_count': len(snapshot['receipts']),
                'command_count': len(snapshot['commands']),
                'outcomes': [{'status': _enum(o['status']),
                    'events': [{'status': _enum(e['status']),
                        'symbol': e['symbol'] if e['symbol'] in ('NVDA', 'SPY', 'MSFT', 'AMD', 'IBM') else 'other'}
                        for e in o['events'][:4]]} for o in snapshot['outcomes'][-8:]],
                'baseline_retrieved_at_utc': _utc(snapshot['receipts'][0]['snapshot']['retrieved_at_utc'])
                    if snapshot['receipts'] else None,
                'last_retrieved_at_utc': _utc(snapshot['receipts'][-1]['snapshot']['retrieved_at_utc'])
                    if snapshot['receipts'] else None}
        result['source'] = _probe(source)
        def gate():
            state = fixture.session.gated_delivery.snapshot()['identity_gate']
            return {'identity_quote_permits': _integer(state['quote_permits']),
                'selected_symbol': state['selected_symbol'] if state['selected_symbol'] in ('NVDA', None) else 'other'}
        result['identity_gate'] = _probe(gate)
        result['native_acquisitions'] = _probe(lambda: len(fixture.session.store.acquisitions_in_replay_order()))
    return result


class FailureEvidenceResult(unittest.TextTestResult):
    def __init__(self, *args, evidence_root, **kwargs):
        super().__init__(*args, **kwargs)
        self.evidence_root = Path(evidence_root)
        self.evidence_files = []
        self.evidence_write_errors = 0

    def _capture(self, test):
        if not hasattr(test, 'phase'):
            return  # Unchanged suites have no coupled-runtime process fixture.
        try:
            self.evidence_root.mkdir(parents=True, exist_ok=True)
            name = '%03d-%s.json' % (len(self.evidence_files)+1,
                hashlib.sha256(test.id().encode()).hexdigest()[:12])
            path = self.evidence_root/name
            value = _probe(lambda: runtime_failure_evidence(test))
            path.write_text(json.dumps(value, indent=2)+'\n', encoding='utf-8')
            self.evidence_files.append(path.name)
        except Exception:
            self.evidence_write_errors += 1  # Never hide the original failure.

    def addFailure(self, test, error):
        self._capture(test)
        super().addFailure(test, error)

    def addError(self, test, error):
        self._capture(test)
        super().addError(test, error)
