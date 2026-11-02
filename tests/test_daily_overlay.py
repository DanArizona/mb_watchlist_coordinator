"""Small real SQLite journals and retained synthetic RSS; no running producer."""
from contextlib import closing
from dataclasses import replace
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch

from test_daily_membership_status import SyntheticMembership
from test_nasdaq_feed_recovery import rss
from mb_watchlist_coordinator.daily_overlay import DailyOverlayReader, DailyOverlayModel
from mb_watchlist_coordinator.daily_supervision import atomic_json
from mb_watchlist_coordinator.sampling_requests import canonical, digest, plain, utc_text


class OverlayScene(SyntheticMembership):
    def quote_value(self, *, symbol='NVDA', channel='hot', status=None, price=12.5, completed=None):
        from mb_market_data.quote_observation_store import PollRunProvenance
        from mb_market_data.schwab_quotes import QuoteBatchResult, QuoteResult, QuoteStatus
        from mb_market_data.watchlist_polling import PollRequest
        from mb_market_data.sampling_acquisition import ExplicitPollSlot
        from mb_market_data.sampling_membership import SamplingChannel
        r=self.store.latest_membership_revision_effective_at(self.now)
        symbols=getattr(r,channel+'_symbols')
        run='fixture-'+channel+'-'+str(self.now.timestamp())
        self.store.record_run(PollRunProvenance(run,self.now,'synthetic',
            {'watchlist_kind':channel,'poll_seconds':[self.now.second]}))
        request=PollRequest(ExplicitPollSlot(SamplingChannel(channel),self.now,(self.now.second,)),r.revision,symbols,self.now)
        batch=QuoteBatchResult(tuple(QuoteResult(s,status or QuoteStatus.QUOTE,
            {'symbol':s,'quote':{'lastPrice':price,'tradeTime':int(self.now.timestamp()*1000)}},
            'synthetic failure' if status else None,1,self.now,self.now) for s in symbols),1,400,())
        return self.store.record_acquisition(run,request,batch,completed_at=completed or self.now)

    def source(self):
        from mb_watchlist_coordinator.daily_feed import DailyFeedTransport
        from mb_watchlist_coordinator.nasdaq_recovery import RecoveryQuery
        self.feed=DailyFeedTransport(self.state_root/'daily-feed.sqlite3',session_date=self.now.date(),
            queries=(RecoveryQuery(self.now.date(),self.now.date()),),clock=lambda:self.now)
        self.feed.initialize(create=True)
        authority={'contract':'daily-nasdaq-publication-authority-v1','feed_identity':plain(self.feed.identity),
            'publication_identity':{'journal':{'path':str(self.journal),'session_date':str(self.now.date()),'schema_version':2},
                'request_path':str(self.state_root/'requests.sqlite3')}}
        claim={'contract':'daily-source-invocation-v1','daily_binding_sha256':self.binding['binding_sha256'],
            'feed_identity':plain(self.feed.identity),'authority_identity':authority}
        atomic_json(self.journal.with_suffix('.daily-feed-session.json'),claim)
        atomic_json(self.state_root/'daily-source-ready.json',{'claim':claim,'status':'INITIALIZED'})
        self.authority=authority
        with closing(sqlite3.connect(self.state_root/'daily-source.sqlite3')) as c,c:
            c.execute('CREATE TABLE recovery_supervisor_identity (id INTEGER PRIMARY KEY,payload TEXT)')
            c.execute('INSERT INTO recovery_supervisor_identity VALUES(1,?)',(canonical(authority),))
            c.execute('CREATE TABLE recovery_supervisor_event (sequence INTEGER PRIMARY KEY,payload TEXT)')
        self.source_status()

    def source_status(self, status='READY_WITH_GAPS', reasons=()):
        with closing(sqlite3.connect(self.state_root/'daily-source.sqlite3')) as c,c:
            old=c.execute('SELECT sequence,payload FROM recovery_supervisor_event ORDER BY sequence DESC LIMIT 1').fetchone()
            e={'kind':'status','status':status,'reasons':list(reasons),'at_utc':utc_text(self.now),
               'sequence':old[0]+1 if old else 1,'previous_sha256':json.loads(old[1])['event_sha256'] if old else digest(self.authority)}
            e['event_sha256']=digest(e);c.execute('INSERT INTO recovery_supervisor_event VALUES(?,?)',(e['sequence'],canonical(e)))

    def capture(self, *, resume=None, query=None, raw=None):
        from mb_watchlist_coordinator.nasdaq_feed_recovery import query_url
        extra=('') if resume is None else ('<ndaq:ResumptionDate>'+self.now.strftime('%m/%d/%Y')+
            '</ndaq:ResumptionDate><ndaq:ResumptionTradeTime>'+resume+'</ndaq:ResumptionTradeTime>')
        raw=raw or rss(self.now.date(),symbol='NVDA',halt='09:45:00',extra=extra)
        r=self.feed.reserve(query,synthetic=True)
        if r is None:raise AssertionError('Fixture attempted an unpaced feed call')
        self.feed.progress(r,{'status_code':200,'final_url':query_url(query),'headers':{},'body_complete':True},raw)
        self.feed.finish(r)


class DailyOverlayTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.scene=OverlayScene(self.temp.name)
        self.scene.add('NVDA')
        self.reader=DailyOverlayReader(self.scene.state_root,clock=lambda:self.scene.now)
        self.model=DailyOverlayModel(self.reader)

    def snapshot(self,symbol='NVDA'):
        result=self.model.refresh(symbol)
        self.assertTrue(result.fresh,result.error)
        return result.snapshot

    def test_new_symbol_is_available_to_existing_overlay_without_candle_cache(self):
        self.scene.quote_value()
        s=self.snapshot()
        self.assertEqual(s.overlay.symbol,'NVDA');self.assertEqual(s.overlay.current_band.value,'hot')
        self.assertEqual(s.membership['counts'],{'hot':1,'focus':1,'uni':1})
        self.assertIn('NVDA',s.membership['symbols'])
        self.assertIsNone(s.overlay.cache);self.assertEqual(s.overlay.candles,())
        self.assertEqual(s.overlay.quote_points[0].values['quote_last_price'],12.5)

    def test_native_figure_renders_quotes_and_membership_without_inventing_candles(self):
        from mb_market_data.observation_overlay_view import build_observation_overlay_figure
        self.scene.quote_value();s=self.snapshot()
        f=build_observation_overlay_figure(s.overlay,units='percent',off_hours=False)
        self.assertEqual(f.layout.height,800)
        self.assertTrue(any(t.name=='Hot quote' for t in f.data))
        self.assertFalse(any(t.type=='candlestick' for t in f.data))
        self.assertEqual(f.layout.yaxis.title.text,'Price')

    def test_future_membership_waits_for_its_native_effective_time(self):
        self.scene.add('AMD',effective=self.scene.now+timedelta(seconds=2))
        self.assertNotIn('AMD',self.snapshot().membership['symbols'])
        self.scene.now+=timedelta(seconds=2)
        self.assertIn('AMD',self.snapshot().membership['symbols'])

    def test_future_completed_quote_is_not_visible_early(self):
        self.scene.quote_value(completed=self.scene.now+timedelta(seconds=2))
        self.assertEqual(self.snapshot().overlay.quote_points,())
        self.scene.now+=timedelta(seconds=2)
        self.assertEqual(len(self.snapshot().overlay.quote_points),1)

    def test_demoted_symbol_keeps_selectable_history_and_current_band_changes(self):
        current=self.scene.store.latest_membership_revision_effective_at(self.scene.now)
        self.scene.now+=timedelta(seconds=2)
        self.scene.store.record_membership_revision(replace(current,revision=current.revision+1,
            effective_at=self.scene.now,published_at=None,hot_symbols=()))
        s=self.snapshot();self.assertEqual(s.overlay.current_band.value,'focus')
        self.assertIn('NVDA',s.membership['symbols']);self.assertFalse(s.membership['groups']['hot'])

    def test_preopen_view_does_not_invent_effective_membership(self):
        self.scene.now=self.scene.start-timedelta(minutes=1)
        s=self.snapshot('IBM')
        self.assertEqual(s.membership['state'],'WAITING_FOR_OPEN')
        self.assertEqual(s.overlay.current_band.value,'outside_uni')
        self.assertEqual(s.membership['groups']['hot'],[])

    def test_unpublished_symbol_selection_is_refused(self):
        r=self.model.refresh('UNPUBLISHED');self.assertFalse(r.fresh);self.assertIsNone(r.snapshot)

    def test_failed_read_keeps_only_selected_symbols_last_verified_chart(self):
        first=self.snapshot()
        (self.scene.state_root/'session.json').write_text('{}')
        failed=self.model.refresh('NVDA');self.assertFalse(failed.fresh)
        self.assertEqual(failed.snapshot,first)
        self.assertIsNone(self.model.refresh('IBM').snapshot)

    def test_read_can_recover_without_resetting_the_binding_or_baseline(self):
        first=self.snapshot();path=self.scene.state_root/'session.json';saved=path.read_bytes()
        path.write_text('{}');self.assertFalse(self.model.refresh('NVDA').fresh)
        path.write_bytes(saved);self.assertEqual(self.snapshot().membership['baseline_sha256'],first.membership['baseline_sha256'])

    def test_missing_state_is_not_created(self):
        root=self.scene.root/'missing'
        self.assertFalse(DailyOverlayModel(DailyOverlayReader(root)).refresh().fresh)
        self.assertFalse(root.exists())

    def test_binding_change_requires_an_explicitly_new_reader(self):
        self.snapshot();raw=dict(self.scene.binding);raw.pop('binding_sha256');raw['extra']='rebind'
        self.scene.binding=dict(raw,binding_sha256=digest(raw));self.scene.claim['binding_sha256']=self.scene.binding['binding_sha256']
        self.scene.save_session();self.assertFalse(self.model.refresh('NVDA').fresh)

    def test_wrong_native_identity_is_unavailable(self):
        with closing(sqlite3.connect(self.scene.journal)) as c,c:c.execute('UPDATE store_identity SET schema_version=2,session_date="1999-01-01"')
        self.assertFalse(self.model.refresh('NVDA').fresh)

    def test_membership_tampering_is_unavailable(self):
        with closing(sqlite3.connect(self.scene.journal)) as c,c:c.execute('UPDATE sampling_channel_member SET symbol="AMD" WHERE revision=2 AND channel="hot"')
        self.assertFalse(self.model.refresh('NVDA').fresh)

    def test_quote_row_count_mismatch_is_unavailable(self):
        self.scene.quote_value()
        with closing(sqlite3.connect(self.scene.journal)) as c,c:c.execute('UPDATE quote_acquisition SET requested_symbol_count=2')
        self.assertFalse(self.model.refresh('NVDA').fresh)

    def test_recorded_per_run_cadence_is_preserved(self):
        self.scene.quote_value();s=self.snapshot()
        self.assertEqual(s.overlay.quote_points[0].poll_seconds,(self.scene.now.second,))

    def test_read_only_sql_never_initializes_or_takes_owner_locks(self):
        self.scene.quote_value();before=self.scene.journal.read_bytes();original=sqlite3.connect;statements=[]
        def connect(*args,**kwargs):
            self.assertTrue(kwargs.get('uri'));self.assertIn('mode=ro',args[0])
            c=original(*args,**kwargs);c.set_trace_callback(statements.append);return c
        with patch('sqlite3.connect',side_effect=connect),patch('mb_watchlist_coordinator.sampling_service.owner_lock',side_effect=AssertionError('no owner')):
            self.snapshot()
        self.assertEqual(before,self.scene.journal.read_bytes())
        self.assertFalse(any(s.lstrip().upper().startswith(('INSERT','UPDATE','DELETE','CREATE','ATTACH')) for s in statements))

    def test_other_symbols_quote_payloads_are_not_read(self):
        self.scene.quote_value(channel='uni');original=sqlite3.connect;reads=[]
        def connect(*a,**k):
            c=original(*a,**k);c.set_trace_callback(reads.append);return c
        with patch('sqlite3.connect',side_effect=connect):self.snapshot()
        selected=[s for s in reads if 'SELECT o.*,a.*' in s]
        self.assertEqual(len(selected),1);self.assertIn("o.symbol='NVDA'",selected[0])

    def test_stopped_controller_and_retained_membership_are_separate(self):
        self.scene.controller(stop={'reason':'operator_stop'})
        s=self.snapshot();self.assertEqual(s.membership['controller']['state'],'STOPPED')
        self.assertEqual(s.overlay.current_band.value,'hot')

    def test_stale_controller_is_never_reported_as_live_collection(self):
        self.scene.controller(age=4);self.assertEqual(self.snapshot().membership['controller']['state'],'STALE')

    def test_missing_source_is_unavailable_not_a_verified_empty_feed(self):
        s=self.snapshot();self.assertEqual(s.source['state'],'UNAVAILABLE');self.assertFalse(s.source['fresh'])
        self.assertEqual(s.overlay.halt_intervals,())

    def test_halt_and_resumption_have_separate_knowledge_times(self):
        self.scene.source();self.scene.capture();first=self.snapshot()
        self.assertIsNone(first.overlay.halt_intervals[0].end_et)
        self.scene.now+=timedelta(seconds=60);self.scene.capture(resume='09:55:00');second=self.snapshot()
        f=second.source['facts'][0]
        self.assertEqual(f['halt_known_at_utc'],first.source['facts'][0]['halt_known_at_utc'])
        self.assertEqual(f['resumption_known_at_utc'],utc_text(self.scene.now))
        self.assertEqual(second.overlay.halt_intervals[0].end_et.hour,9)

    def test_future_capture_does_not_disclose_resumption_before_it_was_known(self):
        self.scene.source();self.scene.capture();cutoff=self.scene.now
        self.scene.now+=timedelta(seconds=60);self.scene.capture(resume='09:55:00')
        self.scene.now=cutoff
        self.assertIsNone(self.snapshot().overlay.halt_intervals[0].end_et)

    def test_feed_raw_body_tampering_is_unavailable(self):
        self.scene.source();self.scene.capture()
        with closing(sqlite3.connect(self.scene.feed.path)) as c,c:c.execute('UPDATE feed_event SET body=? WHERE sequence=2',(b'changed',))
        s=self.snapshot();self.assertFalse(s.source['fresh']);self.assertFalse(s.overlay.halt_intervals)

    def test_source_status_chain_tampering_is_unavailable(self):
        self.scene.source();self.scene.capture()
        with closing(sqlite3.connect(self.scene.state_root/'daily-source.sqlite3')) as c,c:c.execute('UPDATE recovery_supervisor_event SET payload="{}"')
        self.assertFalse(self.snapshot().source['fresh'])

    def test_no_halt_is_inferred_from_a_quote_gap_or_security_status(self):
        self.scene.quote_value();self.assertFalse(self.snapshot().overlay.halt_intervals)

    def test_blocked_source_reasons_and_history_gaps_remain_visible(self):
        self.scene.source();self.scene.source_status('BLOCKED',('OperationalError',))
        s=self.snapshot();self.assertEqual(s.source['state'],'BLOCKED')
        self.assertIn('OperationalError',s.source['known_gaps'])
        self.assertIn('older_unknown_carryovers_not_proven_complete',s.source['known_gaps'])

    def test_slow_refresh_does_not_queue_another_read(self):
        self.snapshot();self.model._lock.acquire()
        try:
            with patch.object(self.reader,'snapshot',side_effect=AssertionError('no second read')):
                r=self.model.refresh('NVDA');self.assertFalse(r.fresh);self.assertEqual(r.error,'REFRESH_IN_PROGRESS')
        finally:self.model._lock.release()

    def test_missing_candle_cache_does_not_hide_quotes(self):
        self.reader.candle_directory=self.scene.root/'candles';self.scene.quote_value()
        s=self.snapshot();self.assertEqual(s.candles['state'],'MISSING');self.assertEqual(len(s.overlay.quote_points),1)

    def test_corrupt_candle_cache_is_explicitly_unavailable(self):
        d=self.scene.root/'candles';d.mkdir();(d/'NVDA.json').write_text('{}');self.reader.candle_directory=d
        self.assertEqual(self.snapshot().candles['state'],'UNAVAILABLE')

    def test_existing_durable_bytes_unchanged_after_source_read(self):
        self.scene.source();self.scene.capture();self.scene.quote_value()
        files=[p for p in self.scene.root.rglob('*') if p.is_file() and p.suffix in ('.json','.sqlite3')]
        before={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
        self.snapshot()
        self.assertEqual(before,{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in files})

    def test_source_read_failure_keeps_confirmed_facts_with_last_verified_label(self):
        self.scene.source();self.scene.capture();first=self.snapshot()
        path=self.scene.state_root/'daily-source-ready.json';path.write_text('{}')
        second=self.snapshot();self.assertFalse(second.source['fresh'])
        self.assertEqual(second.source['facts'],first.source['facts'])
        self.assertEqual(second.overlay.halt_intervals,first.overlay.halt_intervals)
        self.assertIsNotNone(second.source['last_verified_at_utc'])

    def test_later_blank_fields_do_not_retract_a_known_resumption(self):
        self.scene.source();self.scene.capture(resume='09:55:00');first=self.snapshot()
        self.scene.now+=timedelta(seconds=60);self.scene.capture();second=self.snapshot()
        self.assertEqual(second.source['facts'][0]['resumption_known_at_utc'],first.source['facts'][0]['resumption_known_at_utc'])
        self.assertEqual(second.overlay.halt_intervals[0].end_et,first.overlay.halt_intervals[0].end_et)

    def test_announced_future_resumption_is_known_but_halt_line_stops_at_cutoff(self):
        from mb_market_data.observation_overlay_view import resolve_halt_segments
        self.scene.source();self.scene.capture(resume='10:05:00');self.scene.quote_value()
        self.scene.now+=timedelta(seconds=2);s=self.snapshot()
        self.assertTrue(s.source['fresh'])
        segments=resolve_halt_segments(s.overlay,off_hours=False)
        self.assertEqual(segments[0].end_et,self.scene.now)
        self.assertGreater(s.overlay.halt_intervals[0].end_et,self.scene.now)

    def test_quote_resumption_is_separate_from_trade_resumption(self):
        self.scene.source()
        extra='<ndaq:ResumptionDate>'+self.scene.now.strftime('%m/%d/%Y')+'</ndaq:ResumptionDate><ndaq:ResumptionQuoteTime>09:54:00</ndaq:ResumptionQuoteTime>'
        self.scene.capture(raw=rss(self.scene.now.date(),symbol='NVDA',halt='09:45:00',extra=extra))
        s=self.snapshot();self.assertIsNotNone(s.source['facts'][0]['resumption_quote_at_utc'])
        self.assertIsNone(s.source['facts'][0]['resumption_trade_at_utc'])
        self.assertIsNone(s.overlay.halt_intervals[0].end_et)

    def candle_cache(self, *, acquired=None, symbol='NVDA', day=None):
        from mb_market_data.observation_overlay import ObservationOverlayOHLCVCache, OverlayCandle, write_observation_overlay_cache
        day=day or self.scene.now.date();start=datetime.combine(day,self.scene.start.timetz())
        cache=ObservationOverlayOHLCVCache(symbol,day,'Schwab','synthetic saved fixture',
            acquired or self.scene.now-timedelta(seconds=1),start-timedelta(minutes=30),
            start+timedelta(hours=7),'a'*64,(OverlayCandle(symbol,start,10,12,9,11,100),))
        directory=self.scene.root/'candles';directory.mkdir(exist_ok=True)
        write_observation_overlay_cache(directory/'NVDA.json',cache)
        self.reader.candle_directory=directory
        return cache

    def test_saved_completed_candles_attach_to_existing_figure(self):
        self.candle_cache();s=self.snapshot()
        self.assertEqual(s.candles['state'],'AVAILABLE');self.assertEqual(len(s.overlay.candles),1)
        from mb_market_data.observation_overlay_view import build_observation_overlay_figure
        f=build_observation_overlay_figure(s.overlay,units='percent')
        self.assertTrue(any(t.type=='candlestick' for t in f.data))
        self.assertEqual(f.layout.yaxis.title.text,'Change from reference')

    def test_candle_cache_acquired_later_is_not_visible_early(self):
        self.candle_cache(acquired=self.scene.now+timedelta(seconds=2))
        self.assertEqual(self.snapshot().candles['state'],'NOT_YET_AVAILABLE')
        self.scene.now+=timedelta(seconds=2)
        self.assertEqual(len(self.snapshot().overlay.candles),1)

    def test_closed_session_accepts_a_cache_known_now_without_extending_chart_date(self):
        day=self.scene.now.date();self.candle_cache(acquired=self.scene.now+timedelta(days=1)-timedelta(seconds=1))
        self.scene.now+=timedelta(days=1)
        s=self.snapshot();self.assertEqual(s.candles['state'],'AVAILABLE')
        self.assertEqual(s.overlay.replay_time_utc.astimezone(self.scene.now.tzinfo).date(),day)
        self.assertEqual(len(s.overlay.candles),1)

    def test_wrong_symbol_cache_is_unavailable_without_discarding_quotes(self):
        self.scene.quote_value();self.candle_cache(symbol='IBM');s=self.snapshot()
        self.assertEqual(s.candles['state'],'UNAVAILABLE');self.assertEqual(len(s.overlay.quote_points),1)

    def test_native_snapshot_does_not_mix_membership_and_quotes_across_commit(self):
        self.scene.quote_value();original=sqlite3.connect;wrote=[]
        def connect(*a,**k):
            c=original(*a,**k)
            def trace(sql):
                if 'SELECT o.*,a.*' in sql and not wrote:
                    wrote.append(True);self.scene.now+=timedelta(seconds=2);self.scene.add('AMD')
            c.set_trace_callback(trace);return c
        with patch('sqlite3.connect',side_effect=connect):first=self.snapshot()
        self.assertEqual(first.membership['effective_revision'],2)
        self.assertNotIn('AMD',first.membership['symbols'])
        self.assertEqual(self.snapshot().membership['effective_revision'],3)

    def test_carryover_halt_line_is_clipped_to_the_current_regular_session(self):
        from mb_market_data.overlay_halts import OverlayHaltInterval
        from mb_market_data.observation_overlay_view import resolve_halt_segments
        self.scene.quote_value();s=self.snapshot()
        interval=OverlayHaltInterval(self.scene.start-timedelta(days=1),None,'M')
        overlay=replace(s.overlay,halt_intervals=(interval,),replay_time_utc=self.scene.now+timedelta(seconds=2))
        line=resolve_halt_segments(overlay,off_hours=False)[0]
        self.assertEqual(line.start_et,self.scene.start)

    def test_source_status_staleness_is_separate_from_a_successful_evidence_read(self):
        self.scene.source();self.scene.now+=timedelta(seconds=4)
        s=self.snapshot();self.assertTrue(s.source['fresh']);self.assertEqual(s.source['progress'],'STALE')


if __name__=='__main__':unittest.main()
