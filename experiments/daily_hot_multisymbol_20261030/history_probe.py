"""Seeded larger-roster native history, then actual elapsed cold/tail work.

Seeded rows are explicitly synthetic, not elapsed provider acquisitions.
"""
from contextlib import closing
from datetime import datetime,timedelta,timezone
import hashlib,json,sqlite3,time
from pathlib import Path
from unittest.mock import patch


def run(root, *, slots=240, hot_count=40, periods=False, background=False):
    from test_daily_multisymbol import MultiFixture,SYMBOLS,_quote_shape,replay_identity,Response
    from mb_watchlist_coordinator.daily_collector import DailyCollectorSettings,DailyHotCollector
    from mb_watchlist_coordinator.sampling_requests import digest,canonical,plain,utc_text
    from mb_market_data.sampling_acquisition import next_slot,encode_result
    from mb_market_data.quote_observation_store import OBSERVATION_COLUMNS,_fingerprint,_utc_text
    from mb_market_data.watchlist_polling import PollRequest
    from mb_market_data.schwab_quotes import QuoteBatchResult,QuoteResult,QuoteStatus
    from mb_market_data.quote_journal_audit import audit_quote_journal
    from mb_watchlist_coordinator.daily_session import _preview_journal
    from mb_watchlist_coordinator.daily_epoch_collector import make_daily_collector
    import socket
    def denied(*args,**kwargs):raise OSError('Network denied in synthetic history proof')
    socket.socket.connect=socket.socket.connect_ex=socket.create_connection=socket.getaddrinfo=denied
    if type(slots)is not int or slots%24 or not 24<=slots<=9312 or not 1<=hot_count<=40:
        raise ValueError('Explicit bounded synthetic history dimensions required')
    root=Path(root).resolve()
    if root.exists() or not root.name.startswith('multi_history_'):raise ValueError('Fresh synthetic proof root required')
    f=MultiFixture(background=True,root=root,at_open=True);c=f.case;s=f.session
    collector=None
    try:
        rows=[c.row(symbol) for symbol in SYMBOLS[:hot_count]]
        s.recovery.record(s.recovery.settings.queries[0],c.snapshot('HISTORICAL',rows,'burst-history'))
        s.gate.reconcile()
        for _ in range(hot_count):f.pump();f.advance()
        start=c.now.replace(second=0,microsecond=0)+timedelta(minutes=1)
        stop=start+timedelta(minutes=slots//24)
        settings=DailyCollectorSettings(str(c.journal),plain(s.service.identity),plain(s.binding),
            plain(s.claim),start.isoformat(),stop.isoformat(),slots,40)
        def quote(symbol,at,n):
            q=_quote_shape()(at,n);q['symbol']=symbol;return q
        class Client:
            def quotes(self,symbols,*,fields):
                return Response(symbols[0],body={x:quote(x,clock(),n)for n,x in enumerate(symbols)})
            def close(self):pass
        tick_began=None;logical=[c.now]
        def clock():
            return logical[0]+(timedelta(seconds=time.perf_counter()-tick_began)if tick_began is not None else timedelta())
        def make():
            value=(make_daily_collector if periods else DailyHotCollector)(settings,publication_session=s,client_factory=Client,
                clock=clock,activation_approved=True)
            value.client=Client();return value
        s.clock=clock;collector=make();collector.prepare(create=True)
        revisions=c.store.membership_revisions_in_effective_order();revision=revisions[-1]
        members=revision.hot_symbols;slot=collector.next
        sequence=0;previous=digest(collector.poller.identity);began=time.perf_counter()
        with closing(sqlite3.connect(c.journal))as j:
            db=sqlite3.connect(collector.poller.path);db.execute('BEGIN');j.execute('BEGIN')
            def event(kind,at,**payload):
                nonlocal sequence,previous
                sequence+=1;body=dict(payload,kind=kind,recorded_at_utc=utc_text(at))
                sha=digest({'sequence':sequence,'payload':body,'previous_sha256':previous})
                db.execute('INSERT INTO acquisition_event VALUES(?,?,?,?)',(sequence,canonical(body),previous,sha));previous=sha
            marks=','.join('?'for _ in range(9+len(OBSERVATION_COLUMNS)))
            names=','.join(OBSERVATION_COLUMNS)
            def record(request,results,run):
                rows=[c.store._observation_values(request.batch_id,n,r)for n,r in enumerate(results.results)]
                completed=results.results[0].response_received_at_utc
                header=(request.batch_id,run,request.slot.watchlist_kind.value,request.watchlist_revision,
                    str(c.journal.stem),request.slot_id,_utc_text(request.slot.scheduled_at,'fixture'),
                    _utc_text(request.dispatched_at,'fixture'),_utc_text(completed,'fixture'),
                    results.request_count,400,len(rows),'[]')
                fingerprint=_fingerprint({'header':header,'rows':rows})
                j.execute('INSERT INTO quote_acquisition VALUES('+','.join('?'for _ in range(14))+')',(*header,fingerprint))
                j.executemany('INSERT INTO quote_observation(acquisition_id,symbol,ordinal,status,detail,schwab_batch_number,'
                    'request_started_at_utc,response_received_at_utc,normalized_schema_version,'+names+')VALUES('+marks+')',rows)
                return completed,fingerprint
            if background:
                from mb_market_data.sampling_acquisition import ExplicitPollSlot
                from mb_market_data.sampling_membership import SamplingChannel
                for channel,seconds in ((SamplingChannel.UNI,(0,30)),(SamplingChannel.FOCUS,(10,20,40,50))):
                    minute=start.replace(hour=9,minute=30,second=0,microsecond=0)
                    while minute<stop:
                        for second in seconds:
                            at=minute.replace(second=second)
                            if at>=stop:continue
                            r=max((r for r in revisions if r.effective_at<=at),key=lambda r:(r.effective_at,r.revision))
                            symbols=r.symbols_for(channel)
                            request=PollRequest(ExplicitPollSlot(channel,at,seconds),r.revision,symbols,at+timedelta(milliseconds=50))
                            completed=request.dispatched_at+timedelta(milliseconds=20)
                            template=c.store._observation_values(request.batch_id,0,QuoteResult(symbols[0],QuoteStatus.QUOTE,
                                quote(symbols[0],request.dispatched_at,0),None,1,request.dispatched_at,completed))
                            rows=[(request.batch_id,x,n,*template[3:5],n//400+1,*template[6:]) for n,x in enumerate(symbols)]
                            header=(request.batch_id,'existing-'+channel.value,channel.value,r.revision,str(c.journal.stem),
                                request.slot_id,_utc_text(at,'fixture'),_utc_text(request.dispatched_at,'fixture'),
                                _utc_text(completed,'fixture'),(len(symbols)+399)//400,400,len(symbols),'[]')
                            fingerprint=_fingerprint({'header':header,'rows':rows})
                            j.execute('INSERT INTO quote_acquisition VALUES('+','.join('?'for _ in range(14))+')',(*header,fingerprint))
                            j.executemany('INSERT INTO quote_observation(acquisition_id,symbol,ordinal,status,detail,schwab_batch_number,'
                                'request_started_at_utc,response_received_at_utc,normalized_schema_version,'+names+')VALUES('+marks+')',rows)
                        minute+=timedelta(minutes=1)
                print(json.dumps({'phase':'background_seeded','seconds':time.perf_counter()-began}),flush=True)
            for n in range(slots-2):
                if slot is None:
                    if not periods:raise ValueError('Unbounded fixture exhausted its declared window')
                    j.commit();db.commit();db.close()
                    logical[0]=collector.poller.settings.window.end_at+timedelta(milliseconds=10)
                    collector.tick()
                    db=sqlite3.connect(collector.poller.path);db.execute('BEGIN');j.execute('BEGIN')
                    sequence,previous=0,digest(collector.poller.identity)
                    slot=collector.next
                at=slot.scheduled_at+timedelta(milliseconds=50);completed=at+timedelta(milliseconds=20)
                request=PollRequest(slot,revision.revision,members,at)
                result=QuoteBatchResult(tuple(QuoteResult(x,QuoteStatus.QUOTE,quote(x,at,n*40+k),None,1,at,completed)
                    for k,x in enumerate(members)),1,400,())
                completed,fingerprint=record(request,result,collector.poller.run.run_id)
                event('dispatch',at,slot_id=slot.slot_id,scheduled_at_utc=utc_text(slot.scheduled_at),
                    dispatched_at_utc=utc_text(at),revision=revision.revision,
                    membership_effective_at_utc=utc_text(revision.effective_at),hierarchy_sha256=revision.content_sha256,
                    symbols=list(members),run_id=collector.poller.run.run_id)
                event('assembled',completed,slot_id=slot.slot_id,completed_at_utc=utc_text(completed),collector_seconds=.02,result=encode_result(result))
                event('acknowledged',completed,slot_id=slot.slot_id,
                    journal_receipt={'kind':'acquisition','id':request.batch_id,'content_sha256':fingerprint},journal_seconds=0.,recovered=False)
                logical[0]=completed;slot=next_slot(collector.poller.settings,after=slot.scheduled_at)
                if n and n%1000==0:print(json.dumps({'phase':'seed','slots':n,'seconds':time.perf_counter()-began}),flush=True)
            j.commit();db.commit();db.close()
        print(json.dumps({'phase':'seeded','slots':slots-2,'hot_rows':(slots-2)*hot_count,'seconds':time.perf_counter()-began}),flush=True)
        collector.close();_preview_journal.cache_clear()
        collector=make();began=time.perf_counter();collector.prepare();cold=time.perf_counter()-began
        print(json.dumps({'phase':'cold_prepare','seconds':cold,'budget_seconds':3}),flush=True)
        tail=[]
        for _ in range(2):
            logical[0]=collector.next.scheduled_at+timedelta(milliseconds=50);tick_began=time.perf_counter()
            class Clock(datetime):
                @classmethod
                def now(cls,tz=None):return clock().astimezone(tz or timezone.utc)
            with patch('mb_market_data.schwab_quotes.datetime',Clock):result=collector.tick()
            elapsed=time.perf_counter()-tick_began;logical[0]=clock();tick_began=None
            tail.append({'seconds':elapsed,**result});print(json.dumps({'phase':'tail','measurement':tail[-1]}),flush=True)
            if result['status']!='acquired':break
        collector.close()
        audit_began=time.perf_counter()
        audit=audit_quote_journal(c.journal,audited_at=logical[0])
        from mb_watchlist_coordinator.daily_epoch_integrity import verify_journal_content,replay_sequence_digest
        integrity=verify_journal_content(c.journal) if periods else None
        first,second=replay_sequence_digest(c.journal),replay_sequence_digest(c.journal)
        with closing(sqlite3.connect(c.journal))as j:
            counts={name:j.execute('SELECT count(*) FROM '+name).fetchone()[0]for name in
                ('poll_run','sampling_membership_revision','quote_acquisition','quote_observation','poll_slot_skip')}
        verification_seconds=time.perf_counter()-audit_began
        print(json.dumps({'phase':'final_verification','seconds':verification_seconds,'native_audit_passed':audit.passed,
            'integrity':integrity,'two_sequence_digests_equal':first==second}),flush=True)
        report={'contract':'multi-symbol-seeded-history-development-v1','result':'PASS'if cold<3 and len(tail)==2 and
            all(t['status']=='acquired'and t['seconds']<2 for t in tail) and audit.passed and first==second
            and (integrity is None or integrity['passed']) and verification_seconds<60 else'FAILED',
            'hot_symbols':hot_count,'seeded_slots':slots-2,'cold_prepare_seconds':cold,'tail':tail,
            'background_present':background,'native_audit_passed':audit.passed,
            'hot_content_integrity':integrity,'first_replay':first,'second_replay':second,
            'two_fresh_sequence_digests_equal':first==second,'final_verification_seconds':verification_seconds,
            'table_counts':counts,'synthetic_only':True,'provider_capacity_qualified':False,
            'full_session_executed':False,'full_size_history':slots==9312,'bounded_periods':periods}
        (root/'history-report.json').write_text(json.dumps(report,indent=2)+'\n');return report
    finally:
        if collector:collector.close()
        f.close()


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('root');p.add_argument('--slots',type=int,default=240)
    p.add_argument('--periods',action='store_true');p.add_argument('--background',action='store_true')
    a=p.parse_args();print(json.dumps(run(a.root,slots=a.slots,periods=a.periods,background=a.background),indent=2))
