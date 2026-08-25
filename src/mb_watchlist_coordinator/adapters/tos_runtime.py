from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from ..adapter_state import AdapterObservedState
from ..coordinator import WatchlistCoordinator
from ..execution import MaterializationExecutionResult
from ..orchestration import apply_materialization_execution_result
from ..transactions import (
    MaterializationTransaction,
    start_transaction,
)
from ..verification import MaterializationVerificationResult
from .tos import (
    MaterializationOperation,
    ToSMaterializationPlan,
    create_tos_materialization_transaction,
    plan_tos_from_context,
)


class ToSExecutor(Protocol):
    def observe(self) -> AdapterObservedState:
        ...

    def materialize(
        self,
        transaction: MaterializationTransaction,
    ) -> MaterializationExecutionResult:
        ...


@dataclass(frozen=True, slots=True)
class ToSReconciliationStepResult:
    plan: ToSMaterializationPlan

    transaction: MaterializationTransaction | None = None
    observed_state: AdapterObservedState | None = None
    verification_result: MaterializationVerificationResult | None = None


def run_tos_reconciliation_step(
    coordinator: WatchlistCoordinator,
    executor: ToSExecutor,
    *,
    at: datetime,
    transaction_id_factory: Callable[[], str] | None = None,
) -> ToSReconciliationStepResult:
    context = coordinator.adapter_context("tos")
    plan = plan_tos_from_context(context)

    if plan.operation is MaterializationOperation.OBSERVE:
        observed = executor.observe()

        if observed.adapter_id != "tos":
            raise ValueError(
                "ToS executor returned observation for "
                f"adapter {observed.adapter_id!r}"
            )

        coordinator.adapter_state.record_observation(
            observed
        )

        return ToSReconciliationStepResult(
            plan=plan,
            observed_state=observed,
        )

    if plan.operation is MaterializationOperation.NO_OP:
        return ToSReconciliationStepResult(
            plan=plan,
        )

    if transaction_id_factory is None:
        raise ValueError(
            "Materialization transaction requires "
            "transaction_id_factory"
        )

    created = create_tos_materialization_transaction(
        plan,
        transaction_id=transaction_id_factory(),
        created_at=at,
    )

    coordinator.adapter_state.record_transaction(
        created
    )

    active = start_transaction(
        created,
        at=at,
    )

    coordinator.adapter_state.update_transaction(
        active
    )

    execution_result = executor.materialize(
        active
    )

    verification_result = (
        apply_materialization_execution_result(
            coordinator.adapter_state,
            active,
            execution_result,
            at=at,
        )
    )

    terminal = coordinator.adapter_state.get_transaction(
        created.transaction_id
    )

    if terminal is None:
        raise RuntimeError(
            "Materialization transaction disappeared "
            f"from state store: {created.transaction_id}"
        )

    return ToSReconciliationStepResult(
        plan=plan,
        transaction=terminal,
        verification_result=verification_result,
    )
