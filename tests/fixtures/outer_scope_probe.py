"""Network-denied owned-process fixture; all scenarios are synthetic."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src'))
import json
import os
import socket
import subprocess
import time

def denied(*a,**kw):raise RuntimeError('Network denied in owned outer process fixture')
socket.socket.connect=socket.socket.connect_ex=socket.create_connection=socket.getaddrinfo=denied
from mb_watchlist_coordinator.owned_process_scope import receive_gate
from mb_watchlist_coordinator.recovery_workers import atomic_json
scenario=json.loads(Path(sys.argv[1]).read_text())
nonce=scenario['nonce'];root=Path(scenario['root']);mode=scenario['mode']
receive_gate(sys.stdin.buffer,nonce)
if mode=='lease':
    from mb_watchlist_coordinator.sampling_service import owner_lock
    with owner_lock(root/'owned-descendant.lock'):
        (root/'lease-ready').write_text('owned')
        time.sleep(20)
    raise SystemExit(0)
if mode=='owner_death':
    from mb_watchlist_coordinator.owned_process_scope import OwnedProcessScope
    p=root/'leased-child.json';p.write_text(json.dumps(dict(scenario,mode='lease')))
    inner=OwnedProcessScope((sys.executable,'-I','-B',__file__,str(p)),nonce).launch()
    inner.open_gate();until=time.monotonic()+3
    while not (root/'lease-ready').exists() and time.monotonic()<until:time.sleep(.01)
    if not (root/'lease-ready').exists():raise SystemExit(71)
    os._exit(79)  # OS closes the sole non-inherited Job handle.
if mode=='report':
    atomic_json(root/'report-ready.json',{'nonce':nonce,'synthetic':True})
    raise SystemExit(0)
if mode=='report_hang':time.sleep(90);raise SystemExit(0)
if mode=='echo':
    data=sys.stdin.buffer.read()
    # Output is intentionally untrusted. The parent must not retain it.
    os.write(1,data);os.write(2,data)
if mode=='crash':raise SystemExit(77)
child=None
if mode in ('descendant','orphan'):
    child=subprocess.Popen([sys.executable,'-I','-B','-c',
        'import pathlib,sys,time;pathlib.Path(sys.argv[1]).write_text("started");time.sleep(90)',str(root/'descendant-ready')],
        stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    atomic_json(root/'descendant.json',{'pid':child.pid})
phase='BOOTSTRAPPING' if mode=='bootstrap_hang' else 'ACTIVE'
atomic_json(root/'controller-status.json',{'contract':'outer-controller-status-v1','nonce':nonce,'phase':phase})
if mode=='bad_status':
    atomic_json(root/'controller-status.json',{'nonce':'changed','secret':'SYNTHETIC-OUTER-SECRET'})
if mode=='orphan':raise SystemExit(78)
until=time.monotonic()+scenario.get('complete_after',.05)
while mode not in ('goal','echo','descendant') or time.monotonic()<until:
    if (root/'STOP.json').exists() and mode not in ('hang','bootstrap_hang'):
        break
    time.sleep(.01)
else:
    atomic_json(root/'controller-status.json',{'contract':'outer-controller-status-v1','nonce':nonce,'phase':'GOAL_COMPLETE'})
while not (root/'STOP.json').exists():time.sleep(.01)
if child:
    child.terminate();child.wait(timeout=2)
raise SystemExit(0)
