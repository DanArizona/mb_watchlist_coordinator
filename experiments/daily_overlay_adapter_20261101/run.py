"""Frozen, side-by-side read-only daily Overlay delivery."""
import argparse
from contextlib import contextmanager
from datetime import datetime,timezone,timedelta
import hashlib
import importlib.metadata
import json
from pathlib import Path
import socket
import sys
import threading
import time
import unittest
import uuid

ROOT=Path(__file__).resolve().parent
CONTRACT='daily-readonly-overlay-offline-qualification-v1'


def source_guard():
    m=json.loads((ROOT/'SOURCE_INVENTORY.json').read_text())
    for name,sha in m['files'].items():
        path=ROOT/name
        if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest()!=sha:
            raise ValueError('Delivered source differs: '+name)
    return m


def paths():
    sys.path[:0]=[str(ROOT/'coordinator'/'src'),str(ROOT/'coordinator'/'tests'),
        str(ROOT/'market_data'/'src'),str(ROOT/'market_data')]


@contextmanager
def no_network():
    original=(socket.socket.connect,socket.create_connection)
    def denied(*a,**k):raise AssertionError('Offline Overlay checks deny all network connections')
    socket.socket.connect=socket.create_connection=denied
    try:yield
    finally:socket.socket.connect,socket.create_connection=original


def new_run(kind):
    p=ROOT/'runs'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_'+kind+'_'+uuid.uuid4().hex[:8])
    p.mkdir(parents=True,exist_ok=False)
    return p


def versions():
    return {name:importlib.metadata.version(name) for name in ('dash','plotly','Flask','Werkzeug')}


def verify(manifest):
    root=new_run('verify');start=time.monotonic()
    with no_network():
        suite=unittest.defaultTestLoader.loadTestsFromNames([
            'test_daily_overlay','test_daily_overlay_view','test_daily_overlay_cli',
            'tests.test_observation_overlay','tests.test_observation_overlay_view','tests.test_overlay_halts'])
        result=unittest.TextTestRunner(verbosity=2).run(suite)
    source_guard()
    good=result.wasSuccessful() and result.testsRun==manifest['expected_tests'] and not result.skipped
    report={'contract':CONTRACT,'result':'PASS' if good else 'FAILED','tests':result.testsRun,
        'passed':result.testsRun-len(result.failures)-len(result.errors)-len(result.skipped),
        'failures':len(result.failures),'errors':len(result.errors),'skipped':len(result.skipped),
        'failed_tests':[t.id() for t,_ in result.failures+result.errors],
        'seconds':time.monotonic()-start,'platform':sys.platform,'python':list(sys.version_info[:3]),
        'versions':versions(),'source':manifest['source'],
        'source_inventory_sha256':hashlib.sha256((ROOT/'SOURCE_INVENTORY.json').read_bytes()).hexdigest(),
        'windows_checks_passed':good and sys.platform=='win32',
        'focused_adapter_cli_and_dash_transport_checks':58,'existing_overlay_regression_checks':39,
        'actual_dash_layout_and_callback_transport':True,'actual_browser_preview_executed':False,
        'network':'denied','actual_vault_access':False,'actual_provider_used':False,
        'production_changes':False,'membership_writes':False,'process_control':False,
        'p85_or_p94_packet_changed':False,'controller_collector_or_policy_changed':False,
        'full_native_audit_replaced':False,'unrecorded_slot_coverage_assessed':False,
        'full_day_viewer_performance_qualified':False,'full_day_provider_capacity_qualified':False,
        'clock_scope':'Logical future session in synthetic fixtures only; real reader/view use actual UTC',
        'qualification_scope':'Read-only native/source/candle adaptation, knowledge times, failure retention, existing chart, Dash callback transport, loopback display lifecycle',
        'remaining':['Actual Windows qualification and returned CMD prompt','Inspect the synthetic browser preview; it stays open until stopped','Read-only attachment to a dated running session and longer-session view behavior']}
    (root/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2));print('Saved report: '+str(root/'verification.json'))
    return 0 if good else 1


