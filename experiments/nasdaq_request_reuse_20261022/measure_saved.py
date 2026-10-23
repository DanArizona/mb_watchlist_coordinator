"""Fresh final-source measurement of fully validated saved logical fixtures.

Construction is intentionally not repeated. Each current source/request/service
reader validates the retained databases afresh before the bounded idle samples.
"""
import argparse
from datetime import timedelta
import hashlib
import importlib.util
import json
from pathlib import Path
import platform
import socket
import time

HERE=Path(__file__).parent
spec=importlib.util.spec_from_file_location('reuse_workload_measure',HERE/'qualify.py')
q=importlib.util.module_from_spec(spec);spec.loader.exec_module(q)

def inventory():
    return {p.relative_to(q.ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
            for root in [q.ROOT/'src',q.ROOT/'experiments/sampling_promotion_20261016/market_data/src']
            for p in sorted(root.rglob('*.py'))}

def measure(folder,rows,reuse,samples=100):
    folder=Path(folder);construction=json.loads((folder/'result.json').read_text())
    at=q.STOP-timedelta(seconds=1)
    symbols=sorted({r['symbol'] for r in rows})
    uni=tuple(symbols+[f'Z{i:04d}' for i in range(553-len(symbols))])
    baseline=q.SamplingMembership(frozenset(uni),frozenset(uni[-40:]),frozenset())
    def objects():
        requests=q.SamplingRequestStore(folder/'requests.sqlite3',session_date=q.SESSION,baseline=baseline,
            policy=q.SamplingPolicy('admin',0,0,'immediate_cap'),clock=lambda:at)
        native=q.QuoteObservationStore(folder/'membership.sqlite3',session_date=q.SESSION,schema_version=2)
        service=q.SamplingPublicationService(folder/'publication.sqlite3',request_store=requests,
            journal=q.SamplingJournal(native),settings=q.PublicationSettings('reuse-study',1,.1,q.STOP),clock=lambda:at)
        producer=q.NasdaqSamplingProducer(folder/'nasdaq.sqlite3',request_store=requests,
            settings=q.HaltProducerSettings('nasdaq-study',('LUDP','M'),'regular_close',False,reuse),clock=lambda:at)
        return requests,native,service,producer
    before=q.hashes(folder)
    r,n,s,p=objects()
    source=q.plain(p.snapshot())
    facts=[{'recorded_at_utc':a['recorded_at_utc'],'snapshot':a['snapshot']} for a in source['receipts']]
    assert q.digest(facts)==construction['source_facts_sha256']
    events,states,aliases=r.validated_reuse_history()
    assert len(events)==construction['coordinator_receipts'] and len(aliases)==construction['reuse_bindings']
    assert len(n.membership_revisions_in_effective_order())==construction['membership_revisions_including_anchor']
    timeline=q.digest([(a.effective_at.isoformat(),list(a.uni_symbols),list(a.focus_symbols),list(a.hot_symbols)) for a in n.membership_revisions_in_effective_order()])
    assert q.audit_quote_journal(n.database_path).passed
    replay=q.digest([(e.event_id,e.revision.content_sha256) for e in q.QuoteJournalReplayReader(n.database_path).events()])
    assert replay==construction['native_replay_sha256']
    saved=q.digest(q.plain(s.snapshot()));times=[]
    for _ in range(samples):
        begin=time.perf_counter();decision=s.cycle();times.append(time.perf_counter()-begin)
        assert decision['status']=='idle' and decision['processed_sequence']==len(events)
    assert q.digest(q.plain(s.snapshot()))==saved
    assert q.digest([a.payload() for a in r.states()])==q.digest([a.payload() for a in states])
    cold=[]
    for _ in range(3):
        begin=time.perf_counter();r2,n2,s2,p2=objects()
        assert q.digest(q.plain(s2.snapshot()))==saved
        assert q.plain(p2.snapshot())==source
        cold.append(time.perf_counter()-begin)
    assert q.hashes(folder)==before
    stats=q.stats(times)
    return {'coordinator_receipts':len(events),'reuse_bindings':len(aliases),
        'halts':len(rows),'symbols':len(symbols),'source_captures':len(source['receipts']),
        'source_facts_sha256':q.digest(facts),'membership_checkpoints_sha256':construction['membership_checkpoints_sha256'],
        'native_effective_membership_timeline_sha256':timeline,
        'membership_revisions_including_anchor':len(n.membership_revisions_in_effective_order()),
        'idle_cycle_seconds':stats,'idle_timing_gate':'PASS' if stats['p95']<=.5 and stats['maximum']<=1 else 'FAILED',
        'three_cold_reopens_including_full_source_seconds':cold,'cold_gate':'PASS' if max(cold)<=10 else 'FAILED',
        'native_audit':True,'native_replay_matches_construction':True,'fresh_complete_source_reopen_matches':True,
        'all_database_bytes_unchanged':True}

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--fixture-root',type=Path,required=True)
    parser.add_argument('--report',type=Path,required=True);args=parser.parse_args()
    socket.socket.connect=socket.socket.connect_ex=socket.create_connection=socket.getaddrinfo=q.denied
    initial=inventory();report={'result':'PASS','network':'denied','production_access':False,
        'source_inventory':initial,'platform':platform.platform(),'cases':{},
        'scope':'Final-source read-only idle/cold/native/source verification of saved logical fixtures. No re-construction, Windows performance, full-day source or provider claim.'}
    for name,rows in q.datasets().items():
        pair={}
        for reuse in (False,True):
            mode='reuse' if reuse else 'per_event'
            if not (args.fixture_root/(name+'-'+mode)/'result.json').is_file():
                pair[mode]={'result':'INCOMPLETE','reason':'No completed fixture result; preserve failed construction separately.'}
                report['result']='INCOMPLETE'
                continue
            pair[mode]=measure(args.fixture_root/(name+'-'+mode),rows,reuse)
            print('Final source',name,mode,'p95',round(pair[mode]['idle_cycle_seconds']['p95'],4),flush=True)
        if all('source_facts_sha256' in pair[m] for m in pair):
            for key in ['source_facts_sha256','membership_checkpoints_sha256','native_effective_membership_timeline_sha256']:
                assert pair['per_event'][key]==pair['reuse'][key]
        report['cases'][name]=pair
    assert inventory()==initial
    for mode in ('per_event','reuse'):
        report[mode+'_idle_gates']='PASS_FOR_COMPLETED_CASES' if all(c[mode].get('idle_timing_gate','PASS')=='PASS' for c in report['cases'].values()) else 'FAILED'
    if report['reuse_idle_gates']=='FAILED':report['result']='FAILED_TIMING_GATES'
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(report,indent=2)+'\n')
    print('Saved final measurement:',args.report)

if __name__=='__main__':main()
