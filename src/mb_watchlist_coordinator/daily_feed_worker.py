"""One owned daily HTTP attempt, independently bounded by timeout and close."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from datetime import date, datetime, timedelta, timezone
import json
import os
import threading

from mb_watchlist_coordinator.daily_feed import DailyFeedLimits, DailyFeedTransport
from mb_watchlist_coordinator.nasdaq_feed_worker import fetch_http, synthetic_attempt
from mb_watchlist_coordinator.nasdaq_recovery import RecoveryQuery
from mb_watchlist_coordinator.sampling_service import owner_lock
from mb_watchlist_coordinator.sampling_requests import canonical, timestamp


def attempt_clock(synthetic):
    if synthetic is None:
        return lambda:datetime.now(timezone.utc)
    logical=synthetic.get('clock_at_utc')
    real=synthetic.get('clock_real_anchor_utc')
    if real:
        # An advancing fixture shares the parent's two anchors across spawn.
        # A per-step frozen sample can precede the subsequently reserved START.
        if not logical:raise ValueError('Synthetic real anchor requires a logical anchor')
        logical,real=timestamp(logical),timestamp(real)
        return lambda:logical+(datetime.now(timezone.utc)-real)
    return (lambda:timestamp(logical)) if logical else (lambda:datetime.now(timezone.utc))


def main():
    job = json.load(sys.stdin)
    identity = job['identity']
    # This fixture seam is accepted only on explicitly synthetic attempts;
    # every network-enabled attempt uses the actual UTC clock.
    clock = attempt_clock(job['synthetic'])
    queries = tuple(RecoveryQuery(date.fromisoformat(q['halt_date']) if q['halt_date'] else None,
        date.fromisoformat(q['resume_date']) if q['resume_date'] else None) for q in identity['queries'])
    transport = DailyFeedTransport(job['path'], session_date=date.fromisoformat(identity['session_date']),
        queries=queries, limits=DailyFeedLimits(**identity['limits']),clock=clock)
    if canonical(transport.identity) != canonical(identity): raise ValueError('Daily feed identity differs')
    with owner_lock(transport.path.with_suffix('.network.lock')):
        state = transport.snapshot(); pending = state['pending']
        if pending is None or any(pending[k] != job['reservation'][k] for k in ('attempt_id','token')): return 3
        if pending['synthetic'] != (job['synthetic'] is not None): raise ValueError('Daily feed provenance differs')
        cutoff = min(timestamp(state['deadline_utc']), transport.stop,
            timestamp(pending['started_at_utc'])+timedelta(seconds=transport.limits.hard_timeout_seconds))
        remaining = min(transport.limits.hard_timeout_seconds,(cutoff-clock()).total_seconds())
        if remaining <= 0:
            transport.finish(job['reservation'],unknown='hard_deadline'); return 124
        errors=[]
        def acquire():
            try:
                if job['synthetic'] is None: fetch_http(transport,job['reservation'])
                else: synthetic_attempt(transport,job['reservation'],job['synthetic'])
            except BaseException as error: errors.append(type(error).__name__)
        worker=threading.Thread(target=acquire,daemon=True)
        worker.start();worker.join(timeout=remaining)
        if worker.is_alive(): os._exit(124)
        return 125 if errors else 0


if __name__=='__main__': raise SystemExit(main())
