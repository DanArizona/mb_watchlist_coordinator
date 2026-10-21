"""Serialized, restartable publication loop for durable nested sampling requests.

Requests, service outcomes, and the market-data journal are separate commits.
An outbox plan commits first. Journal content and its assigned publication time
are verified before acknowledgement. An uncommitted interrupted plan is never
blindly retried: current inputs/time must be reconsidered. No producer executes
this loop and no callback authenticates external users.
"""

from __future__ import annotations

import json
import math
import os
import sqlite3
from contextlib import closing, contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event
from typing import Callable

from .sampling_projection import require_aware
from .sampling_journal import PublicationDeadlineMissed
from .sampling_requests import (canonical, digest, freeze, identifier, membership_payload,
                                plain, timestamp, utc_text)
from .session import session_expiration, session_start


class ServiceBusy(RuntimeError):
    """Another cycle owns this service's OS lock. No work was attempted."""


@dataclass(frozen=True, slots=True)
class PublicationSettings:
    authority_id: str
    poll_seconds: float
    publication_lead_seconds: float
    publish_until: datetime

    def __post_init__(self):
        identifier(self.authority_id, "authority_id")
        require_aware(self.publish_until, "publish_until")
        for name in ("poll_seconds", "publication_lead_seconds"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be positive and finite")
            try:
                self.publish_until + timedelta(seconds=value)
            except OverflowError as exc:
                raise ValueError(f"{name} exceeds datetime range") from exc

    def payload(self):
        return dict(asdict(self), publish_until=utc_text(self.publish_until))


@contextmanager
def owner_lock(path: Path):
    """One local authority across processes, including plan/commit/ACK gaps.

    An OS lock is needed: committing a SQLite plan releases its write lock.
    Closing this handle (including process exit) releases ownership. The file's
    existence alone is never interpreted as a live owner. Local disks only.
    """
    with path.open("a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"0"); handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise ServiceBusy("Publication authority is already running a cycle") from exc
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def next_boundary(events, state, session):
    """Earliest still-relevant activation/expiry/hold boundary after replay time."""
    if state.as_of is None:
        return None
    cancelled = {(e.payload["owner_id"], e.payload["request_id"]) for e in events
                 if e.accepted and e.kind == "cancel"}
    times = []
    for event in events:
        if event.accepted and event.kind == "request":
            r = event.payload
            if (r["producer_id"], r["intent_id"]) in cancelled:
                continue
            start = timestamp(r["effective_from_utc"] or r["created_at_utc"])
            end = min(timestamp(r["expires_at_utc"]) if r["expires_at_utc"] else session_expiration(session),
                      session_expiration(session))
            if start < end:
                times.extend((start, end))
    times.extend(timestamp(r["expires_at_utc"]) for r in state.active_restrictions)
    times.extend(timestamp(h["demotion_at_utc"]) for h in state.demotion_holds)
    return min((t for t in times if t > state.as_of), default=None)


class SamplingPublicationService:
    def __init__(self, path, *, request_store, journal, settings: PublicationSettings,
                 clock: Callable[[], datetime] | None = None):
        self.path = Path(path)
        self.requests = request_store
        self.journal = journal
        self.settings = settings
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        if not session_start(request_store.session_date) < settings.publish_until <= session_expiration(request_store.session_date):
            raise ValueError("publish_until must be within the request session")
        paths = [self.path.resolve(), request_store.path.resolve(), Path(journal.identity["path"]).resolve()]
        if len(set(paths)) != 3:
            raise ValueError("Service, request ledger and journal must be different files")
        if journal.identity["session_date"] != request_store.session_date.isoformat():
            raise ValueError("Journal and request sessions differ")
        self.identity = freeze({"contract": "sampling-publication-service-v1", "request_identity": plain(request_store.identity),
                         "request_path": str(paths[1]), "journal": plain(journal.identity),
                         "settings": settings.payload()})

    @property
    def lock_path(self):
        return self.path.with_name(self.path.name + ".owner.lock")

    def now(self):
        value = self.clock()
        require_aware(value, "service clock")
        return value

    def _configuration(self):
        self.requests._check_configuration()
        current = dict(self.identity, request_identity=plain(self.requests.identity),
                       request_path=str(self.requests.path.resolve()), journal=plain(self.journal.identity),
                       settings=self.settings.payload())
        if canonical(current) != canonical(self.identity):
            raise ValueError("Publication service configuration changed")

    def initialize(self):
        self._configuration()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with owner_lock(self.lock_path), closing(sqlite3.connect(self.path, timeout=5)) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            tables = {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if tables and "publication_identity" not in tables:
                raise ValueError("Existing database is not a publication ledger")
            connection.execute("CREATE TABLE IF NOT EXISTS publication_identity (id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL, anchor TEXT NOT NULL)")
            row = connection.execute("SELECT payload FROM publication_identity WHERE id=1").fetchone()
            if row is not None and row[0] != canonical(self.identity):
                raise ValueError("Publication identity/settings mismatch")
            if row is None:
                self.requests.events()  # validate before binding an anchor
                anchor = self.journal.revisions()
                if not anchor or self._members(anchor[-1]["proposal"]) != membership_payload(self.requests.baseline):
                    raise ValueError("Journal anchor does not match the fixed request baseline")
                if any(r["proposal"]["metadata"].get("publication_contract") == self.identity["contract"] for r in anchor):
                    raise ValueError("Journal already has service publications; restore its original publication ledger")
                connection.execute("INSERT INTO publication_identity VALUES(1,?,?)", (canonical(self.identity), canonical(anchor)))
            connection.execute("CREATE TABLE IF NOT EXISTS publication_event (sequence INTEGER PRIMARY KEY, payload TEXT NOT NULL, previous_sha256 TEXT NOT NULL, event_sha256 TEXT NOT NULL)")
        self.snapshot()

    @staticmethod
    def _members(proposal):
        return {name: list(proposal[name + "_symbols"]) for name in ("uni", "focus", "hot")}

    def _read(self):
        self._configuration()
        with closing(sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True)) as c:
            row = c.execute("SELECT payload,anchor FROM publication_identity WHERE id=1").fetchone()
            if row is None or row[0] != canonical(self.identity):
                raise ValueError("Publication identity/settings mismatch")
            anchor = json.loads(row[1])
            rows = list(c.execute("SELECT * FROM publication_event ORDER BY sequence"))
        events, states = self.requests.validated_history()
        previous = digest({"identity": self.identity, "anchor": anchor})
        outcomes, pending, acknowledgements, processed = [], None, [], 0
        last_time = None
        for sequence, raw, prior, sha in rows:
            payload = json.loads(raw)
            if sequence != len(outcomes) + 1 or prior != previous or sha != digest({"sequence": sequence, "payload": payload, "previous_sha256": prior}):
                raise ValueError("Publication outcome sequence/hash chain differs")
            at = timestamp(payload["recorded_at_utc"])
            if last_time is not None and at < last_time:
                raise ValueError("Publication outcome clock moved backwards")
            last_time = at
            if "request_sequence" in payload:
                n = payload["request_sequence"]
                if not isinstance(n, int) or n < processed or n >= len(states) or payload["request_state_sha256"] != digest(states[n].payload()):
                    raise ValueError("Publication outcome request prefix differs")
            kind = payload["kind"]
            if kind == "plan":
                if pending is not None:
                    raise ValueError("Multiple pending publication plans")
                proposal = payload["proposal"]
                n = payload["request_sequence"]
                if self._members(proposal) != membership_payload(states[n].applied) or proposal["metadata"]["request_state"] != states[n].payload():
                    raise ValueError("Publication plan differs from request replay")
                expected = anchor[-1]["proposal"]["revision"] + len(acknowledgements) + 1
                if proposal["revision"] != expected or self.journal.content_hash(proposal) != payload["content_sha256"]:
                    raise ValueError("Publication plan revision/content differs")
                pending = dict(payload, plan_id=sequence)
            elif kind in ("acknowledged", "abandoned", "write_failed"):
                if pending is None or payload["plan_id"] != pending["plan_id"]:
                    raise ValueError("Publication outcome has no matching pending plan")
                if kind == "acknowledged":
                    receipt = payload["journal_receipt"]
                    if receipt["proposal"] != pending["proposal"] or receipt["content_sha256"] != pending["content_sha256"]:
                        raise ValueError("Journal acknowledgement differs from plan")
                    published = timestamp(receipt["published_at_utc"])
                    if published > timestamp(pending["proposal"]["effective_at_utc"]) or published > at:
                        raise ValueError("Journal publication time differs from acknowledgement")
                    acknowledgements.append(receipt)
                    processed = pending["request_sequence"]
                    pending = None
                elif kind == "abandoned":
                    pending = None
            elif kind == "no_change":
                if pending is not None:
                    raise ValueError("No-change outcome with unresolved plan")
                target = (acknowledgements or anchor)[-1]
                if self._members(target["proposal"]) != membership_payload(states[payload["request_sequence"]].applied) or payload["journal_content_sha256"] != target["content_sha256"]:
                    raise ValueError("No-change outcome differs from journal")
                processed = payload["request_sequence"]
            elif kind not in ("deferred", "closed"):
                raise ValueError("Unsupported publication outcome")
            outcomes.append(dict(payload, sequence=sequence, event_sha256=sha))
            previous = sha
        expected = anchor + acknowledgements
        actual = self.journal.revisions()
        if actual[:len(expected)] != expected or len(actual) not in (len(expected), len(expected) + int(pending is not None)):
            raise ValueError("Journal prefix differs from publication ledger")
        unacknowledged = actual[len(expected):]
        if unacknowledged and (unacknowledged[0]["proposal"] != pending["proposal"] or unacknowledged[0]["content_sha256"] != pending["content_sha256"]):
            raise ValueError("Unacknowledged journal revision differs from pending plan")
        return {"anchor": anchor, "outcomes": outcomes, "pending": pending, "processed_sequence": processed,
                "request_events": events, "request_states": states, "journal": actual,
                "unacknowledged": unacknowledged, "head_sha256": previous}

    def snapshot(self):
        with owner_lock(self.lock_path):
            value = self._read()
            return freeze({k: v for k, v in value.items() if k not in ("request_events", "request_states")})

    def _append(self, snapshot, kind, **payload):
        at = self.now()
        if snapshot["outcomes"] and at < timestamp(snapshot["outcomes"][-1]["recorded_at_utc"]):
            raise ValueError("Service clock moved backwards")
        sequence = len(snapshot["outcomes"]) + 1
        payload = dict(payload, kind=kind, recorded_at_utc=utc_text(at))
        previous = snapshot["head_sha256"]
        sha = digest({"sequence": sequence, "payload": payload, "previous_sha256": previous})
        with closing(sqlite3.connect(self.path, timeout=5)) as c, c:
            c.execute("BEGIN IMMEDIATE")
            # Cross-check the durable head even though the OS lock serializes callers.
            head = c.execute("SELECT sequence,event_sha256 FROM publication_event ORDER BY sequence DESC LIMIT 1").fetchone()
            if head != ((sequence - 1, previous) if sequence > 1 else None):
                raise ValueError("Publication head changed during cycle")
            c.execute("INSERT INTO publication_event VALUES(?,?,?,?)", (sequence, canonical(payload), previous, sha))
        return sequence

    @staticmethod
    def _checkpoint(state):
        return {"request_sequence": state.sequence, "request_state_sha256": digest(state.payload())}

    def cycle(self, *, fault_hook=None):
        """One bounded pass. Hooks are fault injection for isolated proofs only."""
        with owner_lock(self.lock_path):
            s = self._read()
            now = self.now()
            if s["outcomes"] and now < timestamp(s["outcomes"][-1]["recorded_at_utc"]):
                raise ValueError("Service clock moved backwards")
            if s["pending"] is not None:
                if s["unacknowledged"]:
                    self._append(s, "acknowledged", plan_id=s["pending"]["plan_id"], journal_receipt=s["unacknowledged"][0], recovered=True)
                else:
                    self._append(s, "abandoned", plan_id=s["pending"]["plan_id"], reason="interrupted_before_commit_recheck_current_inputs_and_time")
                s = self._read()
            now = self.now()
            state = s["request_states"][-1]
            if state.as_of is not None and now < state.as_of:
                raise ValueError("Service clock precedes committed request receipts")
            boundary = next_boundary(s["request_events"], state, self.requests.session_date)
            if now >= self.settings.publish_until:
                if not s["outcomes"] or s["outcomes"][-1]["kind"] != "closed" or s["outcomes"][-1].get("request_sequence") != state.sequence:
                    self._append(s, "closed", **self._checkpoint(state), reason="publication_window_ended")
                return {"status": "closed", "processed_sequence": s["processed_sequence"], "latest_request_sequence": state.sequence}
            if state.as_of is None or (boundary is not None and boundary <= now):
                self.requests.tick(f"service-{state.sequence}-{utc_text(now)}")
                s = self._read(); state = s["request_states"][-1]
                boundary = next_boundary(s["request_events"], state, self.requests.session_date)
            last = s["journal"][-1]
            baseline_effective = timestamp(s["anchor"][-1]["proposal"]["effective_at_utc"])
            if now < baseline_effective:
                return {"status": "waiting_for_anchor", "next_at_utc": utc_text(baseline_effective)}
            if self._members(last["proposal"]) == membership_payload(state.applied):
                if state.sequence > s["processed_sequence"]:
                    self._append(s, "no_change", **self._checkpoint(state), journal_content_sha256=last["content_sha256"])
                return {"status": "idle", "processed_sequence": state.sequence,
                        "next_at_utc": utc_text(boundary) if boundary else None}
            effective = max(self.now() + timedelta(seconds=self.settings.publication_lead_seconds),
                            timestamp(last["proposal"]["effective_at_utc"]) + timedelta(microseconds=1))
            deadline = min(boundary, self.settings.publish_until) if boundary else self.settings.publish_until
            if effective >= deadline:
                if not s["outcomes"] or s["outcomes"][-1]["kind"] != "deferred" or s["outcomes"][-1].get("request_state_sha256") != digest(state.payload()):
                    self._append(s, "deferred", **self._checkpoint(state), next_at_utc=utc_text(deadline), reason="known_boundary_before_safe_effective_time")
                return {"status": "deferred", "next_at_utc": utc_text(deadline)}
            proposal = {"session_date": self.requests.session_date.isoformat(), "revision": last["proposal"]["revision"] + 1,
                        "effective_at_utc": utc_text(effective),
                        **{k + "_symbols": v for k, v in membership_payload(state.applied).items()},
                        "source": self.settings.authority_id, "reason": "Current durable request/policy checkpoint",
                        "metadata": {"publication_contract": self.identity["contract"], "service_identity_sha256": digest(self.identity),
                                     "request_state": state.payload(), "request_baseline_sha256": s["request_states"][0].event_sha256}}
            plan_id = self._append(s, "plan", **self._checkpoint(state), proposal=proposal, content_sha256=self.journal.content_hash(proposal))
            if fault_hook:
                fault_hook("after_plan")
            s = self._read()
            if self.now() >= effective or s["request_states"][-1].event_sha256 != state.event_sha256:
                self._append(s, "abandoned", plan_id=plan_id, reason="inputs_or_clock_changed_before_commit")
                return {"status": "recheck"}
            try:
                self.journal.publish(proposal)
            except PublicationDeadlineMissed:
                self._append(s, "abandoned", plan_id=plan_id, reason="store_rejected_missed_effective_time")
                return {"status": "recheck"}
            except sqlite3.OperationalError as exc:
                self._append(s, "write_failed", plan_id=plan_id, error_type=type(exc).__name__, error=str(exc))
                raise
            if fault_hook:
                fault_hook("after_commit")
            s = self._read()
            if not s["unacknowledged"]:
                raise ValueError("Journal did not retain the planned revision")
            self._append(s, "acknowledged", plan_id=plan_id, journal_receipt=s["unacknowledged"][0], recovered=False)
            if fault_hook:
                fault_hook("after_ack")
            return {"status": "published", "revision": proposal["revision"], "processed_sequence": state.sequence,
                    "effective_at_utc": proposal["effective_at_utc"]}

    def run(self, stop: Event, *, on_status=None):
        """Poll local receipts and durable timers; stop.wait keeps shutdown responsive.

        Only SQLite operational failures and ownership contention are retried.
        Integrity/configuration errors propagate, leaving existing history intact.
        No API calls, producer restart, or external authentication occur here.
        """
        while not stop.is_set():
            try:
                result = self.cycle()
            except (sqlite3.OperationalError, ServiceBusy) as exc:
                result = {"status": "retrying", "error_type": type(exc).__name__, "error": str(exc)}
            if on_status:
                on_status(result)
            if result["status"] == "closed":
                return result
            wait = self.settings.poll_seconds
            if result.get("next_at_utc"):
                wait = min(wait, max(0.001, (timestamp(result["next_at_utc"]) - self.now()).total_seconds()))
            stop.wait(wait)
        return {"status": "stopped"}
