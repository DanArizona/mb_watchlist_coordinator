"""Synthetic end-of-day Hot history probe; seeded rows are NOT provider calls.

This development probe deliberately reports no full-session/provider capacity
qualification. It builds a full-size Hot prefix, then times an actual cold
native collector preparation and the last two native acquisitions.
"""
from contextlib import closing
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import socket
import sqlite3
import time
from unittest.mock import patch


def quote_payload(at,n=0):
    milliseconds=int(at.timestamp()*1000)
    return {'symbol':'NVDA','assetMainType':'EQUITY','assetSubType':'COE','realtime':True,
        'extended':{'bidPrice':11.99,'askPrice':12.01,'mark':12.,'lastPrice':12.,'lastSize':100,
            'totalVolume':1000000,'quoteTime':milliseconds,'tradeTime':milliseconds},
        'quote':{'bidPrice':11.99,'askPrice':12.01,'mark':12.,'lastPrice':12+n/100000,
            'bidSize':100,'askSize':200,'lastSize':100,'totalVolume':1000000+n,'securityStatus':'Normal',
            'openPrice':11.8,'highPrice':12.3,'lowPrice':11.7,'closePrice':11.9,'netChange':.1,
            'netPercentChange':.84,'quoteTime':milliseconds,'tradeTime':milliseconds,'bidTime':milliseconds,
            'askTime':milliseconds,'postMarketChange':0.,'postMarketPercentChange':0.},
        'regular':{'regularMarketLastPrice':12.,'regularMarketLastSize':100,'regularMarketTradeTime':milliseconds,
            'regularMarketNetChange':.1,'regularMarketPercentChange':.84},
        'fundamental':{'sharesOutstanding':10000000,'avg10DaysVolume':1200000,'avg1YearVolume':1100000},
        'reference':{'exchange':'NASD','exchangeName':'Nasdaq','description':'Synthetic capacity security'}}


