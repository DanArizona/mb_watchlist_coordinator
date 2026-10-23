"""Network-denied process fixture around the real native collector adapter."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'experiments/sampling_promotion_20261016/market_data/src')]
from datetime import datetime, timedelta, timezone
import json
import os
import socket
import time
from mb_watchlist_coordinator.hot_recovery_collector import HotCollectorSettings, run_worker
import mb_market_data.schwab_quotes as quote_module

def denied(*a,**kw):raise RuntimeError('No network in collector process qualification')
socket.socket.connect=socket.socket.connect_ex=socket.create_connection=socket.getaddrinfo=denied
config=json.loads(Path(sys.argv[-2]).read_text(encoding='utf-8'))
job=json.loads(Path(sys.argv[-1]).read_text(encoding='utf-8'))
settings=HotCollectorSettings(**config['settings'])
anchor=datetime.fromisoformat(config['real_anchor_utc'])
logical=datetime.fromisoformat(config['logical_anchor_utc'])
def clock():return logical+(datetime.now(timezone.utc)-anchor)
class QuoteClock(datetime):
    @classmethod
    def now(cls,tz=None):return clock().astimezone(tz or timezone.utc)
quote_module.datetime=QuoteClock
class Response:
    ok=True
    status_code=200
    def __init__(self,symbols):self.symbols=symbols
    def json(self):return {s:{'assetMainType':'EQUITY','quote':{'lastPrice':12.0}} for s in self.symbols}
class Client:
    def quotes(self,symbols,*,fields):
        with Path(config['call_log']).open('a',encoding='utf-8') as out:
            out.write(json.dumps({'symbols':list(symbols),'at_utc':clock().isoformat()})+'\n');out.flush();os.fsync(out.fileno())
        if job['generation']==1:
            time.sleep(config.get('hang_quote_seconds',0))
        return Response(symbols)
def fault(stage):
    if job['generation']==1 and stage==config.get('crash_stage'):os._exit(77)
run_worker(sys.argv[-1],settings,client_factory=Client,clock=clock,fault_hook=fault)
