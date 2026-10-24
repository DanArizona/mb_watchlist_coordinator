"""Owned offline synthetic SDK around the new strict-progress native entry."""
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'src'), str(ROOT/'experiments/sampling_promotion_20261016/market_data/src'),
    str(ROOT/'experiments/authenticated_startup_20261023/reference_mb_tools/src')]
from contextlib import closing
from datetime import datetime, timedelta, timezone
import json
import os
import socket
import sqlite3
import time
from types import ModuleType

def denied(*a, **kw): raise RuntimeError('Network denied in supervised runtime fixture')
socket.socket.connect = socket.socket.connect_ex = socket.create_connection = socket.getaddrinfo = denied
configuration, simulation, job_path = sys.argv[1:]
simulation = json.loads(Path(simulation).read_text())
job = json.loads(Path(job_path).read_text())
real, logical = datetime.fromisoformat(simulation['real_anchor_utc']), datetime.fromisoformat(simulation['logical_anchor_utc'])
def clock(): return logical+(datetime.now(timezone.utc)-real)
def record(event, **fields):
    with Path(simulation['log']).open('a') as out:
        out.write(json.dumps({'event': event, 'generation': job['generation'], **fields})+'\n')
        out.flush(); os.fsync(out.fileno())
mode = simulation['mode']
SECRET = 'SYNTHETIC-PASSWORD-CANARY-41'
URL = 'https://synthetic.invalid/callback?code=SYNTHETIC-CODE-CANARY-44'
sdk = ModuleType('schwabdev'); sdk.__version__ = '4.0.0'
class Client:
    def __init__(self, **kw):
        self.callback = kw['call_on_auth']
        record('constructed', timeout=kw['timeout'], open_browser=kw['open_browser_for_auth'])
        print(SECRET, flush=True); os.write(1, SECRET.encode()); os.write(2, URL.encode())
        if mode == 'slow_credential': time.sleep(4)
        if mode == 'two_second_credential': time.sleep(2)
        if mode == 'authorization': self.callback(URL)
        if mode == 'constructor_error': raise RuntimeError(SECRET+' '+URL)
        if mode == 'changed_horizon':
            with closing(sqlite3.connect(kw['tokens_db'])) as c, c:
                c.execute('UPDATE schwabdev SET refresh_token_issued=?',
                    ((clock()-timedelta(days=7)+timedelta(seconds=10)).isoformat(),))
    def quotes(self, symbols, *, fields):
        record('quote', symbols=list(symbols), fields=fields)
        if mode == 'late_authorization': self.callback(URL)
        if mode == 'quote_error': raise RuntimeError(SECRET+' '+URL)
        class Response:
            status_code = 429 if mode == 'rate_limit' else 200
            ok = status_code == 200
            text = SECRET+' '+URL
            def json(self):
                return {s: {'symbol': s, 'assetMainType': 'EQUITY', 'assetSubType': 'COE',
                    'quote': {'lastPrice': 12.0}} for s in symbols}
        return Response()
    def close(self): record('closed')
sdk.Client = Client
sys.modules['schwabdev'] = sdk
import mb_market_data.schwab_quotes as quotes
import mb_watchlist_coordinator.hot_recovery_collector as native
class QuoteClock(datetime):
    @classmethod
    def now(cls, tz=None): return clock().astimezone(tz or timezone.utc)
quotes.datetime = native.datetime = QuoteClock
import mb_watchlist_coordinator.supervised_hot_worker as entry

def run(*a, **kw):
    if mode == 'hang_after_auth':
        client = kw['startup_client']()
        record('credentials_without_native_work')
        try: time.sleep(60)
        finally: client.close()
    if mode == 'stop_during_startup':
        original = kw['startup_client']
        def stop():
            client = original(); Path(job['stop_path']).touch(); return client
        kw['startup_client'] = stop
    def fault(stage):
        if job['generation'] == 1 and stage == simulation.get('crash_stage'): os._exit(77)
    return native.run_worker(*a, **kw, fault_hook=fault)

if mode == 'late_entry': time.sleep(3.1)
try:
    entry.run_supervised(configuration, job_path, clock=clock, native_runner=run)
except Exception as error:
    # Safe diagnostics only: no message, locals, SDK output or config contents.
    import traceback
    from mb_watchlist_coordinator.authenticated_startup import StartupError,CODES
    contexts=[];seen=set();current=error
    while current is not None and id(current) not in seen and len(contexts)<4:
        seen.add(id(current))
        contexts.append({'exception_type':type(current).__name__,
            'code':current.code if isinstance(current,StartupError) and current.code in CODES else None,
            'errno':getattr(current,'errno',None) if type(getattr(current,'errno',None)) is int else None,
            'winerror':getattr(current,'winerror',None) if type(getattr(current,'winerror',None)) is int else None,
            'frames':[{'file':Path(f.filename).name,'function':f.name,'line':f.lineno} for f in traceback.extract_tb(current.__traceback__)]})
        current=current.__cause__ or current.__context__
    try:record('safe_failure',contexts=contexts)
    except Exception:pass
    raise SystemExit(70) from None
