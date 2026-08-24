from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class IntentType(StrEnum):
    BASE_SET = "BASE_SET"
    ENSURE_PRESENT = "ENSURE_PRESENT"
    ENSURE_ABSENT = "ENSURE_ABSENT"
    FORCE_PRESENT = "FORCE_PRESENT"
    FORCE_ABSENT = "FORCE_ABSENT"


@dataclass(frozen=True, slots=True)
class ProducerIntent:
    intent_id: str
    producer_id: str
    intent_type: IntentType
    symbols: frozenset[str]

    created_at: datetime

    source_event_id: str | None = None
    effective_from: datetime | None = None
    expires_at: datetime | None = None
    supersession_key: str | None = None

    reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    