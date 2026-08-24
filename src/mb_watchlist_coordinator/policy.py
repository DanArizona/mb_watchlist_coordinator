from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from .models import CanonicalWatchlist, IntentType, ProducerIntent


POLICY_VERSION = "v1"


def build_canonical_watchlist(
    intents: Iterable[ProducerIntent],
    *,
    revision: int,
    created_at: datetime,
) -> CanonicalWatchlist:
    active_intents = tuple(intents)

    base_symbols: set[str] = set()
    ensure_present: set[str] = set()
    ensure_absent: set[str] = set()
    force_present: set[str] = set()
    force_absent: set[str] = set()

    for intent in active_intents:
        if intent.intent_type is IntentType.BASE_SET:
            base_symbols.update(intent.symbols)

        elif intent.intent_type is IntentType.ENSURE_PRESENT:
            ensure_present.update(intent.symbols)

        elif intent.intent_type is IntentType.ENSURE_ABSENT:
            ensure_absent.update(intent.symbols)

        elif intent.intent_type is IntentType.FORCE_PRESENT:
            force_present.update(intent.symbols)

        elif intent.intent_type is IntentType.FORCE_ABSENT:
            force_absent.update(intent.symbols)

        else:
            raise ValueError(f"Unsupported intent type: {intent.intent_type!r}")

    canonical_symbols = base_symbols | ensure_present
    canonical_symbols -= ensure_absent
    canonical_symbols |= force_present
    canonical_symbols -= force_absent

    return CanonicalWatchlist(
        revision=revision,
        symbols=frozenset(canonical_symbols),
        created_at=created_at,
        input_intent_ids=tuple(
            intent.intent_id for intent in active_intents
        ),
        policy_version=POLICY_VERSION,
    )
