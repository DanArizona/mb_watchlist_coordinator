"""Owned synthetic manual-controller entry. No real credential/provider access."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tests'),
    str(ROOT/'experiments/sampling_promotion_20261016/market_data/src'),
    str(ROOT/'experiments/authenticated_startup_20261023/reference_mb_tools/src')]
from datetime import datetime,timezone
import json
import os
import socket
import time
from types import ModuleType

def denied(*a,**kw):raise RuntimeError('Network denied in manual-controller fixture')
socket.socket.connect=socket.socket.connect_ex=socket.create_connection=socket.getaddrinfo=denied
configuration,configuration_sha,simulation_path=sys.argv[1:]
simulation=json.loads(Path(simulation_path).read_text())
real=datetime.fromisoformat(simulation['real_anchor_utc']);logical=datetime.fromisoformat(simulation['logical_anchor_utc'])
def clock():return logical+(datetime.now(timezone.utc)-real)
def record(event,**fields):
    with Path(simulation['controller_log']).open('a') as out:
        out.write(json.dumps({'event':event,**fields})+'\n');out.flush();os.fsync(out.fileno())
if simulation.get('debug_fixed_exceptions'):
    def trace(frame,event,arg):
        if event=='exception' and frame.f_code.co_filename.endswith(('controller_resume.py','integrated_runtime.py')):
            record('fixed_exception',function=frame.f_code.co_name,line=frame.f_lineno,
                exception_type=arg[0].__name__)
        return trace
    sys.settrace(trace)
SECRET='SYNTHETIC-PASSWORD-CANARY-41';URL='https://synthetic.invalid?code=SYNTHETIC-RESUME-CODE-46'
sdk=ModuleType('schwabdev');sdk.__version__='4.0.0'
class Client:
    def __init__(self,**kw):
        record('resume_client_constructed',timeout=kw['timeout'],open_browser=kw['open_browser_for_auth'])
        print(SECRET,flush=True);os.write(1,SECRET.encode());os.write(2,URL.encode())
        mode=simulation.get('resume_mode','normal')
        if mode=='slow_credential':time.sleep(9)
        if mode=='authorization':kw['call_on_auth'](URL)
        if mode=='constructor_error':raise RuntimeError(SECRET+' '+URL)
    def quotes(self,symbols,*,fields):
        record('identity_quote',symbols=list(symbols),fields=fields)
        class Response:
            status_code=200;ok=True;text=SECRET
            def json(self):return {s:{'symbol':s,'assetMainType':'EQUITY','assetSubType':'COE','quote':{'lastPrice':12.0}} for s in symbols}
        return Response()
    def close(self):record('resume_client_closed')
sdk.Client=Client;sys.modules['schwabdev']=sdk
from mb_watchlist_coordinator.nasdaq_feed_recovery import BoundedFeedClient
from mb_watchlist_coordinator.resume_entry import run_entry
from test_controller_bootstrap import INVENTORY
from test_nasdaq_feed_recovery import EMPTY

def stage(name):
    record('stage',stage=name)
    if name==simulation.get('controller_crash_stage'):os._exit(77)
    if name==simulation.get('controller_hang_stage'):time.sleep(70)

def ready(runtime):
    record('controller_ready',counts=runtime.manual_resume_receipt['data']['counts'])
    goal=simulation.get('goal_native',0)
    if not goal:return
    until=time.monotonic()+12
    while time.monotonic()<until:
        result=runtime.step(synthetic={'chunks':[EMPTY.decode()]})
        acquisitions=runtime.session.store.acquisitions_in_replay_order()
        native=len(acquisitions);job=runtime.managed._job()
        owned=runtime.managed.child is not None and job is not None
        fresh=bool(owned and any(a.scheduled_at_utc>=datetime.fromisoformat(job['first_eligible_slot_utc']) for a in acquisitions))
        if native>=goal and fresh and job['generation']>=simulation.get('minimum_generation',1):
            record('native_goal',acquisitions=native,
                generation=runtime.managed._job()['generation'],
                first_eligible_slot_utc=runtime.managed._job()['first_eligible_slot_utc'])
            if simulation.get('crash_after_native_goal'):os._exit(78)
            return
        if simulation.get('crash_after_worker_exit') and (runtime.managed.last_exit is not None
                or runtime.managed.child is not None and runtime.managed.child.poll() is not None):
            os._exit(79)
        if runtime.closed:raise RuntimeError('Synthetic reopened runtime stopped before its native goal')
        time.sleep(.03)
    raise RuntimeError('Synthetic reopened native goal timed out')

raise SystemExit(run_entry(configuration,configuration_sha,clock=clock,
    inventory=lambda _:INVENTORY,feed_factory=BoundedFeedClient,
    fault_hook=stage,on_ready=ready,
    credential_seconds=simulation.get('credential_seconds',8),hard_seconds=simulation.get('hard_seconds',60)))
