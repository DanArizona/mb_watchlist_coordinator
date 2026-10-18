"""Bounded four-process admission proof plus a labeled logical Nasdaq trace."""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import threading
import time
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from hot_proof import append_line, collect, lines, load_context, replay, require, save_config
from test_hot_acquisition import Response, SyntheticClient
from test_admission_publication import fixture, poller, sample
from test_sampling_admission import START, halt_row, make_request
from mb_market_data.quote_journal_audit import audit_quote_journal
from mb_market_data.quote_observation_store import QuoteObservationStore
from mb_market_data.sampling_acquisition import MARKER, AcquisitionSettings, digest, text
from mb_market_data.sampling_membership import SamplingChannel, SamplingHierarchyRevision
from mb_market_data.watchlist_polling import PollWindow
from mb_watchlist_coordinator.nasdaq_sampling import HaltProducerSettings, HaltSnapshot, NasdaqSamplingProducer
from mb_watchlist_coordinator.sampling_admission import AdmissionPolicy
from mb_watchlist_coordinator.sampling_journal import SamplingJournal
from mb_watchlist_coordinator.sampling_policy import SamplingPolicy
from mb_watchlist_coordinator.sampling_projection import SamplingMembership
from mb_watchlist_coordinator.sampling_request_store import SamplingRequestStore
from mb_watchlist_coordinator.sampling_requests import plain
from mb_watchlist_coordinator.sampling_service import PublicationSettings, SamplingPublicationService

EXPERIMENT=Path(__file__).resolve().parent


def load_control(folder):
    journal,config,clock=load_context(folder)
    opening=journal.membership_revisions_in_effective_order()[0]
    baseline=SamplingMembership(frozenset(opening.uni_symbols),frozenset(opening.focus_symbols),frozenset())
    admission=AdmissionPolicy('synthetic-review-catalog-v1',frozenset({'MSFT','NVDA','AMD'}),
        frozenset({'manual','nasdaq','algorithm'}),2,'session')
    ledger=SamplingRequestStore(folder/'requests.sqlite3',session_date=journal.session_date,baseline=baseline,
        admission=admission,policy=SamplingPolicy('proof-super-user',0.2,0.5,'immediate_cap'),clock=clock)
    ledger.initialize()
    service=SamplingPublicationService(folder/'publication.sqlite3',request_store=ledger,journal=SamplingJournal(journal),
        settings=PublicationSettings('isolated-admission-coordinator',0.05,0.35,datetime.fromisoformat(config['end'])),clock=clock)
    service.initialize();return ledger,service


def wait_for(predicate,label,timeout=12):
    deadline=time.monotonic()+timeout;next_progress=time.monotonic()+2
    print('  Waiting: '+label,flush=True)
    while time.monotonic()<deadline:
        value=predicate()
        if value:return value
        if time.monotonic()>=next_progress:
            print('  Scheduled proof is active; waiting for '+label,flush=True)
            next_progress=time.monotonic()+2
        threading.Event().wait(0.025)
    raise RuntimeError('Timed out waiting for '+label)


def run_logical_nasdaq(folder):
    folder.mkdir();ledger,journal,service,clock=fixture(folder)
    p=poller(journal,clock,channel='hot')
    sample(p,clock,0)
    producer=NasdaqSamplingProducer(folder/'nasdaq.sqlite3',request_store=ledger,
        settings=HaltProducerSettings('nasdaq',('LUDP','M'),'regular_close',True),clock=lambda:clock[0])
    producer.initialize()
    producer.record_snapshot(HaltSnapshot('startup',START,'CURRENT',digest([]),(),{'synthetic':True,'clock':'logical'}))
    clock[0]=START+timedelta(seconds=2)
    row=halt_row()
    producer.record_snapshot(HaltSnapshot('arrival',clock[0],'CURRENT',digest(row),(row,),{'synthetic':True,'clock':'logical'}))
    def fail(_):raise RuntimeError('injected after request commit before producer ACK')
    try:producer.deliver_pending(after_submit=fail)
    except RuntimeError as exc:require(str(exc).startswith('injected'),str(exc))
    original=ledger.events()[0]
    retry=producer.deliver_pending()[0]
    require(retry.event==original and not retry.inserted,'Producer retry changed request receipt')
    service.cycle()
    sample(p,clock,2)
    class LogicalDatetime(datetime):
        @classmethod
        def now(cls,tz=None):return clock[0].astimezone(tz or timezone.utc)
    with patch('mb_market_data.schwab_quotes.datetime',LogicalDatetime):
        sample(p,clock,4)
    first=journal.acquisitions_in_replay_order()[0]
    require(first.channel_revision==1 and first.requested_symbol_count==1,'Nasdaq admission did not drive Hot collector')
    check=audit_quote_journal(journal.database_path,audited_at=START+timedelta(seconds=5))
    require(check.passed,'Logical Nasdaq trace audit failed: '+str(check.findings))
    a,b=replay(journal.database_path),replay(journal.database_path)
    require(a==b,'Logical Nasdaq journal replays differ')
    require('hot:MSFT' not in replay(journal.database_path,cutoff=first.completed_at_utc-timedelta(microseconds=1))['latest'],
        'Nasdaq quote was visible before receipt')
    return {'clock':'synthetic logical regular-session time; no live halt',
        'producer_receipts':len(producer.snapshot()['receipts']),'request_receipts':len(ledger.events()),
        'delivery_retry_kept_original_receipt':True,'first_hot_revision':first.channel_revision,
        'journal_replay_sha256':digest(a),'audit_passed':check.passed,
        'audit_note':'Slots :00 and :02 are empty skips; :04 acquires after the admission effective time.'}


