"""Trusted offline wrapper around the unchanged fixed public role dispatcher.

Only test-owned subprocess creation uses this wrapper. It substitutes a secure
SDK, constant shifted clock and synthetic feed via existing Python seams.
The live CMD/dispatcher exposes none of those substitutions.
"""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import socket
import subprocess
import sys

scene_path,entry,*args=sys.argv[1:]
scene=json.loads(Path(scene_path).read_text())
source=Path(entry).resolve().parents[3]
sys.path[:0]=[str(source/'coordinator/src'),str(source/'market_data/src')]
role=args[0]
real,logical=map(datetime.fromisoformat,(scene['real_anchor'],scene['logical_anchor']))
clock=lambda:logical+(datetime.now(timezone.utc)-real)
def denied(*a,**k):raise OSError('Network denied in market-open daily fixture')
socket.socket.connect=socket.socket.connect_ex=socket.create_connection=socket.getaddrinfo=denied
def record(event):
    with Path(scene['log']).open('a',encoding='utf-8') as out:
        out.write(json.dumps({'role':role,'event':event,'at':clock().isoformat()})+'\n')
        out.flush();os.fsync(out.fileno())
original_popen=subprocess.Popen
def wrapped_popen(command,*a,**kw):
    command=list(command)
    if len(command)>3 and command[3]==entry:
        command=[*command[:3],str(Path(__file__).resolve()),scene_path,entry,*command[4:]]
    return original_popen(command,*a,**kw)
subprocess.Popen=wrapped_popen
import mb_watchlist_coordinator.installed_startup_probe as dependencies
dependencies.inspect_dependencies=lambda _:scene['dependencies']
import mb_watchlist_coordinator.daily_authenticated_worker as workers
import mb_watchlist_coordinator.daily_operating_worker as operating
from mb_watchlist_coordinator.nasdaq_sampling import HaltSnapshot
from mb_watchlist_coordinator.sampling_requests import digest
class Status:
    def require_refresh_valid_through(self,required):pass
class Response:
    status_code=200
    ok=True
    def __init__(self,symbol):self.symbol=symbol
    def json(self):return {self.symbol:{'symbol':self.symbol,'assetMainType':'EQUITY',
        'assetSubType':'COE','quote':{'lastPrice':12.0}}}
class Client:
    def __init__(self):record('client_constructed')
    def quotes(self,symbols,*,fields):record('quote:'+symbols[0]);return Response(symbols[0])
    def close(self):record('client_closed')
class Secure:
    DEFAULT_POLLING_REFRESH_MARGIN=timedelta(minutes=75,seconds=30)
    @staticmethod
    def load_secure_schwab_config(path,password):
        if bytes(password)!=b'SYNTHETIC-DAILY-PATH-PRIVATE-CANARY':raise ValueError('Synthetic secret differs')
        return None
    @staticmethod
    def read_schwab_token_status(config,**kwargs):return Status()
    @staticmethod
    def make_client_from_config(config,**kwargs):return Client()
collector,identity,controller=workers.run_collector,workers.run_identity,operating.controller_entry
workers.run_collector=lambda config,job:collector(config,job,clock=clock,secure_api=Secure)
workers.run_identity=lambda config,job:identity(config,job,clock=clock,secure_api=Secure)
EMPTY='<?xml version="1.0"?><rss version="2.0"><channel><title>Nasdaq Trade Halts</title></channel></rss>'
def admit(owner):
    at=clock();local=at.astimezone(logical.tzinfo)
    row={'symbol':'NVDA','halt_date':local.strftime('%m/%d/%Y'),
         'halt_time':(local-timedelta(minutes=1)).strftime('%H:%M:%S.%f'),'reason_code':'LUDP'}
    owner.session.cycle(client=owner.identity_client,
        historical_snapshot=HaltSnapshot('offline-saved-history',at,'HISTORICAL',digest([row]),(row,),{'synthetic_only':True}))
operating.controller_entry=lambda root,nonce:controller(root,nonce,clock=clock,on_started=admit,
    synthetic_factory=lambda:{'clock_at_utc':logical.isoformat(),
        'clock_real_anchor_utc':real.isoformat(),'chunks':[EMPTY]})
class Clock(datetime):
    @classmethod
    def now(cls,tz=None):return clock().astimezone(tz or timezone.utc)
import mb_market_data.schwab_quotes as quotes
quotes.datetime=Clock
from mb_watchlist_coordinator.daily_launch_entry import main
record('fixed_public_dispatch')
raise SystemExit(main(args))
