"""Native offline paired workload proof. Historical counts, synthetic availability.

Source captures here contain changed event rows, not 390 cumulative minute RSS
snapshots. Producer retained-history, mixed-source, full-day and provider capacity
remain separate qualifications. No historical release foreknowledge is implied.
"""
from __future__ import annotations
import argparse
from collections import Counter
from contextlib import closing
from datetime import date, datetime, time as day_time, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import socket
import sqlite3
import statistics
import sys
import time
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).parent
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'experiments/sampling_promotion_20261016/market_data/src')]
from mb_market_data.quote_journal_audit import audit_quote_journal
from mb_market_data.quote_journal_replay import QuoteJournalReplayReader
from mb_market_data.quote_observation_store import QuoteObservationStore
from mb_market_data.sampling_membership import SamplingHierarchyRevision
from mb_watchlist_coordinator.nasdaq_sampling import HaltProducerSettings,HaltSnapshot,NasdaqSamplingProducer
from mb_watchlist_coordinator.sampling_journal import SamplingJournal
from mb_watchlist_coordinator.sampling_policy import SamplingPolicy
from mb_watchlist_coordinator.sampling_projection import SamplingMembership
from mb_watchlist_coordinator.sampling_request_store import SamplingRequestStore
from mb_watchlist_coordinator.sampling_requests import digest,plain
from mb_watchlist_coordinator.sampling_service import PublicationSettings,SamplingPublicationService

ET=ZoneInfo('America/New_York')
SESSION=date(2026,11,2)  # synthetic date, not a calendar or market-open assertion
START=datetime.combine(SESSION,day_time(9,30),ET)
STOP=START.replace(hour=16,minute=0)

def denied(*args,**kw):raise RuntimeError('Network denied in Nasdaq reuse qualification')

def stats(values):
    values=sorted(values)
    return {'samples':len(values),'median':statistics.median(values),
            'p95':values[math.ceil(.95*len(values))-1],'maximum':max(values)}

def hashes(folder):
    return {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(Path(folder).glob('*.sqlite3'))}

def datasets():
    facts=json.loads((HERE/'workload_facts.json').read_text())
    result={}
    for name,c in facts['cases'].items():
        result[name]=[{'symbol':r['symbol'],'halt_time_et':r['halt_time_et'],
                      'reason_code':'LUDP' if 'LUDP' in r['reason_codes_observed'] else 'M'} for r in c['events']]
    result['margin']=[{'symbol':f'X{i%40:03d}',
        'halt_time_et':(START+timedelta(seconds=60+140*i)).strftime('%H:%M:%S.%f'),
        'reason_code':'LUDP'} for i in range(160)]
    return result

