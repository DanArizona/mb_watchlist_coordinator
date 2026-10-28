"""Paced current/dated RSS evidence. HTTP runs only in a bounded owned child.

One ledger is shared by all current and historical requests in an experiment.
It is not coordinated with unrelated clients or older shadow processes.
"""
from __future__ import annotations

from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import time
from urllib.parse import urlencode
import uuid
import xml.etree.ElementTree as XML

from .nasdaq_recovery import RecoveryQuery
from .nasdaq_sampling import HaltSnapshot, halt_event_id, event_time
from .sampling_requests import canonical, digest, freeze, plain, timestamp, utc_text
from .sampling_service import owner_lock, ServiceBusy

BASE_URL = 'https://www.nasdaqtrader.com/rss.aspx'
MAX_BYTES = 4_000_000
SAFE_HEADERS = ('Content-Type', 'Content-Length', 'Content-Encoding', 'Date', 'Server',
                'Via', 'Retry-After', 'X-Iinfo', 'X-CDN', 'Location')
FIELDS = {'HaltDate': 'halt_date', 'HaltTime': 'halt_time', 'IssueSymbol': 'symbol',
    'IssueName': 'issue_name', 'Market': 'market', 'Mkt': 'market_code', 'ReasonCode': 'reason_code',
    'PauseThresholdPrice': 'pause_threshold_price', 'ResumptionDate': 'resumption_date',
    'ResumptionQuoteTime': 'resumption_quote_time', 'ResumptionTradeTime': 'resumption_trade_time'}


def query_url(query=None):
    params = {'feed': 'tradehalts'}
    if query is not None:
        if type(query) is not RecoveryQuery:
            raise ValueError('An explicit validated recovery query is required')
        for field, day in (('haltdate', query.halt_date), ('resumedate', query.resume_date)):
            if day:
                params[field] = day.strftime('%m%d%Y')
    return BASE_URL+'?'+urlencode(params)


@dataclass(frozen=True)
class FeedLimits:
    interval_seconds: int = 60
    max_attempts: int = 10
    budget_seconds: int = 720
    hard_timeout_seconds: float = 10
    consecutive_failures: int = 3

    def __post_init__(self):
        if (type(self.interval_seconds) is not int or self.interval_seconds < 60
                or type(self.max_attempts) is not int or not 1 <= self.max_attempts <= 10
                or type(self.budget_seconds) is not int or not 1 <= self.budget_seconds <= 720
                or type(self.consecutive_failures) is not int or not 1 <= self.consecutive_failures <= 3
                or isinstance(self.hard_timeout_seconds, bool)
                or not isinstance(self.hard_timeout_seconds, (int, float))
                or not math.isfinite(self.hard_timeout_seconds)
                or not .1 <= self.hard_timeout_seconds <= 10):
            raise ValueError('Invalid bounded feed limits')


