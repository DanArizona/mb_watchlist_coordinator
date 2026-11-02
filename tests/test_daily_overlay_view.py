"""Exercise the real Dash layout/callback transport, not a mocked GUI."""
import json
import unittest
from unittest.mock import Mock, patch
import test_daily_overlay as fixtures
from mb_watchlist_coordinator.daily_overlay_view import create_daily_overlay_dashboard, status_text


class DailyOverlayViewTests(unittest.TestCase):
    def setUp(self):
        self.case=fixtures.DailyOverlayTests();self.case.setUp();self.addCleanup(self.case.doCleanups)
        self.case.scene.quote_value()
        self.stop=Mock()
        self.app=create_daily_overlay_dashboard(self.case.model,initial_symbol='NVDA',request_display_stop=self.stop)
        self.client=self.app.server.test_client()

    def refresh(self,symbol='NVDA'):
        key=next(k for k in self.app.callback_map if 'daily-banner.children' in k)
        callback=self.app.callback_map[key]
        values={'daily-refresh.n_intervals':1,'daily-symbol.value':symbol,'daily-theme.value':'dark',
            'daily-off-hours.value':[],'observation-overlay-units.value':'percent',
            'observation-overlay-reference.data':None,'daily-detailed-hover.value':[],
            'observation-overlay-shift-hover.data':False,'observation-overlay-chart.relayoutData':None}
        for group in ('uni','focus','hot'):
            values['observation-overlay-'+group+'-size.value']='standard'
            values['observation-overlay-'+group+'-opacity.value']=100
        inputs=[dict(i,value=values[i['id']+'.'+i['property']]) for i in callback['inputs']]
        states=[dict(i,value=None) for i in callback['state']]
        outputs=[{'id':o.component_id,'property':o.component_property} for o in callback['output']]
        result=self.client.post('/_dash-update-component',json={'output':key,'outputs':outputs,
            'inputs':inputs,'state':states,'changedPropIds':['daily-refresh.n_intervals']})
        self.assertEqual(result.status_code,200,result.data.decode())
        return result.get_json()['response']

    def test_actual_dash_layout_has_monitor_chart_alerts_and_no_membership_edit_actions(self):
        self.assertEqual(self.client.get('/').status_code,200)
        layout=self.client.get('/_dash-layout');self.assertEqual(layout.status_code,200)
        text=layout.data.decode()
        for item in ('Monitor','Chart','Alerts','Hot — complete current list','Focus — additions since r1','Uni — additions since r1'):
            self.assertIn(item,json.dumps(layout.get_json(),ensure_ascii=False))
        for forbidden in ('Promote','Withdraw request','Start collector','Password'):
            self.assertNotIn(forbidden,text)

    def test_actual_callback_renders_existing_chart_from_selected_native_quote(self):
        r=self.refresh()
        self.assertIn('VERIFIED',r['daily-banner']['children'])
        traces=r['observation-overlay-chart']['figure']['data']
        hot=next(t for t in traces if t.get('name')=='Hot quote')
        self.assertEqual(hot['y'],[12.5])
        self.assertEqual(r['observation-overlay-chart']['figure']['layout']['height'],800)

    def test_failed_refresh_retains_chart_and_labels_all_saved_health(self):
        self.refresh();(self.case.scene.state_root/'session.json').write_text('{}')
        r=self.refresh()
        self.assertIn('LAST VERIFIED',r['daily-banner']['children'])
        self.assertIn('LAST VERIFIED',r['daily-health']['children'])
        self.assertTrue(r['observation-overlay-chart']['figure']['data'])

    def test_failed_new_symbol_does_not_relabel_previous_symbols_chart(self):
        self.refresh();r=self.refresh('UNPUBLISHED')
        self.assertIn('UNAVAILABLE',r['daily-banner']['children'])
        self.assertFalse(r['observation-overlay-chart']['figure']['data'])

    def test_confirmed_facts_display_actual_event_and_separate_knowledge_times(self):
        self.case.scene.source();self.case.scene.capture()
        r=self.refresh();text=json.dumps(r['daily-facts'],ensure_ascii=False)
        self.assertIn('halt ',text);self.assertIn('known ',text);self.assertIn('resume not known',text)

    def test_source_read_failure_is_visible_in_monitor_without_opening_alerts(self):
        self.case.scene.source();self.case.scene.capture();self.refresh()
        (self.case.scene.state_root/'daily-source-ready.json').write_text('{}')
        r=self.refresh();self.assertIn('Source evidence UNAVAILABLE',r['daily-health']['children'])
        self.assertIn('LAST VERIFIED SOURCE FACTS',json.dumps(r['daily-facts']))

    def test_recorded_health_does_not_claim_os_process_ownership(self):
        self.case.scene.controller(age=4)
        r=self.refresh();self.assertIn('STALE',r['daily-health']['children'])
        self.assertIn('saved',r['daily-health']['children'])

    def test_reading_or_changing_tabs_does_not_call_display_stop(self):
        self.client.get('/_dash-layout');self.refresh();self.stop.assert_not_called()

    def test_tab_navigation_keeps_refresh_controls_mounted_without_reading_again(self):
        from dash import dcc
        tabs=next(x for x in self.app.layout.children if isinstance(x,dcc.Tabs))
        self.assertTrue(all(x.children is None for x in tabs.children))
        self.assertTrue({'daily-pane-monitor','daily-pane-chart','daily-pane-alerts'} <=
            {getattr(x,'id',None) for x in self.app.layout.children})
        key=next(k for k in self.app.callback_map if 'daily-pane-monitor.style' in k)
        cb=self.app.callback_map[key]
        with patch.object(self.case.model,'refresh',side_effect=AssertionError('navigation must not read/rebuild')):
            r=self.client.post('/_dash-update-component',json={'output':key,
                'outputs':[{'id':o.component_id,'property':o.component_property} for o in cb['output']],
                'inputs':[{'id':'daily-tab','property':'value','value':'chart'}],
                'state':[],'changedPropIds':['daily-tab.value']})
        self.assertEqual(r.status_code,200)
        self.assertEqual(r.get_json()['response']['daily-pane-chart']['style'],{'display':'block'})
        self.assertEqual(r.get_json()['response']['daily-pane-monitor']['style'],{'display':'none'})

    def test_stop_button_only_routes_to_injected_display_stop(self):
        key='daily-stop-result.children';cb=self.app.callback_map[key]
        with patch('mb_watchlist_coordinator.daily_overlay_view.Timer') as timer:
            r=self.client.post('/_dash-update-component',json={'output':key,
                'outputs':{'id':'daily-stop-result','property':'children'},
                'inputs':[{'id':'daily-stop-display','property':'n_clicks','value':1}],
                'state':[],'changedPropIds':['daily-stop-display.n_clicks']})
            self.assertEqual(r.status_code,200);timer.assert_called_once_with(.25,self.stop)
            timer.return_value.start.assert_called_once()
        self.stop.assert_not_called()


if __name__=='__main__':unittest.main()