def build(folder,rows,reuse,*,samples=30):
    if type(samples) is not int or not 2<=samples<=100:raise ValueError('samples must be 2..100')
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=False)
    clock=[START];symbols=sorted({r['symbol'] for r in rows})
    uni=tuple(symbols+[f'Z{i:04d}' for i in range(553-len(symbols))])
    baseline=SamplingMembership(frozenset(uni),frozenset(uni[-40:]),frozenset())
    def open_objects():
        requests=SamplingRequestStore(folder/'requests.sqlite3',session_date=SESSION,baseline=baseline,
            policy=SamplingPolicy('admin',0,0,'immediate_cap'),clock=lambda:clock[0])
        native=QuoteObservationStore(folder/'membership.sqlite3',session_date=SESSION,schema_version=2)
        service=SamplingPublicationService(folder/'publication.sqlite3',request_store=requests,
            journal=SamplingJournal(native),settings=PublicationSettings('reuse-study',1,.1,STOP),clock=lambda:clock[0])
        producer=NasdaqSamplingProducer(folder/'nasdaq.sqlite3',request_store=requests,
            settings=HaltProducerSettings('nasdaq-study',('LUDP','M'),'regular_close',False,reuse),clock=lambda:clock[0])
        return requests,native,service,producer
    requests,native,service,producer=open_objects()
    requests.initialize();native.initialize()
    native.record_membership_revision(SamplingHierarchyRevision(session_date=SESSION,revision=0,
        effective_at=START-timedelta(seconds=1),uni_symbols=uni,focus_symbols=tuple(baseline.focus),hot_symbols=(),
        source='synthetic-nasdaq-workload',metadata={'synthetic_only':True,'logical_clock':True}))
    service.initialize();producer.initialize()
    producer.record_snapshot(HaltSnapshot('baseline',START,'CURRENT',digest([]),(),{'synthetic_only':True}))
    actions=[]
    for i,r in enumerate(rows):
        halt=datetime.combine(SESSION,day_time.fromisoformat(r['halt_time_et']),ET)
        row={'symbol':r['symbol'],'halt_date':SESSION.strftime('%m/%d/%Y'),
             'halt_time':r['halt_time_et'],'reason_code':r['reason_code']}
        actions.append((halt+timedelta(seconds=1),f'halt-{i}',row,True))
        # Both announced release times and their availability are explicitly
        # fabricated for retention proof, never recovered from final history.
        actions.append((halt+timedelta(seconds=31),f'update-{i}',dict(row,
            resumption_quote_time=(halt+timedelta(minutes=5)).strftime('%H:%M:%S'),
            resumption_trade_time=(halt+timedelta(minutes=6)).strftime('%H:%M:%S')),False))
    checkpoints=[];timing={k:[] for k in ['capture','delivery','service']}
    begin=time.perf_counter();last_progress=begin
    for index,(at,cid,row,is_halt) in enumerate(sorted(actions,key=lambda a:(a[0],a[1])),1):
        if time.perf_counter()-begin>600:
            raise TimeoutError('Synthetic fixture construction exceeded its 600-second budget; retained partial databases are not a PASS')
        clock[0]=at
        snapshot=HaltSnapshot(cid,at,'CURRENT',digest([row]),(row,),
            {'synthetic_only':True,'logical_clock':True,'fabricated_availability':True})
        before=time.perf_counter();producer.record_snapshot(snapshot);timing['capture'].append(time.perf_counter()-before)
        before=time.perf_counter();producer.deliver_pending();timing['delivery'].append(time.perf_counter()-before)
        before=time.perf_counter();service.cycle();timing['service'].append(time.perf_counter()-before)
        applied=requests.states()[-1].applied
        checkpoints.append({'at':at.isoformat(),'capture_id':cid,'hot':sorted(applied.hot),
                            'focus':sorted(applied.focus),'uni':sorted(applied.uni)})
        if time.perf_counter()-last_progress>=15:
            print('  Synthetic actions',index,'/',len(actions),'elapsed',round(time.perf_counter()-begin,1),'seconds',flush=True)
            last_progress=time.perf_counter()
    construction=time.perf_counter()-begin
    source=plain(producer.snapshot())
    facts=[{'recorded_at_utc':r['recorded_at_utc'],'snapshot':r['snapshot']} for r in source['receipts']]
    assert len(source['commands'])==len(rows) and not source['pending']
    for at,cid,row,is_halt in actions:
        match=next(r for r in facts if r['snapshot']['capture_id']==cid)
        assert match['snapshot']['records']==[row] or (
            match['snapshot']['records'][0]['halt_time']==day_time.fromisoformat(row['halt_time']).strftime('%H:%M:%S.%f') and
            {k:v for k,v in match['snapshot']['records'][0].items() if k!='halt_time'}=={k:v for k,v in row.items() if k!='halt_time'})
        assert datetime.fromisoformat(match['recorded_at_utc'])==at
    events,_,aliases=requests.validated_reuse_history()
    count=len(events)
    assert count==(len(symbols) if reuse else len(rows))
    assert len(aliases)==(len(rows)-len(symbols) if reuse else 0)
    native_rows=native.membership_revisions_in_effective_order()
    assert len(native_rows)==len(symbols)+1
    audit=audit_quote_journal(native.database_path);assert audit.passed
    def replay_hash():
        return digest([(e.event_id,e.revision.content_sha256) for e in QuoteJournalReplayReader(native.database_path).events()])
    replay1,replay2=replay_hash(),replay_hash();assert replay1==replay2
    clock[0]=STOP-timedelta(seconds=1)
    assert service.cycle()['status']=='idle'
    assert requests.states()[-1].applied.hot==frozenset(symbols)
    before_hashes=hashes(folder);snapshot_digest=digest(plain(service.snapshot()))
    elapsed=[]
    for _ in range(samples):
        before=time.perf_counter();decision=service.cycle();elapsed.append(time.perf_counter()-before)
        assert decision['status']=='idle'
    idle=stats(elapsed)
    assert hashes(folder)==before_hashes
    assert requests.states()[-1].applied.hot==frozenset(symbols)
    before=time.perf_counter();r,n,s,p=open_objects();assert digest(plain(s.snapshot()))==snapshot_digest
    assert plain(p.snapshot())==source
    cold=time.perf_counter()-before
    assert hashes(folder)==before_hashes
    summary={'reuse':reuse,'halts':len(rows),'symbols':len(symbols),'source_captures':len(source['receipts']),
        'commands':len(source['commands']),'coordinator_receipts':count,'reuse_bindings':len(aliases),
        'membership_revisions_including_anchor':len(native_rows),'construction_seconds':construction,
        'observed_operation_seconds':{k:stats(v) for k,v in timing.items()},'idle_cycle_seconds':idle,
        'idle_timing_gate':'PASS' if idle['p95']<=.5 and idle['maximum']<=1 else 'FAILED',
        'cold_reopen_including_source_seconds':cold,'native_audit':True,'identical_native_replays':True,
        'native_replay_sha256':replay1,'source_facts_sha256':digest(facts),
        'membership_checkpoints_sha256':digest(checkpoints),'unchanged_database_bytes_during_idle_and_reopen':True,
        'full_source_reopen_identical':True}
    (folder/'result.json').write_text(json.dumps(summary,indent=2)+'\n')
    return summary

