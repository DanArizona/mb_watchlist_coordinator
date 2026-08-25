from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .adapter_state import AdapterObservedState, AdapterTarget


class ReconciliationStatus(StrEnum):
    OBSERVATION_REQUIRED = "OBSERVATION_REQUIRED"
    CURRENT = "CURRENT"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"


@dataclass(frozen=True, slots=True)
class ReconciliationAssessment:
    adapter_id: str
    canonical_revision: int
    status: ReconciliationStatus

    missing_symbols: frozenset[str] = frozenset()
    unexpected_symbols: frozenset[str] = frozenset()


def assess_reconciliation(
    target: AdapterTarget,
    observed: AdapterObservedState | None,
) -> ReconciliationAssessment:
    if observed is None:
        return ReconciliationAssessment(
            adapter_id=target.adapter_id,
            canonical_revision=target.canonical_revision,
            status=ReconciliationStatus.OBSERVATION_REQUIRED,
        )

    if observed.adapter_id != target.adapter_id:
        raise ValueError(
            "Adapter mismatch: "
            f"target={target.adapter_id!r}, "
            f"observed={observed.adapter_id!r}"
        )

    missing_symbols = target.symbols - observed.symbols
    unexpected_symbols = observed.symbols - target.symbols

    if not missing_symbols and not unexpected_symbols:
        status = ReconciliationStatus.CURRENT
    else:
        status = ReconciliationStatus.RECONCILIATION_REQUIRED

    return ReconciliationAssessment(
        adapter_id=target.adapter_id,
        canonical_revision=target.canonical_revision,
        status=status,
        missing_symbols=frozenset(missing_symbols),
        unexpected_symbols=frozenset(unexpected_symbols),
    )
