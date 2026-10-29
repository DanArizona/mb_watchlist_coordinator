"""Actual operating-scope fixture. Synthetic SDK/journal only; no network."""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import socket
import sys
import time

scene_path,role,root,nonce,*extra=sys.argv[1:]
scene=json.loads(Path(scene_path).read_text())
sys.path[:0]=[str(Path(__file__).resolve().parents[2]/'src'),scene['native_src']]
def denied(*args,**kwargs):raise OSError('Network denied in daily operating fixture')
socket.socket.connect=socket.socket.connect_ex=socket.create_connection=socket.getaddrinfo=denied
real,logical=map(datetime.fromisoformat,(scene['real_anchor'],scene['logical_anchor']))
clock=lambda:logical+(datetime.now(timezone.utc)-real)
from mb_watchlist_coordinator.daily_operating_worker import controller_entry,reporter_entry
from mb_watchlist_coordinator.nasdaq_sampling import HaltSnapshot
from mb_watchlist_coordinator.sampling_requests import digest
EMPTY=b'<?xml version="1.0"?><rss version="2.0"><channel><title>Nasdaq Trade Halts</title></channel></rss>'
def on_started(controller):
    (Path(root)/'test-owned-controller.json').write_text(json.dumps({'pid':os.getpid(),'nonce':nonce}))
    if scene.get('admit'):
        at=clock();day=at.astimezone(logical.tzinfo)
        row={'symbol':'NVDA','halt_date':day.strftime('%m/%d/%Y'),
            'halt_time':(day-timedelta(minutes=1)).strftime('%H:%M:%S.%f'),'reason_code':'LUDP'}
        controller.session.cycle(client=controller.identity_client,
            historical_snapshot=HaltSnapshot('outer-saved-history',at,'HISTORICAL',digest([row]),(row,),{'synthetic_only':True}))
    if scene.get('controller_hang'):
        while True:time.sleep(.05)
try:
    if role=='controller':
        controller_entry(root,nonce,clock=clock,on_started=on_started,
            synthetic_factory=lambda:{'clock_at_utc':logical.isoformat(),
                'clock_real_anchor_utc':real.isoformat(),'chunks':[EMPTY.decode()]})
    elif role=='report':
        if scene.get('report_hang'):time.sleep(90)
        reporter_entry(root,nonce,extra[0])
    else:raise ValueError('Unknown owned synthetic role')
except BaseException:
    raise SystemExit(70)
finally:
    if role=='controller':(Path(root)/'test-owned-controller-finally.json').write_text(json.dumps({'nonce':nonce}))
