from contextlib import closing
import json
import sqlite3

import test_daily_manual_owned as original
from mb_watchlist_coordinator.operating_plan import BROKER_MANUAL_PROFILE
from mb_watchlist_coordinator.daily_supervision import read_json,unseal
from mb_watchlist_coordinator.sampling_requests import plain


class ManualIdentityOwnedTests(original.DailyManualOwnedTests):
    profile=BROKER_MANUAL_PROFILE
    proof_environment='MB_MANUAL_IDENTITY_PROOF_DIR'

    def test_owned_controller_collects_manual_and_nasdaq_roster_and_fences_ui_after_stop(self):
        mid=self.controls.submit('promote',symbol='X000',target='hot')
        self.assertEqual(next(r for r in self.controls.snapshot()['commands']if r['command_id']==mid)['status'],'PENDING')
        self.assertEqual(plain(self.s.gate.snapshot())['identity_gate']['quote_permits'],0)
        self.s.cycle(client=self.controller.identity_client,
            historical_snapshot=self.c.snapshot('HISTORICAL',[self.c.row('X001')],'shared-owned'))
        def both():
            with closing(sqlite3.connect(self.c.journal.as_uri()+'?mode=ro',uri=True))as c:
                return c.execute('SELECT count(*) FROM quote_acquisition WHERE channel="hot" AND requested_symbol_count=2').fetchone()[0]>=2
        self.pump_until(both)
        view=self.controls.snapshot()
        self.assertEqual(set(view['members']['hot']),{'X000','X001'})
        self.assertEqual(next(r for r in view['commands']if r['command_id']==mid)['status'],'EFFECTIVE')
        gate=plain(self.s.gate.snapshot())['identity_gate']
        self.assertEqual(gate['quote_permits'],2)
        self.assertEqual(self.controller.status()['worker_starts'],1)
        self.assertEqual({r['producer_id']for r in self.s.requests.states()[-1].active_requests},
            {'operator:masterbot','nasdaq-shared-daily'})
        worker,identity=self.controller.worker.child,self.controller.identity_client.child
        self.assertIsNone(worker.poll());self.assertIsNone(identity.poll())
        stop=self.controller.close(report=True)
        self.assertIsNotNone(worker.poll());self.assertIsNotNone(identity.poll())
        self.assertTrue(stop['cleanup_within_10_seconds']);self.assertEqual(stop['evidence_errors'],[])
        with self.assertRaises(ValueError):self.controls.submit('promote',symbol='X002',target='hot')
        report=unseal(read_json(stop['reporting']['report_path']))
        self.assertTrue(report['validation_passed']);self.assertTrue(report['hot_content_integrity']['passed'])
        self.assertTrue(report['native_audit_passed']);self.assertTrue(report['two_fresh_replays_equal'])
        with closing(sqlite3.connect(self.c.journal.as_uri()+'?mode=ro',uri=True))as c:
            statuses=dict(c.execute('SELECT o.status,count(*) FROM quote_observation o '
                'JOIN quote_acquisition a ON a.acquisition_id=o.acquisition_id WHERE a.channel="hot" GROUP BY o.status'))
        self.assertEqual(set(statuses),{'quote'})
        proof={'contract':'manual-outside-uni-owned-collection-proof-v1','result':'PASS',
            'manual_symbol':'X000','nasdaq_symbol':'X001','both_symbols_outside_opening_uni':True,
            'identity_quote_permits':2,'worker_starts':1,'both_children_live_before_stop':True,
            'manual_pending_then_effective':True,'old_window_fenced_after_stop':True,
            'cleanup':stop,'native_final_report':report,'hot_status_counts':statuses,
            'identity_events':gate['events'],'synthetic_sdk_only':True,'production_access':False,
            'actual_vault_access':False,'full_day_capacity_qualified':False,'p85_changed':False}
        (self.c.root/'manual-identity-proof.json').write_text(json.dumps(proof,indent=2)+'\n')

    def test_pending_withdrawal_through_bound_controls_leaves_no_identity_dispatch(self):
        mid=self.controls.submit('promote',symbol='X000',target='hot')
        self.controls.submit('withdraw',request_id=mid)
        self.s.cycle(client=self.controller.identity_client)
        self.assertEqual(plain(self.s.gate.snapshot())['identity_gate']['quote_permits'],0)
        self.assertFalse(self.s.requests.states()[-1].active_requests)
        self.assertEqual(next(r for r in self.controls.snapshot()['commands']if r['command_id']==mid)['status'],'WITHDRAWN')
