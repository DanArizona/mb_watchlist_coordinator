"""Read-only daily records adapted to the existing Observation Overlay.

No initialization, lease, SDK, network, publication, or process-control calls.
Native membership, selected-symbol quotes and skips share one read transaction.
Feed facts have a separate, explicit knowledge time and availability status.
This display projection is not a replacement for the independent native audit.
"""
from contextlib import closing
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
import json
import sqlite3
import threading
from zoneinfo import ZoneInfo

from .daily_membership_status import MembershipStatusReader, _aware, _path
from .daily_supervision import read_json
from .sampling_requests import digest, plain, timestamp, utc_text
from mb_market_data.quote_observation_store import QuoteObservationStoreError

CONTRACT = 'daily-readonly-overlay-v1'
ET = ZoneInfo('America/New_York')
MAX_POINTS = 20000
KNOWN_GAPS = ('intermediate_feed_mutations_not_reconstructible',
              'older_unknown_carryovers_not_proven_complete')


def _ro(path):
    path = _path(path)
    c = sqlite3.connect(path.as_uri()+'?mode=ro', uri=True, timeout=.25)
    c.execute('PRAGMA query_only=ON')
    return c


@dataclass(frozen=True)
class DailyOverlaySnapshot:
    membership: dict
    overlay: object
    source: dict
    coverage: dict
    candles: dict

    def summary(self):
        o = self.overlay
        return {'contract': CONTRACT, 'membership': self.membership,
                'symbol': o.symbol, 'as_of_utc': utc_text(o.replay_time_utc),
                'current_band': o.current_band.value,
                'quote_points': len(o.quote_points), 'completed_candles': len(o.candles),
                'source': self.source, 'coverage': self.coverage, 'candles': self.candles,
                'provider_access': False, 'process_control': False,
                'membership_writes': False}


