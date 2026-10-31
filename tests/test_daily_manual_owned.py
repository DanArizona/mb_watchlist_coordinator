"""Real owned processes with synthetic credentials, SDK and native journals."""
from datetime import datetime,timedelta,timezone
import json
import os
from pathlib import Path
import sqlite3
import sys
import time
import unittest

from daily_manual_fixture import CombinedFixture
from mb_watchlist_coordinator.authenticated_startup import AuthStartupSettings,SessionPassword
from mb_watchlist_coordinator.daily_collector import DailyCollectorSettings
from mb_watchlist_coordinator.daily_controller import DailyController
from mb_watchlist_coordinator.daily_manual_controls import open_daily_controls
from mb_watchlist_coordinator.daily_session import DailySession
from mb_watchlist_coordinator.daily_supervision import DailyWorkerConfiguration
from mb_watchlist_coordinator.sampling_requests import digest,plain
from mb_watchlist_coordinator.sampling_service import ServiceBusy

EMPTY='<?xml version="1.0"?><rss version="2.0"><channel><title>Nasdaq Trade Halts</title></channel></rss>'


class DailyManualOwnedTests(unittest.TestCase):
    def setUp(self):
        proof=os.environ.get('MB_MANUAL_DAILY_PROOF_DIR') if self._testMethodName=='test_owned_controller_collects_manual_and_nasdaq_roster_and_fences_ui_after_stop' else None
        self.f=CombinedFixture(universe_size=4,root=proof);self.addCleanup(self.f.close)
        self.c=self.f.case
        self.real=datetime.now(timezone.utc);self.logical=self.c.now
        self.clock=lambda:self.logical+(datetime.now(timezone.utc)-self.real)
        self.f.session.close()
        self.c.session=self.s=self.f.session=DailySession(self.c.settings,self.c.catalog,clock=self.clock)
        self.s.attach(create=False,publication_approved=True)
        self.config=DailyWorkerConfiguration(self.c.settings,str(self.c.root/'catalog'),
            DailyCollectorSettings(str(self.c.journal),plain(self.s.service.identity),plain(self.s.binding),plain(self.s.claim),
                (self.logical+timedelta(seconds=6)).isoformat(),(self.logical+timedelta(seconds=45)).isoformat(),100,40),
            AuthStartupSettings(str(self.c.root/'synthetic-unused.ecfg'),(self.logical+timedelta(seconds=45)).isoformat()))
        import mb_market_data
        scene={'real_anchor':self.real.isoformat(),'logical_anchor':self.logical.isoformat(),
            'native_src':str(Path(mb_market_data.__file__).resolve().parents[1]),
            'log':str(self.c.root/'owned-process-events.jsonl'),'multi_quote_response':True}
        path=self.c.root/'scenario.json';path.write_text(json.dumps(scene))
        entry=Path(__file__).parent/'fixtures/daily_authenticated_process.py'
        commands={role:(sys.executable,'-I','-B',str(entry),str(path),role,str(self.s.root/'daily-worker.json'))
            for role in ('collector','identity','report')}
        self.controller=DailyController(self.s,self.config,commands=commands,
            password=SessionPassword('SYNTHETIC-PRIVATE-CANARY-62',digest(self.config.payload())),
            clock=self.clock,activation_approved=True)
        self.addCleanup(lambda:self.controller.close(report=False))
        self.controller.initialize(create=True)
        self.controls=open_daily_controls(self.s.root,expected_configuration_sha256=digest(self.config.payload()),clock=self.clock)

    def pump_until(self,predicate,seconds=14):
        deadline=time.monotonic()+seconds
        while time.monotonic()<deadline:
            if predicate():return
            self.controller.step(synthetic={'clock_at_utc':self.logical.isoformat(),
                'clock_real_anchor_utc':self.real.isoformat(),'chunks':[EMPTY]})
            time.sleep(.025)
        self.fail('Combined owned condition not observed: '+json.dumps(self.controller.status()))

    def acquisitions(self):
        from contextlib import closing
        with closing(sqlite3.connect(self.c.journal.as_uri()+'?mode=ro',uri=True))as c:
            return c.execute('SELECT count(*) FROM quote_acquisition WHERE channel="hot"').fetchone()[0]

    def test_owned_controller_collects_manual_and_nasdaq_roster_and_fences_ui_after_stop(self):
        mid=self.controls.submit('promote',symbol='IBM',target='hot')
        self.s.cycle(client=self.controller.identity_client,
            historical_snapshot=self.c.snapshot('HISTORICAL',[self.c.row('MSFT')],'owned-nasdaq'))
        self.pump_until(lambda:self.acquisitions()>=2)
        def both():
            from contextlib import closing
            with closing(sqlite3.connect(self.c.journal.as_uri()+'?mode=ro',uri=True))as c:
                return c.execute('SELECT count(*) FROM quote_acquisition WHERE channel="hot" AND requested_symbol_count=2').fetchone()[0]>=2
        self.pump_until(both)
        snapshot=self.controls.snapshot()
        self.assertEqual(set(snapshot['members']['hot']),{'IBM','MSFT'})
        self.assertEqual(next(r for r in snapshot['commands']if r['command_id']==mid)['status'],'EFFECTIVE')
        self.assertEqual(plain(self.s.gate.snapshot())['identity_gate']['quote_permits'],1)
        self.assertEqual(self.controller.status()['worker_starts'],1)
        self.assertIsNone(self.controller.state.read()['terminal'])
        child=self.controller.worker.child
        identity_child=self.controller.identity_client.child
        self.assertIsNotNone(child)
        stop=self.controller.close(report=True)
        with self.assertRaises(ValueError):self.controls.submit('promote',symbol='MSFT',target='hot')
        self.assertIsNotNone(child.poll())
        self.assertIsNotNone(identity_child.poll())
        self.assertTrue(stop['cleanup_within_10_seconds'])
        self.assertEqual(stop['evidence_errors'],[])
        self.assertEqual(stop['reporting']['status'],'COMPLETE',stop)
        self.assertTrue(stop['reporting']['native_audit_passed'])
        self.assertTrue(stop['reporting']['two_fresh_replays_equal'])
        from mb_watchlist_coordinator.daily_supervision import unseal,read_json
        report=unseal(read_json(stop['reporting']['report_path']))
        self.assertTrue(report['validation_passed'])
        self.assertTrue(report['hot_content_integrity']['passed'])
        from contextlib import closing
        with closing(sqlite3.connect(self.c.journal.as_uri()+'?mode=ro',uri=True))as c:
            statuses=dict(c.execute('SELECT o.status,count(*) FROM quote_observation o '
                'JOIN quote_acquisition a ON a.acquisition_id=o.acquisition_id '
                'WHERE a.channel="hot" GROUP BY o.status'))
        self.assertEqual(set(statuses),{'quote'})
        proof={'contract':'owned-nasdaq-manual-controller-proof-v1','result':'PASS',
            'manual_symbol':'IBM','nasdaq_symbol':'MSFT','combined_roster_native_acquisitions_at_least':2,
            'manual_feedback_effective':True,'identity_quote_permits':1,'worker_starts':1,
            'old_controls_fenced_after_stop':True,'cleanup':stop,'native_final_report':report,
            'hot_status_counts':statuses,
            'synthetic_sdk_only':True,'production_access':False,'actual_vault_access':False,
            'p85_changed':False,'full_day_capacity_qualified':False}
        (self.c.root/'combined-proof.json').write_text(json.dumps(proof,indent=2)+'\n')

    def test_wrong_configuration_cannot_attach_or_initialize_controls(self):
        with self.assertRaises(ValueError):open_daily_controls(self.s.root,expected_configuration_sha256='0'*64,clock=self.clock)
        with self.assertRaises(ValueError):self.controls.initialize()
        self.assertEqual(self.controls.snapshot()['commands'],[])

    def test_stale_owner_and_changed_invocation_disable_bound_controls_without_appending(self):
        from unittest.mock import patch
        from mb_watchlist_coordinator.daily_supervision import atomic_json,sealed,read_json,unseal
        before=self.s.manual.snapshot()['commands']
        live_path=self.s.root/'driver-live.json'
        # Pause the monitor under its ordinary lock so this is a deterministic
        # stale-receipt check rather than racing the next fresh heartbeat.
        with self.controller.lock:
            live=unseal(read_json(live_path));old=dict(live)
            live['observed_at_utc']=(self.clock()-timedelta(seconds=4)).isoformat()
            atomic_json(live_path,sealed(live))
            with self.assertRaises(ValueError):self.controls.submit('promote',symbol='IBM',target='hot')
            atomic_json(live_path,sealed(old))
        self.assertEqual(self.s.manual.snapshot()['commands'],before)

    def test_manual_resume_retains_budgets_and_fences_the_old_window(self):
        original=self.controller
        mid=self.controls.submit('promote',symbol='IBM',target='hot')
        original.close(report=False)
        before=original.state.read()
        reopened=DailySession(self.c.settings,self.c.catalog,clock=self.clock)
        self.c.session=self.f.session=self.s=reopened
        reopened.attach(create=False,publication_approved=True)
        resumed=DailyController(reopened,self.config,commands=original.commands,
            password=SessionPassword('SYNTHETIC-PRIVATE-CANARY-62',digest(self.config.payload())),
            clock=self.clock,activation_approved=True)
        self.controller=resumed
        resumed.initialize(create=False,manual_resume_approved=True)
        after=resumed.state.read()
        self.assertEqual(len(after['starts']),len(before['starts']))
        self.assertEqual(len(after['invocations']),len(before['invocations'])+1)
        self.assertGreater(datetime.fromisoformat(after['hold_until_utc']),self.clock()+timedelta(seconds=13))
        with self.assertRaises(ValueError):self.controls.snapshot()
        fresh=open_daily_controls(self.s.root,expected_configuration_sha256=digest(self.config.payload()),clock=self.clock)
        self.assertIn(mid,[r['command_id']for r in fresh.snapshot()['commands']])
