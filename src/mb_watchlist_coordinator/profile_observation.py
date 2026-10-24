"""Read acknowledged native progress without taking the acquisition writer lease.

The native prefix is captured first. Its acknowledged journal rows must already
be committed, so a later journal snapshot can verify them without counting
newer work. This is progress observation, not the final full native audit.
The final reporter still calls the original strict, quiescent snapshot.
"""
from contextlib import closing
import json
import sqlite3

from .sampling_requests import utc_text


class ObservationPending(RuntimeError):
    """A bounded SQLite BUSY read is deferred to the next observer turn."""


def observe_native_facts(session, *, generation_for, after_prefix=None):
    try:return _observe_native_facts(session,generation_for=generation_for,after_prefix=after_prefix)
    except sqlite3.OperationalError as error:
        code=getattr(error,'sqlite_errorcode',None)
        if type(code) is int and code & 0xff == sqlite3.SQLITE_BUSY:
            raise ObservationPending('Native progress read is busy') from None
        raise


def _observe_native_facts(session, *, generation_for, after_prefix=None):
    from mb_market_data.sampling_acquisition import canonical,digest,stamp,ExplicitPollSlot
    poller=session.collector.poller
    if (poller.settings.payload()!=poller.identity['settings']
            or str(poller.journal.database_path.resolve())!=poller.identity['journal']):
        raise ValueError('Native progress configuration differs')
    with closing(sqlite3.connect(poller.path.resolve().as_uri()+'?mode=ro',uri=True,timeout=.1)) as c:
        c.execute('BEGIN')
        if c.execute('SELECT payload FROM acquisition_identity WHERE id=1').fetchone()!=(canonical(poller.identity),):
            raise ValueError('Native progress identity differs')
        prefix=list(c.execute('SELECT * FROM acquisition_event ORDER BY sequence'))
    if after_prefix is not None:after_prefix()  # Trusted offline concurrency seam only.
    previous=digest(poller.identity);events=[];pending=None;finished=set();last=None;facts=[]
    # Open the journal AFTER the native prefix. Never require newer unrelated
    # journal work to be present in an older acknowledged native prefix.
    with closing(sqlite3.connect(poller.journal.database_path.resolve().as_uri()+'?mode=ro',uri=True,timeout=.1)) as journal:
        journal.row_factory=sqlite3.Row;journal.execute('BEGIN')
        for sequence,raw,prior,sha in prefix:
            e=json.loads(raw);at=stamp(e['recorded_at_utc'])
            if (sequence!=len(events)+1 or prior!=previous
                    or sha!=digest({'sequence':sequence,'payload':e,'previous_sha256':prior})
                    or last is not None and at<last):
                raise ValueError('Native progress prefix hash/clock differs')
            kind=e['kind'];slot=e['slot_id']
            if kind=='dispatch':
                if pending is not None or slot in finished:raise ValueError('Overlapping native progress dispatch')
                observed_slot=ExplicitPollSlot(poller.settings.channel,stamp(e['scheduled_at_utc']),poller.settings.seconds)
                if observed_slot.slot_id!=slot or not poller.settings.window.contains(observed_slot.scheduled_at):
                    raise ValueError('Native progress slot differs')
                pending={'dispatch':e,'assembled':None}
            elif kind=='assembled':
                if pending is None or pending['dispatch']['slot_id']!=slot or pending['assembled'] is not None:
                    raise ValueError('Native progress assembly differs')
                pending.update(assembled=e,assembled_event_sha256=sha)
            elif kind=='acknowledged':
                if pending is None or pending['dispatch']['slot_id']!=slot:raise ValueError('Orphan native progress acknowledgement')
                receipt=poller._receipt(pending,connection=journal)
                if receipt is None or receipt!=e['journal_receipt']:raise ValueError('Native progress acknowledgement differs')
                if receipt['kind']=='acquisition':
                    row=journal.execute('SELECT * FROM quote_acquisition WHERE acquisition_id=?',(receipt['id'],)).fetchone()
                    a=poller.journal._stored_acquisition(row)
                    rows=journal.execute('SELECT symbol,status FROM quote_observation WHERE acquisition_id=? ORDER BY ordinal',(a.acquisition_id,)).fetchall()
                    symbols=[r['symbol'] for r in rows];statuses=[r['status'] for r in rows]
                    facts.append({'id':a.acquisition_id,'slot_id':a.slot_id,'run_id':a.run_id,
                        'scheduled_at_utc':utc_text(a.scheduled_at_utc),'completed_at_utc':utc_text(a.completed_at_utc),
                        'ack_at_utc':e['recorded_at_utc'],'generation':generation_for(a),
                        'symbols':symbols,'statuses':statuses,'quote':len(symbols)==1 and statuses==['quote'],
                        'content_sha256':a.content_sha256})
                finished.add(slot);pending=None
            elif kind=='write_failed':
                if pending is None or pending['dispatch']['slot_id']!=slot:raise ValueError('Orphan native progress write failure')
                # A retained assembled response may still recover and ACK.
            elif kind=='abandoned':
                if pending is None or pending['dispatch']['slot_id']!=slot:raise ValueError('Orphan native progress outcome')
                finished.add(slot);pending=None
            elif kind=='missed':
                if pending is not None or slot in finished:raise ValueError('Conflicting native progress miss')
                finished.add(slot)
            else:raise ValueError('Unknown native progress event')
            events.append(dict(e,sequence=sequence,event_sha256=sha));previous=sha;last=at
    return tuple(facts),{'events':events,'pending':pending,'head_sha256':previous,'progress_observation_only':True}
