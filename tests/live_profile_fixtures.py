"""Trusted synthetic APIs for the new entry; never an operator mode."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
import json

import test_controller_bootstrap as bootstrap_fixture
from test_integrated_identity import Response
from mb_watchlist_coordinator.live_profile import configuration
from mb_watchlist_coordinator.sampling_requests import digest, timestamp

SECRET = bootstrap_fixture.SECRET
INVENTORY = bootstrap_fixture.INVENTORY


def config(root, profile='ordinary'):
    root = Path(root)
    settings = replace(bootstrap_fixture.make_settings(root), catalog_mode='owned_directory',
        catalog_id='', catalog_symbols=(), profile=profile)
    value = configuration(settings, root/'outer_controller', Path(__file__).resolve().parents[1], 'e'*64)
    path = root/'launch.json'; path.write_text(json.dumps(value))
    return value, path, digest(value)


class FakeAPI:
    DEFAULT_POLLING_REFRESH_MARGIN = timedelta(minutes=75, seconds=30)
    def __init__(self, root, events, *, mode='normal', worker=False):
        self.root, self.events, self.mode, self.worker = Path(root), events, mode, worker
    def load_secure_schwab_config(self, path, password):
        self.events.append('load')
        if bytes(password) != SECRET.encode(): raise RuntimeError(SECRET)
        if self.mode == 'load_error': raise RuntimeError(SECRET)
        return object()
    def read_schwab_token_status(self, config, *, observed_at):
        return SimpleNamespace(require_refresh_valid_through=lambda at: None)
    def make_client_from_config(self, config, *, timeout, call_on_auth):
        self.events.append('construct')
        if timeout != 3: raise AssertionError('Original timeout required')
        if not self.worker and self.root.exists(): raise AssertionError('Credentials must precede native creation')
        if self.mode == 'authorization': call_on_auth('https://synthetic.invalid?code='+SECRET)
        events = self.events
        class Client:
            def quotes(self, symbols, *, fields):
                events.append('quote'); return Response(symbols[0])
            def close(self): events.append('close')
        return Client()


class Clock:
    def __init__(self, at):
        self.real, self.logical = datetime.now(timezone.utc), timestamp(at)
    def __call__(self): return self.logical+(datetime.now(timezone.utc)-self.real)
    def set(self, at): self.real, self.logical = datetime.now(timezone.utc), at
    def save(self, path):
        from mb_watchlist_coordinator.recovery_workers import atomic_json
        atomic_json(Path(path), {'real': self.real.isoformat(), 'logical': self.logical.isoformat()})
