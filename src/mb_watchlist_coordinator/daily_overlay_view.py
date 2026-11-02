"""Local read-only daily view using the existing Overlay chart and controls."""
from datetime import datetime
from threading import Timer


def status_text(result):
    """Keep saved membership, current process evidence and read success distinct."""
    s=result.snapshot
    if s is None:
        return {'banner':'OVERLAY UNAVAILABLE — waiting for verified daily records',
                'health':'Controller/collection status unavailable',
                'warnings':['Read unavailable: '+str(result.error)], 'facts':[]}
    h=s.membership['controller']
    prefix='' if result.fresh else 'LAST VERIFIED — '
    warnings=[]
    if not result.fresh: warnings.append('Current read failed: '+str(result.error))
    if h['state'] not in ('RUNNING','RUNNING_WITH_SOURCE_GAPS'):
        warnings.append('Controller '+h['state']+': '+h['detail'])
    if not s.source['fresh']:
        warnings.append('Nasdaq source unavailable: '+str(s.source['error']))
        if s.source.get('last_verified_at_utc'):
            warnings.append('Halt facts are LAST VERIFIED at '+s.source['last_verified_at_utc'])
    elif s.source.get('progress')=='STALE': warnings.append('Saved source status is stale')
    warnings.extend(s.source['known_gaps'])
    warnings.extend(h['alerts'])
    if s.candles['state']!='AVAILABLE': warnings.append('Candles '+s.candles['state']+': '+s.candles['detail'])
    if s.coverage['recorded_skip_count']: warnings.append(str(s.coverage['recorded_skip_count'])+' recorded skipped slots; see saved coverage')
    if s.coverage['missing_cadence_runs']: warnings.append('Some recorded quote cadences are unavailable')
    return {'banner':prefix+('NATIVE MEMBERSHIP / QUOTES VERIFIED' if s.membership['state']=='READY' else 'WAITING FOR OPENING MEMBERSHIP'),
        'health':prefix+'Controller '+h['state']+' | Collector (saved) '+h['worker']+
            ' | Source evidence '+s.source['state']+' | Candles '+s.candles['state'],
        'warnings':list(dict.fromkeys(warnings)), 'facts':s.source['facts']}


