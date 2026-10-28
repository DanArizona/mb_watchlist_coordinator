"""Owned synthetic crash drill for the daily publication backend."""
import json
import os
from datetime import timedelta
import socket
from pathlib import Path
import sys

job = json.load(sys.stdin)
def denied(*args, **kwargs): raise OSError('Network denied in synthetic daily-session worker')
socket.create_connection = socket.getaddrinfo = denied
socket.socket.connect = socket.socket.connect_ex = denied
sys.path[:0] = [str(Path(__file__).resolve().parents[2]/'src'), job['native_src']]
from mb_watchlist_coordinator.daily_session import DailySession, DailySettings
from mb_watchlist_coordinator.integrated_catalog import DirectoryCatalog
from mb_watchlist_coordinator.nasdaq_sampling import HaltSnapshot
from mb_watchlist_coordinator.sampling_requests import digest, timestamp

at = timestamp(job['at'])
session = DailySession(DailySettings(**job['settings']), DirectoryCatalog.load(job['catalog']), clock=lambda: at)
session.attach(create=True, publication_approved=True)
row = {'symbol':'NVDA','halt_date':at.strftime('%m/%d/%Y'),
       'halt_time':(at-timedelta(minutes=1)).strftime('%H:%M:%S'), 'reason_code':'LUDP'}
snapshot = HaltSnapshot('synthetic-process-history', at, 'HISTORICAL', digest([row]), (row,), {'synthetic_only':True})

class Response:
    status_code = 200
    def json(self): return {'NVDA':{'symbol':'NVDA','assetMainType':'EQUITY','assetSubType':'COE'}}

class Client:
    def quotes(self, symbols, *, fields):
        with (session.root/'quote-calls.txt').open('a') as stream: stream.write(symbols[0]+'\n')
        return Response()

def fault(stage):
    if stage == job['stage']: os._exit(75)

session.cycle(client=Client(), historical_snapshot=snapshot, identity_fault_hook=fault, service_fault_hook=fault)
raise SystemExit(76)
