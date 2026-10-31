from concurrent.futures import Future
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from manual_membership_fixture import ManualScene
from mb_watchlist_coordinator.manual_membership import ManualMembershipModel
from mb_watchlist_coordinator.manual_membership_window import ManualMembershipWindow


class Widget:
    def __init__(self, value=''): self.value, self.options, self.state_writes = value, {}, 0
    def configure(self, **kwargs):
        self.options.update(kwargs)
        if 'state' in kwargs: self.state_writes += 1
    def get(self): return self.value


class Table:
    def __init__(self): self.rows, self.selected, self.offset, self.writes = {}, (), .4, 0
    def selection(self): return self.selected
    def selection_set(self, cid): self.selected = (cid,)
    def yview(self): return self.offset, 1
    def yview_moveto(self, value): self.offset=value
    def get_children(self): return tuple(self.rows)
    def exists(self, cid): return cid in self.rows
    def insert(self, *args, iid, values): self.rows[iid]=values; self.writes+=1
    def item(self, cid, *, values): self.rows[cid]=values; self.writes+=1
    def delete(self, cid): del self.rows[cid]; self.writes+=1


class ManualWindowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.scene=ManualScene(Path(self.temp.name)/'scene')
        self.model=ManualMembershipModel(self.scene.controls)
        w=self.window=object.__new__(ManualMembershipWindow)
        w.model=self.model; w.last_value=w.last_rows=w.future=None
        w.pending_action=None; w.button_states={}
        w.closed=False; w.interval_ms=100; w.read_count=0
        w.banner=Widget(); w.context=Widget(); w.action_text=Widget(); w.detail=Widget(); w.privilege=Widget()
        w.symbol=Widget(' msft '); w.reason=Widget('Operator reason')
        w.table=Table()
        w.buttons={k:Widget() for k in ('focus','hot','demote_focus','demote_uni','withdraw','retry','limit_focus','limit_uni','clear_limit')}
        self.jobs=[]; self.callbacks=[]
        def schedule(fn):
            future=Future(); self.jobs.append((fn,future)); return future
        w.pool=SimpleNamespace(submit=schedule,shutdown=lambda **kwargs: None)
        w.root=SimpleNamespace(after=lambda *args:self.callbacks.append(args),destroy=lambda:None)

    def settle(self):
        fn,future=self.jobs[-1]
        try: future.set_result(fn())
        except Exception as error: future.set_exception(error)
        self.window._tick()

    def fresh(self): self.window._apply(self.model.refresh())

    def test_refresh_shows_requested_and_effective_in_separate_columns(self):
        cid=self.scene.controls.submit('promote',symbol='MSFT',target='hot')
        self.fresh()
        self.assertEqual(self.window.table.rows[cid][2:5],('hot','PENDING','uni'))
        self.scene.publish(); self.fresh()
        self.assertEqual(self.window.table.rows[cid][3:5],('EFFECTIVE','hot'))

    def test_refresh_preserves_selection_and_scroll(self):
        cid=self.scene.controls.submit('promote',symbol='MSFT',target='hot')
        self.fresh(); self.window.table.selection_set(cid)
        self.scene.publish(); self.fresh()
        self.assertEqual(self.window.table.selected,(cid,)); self.assertEqual(self.window.table.offset,.4)

    def test_unchanged_refresh_does_not_rewrite_rows(self):
        self.scene.controls.submit('promote',symbol='MSFT',target='hot'); self.fresh()
        before=self.window.table.writes; self.fresh()
        self.assertEqual(self.window.table.writes,before)

    def test_failed_refresh_keeps_rows_and_disables_all_edits(self):
        cid=self.scene.controls.submit('promote',symbol='MSFT',target='hot'); self.fresh()
        with patch.object(self.scene.controls,'snapshot',side_effect=OSError()): self.window._apply(self.model.refresh())
        self.assertIn(cid,self.window.table.rows)
        self.assertIn('UNAVAILABLE',self.window.banner.options['text'])
        self.assertTrue(all(w.options['state']=='disabled' for w in self.window.buttons.values()))

    def test_initial_error_does_not_show_verified_empty_membership(self):
        with patch.object(self.scene.controls,'snapshot',side_effect=OSError()): self.window._apply(self.model.refresh())
        self.assertFalse(self.window.table.rows)
        self.assertIn('UNAVAILABLE',self.window.banner.options['text'])

    def test_slow_refresh_keeps_one_pending_click_without_queueing_duplicate_reads(self):
        self.fresh()
        for _ in range(10):
            self.window._tick(); self.window.submit('promote',target='hot')
        self.assertEqual(len(self.jobs),1)
        self.assertIsNotNone(self.window.pending_action)

    def test_routine_refresh_keeps_button_states_steady_without_repainting(self):
        self.fresh()
        before={k:b.state_writes for k,b in self.window.buttons.items()}
        self.window._tick()
        self.assertEqual(self.window.buttons['hot'].options['state'],'normal')
        self.settle()
        self.assertEqual(before,{k:b.state_writes for k,b in self.window.buttons.items()})

    def test_one_click_during_refresh_waits_for_verified_read_then_dispatches_once(self):
        self.fresh(); self.window._tick()
        self.window.submit('promote',target='hot'); self.window.submit('promote',target='hot')
        self.assertEqual(len(self.jobs),1)
        self.assertIsNotNone(self.window.pending_action)
        self.assertEqual(self.window.buttons['hot'].options['state'],'disabled')
        self.settle()
        self.assertEqual(len(self.jobs),2)
        self.assertEqual(self.scene.requests.events(),())
        self.settle()
        self.assertEqual(len(self.scene.requests.events()),1)

    def test_queued_click_is_cancelled_when_refresh_fails(self):
        self.fresh(); self.window._tick(); self.window.submit('promote',target='hot')
        with patch.object(self.scene.controls,'snapshot',side_effect=OSError()): self.settle()
        self.assertIsNone(self.window.pending_action)
        self.assertEqual(len(self.jobs),1)
        self.assertEqual(self.scene.requests.events(),())
        self.assertIn('not sent',self.window.action_text.options['text'])

    def test_delayed_refresh_disables_edits_and_close_cancels_unsent_click(self):
        self.fresh(); self.window._tick(); self.window.submit('promote',target='hot')
        self.assertIsNotNone(self.window.pending_action)
        self.window.started-=4
        self.window._tick()
        self.assertFalse(self.model.fresh)
        self.assertIsNone(self.window.pending_action)
        self.assertEqual(self.window.buttons['hot'].options['state'],'disabled')
        self.window.close()
        self.assertIsNone(self.window.pending_action)
        self.assertEqual(self.scene.requests.events(),())

    def test_submit_captures_symbol_reason_and_one_command_before_worker_dispatch(self):
        self.fresh(); self.window.submit('promote',target='hot')
        self.window.reason.value='changed'; self.window.symbol.value='AAPL'
        self.window.submit('promote',target='hot')
        self.assertEqual(len(self.jobs),1); self.settle()
        event=self.scene.requests.events()[0]
        self.assertEqual(event.payload['symbols'],('MSFT',)); self.assertEqual(event.payload['reason'],'Operator reason')

    def test_withdraw_selects_only_bound_own_request(self):
        cid=self.scene.controls.submit('promote',symbol='MSFT',target='hot')
        self.fresh(); self.window.table.selection_set(cid); self.window.withdraw()
        self.window.reason.value='changed'; self.settle()
        e=self.scene.requests.events()[-1]
        self.assertEqual(e.payload['owner_id'],self.scene.actor); self.assertEqual(e.payload['request_id'],cid)
        self.assertEqual(e.payload['reason'],'Operator reason')

    def test_demotion_uses_selected_request_and_keeps_actor_fixed(self):
        cid=self.scene.controls.submit('promote',symbol='MSFT',target='hot')
        self.fresh(); self.window.table.selection_set(cid); self.window.demote('focus'); self.settle()
        self.assertEqual(self.scene.requests.events()[-1].payload['request_id'],cid)
        self.assertTrue(all(e.actor_id==self.scene.actor for e in self.scene.requests.events()))

    def test_unprivileged_limit_buttons_are_disabled(self):
        self.fresh()
        for k in ('limit_focus','limit_uni','clear_limit'): self.assertEqual(self.window.buttons[k].options['state'],'disabled')
        self.assertEqual(self.window.buttons['hot'].options['state'],'normal')

    def test_retry_recovers_saved_command_instead_of_creating_another(self):
        from test_manual_membership import interrupted
        with self.assertRaises(RuntimeError): self.scene.controls.submit('promote',symbol='MSFT',target='hot',
            command_id='pending',fault_hook=interrupted('after_requested'))
        self.fresh(); self.window.table.selection_set('pending'); self.window.retry(); self.settle()
        self.assertEqual(len(self.scene.controls.snapshot()['commands']),1)
        self.assertEqual(len(self.scene.requests.events()),1)

    def test_unexpected_background_error_is_visible_and_refresh_can_continue(self):
        self.fresh(); self.window._tick()
        self.jobs[-1][1].set_exception(RuntimeError('synthetic')); self.window._tick()
        self.assertIn('UNAVAILABLE',self.window.banner.options['text'])
        self.assertIsNone(self.window.future); self.assertFalse(self.model.fresh)
        self.window._tick(); self.settle()
        self.assertTrue(self.model.fresh)

    def test_close_only_stops_window_executor_and_leaves_backend_unchanged(self):
        before={p.name:p.read_bytes() for p in self.scene.root.glob('*.sqlite3')}
        events=[]
        self.window.pool.shutdown=lambda **kw:events.append('executor')
        self.window.root.destroy=lambda:events.append('window')
        self.window.close(); self.window.close()
        self.assertEqual(events,['executor','window'])
        self.assertEqual(before,{p.name:p.read_bytes() for p in self.scene.root.glob('*.sqlite3')})

    def test_details_explain_other_source_retention(self):
        cid=self.scene.controls.submit('promote',symbol='MSFT',target='hot'); self.scene.nasdaq(); self.scene.publish()
        wid=self.scene.controls.submit('withdraw',request_id=cid); self.scene.publish()
        self.fresh(); self.window.table.selection_set(wid); self.window._details()
        self.assertIn('nasdaq-shared-daily',self.window.detail.options['text'])
