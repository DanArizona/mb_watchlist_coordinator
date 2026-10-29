"""Targeted extraction check of the changed recovery drill; no full suite repeat."""
import importlib.util
import json
import os
from pathlib import Path
import socket
import sys
import unittest

root = Path(sys.argv[1]).resolve()
sys.dont_write_bytecode = True
os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
spec = importlib.util.spec_from_file_location('packet_run', root/'run.py')
packet = importlib.util.module_from_spec(spec)
spec.loader.exec_module(packet)
manifest = packet.inventory()

def denied(*args, **kwargs):
    raise OSError('Network denied in extracted recovery qualification')

socket.socket.connect = socket.socket.connect_ex = socket.create_connection = socket.getaddrinfo = denied
sys.path[:0] = [str(root/'coordinator/src'), str(root/'market_data/src'), str(root/'coordinator/tests')]
proof = root/'runs'/'targeted-extracted-recovery'
proof.parent.mkdir(parents=True, exist_ok=True)
os.environ['MB_DAILY_CONTROLLER_RECOVERY_PROOF_DIR'] = str(proof)
suite = unittest.defaultTestLoader.loadTestsFromName(
    'test_daily_controller.DailyControllerTests.test_lost_owned_worker_recovers_response_after_full_fifteen_second_hold')
result = unittest.TextTestRunner(verbosity=2).run(suite)
packet.inventory()
if result.wasSuccessful():
    value = json.loads((proof/'recovery-proof.json').read_text())
    assert value['result'] == 'PASS' and value['replacement_crossed_launch_slot']
    print(json.dumps(value, indent=2))
raise SystemExit(0 if result.wasSuccessful() else 1)
