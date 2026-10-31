"""One actual paced multi-symbol daily composition with concurrent native writers."""
from contextlib import closing
from datetime import datetime,timedelta,timezone
import json,os,sqlite3,sys,threading,time,unittest
from pathlib import Path

from mb_watchlist_coordinator.authenticated_startup import AuthStartupSettings,SessionPassword
from mb_watchlist_coordinator.daily_collector import DailyCollectorSettings
from mb_watchlist_coordinator.daily_operating import DailyOperatingOwner
from mb_watchlist_coordinator.daily_supervision import DailyWorkerConfiguration,read_json,unseal
from mb_watchlist_coordinator.sampling_requests import digest,plain
from test_daily_multisymbol import MultiFixture,SYMBOLS,_quote_shape
from test_nasdaq_feed_recovery import rss


class MultiOwnedTests(unittest.TestCase):
    def test_paced_forty_symbol_admissions_cross_period_while_uni_focus_keep_writing(self):
        directory=os.environ.get('MB_MULTI_OWNED_PROOF_DIR')
        f=MultiFixture(background=True,root=Path(directory) if directory else None);self.addCleanup(f.close)
        c,s=f.case,f.session
        logical=c.at.replace(minute=4,second=30);real=datetime.now(timezone.utc)
        clock=lambda:logical+(datetime.now(timezone.utc)-real)
        stop=logical+timedelta(seconds=180);background_stop=logical+timedelta(seconds=173)
        settings=DailyCollectorSettings(str(c.journal),plain(s.service.identity),plain(s.binding),plain(s.claim),
            (logical+timedelta(seconds=6)).isoformat(),stop.isoformat(),72,40)
        config=DailyWorkerConfiguration(c.settings,str(c.root/'catalog'),settings,
            AuthStartupSettings(str(c.root/'unused.ecfg'),stop.isoformat()))
        import mb_market_data
        scene={'real_anchor':real.isoformat(),'logical_anchor':logical.isoformat(),
            'native_src':str(Path(mb_market_data.__file__).resolve().parents[1]),'log':str(c.root/'multi-process-events.jsonl'),
            'admit':False,'trace_stacks':False}
        items=[rss(logical.date(),symbol=x,halt='10:03:00').decode().split('<channel>',1)[1].split('</channel>',1)[0]
            for x in SYMBOLS[:41]]
        scene['feed_body']='<rss><channel>'+''.join(items)+'</channel></rss>'
        scene_path=c.root/'multi-scene.json';scene_path.write_text(json.dumps(scene))
        fixture=Path(__file__).parent/'fixtures'
        commands={role:(sys.executable,'-I','-B',str(fixture/'multi_authenticated_process.py'),str(scene_path),role,
            str(Path(c.settings.state_root)/'daily-worker.json'))for role in ('collector','identity','report')}
        entries={role:(sys.executable,'-I','-B',str(fixture/'daily_operating_process.py'),str(scene_path),role)
            for role in ('controller','report')}
        # Preserve the original external registrations and add only this
        # test-owned writer's explicit interval. No production process exists.
        from mb_market_data.quote_observation_store import PollRunProvenance
        for channel,seconds in (('uni',[0,30]),('focus',[10,20,40,50])):
            c.store.record_run(PollRunProvenance('concurrent-'+channel,logical,'synthetic-concurrent',
                {'watchlist_kind':channel,'poll_seconds':seconds,'cadence_profile':'interleaved-v1',
                 'poll_window_start_et':logical.isoformat(),'poll_window_end_et':background_stop.isoformat()}))
        s.close();done=threading.Event();writer_errors=[];written={'uni':0,'focus':0}
        def writer():
            from mb_market_data.sampling_acquisition import ExplicitPollSlot
            from mb_market_data.sampling_membership import SamplingChannel
            from mb_market_data.watchlist_polling import PollRequest
            from mb_market_data.schwab_quotes import QuoteBatchResult,QuoteResult,QuoteStatus
            seen=set()
            try:
                while not done.wait(.02):
                    now=clock()
                    for channel,seconds in ((SamplingChannel.UNI,(0,30)),(SamplingChannel.FOCUS,(10,20,40,50))):
                        for minute in (now.replace(second=0,microsecond=0)-timedelta(minutes=1),now.replace(second=0,microsecond=0)):
                            for second in seconds:
                                at=minute.replace(second=second);key=(channel.value,at)
                                if key in seen or not logical<=at<min(now,background_stop):continue
                                r=c.store.latest_membership_revision_effective_at(at);symbols=r.symbols_for(channel)
                                request=PollRequest(ExplicitPollSlot(channel,at,seconds),r.revision,symbols,now)
                                results=tuple(QuoteResult(x,QuoteStatus.QUOTE,dict(_quote_shape()(now,n),symbol=x),None,
                                    n//400+1,now,now)for n,x in enumerate(symbols))
                                batch=QuoteBatchResult(results,(len(symbols)+399)//400,400,())
                                c.store.record_acquisition('concurrent-'+channel.value,request,batch,completed_at=now)
                                seen.add(key);written[channel.value]+=1
            except BaseException as error:writer_errors.append(type(error).__name__+':'+str(error))
        thread=threading.Thread(target=writer,daemon=True);thread.start()
        owner=DailyOperatingOwner(c.root/'daily_outer_multi',config,commands=commands,
            controller_entry=entries['controller'],reporter_entry=entries['report'],clock=clock,activation_approved=True)
        began=time.monotonic();proof={'contract':'multi-symbol-paced-owned-proof-v1','result':'FAILED'}
        def stop_requested():
            if writer_errors:return True
            if time.monotonic()-began>=173:
                done.set();thread.join(timeout=1);return True
            return False
        try:
            print('Owned multi-symbol proof: 41 simultaneous candidates; real 60-second source pacing, 2-second identity spacing and concurrent Uni/Focus SQLite writers.',flush=True)
            result=owner.run(SessionPassword('SYNTHETIC-PRIVATE-CANARY-62',digest(config.payload())),stop_requested_callback=stop_requested)
            proof.update(owner=result,elapsed_seconds=time.monotonic()-began,background_acquisitions=written,writer_errors=writer_errors)
            self.assertFalse(writer_errors,proof)
            self.assertEqual(result['result'],'STOPPED',proof)
            self.assertEqual(result['cleanup']['status'],'EXIT_OBSERVED',proof)
            self.assertTrue(result['reporting']['validation_passed'],proof)
            state=Path(config.publication.state_root)
            status=unseal(read_json(state/'hot-status.json'));driver=unseal(read_json(state/'driver-state.json'))
            self.assertTrue(status['source_reconciled'],status)
            self.assertEqual(len(driver['starts']),1,driver);self.assertIsNone(driver['terminal'],driver)
            with closing(sqlite3.connect(c.journal.as_uri()+'?mode=ro',uri=True))as db:
                maximum=db.execute('SELECT max(requested_symbol_count) FROM quote_acquisition WHERE channel="hot"').fetchone()[0]
                full=db.execute('SELECT count(*) FROM quote_acquisition WHERE channel="hot" AND requested_symbol_count=40').fetchone()[0]
            self.assertEqual(maximum,40,proof);self.assertGreaterEqual(full,2,proof)
            events=[json.loads(line)for line in Path(scene['log']).read_text().splitlines()]
            identity=[e for e in events if e['role']=='identity'and e['event']=='quote']
            intervals=[(datetime.fromisoformat(b['at'])-datetime.fromisoformat(a['at'])).total_seconds()for a,b in zip(identity,identity[1:])]
            self.assertEqual(len(identity),40,identity);self.assertTrue(all(x>=2 for x in intervals),intervals)
            self.assertTrue(all(e['event']!='failed'for e in events),events)
            with closing(sqlite3.connect((state/'daily-feed.sqlite3').as_uri()+'?mode=ro',uri=True))as db:
                feed=[json.loads(r[0])for r in db.execute('SELECT payload FROM feed_event ORDER BY sequence')]
            starts=[e for e in feed if e['kind']=='start'];finishes=[e for e in feed if e['kind']=='finish']
            self.assertEqual(len(starts),3,feed);self.assertEqual(len(finishes),3,feed)
            gaps=[(datetime.fromisoformat(starts[n+1]['at_utc'])-datetime.fromisoformat(finishes[n]['at_utc'])).total_seconds()for n in range(2)]
            self.assertTrue(all(x>=60 for x in gaps),gaps)
            self.assertGreaterEqual(len(list(c.journal.parent.glob('*.hot.e*.poller.sqlite3'))),2)
            self.assertTrue(all(written[x]>0 for x in ('uni','focus')))
            proof.update(result='PASS',source_attempts=3,source_reconciled=True,identity_calls=40,
                minimum_identity_interval_seconds=min(intervals),source_intervals_seconds=gaps,
                full_roster_hot_acquisitions=full,worker_starts=1,network='denied',synthetic_only=True,
                provider_capacity_qualified=False,full_session_executed=False,production_changes=False)
        finally:
            done.set();thread.join(timeout=2)
            (c.root/'multi-owned-proof.json').write_text(json.dumps(proof,indent=2)+'\n')