def create_daily_overlay_dashboard(model, *, initial_symbol=None, request_display_stop=None,banner_note=None):
    from dash import Dash, dcc, html, Input, Output, State, no_update, ctx
    import plotly.graph_objects as go
    from mb_market_data.quote_dashboard import ASSETS_DIRECTORY, _overlay_channel_control, _overlay_point_style
    from mb_market_data.observation_overlay_view import (build_observation_overlay_figure,
        resolve_reference, resolve_overlay_time_viewport, selected_reference_from_click)
    app=Dash(__name__,assets_folder=str(ASSETS_DIRECTORY),title='Daily Hot Overlay — read-only')
    first=model.refresh(initial_symbol);selected=first.snapshot.overlay.symbol if first.snapshot else initial_symbol
    initial_options=first.snapshot.membership['symbols'] if first.snapshot else []
    def group(k,label):
        return html.Section([html.H3(label),html.Div(id='daily-'+k)],style={'flex':'1','minWidth':'220px'})
    app.layout=html.Div([
        html.H2('Daily Hot Overlay'),
        html.Strong(banner_note or ''),
        html.P('Read-only daily records · closing this display leaves collection running'),
        html.Div(id='daily-banner'),html.Div(id='daily-health'),html.Div(id='daily-as-of'),
        html.Label(['Symbol',dcc.Dropdown(id='daily-symbol',options=initial_options,value=selected,clearable=False)]),
        dcc.Interval(id='daily-refresh',interval=5000),
        dcc.Store(id='observation-overlay-reference'),dcc.Store(id='observation-overlay-reference-mode',data=False),
        dcc.Store(id='observation-overlay-shift-hover',data=False),
        dcc.Store(id='observation-overlay-viewport'),
        dcc.Tabs(id='daily-tab',value='monitor',children=[
            dcc.Tab(label='Monitor',value='monitor',children=[
                html.Div([group('hot','Hot — complete current list'),
                    group('focus','Focus — additions since r1'),group('uni','Uni — additions since r1')],
                    style={'display':'flex','gap':'20px','flexWrap':'wrap'}),
                html.H3('Confirmed Nasdaq facts and knowledge times'),html.Div(id='daily-facts'),
                html.H3('Collection evidence'),html.Pre(id='daily-coverage',style={'whiteSpace':'pre-wrap'})]),
            dcc.Tab(label='Chart',value='chart',children=[
                html.Div([
                    dcc.RadioItems(id='daily-theme',options=['dark','light'],value='dark',inline=True),
                    dcc.Checklist(id='daily-off-hours',options=[{'label':'Off-hours','value':'show'}],value=[]),
                    dcc.RadioItems(id='observation-overlay-units',options=['percent','price'],value='percent',inline=True),
                    dcc.Checklist(id='daily-detailed-hover',options=[{'label':'Detailed hover','value':'show'}],value=[]),
                    html.Button('Set 0% reference',id='observation-overlay-set-reference'),
                    html.Button('Reset reference',id='observation-overlay-reset-reference'),
                    html.Span(id='daily-reference-label'),
                    html.Div([_overlay_channel_control(html,dcc,k) for k in ('uni','focus','hot')],
                        style={'display':'flex','gap':'12px','flexWrap':'wrap'})]),
                dcc.Graph(id='observation-overlay-chart',figure=go.Figure(),style={'height':'800px'})]),
            dcc.Tab(label='Alerts',value='alerts',children=html.Ul(id='daily-alerts'))]),
        html.Button('Stop display',id='daily-stop-display',disabled=request_display_stop is None),
        html.Span(id='daily-stop-result')],id='daily-page',className='dashboard-shell theme-dark',
        style={'padding':'20px','maxWidth':'1600px','margin':'auto'})

    # dcc.Tabs mounts only its selected Tab's content. Refresh has inputs from
    # the chart controls even while Monitor is selected, so keep all panes in
    # the layout and switch their display style. Navigation never rebuilds the
    # controls, drops a callback input, or resets the current chart selection.
    tabs=next(child for child in app.layout.children if isinstance(child,dcc.Tabs))
    panes=[]
    for tab in tabs.children:
        panes.append(html.Div(tab.children,id='daily-pane-'+tab.value,
            style={'display':'block' if tab.value=='monitor' else 'none'}))
        tab.children=None
    index=app.layout.children.index(tabs)+1
    app.layout.children[index:index]=panes

    @app.callback(Output('daily-pane-monitor','style'),Output('daily-pane-chart','style'),
        Output('daily-pane-alerts','style'),Input('daily-tab','value'))
    def switch_tab(selected):
        return tuple({'display':'block' if selected==name else 'none'} for name in ('monitor','chart','alerts'))

    @app.callback(Output('observation-overlay-reference','data'),
        Output('observation-overlay-reference-mode','data'),Output('observation-overlay-set-reference','children'),
        Input('observation-overlay-set-reference','n_clicks'),Input('observation-overlay-reset-reference','n_clicks'),
        Input('observation-overlay-chart','clickData'),Input('daily-symbol','value'),
        State('observation-overlay-reference-mode','data'),State('observation-overlay-chart','figure'),
        prevent_initial_call=True)
    def choose_reference(_set,_reset,click,symbol,choosing,figure):
        trigger=ctx.triggered_id
        if trigger in ('daily-symbol','observation-overlay-reset-reference'):return None,False,'Set 0% reference'
        if trigger=='observation-overlay-set-reference':return no_update,True,'Click a candle or quote…'
        if not choosing:return no_update,False,no_update
        saved=model.last_verified.get(symbol)
        selected=selected_reference_from_click(saved.overlay,click,figure,'open') if saved else None
        return (selected,False,'Set 0% reference') if selected else (no_update,True,'Choose a candle or quote price')

    def render(result,symbol,theme,off_hours,units,reference,viewport,relayout,styles,old_options,detailed=False,shift=False):
        s=result.snapshot;text=status_text(result)
        if s is None:
            return (no_update,no_update,text['banner'],text['health'],'', ['Unavailable'],['Unavailable'],
                ['Unavailable'],[],[html.Li(t) for t in text['warnings']],'',go.Figure(),'',None,'dashboard-shell theme-'+theme)
        o=s.overlay;options=s.membership['symbols'];off=bool(off_hours and 'show' in off_hours)
        v=resolve_overlay_time_viewport(o,viewport,relayout,off_hours=off)
        f=build_observation_overlay_figure(o,theme=theme,units=units,off_hours=off,
            selected_reference=reference,viewport=v,point_styles=styles,
            detailed_hover=detailed,shift_hover=shift,
            relayout_data={k:v for k,v in (relayout or {}).items() if k.startswith('yaxis')})
        facts=[html.Li(f"{x['symbol']} {x['reason_code']} | halt {x['halt_at_utc']} | known {x['halt_known_at_utc']} | "
            f"resume {x['resumption_trade_at_utc'] or 'not known'} | resume known {x['resumption_known_at_utc'] or 'not known'} | "
            f"quote resume {x.get('resumption_quote_at_utc') or 'not known'} | quote resume known {x.get('resumption_quote_known_at_utc') or 'not known'}")
            for x in text['facts']]
        if not facts:facts=[html.P('No verified symbol-specific halt facts available at this observation time.')]
        elif not s.source['fresh']:facts.insert(0,html.Strong('LAST VERIFIED SOURCE FACTS — current source read unavailable'))
        panels=[[html.Div(row['symbol']+'  '+row['joined_at_utc']) for row in s.membership['groups'][k]] or
            [html.Div('No current Hot members' if k=='hot' else 'None added since r1')] for k in ('hot','focus','uni')]
        ref=resolve_reference(o,reference)
        label=f'0%: ${ref[0]:g} · {ref[1]}' if ref else '0% reference waits for a saved completed candle, or select a quote'
        last=s.membership['last_hot_acquisition']
        coverage=(('Last committed Hot slot: '+last['scheduled_at_utc']) if last else 'No completed Hot acquisition recorded')
        coverage+='\nRecorded skips: '+str(s.coverage['recorded_skip_count'])
        coverage+='\nCadence comes from each recorded run. Unrecorded-slot coverage is not independently assessed here.'
        coverage+='\nSelected-symbol chart; full native audit and Hot-content verification remain separate.'
        return (no_update if options==old_options else options,
            no_update if symbol==o.symbol else o.symbol,text['banner'],text['health'],
            'Session '+str(o.session_date)+' | '+o.symbol+' | '+str(o.current_band.value)+' | as of '+o.replay_time_utc.isoformat(),
            *panels,facts,[html.Li(t) for t in text['warnings']],coverage,f,label,v,'dashboard-shell theme-'+theme)

    outputs=[Output('daily-symbol','options'),Output('daily-symbol','value'),Output('daily-banner','children'),
        Output('daily-health','children'),Output('daily-as-of','children'),Output('daily-hot','children'),
        Output('daily-focus','children'),Output('daily-uni','children'),Output('daily-facts','children'),
        Output('daily-alerts','children'),Output('daily-coverage','children'),Output('observation-overlay-chart','figure'),
        Output('daily-reference-label','children'),Output('observation-overlay-viewport','data'),Output('daily-page','className')]
    @app.callback(*outputs,Input('daily-refresh','n_intervals'),Input('daily-symbol','value'),
        Input('daily-theme','value'),Input('daily-off-hours','value'),Input('observation-overlay-units','value'),
        Input('observation-overlay-reference','data'),
        *[Input('observation-overlay-'+k+'-'+field,'value') for k in ('uni','focus','hot') for field in ('size','opacity')],
        Input('daily-detailed-hover','value'),Input('observation-overlay-shift-hover','data'),
        Input('observation-overlay-chart','relayoutData'),State('observation-overlay-viewport','data'),State('daily-symbol','options'))
    def refresh(_ticks,symbol,theme,off_hours,units,reference,*rest):
        values,detailed,shift,relayout,viewport,options=rest[:6],rest[6],rest[7],rest[8],rest[9],rest[10]
        styles={k:_overlay_point_style(values[n*2],values[n*2+1]) for n,k in enumerate(('uni','focus','hot'))}
        return render(model.refresh(symbol),symbol,theme,off_hours,units,reference,viewport,
            relayout if ctx.triggered_id=='observation-overlay-chart' else None,styles,options,
            bool(detailed and 'show' in detailed),shift is True)

    if request_display_stop:
        @app.callback(Output('daily-stop-result','children'),Input('daily-stop-display','n_clicks'),prevent_initial_call=True)
        def stop(_clicks):
            Timer(.25,request_display_stop).start()
            return 'Stopping this display; collectors continue.'
    app._daily_overlay_render=render
    app._daily_overlay_model=model
    return app
