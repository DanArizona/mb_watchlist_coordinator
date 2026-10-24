"""Read-only native evidence and fixed goals for the bounded Hot profiles.

Raw audit failures are retained even when a deliberate recovery outage explains
missing coverage. No source/admission/native ledger is changed by reporting.
"""
from dataclasses import fields, is_dataclass
from datetime import date, datetime, timedelta
from collections.abc import Mapping
import hashlib
import json
from pathlib import Path

from .sampling_requests import canonical, digest, plain, timestamp, utc_text

PROFILES = ('ordinary','owned_worker_recovery')


def wire(value):
    if is_dataclass(value):return {f.name:wire(getattr(value,f.name)) for f in fields(value)}
    if isinstance(value,Mapping):return {k:wire(v) for k,v in value.items()}
    if isinstance(value,(tuple,list)):return [wire(v) for v in value]
    if isinstance(value,(date,datetime)):return value.isoformat()
    if isinstance(value,Path):return str(value)
    return value


def native_facts(session, *, generation_for):
    """Count only validated, committed AND acknowledged one-symbol quotes."""
    from mb_market_data.quote_journal_replay import QuoteJournalReplayReader, QuoteAcquisitionEvent
    state=session.collector.poller.snapshot()  # Includes native header/row/ledger validation.
    acks={e['journal_receipt']['id']:e for e in state['events']
        if e['kind']=='acknowledged' and e['journal_receipt']['kind']=='acquisition'}
    result=[]
    for event in QuoteJournalReplayReader(session.store.database_path).events():
        if not isinstance(event,QuoteAcquisitionEvent):continue
        a=event.acquisition
        if a.channel!='hot':raise ValueError('Experimental Uni/Focus acquisitions are forbidden')
        ack=acks.get(a.acquisition_id)
        rows=event.observations
        result.append({'id':a.acquisition_id,'slot_id':a.slot_id,'run_id':a.run_id,
            'scheduled_at_utc':utc_text(a.scheduled_at_utc),'completed_at_utc':utc_text(a.completed_at_utc),
            'ack_at_utc':ack['recorded_at_utc'] if ack else None,
            'generation':generation_for(a),
            'symbols':[row.symbol for row in rows],
            'statuses':[str(row.status) for row in rows],
            'quote':bool(ack and len(rows)==1 and str(rows[0].status)=='quote'),
            'content_sha256':a.content_sha256})
    return tuple(result),state


def goal_counts(profile, facts, *, cutover_at_utc, fault=None, restart=None):
    if profile not in PROFILES:raise ValueError('Unknown profile')
    ids=[f['id'] for f in facts];slots=[f['slot_id'] for f in facts]
    if len(set(ids))!=len(ids) or len(set(slots))!=len(slots):raise ValueError('Duplicate profile acquisitions')
    cutover=timestamp(cutover_at_utc) if cutover_at_utc else None
    eligible=[f for f in facts if f['quote'] and f['ack_at_utc'] is not None
        and cutover is not None and timestamp(f['scheduled_at_utc'])>cutover]
    if profile=='ordinary':return {'after_cutover':len(eligible),'goal_complete':len(eligible)>=30}
    before=after=0
    if fault:
        requested=timestamp(fault['requested_at_utc']);exited=timestamp(fault['exit_observed_at_utc'])
        if exited<requested:raise ValueError('Fault exit precedes request')
        before=sum(timestamp(f['ack_at_utc'])<=requested and f['generation']==fault['generation'] for f in eligible)
        if fault['last_acknowledged_id'] not in {f['id'] for f in eligible
                if timestamp(f['ack_at_utc'])<=requested}:raise ValueError('Fault lacks a committed acknowledged acquisition')
    if restart:
        if (not fault or restart['generation']!=fault['generation']+1
                or restart['token']==fault['token'] or restart['pid']==fault['pid']
                or timestamp(restart['started_at_utc'])<timestamp(fault['exit_observed_at_utc'])+timedelta(seconds=15)
                or timestamp(restart['ready_at_utc'])<timestamp(restart['started_at_utc'])):
            raise ValueError('Replacement identity/hold differs')
        after=sum(f['generation']==restart['generation']
            and timestamp(f['scheduled_at_utc'])>=timestamp(restart['first_eligible_slot_utc'])
            and timestamp(f['ack_at_utc'])>=timestamp(restart['ready_at_utc']) for f in eligible)
    return {'before_fault':before,'after_restart':after,
        'goal_complete':bool(fault and restart and before>=12 and after>=24)}


def final_native_report(session, *, profile, facts, stop_at_utc, cutover_at_utc,
                        source_reconciled, source_reasons=(), fault=None, restart=None):
    from mb_market_data.quote_journal_audit import audit_quote_journal
    from mb_market_data.quote_journal_replay import QuoteJournalReplayReader
    stop=timestamp(stop_at_utc)
    goals=goal_counts(profile,[f for f in facts if f['ack_at_utc'] is not None
        and timestamp(f['ack_at_utc'])<=stop],cutover_at_utc=cutover_at_utc,fault=fault,restart=restart)
    audit=audit_quote_journal(session.store.database_path,audited_at=stop)
    def replay():
        h=hashlib.sha256();count=0
        for event in QuoteJournalReplayReader(session.store.database_path).events():
            h.update((canonical(wire(event))+'\n').encode());count+=1
        return {'sha256':h.hexdigest(),'events':count}
    replays=(replay(),replay())
    missing=sorted(s for c in audit.channels for s in c.missing_slot_ids)
    explained=[]
    if fault and restart:
        # Only slots after the last acknowledged committed slot, and strictly
        # before the replacement's first eligible future slot, can be explained.
        last=next(f for f in facts if f['id']==fault['last_acknowledged_id'])
        lo=timestamp(fault['requested_at_utc']);hi=timestamp(restart['first_eligible_slot_utc'])
        explained=[s for s in missing if s.startswith('hot:') and lo<=timestamp(s[4:])<hi]
    unexplained=sorted(set(missing)-set(explained))
    non_missing=[wire(f) for f in audit.findings if f.code!='missing_poll_slots']
    bad_quotes=[f['id'] for f in facts if not f['quote']]
    status=('FAILED' if non_missing or unexplained or bad_quotes or replays[0]!=replays[1]
        else 'INCOMPLETE' if not source_reconciled
        else 'READINESS_ONLY' if not facts
        else 'INCOMPLETE' if not goals['goal_complete']
        else 'PASS_WITH_WARNINGS' if source_reasons or explained else 'PASS')
    # Preserve the native raw verdict. Explained gaps never rewrite it to PASS.
    return {'contract':'bounded-hot-profile-native-evidence-v1','result':status,'profile':profile,
        'audited_at_utc':utc_text(stop),'goals':goals,'source_reconciled':bool(source_reconciled),
        'source_reasons':list(source_reasons),'raw_native_audit_passed':audit.passed,
        'raw_native_audit':wire(audit),
        'missing_slot_ids':missing,'intentional_outage_missing_slot_ids':explained,
        'unexplained_missing_slot_ids':unexplained,'non_quote_acquisition_ids':bad_quotes,
        'replays':list(replays),'identical_fresh_replays':replays[0]==replays[1],
        'facts_sha256':digest(facts),'production_access':False}
