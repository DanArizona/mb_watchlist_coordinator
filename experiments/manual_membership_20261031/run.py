"""Short offline qualification and an isolated interactive manual-controls preview."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import socket
import sys
import time
import unittest
from uuid import uuid4

ROOT = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path[:0] = [str(ROOT/'coordinator/src'),str(ROOT/'market_data/src'),str(ROOT/'coordinator/tests')]
CHECKS = 58


def guard():
    manifest=json.loads((ROOT/'SOURCE_INVENTORY.json').read_text())
    if manifest['contract']!='manual-membership-candidate-source-v1':
        raise ValueError('Exact manual candidate source inventory required')
    for name,expected in manifest['files'].items():
        p=ROOT/name
        if p.is_symlink() or hashlib.sha256(p.read_bytes()).hexdigest()!=expected:
            raise ValueError('Candidate source bytes differ')
    return manifest


def deny_network():
    def denied(*args,**kwargs): raise OSError('Offline manual candidate: network denied')
    socket.socket.connect=socket.socket.connect_ex=socket.create_connection=socket.getaddrinfo=denied


def new_root(kind):
    root=ROOT/'runs'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ_')+kind+'_'+uuid4().hex[:8])
    root.mkdir(parents=True,exist_ok=False)
    return root


def gui_proof(folder, *, preview_hold_seconds=15):
    from manual_membership_fixture import ManualScene
    from mb_watchlist_coordinator.manual_membership import ManualMembershipModel
    from mb_watchlist_coordinator.manual_membership_window import ManualMembershipWindow
    scene=ManualScene(folder/'gui',actor='operator:masterbot',privileged=True)
    model=ManualMembershipModel(scene.controls)
    window=ManualMembershipWindow(model,title='OFFLINE SYNTHETIC manual membership — auto-closing proof',interval_ms=100)
    tk_version=str(window.root.tk.call('info','patchlevel'))
    window.symbol.set('MSFT')
    phases,errors=[],[]
    began=time.monotonic(); hidden=scene.controls.path.with_suffix('.held')
    hold_started=None; auto_closed=False
    requested=lowered=limit=None

    def advance():
        nonlocal requested,lowered,limit,hold_started,auto_closed
        try:
            if hold_started is None and time.monotonic()-began>25: raise AssertionError('GUI phase deadline exceeded')
            if hold_started is not None:
                remaining=preview_hold_seconds-(time.monotonic()-hold_started)
                if remaining<=0:
                    auto_closed=True; window.close(); return
                window.action_text.configure(text=f'Preview complete — closes in {remaining:.0f} seconds. You can also close it now.')
            value=window.last_value
            if window.future is None and value is not None:
                rows=value.get('commands',[])
                if not phases and value.get('fresh') and not rows:
                    phases.append('verified_empty'); window.submit('promote',target='hot')
                elif len(phases)==1 and rows and rows[-1]['status']=='PENDING':
                    requested=rows[-1]['command_id']; phases.append('requested_pending'); scene.publish()
                elif len(phases)==2 and rows[-1]['status']=='EFFECTIVE':
                    phases.append('effective_hot'); window.table.selection_set(requested); window.demote('focus')
                elif len(phases)==3 and rows[-1]['action']=='demote' and rows[-1]['status']=='PENDING':
                    lowered=rows[-1]['command_id']; phases.append('own_demotion_pending'); scene.advance(130); scene.publish()
                elif len(phases)==4 and rows[-1]['status']=='EFFECTIVE' and rows[-1]['effective_group']=='focus':
                    phases.append('effective_focus'); window.submit('limit',target='uni')
                elif len(phases)==5 and rows[-1]['action']=='limit' and rows[-1]['status']=='PENDING':
                    limit=rows[-1]['command_id']; phases.append('privileged_limit_pending'); scene.publish()
                elif len(phases)==6 and rows[-1]['status']=='EFFECTIVE' and rows[-1]['effective_group']=='uni':
                    phases.append('effective_limit'); scene.controls.path.rename(hidden)
                elif len(phases)==7 and not value.get('fresh') and value.get('last_verified'):
                    if not all(str(b.cget('state'))=='disabled' for b in window.buttons.values()):
                        raise AssertionError('Read error left edits enabled')
                    phases.append('read_error_retains_feedback_and_disables_edits'); hidden.rename(scene.controls.path)
                elif len(phases)==8 and value.get('fresh'):
                    phases.append('read_recovered_without_reset'); hold_started=time.monotonic()
            if not window.closed: window.root.after(30,advance)
        except Exception as error:
            errors.append(type(error).__name__+': '+str(error)); window.close()

    window.root.after(30,advance)
    try: window.run()
    finally:
        window.close(); window.pool.shutdown(wait=True,cancel_futures=True)
        if hidden.exists() and not scene.controls.path.exists(): hidden.rename(scene.controls.path)
    return {'result':'PASS' if len(phases)==9 and not errors else 'FAILED','actual_tk_window':True,
        'tk_version':tk_version, 'observed_phases':phases,
        'errors':errors,'auto_closed':auto_closed,'executor_stopped':True,'synthetic_only':True,
        'preview_hold_seconds':preview_hold_seconds,
        'completed_display_visible_seconds':time.monotonic()-hold_started if hold_started is not None else None,
        'logical_clock_advanced_for_demotion_hold':True,'provider_requests':0,'production_access':False}


def verify(manifest):
    from manual_membership_fixture import ManualScene
    from mb_market_data.quote_journal_audit import audit_quote_journal
    root=new_root('verify'); began=time.monotonic()
    print('OFFLINE manual membership candidate: synthetic ledgers/journals only; no password, API or production changes.',flush=True)
    print('58 focused checks. Windows also opens an automatic synthetic GUI proof with a 15-second display hold; allow about 30 seconds.',flush=True)
    suite=unittest.defaultTestLoader.loadTestsFromNames(['test_manual_membership','test_manual_membership_window'])
    if suite.countTestCases()!=CHECKS: raise ValueError('Focused test count differs')
    class Log:
        def __init__(self,out): self.out=out
        def write(self,value): self.out.write(value); sys.stdout.write(value)
        def flush(self): self.out.flush(); sys.stdout.flush()
    with (root/'tests.log').open('w',encoding='utf-8') as output:
        result=unittest.TextTestRunner(stream=Log(output),verbosity=2).run(suite)
    scene=ManualScene(root/'native-proof',actor='operator:masterbot',privileged=True)
    cid=scene.controls.submit('promote',symbol='MSFT',target='hot'); scene.publish()
    scene.nasdaq(); scene.publish()
    lower=scene.controls.submit('demote',request_id=cid,target='focus'); scene.publish()
    cap=scene.controls.submit('limit',symbol='MSFT',target='uni'); scene.publish()
    held=scene.controls.snapshot()
    scene.controls.submit('clear_limit',symbol='MSFT',request_id=cap); scene.publish()
    scene.controls.submit('withdraw',request_id=lower+':replacement'); scene.publish()
    scene.reopen(); proof=scene.controls.snapshot()
    (root/'manual-feedback.json').write_text(json.dumps(proof,indent=2)+'\n')
    audit=audit_quote_journal(scene.store.database_path)
    gui={'result':'NOT_EXERCISED','reason':'No local desktop; actual Windows GUI proof remains due'}
    if result.wasSuccessful() and (os.name=='nt' or os.environ.get('DISPLAY')):
        try: gui=gui_proof(root)
        except Exception as error: gui={'result':'FAILED','error_type':type(error).__name__,'detail':str(error)}
    guard()
    native_ok=audit.passed and proof['members']['hot']==['MSFT'] and held['members']['hot']==[]
    passed=result.wasSuccessful() and not result.skipped and native_ok and (os.name!='nt' or gui['result']=='PASS')
    report={'contract':'manual-membership-candidate-offline-qualification-v1','result':'PASS' if passed else 'FAILED',
        'tests':result.testsRun,'passed':result.testsRun-len(result.failures)-len(result.errors)-len(result.skipped),
        'failures':len(result.failures),'errors':len(result.errors),'skipped':len(result.skipped),
        'failed_tests':[t.id() for t,_ in result.failures+result.errors], 'seconds':time.monotonic()-began,
        'platform':sys.platform,'python':list(sys.version_info[:3]),'windows_checks_passed':bool(passed and os.name=='nt'),
        'source':manifest['source'],'source_inventory_sha256':hashlib.sha256((ROOT/'SOURCE_INVENTORY.json').read_bytes()).hexdigest(),
        'manual_actions':['request_focus','request_hot','demote_own_request_to_focus_or_uni','withdraw_own_request',
                          'privileged_limit','clear_selected_privileged_limit'],
        'feedback':['requested','pending','effective','blocked_restricted','withdrawn','other_source_demand','policy_holds'],
        'native_proof':{'native_audit_passed':audit.passed,'effective_revision':proof['effective_revision'],
            'nasdaq_hot_demand_survives_own_demotion_and_withdrawal':proof['members']['hot']==['MSFT'],
            'privileged_limit_removed_hot_while_retaining_demand':held['members']['hot']==[],
            'restart_feedback_reconstructed':True,'quote_acquisitions':0},
        'gui_proof':gui,'network':'denied','actual_vault_access':False,'actual_provider_used':False,
        'production_changes':False,'p85_source_or_approval_changed':False,'daily_controller_changed':False,
        'promotion_scope':'verified opening Uni only; outside-Uni manual broker admission is not bypassed',
        'production_manual_launch_available':False,'automatic_controller_process_integration_qualified':False,
        'clock_scope':'Logical future session in synthetic fixture only; real UI/read/SQLite operations',
        'unchanged_hot_capacity_provider_recovery_proofs_repeated':False,
        'remaining':['Windows qualification and actual returned CMD prompt',
            'Reviewed manual-enabled daily composition, outside-Uni identity integration and affected controller qualification']}
    (root/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2)); print('Saved report:',root/'verification.json',flush=True)
    return 0 if passed else 1


def preview():
    from manual_membership_fixture import ManualScene
    from mb_watchlist_coordinator.manual_membership import ManualMembershipModel
    from mb_watchlist_coordinator.manual_membership_window import ManualMembershipWindow
    root=new_root('preview')
    scene=ManualScene(root/'synthetic',actor='operator:masterbot',privileged=True)
    scene.nasdaq()
    window=ManualMembershipWindow(ManualMembershipModel(scene.controls),
        title='OFFLINE SYNTHETIC manual controls — MSFT has simulated Nasdaq demand')
    window.symbol.set('MSFT')
    previous=time.monotonic()
    def publish():
        nonlocal previous
        if window.closed: return
        at=time.monotonic(); scene.advance(at-previous); previous=at
        try: scene.service.cycle()
        except Exception as error:
            from mb_watchlist_coordinator.sampling_service import ServiceBusy
            if not isinstance(error,ServiceBusy):
                window.action_text.configure(text='Synthetic publisher: '+type(error).__name__)
        if not window.closed: window.root.after(250,publish)
    window.root.after(250,publish)
    print('Synthetic preview only. MSFT has a simulated Nasdaq Hot request; AAPL and SPY are also available.',flush=True)
    print('Only files under',root,'are used. Closing this window ends the preview.',flush=True)
    try: window.run()
    finally: window.close(); window.pool.shutdown(wait=True,cancel_futures=True)
    return 0


def main(argv):
    manifest=guard(); deny_network()
    if argv==['verify']: return verify(manifest)
    if argv==['preview']: return preview()
    if argv==['preview15']:
        root=new_root('preview15')
        print('OFFLINE GUI preview only. Completed display stays open for 15 seconds; the 54 accepted checks are not repeated.',flush=True)
        result=gui_proof(root)
        (root/'preview.json').write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps(result,indent=2)); print('Saved preview:',root/'preview.json',flush=True)
        return 0 if result['result']=='PASS' else 1
    raise ValueError('Use verify, preview or preview15; no production attachment entry is exposed')


if __name__=='__main__':
    try: raise SystemExit(main(sys.argv[1:]))
    except Exception as error:
        print('Manual candidate refused:',type(error).__name__,str(error),flush=True)
        raise SystemExit(1)
