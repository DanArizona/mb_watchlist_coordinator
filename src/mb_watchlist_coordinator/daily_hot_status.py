"""Read saved Hot evidence and assess current owner freshness. No provider access."""
from datetime import datetime, timezone
from pathlib import Path

from .daily_supervision import CONTRACT, DailyProcessState, read_json, unseal
from .daily_session import regular_path
from .sampling_requests import digest, timestamp, utc_text
from .sampling_service import ServiceBusy, owner_lock


def inspect_hot_status(root, *, clock=None):
    root = regular_path(root)
    now = (clock or (lambda: datetime.now(timezone.utc)))()
    if now.tzinfo is None: raise ValueError('Aware status observation time required')
    result = {'contract': 'daily-hot-read-only-status-v1', 'observed_at_utc': utc_text(now),
        'state': 'UNKNOWN', 'alerts': [], 'provider_access': False, 'restart_performed': False}
    try:
        binding = read_json(root/'driver-binding.json')
        if (binding['contract'] != CONTRACT or binding['configuration_path'] != str(root/'daily-worker.json')
                or digest(read_json(root/'daily-worker.json')) != binding['configuration_sha256']):
            raise ValueError('Hot status configuration identity differs')
        state = DailyProcessState(root, binding).read()
        status = unseal(read_json(root/'hot-status.json'))
        if (status['identity_sha256'] != digest(binding)
                or status['invocation'] != state['active_invocation']):
            raise ValueError('Hot status invocation differs')
        result.update(recorded_state=status['state'], worker_starts=len(state['starts']),
            hot_symbols=status.get('hot_symbols', []), effective_revision=status.get('effective_revision'),
            source_reconciled=status['source_reconciled'])
        if state['terminal']:
            result.update(state='BLOCKED', terminal=state['terminal'])
            result['alerts'].append('controller_blocked')
            return result
        if state['stop']:
            result.update(state='STOPPED', stop=state['stop'])
            return result
        live = unseal(read_json(root/'driver-live.json'))
        age = (now-timestamp(live['observed_at_utc'])).total_seconds()
        if (live['identity_sha256'] != digest(binding)
                or live['invocation'] != state['active_invocation']):
            raise ValueError('Hot controller heartbeat identity differs')
        result['controller_check_age_seconds'] = age
        lease = root/'driver-owner.lock'
        if not lease.is_file() or lease.stat().st_size < 1:
            raise ValueError('Hot controller lease evidence missing')
        try:
            with owner_lock(lease): pass
        except ServiceBusy:
            owner = True
        else: owner = False
        if not owner:
            result.update(state='CONTROLLER_NOT_RUNNING', alerts=['controller_owner_lost'])
        elif live['state'] != 'RUNNING' or not 0 <= age < 3:
            result.update(state='STALE_CONTROLLER', alerts=['controller_progress_stale'])
        else:
            result['state'] = status['state']
            if not status['source_reconciled']: result['alerts'].append('source_reconciliation_incomplete')
        return result
    except (OSError, ValueError, TypeError, KeyError) as error:
        result.update(state='UNKNOWN', alerts=['original_evidence_unavailable_or_invalid'],
            error_type=type(error).__name__)
        return result