class DailyOverlayReader:
    def __init__(self, state_root, *, candle_directory=None, clock=None, expected_journal=None):
        self.membership_reader = MembershipStatusReader(state_root, clock=clock)
        self.root = self.membership_reader.root
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.candle_directory = Path(candle_directory).resolve() if candle_directory else None
        self._verified_source = {}
        self.expected_journal=Path(expected_journal).resolve() if expected_journal else None

    def snapshot(self, symbol=None):
        from mb_market_data.observation_overlay import ObservationOverlayData
        now = _aware(self.clock())
        # Reuse the accepted session/claim/r1/controller binding checks. The
        # native transaction below, rather than this preliminary view, supplies
        # every membership/quote value in the returned chart.
        preliminary = self.membership_reader.snapshot()
        session = read_json(self.root/'session.json')
        binding = session['binding']
        if self.expected_journal is not None and binding['settings']['journal_path']!=str(self.expected_journal):
            raise ValueError('Reviewed summary journal differs from attached daily session')
        day = date.fromisoformat(binding['session_date'])
        cutoff = min(now, datetime.combine(day, time.max, ET))
        native, transitions, points, coverage = self._native(binding, preliminary, cutoff, symbol)
        symbol = native.pop('selected_symbol')
        source, intervals = self._source(binding, day, cutoff, symbol)
        # Knowledge of a saved cache follows the actual observation time. A
        # closed session's drawing cutoff remains on that session, so a cache
        # acquired the next day can still supply its completed old candles.
        cache, candle_status = self._candles(day, now, symbol)
        overlay = ObservationOverlayData(day, symbol, cutoff, cache,
            cache.visible_candles(cutoff) if cache else (), transitions, points, intervals)
        if read_json(self.root/'session.json') != session:
            raise ValueError('Daily binding changed during Overlay read')
        return DailyOverlaySnapshot(native, overlay, source, coverage, candle_status)

    def _native(self, binding, preliminary, cutoff, symbol):
        from mb_market_data.observation_overlay import OverlayMembershipTransition, OverlayQuotePoint, membership_band
        from mb_market_data.quote_observation_store import QuoteObservationStore, SCHEMA_VERSION, _utc_text
        from mb_market_data.sampling_membership import SAMPLING_HIERARCHY_CONTRACT
        from mb_market_data.schwab_quotes import normalize_symbols
        path = _path(binding['settings']['journal_path'])
        day = date.fromisoformat(binding['session_date'])
        parser = QuoteObservationStore(path, session_date=day, schema_version=2)
        at = _utc_text(cutoff, 'cutoff')
        with closing(_ro(path)) as c:
            c.row_factory = sqlite3.Row
            c.execute('BEGIN')
            identity = c.execute('SELECT * FROM store_identity WHERE singleton=1').fetchone()
            if (c.execute('PRAGMA user_version').fetchone()[0] != 2 or identity is None
                    or identity['session_date'] != str(day) or identity['schema_version'] != 2
                    or identity['membership_contract'] != SAMPLING_HIERARCHY_CONTRACT):
                raise ValueError('Overlay journal identity differs')
            rows = c.execute('SELECT * FROM sampling_membership_revision WHERE session_date=? '
                'AND published_at_utc<=? ORDER BY effective_at_utc,revision', (str(day), at,)).fetchall()
            revisions = [parser._membership_revision_from_row(c, row) for row in rows]
            by_number = {r.revision: r for r in revisions}
            if ([by_number[n].content_sha256 for n in (0, 1)] != binding['published_anchor']
                    or by_number[1].content_sha256 != preliminary['baseline_sha256']):
                raise ValueError('Opening Overlay baseline differs')
            visible = [r for r in revisions if r.effective_at <= cutoff]
            current = visible[-1] if visible else None
            choices = sorted({s for r in visible for s in r.uni_symbols})
            if symbol is None:
                symbol = next(iter(current.hot_symbols or current.focus_symbols or current.uni_symbols), None) if current else None
            if symbol is None:
                # A pre-open view may select a published opening symbol, while
                # keeping its membership explicitly not yet effective.
                symbol = next(iter(by_number[1].uni_symbols), None)
            normalized = normalize_symbols((symbol,)) if symbol is not None else ()
            if len(normalized) != 1:
                raise ValueError('One explicit Overlay symbol is required')
            symbol = normalized[0]
            allowed = {s for r in revisions for s in r.uni_symbols}
            if symbol not in allowed:
                raise ValueError('Symbol has no published daily membership history')
            if not choices:
                choices = list(by_number[1].uni_symbols)
            transitions, last_band = [], None
            for r in visible:
                band = membership_band(r, symbol)
                if band != last_band:
                    transitions.append(OverlayMembershipTransition(max(r.effective_at, r.published_at),
                        r.revision, band, r.source, r.reason))
                    last_band = band
            groups = {k: [] for k in ('hot', 'focus', 'uni')}
            if current:
                for k in groups:
                    members = set(getattr(current, k+'_symbols'))
                    if k != 'hot': members -= set(getattr(by_number[1], k+'_symbols'))
                    for s in sorted(members):
                        joined = next(r for r in visible if s in getattr(r, k+'_symbols'))
                        groups[k].append({'symbol': s, 'joined_at_utc': utc_text(joined.effective_at),
                            'revision': joined.revision, 'source': joined.source, 'reason': joined.reason})
            selected = c.execute('SELECT o.*,a.*,p.configuration_json, '
                '(SELECT count(*) FROM quote_observation z WHERE z.acquisition_id=a.acquisition_id) AS actual_rows '
                'FROM quote_observation o JOIN quote_acquisition a ON a.acquisition_id=o.acquisition_id '
                'JOIN poll_run p ON p.run_id=a.run_id WHERE o.symbol=? AND a.session_date=? '
                'AND a.completed_at_utc<=? ORDER BY a.completed_at_utc,a.channel,a.acquisition_id LIMIT ?',
                (symbol, str(day), at, MAX_POINTS+1)).fetchall()
            if len(selected) > MAX_POINTS:
                raise ValueError('Selected-symbol Overlay display bound exceeded')
            points = []
            for row in selected:
                a, o = parser._stored_acquisition(row), parser._stored_observation(row)
                r = by_number.get(a.channel_revision)
                effective = [v for v in visible if v.effective_at <= a.scheduled_at_utc]
                if (r is None or not effective or effective[-1].revision != r.revision
                        or a.channel not in groups or symbol not in getattr(r, a.channel+'_symbols')
                        or row['normalized_schema_version'] != SCHEMA_VERSION
                        or a.requested_symbol_count != row['actual_rows']
                        or a.requested_symbol_count != len(getattr(r, a.channel+'_symbols'))
                        or o.ordinal != getattr(r, a.channel+'_symbols').index(symbol)
                        or not a.scheduled_at_utc <= a.dispatched_at_utc <= a.completed_at_utc
                        or o.response_received_at_utc is not None and o.response_received_at_utc > a.completed_at_utc):
                    raise ValueError('Selected Overlay quote differs from its native membership/header')
                config = json.loads(row['configuration_json'])
                cadence = config.get('poll_seconds')
                if cadence is not None and (not isinstance(cadence, list) or not cadence
                        or any(type(n) is not int or not 0 <= n < 60 for n in cadence)
                        or len(cadence) != len(set(cadence))):
                    raise ValueError('Invalid recorded Overlay cadence')
                points.append(OverlayQuotePoint(a.completed_at_utc, a.scheduled_at_utc, a.acquisition_id,
                    a.channel, a.channel_revision, o.status, o.detail, o.values,
                    tuple(cadence) if cadence is not None else None))
            skips = [dict(r) for r in c.execute('SELECT channel,slot_id,scheduled_at_utc,observed_at_utc,reason '
                'FROM poll_slot_skip WHERE session_date=? AND observed_at_utc<=? '
                'ORDER BY scheduled_at_utc,channel', (str(day), at))]
            tail = c.execute('SELECT scheduled_at_utc,completed_at_utc,requested_symbol_count FROM quote_acquisition '
                'WHERE session_date=? AND channel="hot" AND completed_at_utc<=? '
                'ORDER BY scheduled_at_utc DESC LIMIT 1', (str(day), at)).fetchone()
            native = dict(preliminary, groups=groups, counts={k: len(v) for k,v in groups.items()},
                effective_revision=current.revision if current else None,
                effective_at_utc=utc_text(current.effective_at) if current else None,
                state='READY' if current else 'WAITING_FOR_OPEN', symbols=choices,
                selected_symbol=symbol, last_hot_acquisition=dict(tail) if tail else None)
        return native, tuple(transitions), tuple(points), {
            'recorded_skips': skips, 'recorded_skip_count': len(skips),
            'quote_payload_scope': 'selected symbol only; native membership/header/row-count checks',
            'independent_full_native_audit_required': True,
            'unrecorded_slot_coverage': 'not independently assessed by this display',
            'missing_cadence_runs': sorted({p.acquisition_id for p in points if p.poll_seconds is None})}

    def _source(self, binding, day, cutoff, symbol):
        from .daily_feed import DailyFeedTransport, DailyFeedLimits
        from .nasdaq_recovery import RecoveryQuery
        from .nasdaq_sampling import event_time, halt_event_id
        from mb_market_data.overlay_halts import OverlayHaltInterval

        class SavedTransport(DailyFeedTransport):
            def _connect(self, write=False):
                if write: raise ValueError('Overlay transport is read-only')
                return _ro(self.path)

        key=(binding['binding_sha256'],symbol)
        try:
            journal = Path(binding['settings']['journal_path'])
            claim = read_json(journal.with_suffix('.daily-feed-session.json'))
            if (claim['contract'] != 'daily-source-invocation-v1'
                    or claim['daily_binding_sha256'] != binding['binding_sha256']
                    or read_json(self.root/'daily-source-ready.json') != {'claim': claim, 'status': 'INITIALIZED'}):
                raise ValueError('Source claim differs from daily binding')
            identity = claim['feed_identity']
            queries = tuple(RecoveryQuery(date.fromisoformat(q['halt_date']) if q['halt_date'] else None,
                date.fromisoformat(q['resume_date']) if q['resume_date'] else None) for q in identity['queries'])
            transport = SavedTransport(self.root/'daily-feed.sqlite3', session_date=day,
                queries=queries, limits=DailyFeedLimits(**identity['limits']), clock=lambda: cutoff)
            if plain(transport.identity) != identity:
                raise ValueError('Feed identity differs')
            feed = transport.snapshot()  # Original retained-body/hash/pacing/classification checks.
            authority = claim['authority_identity']
            pub = authority['publication_identity']
            if (authority['contract'] != 'daily-nasdaq-publication-authority-v1'
                    or authority['feed_identity'] != identity
                    or pub['journal'] != {'path':str(journal), 'session_date':str(day), 'schema_version':2}
                    or pub['request_path'] != str(self.root/'requests.sqlite3')):
                raise ValueError('Source authority/feed identity differs')
            previous, statuses, last_at = digest(authority), [], None
            with closing(_ro(self.root/'daily-source.sqlite3')) as c:
                c.execute('BEGIN')
                stored = c.execute('SELECT payload FROM recovery_supervisor_identity WHERE id=1').fetchone()
                if stored is None or json.loads(stored[0]) != authority:
                    raise ValueError('Source authority identity differs')
                for n,(sequence,raw) in enumerate(c.execute('SELECT sequence,payload FROM recovery_supervisor_event ORDER BY sequence'),1):
                    event = json.loads(raw); unsigned = dict(event); sha = unsigned.pop('event_sha256')
                    at = timestamp(event['at_utc'])
                    if (sequence != n or event['sequence'] != n or event['previous_sha256'] != previous
                            or digest(unsigned) != sha or last_at is not None and at < last_at
                            or event['kind'] not in ('status','ingested')):
                        raise ValueError('Source authority history differs')
                    previous, last_at = sha, at
                    if event['kind']=='status' and at<=cutoff: statuses.append(event)
            facts = {}
            for attempt in feed['attempts']:
                at = timestamp(attempt['completed_at_utc'])
                if at>cutoff or attempt['outcome']['status']!='valid': continue
                for row in attempt['outcome']['records']:
                    if row['symbol']!=symbol: continue
                    eid = halt_event_id(row); prior = facts.get(eid)
                    halt = event_time(row)
                    resume = None
                    if row.get('resumption_trade_time'):
                        resume_day = datetime.strptime(row['resumption_date'], '%m/%d/%Y').date()
                        resume = datetime.fromisoformat(str(resume_day)+'T'+''.join(row['resumption_trade_time'].split())).replace(tzinfo=ET)
                        if resume<halt: raise ValueError('Resumption precedes halt')
                    # A missing field is not a retraction of a previously
                    # confirmed time. Nasdaq may also announce a future time;
                    # knowledge is available now, while the plotted span is
                    # still clipped to the observation cutoff.
                    if resume is None and prior and prior['resumption_trade_at_utc']:
                        resume=timestamp(prior['resumption_trade_at_utc'])
                    quote_resume=None
                    if row.get('resumption_quote_time'):
                        qday=datetime.strptime(row['resumption_date'],'%m/%d/%Y').date()
                        quote_resume=datetime.fromisoformat(str(qday)+'T'+''.join(row['resumption_quote_time'].split())).replace(tzinfo=ET)
                        if quote_resume<halt:raise ValueError('Quote resumption precedes halt')
                    elif prior and prior.get('resumption_quote_at_utc'):
                        quote_resume=timestamp(prior['resumption_quote_at_utc'])
                    if halt>cutoff or halt.date()>day or resume is not None and resume.date()<day: continue
                    facts[eid] = {'event_id': eid, 'symbol': symbol, 'reason_code': row['reason_code'],
                        'halt_at_utc': utc_text(halt), 'halt_known_at_utc': prior['halt_known_at_utc'] if prior else utc_text(at),
                        'resumption_trade_at_utc': utc_text(resume) if resume else None,
                        'resumption_known_at_utc': (prior['resumption_known_at_utc'] if prior and
                            prior['resumption_trade_at_utc']==(utc_text(resume) if resume else None) else utc_text(at)) if resume else None,
                        'resumption_quote_at_utc':utc_text(quote_resume) if quote_resume else None,
                        'resumption_quote_known_at_utc':(prior['resumption_quote_known_at_utc'] if prior and
                            prior.get('resumption_quote_at_utc')==(utc_text(quote_resume) if quote_resume else None) else utc_text(at)) if quote_resume else None,
                        'last_capture_at_utc': utc_text(at), 'query_id': attempt['query_id']}
            facts = sorted(facts.values(), key=lambda f:(f['halt_at_utc'],f['event_id']))
            intervals = tuple(OverlayHaltInterval(timestamp(f['halt_at_utc']).astimezone(ET),
                timestamp(f['resumption_trade_at_utc']).astimezone(ET) if f['resumption_trade_at_utc'] else None,
                f['reason_code']) for f in facts)
            last = statuses[-1] if statuses else None
            reasons = sorted(set(KNOWN_GAPS)|set(last.get('reasons',[]) if last else []))
            value={'state': last['status'] if last else 'WAITING_FOR_SOURCE_STATUS', 'fresh': True,
                    'reported_at_utc': last['at_utc'] if last else None,
                    'status_age_seconds': (cutoff-timestamp(last['at_utc'])).total_seconds() if last else None,
                    'progress': 'CURRENT' if last and (cutoff-timestamp(last['at_utc'])).total_seconds()<3 else 'STALE',
                    'known_gaps': reasons, 'facts': facts,
                    'transport_stop_reason': feed['stop_reason'], 'error': None}
            self._verified_source[key]=(cutoff,value,intervals)
            # Keep selected-symbol source history bounded with the chart cache.
            if len(self._verified_source)>8:self._verified_source.pop(next(iter(self._verified_source)))
            return value,intervals
        except (OSError, sqlite3.Error, ValueError, TypeError, KeyError) as e:
            saved=self._verified_source.get(key)
            if saved and saved[0]>cutoff:saved=None
            return {'state':'UNAVAILABLE', 'fresh':False, 'reported_at_utc':None,
                    'known_gaps':list(KNOWN_GAPS), 'facts':saved[1]['facts'] if saved else [],
                    'last_verified_at_utc':utc_text(saved[0]) if saved else None,
                    'error':type(e).__name__}, saved[2] if saved else ()

    def _candles(self, day, cutoff, symbol):
        from mb_market_data.observation_overlay import load_observation_overlay_cache
        if self.candle_directory is None:
            return None, {'state':'NOT_CONFIGURED', 'detail':'No saved candle directory; quote history remains visible'}
        path = self.candle_directory/(symbol+'.json')
        try:
            if path.parent.resolve()!=self.candle_directory or path.is_symlink():
                raise ValueError('Candle path leaves its directory')
            if not path.is_file():
                return None, {'state':'MISSING', 'detail':'No saved candle cache for this symbol'}
            cache = load_observation_overlay_cache(_path(path))
            if cache.symbol!=symbol or cache.session_date!=day:
                raise ValueError('Candle cache session/symbol differs')
            if cache.acquired_at_utc>cutoff:
                return None, {'state':'NOT_YET_AVAILABLE', 'detail':'Cache acquired after this observation time'}
            return cache, {'state':'AVAILABLE', 'detail':'Saved cache; no provider request'}
        except (OSError,ValueError,TypeError,KeyError) as e:
            return None, {'state':'UNAVAILABLE', 'detail':type(e).__name__}


@dataclass(frozen=True)
class OverlayReadResult:
    fresh: bool
    snapshot: DailyOverlaySnapshot | None
    error: str | None = None


class DailyOverlayModel:
    """Keep failed reads explicit and never show another symbol's saved chart."""
    def __init__(self, reader):
        self.reader, self.last_verified = reader, {}
        self._lock = threading.Lock()

    def refresh(self, symbol=None):
        key = symbol.strip().upper() if isinstance(symbol,str) else None
        if not self._lock.acquire(blocking=False):
            return OverlayReadResult(False, self.last_verified.get(key), 'REFRESH_IN_PROGRESS')
        try:
            result = self.reader.snapshot(key)
            self.last_verified[result.overlay.symbol] = result
            self.last_verified[None] = result
            # Bound retained charts, including a selected symbol's full-day data.
            while len(self.last_verified)>9:
                self.last_verified.pop(next(k for k in self.last_verified if k is not None and k!=result.overlay.symbol))
            return OverlayReadResult(True, result)
        except (OSError,sqlite3.Error,QuoteObservationStoreError,ValueError,TypeError,KeyError) as e:
            return OverlayReadResult(False, self.last_verified.get(key), type(e).__name__)
        finally:
            self._lock.release()
