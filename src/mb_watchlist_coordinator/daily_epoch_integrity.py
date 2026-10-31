"""Independent comparison of Hot values against verified period receipts.

SQLite numeric affinity can change the writer's int/float representation, so an
original acquisition fingerprint cannot be recomputed from database rows alone.
Period receipts instead bind the exact stored values checked by the native
acquisition reader. Coverage/membership audit and replay sequence are separate.
"""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3

from mb_market_data.quote_journal_replay import QuoteJournalReplayReader
from .sampling_requests import digest


def stored_values_digest(headers,observations,skips):
    """Canonical digest of SQLite values, independent of physical row order."""
    values={'headers':sorted(map(tuple,headers),key=lambda r:r[0]),
        'observations':sorted(map(tuple,observations),key=lambda r:(r[0],r[2])),
        'skips':sorted(map(tuple,skips),key=lambda r:r[0])}
    return {'acquisitions':len(values['headers']),'observations':len(values['observations']),
        'skips':len(values['skips']),'stored_values_sha256':digest(values)}


def verified_period_digest(poller):
    # A native live/shutdown snapshot must have succeeded immediately before this call. These are
    # the complete SQLite values that its native assembled-response checks used.
    cache=poller._verified_history
    if cache is None:raise ValueError('Native period verification required')
    return stored_values_digest(cache['raw_headers'],cache['raw_observations'],cache['raw_skips'])


def verify_journal_content(path, *, expected_settings=None,unfinished_validator=None):
    path=Path(path).resolve();errors=[];acquisitions=observations=skips=0
    manifest=json.loads(path.with_suffix('.hot.periods.json').read_text())
    body=dict(manifest);sha=body.pop('content_sha256')
    if sha!=digest(body)or expected_settings is not None and body['settings']!=expected_settings:
        raise ValueError('Original bound period manifest required')
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True))as c:
        c.execute('BEGIN')
        for index,start,stop,_ in body['windows']:
            # Native UTC uses fixed microseconds and Z; public period text uses
            # aware ISO. Convert rather than compare unlike timestamp strings.
            from mb_market_data.quote_observation_store import _utc_text
            from .sampling_requests import timestamp
            bounds=tuple(_utc_text(timestamp(at),'period')for at in (start,stop))
            headers=c.execute('SELECT * FROM quote_acquisition WHERE channel="hot" AND '
                'scheduled_at_utc>=? AND scheduled_at_utc<? ORDER BY acquisition_id',bounds).fetchall()
            rows=c.execute('SELECT o.* FROM quote_acquisition h JOIN quote_observation o '
                'ON h.acquisition_id=o.acquisition_id WHERE h.channel="hot" AND '
                'h.scheduled_at_utc>=? AND h.scheduled_at_utc<? ORDER BY h.acquisition_id,o.ordinal',bounds).fetchall()
            skip_rows=c.execute('SELECT * FROM poll_slot_skip WHERE channel="hot" AND '
                'scheduled_at_utc>=? AND scheduled_at_utc<? ORDER BY slot_id',bounds).fetchall()
            actual=stored_values_digest(headers,rows,skip_rows)
            receipts=[path.with_suffix(f'.hot.e{index:02d}.{suffix}.json')for suffix in ('closed','checkpoint')]
            receipt=next((p for p in receipts if p.is_file()),None)
            value=None;valid=False
            if receipt is not None:
                raw=json.loads(receipt.read_text());value=dict(raw);expected=value.pop('content_sha256')
                valid=(expected==digest(value)and value['parent_sha256']==digest(body['settings'])
                    and (value['index'],value['start'],value['stop'])==(index,start,stop)
                    and value['verified_stored_values']==actual)
            is_closed=receipts[0].exists()
            if not valid and not is_closed and unfinished_validator is not None:
                ledger=path.with_suffix(f'.hot.e{index:02d}.poller.sqlite3')
                if ledger.is_file():
                    try:valid=unfinished_validator(index)==actual
                    except (ValueError,OSError,sqlite3.Error)as error:
                        errors.append(f'period_{index}:native_readback_'+type(error).__name__)
            if not valid and (receipt is not None or headers or rows or skip_rows):
                errors.append(f'period_{index}:verified_stored_values_unavailable_or_differ')
            acquisitions+=len(headers);observations+=len(rows);skips+=len(skip_rows)
        total=c.execute('SELECT count(*) FROM quote_acquisition WHERE channel="hot"').fetchone()[0]
        total_rows=c.execute('SELECT count(*) FROM quote_observation o JOIN quote_acquisition h '
            'ON h.acquisition_id=o.acquisition_id WHERE h.channel="hot"').fetchone()[0]
        total_skips=c.execute('SELECT count(*) FROM poll_slot_skip WHERE channel="hot"').fetchone()[0]
        if (total,total_rows,total_skips)!=(acquisitions,observations,skips):errors.append('hot_values_outside_period_schedule')
    return {'contract':'full-hot-journal-content-check-v1','passed':not errors,
        'acquisitions':acquisitions,'observations':observations,'skips':skips,
        'error_count':len(errors),'errors':errors[:20],
        'scope':'All Hot stored values against native-verified period receipts; other channels covered by native audit'}


def replay_sequence_digest(path):
    reader=QuoteJournalReplayReader(path);sha=hashlib.sha256();count=0
    for value in reader._ordered_headers():
        event_id=(value.event_id if hasattr(value,'event_id')else
            'quote_acquisition:'+value.acquisition_id)
        count+=1;sha.update((event_id+'\n').encode())
    return {'events':count,'sequence_sha256':sha.hexdigest()}
