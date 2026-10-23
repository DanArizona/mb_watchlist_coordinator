"""Offline-only installed-probe fixture; real operator entry has no fake mode."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'experiments/authenticated_startup_20261023/reference_mb_tools/src')]
from contextlib import closing
import json
import os
import socket
import sqlite3
import time
from types import ModuleType

def denied(*a,**kw):raise RuntimeError('Network denied in installed-probe fixture')
socket.socket.connect=socket.socket.connect_ex=socket.create_connection=socket.getaddrinfo=denied
simulation=json.loads(Path(sys.argv[1]).read_text())
mode=simulation['mode']
SECRET='SYNTHETIC-PASSWORD-CANARY-40'
URL='https://synthetic.invalid/callback?code=SYNTHETIC-CODE-CANARY-40'
def record(event):
    with Path(simulation['log']).open('a') as out:
        out.write(event+'\n');out.flush();os.fsync(out.fileno())
sdk=ModuleType('schwabdev');sdk.__version__='4.0.0'
class Client:
    def __init__(self,**kw):
        record('constructed');self.callback=kw['call_on_auth']
        assert kw['open_browser_for_auth'] is False and kw['timeout']==3
        print(SECRET,flush=True);os.write(2,URL.encode());os.write(1,SECRET.encode())
        if mode=='authorization':self.callback(URL)
        if mode=='constructor_error':raise ValueError(SECRET+' '+URL)
        if mode=='hung_constructor':time.sleep(60)
    def quotes(self,symbols,*,fields):
        assert symbols==['SPY'] and fields=='all'
        record('quote')
        if mode=='hung_quote':time.sleep(60)
        if mode=='transport_error':raise ValueError(SECRET+' '+URL)
        if mode=='late_authorization':self.callback(URL)
        class Response:
            ok=mode!='http_error'
            status_code=401 if mode=='http_error' else 200
            text=SECRET+' '+URL
            def json(self):
                if mode=='decode_error':raise ValueError(SECRET+' '+URL)
                if mode=='missing_symbol':return {'UNEXPECTED':{'symbol':'SPY','quote':{'lastPrice':12.0}}}
                if mode=='wrong_symbol':return {'SPY':{'symbol':'UNEXPECTED','quote':{'lastPrice':12.0}}}
                if mode=='invalid_price':return {'SPY':{'symbol':'SPY','quote':{'lastPrice':False}}}
                return {'SPY':{'symbol':'SPY','quote':{'lastPrice':12.0},'ignored_debug':SECRET+' '+URL}}
        return Response()
    def close(self):
        record('closed')
        if mode=='hung_close':time.sleep(60)
sdk.Client=Client;sys.modules['schwabdev']=sdk
from mb_watchlist_coordinator.installed_startup_probe import ProbeSettings,run_child
settings=ProbeSettings(**json.loads(sys.argv[2]))
if mode=='raw_protocol_error':
    print(SECRET+' '+URL);raise SystemExit(70)
if mode=='early_exit':raise SystemExit(77)
raise SystemExit(run_child(settings,{},inventory=lambda _:simulation['inventory']))
