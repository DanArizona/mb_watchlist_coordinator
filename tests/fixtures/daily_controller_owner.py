"""Owned controller process for the actual parent-loss drill; entirely synthetic."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import socket
import sys
import time

scene = json.loads(Path(sys.argv[1]).read_text())
sys.path[:0] = [str(Path(__file__).resolve().parents[2]/'src'), scene['native_src']]
def denied(*args, **kwargs): raise OSError('Network denied in owned-controller fixture')
socket.socket.connect = socket.socket.connect_ex = socket.create_connection = socket.getaddrinfo = denied
from mb_watchlist_coordinator.authenticated_startup import AuthStartupSettings, SessionPassword
from mb_watchlist_coordinator.daily_collector import DailyCollectorSettings
from mb_watchlist_coordinator.daily_controller import DailyController
from mb_watchlist_coordinator.daily_session import DailySession, DailySettings
from mb_watchlist_coordinator.daily_supervision import DailyWorkerConfiguration
from mb_watchlist_coordinator.integrated_catalog import DirectoryCatalog
from mb_watchlist_coordinator.recovery_workers import atomic_json
from mb_watchlist_coordinator.sampling_requests import digest
real, logical = map(datetime.fromisoformat, (scene['real_anchor'], scene['logical_anchor']))
clock = lambda: logical+(datetime.now(timezone.utc)-real)
raw = scene['configuration']
configuration = DailyWorkerConfiguration(DailySettings(**raw['publication']), raw['catalog_path'],
    DailyCollectorSettings(**raw['collector']), AuthStartupSettings(**raw['authentication']))
session = DailySession(configuration.publication, DirectoryCatalog.load(configuration.catalog_path), clock=clock)
session.attach(publication_approved=True)
password = SessionPassword('SYNTHETIC-PRIVATE-CANARY-62', digest(configuration.payload()))
controller = DailyController(session, configuration, commands={k: tuple(v) for k, v in scene['commands'].items()},
    password=password, clock=clock, activation_approved=True)
controller.initialize(create=True)
while controller.status()['state'] not in ('RUNNING', 'RUNNING_WITH_SOURCE_GAPS'):
    if controller.stopped(): raise SystemExit(70)
    time.sleep(.025)
atomic_json(Path(scene['ready']), {'status': 'RUNNING', 'root': str(controller.root)})
while True: time.sleep(.05)