def preview(args):
    from test_daily_overlay import OverlayScene
    from mb_watchlist_coordinator.daily_overlay import DailyOverlayReader,DailyOverlayModel
    from mb_watchlist_coordinator.daily_overlay_cli import serve
    from mb_market_data.observation_overlay import ObservationOverlayOHLCVCache,OverlayCandle,write_observation_overlay_cache
    root=new_run('preview');scene=OverlayScene(root/'synthetic')
    stop=threading.Event();phases=[];errors=[]
    saved=(scene.state_root/'session.json').read_bytes()
    def cache(symbol):
        start=scene.start
        value=ObservationOverlayOHLCVCache(symbol,scene.now.date(),'Schwab','SYNTHETIC preview; no provider',
            scene.now-timedelta(seconds=1),start-timedelta(hours=1),start+timedelta(hours=7),'a'*64,
            tuple(OverlayCandle(symbol,start+timedelta(minutes=5*n),10+n/2,11+n/2,9+n/2,10.5+n/2,100+n*50) for n in range(3)))
        write_observation_overlay_cache(root/'candles'/(symbol+'.json'),value)
    scene.source();scene.capture(raw=b'<rss><channel></channel></rss>')
    scene.quote_value(channel='uni');scene.quote_value(channel='focus');cache('MSFT')
    reader=DailyOverlayReader(scene.state_root,candle_directory=root/'candles',clock=lambda:scene.now)
    model=DailyOverlayModel(reader)
    def mark(name):
        phases.append(name);print(json.dumps({'synthetic_preview_phase':name,'provider_requests':0}),flush=True)
    def progress():
        try:
            mark('opening_membership_and_saved_candles')
            if stop.wait(6):return
            scene.now+=timedelta(seconds=60);scene.add('NVDA');scene.capture();scene.controller();scene.source_status()
            scene.quote_value(channel='hot');mark('NVDA_added_to_Hot_Focus_Uni_quote_without_candles')
            if stop.wait(10):return
            scene.now+=timedelta(seconds=60);scene.capture(resume='09:55:00');scene.controller();scene.source_status()
            scene.quote_value(channel='hot');cache('NVDA');mark('resumption_knowledge_and_saved_candles_arrive')
            if stop.wait(10):return
            (scene.state_root/'session.json').write_text('{}');mark('read_failure_last_verified_chart')
            if stop.wait(16):return
            (scene.state_root/'session.json').write_bytes(saved)
            scene.controller(stop={'at_utc':scene.now.isoformat(),'reason':'operator_stop'})
            mark('stopped_controller_membership_and_chart_retained')
            print('Preview complete. Inspect as long as needed; Stop display or Ctrl+C ends only this viewer.',flush=True)
        except BaseException as e:
            errors.append(type(e).__name__);print('Synthetic preview error: '+type(e).__name__,flush=True)
    thread=threading.Thread(target=progress,name='synthetic-overlay-preview',daemon=True);thread.start()
    try:
        serve(model,symbol='MSFT',port=args.port,open_browser=not args.no_browser,stop_event=stop,
            banner_note='SYNTHETIC PREVIEW — fixture session/clock, no credentials, API or production access')
    finally:
        stop.set();thread.join(timeout=2)
        report={'contract':'daily-overlay-synthetic-browser-preview-v1','result':'STOPPED' if not errors else 'FAILED',
            'synthetic_only':True,'phases':phases,'errors':errors,'browser_open_requested':not args.no_browser,
            'preview_kept_open_until_operator_stop':True,'actual_provider_used':False,'production_access':False,
            'viewer_thread_stopped':not thread.is_alive(),'clock_scope':'Trusted synthetic fixture clock only',
            'no_real_process_control':True}
        (root/'preview-result.json').write_text(json.dumps(report,indent=2)+'\n')
        print('Saved preview result: '+str(root/'preview-result.json'))
    return 1 if errors else 0


def main(argv=None):
    paths();manifest=source_guard()
    args=list(sys.argv[1:] if argv is None else argv)
    if args==['verify']:return verify(manifest)
    if args and args[0]=='preview':
        p=argparse.ArgumentParser();p.add_argument('--port',type=int,default=8056);p.add_argument('--no-browser',action='store_true')
        parsed=p.parse_args(args[1:])
        if not 0<=parsed.port<=65535:p.error('Invalid loopback port')
        return preview(parsed)
    from mb_watchlist_coordinator.daily_overlay_cli import main as readonly
    return readonly(args)


if __name__=='__main__':raise SystemExit(main())
