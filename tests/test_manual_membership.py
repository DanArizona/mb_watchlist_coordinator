import json
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import timedelta
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from manual_membership_fixture import ManualScene
from mb_market_data.quote_journal_audit import audit_quote_journal
from mb_watchlist_coordinator.manual_membership import ManualMembershipControls, ManualMembershipModel
from mb_watchlist_coordinator.sampling_request_store import RequestConflictError


def interrupted(stage):
    def hook(actual):
        if actual == stage: raise RuntimeError('Synthetic interruption')
    return hook


class ManualMembershipTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.scene = ManualScene(self.root/'scene')

    def promote(self, **kwargs):
        return self.scene.controls.submit('promote', symbol='MSFT', target='hot', **kwargs)

    def test_requested_pending_and_native_effective_are_distinct(self):
        cid = self.promote()
        row = self.scene.row(cid)
        self.assertEqual((row['status'],row['effective_group']),('PENDING','uni'))
        self.scene.service.cycle()
        self.assertEqual(self.scene.row(cid)['status'],'PENDING')
        self.scene.advance(.3)
        row = self.scene.row(cid)
        self.assertEqual((row['status'],row['effective_group']),('EFFECTIVE','hot'))

    def test_focus_promotion_preserves_hot_subset_focus_subset_uni(self):
        cid = self.scene.controls.submit('promote', symbol='AAPL',target='focus')
        self.scene.publish()
        state=self.scene.controls.snapshot()
        self.assertEqual(self.scene.row(cid)['effective_group'],'focus')
        self.assertLessEqual(set(state['members']['hot']),set(state['members']['focus']))
        self.assertLessEqual(set(state['members']['focus']),set(state['members']['uni']))

    def test_withdrawal_does_not_cancel_nasdaq_demand(self):
        cid=self.promote(); self.scene.nasdaq(); self.scene.publish()
        withdrawal=self.scene.controls.submit('withdraw', request_id=cid)
        self.scene.publish()
        row=self.scene.row(withdrawal)
        self.assertEqual((row['status'],row['effective_group']),('WITHDRAWN','hot'))
        self.assertEqual(row['other_sources'],['nasdaq-shared-daily'])
        self.assertIn('nasdaq-1',[r['intent_id'] for r in self.scene.requests.states()[-1].active_requests])

    def test_foreign_withdrawal_has_durable_blocked_receipt(self):
        self.scene.nasdaq()
        cid=self.scene.controls.submit('withdraw', request_id='nasdaq-1')
        self.scene.reopen()
        self.assertEqual(self.scene.row(cid)['status'],'BLOCKED')
        self.assertEqual(self.scene.row(cid)['detail'],'unknown_request')
        self.assertTrue(self.scene.requests.states()[-1].active_requests)

    def test_own_withdrawal_observes_policy_hold_and_then_demotion(self):
        cid=self.promote(); self.scene.publish(); self.scene.advance(10)
        wid=self.scene.controls.submit('withdraw',request_id=cid); self.scene.publish()
        self.assertTrue(self.scene.row(wid)['demotion_holds'])
        self.assertEqual(self.scene.row(wid)['effective_group'],'hot')
        self.scene.advance(120); self.scene.publish()
        self.assertEqual(self.scene.row(wid)['effective_group'],'uni')
        self.assertEqual(self.scene.row(cid)['status'],'WITHDRAWN')

    def test_own_hot_to_focus_demotion_preserves_focus_demand(self):
        cid=self.promote(); self.scene.publish()
        lower=self.scene.controls.submit('demote',request_id=cid,target='focus')
        self.scene.publish()
        self.assertEqual(self.scene.row(lower)['status'],'PENDING')
        self.scene.advance(130); self.scene.publish()
        self.assertEqual((self.scene.row(lower)['status'],self.scene.row(lower)['effective_group']),('EFFECTIVE','focus'))
        active=self.scene.requests.states()[-1].active_requests
        self.assertTrue(any(r['intent_id']==lower+':replacement' and r['sampling_channel']=='focus' for r in active))

    def test_own_demotion_does_not_override_nasdaq_hot(self):
        cid=self.promote(); self.scene.nasdaq(); self.scene.publish()
        lower=self.scene.controls.submit('demote',request_id=cid,target='focus')
        self.assertEqual(self.scene.row(lower)['status'],'PENDING')
        self.assertTrue(self.scene.row(lower)['publication_pending']); self.scene.publish()
        self.assertEqual((self.scene.row(lower)['status'],self.scene.row(lower)['effective_group']),('LOWERED','hot'))

    def test_lowered_focus_demand_can_be_withdrawn(self):
        cid=self.promote(); self.scene.publish()
        lower=self.scene.controls.submit('demote',request_id=cid,target='focus'); self.scene.publish()
        self.scene.controls.submit('withdraw',request_id=lower+':replacement')
        self.scene.advance(130); self.scene.publish()
        self.assertEqual(self.scene.row(lower)['status'],'WITHDRAWN')
        self.assertEqual(self.scene.row(lower)['effective_group'],'uni')

    def test_own_demotion_to_uni_does_not_create_another_demand(self):
        cid=self.promote(); self.scene.publish()
        lower=self.scene.controls.submit('demote',request_id=cid,target='uni'); self.scene.publish()
        self.scene.advance(130); self.scene.publish()
        self.assertEqual(self.scene.row(lower)['status'],'EFFECTIVE')
        self.assertEqual(self.scene.requests.states()[-1].active_requests,())

    def test_lowering_adds_replacement_before_withdraw_and_recovers_interruption(self):
        cid=self.promote(); self.scene.publish()
        with self.assertRaises(RuntimeError): self.scene.controls.submit('demote',request_id=cid,target='focus',
            command_id='lower',fault_hook=interrupted('after_replacement'))
        self.assertEqual(len(self.scene.requests.states()[-1].active_requests),2)
        self.scene.reopen().retry('lower'); self.scene.publish()
        self.assertEqual(len(self.scene.requests.states()[-1].active_requests),1)
        self.assertEqual(self.scene.row('lower')['status'],'PENDING')

    def test_foreign_or_not_lower_request_demotion_is_durably_blocked(self):
        self.scene.nasdaq()
        cid=self.scene.controls.submit('demote',request_id='nasdaq-1',target='focus')
        self.assertEqual(self.scene.row(cid)['detail'],'own_active_higher_request_required')
        fid=self.scene.controls.submit('promote',symbol='MSFT',target='focus')
        cid=self.scene.controls.submit('demote',request_id=fid,target='focus')
        self.assertEqual(self.scene.row(cid)['status'],'BLOCKED')

    def test_opening_focus_is_not_removed_by_own_withdrawal(self):
        cid=self.scene.controls.submit('promote',symbol='SPY',target='focus'); self.scene.publish()
        wid=self.scene.controls.submit('withdraw',request_id=cid); self.scene.advance(130); self.scene.publish()
        self.assertEqual(self.scene.row(wid)['effective_group'],'focus')

    def test_ordinary_operator_cannot_apply_or_clear_privileged_limits(self):
        a=self.scene.controls.submit('limit',symbol='MSFT',target='uni')
        b=self.scene.controls.submit('clear_limit',symbol='MSFT',request_id='a-limit')
        for cid in (a,b):
            self.assertEqual(self.scene.row(cid)['detail'],'not_restriction_authority')
        self.assertEqual(self.scene.requests.events(),())

    def test_privileged_cap_overrides_nasdaq_and_clear_restores_demand(self):
        self.scene=ManualScene(self.root/'privileged',actor='operator:masterbot',privileged=True)
        self.scene.nasdaq(); self.scene.publish()
        limit=self.scene.controls.submit('limit',symbol='MSFT',target='focus')
        self.assertEqual(self.scene.row(limit)['status'],'PENDING')
        self.scene.publish()
        self.assertEqual((self.scene.row(limit)['status'],self.scene.row(limit)['effective_group']),('EFFECTIVE','focus'))
        clear=self.scene.controls.submit('clear_limit',symbol='MSFT',request_id=limit)
        self.scene.service.cycle()
        self.assertEqual(self.scene.row(clear)['status'],'PENDING')
        self.assertTrue(self.scene.row(clear)['publication_pending'])
        self.scene.advance(.3)
        self.assertEqual(self.scene.row(clear)['status'],'CLEARED')
        self.assertEqual(self.scene.row(clear)['effective_group'],'hot')
        self.assertEqual(self.scene.row(limit)['status'],'INACTIVE')

    def test_restricted_request_shows_blocked_with_actual_membership(self):
        self.scene.requests.restrict_symbol('cap',symbol='MSFT',max_group='uni',actor_id='operator:masterbot')
        cid=self.promote(); self.scene.publish()
        row=self.scene.row(cid)
        self.assertEqual((row['status'],row['effective_group']),('BLOCKED','uni'))
        self.assertTrue(row['active_restrictions'])

    def test_stale_restriction_selection_cannot_clear_a_newer_cap(self):
        self.scene=ManualScene(self.root/'privileged',actor='operator:masterbot',privileged=True)
        old=self.scene.controls.submit('limit',symbol='MSFT',target='focus')
        self.scene.controls.submit('limit',symbol='MSFT',target='uni')
        cid=self.scene.controls.submit('clear_limit',symbol='MSFT',request_id=old)
        self.assertEqual(self.scene.row(cid)['detail'],'restriction_not_current')

    def test_outside_uni_does_not_bypass_identity_or_add_membership(self):
        cid=self.scene.controls.submit('promote',symbol='OUT',target='hot')
        self.assertEqual(self.scene.row(cid)['detail'],'manual_identity_confirmation_required')
        self.assertEqual(self.scene.requests.events(),())
        self.assertNotIn('OUT',self.scene.controls.snapshot()['members']['uni'])

    def test_exact_retry_preserves_original_created_time_and_one_backend_event(self):
        cid=self.promote(command_id='same'); first=self.scene.requests.events()[0]
        self.scene.advance(5); self.scene.reopen(); self.promote(command_id=cid)
        self.assertEqual(self.scene.requests.events(),(first,))
        self.assertEqual(len(self.scene.controls.snapshot()['commands']),1)

    def test_conflicting_id_is_refused_without_changing_original_action(self):
        self.promote(command_id='same')
        with self.assertRaises(ValueError): self.scene.controls.submit('promote',symbol='AAPL',target='focus',command_id='same')
        self.assertEqual(self.scene.row('same')['symbol'],'MSFT')

    def test_existing_backend_id_collision_is_refused(self):
        self.scene.nasdaq('other')
        from mb_watchlist_coordinator.models import ProducerIntent,IntentType
        self.scene.requests.submit_request(ProducerIntent('collision',self.scene.actor,IntentType.ENSURE_PRESENT,
            frozenset({'AAPL'}),self.scene.now,metadata={'sampling_channel':'focus','session_date':str(self.scene.day)}),actor_id=self.scene.actor)
        with self.assertRaises(RequestConflictError): self.promote(command_id='collision')
        self.assertEqual(self.scene.row('collision')['status'],'REQUESTED')

    def test_interruption_after_durable_request_is_recoverable(self):
        with self.assertRaises(RuntimeError): self.promote(command_id='pending',fault_hook=interrupted('after_requested'))
        self.assertEqual(self.scene.row('pending')['status'],'REQUESTED')
        self.assertEqual(self.scene.requests.events(),())
        self.scene.reopen().retry('pending')
        self.assertEqual(len(self.scene.requests.events()),1)
        self.assertEqual(self.scene.row('pending')['status'],'PENDING')

    def test_lost_backend_reply_recovers_same_receipt_after_restart(self):
        with self.assertRaises(RuntimeError): self.promote(command_id='lost',fault_hook=interrupted('after_backend'))
        before=self.scene.requests.events()
        self.scene.reopen().retry('lost')
        self.assertEqual(self.scene.requests.events(),before)
        self.scene.publish(); self.assertEqual(self.scene.row('lost')['status'],'EFFECTIVE')

    def test_lost_reply_recovery_after_close_does_not_create_fresh_demand(self):
        with self.assertRaises(RuntimeError): self.promote(command_id='lost',fault_hook=interrupted('after_backend'))
        before=self.scene.requests.events(); self.scene.advance(700)
        self.scene.reopen().retry('lost')
        self.assertEqual(self.scene.requests.events(),before)
        self.assertEqual(self.scene.row('lost')['status'],'EXPIRED')

    def test_new_action_after_close_is_durably_blocked(self):
        self.scene.advance(700); cid=self.promote()
        self.assertEqual(self.scene.row(cid)['detail'],'manual_session_closed')
        self.assertEqual(self.scene.requests.events(),())

    def test_pending_unapplied_action_after_close_cannot_start_new_demand(self):
        with self.assertRaises(RuntimeError): self.promote(command_id='late',fault_hook=interrupted('after_requested'))
        self.scene.advance(700); self.scene.controls.retry('late')
        self.assertEqual(self.scene.row('late')['detail'],'manual_session_closed')

    def test_reopen_reconstructs_requested_effective_and_blocked_feedback(self):
        a=self.promote(); self.scene.publish()
        b=self.scene.controls.submit('promote',symbol='OUT',target='hot')
        before=self.scene.controls.snapshot(); self.scene.reopen()
        self.assertEqual(self.scene.controls.snapshot(),before)
        self.assertEqual((self.scene.row(a)['status'],self.scene.row(b)['status']),('EFFECTIVE','BLOCKED'))

    def test_controls_do_not_drive_publication_or_modify_native_journal(self):
        before=self.scene.store.database_path.read_bytes()
        self.promote(); self.scene.controls.snapshot()
        self.assertEqual(self.scene.store.database_path.read_bytes(),before)
        self.assertEqual(len(self.scene.service.journal.revisions()),2)

    def test_missing_receipt_ledger_is_not_created_by_read(self):
        control=ManualMembershipControls(self.root/'missing.sqlite3',publication=self.scene.service,actor_id=self.scene.actor)
        with self.assertRaises(sqlite3.OperationalError): control.snapshot()
        self.assertFalse(control.path.exists())

    def test_changed_actor_or_capability_is_refused(self):
        self.scene.controls.actor_id='nasdaq-shared-daily'
        with self.assertRaises(ValueError): self.promote()
        self.scene.controls.actor_id=self.scene.actor; self.scene.controls.allow_restrictions=True
        with self.assertRaises(ValueError): self.promote()
        self.assertEqual(self.scene.requests.events(),())

    def test_policy_rejects_untrusted_privilege_at_construction(self):
        with self.assertRaises(ValueError): ManualMembershipControls(self.root/'other.sqlite3',publication=self.scene.service,
            actor_id=self.scene.actor,allow_restrictions=True)

    def test_original_p85_source_policy_cannot_be_silently_enabled_for_manual(self):
        from dataclasses import replace
        self.scene.requests.admission=replace(self.scene.requests.admission,allowed_sources=frozenset({'nasdaq-shared-daily'}))
        with self.assertRaises(ValueError): ManualMembershipControls(self.root/'other.sqlite3',publication=self.scene.service,actor_id=self.scene.actor)

    def test_manual_hash_tampering_fails_closed(self):
        self.promote()
        with closing(sqlite3.connect(self.scene.controls.path)) as c,c:
            raw=json.loads(c.execute('SELECT payload FROM manual_event WHERE sequence=1').fetchone()[0]); raw['command']['symbol']='AAPL'
            c.execute('UPDATE manual_event SET payload=? WHERE sequence=1',(json.dumps(raw),))
        with self.assertRaises(ValueError): self.scene.controls.snapshot()

    def test_backend_tampering_blocks_feedback_and_new_dispatch(self):
        self.promote()
        with closing(sqlite3.connect(self.scene.requests.path)) as c,c:
            c.execute("UPDATE request_event SET actor_id='forged' WHERE sequence=1")
        with self.assertRaises(ValueError): self.scene.controls.snapshot()
        with self.assertRaises(ValueError): self.promote()

    def test_clock_reversal_is_refused(self):
        self.promote(); self.scene.advance(-1)
        with self.assertRaises(ValueError): self.promote()
        with self.assertRaises(ValueError): self.scene.controls.snapshot()

    def test_native_audit_passes_after_promote_limit_clear_withdraw(self):
        self.scene=ManualScene(self.root/'privileged',actor='operator:masterbot',privileged=True,grace=0,residence=0)
        cid=self.promote(); self.scene.publish()
        cap=self.scene.controls.submit('limit',symbol='MSFT',target='uni'); self.scene.publish()
        self.scene.controls.submit('clear_limit',symbol='MSFT',request_id=cap); self.scene.publish()
        self.scene.controls.submit('withdraw',request_id=cid); self.scene.publish()
        self.assertTrue(audit_quote_journal(self.scene.store.database_path).passed)

    def test_two_manual_clients_keep_both_receipts_without_duplicate_dispatch(self):
        controls=[ManualMembershipControls(self.scene.controls.path,publication=self.scene.service,actor_id=self.scene.actor) for _ in range(2)]
        def issue(i):
            from mb_watchlist_coordinator.sampling_service import ServiceBusy
            import time
            for _ in range(50):
                try: return controls[i].submit('promote',symbol='MSFT',target='hot',command_id='shared')
                except ServiceBusy: time.sleep(.002)
            self.fail('Manual receipt owner did not release')
        with ThreadPoolExecutor(max_workers=2) as pool: self.assertEqual(list(pool.map(issue,range(2))),['shared','shared'])
        self.assertEqual(len(self.scene.requests.events()),1)
        self.assertEqual(len(self.scene.controls.snapshot()['commands']),1)

    def test_failed_read_retains_feedback_and_disables_model_mutations(self):
        cid=self.promote(); model=ManualMembershipModel(self.scene.controls)
        good=model.refresh()
        with patch.object(self.scene.controls,'snapshot',side_effect=OSError('synthetic')):
            failed=model.refresh()
        self.assertFalse(failed['fresh']); self.assertEqual(failed['last_verified']['commands'],good['commands'])
        with self.assertRaises(ValueError): model.submit('withdraw',request_id=cid)
        self.assertTrue(model.refresh()['fresh'])

    def test_model_initial_read_error_does_not_claim_empty_verified_state(self):
        model=ManualMembershipModel(self.scene.controls)
        with patch.object(self.scene.controls,'snapshot',side_effect=OSError('synthetic')): value=model.refresh()
        self.assertIsNone(value['last_verified']); self.assertFalse(value['fresh'])

    def test_invalid_inputs_do_not_append_receipts(self):
        for args in [dict(action='promote',symbol='',target='hot'),dict(action='promote',symbol='MSFT',target='uni'),
                     dict(action='withdraw',request_id='x',symbol='MSFT'),dict(action='limit',symbol='MSFT',target='hot')]:
            with self.subTest(args=args), self.assertRaises(ValueError): self.scene.controls.submit(**args)
        self.assertEqual(self.scene.controls.snapshot()['commands'],[])

    def test_status_does_not_read_quote_payloads(self):
        original=sqlite3.connect; sql=[]
        class Traced(sqlite3.Connection):
            def execute(self,statement,*args,**kwargs):
                sql.append(statement); return super().execute(statement,*args,**kwargs)
        def connect(*args,**kwargs): return original(*args,**dict(kwargs,factory=Traced))
        with patch('sqlite3.connect',side_effect=connect): self.scene.controls.snapshot()
        self.assertFalse(any('quote_observation' in q.lower() or 'quote_acquisition' in q.lower() for q in sql))