def run(root, *, slots=9360, background=False, full_quote=False):
    root = Path(root).resolve()
    if not root.name.startswith('capacity_') or root.exists() or not root.parent.is_dir():
        raise ValueError('Fresh test-owned capacity directory required')
    if type(slots) is not int or not 3 <= slots <= 9360:
        raise ValueError('Explicit bounded synthetic slot count required')
    def denied(*args, **kwargs): raise OSError('Network denied in seeded capacity probe')
    socket.socket.connect = socket.socket.connect_ex = socket.create_connection = socket.getaddrinfo = denied
    from test_daily_session import DailySessionTests
    from mb_market_data.quote_observation_store import OBSERVATION_COLUMNS, _fingerprint
    from mb_market_data.sampling_acquisition import encode_result, next_slot
    from mb_market_data.schwab_quotes import QuoteResult, QuoteBatchResult, QuoteStatus
    from mb_market_data.watchlist_polling import PollRequest
    from mb_watchlist_coordinator.daily_collector import DailyHotCollector, DailyCollectorSettings
    from mb_watchlist_coordinator.daily_session import DailySession
    from mb_watchlist_coordinator.sampling_requests import plain, canonical, digest, utc_text
    case = DailySessionTests('test_preview_reads_published_anchor_and_creates_no_application_state_or_client')
    if background:
        case.universe_symbols_override=['IBM','MSFT']+[f'C{n:05d}' for n in range(598)]
        case.focus_symbols_override=case.universe_symbols_override[:40]
        case.full_window_run_configs=True
        def large_catalog(at):
            from test_integrated_catalog import sources,receipts
            from mb_watchlist_coordinator.integrated_catalog import DirectoryCatalog
            bodies=sources(at)
            header,footer=bodies['nasdaq'].rsplit(b'File Creation Time:',1)
            extra=''.join(f'C{n:05d}|Synthetic directory record {n}|Q|N|N|100|N\n' for n in range(7000)).encode()
            bodies['nasdaq']=header+extra+b'File Creation Time:'+footer
            return DirectoryCatalog(bodies,receipts(at))
        case.catalog_factory_override=large_catalog
    case.proof_directory_override = str(root); case.setUp()
    case.now = case.at.replace(hour=9, minute=30, second=1)
    case.at = case.now+timedelta(seconds=59)
    case.session = DailySession(case.settings, case.catalog, clock=lambda: case.now)
    case.session.attach(create=True, publication_approved=True); case.admit()
    settings = DailyCollectorSettings(str(case.journal), plain(case.session.service.identity),
        plain(case.session.binding), plain(case.session.claim), case.now.replace(second=0).isoformat(),
        case.now.replace(hour=16, minute=0, second=0).isoformat(), 9360, 1)
    def make(): return DailyHotCollector(settings, publication_session=case.session,
        client_factory=lambda: case.client, clock=lambda: case.now, activation_approved=True)
    collector = make(); collector.prepare(create=True)
    revision = case.store.membership_revisions_in_effective_order()[-1]
    sequence, previous = 0, digest(collector.poller.identity)
    slot = collector.next
    began = time.perf_counter()
    seed = root/'seed.json'
    seed.write_text(json.dumps({'synthetic_only':True, 'seeded_slots':slots-2,
        'seed_method':'Bulk synthetic journal/sidecar fixture, not native/provider execution',
        'background_uni_focus_size_representative':background,'full_quote_shape':full_quote})+'\n')
    try:
        with closing(sqlite3.connect(case.journal)) as j, j, closing(sqlite3.connect(collector.poller.path)) as c, c:
            def event(kind, recorded, **payload):
                nonlocal sequence, previous
                sequence += 1
                body = dict(payload, kind=kind, recorded_at_utc=utc_text(recorded))
                sha = digest({'sequence':sequence,'payload':body,'previous_sha256':previous})
                c.execute('INSERT INTO acquisition_event VALUES(?,?,?,?)', (sequence,canonical(body),previous,sha))
                previous = sha
            placeholders = ','.join('?' for _ in range(9+len(OBSERVATION_COLUMNS)))
            columns = ','.join(OBSERVATION_COLUMNS)
            if background:
                from mb_market_data.sampling_acquisition import ExplicitPollSlot
                from mb_market_data.sampling_membership import SamplingChannel
                revisions=case.store.membership_revisions_in_effective_order()
                for channel,seconds in ((SamplingChannel.UNI,(0,30)),(SamplingChannel.FOCUS,(10,20,40,50))):
                    minute=case.now.replace(second=0,microsecond=0)
                    stop=minute.replace(hour=16,minute=0)
                    while minute<stop:
                        for second in seconds:
                            at=minute.replace(second=second)
                            r=max((r for r in revisions if r.effective_at<=at),key=lambda r:(r.effective_at,r.revision))
                            members=r.symbols_for(channel)
                            request=PollRequest(ExplicitPollSlot(channel,at,seconds),r.revision,members,at+timedelta(milliseconds=50))
                            completed=request.dispatched_at+timedelta(milliseconds=20)
                            template=case.store._observation_values(request.batch_id,0,QuoteResult(members[0],QuoteStatus.QUOTE,
                                quote_payload(request.dispatched_at),None,1,request.dispatched_at,completed))
                            rows=[(request.batch_id,symbol,n,*template[3:5],n//400+1,*template[6:]) for n,symbol in enumerate(members)]
                            header=(request.batch_id,'existing-'+channel.value,channel.value,r.revision,str(case.journal.stem),
                                request.slot_id,utc_text(at),utc_text(request.dispatched_at),utc_text(completed),
                                (len(members)+399)//400,400,len(members),'[]')
                            fingerprint=_fingerprint({'header':header,'rows':rows})
                            j.execute('INSERT INTO quote_acquisition VALUES('+','.join('?' for _ in range(14))+')',(*header,fingerprint))
                            j.executemany('INSERT INTO quote_observation (acquisition_id,symbol,ordinal,status,detail,schwab_batch_number,'
                                'request_started_at_utc,response_received_at_utc,normalized_schema_version,'+columns+') VALUES ('+placeholders+')',rows)
                        minute+=timedelta(minutes=1)
            for n in range(slots-2):
                dispatched = slot.scheduled_at+timedelta(milliseconds=50)
                completed = dispatched+timedelta(milliseconds=20)
                request = PollRequest(slot, revision.revision, ('NVDA',), dispatched)
                quote = quote_payload(dispatched,n) if full_quote else {'symbol':'NVDA','assetMainType':'EQUITY','assetSubType':'COE',
                    'quote':{'lastPrice':12+n/100000,'bidPrice':11.99,'askPrice':12.01,'totalVolume':100000+n}}
                result = QuoteBatchResult((QuoteResult('NVDA',QuoteStatus.QUOTE,quote,None,1,dispatched,completed),),1,400,())
                row = case.store._observation_values(request.batch_id,0,result.results[0])
                header = (request.batch_id, collector.poller.run.run_id, 'hot', revision.revision,
                    str(case.journal.stem), slot.slot_id, utc_text(slot.scheduled_at), utc_text(dispatched),
                    utc_text(completed),1,400,1,'[]')
                fingerprint = _fingerprint({'header':header,'rows':[row]})
                j.execute('INSERT INTO quote_acquisition VALUES('+','.join('?' for _ in range(14))+')', (*header,fingerprint))
                j.execute('INSERT INTO quote_observation (acquisition_id,symbol,ordinal,status,detail,schwab_batch_number,'
                    'request_started_at_utc,response_received_at_utc,normalized_schema_version,'+columns+') VALUES ('+placeholders+')',row)
                event('dispatch',dispatched,slot_id=slot.slot_id,scheduled_at_utc=utc_text(slot.scheduled_at),
                    dispatched_at_utc=utc_text(dispatched),revision=revision.revision,
                    membership_effective_at_utc=utc_text(revision.effective_at),hierarchy_sha256=revision.content_sha256,
                    symbols=['NVDA'],run_id=collector.poller.run.run_id)
                event('assembled',completed,slot_id=slot.slot_id,completed_at_utc=utc_text(completed),
                    collector_seconds=.02,result=encode_result(result))
                event('acknowledged',completed,slot_id=slot.slot_id,
                    journal_receipt={'kind':'acquisition','id':request.batch_id,'content_sha256':fingerprint},
                    journal_seconds=0.,recovered=False)
                case.now = completed
                slot = next_slot(collector.poller.settings, after=slot.scheduled_at)
        seed_seconds = time.perf_counter()-began
        print(json.dumps({'phase':'seeded','synthetic_slots':slots-2,'seconds':seed_seconds}),flush=True)
        collector.close(); collector = make()
        began = time.perf_counter(); collector.prepare(); cold = time.perf_counter()-began
        print(json.dumps({'phase':'cold_prepare','seconds':cold,'original_progress_budget_seconds':3}),flush=True)
        class Clock(datetime):
            @classmethod
            def now(cls,tz=None): return case.now.astimezone(tz or timezone.utc)
        tail=[]
        with patch('mb_market_data.schwab_quotes.datetime',Clock):
            for n in range(2):
                case.now = collector.next.scheduled_at+timedelta(milliseconds=50)
                began = time.perf_counter(); result=collector.tick(); elapsed=time.perf_counter()-began
                assert result['status']=='acquired',result
                tail.append({'actual_native_tick_seconds':elapsed,'state_prepare_seconds':result['state_prepare_seconds'],
                    'spool_and_check_seconds':result['spool_and_check_seconds']})
                print(json.dumps({'phase':'tail','measurement':tail[-1]}),flush=True)
        report={'contract':'seeded-hot-prefix-development-probe-v1','synthetic_only':True,
            'seeded_slots':slots-2,'actual_tail_native_acquisitions':2,'provider_calls':0,
            'seed_seconds':seed_seconds,'cold_prepare_seconds':cold,'tail':tail,
            'background_uni_focus_size_representative':background,'full_quote_shape':full_quote,
            'full_session_executed':False,
            'provider_capacity_qualified':False,'full_day_capacity_qualified':False,
            'raw_processing_fits_current_gates':cold<3 and all(t['actual_native_tick_seconds']<2 and
                t['state_prepare_seconds']+t['spool_and_check_seconds']<.75 for t in tail)}
        (root/'capacity-development.json').write_text(json.dumps(report,indent=2)+'\n')
        return report
    finally:
        collector.close();case.close()
