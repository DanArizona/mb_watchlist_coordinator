from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from ..adapter_state import AdapterObservedState, AdapterTarget
from ..reconciliation import (
    ReconciliationStatus,
    assess_reconciliation,
)


class MaterializationOperation(StrEnum):
    OBSERVE = "OBSERVE"
    NO_OP = "NO_OP"
    ADD = "ADD"
    REPLACE = "REPLACE"


@dataclass(frozen=True, slots=True)
class ToSMaterializationPlan:
    adapter_id: str
    canonical_revision: int
    operation: MaterializationOperation
    symbols: frozenset[str]


def plan_tos_materialization(
    target: AdapterTarget,
    observed: AdapterObservedState | None,
) -> ToSMaterializationPlan:
    assessment = assess_reconciliation(
        target,
        observed,
    )

    if assessment.status is ReconciliationStatus.OBSERVATION_REQUIRED:
        return ToSMaterializationPlan(
            adapter_id=target.adapter_id,
            canonical_revision=target.canonical_revision,
            operation=MaterializationOperation.OBSERVE,
            symbols=frozenset(),
        )

    if assessment.status is ReconciliationStatus.CURRENT:
        return ToSMaterializationPlan(
            adapter_id=target.adapter_id,
            canonical_revision=target.canonical_revision,
            operation=MaterializationOperation.NO_OP,
            symbols=frozenset(),
        )

    if not assessment.unexpected_symbols:
        return ToSMaterializationPlan(
            adapter_id=target.adapter_id,
            canonical_revision=target.canonical_revision,
            operation=MaterializationOperation.ADD,
            symbols=assessment.missing_symbols,
        )

    return ToSMaterializationPlan(
        adapter_id=target.adapter_id,
        canonical_revision=target.canonical_revision,
        operation=MaterializationOperation.REPLACE,
        symbols=target.symbols,
    )
