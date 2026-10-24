"""Owned synthetic fresh runtime/native quote and separate read-only reporter."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tests'),
    str(ROOT/'experiments/sampling_promotion_20261016/market_data/src'),
    str(ROOT/'experiments/authenticated_startup_20261023/reference_mb_tools/src')]
from datetime import datetime,timezone
import json
import socket
import time
def denied(*a,**kw):raise RuntimeError('Network denied in outer native runtime fixture')
socket.socket.connect=socket.socket.connect_ex=socket.create_connection=socket.getaddrinfo=denied
from mb_watchlist_coordinator.owned_process_scope import receive_gate
from mb_watchlist_coordinator.recovery_workers import atomic_json
config=json.loads(Path(sys.argv[1]).read_text());root=Path(config['root']);nonce=config['nonce']
receive_gate(sys.stdin.buffer,nonce)
if config['mode']=='report':
    from mb_watchlist_coordinator.profile_report import report_saved_profile
    try:value=report_saved_profile(root/'integrated_hot_fresh',outer_stop_path=root/'STOP.json',nonce=nonce)
    except Exception as error:
        import traceback
        atomic_json(root/'entry-failure.json',{'phase':'read_only_report','exception_type':type(error).__name__,
            'frames':[{'file':Path(f.filename).name,'function':f.name,'line':f.lineno} for f in traceback.extract_tb(error.__traceback__)]})
        raise SystemExit(70)
    atomic_json(root/'native-profile-report.json',value)
    raise SystemExit(0)
from runtime_fixtures import RuntimeFixture,ScriptedFeed
from runtime_process_evidence import subsequent_halt_snapshot
from mb_watchlist_coordinator.integrated_runtime import IntegratedRuntime
from mb_watchlist_coordinator.profile_runtime import BoundProfile
from mb_watchlist_coordinator.sampling_requests import timestamp,utc_text
# RuntimeFixture's synthetic SDK uses patch.dict(sys.modules). Modules first
# imported inside that context are removed on exit. Preload the native backend
# so the live poller and the observer keep the SAME AcquisitionBusy class.
import mb_market_data.sampling_acquisition as native_api
f=RuntimeFixture(root)
if sys.modules.get(native_api.__name__) is not native_api or not isinstance(f.session.collector.poller,native_api.IsolatedSamplingPoller):
    raise RuntimeError('Synthetic fixture changed the native module identity')
atomic_json(root/'fixture-module-identity.json',{'native_module_preserved':True})
simulation=root/'native-worker-simulation.json'
command=(sys.executable,'-I','-B',str(Path(__file__).parent/'supervised_hot_worker_probe.py'),
    str(f.target/'authenticated-worker.json'),str(simulation))
r=IntegratedRuntime(f.session,feed_client=ScriptedFeed(f.session.feed),worker_command=command)
r.initialize();p=BoundProfile(r,'ordinary')
f.realtime()
atomic_json(root/'controller-status.json',{'contract':'outer-controller-status-v1','nonce':nonce,'phase':'ACTIVE'})
atomic_json(root/'logical-clock.json',{'real':f.real.isoformat(),'logical':f.logical.isoformat()})
simulation.write_text(json.dumps({'mode':'normal','log':str(root/'native-worker-events.jsonl'),
    'real_anchor_utc':f.real.isoformat(),'logical_anchor_utc':f.logical.isoformat()}))
emitted=False;deadline=time.monotonic()+10
fixed_exceptions=[]
def trace(frame,event,arg):
    selected=frame.f_code.co_filename.endswith(('integrated_runtime.py','nasdaq_recovery_supervisor.py',
        'sampling_service.py','sampling_acquisition.py'))
    if not selected:return None
    if event=='exception':
        fixed_exceptions.append({'file':Path(frame.f_code.co_filename).name,'function':frame.f_code.co_name,
            'line':frame.f_lineno,'exception_type':arg[0].__name__})
        del fixed_exceptions[:-20]
    return trace
if config.get('trace_fixed_exceptions'):sys.settrace(trace)
try:
    while time.monotonic()<deadline and not (root/'STOP.json').exists():
        result=p.step()
        report=r.last_report or {}
        if report.get('worker',{}).get('status')=='RUNNING' and not emitted:
            baseline=f.session.live.snapshot()['receipts'][0]['snapshot']
            if f.clock()>timestamp(baseline['retrieved_at_utc']):
                f.session.live.record_snapshot(subsequent_halt_snapshot(baseline,
                    observed_at=f.clock(),capture_id='outer-owned-native-synthetic-halt'))
                emitted=True
        if f.session.store.acquisitions_in_replay_order():
            # This fixture proves wiring with one native quote only, NOT the
            # ordinary 30-quote goal. Final evidence must remain INCOMPLETE.
            atomic_json(root/'controller-status.json',{'contract':'outer-controller-status-v1','nonce':nonce,'phase':'GOAL_COMPLETE'})
            break
        if r.closed:raise RuntimeError('Synthetic native runtime stopped')
        time.sleep(.03)
    while not (root/'STOP.json').exists() and time.monotonic()<deadline:time.sleep(.01)
except Exception as error:
    import traceback
    atomic_json(root/'controller-entry-failure.json',{'phase':'runtime_profile_pump','exception_type':type(error).__name__,
        'runtime_reason':(r.last_report or {}).get('reason'),'fixed_exceptions':fixed_exceptions,
        'frames':[{'file':Path(f.filename).name,'function':f.name,'line':f.lineno} for f in traceback.extract_tb(error.__traceback__)]})
    raise SystemExit(70)
finally:
    p.close();f.session.close()
    import hashlib
    atomic_json(root/'before-report-hashes.json',{p.relative_to(f.target).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
        for p in f.target.rglob('*') if p.is_file() and not p.name.endswith(('-shm','-wal'))})
