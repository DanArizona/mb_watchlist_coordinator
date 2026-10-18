"""Real local processes with synthetic quotes; no network or brokerage access."""

from __future__ import annotations

import json
import math
import os
import sqlite3
import statistics
import subprocess
import sys
import threading
import time
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

from mb_market_data.quote_event_state import QuoteEventStateProjector
from mb_market_data.quote_journal_audit import audit_quote_journal
from mb_market_data.quote_journal_replay import MembershipRevisionEvent, QuoteJournalReplayReader
from mb_market_data.quote_observation_store import QuoteObservationStore
from mb_market_data.sampling_acquisition import (MARKER, AcquisitionSettings, IsolatedSamplingPoller, canonical, digest, stamp, text)
from mb_market_data.sampling_membership import SamplingChannel, SamplingHierarchyRevision
from mb_market_data.watchlist_polling import PollWindow
from mb_watchlist_coordinator.models import IntentType, ProducerIntent
from mb_watchlist_coordinator.sampling_journal import SamplingJournal
from mb_watchlist_coordinator.sampling_policy import SamplingPolicy
from mb_watchlist_coordinator.sampling_projection import SamplingMembership
from mb_watchlist_coordinator.sampling_request_store import SamplingRequestStore
from mb_watchlist_coordinator.sampling_service import PublicationSettings, SamplingPublicationService
from test_hot_acquisition import Response, SyntheticClient, fixture

EXPERIMENT=Path(__file__).resolve().parent


def require(value, message):
    if not value:raise RuntimeError(message)


def save_config(folder, store, settings, *, logical_now=None, control=False):
    config={"start":text(settings.window.start_at),"end":text(settings.window.end_at),
            "cadences":{"hot":list(settings.seconds),"focus":list(range(0,60,4)),"uni":list(range(0,60,6))},
            "batch_size":settings.batch_size,"max_lateness":settings.max_dispatch_lateness_seconds,
            "logical_now":text(logical_now) if logical_now else None,"control":control,
            "synthetic_delay_seconds":{"hot":0.15,"focus":0.01,"uni":0.01}}
    (folder/'worker_config.json').write_text(json.dumps(config,indent=2)+'\n',encoding='utf-8')


def load_context(folder, channel=None, *, initialize=True):
    c=json.loads((folder/'worker_config.json').read_text(encoding='utf-8'))
    window=PollWindow(stamp(c['start']),stamp(c['end']))
    clock=(lambda:stamp(c['logical_now'])) if c['logical_now'] else (lambda:datetime.now(timezone.utc))
    store=QuoteObservationStore(folder/'quotes.sqlite3',session_date=window.session_date,schema_version=2)
    if channel is None:return store,c,clock
    settings=AcquisitionSettings(SamplingChannel(channel),tuple(c['cadences'][channel]),window,c['batch_size'],
        'all','synthetic_offline',c['max_lateness'],0.05)
    client=SyntheticClient()
    def reply(symbols,fields):
        if not c['logical_now']:threading.Event().wait(c['synthetic_delay_seconds'][channel])
        payload={s:{'assetMainType':'EQUITY','realtime':False,'quote':{'lastPrice':100.0+len(client.calls),
            'totalVolume':len(client.calls),'securityStatus':'Synthetic offline quote'}} for s in symbols}
        append_line(folder/(channel+'_client.jsonl'),{'symbols':list(symbols),'fields':fields,'synthetic':True,'returned_at_utc':text(clock())})
        return Response(payload)
    client.callback=reply
    p=IsolatedSamplingPoller(store,settings=settings,client=client,clock=clock)
    if initialize:p.initialize()
    return store,c,clock,p


def load_control(folder):
    store,c,clock=load_context(folder)
    r=store.membership_revisions_in_effective_order()[0]
    baseline=SamplingMembership(frozenset(r.uni_symbols),frozenset(r.focus_symbols),frozenset(r.hot_symbols))
    policy=SamplingPolicy('proof-super-user',0.2,0.5,'immediate_cap')
    ledger=SamplingRequestStore(folder/'requests.sqlite3',session_date=store.session_date,baseline=baseline,policy=policy,clock=clock)
    ledger.initialize()
    settings=PublicationSettings('isolated-hot-coordinator',0.05,0.35,stamp(c['end']))
    service=SamplingPublicationService(folder/'publication.sqlite3',request_store=ledger,journal=SamplingJournal(store),settings=settings,clock=clock)
    service.initialize()
    return ledger,service


def append_line(path,value):
    with path.open('a',encoding='utf-8') as f:f.write(json.dumps(value)+'\n')


def lines(path):
    if not path.is_file():return []
    return [json.loads(s) for s in path.read_text(encoding='utf-8').split('\n')[:-1] if s]


