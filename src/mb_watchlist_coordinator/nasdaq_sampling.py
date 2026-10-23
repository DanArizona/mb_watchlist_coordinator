"""Durable Nasdaq snapshot -> source-owned request adapter; no network or scheduler.

The first CURRENT snapshot is a baseline. Event identity excludes mutable reason
and resumption fields. Later distinct halts for one symbol have distinct IDs.
Request delivery is retryable across the two SQLite commits; it is not a
membership-publication outbox. Caller identity remains a trusted local boundary.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Mapping
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, time, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .models import IntentType, ProducerIntent
from .sampling_projection import SamplingMembership, require_aware
from .sampling_requests import canonical, digest, freeze, identifier, plain, request_payload, timestamp, utc_text


ET = ZoneInfo("America/New_York")


@dataclass(frozen=True, slots=True)
class HaltProducerSettings:
    producer_id: str
    reason_codes: tuple[str, ...]
    request_lifetime: str
    replay_mode: bool
    reuse_active_symbol_requests: bool = False

    def __post_init__(self):
        identifier(self.producer_id, "producer_id")
        if self.producer_id == "__coordinator__":
            raise ValueError("Reserved producer identity")
        if isinstance(self.reason_codes, str):
            raise ValueError("reason_codes must be a collection")
        if not self.reason_codes or any(not isinstance(c, str) or not re.fullmatch(r"[A-Z0-9]+", c) for c in self.reason_codes):
            raise ValueError("Explicit canonical reason codes required")
        codes = tuple(sorted(set(self.reason_codes)))
        object.__setattr__(self, "reason_codes", codes)
        if self.request_lifetime != "regular_close":
            raise ValueError("Select request_lifetime='regular_close' explicitly")
        if type(self.replay_mode) is not bool:
            raise ValueError("replay_mode must be explicit boolean")
        if type(self.reuse_active_symbol_requests) is not bool:
            raise ValueError("reuse_active_symbol_requests must be boolean")

    def payload(self):
        value = {"producer_id": self.producer_id, "reason_codes": list(self.reason_codes),
                "request_lifetime": self.request_lifetime, "replay_mode": self.replay_mode,
                "first_current_snapshot": "baseline_only", "window_et": ["09:30:00", "16:00:00"]}
        if self.reuse_active_symbol_requests:
            value["reuse_active_symbol_requests"] = True
        return value


def event_time(record: Mapping) -> datetime:
    day = datetime.strptime(record["halt_date"], "%m/%d/%Y").date()
    text = "".join(record["halt_time"].split())
    if not re.fullmatch(r"\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?", text):
        raise ValueError("Invalid halt time")
    return datetime.combine(day, time.fromisoformat(text), ET)


def halt_event_id(record: Mapping) -> str:
    return "nasdaq-halt-" + digest([record["symbol"], utc_text(event_time(record))])


@dataclass(frozen=True, slots=True)
class HaltSnapshot:
    capture_id: str
    retrieved_at: datetime
    retrieval_mode: str
    raw_sha256: str
    records: tuple[Mapping, ...]
    provenance: Mapping

    def __post_init__(self):
        identifier(self.capture_id, "capture_id")
        require_aware(self.retrieved_at, "retrieved_at")
        if self.retrieval_mode not in ("CURRENT", "HISTORICAL"):
            raise ValueError("Unknown retrieval mode")
        if not isinstance(self.raw_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", self.raw_sha256):
            raise ValueError("raw_sha256 must be lowercase SHA-256")
        rows = []
        for source in self.records:
            row = json.loads(canonical(source))
            # Receipt metadata belongs to the snapshot, not mutable event fields.
            row.pop("retrieved_at_et", None)
            row.pop("retrieval_mode", None)
            for field in ("symbol", "halt_date", "halt_time", "reason_code"):
                if not isinstance(row.get(field), str) or not row[field]:
                    raise ValueError("Missing halt field: " + field)
            SamplingMembership(frozenset({row["symbol"]}), frozenset(), frozenset())
            if not re.fullmatch(r"[A-Z0-9]+", row["reason_code"]):
                raise ValueError("Noncanonical reason code")
            at = event_time(row)
            row["halt_time"] = at.strftime("%H:%M:%S.%f")
            rows.append(freeze(row))
        object.__setattr__(self, "records", tuple(rows))
        object.__setattr__(self, "provenance", freeze(json.loads(canonical(self.provenance))))

    def payload(self):
        return {"capture_id": self.capture_id, "retrieved_at_utc": utc_text(self.retrieved_at),
                "retrieval_mode": self.retrieval_mode, "raw_sha256": self.raw_sha256,
                "records": plain(self.records), "provenance": plain(self.provenance)}


def _reduce(identity, receipts):
    """Derive commands and observation outcomes solely from validated input history."""
    previous = digest(identity)
    seen, commands, outcomes = {}, {}, []
    current_started = False
    startup_floor = None
    last_at = last_capture = None
    baseline = identity["request_identity"]["baseline"]
    session = identity["request_identity"]["session_date"]
    settings = identity["settings"]
    start = datetime.combine(datetime.fromisoformat(session).date(), time(9, 30), ET)
    stop = start.replace(hour=16, minute=0)
    capture_ids = set()
    for number, receipt in enumerate(receipts, 1):
        value = dict(receipt)
        checksum = value.pop("event_sha256")
        if value["sequence"] != number or value["previous_sha256"] != previous or digest(value) != checksum:
            raise ValueError("Nasdaq receipt history changed or is incomplete")
        at = timestamp(value["recorded_at_utc"])
        payload = value["snapshot"]
        snap = HaltSnapshot(payload["capture_id"], timestamp(payload["retrieved_at_utc"]),
                            payload["retrieval_mode"], payload["raw_sha256"],
                            tuple(payload["records"]), payload["provenance"])
        if snap.payload() != payload or snap.capture_id in capture_ids:
            raise ValueError("Noncanonical or duplicate snapshot receipt")
        capture_ids.add(snap.capture_id)
        if last_at is not None and at < last_at:
            raise ValueError("Nasdaq receipt clock moved backwards")
        if not settings["replay_mode"] and snap.retrieved_at > at:
            raise ValueError("Capture cannot follow adapter receipt")
        # HISTORICAL queries never create source requests or initialize CURRENT state.
        if snap.retrieval_mode == "HISTORICAL":
            outcomes.append({"capture_id": snap.capture_id, "mode": "HISTORICAL", "events": [],
                             "status": "historical_only"})
            previous, last_at = checksum, at
            continue
        if last_capture is not None and snap.retrieved_at < last_capture:
            raise ValueError("CURRENT captures moved backwards")
        first = not current_started
        current_started = True
        if first:
            startup_floor = at if settings["replay_mode"] else snap.retrieved_at
        unique, observations = {}, []
        for record in snap.records:
            eid = halt_event_id(record)
            if eid in unique and canonical(unique[eid]) != canonical(record):
                raise ValueError("Conflicting rows for one halt within a snapshot")
            unique[eid] = record
        for eid, record in sorted(unique.items()):
            event_at = event_time(record)
            if event_at > at or (not settings["replay_mode"] and event_at > snap.retrieved_at):
                raise ValueError("Halt timestamp follows available knowledge")
            if eid in seen:
                status = "repeat" if canonical(seen[eid]) == canonical(record) else "updated"
            elif first:
                status = "baseline"
            elif event_at.date().isoformat() != session:
                status = "different_session"
            elif event_at < startup_floor:
                status = "predates_startup"
            elif not start <= at < stop:
                status = "outside_receipt_window"
            elif not start <= event_at < stop:
                status = "outside_halt_window"
            elif record["reason_code"] not in settings["reason_codes"]:
                status = "reason_not_selected"
            elif record["symbol"] not in baseline["uni"] and "admission" not in identity["request_identity"]:
                status = "outside_fixed_uni"
            else:
                status = "request_queued"
                commands[eid] = {"intent_id": eid, "producer_id": settings["producer_id"],
                    "symbol": record["symbol"], "created_at_utc": utc_text(at),
                    "expires_at_utc": utc_text(stop), "source_event_id": eid,
                    "reason": "Nasdaq halt " + record["reason_code"],
                    "metadata": {"sampling_channel": "hot", "session_date": session,
                        "halt_event": plain(record), "halt_at_utc": utc_text(event_at),
                        "capture_id": snap.capture_id, "capture_retrieved_at_utc": utc_text(snap.retrieved_at),
                        "capture_raw_sha256": snap.raw_sha256, "capture_provenance": plain(snap.provenance),
                        "adapter_first_seen_at_utc": utc_text(at), "replay_mode": settings["replay_mode"],
                        "producer_receipt_sha256": checksum, "request_lifetime": "regular_close"}}
            seen[eid] = record
            observations.append({"event_id": eid, "symbol": record["symbol"], "status": status})
        outcomes.append({"capture_id": snap.capture_id, "mode": "CURRENT", "events": observations,
                         "status": "initial_baseline" if first else "incremental"})
        previous, last_at, last_capture = checksum, at, snap.retrieved_at
    return commands, outcomes


def _intent(command):
    return ProducerIntent(command["intent_id"], command["producer_id"], IntentType.ENSURE_PRESENT,
        frozenset({command["symbol"]}), timestamp(command["created_at_utc"]),
        expires_at=timestamp(command["expires_at_utc"]), source_event_id=command["source_event_id"],
        reason=command["reason"], metadata=command["metadata"])


class NasdaqSamplingProducer:
    def __init__(self, path: str | Path, *, request_store, settings: HaltProducerSettings, clock=None):
        self.path = Path(path)
        self.request_store = request_store
        self.settings = settings
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.identity = json.loads(canonical({"contract": self.contract,
            "request_identity": request_store.identity, "settings": settings.payload()}))

    @property
    def contract(self):
        return "nasdaq-source-requests-v2" if self.settings.reuse_active_symbol_requests else "nasdaq-source-requests-v1"

    def _check(self):
        self.request_store._check_configuration()
        if self.identity != {"contract": self.contract,
                "request_identity": self.request_store.identity, "settings": self.settings.payload()}:
            raise ValueError("Nasdaq producer configuration changed")

    def initialize(self):
        self._check()
        self.request_store.events()  # Require an initialized, identity-validated request ledger.
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path, timeout=5)) as conn:
            with conn:
                conn.execute("BEGIN IMMEDIATE")
                tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if tables and "halt_identity" not in tables:
                    raise ValueError("Existing database is not a Nasdaq producer ledger")
                conn.execute("CREATE TABLE IF NOT EXISTS halt_identity (id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL)")
                row = conn.execute("SELECT payload FROM halt_identity WHERE id=1").fetchone()
                if row and row[0] != canonical(self.identity):
                    raise ValueError("Nasdaq producer identity mismatch")
                conn.execute("INSERT OR IGNORE INTO halt_identity VALUES (1,?)", (canonical(self.identity),))
                conn.execute("CREATE TABLE IF NOT EXISTS halt_receipt (sequence INTEGER PRIMARY KEY, capture_id TEXT UNIQUE NOT NULL, payload TEXT NOT NULL)")
                conn.execute("CREATE TABLE IF NOT EXISTS halt_delivery (command_id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
                self._read(conn)

    def _read(self, conn):
        self._check()
        row = conn.execute("SELECT payload FROM halt_identity WHERE id=1").fetchone()
        if not row or row[0] != canonical(self.identity):
            raise ValueError("Nasdaq producer identity mismatch")
        receipts = []
        for seq, cid, payload in conn.execute("SELECT * FROM halt_receipt ORDER BY sequence"):
            r = json.loads(payload)
            if r["sequence"] != seq or r["snapshot"]["capture_id"] != cid:
                raise ValueError("Nasdaq receipt columns differ from payload")
            receipts.append(r)
        commands, outcomes = _reduce(self.identity, receipts)
        deliveries = {k: json.loads(v) for k, v in conn.execute("SELECT * FROM halt_delivery")}
        if self.settings.reuse_active_symbol_requests:
            events, _, aliases = self.request_store.validated_reuse_history()
        else:
            events, aliases = self.request_store.events(), {}
        request_events = {(e.actor_id, e.command_id): e for e in events if e.kind == "request"}
        for (owner, cid), alias in aliases.items():
            if owner != self.settings.producer_id or cid not in commands:
                continue
            target = events[alias["request_sequence"]-1]
            original = commands.get(target.command_id)
            expected = {"command_id": cid, "kind": "request", "actor_id": owner,
                        "payload": request_payload(_intent(commands[cid]))}
            if (original is None or canonical(alias["command"]) != canonical(expected)
                    or target.command_payload()["payload"] != request_payload(_intent(original))):
                raise ValueError("Nasdaq pending reuse origin differs")
        for cid, delivery in deliveries.items():
            target_id = delivery.get("reused_request_id", cid)
            event = request_events.get((self.settings.producer_id, target_id))
            command = commands.get(cid)
            alias = aliases.get((self.settings.producer_id, cid))
            reused = target_id != cid
            if reused:
                original = commands.get(target_id)
                target_delivery = deliveries.get(target_id)
                expected_command = {"command_id": cid, "kind": "request", "actor_id": self.settings.producer_id,
                                    "payload": request_payload(_intent(command))} if command else None
                if (not self.settings.reuse_active_symbol_requests or alias is None
                        or alias["receipt_sha256"] != delivery.get("reuse_receipt_sha256")
                        or canonical(alias["command"]) != canonical(expected_command)
                        or original is None or target_delivery is None or not target_delivery["accepted"]
                        or "reused_request_id" in target_delivery or event is None
                        or event.event_sha256 != alias["request_event_sha256"]
                        or event.command_payload()["payload"] != request_payload(_intent(original))):
                    raise ValueError("Nasdaq reused request coverage binding differs")
            elif alias is not None or "reuse_receipt_sha256" in delivery:
                raise ValueError("Nasdaq reuse acknowledgement missing its original request")
            if (cid not in commands or event is None or event.event_sha256 != delivery["request_event_sha256"]
                    or (not reused and event.command_payload()["payload"] != request_payload(_intent(commands[cid])))
                    or delivery["command_sha256"] != digest(commands[cid])
                    or delivery["accepted"] != event.accepted
                    or delivery["request_sequence"] != event.sequence
                    or delivery["rejection_reason"] != event.rejection_reason):
                raise ValueError("Nasdaq delivery acknowledgement differs from request history")
        return receipts, commands, outcomes, deliveries

    def record_snapshot(self, snapshot: HaltSnapshot):
        payload = snapshot.payload()
        with closing(sqlite3.connect(self.path, timeout=5)) as conn:
            with conn:
                conn.execute("BEGIN IMMEDIATE")
                receipts, _, _, _ = self._read(conn)
                for old in receipts:
                    if old["snapshot"]["capture_id"] == snapshot.capture_id:
                        if old["snapshot"] != payload:
                            raise ValueError("Capture ID already has different content")
                        return freeze(old), False
                at = self.clock()
                require_aware(at, "producer receipt clock")
                value = {"sequence": len(receipts) + 1, "snapshot": payload, "recorded_at_utc": utc_text(at),
                         "previous_sha256": receipts[-1]["event_sha256"] if receipts else digest(self.identity)}
                value["event_sha256"] = digest(value)
                _reduce(self.identity, receipts + [value])
                conn.execute("INSERT INTO halt_receipt VALUES (?,?,?)",
                             (value["sequence"], snapshot.capture_id, canonical(value)))
                return freeze(value), True

    def snapshot(self):
        with closing(sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True)) as conn:
            conn.execute("BEGIN")
            receipts, commands, outcomes, deliveries = self._read(conn)
            return freeze({"receipts": receipts, "commands": commands, "outcomes": outcomes,
                           "deliveries": deliveries, "pending": [c for c in commands if c not in deliveries]})

    def deliver_pending(self, *, after_submit=None):
        """One serialized producer worker; request commit precedes producer ACK.

        An interruption after request commit leaves a pending command. Exact retry
        reuses its original request receipt; withdrawal cannot be undone by retry.
        """
        results = []
        with closing(sqlite3.connect(self.path, timeout=5)) as conn:
            with conn:
                conn.execute("BEGIN IMMEDIATE")
                _, commands, _, delivered = self._read(conn)
                for cid, command in commands.items():
                    if cid in delivered:
                        continue
                    alias = None
                    if self.settings.reuse_active_symbol_requests:
                        candidates = [key for key, value in delivered.items()
                                      if value["accepted"] and "reused_request_id" not in value]
                        alias = self.request_store.reuse_active_request(_intent(command),
                            actor_id=self.settings.producer_id, candidate_request_ids=candidates)
                    result = self.request_store.submit_request(_intent(command), actor_id=self.settings.producer_id)
                    if after_submit is not None:
                        after_submit(result)
                    ack = {"command_sha256": digest(command), "request_event_sha256": result.event.event_sha256,
                           "request_sequence": result.event.sequence, "accepted": result.event.accepted,
                           "rejection_reason": result.event.rejection_reason}
                    if alias is not None:
                        ack.update(reused_request_id=result.event.command_id,
                                   reuse_receipt_sha256=alias["receipt_sha256"])
                    conn.execute("INSERT INTO halt_delivery VALUES (?,?)", (cid, canonical(ack)))
                    delivered[cid] = ack
                    results.append(result)
        return tuple(results)
