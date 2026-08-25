from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class AdapterTarget:
    adapter_id: str
    canonical_revision: int
    symbols: frozenset[str]


@dataclass(frozen=True, slots=True)
class AdapterObservedState:
    adapter_id: str
    symbols: frozenset[str]
    observed_at: datetime

    evidence_ref: str | None = None


@dataclass(frozen=True, slots=True)
class AdapterConfirmedState:
    adapter_id: str
    canonical_revision: int
    symbols: frozenset[str]
    confirmed_at: datetime

    transaction_id: str | None = None
    evidence_ref: str | None = None