def classify(raw, metadata, *, url, at, historical):
    """Availability and canonical facts are derived from retained bytes afresh."""
    def fail(kind, terminal=False):
        return {'status': 'unavailable', 'kind': kind, 'terminal': terminal, 'records': []}
    code = metadata.get('status_code')
    if len(raw) > MAX_BYTES:
        return fail('body_limit', True)
    if code in (401, 403, 429) or code is not None and 300 <= code < 400:
        return fail('access_or_redirect_stop', True)
    if code is not None and code >= 400 and metadata.get('headers', {}).get('Retry-After'):
        return fail('retry_after_stop', True)
    if metadata.get('final_url') not in (None, url):
        return fail('unexpected_response_url', True)
    if metadata.get('transport_error_type') or not metadata.get('body_complete'):
        return fail('transport_or_incomplete_body')
    if code != 200:
        return fail('http_status_unavailable')
    length = metadata.get('headers', {}).get('Content-Length')
    try:
        if length is not None and int(length) != len(raw):
            return fail('content_length_mismatch')
    except (ValueError, TypeError):
        return fail('invalid_content_length')
    if not raw:
        return fail('empty_body')
    try:
        text = raw.decode('utf-8-sig')
    except UnicodeDecodeError:
        return fail('invalid_utf8')
    if re.match(r'^\s*(?:<\?xml[^>]*>\s*)?(?:<!doctype\s+html\b|<html(?:\s|>))', text[:1024], re.I):
        return fail('non_feed_html')
    if '<!DOCTYPE' in text.upper() or '<!ENTITY' in text.upper():
        return fail('unsupported_xml_declaration', True)
    try:
        root = XML.fromstring(re.sub(r'(<\/?)ndaq:', r'\1', text))
    except XML.ParseError:
        return fail('malformed_xml')
    if root.tag != 'rss' or root.find('channel') is None:
        return fail('non_rss_document')
    rows = [{target: ' '.join(''.join(item.find(field).itertext()).split())
             if item.find(field) is not None else '' for field, target in FIELDS.items()}
            for item in root.findall('./channel/item')]
    try:
        snapshot = HaltSnapshot('validation', at, 'HISTORICAL' if historical else 'CURRENT',
            hashlib.sha256(raw).hexdigest(), tuple(rows), {})
        seen = {}
        for row in snapshot.records:
            if event_time(row) > at:
                return fail('future_halt_timestamp')
            eid = halt_event_id(row)
            if eid in seen and canonical(seen[eid]) != canonical(row):
                return fail('conflicting_rows')
            seen[eid] = row
    except (ValueError, TypeError, KeyError):
        return fail('invalid_halt_fields')
    return {'status': 'valid', 'kind': 'rss', 'terminal': False, 'records': plain(snapshot.records)}


