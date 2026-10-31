"""Actual Tk preview over synthetic shared broker-identity ledgers."""
import time


def gui_proof(folder,*,preview_hold_seconds=15):
    from daily_manual_fixture import CombinedFixture
    from mb_watchlist_coordinator.operating_plan import BROKER_MANUAL_PROFILE
    from mb_watchlist_coordinator.manual_membership import ManualMembershipModel
    from mb_watchlist_coordinator.manual_membership_window import ManualMembershipWindow
    fixture=CombinedFixture(profile=BROKER_MANUAL_PROFILE,root=folder/'gui',universe_size=4)
    controls=fixture.session.manual
    window=ManualMembershipWindow(ManualMembershipModel(controls),interval_ms=150,
        title='OFFLINE synthetic manual broker identity — 15-second completed preview')
    phases,errors=[],[];started=time.monotonic();hold=None;auto_closed=False
    first=second=None;hidden=controls.path.with_suffix('.held')
    tk_version=str(window.root.tk.call('info','patchlevel'))

    def advance():
        nonlocal first,second,hold,auto_closed
        try:
            if hold is not None:
                remaining=preview_hold_seconds-(time.monotonic()-hold)
                if remaining<=0:auto_closed=True;window.close();return
                window.action_text.configure(text=f'Outside-Uni proof complete — closes in {remaining:.0f} seconds. You may close it now.')
            elif time.monotonic()-started>25:raise AssertionError('Manual identity GUI phase deadline exceeded')
            value=window.last_value
            if window.future is None and value is not None:
                rows=value.get('commands',[]);by_id={r['command_id']:r for r in rows}
                if not phases and value.get('fresh')and not rows:
                    phases.append('verified_empty');window.symbol.set('X000');window.submit('promote',target='hot')
                elif len(phases)==1 and rows and rows[-1]['status']=='PENDING':
                    assert not fixture.case.calls
                    first=rows[-1]['command_id'];phases.append('outside_request_pending_no_provider_in_gui')
                    window.table.selection_set(first);window.withdraw()
                elif len(phases)==2 and by_id.get(first,{}).get('status')=='WITHDRAWN':
                    fixture.pump();assert not fixture.case.calls
                    phases.append('pending_withdrawal_no_broker_dispatch')
                    window.symbol.set('X001');window.submit('promote',target='hot')
                elif len(phases)==3 and rows[-1]['symbol']=='X001'and rows[-1]['status']=='PENDING':
                    second=rows[-1]['command_id'];phases.append('second_outside_request_pending')
                    fixture.pump();fixture.publish()
                elif len(phases)==4 and by_id.get(second,{}).get('status')=='EFFECTIVE':
                    assert fixture.case.calls==[['X001']]
                    phases.append('broker_confirmed_native_effective_hot')
                    fixture.queue_nasdaq(['X001']);fixture.advance();fixture.pump();fixture.publish()
                    window.table.selection_set(second);window.withdraw()
                elif len(phases)==5 and by_id.get(second,{}).get('status')=='WITHDRAWN':
                    row=by_id[second]
                    assert row['effective_group']=='hot'and'nasdaq-shared-daily'in row.get('other_sources',[])
                    assert fixture.case.calls==[['X001']]
                    phases.append('own_withdrawal_retains_nasdaq_hot_without_another_lookup')
                    controls.path.rename(hidden)
                elif len(phases)==6 and not value.get('fresh')and value.get('last_verified'):
                    assert all(str(b.cget('state'))=='disabled'for b in window.buttons.values())
                    phases.append('read_failure_retains_feedback_and_disables_edits');hidden.rename(controls.path)
                elif len(phases)==7 and value.get('fresh'):
                    phases.append('read_recovered_without_queue_or_budget_reset');hold=time.monotonic()
            if not window.closed:window.root.after(30,advance)
        except Exception as error:
            errors.append(type(error).__name__+': '+str(error));window.close()

    window.root.after(30,advance)
    try:window.run()
    finally:
        window.close();window.pool.shutdown(wait=True,cancel_futures=True)
        if hidden.exists()and not controls.path.exists():hidden.rename(controls.path)
        fixture.close()
    return {'result':'PASS'if len(phases)==8 and not errors else'FAILED','actual_tk_window':True,
        'tk_version':tk_version,'observed_phases':phases,'errors':errors,'auto_closed':auto_closed,
        'executor_stopped':True,'synthetic_only':True,'preview_hold_seconds':preview_hold_seconds,
        'completed_display_visible_seconds':time.monotonic()-hold if hold is not None else None,
        'synthetic_identity_calls':len(fixture.case.calls),'actual_provider_requests':0,'production_access':False}