def start_child(folder,mode,stage='run'):
    return subprocess.Popen([sys.executable,'-I','-B',str(EXPERIMENT/'hot_worker.py'),str(folder),mode,stage],
                            stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)


def collect(child,folder,label,timeout=8):
    try:out,_=child.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        child.kill();out,_=child.communicate()
        (folder/(label+'_output.txt')).write_text(out,encoding='utf-8')
        raise RuntimeError('Bounded isolated child timed out: '+label)
    (folder/(label+'_output.txt')).write_text(out,encoding='utf-8')
    return out


def wait_for(predicate,label,timeout=9):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        r=predicate()
        if r:return r
        threading.Event().wait(0.025)
    raise RuntimeError('Timed out waiting for '+label)


def replay(path,*,cutoff=None):
    p=QuoteEventStateProjector();events=[]
    for e in QuoteJournalReplayReader(path).events():
        if cutoff is not None and e.available_at_utc>cutoff:continue
        p.apply(e)
        value={'id':e.event_id,'kind':e.kind.value,'available_at_utc':text(e.available_at_utc)}
        if isinstance(e,MembershipRevisionEvent):
            value.update(revision=e.revision.revision,content_sha256=e.revision.content_sha256,
                         membership={c:list(e.revision.symbols_for(c)) for c in ('uni','focus','hot')})
        else:
            a=e.acquisition
            value.update(channel=a.channel,revision=a.channel_revision,slot_id=a.slot_id,content_sha256=a.content_sha256,
                scheduled_at_utc=text(a.scheduled_at_utc),dispatched_at_utc=text(a.dispatched_at_utc),completed_at_utc=text(a.completed_at_utc),
                observations=[{'symbol':o.symbol,'status':o.status,'request_started_at_utc':text(o.request_started_at_utc),
                    'response_received_at_utc':text(o.response_received_at_utc) if o.response_received_at_utc else None,'values':dict(o.values)} for o in e.observations])
        events.append(value)
    state=p.snapshot()
    return {'events':events,'membership':{c:list(state.current_members(c)) for c in ('uni','focus','hot')},
            'acquisitions':state.acquisition_count,'observations':state.observation_count,
            'latest':{c+':'+s:{'status':o.observation.status,'available_at_utc':text(o.available_at_utc)} for (c,s),o in state.latest_observations.items()}}


def timing(values):
    values=sorted(values)
    if not values:return {'n':0}
    return {'n':len(values),'mean_ms':round(statistics.mean(values)*1000,3),
            'p95_ms':round(values[max(0,math.ceil(len(values)*0.95)-1)]*1000,3),'max_ms':round(values[-1]*1000,3)}


