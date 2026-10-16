"""Explicit experimental adapter between Coordinator requests and schema-v2.

Returns a complete publication proposal. The existing store owns the atomic
commit and the actual published_at timestamp. No database is opened here.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from mb_market_data.sampling_membership import SamplingHierarchyRevision
from mb_watchlist_coordinator.models import ProducerIntent
from mb_watchlist_coordinator.sampling_projection import (
    SamplingMembership, project_promotion, require_aware,
)


BRIDGE_CONTRACT = "experimental-single-promotion-v1"


def utc_text(value: datetime | None) -> str | None:
    return value.astimezone(timezone.utc).isoformat() if value is not None else None


def request_payload(intent: ProducerIntent) -> dict:
    # Snapshot mutable metadata and reject non-JSON / nonfinite evidence.
    metadata = json.loads(json.dumps(intent.metadata, allow_nan=False))
    return {
        "intent_id": intent.intent_id,
        "producer_id": intent.producer_id,
        "intent_type": intent.intent_type.value,
        "symbols": sorted(intent.symbols),
        "source_event_id": intent.source_event_id,
        "created_at_utc": utc_text(intent.created_at),
        "effective_from_utc": utc_text(intent.effective_from),
        "expires_at_utc": utc_text(intent.expires_at),
        "supersession_key": intent.supersession_key,
        "reason": intent.reason,
        "metadata": metadata,
    }


def promotion_proposal(
    baseline: SamplingHierarchyRevision,
    intent: ProducerIntent,
    *,
    decided_at: datetime,
    effective_at: datetime,
) -> SamplingHierarchyRevision:
    require_aware(decided_at, "decided_at")
    require_aware(effective_at, "effective_at")
    if baseline.published_at is not None and decided_at < baseline.published_at:
        raise ValueError("Decision cannot precede publication of its baseline")
    if intent.metadata.get("session_date") != baseline.session_date.isoformat():
        raise ValueError("Request session_date must match the baseline session")
    if effective_at < decided_at or effective_at <= baseline.effective_at:
        raise ValueError("Effective time must follow the baseline and not precede the decision")
    if effective_at.astimezone(ZoneInfo("America/New_York")).date() != baseline.session_date:
        raise ValueError("Effective time must fall on the declared ET session date")
    membership = SamplingMembership(
        frozenset(baseline.uni_symbols), frozenset(baseline.focus_symbols),
        frozenset(baseline.hot_symbols),
    )
    projected = project_promotion(membership, intent, at=decided_at)
    if intent.expires_at is not None and effective_at >= intent.expires_at:
        raise ValueError("Request would expire before the promotion takes effect")
    return SamplingHierarchyRevision(
        session_date=baseline.session_date,
        revision=baseline.revision + 1,
        effective_at=effective_at,
        uni_symbols=tuple(projected.membership.uni),
        focus_symbols=tuple(projected.membership.focus),
        hot_symbols=tuple(projected.membership.hot),
        source="watchlist_coordinator_experimental",
        reason=intent.reason,
        metadata={
            "bridge_contract": BRIDGE_CONTRACT,
            "experimental": True,
            "decided_at_utc": utc_text(decided_at),
            "baseline_revision": baseline.revision,
            "baseline_content_sha256": baseline.content_sha256,
            "request": request_payload(intent),
        },
    )
