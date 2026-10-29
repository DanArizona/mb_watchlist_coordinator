"""Changed role-lock regression and shutdown checks from the immutable ZIP."""
import importlib.util
import json
import os
from pathlib import Path
import socket
import sys
import time
import unittest

root = Path(sys.argv[1]).resolve()
sys.dont_write_bytecode = True
os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
spec = importlib.util.spec_from_file_location('packet_run', root/'run.py')
packet = importlib.util.module_from_spec(spec)
spec.loader.exec_module(packet)
manifest = packet.inventory()

def denied(*args, **kwargs):
    raise OSError('Network denied in extracted role-entry qualification')

socket.socket.connect = socket.socket.connect_ex = socket.create_connection = socket.getaddrinfo = denied
sys.path[:0] = [str(root/'coordinator/src'), str(root/'market_data/src'), str(root/'coordinator/tests')]
suite = unittest.defaultTestLoader.loadTestsFromNames([
    'test_daily_controller.DailyControllerTests.test_transient_health_probe_on_role_lease_does_not_abort_worker_startup',
    'test_daily_supervision.DailySupervisionTests.test_role_lease_contention_has_a_fixed_budget_and_other_errors_are_not_retried',
    'test_daily_supervision.DailySupervisionTests.test_role_work_raising_service_busy_is_not_replayed_and_releases_ownership',
    'test_daily_shutdown.DailyShutdownTests.test_source_finalization_failure_leaves_other_owned_roles_stopped_and_leases_free'])
started = time.monotonic()
result = unittest.TextTestRunner(verbosity=2).run(suite)
packet.inventory()
report = {'contract': 'daily-role-entry-extracted-qualification-v1',
    'result': 'PASS' if result.wasSuccessful() and not result.skipped else 'FAILED',
    'tests': result.testsRun, 'seconds': time.monotonic()-started,
    'failures': len(result.failures), 'errors': len(result.errors), 'skipped': len(result.skipped),
    'source': manifest['source'], 'network': 'denied', 'production_changes': False}
print(json.dumps(report, indent=2))
raise SystemExit(0 if report['result'] == 'PASS' else 1)
