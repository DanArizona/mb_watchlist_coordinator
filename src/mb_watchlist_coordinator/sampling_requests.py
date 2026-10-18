"""Deterministic, source-owned sampling requests and demotion eligibility.

The caller identity is supplied by a trusted adapter, separately from producer
payloads. This module checks that identity; it does not authenticate a network
caller. Without explicit policy, removals remain eligible and retained. An
explicit policy adds bounded restrictions and replay-derived demotion timers.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from types import MappingProxyType
from typing import Any

from .models import IntentType, ProducerIntent
from .sampling_projection import SamplingMembership, require_aware
from .sampling_policy import SamplingPolicy, apply_policy
from .sampling_admission import AdmissionPolicy
from .session import session_expiration, session_start


CONTRACT = "source-owned-sampling-requests-v1"


def plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {k: plain(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [plain(v) for v in value]
    return value


def canonical(value: Any) -> str:
    return json.dumps(plain(value), sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({k: freeze(v) for k, v in value.items()})
    if isinstance(value, list):
        return tuple(freeze(v) for v in value)
    return value


def identifier(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f"{name} must be a nonblank identifier without surrounding spaces")
    return value


def utc_text(value: datetime) -> str:
    require_aware(value, "timestamp")
    return value.astimezone(timezone.utc).isoformat()


def timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    require_aware(parsed, "timestamp")
    return parsed


def membership_payload(value: SamplingMembership) -> dict:
    return {c: sorted(getattr(value, c)) for c in ("uni", "focus", "hot")}


def baseline_payload(session: date, baseline: SamplingMembership, policy: SamplingPolicy | None = None,
                     admission: AdmissionPolicy | None = None) -> dict:
    if isinstance(session, datetime) or not isinstance(session, date):
        raise ValueError("session must be a date")
    value = {"contract": CONTRACT, "session_date": session.isoformat(),
             "baseline": membership_payload(baseline)}
    if policy is not None:
        for seconds in (policy.demotion_grace_seconds, policy.minimum_residence_seconds):
            try:
                session_expiration(session) + timedelta(seconds=seconds)
            except OverflowError as exc:
                raise ValueError("Policy duration exceeds the session's supported datetime range") from exc
        value.update(contract="source-owned-sampling-policy-v1", policy=policy.payload())
    if admission is not None:
        value.update(contract="source-owned-sampling-admission-v1", admission=admission.payload())
    return value


def request_payload(intent: ProducerIntent, *, allow_uni: bool = False) -> dict:
    identifier(intent.intent_id, "intent_id")
    identifier(intent.producer_id, "producer_id")
    if intent.intent_type != IntentType.ENSURE_PRESENT:
        raise ValueError("Only ENSURE_PRESENT sampling requests are supported")
    if intent.supersession_key is not None:
        raise ValueError("Supersession requires a subsequent policy increment")
    if not intent.symbols:
        raise ValueError("A request must contain symbols")
    # Reuse the canonical-symbol/nesting validation without importing market data.
    members = SamplingMembership(intent.symbols, frozenset(), frozenset())
    if intent.metadata.get("sampling_channel") not in (("uni", "focus", "hot") if allow_uni else ("focus", "hot")):
        raise ValueError("Unsupported sampling_channel for this ledger")
    created = utc_text(intent.created_at)
    effective = utc_text(intent.effective_from) if intent.effective_from is not None else None
    expires = utc_text(intent.expires_at) if intent.expires_at is not None else None
    if expires is not None and timestamp(expires) <= max(
        intent.created_at, intent.effective_from or intent.created_at
    ):
        raise ValueError("expires_at must follow creation and effective_from")
    if intent.reason is not None and not isinstance(intent.reason, str):
        raise ValueError("reason must be text or None")
    if intent.source_event_id is not None:
        identifier(intent.source_event_id, "source_event_id")
    return json.loads(canonical({
        "intent_id": intent.intent_id, "producer_id": intent.producer_id,
        "symbols": sorted(members.uni), "sampling_channel": intent.metadata["sampling_channel"],
        "created_at_utc": created, "effective_from_utc": effective,
        "expires_at_utc": expires, "source_event_id": intent.source_event_id,
        "reason": intent.reason, "metadata": intent.metadata,
    }))


@dataclass(frozen=True, slots=True)
class RequestEvent:
    sequence: int
    command_id: str
    kind: str
    actor_id: str
    payload: Mapping[str, Any]
    recorded_at: datetime
    accepted: bool
    rejection_reason: str | None
    previous_sha256: str
    event_sha256: str

    def __post_init__(self):
        object.__setattr__(self, "payload", freeze(json.loads(canonical(self.payload))))

    def command_payload(self) -> dict:
        return {"command_id": self.command_id, "kind": self.kind,
                "actor_id": self.actor_id, "payload": plain(self.payload)}

    def hash_payload(self) -> dict:
        return {**self.command_payload(), "sequence": self.sequence,
                "recorded_at_utc": utc_text(self.recorded_at), "accepted": self.accepted,
                "rejection_reason": self.rejection_reason, "previous_sha256": self.previous_sha256}


def admission_reason(kind: str, actor: str, payload: Mapping, *, at: datetime,
                     session: date, baseline: SamplingMembership,
                     requests: Mapping, policy: SamplingPolicy | None = None,
                     restrictions: Mapping | None = None, admission: AdmissionPolicy | None = None,
                     admitted_symbols: frozenset[str] = frozenset(),
                     cancelled_requests: frozenset = frozenset()) -> str | None:
    if kind == "tick":
        return None if actor == "__coordinator__" and not payload else "invalid_clock_command"
    if kind == "request":
        if actor != payload["producer_id"] or actor == "__coordinator__":
            return "actor_does_not_own_request"
        if payload["metadata"].get("session_date") != session.isoformat():
            return "session_mismatch"
        if admission is None and not set(payload["symbols"]) <= baseline.uni:
            return "outside_fixed_uni"
        if timestamp(payload["created_at_utc"]) > at:
            return "creation_after_receipt"
        if not session_start(session) <= at < session_expiration(session):
            return "outside_session"
        if payload["expires_at_utc"] is not None and timestamp(payload["expires_at_utc"]) <= at:
            return "request_already_expired"
        if admission is not None:
            if actor not in admission.allowed_sources:
                return "source_not_permitted"
            extra = set(payload["symbols"]) - baseline.uni
            if not extra <= admission.catalog_symbols:
                return "symbol_not_in_admission_catalog"
            reserved = set(admitted_symbols)
            for key, request in requests.items():
                end = min(timestamp(request["expires_at_utc"]) if request["expires_at_utc"]
                          else session_expiration(session), session_expiration(session))
                start = timestamp(request["effective_from_utc"] or request["created_at_utc"])
                if key not in cancelled_requests and at < end and start < end:
                    reserved.update(set(request["symbols"]) - baseline.uni)
            if len(reserved | extra) > admission.max_additional_symbols:
                return "session_admission_capacity"
        return None
    if kind == "cancel":
        if actor != payload["owner_id"]:
            return "actor_does_not_own_request"
        if (payload["owner_id"], payload["request_id"]) not in requests:
            return "unknown_request"
        return None
    if kind in ("restrict", "clear_restriction"):
        if policy is None:
            return "policy_not_configured"
        if actor != policy.super_user_id:
            return "not_restriction_authority"
        if payload["symbol"] not in baseline.uni:
            if admission is None:
                return "outside_fixed_uni"
            if payload["symbol"] not in admission.catalog_symbols:
                return "symbol_not_in_admission_catalog"
        if kind == "restrict":
            if not session_start(session) <= at < session_expiration(session):
                return "outside_session"
            expiry = timestamp(payload["expires_at_utc"])
            if expiry > session_expiration(session):
                return "restriction_exceeds_session"
            if expiry <= at:
                return "restriction_already_expired"
            return None
        current = (restrictions or {}).get(payload["symbol"])
        if current is None or current["restriction_id"] != payload["restriction_id"]:
            return "restriction_not_current"
        return None
    raise ValueError(f"Unsupported request event kind: {kind}")


@dataclass(frozen=True, slots=True)
class RequestState:
    sequence: int
    event_sha256: str
    as_of: datetime | None
    desired: SamplingMembership
    retained: SamplingMembership
    active_requests: tuple[Mapping, ...]
    demotion_eligible_focus: tuple[str, ...]
    demotion_eligible_hot: tuple[str, ...]
    rejected_count: int
    unrestricted_desired: SamplingMembership | None = None
    active_restrictions: tuple[Mapping, ...] = ()
    demotion_holds: tuple[Mapping, ...] = ()
    policy: Mapping | None = None
    admission: Mapping | None = None
    session_additions: tuple[Mapping, ...] = ()

    @property
    def applied(self) -> SamplingMembership:
        """Applied membership; retained is kept as the original API field name."""
        return self.retained

    def reasons_for(self, symbol: str, channel: str) -> tuple[tuple[str, str], ...]:
        if channel not in ("uni", "focus", "hot"):
            raise ValueError("channel must be uni, focus or hot")
        return tuple((r["producer_id"], r["intent_id"]) for r in self.active_requests
                     if symbol in r["symbols"] and
                     (channel == "uni" or r["sampling_channel"] == "hot"
                      or channel == "focus" and r["sampling_channel"] == "focus"))

    def payload(self) -> dict:
        value = {"sequence": self.sequence, "event_sha256": self.event_sha256,
                "as_of_utc": utc_text(self.as_of) if self.as_of is not None else None,
                "desired": membership_payload(self.desired),
                "retained": membership_payload(self.retained),
                "active_requests": plain(self.active_requests),
                "demotion_eligible": {"focus": list(self.demotion_eligible_focus),
                                      "hot": list(self.demotion_eligible_hot)},
                "rejected_count": self.rejected_count,
                "demotion_policy": "not_configured_retain_promoted_members"}
        if self.policy is not None:
            value.update(demotion_policy="configured", policy=plain(self.policy),
                         unrestricted_desired=membership_payload(self.unrestricted_desired),
                         active_restrictions=plain(self.active_restrictions),
                         demotion_holds=plain(self.demotion_holds))
        if self.admission is not None:
            value.update(admission=plain(self.admission), session_additions=plain(self.session_additions))
        return value


def restriction_heads(events: tuple[RequestEvent, ...]) -> dict:
    """Latest set per symbol, including expired heads; no superseded revival."""
    heads = {}
    for event in events:
        if not event.accepted:
            continue
        if event.kind == "restrict":
            heads[event.payload["symbol"]] = event.payload
        elif event.kind == "clear_restriction":
            heads.pop(event.payload["symbol"], None)
    return heads


def replay_requests(session: date, baseline: SamplingMembership,
                    events: tuple[RequestEvent, ...], *, policy: SamplingPolicy | None = None,
                    admission: AdmissionPolicy | None = None) -> tuple[RequestState, ...]:
    """Replay every receipt, including rejected commands and explicit clock ticks.

    Reading alone never advances time. Expiry is evaluated at durable receipt or
    tick timestamps, preserving the same decision on restart and replay.
    """
    seed = digest(baseline_payload(session, baseline, policy, admission))
    config = freeze(policy.payload()) if policy is not None else None
    admission_config = freeze(admission.payload()) if admission is not None else None
    states = [RequestState(0, seed, None, baseline, baseline, (), (), (), 0,
                           baseline if policy is not None else None, policy=config, admission=admission_config)]
    requests: dict[tuple[str, str], Mapping] = {}
    cancelled = set()
    commands = set()
    restrictions = {}
    entered = {(c, s): session_start(session) for c in ("focus", "hot") for s in getattr(baseline, c)}
    missing = {}
    admitted = {}
    request_receipts = {}
    for event in events:
        previous = states[-1]
        if event.sequence != previous.sequence + 1 or event.previous_sha256 != previous.event_sha256:
            raise ValueError("Request event sequence/hash chain is inconsistent")
        if digest(event.hash_payload()) != event.event_sha256:
            raise ValueError("Request event hash is inconsistent")
        if previous.as_of is not None and event.recorded_at < previous.as_of:
            raise ValueError("Request receipt time moved backwards")
        key = (event.actor_id, event.kind, event.command_id)
        if key in commands:
            raise ValueError("Duplicate command in request history")
        commands.add(key)
        reason = admission_reason(event.kind, event.actor_id, event.payload, at=event.recorded_at,
                                  session=session, baseline=baseline, requests=requests,
                                  policy=policy, restrictions=restrictions, admission=admission,
                                  admitted_symbols=frozenset(admitted), cancelled_requests=frozenset(cancelled))
        if event.accepted != (reason is None) or event.rejection_reason != reason:
            raise ValueError("Stored admission outcome differs from replay")
        if event.accepted and event.kind == "request":
            requests[(event.payload["producer_id"], event.payload["intent_id"])] = event.payload
            request_receipts[(event.payload["producer_id"], event.payload["intent_id"])] = event.event_sha256
        if event.accepted and event.kind == "cancel":
            cancelled.add((event.payload["owner_id"], event.payload["request_id"]))
        if event.accepted and event.kind == "restrict":
            restrictions[event.payload["symbol"]] = event.payload
        if event.accepted and event.kind == "clear_restriction":
            restrictions.pop(event.payload["symbol"], None)
        active = []
        for request_key, r in sorted(requests.items()):
            start = timestamp(r["effective_from_utc"] or r["created_at_utc"])
            end = min(timestamp(r["expires_at_utc"]) if r["expires_at_utc"] else session_expiration(session),
                      session_expiration(session))
            if request_key not in cancelled and start <= event.recorded_at < end:
                active.append(r)
        focus, hot = set(baseline.focus), set(baseline.hot)
        for r in active:
            if admission is not None:
                for symbol in sorted(set(r["symbols"]) - baseline.uni):
                    admitted.setdefault(symbol, freeze({"symbol": symbol,
                        "admitted_at_utc": utc_text(event.recorded_at),
                        "producer_id": r["producer_id"], "request_id": r["intent_id"],
                        "request_event_sha256": request_receipts[(r["producer_id"], r["intent_id"])]}))
            if r["sampling_channel"] in ("focus", "hot"):
                focus.update(r["symbols"])
            if r["sampling_channel"] == "hot":
                hot.update(r["symbols"])
        uni = baseline.uni | frozenset(admitted)
        desired = SamplingMembership(uni, frozenset(focus), frozenset(hot))
        unrestricted = desired
        retained = SamplingMembership(uni, previous.retained.focus | desired.focus,
                                       previous.retained.hot | desired.hot)
        active_restrictions = tuple(r for _, r in sorted(restrictions.items())
                                    if event.recorded_at < timestamp(r["expires_at_utc"]))
        holds = ()
        if policy is not None:
            desired, retained, holds = apply_policy(desired, previous.retained, active_restrictions,
                at=event.recorded_at, policy=policy, entered=entered, missing=missing)
        states.append(RequestState(event.sequence, event.event_sha256, event.recorded_at,
                                   desired, retained, tuple(active),
                                   tuple(sorted(retained.focus - desired.focus)),
                                   tuple(sorted(retained.hot - desired.hot)),
                                   previous.rejected_count + int(not event.accepted),
                                   unrestricted if policy is not None else None,
                                   active_restrictions, tuple(freeze(h) for h in holds), config,
                                   admission_config, tuple(admitted[s] for s in sorted(admitted))))
    return tuple(states)