def run_proof(folder):
    real=folder/'real';real.mkdir()
    now=datetime.now(timezone.utc)
    start=(now+timedelta(seconds=5)).replace(microsecond=0)
    if start.second%2:start+=timedelta(seconds=1)
    window=PollWindow(start,start+timedelta(seconds=14))
    store=QuoteObservationStore(real/'quotes.sqlite3',session_date=window.session_date,schema_version=2);store.initialize()
    store.record_membership_revision(SamplingHierarchyRevision(session_date=store.session_date,revision=0,effective_at=start,
        uni_symbols=('AAPL','MSFT','SPY'),focus_symbols=('SPY',),hot_symbols=(),source='isolated_hot_fixture',
        metadata={MARKER:True,'experimental':True,'quote_source':'synthetic','logical_clock':False}))
    settings=AcquisitionSettings(SamplingChannel.HOT,tuple(range(0,60,2)),window,2,'all','synthetic_offline',0.8,0.05)
    save_config(real,store,settings,control=True)
    ledger,service=load_control(real)
    children={c:start_child(real,c) for c in ('coordinator','uni','focus','hot')}
    trace=[];started=time.monotonic();completed=False
    def hot_acquisition(min_revision=1):
        return next((a for a in store.acquisitions_in_replay_order() if a.channel=='hot' and a.channel_revision>=min_revision),None)
    try:
        wait_for(lambda:all(lines(real/(c+'_status.jsonl')) for c in children),'four independent worker starts')
        intent=ProducerIntent('m1','manual',IntentType.ENSURE_PRESENT,frozenset({'MSFT'}),datetime.now(timezone.utc),
            source_event_id='synthetic-manual',metadata={'session_date':store.session_date.isoformat(),'sampling_channel':'hot'})
        ledger.submit_request(intent,actor_id='manual')
        first=wait_for(lambda:hot_acquisition(),'Hot observation after Coordinator promotion')
        trace.append({'label':'manual promotion observed by Hot','revision':first.channel_revision,'slot_id':first.slot_id})
        ledger.submit_request(ProducerIntent('h1','synthetic-halt',IntentType.ENSURE_PRESENT,frozenset({'MSFT'}),datetime.now(timezone.utc),
            source_event_id='synthetic-halt-001',metadata={'session_date':store.session_date.isoformat(),'sampling_channel':'hot'}),actor_id='synthetic-halt')
        ledger.cancel_request('withdraw-manual',owner_id='manual',request_id='m1',actor_id='manual')
        require(ledger.states()[-1].applied.hot=={'MSFT'},'Manual cancellation lost independent halt demand')
        ledger.restrict_symbol('cap',symbol='MSFT',max_group='uni',actor_id='proof-super-user',expires_at=datetime.now(timezone.utc)+timedelta(seconds=3))
        def capped_skip():
            with closing(sqlite3.connect(store.database_path)) as c:
                return c.execute("SELECT slot_id,channel_revision FROM poll_slot_skip WHERE channel='hot' AND channel_revision>? ORDER BY scheduled_at_utc LIMIT 1",(first.channel_revision,)).fetchone()
        capped=wait_for(capped_skip,'empty Hot slot under cap')
        trace.append({'label':'cap produces empty Hot skip without quote call','slot_id':capped[0],'revision':capped[1]})
        returned=wait_for(lambda:hot_acquisition(capped[1]+1),'Hot observation after automatic cap expiry')
        trace.append({'label':'cap expiry reentry observed by Hot','slot_id':returned.slot_id,'revision':returned.channel_revision})
        ledger.cancel_request('withdraw-halt',owner_id='synthetic-halt',request_id='h1',actor_id='synthetic-halt')
        wait_for(lambda:store.membership_revisions_in_effective_order()[-1].revision>returned.channel_revision and not store.membership_revisions_in_effective_order()[-1].hot_symbols,'delayed ordinary demotion publication')
        for name,child in children.items():
            out=collect(child,real,name,timeout=20)
            require(child.returncode==0,f'{name} worker failed: {out}')
            require(lines(real/(name+'_status.jsonl'))[-1]['status'] in ('window_ended','closed'),name+' did not finish its bounded window')
        completed=True
    finally:
        if not completed:
            (real/'STOP').write_text('stop\n',encoding='utf-8')
            for name,child in children.items():
                if child.poll() is None:collect(child,real,name,timeout=5)
    audit=audit_quote_journal(store.database_path,audited_at=window.end_at)
    require(audit.passed,'Real-process journal audit failed: '+str(audit.findings))
    a,b=replay(store.database_path),replay(store.database_path)
    require(a==b,'Acquisition-aware journal replays differ')
    require(a['membership']=={'uni':['AAPL','MSFT','SPY'],'focus':['SPY'],'hot':[]},'Unexpected final hierarchy')
    revisions=store.membership_revisions_in_effective_order()
    require([list(r.hot_symbols) for r in revisions]==[[],['MSFT'],[],['MSFT'],[]],'Unexpected five-revision Hot trace')
    first_hot=next(a for a in store.acquisitions_in_replay_order() if a.channel=='hot')
    before=replay(store.database_path,cutoff=first_hot.completed_at_utc-timedelta(microseconds=1))
    require('hot:MSFT' not in before['latest'],'Hot quote appeared before acquisition completion')
    after=replay(store.database_path,cutoff=first_hot.completed_at_utc)
    require(after['latest']['hot:MSFT']['available_at_utc']==text(first_hot.completed_at_utc),'Hot quote availability differs from its receipt')
    metrics={};outcomes={}
    for name in ('uni','focus','hot'):
        _,_,_,p=load_context(real,name,initialize=False)
        s=p.snapshot();require(s['pending'] is None,name+' has pending evidence after completion')
        outcomes[name]=s
        rows=[r for r in lines(real/(name+'_status.jsonl')) if r['status'] in ('acquired','empty_membership')]
        require(rows,name+' produced no outcomes')
        metrics[name]={'acquisitions':sum(r['status']=='acquired' for r in rows),'empty_skips':sum(r['status']=='empty_membership' for r in rows),
            'synthetic_client_calls':len(lines(real/(name+'_client.jsonl'))),
            'collector':timing([r['collector_seconds'] for r in rows if r['status']=='acquired']),
            'journal':timing([r['journal_seconds'] for r in rows]),'cycle':timing([r['cycle_seconds'] for r in rows if 'cycle_seconds'in r]),
            'active_cycle':timing([r['cycle_seconds'] for r in rows if r['status']=='acquired' and 'cycle_seconds'in r]),
            'empty_cycle':timing([r['cycle_seconds'] for r in rows if r['status']=='empty_membership' and 'cycle_seconds'in r]),
            'dispatch_lateness':timing([r['dispatch_lateness_seconds'] for r in rows if 'dispatch_lateness_seconds'in r])}
        require(all(r['pid']!=os.getpid() for r in lines(real/(name+'_status.jsonl'))),'Acquisition worker was not a separate process')
    recovery=[]
    for stage in ('after_dispatch','after_response','after_assembled','after_journal_commit'):
        case=folder/stage;case.mkdir()
        j,p,client,clock=fixture(case)
        save_config(case,j,p.settings,logical_now=clock[0])
        child=start_child(case,'hot',stage);out=collect(child,case,'fault')
        require(child.returncode==73,'Fault stage not reached: '+stage+' '+out)
        calls_before=lines(case/'hot_client.jsonl');old=j.acquisitions_in_replay_order()
        clock[0]+=timedelta(seconds=2)
        reopened=IsolatedSamplingPoller(j,settings=p.settings,client=client,clock=lambda:clock[0]);reopened.initialize();result=reopened.recover()
        require(client.calls==[] and lines(case/'hot_client.jsonl')==calls_before,'Recovery repeated a quote request')
        check=audit_quote_journal(j.database_path,audited_at=p.settings.window.start_at+timedelta(seconds=1))
        unknown=stage in ('after_dispatch','after_response')
        if unknown:
            require(not check.passed and result['status']=='unresolved_dispatch' and not j.acquisitions_in_replay_order(),'Unknown dispatch was hidden or reacquired')
        else:
            require(check.passed and len(j.acquisitions_in_replay_order())==1,'Durable response recovery audit failed')
            if stage=='after_journal_commit':require(old==j.acquisitions_in_replay_order(),'Recovery changed the committed acquisition')
        require(replay(j.database_path)==replay(j.database_path),'Recovery journal replays differ')
        recovery.append({'stage':stage,'exit_code':child.returncode,'synthetic_client_calls':len(calls_before),
            'clock':'injected logical fault drill; store publication clock remains actual',
            'journal_audit':'expected gap detected' if unknown else 'PASS','result':result,
            'outcome_sha256':reopened.snapshot()['head_sha256']})
    report={'result':'PASS','real_independent_processes':4,'elapsed_seconds':round(time.monotonic()-started,3),
        'source':'synthetic offline quote responses through pinned fetch_quotes_batched; no network',
        'window':{'start':text(window.start_at),'end':text(window.end_at)},'review_cadences':json.loads((real/'worker_config.json').read_text())['cadences'],
        'review_settings':'Synthetic three-symbol Uni, baseline one-symbol Focus, one-symbol Hot; proof values are not production defaults',
        'metrics':metrics,'trace':trace,'journal_audit':'PASS','table_counts':dict(audit.table_counts),
        'journal_replay_sha256':digest(a),'outcomes':outcomes,'recovery':recovery,
        'receipt_causal_replay':'PASS; no Hot quote before its completion time',
        'limits':'No live Nasdaq/Schwab data, market capacity or production Hot activation claim; staged market-data extension needs integration after review'}
    (folder/'proof_report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    summary=['Isolated Hot acquisition proof: PASS','Four independent processes: Coordinator + Uni + Focus + Hot',
        'Synthetic responses use the existing batch collector and schema-v2 journal; no network/password',
        'Coordinator promotion, privileged cap, expiry reentry and ordinary demotion drive Hot acquisition/skips: PASS',
        'Uni/Focus continuity, complete configured-slot coverage and acquisition-aware repeated replay: PASS',
        'Receipt timing: no Hot quote visible before its completed response',
        'Abrupt exit after saved response / journal commit: recovered without another quote request',
        'Abrupt exit before saved response: explicit gap detected; no catch-up request',
        'Review cadence: Hot every 2s; Focus every 4s; Uni every 6s; existing production cadences unchanged',
        'Timing below measures local work with injected synthetic latency, not Schwab or market capacity:']
    for name,m in metrics.items():
        summary.append(f"  {name}: acquisitions={m['acquisitions']}; empty skips={m['empty_skips']}; active cycle mean/p95/max={m['active_cycle'].get('mean_ms',0)}/{m['active_cycle'].get('p95_ms',0)}/{m['active_cycle'].get('max_ms',0)} ms")
    summary += [f"Hierarchy revisions: {len(revisions)}; synthetic acquisitions: {audit.table_counts['quote_acquisition']}; live market acquisitions: 0",
        'Journal replay SHA-256: '+report['journal_replay_sha256'],'Finished bounded processes; production remains unchanged.','']
    (folder/'proof_report.txt').write_text('\n'.join(summary),encoding='utf-8')
    return report
