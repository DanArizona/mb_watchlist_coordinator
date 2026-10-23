"""One reserved feed attempt. Parent owns the hard deadline and this child only."""
from __future__ import annotations

from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dataclasses import fields
from datetime import date, datetime, timedelta, timezone
from http.client import HTTPException, IncompleteRead
import json
import os
import socket
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from mb_watchlist_coordinator.nasdaq_feed_recovery import FeedLimits, FeedRecoveryTransport, MAX_BYTES, SAFE_HEADERS
from mb_watchlist_coordinator.nasdaq_recovery import RecoveryQuery
from mb_watchlist_coordinator.sampling_service import owner_lock
from mb_watchlist_coordinator.sampling_requests import canonical, timestamp


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def fetch_http(transport, reservation, *, opener=None):
    pending = transport.snapshot()['pending']
    url = pending['url']
    metadata = {'status_code': None, 'final_url': None, 'headers': {},
                'body_complete': False, 'transport_error_type': None}
    request = Request(url, headers={'User-Agent': 'mb_watchlist_coordinator bounded Nasdaq recovery/1',
        'Accept': 'application/rss+xml,application/xml', 'Accept-Encoding': 'identity'})
    response = None
    try:
        try:
            response = (opener or build_opener(ProxyHandler({}), NoRedirects())).open(request,
                timeout=min(3, transport.limits.hard_timeout_seconds))
        except HTTPError as error:
            response = error
        metadata.update(status_code=response.getcode(), final_url=response.geturl(),
            headers={name: str(response.headers.get(name))[:2048] for name in SAFE_HEADERS
                     if response.headers.get(name) is not None})
        transport.progress(reservation, metadata)
        size = 0
        while size <= MAX_BYTES:
            try:
                chunk = response.read(min(65536, MAX_BYTES+1-size))
            except IncompleteRead as error:
                chunk = error.partial[:MAX_BYTES+1-size]
                metadata['transport_error_type'] = 'IncompleteRead'
                transport.progress(reservation, metadata, chunk)
                break
            if not chunk:
                metadata['body_complete'] = True
                transport.progress(reservation, metadata)
                break
            size += len(chunk)
            transport.progress(reservation, metadata, chunk)
    except (OSError, URLError, HTTPException) as error:
        metadata['transport_error_type'] = type(error).__name__
        transport.progress(reservation, metadata)
    finally:
        if response is not None:
            response.close()
    transport.finish(reservation)


def synthetic_attempt(transport, reservation, scenario):
    def denied(*args, **kwargs):
        raise RuntimeError('Network denied in synthetic feed child')
    socket.socket.connect = socket.socket.connect_ex = socket.create_connection = socket.getaddrinfo = denied
    if scenario.get('hang_before_headers'):
        time.sleep(60)
    p = transport.snapshot()['pending']
    metadata = {'status_code': scenario.get('status_code', 200), 'final_url': p['url'],
        'headers': scenario.get('headers', {}), 'body_complete': False, 'transport_error_type': None}
    transport.progress(reservation, metadata)
    for chunk in scenario.get('chunks', []):
        transport.progress(reservation, metadata, chunk.encode())
    if scenario.get('hang_after_body'):
        time.sleep(60)
    metadata.update(body_complete=True, transport_error_type=scenario.get('error_type'))
    transport.progress(reservation, metadata)
    transport.finish(reservation)


def main():
    job = json.load(sys.stdin)
    identity = job['identity']
    queries = tuple(RecoveryQuery(date.fromisoformat(q['halt_date']) if q['halt_date'] else None,
        date.fromisoformat(q['resume_date']) if q['resume_date'] else None) for q in identity['queries'])
    transport = FeedRecoveryTransport(job['path'], session_date=date.fromisoformat(identity['session_date']),
        queries=queries, limits=FeedLimits(**identity['limits']))
    if canonical(transport.identity) != canonical(identity):
        raise ValueError('Feed worker identity differs')
    with owner_lock(transport.path.with_suffix('.network.lock')):
        pending = transport.snapshot()['pending']
        if pending is None or any(pending[k] != job['reservation'][k] for k in ('attempt_id', 'token')):
            return 3  # A restarted controller fenced this not-yet-dispatched worker.
        if pending['synthetic'] != (job['synthetic'] is not None):
            raise ValueError('Feed worker provenance differs')
        state = transport.snapshot()
        cutoff = min(timestamp(state['deadline_utc']), timestamp(pending['started_at_utc'])+
            timedelta(seconds=transport.limits.hard_timeout_seconds))
        remaining = min(transport.limits.hard_timeout_seconds,
            (cutoff-datetime.now(timezone.utc)).total_seconds())
        if remaining <= 0:
            transport.finish(job['reservation'], unknown='hard_deadline')
            return 124
        errors = []
        def acquire():
            try:
                if job['synthetic'] is None:
                    fetch_http(transport, job['reservation'])
                else:
                    synthetic_attempt(transport, job['reservation'], job['synthetic'])
            except BaseException as error:
                errors.append(type(error).__name__)
        worker = threading.Thread(target=acquire, daemon=True)
        worker.start(); worker.join(timeout=remaining)
        if worker.is_alive():
            # Also bound an orphan after its controller dies. This process owns
            # this thread/HTTP request only; OS exit releases the network lease.
            os._exit(124)
        if errors:
            return 125
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
