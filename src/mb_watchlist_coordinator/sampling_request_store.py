"""SQLite receipt log for sampling requests. Every owned connection closes.

    actor_id is a trusted caller identity, not a field taken from request JSON.
    A future service must authenticate callers before invoking this local API.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable

from .models import ProducerIntent
from .sampling_projection import SamplingMembership, require_aware
from .sampling_requests import (
    RequestEvent, admission_reason, baseline_payload, canonical, digest,
    identifier, plain, replay_requests, request_payload, timestamp, utc_text,
)


class RequestConflictError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class RecordedCommand:
    event: RequestEvent
    inserted: bool


class SamplingRequestStore:
    def __init__(self, path: str | Path, *, session_date: date, baseline: SamplingMembership,
                 clock: Callable[[], datetime] | None = None):
        self.path = Path(path)
        self.session_date = session_date
        self.baseline = baseline
        self.identity = baseline_payload(session_date, baseline)
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path, timeout=5)) as connection:
            # SQLite's context manager handles a transaction, not handle lifetime.
            with connection:
                connection.execute("BEGIN IMMEDIATE")
                tables = {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if tables and "request_identity" not in tables:
                    raise ValueError("Existing database is not a sampling request ledger")
                connection.execute("CREATE TABLE IF NOT EXISTS request_identity (id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL)")
                row = connection.execute("SELECT payload FROM request_identity WHERE id=1").fetchone()
                if row is not None and row[0] != canonical(self.identity):
                    raise ValueError("Request ledger identity/baseline mismatch")
                connection.execute("INSERT OR IGNORE INTO request_identity VALUES (1, ?)", (canonical(self.identity),))
                connection.execute("""CREATE TABLE IF NOT EXISTS request_event (
                    sequence INTEGER PRIMARY KEY,
                    command_id TEXT NOT NULL, kind TEXT NOT NULL, actor_id TEXT NOT NULL,
                    payload TEXT NOT NULL, recorded_at_utc TEXT NOT NULL,
                    accepted INTEGER NOT NULL CHECK(accepted IN (0,1)), rejection_reason TEXT,
                    previous_sha256 TEXT NOT NULL, event_sha256 TEXT NOT NULL,
                    UNIQUE(actor_id, kind, command_id))""")

    def _read(self, connection: sqlite3.Connection) -> tuple[RequestEvent, ...]:
        row = connection.execute("SELECT payload FROM request_identity WHERE id=1").fetchone()
        if row is None or row[0] != canonical(self.identity):
            raise ValueError("Request ledger identity/baseline mismatch")
        events = tuple(RequestEvent(r[0], r[1], r[2], r[3], json.loads(r[4]), timestamp(r[5]),
                                    bool(r[6]), r[7], r[8], r[9]) for r in connection.execute(
                                        "SELECT * FROM request_event ORDER BY sequence"))
        replay_requests(self.session_date, self.baseline, events)
        return events

    def events(self) -> tuple[RequestEvent, ...]:
        with closing(sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
            return self._read(connection)

    def states(self):
        return replay_requests(self.session_date, self.baseline, self.events())

    def submit_request(self, intent: ProducerIntent, *, actor_id: str) -> RecordedCommand:
        return self._record(intent.intent_id, "request", actor_id, request_payload(intent))

    def cancel_request(self, cancellation_id: str, *, owner_id: str, request_id: str,
                       actor_id: str, reason: str | None = None) -> RecordedCommand:
        identifier(owner_id, "owner_id")
        identifier(request_id, "request_id")
        if reason is not None and not isinstance(reason, str):
            raise ValueError("reason must be text or None")
        return self._record(cancellation_id, "cancel", actor_id,
                            {"owner_id": owner_id, "request_id": request_id, "reason": reason})

    def tick(self, tick_id: str) -> RecordedCommand:
        return self._record(tick_id, "tick", "__coordinator__", {})

    def _record(self, command_id: str, kind: str, actor_id: str, payload: dict) -> RecordedCommand:
        identifier(command_id, "command_id")
        identifier(actor_id, "actor_id")
        command = {"command_id": command_id, "kind": kind, "actor_id": actor_id, "payload": payload}
        with closing(sqlite3.connect(self.path, timeout=5)) as connection:
            with connection:
                connection.execute("BEGIN IMMEDIATE")
                events = self._read(connection)
                for previous in events:
                    if (previous.actor_id, previous.kind, previous.command_id) == (actor_id, kind, command_id):
                        if canonical(previous.command_payload()) != canonical(command):
                            raise RequestConflictError("Command identity already has different content")
                        return RecordedCommand(previous, False)
                now = self.clock()
                require_aware(now, "receipt clock")
                state = replay_requests(self.session_date, self.baseline, events)[-1]
                if state.as_of is not None and now < state.as_of:
                    raise ValueError("Request receipt clock moved backwards")
                requests = {(e.payload["producer_id"], e.payload["intent_id"]): e.payload
                            for e in events if e.accepted and e.kind == "request"}
                rejection = admission_reason(kind, actor_id, payload, at=now, session=self.session_date,
                                             baseline=self.baseline, requests=requests)
                event = RequestEvent(state.sequence + 1, command_id, kind, actor_id, payload, now,
                                     rejection is None, rejection, state.event_sha256, "")
                event = replace(event, event_sha256=digest(event.hash_payload()))
                connection.execute("INSERT INTO request_event VALUES (?,?,?,?,?,?,?,?,?,?)",
                                   (event.sequence, command_id, kind, actor_id, canonical(payload), utc_text(now),
                                    int(event.accepted), rejection, event.previous_sha256, event.event_sha256))
                return RecordedCommand(event, True)
