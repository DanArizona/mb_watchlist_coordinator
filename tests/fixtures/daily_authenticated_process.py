"""Owned synthetic SDK process; no network, vault or actual broker library."""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import socket
import sys
import time

scenario_path, role, configuration, job_path = sys.argv[1:]
scenario = json.loads(Path(scenario_path).read_text())
sys.path[:0] = [str(Path(__file__).resolve().parents[2]/'src'), scenario['native_src']]

def denied(*args, **kwargs):
    raise OSError('Network denied in daily authenticated process fixture')
socket.socket.connect = socket.socket.connect_ex = socket.create_connection = socket.getaddrinfo = denied
real, logical = map(datetime.fromisoformat, (scenario['real_anchor'], scenario['logical_anchor']))
def clock():
    return logical+(datetime.now(timezone.utc)-real)

def record(event):
    with Path(scenario['log']).open('a', encoding='utf-8') as out:
        out.write(json.dumps({'role': role, 'event': event, 'at': clock().isoformat()})+'\n')
        out.flush(); os.fsync(out.fileno())

mode = scenario.get('mode', 'normal') if role == scenario.get('target_role', 'collector') else 'normal'
class Status:
    def require_refresh_valid_through(self, required):
        if mode == 'credential_horizon': raise ValueError('SYNTHETIC-PRIVATE-CANARY-62')
class Response:
    status_code = 429 if mode == 'rate_limit' else 200
    ok = status_code == 200
    def __init__(self, symbol): self.symbol = symbol
    def json(self):
        return {self.symbol: {'symbol': self.symbol, 'assetMainType': 'EQUITY',
            'assetSubType': 'COE', 'quote': {'lastPrice': 12.0}}} if self.ok else {}
class Client:
    def __init__(self):
        record('constructed')
        print('SYNTHETIC-PRIVATE-CANARY-62', flush=True)
        os.write(2, b'https://synthetic.invalid/callback?code=SYNTHETIC-CODE-CANARY-62')
        if mode == 'auth_hang': time.sleep(60)
        if mode == 'auth_error': raise RuntimeError('SYNTHETIC-PRIVATE-CANARY-62')
    def quotes(self, symbols, *, fields):
        record('quote:'+symbols[0])
        if mode == 'quote_hang': time.sleep(60)
        return Response(symbols[0])
    def close(self):
        record('closed')
        if mode == 'close_hang': time.sleep(60)
class Secure:
    DEFAULT_POLLING_REFRESH_MARGIN = timedelta(minutes=75, seconds=30)
    @staticmethod
    def load_secure_schwab_config(path, password):
        if bytes(password) != b'SYNTHETIC-PRIVATE-CANARY-62': raise ValueError('Synthetic secret differs')
        return None
    @staticmethod
    def read_schwab_token_status(config, **kwargs): return Status()
    @staticmethod
    def make_client_from_config(config, **kwargs):
        assert kwargs['timeout'] == 3
        if mode == 'authorization': kwargs['call_on_auth']('https://synthetic.invalid/callback?code=SYNTHETIC-CODE-CANARY-62')
        return Client()

from mb_watchlist_coordinator.daily_authenticated_worker import run_collector, run_identity, run_report
from unittest.mock import patch
class Clock(datetime):
    @classmethod
    def now(cls, tz=None): return clock().astimezone(tz or timezone.utc)
def fault(stage):
    if mode.startswith('crash_') and stage == mode.removeprefix('crash_'):
        job = json.loads(Path(job_path).read_text())
        if job['generation'] == 1:
            record('fault:'+stage)
            os._exit(75)
try:
    if role == 'collector' and scenario.get('replacement_cross_launch_slot'):
        job = json.loads(Path(job_path).read_text())
        if job['generation'] == 2:
            until = datetime.fromisoformat(job['first_eligible_slot_utc'])+timedelta(milliseconds=50)
            delay = (until-clock()).total_seconds()
            if delay > 2: raise ValueError('Synthetic replacement delay exceeds fixture bound')
            if delay > 0: time.sleep(delay)
            record('replacement_crossed_launch_slot')
    with patch('mb_market_data.schwab_quotes.datetime', Clock):
        if role == 'collector': run_collector(configuration, job_path, clock=clock, secure_api=Secure, fault_hook=fault)
        elif role == 'identity': run_identity(configuration, job_path, clock=clock, secure_api=Secure)
        elif role == 'report':
            if mode == 'report_hang': time.sleep(60)
            run_report(configuration, job_path)
        else: raise ValueError('Unknown fixture role')
except BaseException as error:
    record('failed:'+type(error).__name__+':'+getattr(error, 'code', 'no_code'))
    raise SystemExit(70)
