"""Test-owned independent parent, suitable for deliberate parent-loss drills."""
from datetime import datetime,timedelta,timezone
import json
from pathlib import Path
import socket
import sys

scene=json.loads(Path(sys.argv[1]).read_text())
sys.path[:0]=[str(Path(__file__).resolve().parents[2]/'src'),scene['native_src']]
def denied(*a,**kw):raise OSError('Network denied in owned-parent fixture')
socket.socket.connect=socket.socket.connect_ex=socket.create_connection=socket.getaddrinfo=denied
from mb_watchlist_coordinator.daily_operating import DailyOperatingOwner
from mb_watchlist_coordinator.daily_supervision import DailyWorkerConfiguration
from mb_watchlist_coordinator.authenticated_startup import SessionPassword
from mb_watchlist_coordinator.sampling_requests import digest
real,logical=map(datetime.fromisoformat,(scene['real_anchor'],scene['logical_anchor']))
clock=lambda:logical+(datetime.now(timezone.utc)-real)
config=DailyWorkerConfiguration.load(scene['configuration_path'])
owner=DailyOperatingOwner(scene['outer_root'],config,
    commands={role:tuple(command) for role,command in scene['commands'].items()},
    controller_entry=tuple(scene['controller_entry']),reporter_entry=tuple(scene['reporter_entry']),
    clock=clock,activation_approved=True)
owner.run(SessionPassword('SYNTHETIC-PRIVATE-CANARY-62',digest(config.payload())))
