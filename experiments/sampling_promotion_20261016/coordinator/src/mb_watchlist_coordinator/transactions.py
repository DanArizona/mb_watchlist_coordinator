from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum


class MaterializationTransactionStatus(StrEnum):
    CREATED = "CREATED"
    ACTIVE = "ACTIVE"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    INTERRUPTED_OUTCOME_UNKNOWN = "INTERRUPTED_OUTCOME_UNKNOWN"


@dataclass(frozen=True, slots=True)
class MaterializationTransaction:
    transaction_id: str
    adapter_id: str

    target_canonical_revision: int
    target_symbols: frozenset[str]

    operation: str
    operation_symbols: frozenset[str]

    created_at: datetime
    status: MaterializationTransactionStatus = (
        MaterializationTransactionStatus.CREATED
    )

    started_at: datetime | None = None
    completed_at: datetime | None = None
    failure_reason: str | None = None


def start_transaction(
    transaction: MaterializationTransaction,
    *,
    at: datetime,
) -> MaterializationTransaction:
    _require_status(
        transaction,
        MaterializationTransactionStatus.CREATED,
    )

    return replace(
        transaction,
        status=MaterializationTransactionStatus.ACTIVE,
        started_at=at,
    )


def succeed_transaction(
    transaction: MaterializationTransaction,
    *,
    at: datetime,
) -> MaterializationTransaction:
    _require_status(
        transaction,
        MaterializationTransactionStatus.ACTIVE,
    )

    return replace(
        transaction,
        status=MaterializationTransactionStatus.SUCCESS,
        completed_at=at,
    )


def fail_transaction(
    transaction: MaterializationTransaction,
    *,
    at: datetime,
    reason: str,
) -> MaterializationTransaction:
    _require_status(
        transaction,
        MaterializationTransactionStatus.ACTIVE,
    )

    return replace(
        transaction,
        status=MaterializationTransactionStatus.FAILED,
        completed_at=at,
        failure_reason=reason,
    )


def interrupt_transaction(
    transaction: MaterializationTransaction,
    *,
    at: datetime,
    reason: str | None = None,
) -> MaterializationTransaction:
    _require_status(
        transaction,
        MaterializationTransactionStatus.ACTIVE,
    )

    return replace(
        transaction,
        status=(
            MaterializationTransactionStatus.INTERRUPTED_OUTCOME_UNKNOWN
        ),
        completed_at=at,
        failure_reason=reason,
    )


def _require_status(
    transaction: MaterializationTransaction,
    required: MaterializationTransactionStatus,
) -> None:
    if transaction.status is not required:
        raise ValueError(
            f"Transaction {transaction.transaction_id!r} "
            f"must be {required.value}, "
            f"not {transaction.status.value}"
        )
