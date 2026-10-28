"""Owned synthetic native-collector crash drill; no credentials or network."""
from pathlib import Path
import sys,json,os,socket
from datetime import datetime,timedelta,timezone
from unittest.mock import patch

job=json.load(sys.stdin)
def denied(*args,**kwargs):raise OSError('Network denied in daily native collector drill')
socket.create_connection=socket.getaddrinfo=denied
socket.socket.connect=socket.socket.connect_ex=denied
sys.path[:0]=[str(Path(__file__).resolve().parents[2]/'src'),job['native_src']]
from mb_watchlist_coordinator.daily_session import DailySettings,DailySession
from mb_watchlist_coordinator.integrated_catalog import DirectoryCatalog
from mb_watchlist_coordinator.daily_collector import DailyCollectorSettings,DailyHotCollector
from mb_watchlist_coordinator.sampling_requests import timestamp

at=timestamp(job['at']);now=[at-timedelta(microseconds=500000)]
session=DailySession(DailySettings(**job['publication_settings']),DirectoryCatalog.load(job['catalog']),clock=lambda:now[0])
session.attach(publication_approved=True)
class Response:
    status_code=200;ok=True
    def json(self):return {'NVDA':{'symbol':'NVDA','assetMainType':'EQUITY','assetSubType':'COE','quote':{'lastPrice':12.0}}}
class Client:
    def quotes(self,symbols,*,fields):
        with (Path(session.settings.state_root).parent/'native-provider-calls.txt').open('a') as stream:
            stream.write(symbols[0]+'\n');stream.flush();os.fsync(stream.fileno())
        return Response()
    def close(self):pass
collector=DailyHotCollector(DailyCollectorSettings(**job['collector']),publication_session=session,
    client_factory=Client,clock=lambda:now[0],activation_approved=True)
collector.prepare();now[0]=at
def fault(stage):
    if stage==job['stage']:os._exit(75)
class Clock(datetime):
    @classmethod
    def now(cls,tz=None):return now[0].astimezone(tz or timezone.utc)
with patch('mb_market_data.schwab_quotes.datetime',Clock):collector.tick(fault_hook=fault)
raise SystemExit(76)