def run_proof(folder):
    logical=run_logical_nasdaq(folder/'logical_nasdaq')
    print('[3/3] Four processes, actual wall clock, about 25-35 seconds including startup alignment.',flush=True)
    print('Synthetic quotes only. Progress below follows membership and scheduled slots.',flush=True)
    real=folder/'real';real.mkdir()
    now=datetime.now(timezone.utc)
    start=(now+timedelta(seconds=6)).replace(microsecond=0)
    start+=timedelta(seconds=(-start.second)%6)
    window=PollWindow(start,start+timedelta(seconds=20))
    journal=QuoteObservationStore(real/'quotes.sqlite3',session_date=window.session_date,schema_version=2);journal.initialize()
    journal.record_membership_revision(SamplingHierarchyRevision(session_date=journal.session_date,revision=0,effective_at=start,
        uni_symbols=('AAPL','SPY'),focus_symbols=('SPY',),hot_symbols=(),source='synthetic_admission_opening',
        metadata={MARKER:True,'experimental':True,'logical_clock':False,'quote_source':'synthetic'}))
    initial=journal.membership_revisions_in_effective_order()[0]
    settings=AcquisitionSettings(SamplingChannel.HOT,tuple(range(0,60,2)),window,2,'all','synthetic_offline',0.8,0.05)
    save_config(real,journal,settings,control=True)
    ledger,service=load_control(real)
    children={mode:subprocess.Popen([sys.executable,'-I','-B',str(EXPERIMENT/'admission_worker.py'),str(real),mode],
        stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True) for mode in ('coordinator','uni','focus','hot')}
    completed=False;trace=[];elapsed_start=time.monotonic()
    def acq(channel,revision=0):
        return next((a for a in journal.acquisitions_in_replay_order() if a.channel==channel and a.channel_revision>=revision),None)
    def latest():return journal.membership_revisions_in_effective_order()[-1]
    def request(owner,target,rid):
        intent=make_request(datetime.now(timezone.utc),owner=owner,rid=rid,target=target)
        # Use ET journal identity even when actual UTC and ET dates differ.
        from dataclasses import replace
        intent=replace(intent,metadata={'sampling_channel':target,'session_date':journal.session_date.isoformat(),
            'synthetic':True,'direct_request':True})
        return ledger.submit_request(intent,actor_id=owner)
    try:
        wait_for(lambda:all(lines(real/(c+'_status.jsonl')) for c in children),'four independent worker starts')
        wait_for(lambda:acq('uni'),'opening Uni acquisition before admission')
        require(acq('uni').requested_symbol_count==2,'Opening Uni was already expanded')
        request('manual','uni','manual-inclusion')
        admitted=wait_for(lambda:latest() if 'MSFT' in latest().uni_symbols else None,'Uni-only admission publication')
        require(not admitted.hot_symbols and admitted.focus_symbols==('SPY',),'Uni-only admission promoted other groups')
        first_uni=wait_for(lambda:acq('uni',admitted.revision),'next Uni acquisition containing the outside symbol')
        trace.append({'stage':'Uni-only manual inclusion','revision':admitted.revision,'slot':first_uni.slot_id,
                      'symbols':first_uni.requested_symbol_count})
        request('algorithm','focus','algorithm-focus')
        focused=wait_for(lambda:latest() if 'MSFT' in latest().focus_symbols else None,'algorithm Focus publication')
        first_focus=wait_for(lambda:acq('focus',focused.revision),'next Focus acquisition with the added symbol')
        trace.append({'stage':'algorithm Focus demand','revision':focused.revision,'slot':first_focus.slot_id})
        request('nasdaq','hot','synthetic-direct-halt')
        hot=wait_for(lambda:latest() if 'MSFT' in latest().hot_symbols else None,'synthetic halt Hot publication')
        first_hot=wait_for(lambda:acq('hot',hot.revision),'next Hot acquisition with the added symbol')
        trace.append({'stage':'synthetic direct halt-source demand','revision':hot.revision,'slot':first_hot.slot_id})
        ledger.cancel_request('cancel-manual',owner_id='manual',request_id='manual-inclusion',actor_id='manual')
        ledger.cancel_request('cancel-algorithm',owner_id='algorithm',request_id='algorithm-focus',actor_id='algorithm')
        require(ledger.states()[-1].applied.hot=={'MSFT'},'Independent halt demand was lost')
        ledger.cancel_request('cancel-halt',owner_id='nasdaq',request_id='synthetic-direct-halt',actor_id='nasdaq')
        demoted=wait_for(lambda:latest() if latest().revision>hot.revision and not latest().hot_symbols else None,
                         'ordinary demotion while retaining Uni')
        final_uni=wait_for(lambda:acq('uni',demoted.revision),'continued Uni coverage after all source withdrawals')
        trace.append({'stage':'all requests withdrawn; Uni retained','revision':demoted.revision,'slot':final_uni.slot_id})
        print('  Membership sequence complete; waiting for the configured polling window to finish.',flush=True)
        wait_for(lambda:all(c.poll() is not None for c in children.values()),'bounded workers to finish',timeout=16)
        for name,child in children.items():
            out=collect(child,real,name,timeout=2)
            require(child.returncode==0,name+' worker failed: '+out)
        completed=True
    finally:
        if not completed:
            (real/'STOP').write_text('stop\n',encoding='utf-8')
            for name,child in children.items():
                if not (real/(name+'_output.txt')).exists():collect(child,real,name,timeout=5)
    audit=audit_quote_journal(journal.database_path,audited_at=window.end_at)
    require(audit.passed,'Actual-clock admission audit failed: '+str(audit.findings))
    a,b=replay(journal.database_path),replay(journal.database_path)
    require(a==b,'Admission journal replays differ')
    require(a['membership']=={'uni':['AAPL','MSFT','SPY'],'focus':['SPY'],'hot':[]},'Final membership differs')
    require(journal.membership_revisions_in_effective_order()[0]==initial,'Opening revision changed')
    require('MSFT' not in replay(journal.database_path,cutoff=admitted.effective_at-timedelta(microseconds=1))['membership']['uni'],
        'Expanded Uni appeared before admission effective time')
    require('hot:MSFT' not in replay(journal.database_path,cutoff=first_hot.completed_at_utc-timedelta(microseconds=1))['latest'],
        'First Hot quote appeared before receipt')
    metrics={}
    for channel in ('uni','focus','hot'):
        _,_,_,p=load_context(real,channel,initialize=False)
        require(p.snapshot()['pending'] is None,'Pending evidence after '+channel+' completion')
        rows=lines(real/(channel+'_status.jsonl'))
        require(rows[-1]['status']=='window_ended',channel+' did not complete its window')
        require(all(r['pid']!=os.getpid() for r in rows),'Worker not independent')
        acquisitions=[r for r in rows if r['status']=='acquired']
        metrics[channel]={'acquisitions':len(acquisitions),'empty_skips':sum(r['status']=='empty_membership' for r in rows),
                          'synthetic_batch_calls':len(lines(real/(channel+'_client.jsonl')))}
    request_states=[s.payload() for s in ledger.states()]
    reopened,again=load_control(real)
    require(request_states==[s.payload() for s in reopened.states()],'Request admission restart changed state')
    require(plain(service.snapshot())==plain(again.snapshot()),'Publication restart changed state')
    report={'result':'PASS','clock':'actual wall clock for four-process polling; labeled logical Nasdaq sub-proof',
        'logical_nasdaq':logical,'real_independent_processes':4,'window':{'start':text(start),'end':text(window.end_at)},
        'elapsed_real_seconds':round(time.monotonic()-elapsed_start,3),'trace':trace,'metrics':metrics,
        'opening_membership':{'uni':['AAPL','SPY'],'focus':['SPY'],'hot':[]},'final_membership':a['membership'],
        'table_counts':dict(audit.table_counts),'journal_audit':'PASS','repeated_journal_replay':'identical',
        'journal_replay_sha256':digest(a),'request_replay_sha256':digest(request_states),
        'live_market_acquisitions':0,'catalog':'synthetic identity catalog, separate from opening roster',
        'review_settings':plain(ledger.identity),'limits':'No live halt/feed, API request, provider capacity, production settings or activation claim'}
    (folder/'proof_report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    summary=['Outside-Uni admission proof: PASS',
        'Opening Uni: AAPL SPY; added MSFT through source-owned requests',
        'Manual Uni-only -> algorithm Focus -> synthetic halt-source Hot: PASS',
        'Recorded synthetic Nasdaq adapter -> common admission -> Hot acquisition: PASS (logical clock)',
        'Independent source withdrawals; last withdrawal demotes higher groups and retains Uni: PASS',
        'Original opening revision preserved; no pre-admission or pre-receipt observations invented',
        'Four independent actual-clock processes; complete configured-slot coverage; journal audit: PASS',
        'Request/publication restart and two identical acquisition-aware journal replays: PASS',
        'Review catalog/capacity, grace/residence and grids are explicit demonstration settings',
        'No live feed, API/password, production change or measured provider-capacity claim']
    for channel,m in metrics.items():summary.append(f"  {channel}: acquisitions={m['acquisitions']}; empty skips={m['empty_skips']}; synthetic batch calls={m['synthetic_batch_calls']}")
    summary += ['Journal replay SHA-256: '+report['journal_replay_sha256'],
                'Request replay SHA-256: '+report['request_replay_sha256'],'']
    (folder/'proof_report.txt').write_text('\n'.join(summary),encoding='utf-8')
    return report
