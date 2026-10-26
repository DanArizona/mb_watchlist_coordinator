"""Synthetic cooperative-close delay, inside an already owned outer scope."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src'))
import json
import socket
import time
def denied(*a,**kw):raise RuntimeError('Network denied in cleanup fixture')
socket.socket.connect=socket.socket.connect_ex=socket.create_connection=socket.getaddrinfo=denied
from mb_watchlist_coordinator.owned_process_scope import receive_gate
from mb_watchlist_coordinator.recovery_workers import atomic_json
role,path=sys.argv[1:];value=json.loads(Path(path).read_text())
root=Path(value['root']);receive_gate(sys.stdin.buffer,value['nonce'])
if role=='report':
    atomic_json(root/'native-profile-report.json',{
        'outer_nonce':value['nonce'],'preflight_configuration_sha256':value['preflight'],
        'reporting_read_only':True,'result':'READINESS_ONLY'})
    raise SystemExit(0)
atomic_json(root/'controller-status.json',{'contract':'outer-controller-status-v1',
    'nonce':value['nonce'],'phase':'GOAL_COMPLETE' if role=='cooperative' else 'ACTIVE'})
if role=='hang':time.sleep(30);raise SystemExit(1)
while not (root/'STOP.json').exists():time.sleep(.01)
time.sleep(value['close_seconds'])
atomic_json(root/'cooperative-close.json',{'synthetic':True,'completed':True})
raise SystemExit(0)
