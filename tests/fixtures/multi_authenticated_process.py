"""Owned multi-symbol synthetic SDK. No vault, broker library or network."""
from datetime import datetime,timedelta,timezone
import importlib.util,json,os,socket,sys
from pathlib import Path
from unittest.mock import patch
scene_path,role,configuration,job_path=sys.argv[1:]
scene=json.loads(Path(scene_path).read_text());project=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(project/'src'),scene['native_src']]
def denied(*args,**kwargs):raise OSError('Network denied in multi-symbol owned proof')
socket.socket.connect=socket.socket.connect_ex=socket.create_connection=socket.getaddrinfo=denied
real,logical=map(datetime.fromisoformat,(scene['real_anchor'],scene['logical_anchor']))
def clock():return logical+(datetime.now(timezone.utc)-real)
def record(event,**values):
    with Path(scene['log']).open('a',encoding='utf-8')as out:
        out.write(json.dumps(dict(values,role=role,event=event,at=clock().isoformat()))+'\n');out.flush();os.fsync(out.fileno())
spec=importlib.util.spec_from_file_location('multi_quote_shape',project/'experiments/daily_hot_operating_20261028/capacity_probe.py')
shape=importlib.util.module_from_spec(spec);spec.loader.exec_module(shape)
class Response:
    status_code=200;ok=True
    def __init__(self,symbols):self.symbols=symbols
    def json(self):return {s:dict(shape.quote_payload(clock(),n),symbol=s)for n,s in enumerate(self.symbols)}
class Status:
    def require_refresh_valid_through(self,required):pass
class Client:
    def __init__(self):record('constructed')
    def quotes(self,symbols,*,fields):
        if fields!='all' or not 1<=len(symbols)<=40:raise ValueError('Synthetic request shape differs')
        record('quote',symbols=list(symbols));return Response(symbols)
    def close(self):record('closed')
class Secure:
    DEFAULT_POLLING_REFRESH_MARGIN=timedelta(minutes=75,seconds=30)
    @staticmethod
    def load_secure_schwab_config(path,password):
        if bytes(password)!=b'SYNTHETIC-PRIVATE-CANARY-62':raise ValueError('Private synthetic secret differs')
    @staticmethod
    def read_schwab_token_status(config,**kwargs):return Status()
    @staticmethod
    def make_client_from_config(config,**kwargs):
        if kwargs['timeout']!=3:raise ValueError('Original request timeout required')
        return Client()
class Clock(datetime):
    @classmethod
    def now(cls,tz=None):return clock().astimezone(tz or timezone.utc)
from mb_watchlist_coordinator.daily_authenticated_worker import run_collector,run_identity,run_report
try:
    with patch('mb_market_data.schwab_quotes.datetime',Clock):
        if role=='collector':run_collector(configuration,job_path,clock=clock,secure_api=Secure)
        elif role=='identity':run_identity(configuration,job_path,clock=clock,secure_api=Secure)
        elif role=='report':run_report(configuration,job_path)
        else:raise ValueError('Unknown synthetic role')
except BaseException as error:
    import traceback
    record('failed',error_type=type(error).__name__,frames=[f.name for f in traceback.extract_tb(error.__traceback__)])
    raise SystemExit(70)
