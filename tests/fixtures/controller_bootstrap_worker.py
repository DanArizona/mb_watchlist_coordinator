"""Owned offline process fixture; SDK/configuration are entirely synthetic."""
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

def denied(*a, **kw):
    raise RuntimeError('Network denied in fresh-bootstrap process qualification')
socket.socket.connect = socket.socket.connect_ex = socket.create_connection = socket.getaddrinfo = denied
simulation = json.loads(Path(sys.argv[1]).read_text())
mode = simulation['mode']
SECRET = 'SYNTHETIC-PASSWORD-CANARY-41'
URL = 'https://synthetic.invalid/callback?code=SYNTHETIC-CODE-CANARY-41'
real = datetime.fromisoformat(simulation['real_anchor_utc'])
logical = datetime.fromisoformat(simulation['logical_anchor_utc'])
shift = timedelta()
def clock():
    return logical + (datetime.now(timezone.utc)-real) + shift
def record(event):
    with Path(simulation['log']).open('a') as out:
        out.write(event+'\n'); out.flush(); os.fsync(out.fileno())
sdk = ModuleType('schwabdev'); sdk.__version__ = '4.0.0'
class Client:
    def __init__(self, **kw):
        global shift
        assert not Path(simulation['experiment_root']).exists()
        assert kw['timeout'] == 3 and kw['open_browser_for_auth'] is False
        record('constructed')
        print(SECRET, flush=True); os.write(1, SECRET.encode()); os.write(2, URL.encode())
        if mode == 'authorization': kw['call_on_auth'](URL)
        if mode == 'constructor_error': raise RuntimeError(SECRET+' '+URL)
        if mode == 'hung_constructor': time.sleep(60)
        if mode == 'changed_horizon':
            with closing(sqlite3.connect(kw['tokens_db'])) as c, c:
                c.execute('UPDATE schwabdev SET refresh_token_issued=?',
                    ((clock()-timedelta(days=7)+timedelta(seconds=2)).isoformat(),))
        if mode == 'changed_input':
            p = Path(simulation['opening_proposal']); p.write_bytes(p.read_bytes()+b' ')
        if mode == 'window_expired': shift = timedelta(seconds=62)
    def quotes(self, *a, **kw):
        record('UNEXPECTED_QUOTE')
        raise AssertionError('No bootstrap quote is allowed')
    def close(self):
        record('closed')
        if mode == 'hung_close': time.sleep(60)
sdk.Client = Client
sys.modules['schwabdev'] = sdk

from mb_watchlist_coordinator.bootstrap_entry import run_entry
def fault(name):
    if name == 'credentials_accepted' and mode == 'fault_before_root': raise RuntimeError(SECRET)
    if name == 'root_claimed' and mode == 'crash_after_root': os._exit(77)
    if name == 'root_claimed' and mode == 'hang_after_root': time.sleep(60)
    if name == 'initial_poll_run_registered' and mode == 'fault_after_run': raise RuntimeError(SECRET)
raise SystemExit(run_entry(simulation['configuration'], simulation['configuration_sha256'], clock=clock,
    inventory=lambda _: simulation['inventory'], fault_hook=fault,
    startup_seconds=simulation.get('startup_seconds', 8), hard_seconds=simulation.get('hard_seconds', 60)))