class FeedRecoveryTransport:
    def __init__(self, path, *, session_date, queries, limits=None, clock=None):
        if not queries or any(type(q) is not RecoveryQuery for q in queries):
            raise ValueError('Explicit dated queries required')
        if len({q.query_id for q in queries}) != len(queries):
            raise ValueError('Duplicate dated query')
        if RecoveryQuery(session_date, session_date) not in queries:
            raise ValueError('Target-day halt/resumption union required')
        if any(d and d > session_date for q in queries for d in (q.halt_date, q.resume_date)):
            raise ValueError('Query follows target session')
        self.path, self.session_date, self.queries = Path(path), session_date, tuple(queries)
        self.limits = limits or FeedLimits()
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.identity = freeze({'contract': 'nasdaq-paced-recovery-feed-v1',
            'session_date': session_date.isoformat(), 'queries': [q.payload() for q in queries],
            'limits': asdict(self.limits), 'endpoint': BASE_URL})

    def _connect(self, write=False):
        return sqlite3.connect(self.path.resolve().as_uri()+('?mode=rw' if write else '?mode=ro'), uri=True, timeout=5)

    def initialize(self, *, create=False):
        if create:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open('xb'):
                pass
            with closing(self._connect(True)) as c, c:
                c.execute('CREATE TABLE feed_identity (id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL)')
                c.execute('INSERT INTO feed_identity VALUES(1,?)', (canonical(self.identity),))
                c.execute('CREATE TABLE feed_event (sequence INTEGER PRIMARY KEY, payload TEXT NOT NULL, body BLOB NOT NULL)')
        elif not self.path.is_file():
            raise FileNotFoundError('Missing feed evidence ledger; restore or explicitly declare a new experiment')
        return self.snapshot()

    def _read(self, c):
        expected = {'contract': 'nasdaq-paced-recovery-feed-v1', 'session_date': self.session_date.isoformat(),
            'queries': [q.payload() for q in self.queries], 'limits': asdict(self.limits), 'endpoint': BASE_URL}
        if canonical(expected) != canonical(self.identity) or c.execute('SELECT payload FROM feed_identity WHERE id=1').fetchone() != (canonical(self.identity),):
            raise ValueError('Feed identity differs')
        previous, last, current, attempts, events = digest(self.identity), None, None, [], []
        next_due, deadline, consecutive, stop = None, None, 0, None
        for n, raw_json, body in c.execute('SELECT * FROM feed_event ORDER BY sequence'):
            e = json.loads(raw_json); payload = dict(e); sha = payload.pop('event_sha256')
            at = timestamp(e['at_utc'])
            if (n != len(events)+1 or e['sequence'] != n or e['previous_sha256'] != previous
                    or e['body_sha256'] != hashlib.sha256(body).hexdigest() or digest(payload) != sha
                    or last is not None and at < last):
                raise ValueError('Feed evidence chain or clock differs')
            if e['kind'] == 'start':
                qid = e['query_id']
                query = next((q for q in self.queries if q.query_id == qid), None)
                if (body or current is not None or stop or len(attempts) >= self.limits.max_attempts
                        or any(a['attempt_id'] == e['attempt_id'] for a in attempts)
                        or next_due is not None and at < next_due or deadline is not None and at >= deadline
                        or qid != 'CURRENT' and query is None or e['url'] != query_url(query)):
                    raise ValueError('Invalid or unpaced feed start')
                deadline = deadline or at+timedelta(seconds=self.limits.budget_seconds)
                current = {'attempt_id': e['attempt_id'], 'query_id': qid, 'url': e['url'],
                    'started_at_utc': e['at_utc'], 'token': e['token'], 'raw': b'', 'metadata': {},
                    'synthetic': e['synthetic']}
                if type(e['synthetic']) is not bool:
                    raise ValueError('Explicit transport provenance required')
            elif e['kind'] in ('progress', 'finish'):
                if current is None or current['attempt_id'] != e['attempt_id']:
                    raise ValueError('Feed progress has no matching attempt')
                if e['kind'] == 'progress':
                    if len(current['raw'])+len(body) > MAX_BYTES+1:
                        raise ValueError('Retained feed body limit exceeded')
                    if set(e['metadata']) - {'status_code', 'final_url', 'headers', 'body_complete', 'transport_error_type'}:
                        raise ValueError('Unexpected feed metadata')
                    if set(e['metadata'].get('headers', {})) - set(SAFE_HEADERS):
                        raise ValueError('Unapproved response header')
                    if (type(e['metadata'].get('body_complete', False)) is not bool
                            or e['metadata'].get('status_code') is not None and type(e['metadata']['status_code']) is not int):
                        raise ValueError('Invalid HTTP diagnostic types')
                    current['raw'] += body
                    current['metadata'] = e['metadata']
                else:
                    if body:
                        raise ValueError('Final feed event must not add bytes')
                    if e['unknown'] not in (None, 'interrupted', 'hard_deadline', 'worker_exit', 'stop_requested'):
                        raise ValueError('Unknown feed completion disposition')
                    if e['unknown'] is None and (at >= deadline or
                            at >= timestamp(current['started_at_utc'])+timedelta(seconds=self.limits.hard_timeout_seconds)):
                        raise ValueError('Late HTTP outcome cannot claim a normal completion')
                    result = ({'status': 'unavailable', 'kind': 'unknown_'+e['unknown'], 'terminal': False, 'records': []}
                        if e['unknown'] else classify(current['raw'], current['metadata'], url=current['url'], at=at, historical=current['query_id'] != 'CURRENT'))
                    if canonical(result) != canonical(e['outcome']):
                        raise ValueError('Feed outcome differs from retained evidence')
                    current.update(completed_at_utc=e['at_utc'], outcome=result,
                                   completion_event_sha256=e['event_sha256'])
                    attempts.append(current); current = None
                    next_due = at+timedelta(seconds=self.limits.interval_seconds)
                    consecutive = 0 if result['status'] == 'valid' else consecutive+1
                    if result['terminal']:
                        stop = result['kind']
                    elif consecutive >= self.limits.consecutive_failures:
                        stop = 'consecutive_unavailable_limit'
            else:
                raise ValueError('Unknown feed event')
            previous, last = sha, at; events.append(e)
        return {'events': events, 'attempts': attempts, 'pending': current, 'head_sha256': previous,
            'next_at_utc': utc_text(next_due) if next_due else None,
            'deadline_utc': utc_text(deadline) if deadline else None, 'stop_reason': stop,
            'consecutive_failures': consecutive}

    def snapshot(self):
        with closing(self._connect()) as c:
            c.execute('BEGIN')
            return self._read(c)

    def _append(self, c, state, kind, *, body=b'', **data):
        e = {'sequence': len(state['events'])+1, 'kind': kind, 'at_utc': utc_text(self.clock()),
            'previous_sha256': state['head_sha256'], 'body_sha256': hashlib.sha256(body).hexdigest(), **data}
        e['event_sha256'] = digest(e)
        c.execute('INSERT INTO feed_event VALUES(?,?,?)', (e['sequence'], canonical(e), body))
        self._read(c)  # Validate time, pacing, metadata and outcome before commit.

    def reserve(self, query=None, *, synthetic=False):
        with closing(self._connect(True)) as c, c:
            c.execute('BEGIN IMMEDIATE'); state = self._read(c)
            now = self.clock()
            if state['pending']:
                return None
            if (state['stop_reason'] or len(state['attempts']) >= self.limits.max_attempts
                    or state['deadline_utc'] and now >= timestamp(state['deadline_utc'])):
                return None
            if state['next_at_utc'] and now < timestamp(state['next_at_utc']):
                return None
            aid, token = uuid.uuid4().hex, uuid.uuid4().hex
            self._append(c, state, 'start', attempt_id=aid, token=token,
                query_id=query.query_id if query else 'CURRENT', url=query_url(query), synthetic=synthetic)
            return {'attempt_id': aid, 'token': token}

    def progress(self, reservation, metadata, chunk=b''):
        with closing(self._connect(True)) as c, c:
            c.execute('BEGIN IMMEDIATE'); state = self._read(c)
            if not state['pending'] or any(state['pending'][k] != reservation[k] for k in ('attempt_id', 'token')):
                raise ValueError('Stale feed worker reservation')
            self._append(c, state, 'progress', attempt_id=reservation['attempt_id'], metadata=metadata, body=chunk)

    def finish(self, reservation, *, unknown=None):
        if unknown not in (None, 'interrupted', 'hard_deadline', 'worker_exit', 'stop_requested'):
            raise ValueError('Unknown interruption disposition')
        with closing(self._connect(True)) as c, c:
            c.execute('BEGIN IMMEDIATE'); state = self._read(c); current = state['pending']
            if not current or any(current[k] != reservation[k] for k in ('attempt_id', 'token')):
                raise ValueError('Stale feed completion')
            if unknown is None and (self.clock() >= timestamp(state['deadline_utc']) or
                    self.clock() >= timestamp(current['started_at_utc'])+timedelta(seconds=self.limits.hard_timeout_seconds)):
                unknown = 'hard_deadline'
            outcome = ({'status': 'unavailable', 'kind': 'unknown_'+unknown, 'terminal': False, 'records': []}
                if unknown else classify(current['raw'], current['metadata'], url=current['url'],
                    at=self.clock(), historical=current['query_id'] != 'CURRENT'))
            self._append(c, state, 'finish', attempt_id=reservation['attempt_id'], unknown=unknown, outcome=outcome)

    def halt_snapshot(self, attempt):
        if attempt['outcome']['status'] != 'valid':
            raise ValueError('Unavailable feed never means an empty valid snapshot')
        return HaltSnapshot('feed-'+attempt['attempt_id'], timestamp(attempt['completed_at_utc']),
            'CURRENT' if attempt['query_id'] == 'CURRENT' else 'HISTORICAL',
            hashlib.sha256(attempt['raw']).hexdigest(), tuple(attempt['outcome']['records']),
            {'transport_contract': self.identity['contract'], 'query_id': attempt['query_id'],
             'attempt_id': attempt['attempt_id'],
             'transport_completion_sha256': attempt['completion_event_sha256'],
             'synthetic_only': attempt['synthetic']})