def run(output,samples=30):
    folder=Path(output);folder.mkdir(parents=True,exist_ok=False)
    report={'result':'IN_PROGRESS','source':'historical_counts_with_synthetic_receipts','network':'denied',
        'production_access':False,'cases':{},'scope':'Native logical workload and bounded host timing. No full-day source capture, mixed-source, Windows performance or provider qualification.'}
    for name,rows in datasets().items():
        pair={}
        for reuse in (False,True):
            mode='reuse' if reuse else 'per_event'
            print('Building',name,mode,'logical workload; no market/provider activity.',flush=True)
            try:
                pair[mode]=build(folder/(name+'-'+mode),rows,reuse,samples=samples)
            except Exception as exc:
                pair[mode]={'result':'FAILED','error_type':type(exc).__name__,'error':str(exc)}
                report['cases'][name]=pair;report['result']='FAILED'
                (folder/'report.json').write_text(json.dumps(report,indent=2)+'\n')
                raise
            print(name,mode,'receipts',pair[mode]['coordinator_receipts'],'idle p95',round(pair[mode]['idle_cycle_seconds']['p95'],4),flush=True)
        for key in ['source_facts_sha256','membership_checkpoints_sha256']:
            assert pair['per_event'][key]==pair['reuse'][key]
        pair['all_source_facts_and_membership_checkpoints_identical']=True
        report['cases'][name]=pair
        (folder/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    report['correctness']='PASS'
    report['reference_idle_timing_gates']='PASS' if all(c['per_event']['idle_timing_gate']=='PASS' for c in report['cases'].values()) else 'FAILED'
    report['candidate_idle_timing_gates']='PASS' if all(c['reuse']['idle_timing_gate']=='PASS' for c in report['cases'].values()) else 'FAILED'
    report['result']='PASS' if report['candidate_idle_timing_gates']=='PASS' else 'FAILED'
    (folder/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print('Saved workload report:',folder/'report.json',flush=True)
    return report

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output-root',type=Path,required=True)
    parser.add_argument('--samples',type=int,default=30);args=parser.parse_args()
    socket.socket.connect=socket.socket.connect_ex=socket.create_connection=socket.getaddrinfo=denied
    run(args.output_root,args.samples)
