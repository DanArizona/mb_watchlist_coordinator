"""Development measurement only: synthetic daily collector, no provider/network."""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import socket
import sys
import time
from unittest.mock import patch

root = Path('/workspace/scratch/6ce939acb4eb')
sys.path[:0] = [str(root/'mb_watchlist_daily_operating/src'),
    str(root/'mb_market_data_daily/src'), str(root/'mb_watchlist_daily_operating/tests')]
sys.dont_write_bytecode = True
def denied(*args, **kwargs): raise OSError('Network denied in synthetic capacity probe')
socket.socket.connect = socket.socket.connect_ex = socket.create_connection = socket.getaddrinfo = denied
from test_daily_session import DailySessionTests
from mb_watchlist_coordinator.daily_collector import DailyCollectorSettings, DailyHotCollector
from mb_watchlist_coordinator.daily_session import DailySession
from mb_watchlist_coordinator.sampling_requests import plain

case = DailySessionTests('test_preview_reads_published_anchor_and_creates_no_application_state_or_client')
case.proof_directory_override = str(root/'daily_capacity_baseline_probe')
case.setUp()
case.now = case.at.replace(hour=9, minute=30, second=1)
case.at = case.now+timedelta(seconds=59)
case.session = DailySession(case.settings, case.catalog, clock=lambda: case.now)
case.session.attach(create=True, publication_approved=True)
case.admit()
settings = DailyCollectorSettings(str(case.journal), plain(case.session.service.identity),
    plain(case.session.binding), plain(case.session.claim),
    case.now.replace(second=0).isoformat(), case.now.replace(hour=16, minute=0, second=0).isoformat(), 9360, 1)
collector = DailyHotCollector(settings, publication_session=case.session,
    client_factory=lambda: case.client, clock=lambda: case.now, activation_approved=True)
class Clock(datetime):
    @classmethod
    def now(cls, tz=None): return case.now.astimezone(tz or timezone.utc)
samples = []
try:
    collector.prepare(create=True)
    with patch('mb_market_data.schwab_quotes.datetime', Clock):
        for n in range(1, 257):
            case.now = collector.next.scheduled_at+timedelta(milliseconds=50)
            began = time.perf_counter(); result = collector.tick(); elapsed = time.perf_counter()-began
            assert result['status']=='acquired', result
            samples.append({'n':n,'tick_seconds':elapsed,'native_cycle_seconds':result['cycle_seconds'],
                'state_prepare_seconds':result['state_prepare_seconds'],'spool_and_check_seconds':result['spool_and_check_seconds']})
            if n in (1,16,32,64,128,256):
                print(json.dumps(samples[-1]), flush=True)
            if elapsed > 2:
                print('Actual collector processing already exceeds shortest slot spacing; stop probe.', flush=True)
                break
finally:
    collector.close(); case.close()
    (case.root/'measurements.json').write_text(json.dumps({'contract':'synthetic-daily-growth-development-probe-v1',
        'synthetic_only':True,'logical_clock':True,'provider_capacity_qualified':False,
        'full_session_executed':False,'measurements':samples},indent=2)+'\n')
