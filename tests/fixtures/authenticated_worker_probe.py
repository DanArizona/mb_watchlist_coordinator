"""Offline-only SDK replacement around the actual authenticated worker entry."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'experiments/sampling_promotion_20261016/market_data/src'),
    str(ROOT/'experiments/authenticated_startup_20261023/reference_mb_tools/src')]
from contextlib import closing
from datetime import datetime, timedelta, timezone
import json
import os
import socket
import sqlite3
import time
from types import ModuleType

def denied(*a,**kw):raise RuntimeError('Network denied in authenticated startup fixture')
socket.socket.connect=socket.socket.connect_ex=socket.create_connection=socket.getaddrinfo=denied
configuration,simulation,job_path=sys.argv[1:]
simulation=json.loads(Path(simulation).read_text(encoding='utf-8'))
job=json.loads(Path(job_path).read_text(encoding='utf-8'))
real=datetime.fromisoformat(simulation['real_anchor_utc'])
logical=datetime.fromisoformat(simulation['logical_anchor_utc'])
shift=timedelta()
def clock():return logical+(datetime.now(timezone.utc)-real)+shift
def record(event,**fields):
    with Path(simulation['log']).open('a',encoding='utf-8') as out:
        out.write(json.dumps(dict(event=event,generation=job['generation'],**fields))+'\n')
        out.flush();os.fsync(out.fileno())
mode=simulation['mode']
SECRET='SYNTHETIC-PASSWORD-CANARY-38'
URL='https://synthetic.invalid/callback?code=SYNTHETIC-CODE-CANARY-38'
sdk=ModuleType('schwabdev');sdk.__version__='4.0.0'
class Client:
    def __init__(self,**kw):
        global shift
        self.callback=kw['call_on_auth']
        record('constructed',timeout=kw['timeout'],open_browser=kw['open_browser_for_auth'])
        # Exercise both Python and direct descriptor output, outside exception handlers.
        print(SECRET,flush=True);print(URL,file=sys.stderr,flush=True)
        os.write(1,SECRET.encode());os.write(2,URL.encode())
        if mode=='authorization':self.callback(URL)
        if mode=='constructor_error':raise RuntimeError(SECRET+' '+URL)
        if mode=='hung_constructor':time.sleep(60)
        if mode=='changed_horizon':
            with closing(sqlite3.connect(kw['tokens_db'])) as connection,connection:
                connection.execute('UPDATE schwabdev SET refresh_token_issued=?',
                    ((clock()-timedelta(days=7)+timedelta(seconds=10)).isoformat(),))
        if mode=='window_expired':shift=timedelta(seconds=120)
        if mode=='stop_during_constructor':Path(job['stop_path']).touch()
    def quotes(self,symbols,*,fields):
        record('quote',symbols=list(symbols),fields=fields)
        if mode=='late_authorization':self.callback(URL)
        if mode=='quote_error':raise RuntimeError(SECRET+' '+URL)
        class Response:
            status_code=401 if mode=='http_401' else 200
            ok=status_code==200
            text=SECRET+' '+URL
            def json(self):
                if mode=='decode_error':raise ValueError(SECRET+' '+URL)
                return {s:{'assetMainType':'EQUITY','quote':{'lastPrice':12.0}} for s in symbols}
        return Response()
    def close(self):record('closed')
sdk.Client=Client
sys.modules['schwabdev']=sdk

import mb_market_data.schwab_quotes as quotes
class QuoteClock(datetime):
    @classmethod
    def now(cls,tz=None):return clock().astimezone(tz or timezone.utc)
quotes.datetime=QuoteClock
import mb_watchlist_coordinator.authenticated_hot_worker as entry
original=entry.run_worker
def run(*a,**kw):
    def fault(stage):
        if job['generation']==1 and stage==simulation.get('crash_stage'):os._exit(77)
    return original(*a,**kw,fault_hook=fault)
entry.run_worker=run
try:
    entry.run_authenticated(configuration,job_path,clock=clock)
except Exception:
    # The real entry also returns only an exit code; never print raw exceptions.
    raise SystemExit(70) from None
