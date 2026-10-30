"""Read-only operator membership view, anchored to the published opening r1.

No store initialization, owner locks, provider calls, or controller commands.
Each refresh uses one short SQLite read transaction and the native revision
parser. Only membership and acquisition headers are read, never quote payloads.
"""
from contextlib import closing
from datetime import date, datetime, timezone
from pathlib import Path
import sqlite3

from .daily_supervision import read_json, unseal
from .sampling_requests import digest, plain, timestamp, utc_text

CONTRACT = 'daily-membership-status-v1'
GROUPS = ('hot', 'focus', 'uni')


def _aware(value):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('Aware observation time required')
    return value


def _path(value):
    path = Path(value)
    if not path.is_absolute() or path != path.resolve() or not path.is_file() or path.is_symlink():
        raise ValueError('Existing canonical file required')
    return path


def _controller(root, daily_binding, now):
    """Assess saved progress. Never acquire a lease or claim OS-owner liveness."""
    if not (root/'driver-binding.json').exists():
        return {'state': 'NOT_STARTED', 'worker': 'not started', 'source': 'not started',
                'detail': 'Waiting for Hot controller startup', 'alerts': []}
    try:
        identity = read_json(root/'driver-binding.json')
        config = read_json(root/'daily-worker.json')
        state = unseal(read_json(root/'driver-state.json'))
        report = unseal(read_json(root/'hot-status.json'))
        live = unseal(read_json(root/'driver-live.json'))
        sha = digest(identity)
        if (identity['configuration_path'] != str(root/'daily-worker.json')
                or identity['configuration_sha256'] != digest(config)
                or config['collector']['daily_binding'] != daily_binding
                or any(v['identity_sha256'] != sha for v in (state, report, live))
                or report['invocation'] != state['active_invocation']
                or live['invocation'] != state['active_invocation']):
            raise ValueError('Controller status binding differs')
        age = (now-timestamp(live['observed_at_utc'])).total_seconds()
        report_age = (now-timestamp(report['observed_at_utc'])).total_seconds()
        if min(age, report_age) < 0:
            raise ValueError('Controller evidence is from the future')
        incidents = unseal(read_json(root/'hot-incidents.json'))
        if incidents['identity_sha256'] != sha:
            raise ValueError('Controller incident binding differs')
        alerts = sorted(k for k, v in incidents['incidents'].items() if v['resolved_at_utc'] is None)
        health = report['state']
        detail = report.get('terminal') or 'Saved controller report; no process control'
        if state['terminal']:
            health, detail = 'BLOCKED', state['terminal']
        elif state['stop']:
            health = 'STOPPED'
            detail = state['stop'].get('reason', 'stopped')
        elif max(age, report_age) >= 3 or live['state'] != 'RUNNING':
            health, detail = 'STALE', 'Controller progress or status is stale'
        return {'state': health, 'worker': report['worker']['status'],
                'source': report['source_status'], 'detail': detail, 'alerts': alerts,
                'source_reconciled': report['source_reconciled'],
                'reported_at_utc': report['observed_at_utc'], 'age_seconds': max(age, report_age)}
    except (OSError, ValueError, TypeError, KeyError) as error:
        return {'state': 'UNAVAILABLE', 'worker': 'unknown', 'source': 'unknown',
                'detail': 'Saved controller evidence unavailable: '+type(error).__name__, 'alerts': []}


