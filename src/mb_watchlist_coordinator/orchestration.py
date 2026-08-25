from __future__ import annotations

from datetime import datetime

from .execution import (
    MaterializationExecutionResult,
    MaterializationExecutionStatus,
)
from .state_store import AdapterStateStore
from .transactions import (
    MaterializationTransaction,
    MaterializationTransactionStatus,
    fail_transaction,
    interrupt_transaction,
)
from .verification import (
    MaterializationVerificationResult,
    verify_materialization,
)


def apply_materialization_execution_result(
    store: AdapterStateStore,
    transaction: MaterializationTransaction,
    execution_result: MaterializationExecutionResult,
    *,
    at: datetime,
) -> MaterializationVerificationResult | None:
    if transaction.status is not MaterializationTransactionStatus.ACTIVE:
        raise ValueError(
            f"Transaction {transaction.transaction_id!r} "
            "must be ACTIVE"
        )

    if execution_result.transaction_id != transaction.transaction_id:
        raise ValueError(
            "Transaction mismatch: "
            f"transaction={transaction.transaction_id!r}, "
            f"execution_result={execution_result.transaction_id!r}"
        )

    if execution_result.status is MaterializationExecutionStatus.OBSERVED:
        observed = execution_result.observed_state

        if observed is None:
            raise ValueError(
                "OBSERVED execution result requires observed_state"
            )

        verification = verify_materialization(
            transaction,
            observed,
            at=at,
        )

        store.apply_verification_result(verification)

        return verification

    if execution_result.status is MaterializationExecutionStatus.FAILED:
        failed = fail_transaction(
            transaction,
            at=at,
            reason=execution_result.reason or "Execution failed",
        )

        store.update_transaction(failed)

        return None

    if (
        execution_result.status
        is MaterializationExecutionStatus.OUTCOME_UNKNOWN
    ):
        interrupted = interrupt_transaction(
            transaction,
            at=at,
            reason=execution_result.reason,
        )

        store.update_transaction(interrupted)
        
        store.invalidate_observation(
            transaction.adapter_id,
            at=at,
        )

        return None

    raise ValueError(
        f"Unsupported execution status: "
        f"{execution_result.status!r}"
    )
