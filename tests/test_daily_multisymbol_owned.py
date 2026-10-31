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
        logical=c.at.replace(minute=2,second=0);real=datetime.now(timezone.utc)
        clock=lambda:logical+(datetime.now(timezone.utc)-real)
        stop=logical+timedelta(seconds=210);background_stop=logical+timedelta(seconds=199)
        settings=DailyCollectorSettings(str(c.journal),plain(s.service.identity),plain(s.binding),plain(s.claim),
            (logical+timedelta(seconds=6)).isoformat(),stop.isoformat(),84,40)
        config=DailyWorkerConfiguration(c.settings,str(c.root/'catalog'),settings,
            AuthStartupSettings(str(c.root/'unused.ecfg'),stop.isoformat()))
        import mb_market_data
        scene={'real_anchor':real.isoformat(),'logical_anchor':logical.isoformat(),
            'native_src':str(Path(mb_market_data.__file__).resolve().parents[1]),'log':str(c.root/'multi-process-events.jsonl'),
            'admit':False,'trace_stacks':False}
        items=[rss(logical.date(),symbol=x,halt=(logical-timedelta(minutes=1)).strftime('%H:%M:%S')).decode().split('<channel>',1)[1].split('</channel>',1)[0]
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
        progress_mark=[0]
        began=time.monotonic();proof={'contract':'multi-symbol-paced-owned-proof-v1','result':'FAILED'}
        def stop_requested():
            elapsed=time.monotonic()-began
            if elapsed-progress_mark[0]>=30:
                progress_mark[0]=elapsed
                print(json.dumps({'phase':'owned_burst_progress','elapsed_seconds':round(elapsed,1),
                    'concurrent_uni':written['uni'],'concurrent_focus':written['focus']}),flush=True)
            if writer_errors:return True
            if time.monotonic()-began>=199:
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
            # The latest status after owner.run is a stopped-state report. Check
            # the last verified active source event against this owner's Stop
            # cutoff, then check the same retained native/identity/feed evidence.
            from multisymbol_closed_checks import assess_closed_owned
            assessed=assess_closed_owned(c.root)
            self.assertEqual(assessed['background_acquisitions'],written)
            proof.update(assessed,result='PASS',elapsed_seconds=time.monotonic()-began,
                source_reconciled=True,publication_batch_seconds=10,network='denied',synthetic_only=True,
                provider_capacity_qualified=False,full_session_executed=False,production_changes=False)

        finally:
            done.set();thread.join(timeout=2)
            (c.root/'multi-owned-proof.json').write_text(json.dumps(proof,indent=2)+'\n')
