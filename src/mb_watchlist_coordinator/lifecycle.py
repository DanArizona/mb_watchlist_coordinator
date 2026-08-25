from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from .models import ProducerIntent


def is_intent_time_active(
    intent: ProducerIntent,
    *,
    at: datetime,
) -> bool:
    if at < intent.created_at:
        return False
    
    if intent.effective_from is not None and at < intent.effective_from:
        return False

    if intent.expires_at is not None and at >= intent.expires_at:
        return False

    return True


def select_effective_intents(
    intents: Iterable[ProducerIntent],
    *,
    at: datetime,
) -> tuple[ProducerIntent, ...]:
    all_intents = tuple(intents)

    selected: list[ProducerIntent] = []
    supersession_groups: dict[str, list[ProducerIntent]] = {}

    for intent in all_intents:
        if intent.supersession_key is None:
            if is_intent_time_active(intent, at=at):
                selected.append(intent)
            continue

        supersession_groups.setdefault(
            intent.supersession_key,
            [],
        ).append(intent)

    for group in supersession_groups.values():
        eligible = [
            intent
            for intent in group
            if at >= intent.created_at
            and (
                intent.effective_from is None
                or at >= intent.effective_from
            )
        ]

        if not eligible:
            continue

        winner = max(
            eligible,
            key=lambda intent: (
                intent.created_at,
                intent.intent_id,
            ),
        )

        if is_intent_time_active(winner, at=at):
            selected.append(winner)

    return tuple(
        sorted(
            selected,
            key=lambda intent: (
                intent.created_at,
                intent.intent_id,
            ),
        )
    )
