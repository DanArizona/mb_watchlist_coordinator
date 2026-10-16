from __future__ import annotations

from datetime import datetime
from dataclasses import dataclass
from enum import StrEnum

from ..adapter_state import (
    AdapterObservedState,
    AdapterReconciliationContext,
    AdapterTarget,
)
from ..reconciliation import (
    ReconciliationStatus,
    assess_reconciliation,
)
from ..transactions import MaterializationTransaction


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

    target_symbols: frozenset[str]
    operation_symbols: frozenset[str]


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
            target_symbols=target.symbols,
            operation_symbols=frozenset(),
        )

    if assessment.status is ReconciliationStatus.CURRENT:
        return ToSMaterializationPlan(
            adapter_id=target.adapter_id,
            canonical_revision=target.canonical_revision,
            operation=MaterializationOperation.NO_OP,
            target_symbols=target.symbols,
            operation_symbols=frozenset(),
        )

    if not assessment.unexpected_symbols:
        return ToSMaterializationPlan(
            adapter_id=target.adapter_id,
            canonical_revision=target.canonical_revision,
            operation=MaterializationOperation.ADD,
            target_symbols=target.symbols,
            operation_symbols=assessment.missing_symbols,
        )

    return ToSMaterializationPlan(
        adapter_id=target.adapter_id,
        canonical_revision=target.canonical_revision,
        operation=MaterializationOperation.REPLACE,
        target_symbols=target.symbols,
        operation_symbols=target.symbols,
    )


def plan_tos_from_context(
    context: AdapterReconciliationContext,
) -> ToSMaterializationPlan:
    return plan_tos_materialization(
        context.target,
        context.observed,
    )


def create_tos_materialization_transaction(
    plan: ToSMaterializationPlan,
    *,
    transaction_id: str,
    created_at: datetime,
) -> MaterializationTransaction:
    if plan.operation not in {
        MaterializationOperation.ADD,
        MaterializationOperation.REPLACE,
    }:
        raise ValueError(
            f"Operation {plan.operation.value} "
            "does not require a materialization transaction"
        )

    return MaterializationTransaction(
        transaction_id=transaction_id,
        adapter_id=plan.adapter_id,
        target_canonical_revision=plan.canonical_revision,
        target_symbols=plan.target_symbols,
        operation=plan.operation.value,
        operation_symbols=plan.operation_symbols,
        created_at=created_at,
    )