class MembershipStatusReader:
    def __init__(self, state_root, *, clock=None):
        self.root = Path(state_root)
        if not self.root.is_absolute() or self.root != self.root.resolve():
            raise ValueError('Canonical absolute state root required')
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.anchor = None

    def snapshot(self):
        now = _aware(self.clock())
        session = read_json(self.root/'session.json')
        binding = session['binding']
        unsigned = dict(binding)
        sha = unsigned.pop('binding_sha256')
        if (session['status'] != 'ATTACHED' or digest(unsigned) != sha
                or binding['contract'] != 'daily-hot-publication-session-v1'
                or binding['settings']['state_root'] != str(self.root)
                or session['claim']['binding_sha256'] != sha
                or session['claim']['state_root'] != str(self.root)
                or len(binding['published_anchor']) != 2):
            raise ValueError('Attached daily membership binding required')
        day = date.fromisoformat(binding['session_date'])
        path = _path(binding['settings']['journal_path'])
        if path.name != str(day)+'.sqlite3':
            raise ValueError('Journal session filename differs')
        if read_json(path.with_suffix('.daily-hot-session.json')) != session['claim']:
            raise ValueError('Daily journal claim differs')
        anchor = (sha, str(path), day, tuple(binding['published_anchor']))
        if self.anchor is not None and anchor != self.anchor:
            raise ValueError('Opening r1 anchor changed; reopen for a different session')

        from mb_market_data.quote_observation_store import QuoteObservationStore, _utc_text
        from mb_market_data.sampling_membership import SAMPLING_HIERARCHY_CONTRACT
        parser = QuoteObservationStore(path, session_date=day, schema_version=2)
        # mode=ro refuses a missing database; query_only also forbids writes.
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro', uri=True, timeout=.25)) as c:
            c.row_factory = sqlite3.Row
            c.execute('PRAGMA query_only=ON')
            c.execute('BEGIN')
            identity = c.execute('SELECT * FROM store_identity WHERE singleton=1').fetchone()
            if (c.execute('PRAGMA user_version').fetchone()[0] != 2 or identity is None
                    or identity['schema_version'] != 2 or identity['session_date'] != str(day)
                    or identity['membership_contract'] != SAMPLING_HIERARCHY_CONTRACT):
                raise ValueError('Journal identity differs')
            parsed = {}

            def revision(row):
                if row is None:
                    raise ValueError('Required published revision is missing')
                number = row['revision']
                if number not in parsed:
                    value = parser._membership_revision_from_row(c, row)
                    if value.session_date != day or value.published_at > now:
                        raise ValueError('Revision session or publication time differs')
                    parsed[number] = value
                return parsed[number]

            anchors = [revision(c.execute('SELECT * FROM sampling_membership_revision '
                'WHERE session_date=? AND revision=?', (str(day), n)).fetchone()) for n in (0, 1)]
            if ([v.content_sha256 for v in anchors] != binding['published_anchor']
                    or anchors[0].uni_symbols != anchors[1].uni_symbols
                    or any(v.effective_at != timestamp(binding['start_at_utc']) for v in anchors)
                    or anchors[0].focus_symbols or anchors[0].hot_symbols or anchors[1].hot_symbols):
                raise ValueError('Published opening r0/r1 differs')
            r1 = anchors[1]
            row = c.execute('SELECT * FROM sampling_membership_revision '
                'WHERE session_date=? AND effective_at_utc<=? '
                'ORDER BY effective_at_utc DESC,revision DESC LIMIT 1',
                (str(day), _utc_text(now, 'now'))).fetchone()
            current = revision(row) if row is not None else None
            if current is not None and current.revision < 1:
                raise ValueError('Effective opening r1 is missing')
            groups = {k: [] for k in GROUPS}
            if current is not None:
                for channel in GROUPS:
                    symbols = set(getattr(current, channel+'_symbols'))
                    if channel != 'hot':
                        symbols -= set(getattr(r1, channel+'_symbols'))
                    for symbol in sorted(symbols):
                        first = c.execute('SELECT r.* FROM sampling_membership_revision r '
                            'JOIN sampling_channel_member m ON m.session_date=r.session_date AND m.revision=r.revision '
                            'WHERE r.session_date=? AND m.channel=? AND m.symbol=? '
                            'AND r.effective_at_utc<=? ORDER BY r.effective_at_utc,r.revision LIMIT 1',
                            (str(day), channel, symbol, _utc_text(now, 'now'))).fetchone()
                        joined = revision(first)
                        groups[channel].append({'symbol': symbol, 'joined_at_utc': utc_text(joined.effective_at),
                            'revision': joined.revision, 'source': joined.source, 'reason': joined.reason})
            last = c.execute('SELECT scheduled_at_utc,completed_at_utc,requested_symbol_count '
                'FROM quote_acquisition WHERE session_date=? AND channel=? AND scheduled_at_utc<=? '
                'ORDER BY scheduled_at_utc DESC LIMIT 1', (str(day), 'hot', _utc_text(now, 'now'))).fetchone()
        self.anchor = anchor
        return {'contract': CONTRACT, 'observed_at_utc': utc_text(now), 'session_date': str(day),
                'journal_path': str(path), 'baseline_revision': 1, 'baseline_sha256': r1.content_sha256,
                'effective_revision': current.revision if current else None,
                'effective_at_utc': utc_text(current.effective_at) if current else None,
                'state': 'READY' if current else 'WAITING_FOR_OPEN', 'groups': groups,
                'counts': {k: len(v) for k, v in groups.items()},
                'opening_counts': {k: len(getattr(r1, k+'_symbols')) for k in GROUPS},
                'controller': _controller(self.root, binding, now),
                'last_hot_acquisition': dict(last) if last else None,
                'provider_access': False, 'process_control': False}


