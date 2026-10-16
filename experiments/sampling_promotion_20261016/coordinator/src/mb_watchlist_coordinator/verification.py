from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .adapter_state import (
    AdapterConfirmedState,
    AdapterObservedState,
)
from .transactions import (
    MaterializationTransaction,
    MaterializationTransactionStatus,
    fail_transaction,
    succeed_transaction,
)


@dataclass(frozen=True, slots=True)
class MaterializationVerificationResult:
    transaction: MaterializationTransaction
    observed_state: AdapterObservedState
    confirmed_state: AdapterConfirmedState | None

    missing_symbols: frozenset[str] = frozenset()
    unexpected_symbols: frozenset[str] = frozenset()


def verify_materialization(
    transaction: MaterializationTransaction,
    observed: AdapterObservedState,
    *,
    at: datetime,
) -> MaterializationVerificationResult:
    if transaction.status is not MaterializationTransactionStatus.ACTIVE:
        raise ValueError(
            f"Transaction {transaction.transaction_id!r} "
            "must be ACTIVE for verification"
        )

    if observed.adapter_id != transaction.adapter_id:
        raise ValueError(
            "Adapter mismatch: "
            f"transaction={transaction.adapter_id!r}, "
            f"observed={observed.adapter_id!r}"
        )

    missing_symbols = (
        transaction.target_symbols - observed.symbols
    )
    unexpected_symbols = (
        observed.symbols - transaction.target_symbols
    )

    if missing_symbols or unexpected_symbols:
        failed = fail_transaction(
            transaction,
            at=at,
            reason="Complete target verification mismatch",
        )

        return MaterializationVerificationResult(
            transaction=failed,
            observed_state=observed,
            confirmed_state=None,
            missing_symbols=frozenset(missing_symbols),
            unexpected_symbols=frozenset(unexpected_symbols),
        )

    success = succeed_transaction(
        transaction,
        at=at,
    )

    confirmed = AdapterConfirmedState(
        adapter_id=transaction.adapter_id,
        canonical_revision=(
            transaction.target_canonical_revision
        ),
        symbols=observed.symbols,
        confirmed_at=at,
        transaction_id=transaction.transaction_id,
        evidence_ref=observed.evidence_ref,
    )

    return MaterializationVerificationResult(
        transaction=success,
        observed_state=observed,
        confirmed_state=confirmed,
    )