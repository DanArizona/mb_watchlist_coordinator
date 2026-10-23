"""Owned synthetic gate fault worker; never imports an installed broker SDK."""
from pathlib import Path
import json
import os
import socket
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'src'), str(ROOT/'tests'),
    str(ROOT/'experiments/sampling_promotion_20261016/market_data/src')]


def denied(*a, **kw): raise RuntimeError('Synthetic identity child denies network')
socket.socket.connect = socket.socket.connect_ex = socket.create_connection = socket.getaddrinfo = denied

from test_integrated_identity import build, Response, AT

job = json.load(sys.stdin); root = Path(job['root'])
gate = build(root, lambda: AT)


class Client:
    def quotes(self, symbols, *, fields):
        with (root/'synthetic_quote_calls.txt').open('a') as stream:
            stream.write(symbols[0]+'\n'); stream.flush(); os.fsync(stream.fileno())
        return Response(symbols[0])


def fault(stage):
    if stage == job['stage']: os._exit(75)


gate.deliver_pending(client=Client(), fault_hook=fault,
    after_submit=lambda _: fault('after_request_commit'))
raise SystemExit(76)