class MembershipDisplayModel:
    """Retain last verified lists with an explicit error banner on a failed read."""
    def __init__(self, reader):
        self.reader, self.last_verified = reader, None

    def refresh(self):
        from mb_market_data.quote_observation_store import QuoteObservationStoreError
        try:
            result = self.reader.snapshot()
            self.last_verified = plain(result)
            return dict(result, fresh=True, error=None)
        except (OSError, sqlite3.Error, QuoteObservationStoreError, ValueError, TypeError, KeyError) as error:
            return {'contract': CONTRACT, 'fresh': False, 'error': type(error).__name__,
                    'last_verified': plain(self.last_verified) if self.last_verified is not None else None}


def et_text(value):
    from zoneinfo import ZoneInfo
    return timestamp(value).astimezone(ZoneInfo('America/New_York')).strftime('%Y-%m-%d %H:%M:%S %Z')


def display_lines(value):
    """Common presentation model for the window and one-shot JSON/text output."""
    current = value if value.get('fresh') else value.get('last_verified')
    if current is None:
        return {'banner': 'MEMBERSHIP UNAVAILABLE - waiting for verified session evidence',
                'context': 'Read failure: '+str(value.get('error')),
                'health': 'Controller status unavailable', 'collection': 'Last Hot acquisition: unknown',
                'warning': 'No membership has been verified.',
                'panels': {k: ['Unavailable'] for k in GROUPS}, 'counts': {k: '?' for k in GROUPS}}
    fresh = value.get('fresh') is True
    banner = ('MEMBERSHIP VERIFIED' if current['state'] == 'READY' else 'WAITING FOR OPENING r1') if fresh else 'READ FAILED - showing LAST VERIFIED membership'
    context = (f"Session {current['session_date']} | opening baseline r1 | effective "
               f"r{current['effective_revision']} | verified {et_text(current['observed_at_utc'])}")
    if current['effective_revision'] is None:
        context = context.replace('effective rNone', 'opening membership not yet effective')
    h = current['controller']
    health = f"Controller: {h['state']} | Collector (saved): {h['worker']} | Source (saved): {h['source']}"
    if not fresh:
        health = 'LAST VERIFIED health: '+health+' | current health unavailable'
    last = current['last_hot_acquisition']
    collection = ('Last committed Hot slot: '+et_text(last['scheduled_at_utc'])+
                  f" | symbols requested: {last['requested_symbol_count']}") if last else 'Last committed Hot slot: none recorded'
    warning = h['detail']
    if h['alerts']:
        names = {'source:gap': 'Known gaps in Nasdaq feed history',
                 'worker:recovery': 'Hot worker recovery in progress',
                 'controller:blocked': 'Hot controller blocked'}
        warning += ' | '+', '.join(names.get(k, k) for k in h['alerts'])
    if not fresh:
        warning = 'Read failure: '+str(value.get('error'))+' | '+warning
    panels = {}
    for channel in GROUPS:
        panels[channel] = [item['symbol']+'   '+et_text(item['joined_at_utc']).split(' ', 1)[1]
                           for item in current['groups'][channel]]
        if not panels[channel]:
            panels[channel] = ['Waiting for opening'] if current['state'] != 'READY' else [
                'No current Hot members' if channel == 'hot' else 'None added since r1']
    return dict(banner=banner, context=context, health=health, collection=collection,
                warning=warning, panels=panels, counts=current['counts'])
