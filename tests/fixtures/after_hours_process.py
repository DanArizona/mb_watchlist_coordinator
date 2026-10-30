"""Trusted offline seam: synthetic SDK, shifted wall clock, actual elapsed gates."""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import socket
import sys
import time
from unittest.mock import patch

scene_path, role, root, nonce = sys.argv[1:]
scene = json.loads(Path(scene_path).read_text())
sys.path[:0] = [str(Path(__file__).resolve().parents[2]/'src'), scene['native_src']]
def denied(*a, **k): raise OSError('Network denied in off-hours synthetic fixture')
socket.socket.connect = socket.socket.connect_ex = socket.create_connection = socket.getaddrinfo = denied
real, logical = map(datetime.fromisoformat, (scene['real_anchor'], scene['logical_anchor']))
clock = lambda: logical+(datetime.now(timezone.utc)-real)
class Clock(datetime):
    @classmethod
    def now(cls, tz=None): return clock().astimezone(tz or timezone.utc)
def event(name):
    with Path(scene['events']).open('a', encoding='utf-8') as f:
        f.write(name+'\n'); f.flush(); os.fsync(f.fileno())
SECRET = 'SYNTHETIC-OFF-HOURS-SECRET'
mode = scene.get('mode', 'normal')
class Response:
    status_code = 429 if mode == 'rate_limit' else 200
    ok = status_code == 200
    def json(self):
        if mode == 'decode_error': raise ValueError(SECRET)
        return {'SPY': {'symbol': 'SPY', 'assetMainType': 'EQUITY',
            'quote': {'lastPrice': 123.45, 'quoteTime': int(clock().timestamp()*1000)}}}
class Client:
    def quotes(self, symbols, *, fields):
        assert symbols == ['SPY'] and fields == 'all'; event('quote')
        if mode == 'quote_hang': time.sleep(60)
        if mode == 'transport_error': raise ValueError(SECRET)
        return Response()
    def close(self): event('closed')
class Status:
    def require_refresh_valid_through(self, required):
        assert required >= clock()+timedelta(minutes=75)
class Secure:
    DEFAULT_POLLING_REFRESH_MARGIN = timedelta(minutes=75, seconds=30)
    @staticmethod
    def load_secure_schwab_config(path, password):
        assert bytes(password) == SECRET.encode(); event('config_accepted'); return None
    @staticmethod
    def read_schwab_token_status(config, **kw): return Status()
    @staticmethod
    def make_client_from_config(config, **kw):
        assert kw['timeout'] == 3; event('constructed')
        print(SECRET, flush=True); os.write(2, SECRET.encode())
        if mode == 'auth_hang': time.sleep(60)
        if mode == 'authorization': kw['call_on_auth']('https://synthetic.invalid/?code='+SECRET)
        return Client()

from mb_watchlist_coordinator.installed_startup_probe import _silence
from mb_watchlist_coordinator.after_hours_profile import run_worker, run_report
_silence()
try:
    if role == 'worker':
        if mode == 'early_exit': raise SystemExit(77)
        with patch('mb_market_data.schwab_quotes.datetime', Clock), \
                patch('mb_market_data.quote_observation_store._utc_now', clock):
            raise SystemExit(run_worker(root, nonce, clock=clock, secure_api=Secure, synthetic_only=True))
    if role == 'report': raise SystemExit(run_report(root, nonce))
    raise SystemExit(64)
except Exception:
    raise SystemExit(70)
