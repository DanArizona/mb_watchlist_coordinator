"""Owned process-protocol fixture. No provider, credential or quote acquisition."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'src'))
from datetime import datetime, timezone
import json
import os
import socket
import time
from mb_watchlist_coordinator.recovery_workers import atomic_json
from mb_watchlist_coordinator.sampling_requests import digest
from mb_watchlist_coordinator.sampling_service import owner_lock, ServiceBusy

def denied(*a, **kw):raise RuntimeError('No network in recovery process fixture')
socket.socket.connect=socket.socket.connect_ex=socket.create_connection=socket.getaddrinfo=denied
job=json.loads(Path(sys.argv[-1]).read_text(encoding='utf-8'))
value=dict(job);checksum=value.pop('content_sha256')
assert digest(value)==checksum
begin=time.monotonic()
exit_after=next((float(a.split('=',1)[1]) for a in sys.argv[1:-1] if a.startswith('--exit-after=')),None)
hang='--hang' in sys.argv
try:
    with owner_lock(Path(job['lease_path'])):
        current=json.loads(Path(job['registry_path']).read_text(encoding='utf-8'))
        if current['token']!=job['token']:raise SystemExit(3)
        while not Path(job['stop_path']).exists():
            if exit_after is not None and time.monotonic()-begin>=exit_after:break
            if not hang:
                atomic_json(Path(job['heartbeat_path']),{'token':job['token'],
                    'generation':job['generation'],'identity_sha256':digest(job['identity']),
                    'completed_at_utc':datetime.now(timezone.utc).isoformat(),'pid':os.getpid(),
                    'progress':'completed','no_provider_calls':True,
                    'resume_after_utc':job['resume_after_utc']})
            time.sleep(.03)
except ServiceBusy:
    raise SystemExit(4)
