"""Offline logical-clock wrapper of the actual paced synthetic HTTP worker."""
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'src'), str(ROOT/'experiments/sampling_promotion_20261016/market_data/src')]
from datetime import datetime, timezone
import json
import socket
def denied(*a, **kw): raise RuntimeError('Network denied in runtime feed fixture')
socket.socket.connect = socket.socket.connect_ex = socket.create_connection = socket.getaddrinfo = denied
simulation = json.loads(Path(sys.argv[1]).read_text())
real = datetime.fromisoformat(simulation['real_anchor_utc'])
logical = datetime.fromisoformat(simulation['logical_anchor_utc'])
class Clock(datetime):
    @classmethod
    def now(cls, tz=None):
        return (logical+(datetime.now(timezone.utc)-real)).astimezone(tz or timezone.utc)
import mb_watchlist_coordinator.nasdaq_feed_recovery as transport
import mb_watchlist_coordinator.nasdaq_feed_worker as worker
transport.datetime = worker.datetime = Clock
raise SystemExit(worker.main())
