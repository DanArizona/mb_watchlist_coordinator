"""Promotion-only sampling projection; no IO, arbitration, or poll scheduling.

This is the first bridge increment. One admitted request may add members to
Focus or Hot inside a fixed Uni. Cancellation, supersession, restrictions,
expiry-driven demotion, and multi-source arbitration require a later reducer.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache

from .lifecycle import select_effective_intents
from .models import IntentType, ProducerIntent


def require_aware(value: datetime, name: str) -> None:
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ValueError(f"{name} must be a timezone-aware datetime")


def _canonical_symbol(value: str) -> bool:
    return (isinstance(value, str) and bool(value) and value == value.strip().upper()
            and not any(c.isspace() or c == ',' for c in value))


@lru_cache(maxsize=4096)
def _canonical_text(value: str) -> bool:
    """Memoize only short, exact built-in strings; never ledger/state validity."""
    return _canonical_symbol(value)


def _symbols(value: frozenset[str], name: str) -> frozenset[str]:
    if isinstance(value, str):
        raise ValueError(f"{name} must be a collection of symbols")
    result = frozenset(value)
    # Subclasses may override string methods; long strings remain supported but
    # do not occupy the bounded cache. Membership nesting is checked every time.
    if any(not (_canonical_text(s) if type(s) is str and len(s) <= 64
                else _canonical_symbol(s)) for s in result):
        raise ValueError(f"{name} must contain canonical uppercase symbols")
    return result


@dataclass(frozen=True, slots=True)
class SamplingMembership:
    uni: frozenset[str]
    focus: frozenset[str]
    hot: frozenset[str]

    def __post_init__(self) -> None:
        for name in ("uni", "focus", "hot"):
            object.__setattr__(self, name, _symbols(getattr(self, name), name))
        if not self.uni or not self.hot <= self.focus <= self.uni:
            raise ValueError("Membership requires nonempty Uni and Hot <= Focus <= Uni")


@dataclass(frozen=True, slots=True)
class PromotionProjection:
    membership: SamplingMembership
    intent_id: str
    producer_id: str
    target_channel: str
    decided_at: datetime


def project_promotion(
    baseline: SamplingMembership,
    intent: ProducerIntent,
    *,
    at: datetime,
) -> PromotionProjection:
    """Project one active ENSURE_PRESENT request without removing any member.

    Producer IDs are attribution, not authentication. The caller must admit
    requests from trusted producers; this function grants no special authority.
    """
    require_aware(at, "at")
    require_aware(intent.created_at, "created_at")
    for name in ("effective_from", "expires_at"):
        value = getattr(intent, name)
        if value is not None:
            require_aware(value, name)
    for name in ("intent_id", "producer_id"):
        value = getattr(intent, name)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} must be nonblank")
    if intent.intent_type != IntentType.ENSURE_PRESENT:
        raise ValueError("This increment accepts ENSURE_PRESENT promotions only")
    if intent.supersession_key is not None:
        raise ValueError("Supersession requires the later multi-request reducer")
    target = intent.metadata.get("sampling_channel")
    if target not in ("focus", "hot"):
        raise ValueError("sampling_channel must be focus or hot")
    requested = _symbols(intent.symbols, "request symbols")
    if not requested:
        raise ValueError("A promotion must request at least one symbol")
    if not requested <= baseline.uni:
        raise ValueError("Promotion cannot add symbols outside the fixed Uni")
    if not select_effective_intents((intent,), at=at):
        raise ValueError("Promotion request is not active at the decision time")
    membership = SamplingMembership(
        uni=baseline.uni,
        focus=baseline.focus | requested,
        hot=baseline.hot | requested if target == "hot" else baseline.hot,
    )
    return PromotionProjection(membership, intent.intent_id, intent.producer_id, target, at)
