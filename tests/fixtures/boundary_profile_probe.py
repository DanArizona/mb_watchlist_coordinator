"""Elapsed synthetic profile fixture; never selected by an operator launcher."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tests'),
    str(ROOT/'experiments/sampling_promotion_20261016/market_data/src'),
    str(ROOT/'experiments/authenticated_startup_20261023/reference_mb_tools/src')]
from datetime import datetime,timezone
import json
import socket
def denied(*a,**kw):raise RuntimeError('Network denied in elapsed synthetic boundary profile')
socket.socket.connect=socket.socket.connect_ex=socket.create_connection=socket.getaddrinfo=denied
from live_profile_fixtures import FakeAPI,Clock,INVENTORY
import mb_watchlist_coordinator.live_profile as live
from mb_watchlist_coordinator.owned_process_scope import receive_gate
from mb_watchlist_coordinator.sampling_requests import timestamp
from mb_watchlist_coordinator.recovery_workers import atomic_json
from test_integrated_catalog import catalog
from runtime_fixtures import ScriptedFeed
from test_nasdaq_feed_recovery import EMPTY,rss

role,path,sha=sys.argv[1:4];value=live.bounded_json(path)
parent=Path(value['outer_root']).parent;clock_path=parent/'logical-clock.json'
if role=='worker':
    import mb_watchlist_coordinator.installed_startup_probe as installed
    import mb_watchlist_coordinator.supervised_hot_worker as supervised
    import mb_market_data.schwab_quotes as quotes
    import mb_watchlist_coordinator.hot_recovery_collector as native
    def clock():
        raw=json.loads(clock_path.read_text())
        return timestamp(raw['logical'])+(datetime.now(timezone.utc)-timestamp(raw['real']))
    class QuoteClock(datetime):
        @classmethod
        def now(cls,tz=None):return clock().astimezone(tz or timezone.utc)
    quotes.datetime=native.datetime=QuoteClock
    original_validate=live.validate_configuration
    live.validate_configuration=lambda v,h:original_validate(v,h,verify_source=lambda *a:None)
    installed.inspect_dependencies=lambda _:INVENTORY
    original=supervised.run_supervised
    supervised.run_supervised=lambda c,j:original(c,j,clock=clock,
        secure_api=FakeAPI(value['settings']['experiment_root'],[],worker=True))
    from mb_watchlist_coordinator.live_profile_entry import main
    raise SystemExit(main())
receive_gate(sys.stdin.buffer,value['nonce'])
if role=='report':raise SystemExit(live.run_reporter(value,sha,verify_source=lambda *a:None))
clock=Clock(value['settings']['password_submitted_at_utc'])
def factory(t):
    client=ScriptedFeed(t)
    day=timestamp(value['settings']['password_submitted_at_utc']).date()
    body=rss(day,halt='09:59:30')
    client.responses=[EMPTY]+[body]*9
    return client
def stage(name):
    if name=='runtime_initialized':clock.save(clock_path)
def command(v,p,h):
    return (sys.executable,'-I','-B',__file__,'worker',str(p),h,
        str(Path(v['settings']['experiment_root'])/'authenticated-worker.json'))
raise SystemExit(live.run_controller(value,path,sha,sys.stdin.buffer,clock=clock,
    inventory=lambda _:INVENTORY,secure_api=FakeAPI(value['settings']['experiment_root'],[]),
    catalog_acquirer=lambda **kw:catalog(clock()),feed_factory=factory,
    verify_source=lambda *a:None,on_stage=stage,command_factory=command))
