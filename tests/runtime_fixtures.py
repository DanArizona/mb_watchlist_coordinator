"""Synthetic credentials/SDK and scripted transport for coupled runtime tests."""
from contextlib import closing
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
import json
import sqlite3
from types import ModuleType
from unittest.mock import patch

from mb_tools.secure_config import save_ecfg
from mb_watchlist_coordinator.controller_bootstrap import bootstrap_fresh
from mb_watchlist_coordinator.nasdaq_feed_recovery import query_url
from mb_watchlist_coordinator.sampling_requests import timestamp
from test_controller_bootstrap import make_settings, INVENTORY, SECRET
from test_integrated_catalog import catalog
from test_integrated_identity import Response
from test_nasdaq_feed_recovery import EMPTY


class RuntimeFixture:
    def __init__(self, root):
        self.root = Path(root)
        self.settings = replace(make_settings(self.root), catalog_mode='owned_directory',
            catalog_id='', catalog_symbols=())
        self.plan = self.settings.plan()
        self.now = timestamp(self.settings.password_submitted_at_utc)
        self.real = self.logical = None
        self.events, self.response = [], None
        with closing(sqlite3.connect(self.root/'synthetic-token-metadata.sqlite3')) as c, c:
            c.execute('CREATE TABLE schwabdev(access_token_issued TEXT,refresh_token_issued TEXT,expires_in INTEGER)')
            c.execute('INSERT INTO schwabdev VALUES(?,?,?)', (self.now.isoformat(), self.now.isoformat(), 1800))
        save_ecfg(Path(self.settings.ecfg_path), {'SCHWAB_APP_KEY': 'A'*16, 'SCHWAB_APP_SECRET': 'B'*16,
            'SCHWAB_CALLBACK_URL': 'https://synthetic.invalid',
            'SCHWAB_TOKENS_DB': str(self.root/'synthetic-token-metadata.sqlite3'),
            'SCHWAB_TOKEN_DB_FERNET_KEY': 'synthetic-placeholder'}, SECRET)
        fixture = self
        sdk = ModuleType('schwabdev'); sdk.__version__ = '4.0.0'
        class Client:
            def __init__(self, **kw):
                if Path(fixture.settings.experiment_root).exists():
                    raise AssertionError('Bootstrap must precede target creation')
                if kw['timeout'] != 3 or kw['open_browser_for_auth'] is not False:
                    raise AssertionError('Original client limits required')
                fixture.events.append('parent_constructed')
            def quotes(self, symbols, *, fields):
                fixture.events.append(('identity_quote', list(symbols), fields))
                if isinstance(fixture.response, Exception):
                    raise fixture.response
                return fixture.response or Response(symbols[0])
            def close(self):
                fixture.events.append('parent_closed')
        sdk.Client = Client
        self.sdk = sdk
        with patch.dict('sys.modules', schwabdev=sdk):
            self.session = bootstrap_fresh(self.plan, bytearray(SECRET.encode()), clock=self.clock,
                inventory=lambda _: INVENTORY,
                catalog_acquirer=lambda **kw: catalog(self.clock()))
        self.target = Path(self.settings.experiment_root)
        self.start, self.stop = timestamp(self.session.plan.public['start_at_utc']), timestamp(self.session.plan.public['stop_at_utc'])

    def clock(self):
        return self.now if self.real is None else self.logical+(datetime.now(timezone.utc)-self.real)

    def realtime(self, at=None):
        self.real, self.logical = datetime.now(timezone.utc), at or self.start


class ScriptedFeed:
    def __init__(self, transport):
        self.transport, self.responses, self.closed = transport, [], False
        self.calls = 0

    def step(self, query=None, *, stop_requested=lambda: False, **kw):
        if stop_requested():
            return {'status': 'stopped'}
        reservation = self.transport.reserve(query, synthetic=True)
        if reservation is None:
            return {'status': 'waiting'}
        self.calls += 1
        raw = self.responses.pop(0) if self.responses else EMPTY
        self.transport.progress(reservation, {'status_code': 200, 'final_url': query_url(query),
            'headers': {}, 'body_complete': True}, raw)
        self.transport.finish(reservation)
        return {'status': 'completed'}

    def close_owned(self):
        self.closed = True