class BoundedFeedClient:
    """Nonblocking owned HTTP child; explicit network authorization is required."""
    def __init__(self, transport, *, allow_network=False, monotonic=time.monotonic):
        self.transport, self.allow_network, self.monotonic = transport, allow_network, monotonic
        self._observed_completion = None
        self._cooldown_until = None
        self._active = None
        self._controller = None

    def worker_entry(self):
        """Trusted subclass seam; the bounded experiment retains its entry."""
        return Path(__file__).with_name('nasdaq_feed_worker.py')

    @property
    def owns_attempt(self):
        return self._active is not None

    def _completed(self, state):
        last = state['attempts'][-1]['attempt_id'] if state['attempts'] else None
        if last != self._observed_completion:
            self._observed_completion = last
            self._cooldown_until = self.monotonic()+self.transport.limits.interval_seconds if last else None

    @staticmethod
    def _stop(child):
        if child.poll() is None:
            child.terminate()
        try:
            child.wait(timeout=1)
        except subprocess.TimeoutExpired:
            child.kill(); child.wait(timeout=2)

    def _release(self):
        self._active = None
        if self._controller is not None:
            context, self._controller = self._controller, None
            context.__exit__(None, None, None)

    def close_owned(self):
        if self._active is None:
            return
        child, reservation, _ = self._active
        try:
            self._stop(child)
            pending = self.transport.snapshot()['pending']
            if pending and pending['attempt_id'] == reservation['attempt_id']:
                self.transport.finish(reservation, unknown='interrupted')
        finally:
            self._release()

    def step(self, query=None, *, synthetic=None, stop_requested=lambda: False):
        t = self.transport
        if synthetic is None and not self.allow_network:
            raise ValueError('HTTP disabled; explicitly authorize network or supply a synthetic child fixture')
        try:
            if self._active is not None:
                child, reservation, cutoff = self._active
                unknown = None
                if child.poll() is None:
                    if stop_requested():
                        unknown = 'stop_requested'
                    elif self.monotonic() >= cutoff:
                        unknown = 'hard_deadline'
                    else:
                        return {'status': 'acquiring'}
                    self._stop(child)
                elif child.returncode:
                    unknown = 'hard_deadline' if child.returncode == 124 else 'worker_exit'
                state = t.snapshot()
                if state['pending'] and state['pending']['attempt_id'] == reservation['attempt_id']:
                    t.finish(reservation, unknown=unknown or 'worker_exit')
                state = t.snapshot(); self._completed(state)
                self._release()
                return {'status': 'completed', 'attempt': state['attempts'][-1]}
            context = owner_lock(t.path.with_suffix('.controller.lock'))
            context.__enter__(); self._controller = context
            state = t.snapshot()
            if state['pending']:
                try:
                    with owner_lock(t.path.with_suffix('.network.lock')):
                        pending = t.snapshot()['pending']
                        if pending:
                            t.finish(pending, unknown='interrupted')
                except ServiceBusy:
                    self._release()
                    return {'status': 'in_flight_unknown'}
                state = t.snapshot()
            self._completed(state)
            if stop_requested():
                self._release(); return {'status': 'stopped'}
            if self._cooldown_until is not None and self.monotonic() < self._cooldown_until:
                self._release(); return {'status': 'waiting_for_pacing'}
            reservation = t.reserve(query, synthetic=synthetic is not None)
            if reservation is None:
                self._release(); return {'status': 'waiting_or_bounded_stop'}
            state = t.snapshot()
            remaining = (timestamp(state['deadline_utc'])-t.clock()).total_seconds()
            cutoff = self.monotonic()+min(t.limits.hard_timeout_seconds, max(0, remaining))
            job = {'path': str(t.path.resolve()), 'identity': plain(t.identity),
                   'reservation': reservation, 'synthetic': synthetic}
            child = subprocess.Popen([sys.executable, '-I', '-B', str(self.worker_entry())],
                stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self._active = (child, reservation, cutoff)
            try:
                child.stdin.write(json.dumps(job).encode())
            finally:
                child.stdin.close()
            return {'status': 'acquiring'}
        except BaseException:
            if self._active is not None:
                self.close_owned()
            else:
                self._release()
            raise

    def attempt(self, query=None, *, synthetic=None, stop_requested=lambda: False):
        """Convenience blocking API; the supervisor uses step() instead."""
        while True:
            result = self.step(query, synthetic=synthetic, stop_requested=stop_requested)
            if result['status'] != 'acquiring':
                return result
            time.sleep(.02)
