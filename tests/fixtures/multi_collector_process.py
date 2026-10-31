"""Actual process-exit boundary with synthetic 40-symbol broker payloads only."""
from pathlib import Path
import sys, json, os, socket
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

job = json.load(sys.stdin)
sys.path[:0] = [str(Path(__file__).resolve().parents[2]/'src'),
    str(Path(__file__).resolve().parents[1]), job['native_src']]
def denied(*args, **kwargs): raise OSError('Network denied in multi-symbol collector fixture')
socket.socket.connect = socket.socket.connect_ex = socket.create_connection = socket.getaddrinfo = denied
from mb_watchlist_coordinator.daily_session import DailySettings
from mb_watchlist_coordinator.daily_worker_view import DailyPublicationReader
from mb_watchlist_coordinator.daily_collector import DailyCollectorSettings
from mb_watchlist_coordinator.daily_epoch_collector import make_daily_collector
from test_daily_multisymbol import full_quotes
from test_integrated_identity import Response

at = datetime.fromisoformat(job['at']); now = [at-timedelta(seconds=.5)]
settings = DailyCollectorSettings(**job['collector'])
view = DailyPublicationReader(DailySettings(**job['publication_settings']),job['catalog'],
    binding=job['binding'],claim=job['claim'],publication_binding=settings.publication_binding,
    clock=lambda:now[0],fence=lambda:None)
class Client:
    def quotes(self, symbols, *, fields):
        with Path(job['call_log']).open('a') as out:
            out.write(json.dumps(list(symbols))+'\n'); out.flush(); os.fsync(out.fileno())
        return Response(symbols[0],body=full_quotes(symbols,now[0]))
    def close(self): pass
collector = make_daily_collector(settings,publication_session=view,client_factory=Client,
    clock=lambda:now[0],activation_approved=True)
collector.prepare(); now[0] = at
def fault(stage):
    if stage == job['stage']: os._exit(75)
class Clock(datetime):
    @classmethod
    def now(cls,tz=None): return now[0].astimezone(tz or timezone.utc)
try:
    with patch('mb_market_data.schwab_quotes.datetime',Clock): collector.tick(fault_hook=fault)
finally: collector.close()
raise SystemExit(76)
