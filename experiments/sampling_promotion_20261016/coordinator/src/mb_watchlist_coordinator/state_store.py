from __future__ import annotations
from datetime import datetime

from .adapter_state import (
    AdapterConfirmedState,
    AdapterObservedState,
)
from .health import AdapterHealthState
from .transactions import (
    MaterializationTransaction,
    MaterializationTransactionStatus,
)
from .verification import MaterializationVerificationResult


_ALLOWED_TRANSACTION_TRANSITIONS = {
    MaterializationTransactionStatus.CREATED: {
        MaterializationTransactionStatus.ACTIVE,
    },
    MaterializationTransactionStatus.ACTIVE: {
        MaterializationTransactionStatus.SUCCESS,
        MaterializationTransactionStatus.FAILED,
        MaterializationTransactionStatus.INTERRUPTED_OUTCOME_UNKNOWN,
    },
    MaterializationTransactionStatus.SUCCESS: set(),
    MaterializationTransactionStatus.FAILED: set(),
    MaterializationTransactionStatus.INTERRUPTED_OUTCOME_UNKNOWN: set(),
}


class AdapterStateStore:
    def __init__(self) -> None:
        self._latest_observed: dict[str, AdapterObservedState] = {}
        self._observation_invalidated_at: dict[str, datetime] = {}
        self._latest_confirmed: dict[str, AdapterConfirmedState] = {}
        self._latest_health: dict[str, AdapterHealthState] = {}

        self._transactions: dict[
            str,
            MaterializationTransaction,
        ] = {}

        self._transaction_history: dict[
            str,
            list[MaterializationTransaction],
        ] = {}

    # def __init__(self) -> None:
    #     self._latest_observed: dict[str, AdapterObservedState] = {}
    #     self._observation_invalidated_at: dict[str, datetime] = {}
    #     self._latest_confirmed: dict[str, AdapterConfirmedState] = {}

    #     self._transactions: dict[
    #         str,
    #         MaterializationTransaction,
    #     ] = {}

    #     self._transaction_history: dict[
    #         str,
    #         list[MaterializationTransaction],
    #     ] = {}

    def latest_observed(
        self,
        adapter_id: str,
    ) -> AdapterObservedState | None:
        return self._latest_observed.get(adapter_id)

    def trusted_observed(
        self,
        adapter_id: str,
    ) -> AdapterObservedState | None:
        observed = self._latest_observed.get(adapter_id)

        if observed is None:
            return None

        invalidated_at = self._observation_invalidated_at.get(
            adapter_id
        )

        if (
            invalidated_at is not None
            and observed.observed_at <= invalidated_at
        ):
            return None

        return observed

    def latest_confirmed(
        self,
        adapter_id: str,
    ) -> AdapterConfirmedState | None:
        return self._latest_confirmed.get(adapter_id)

    def latest_health(
        self,
        adapter_id: str,
    ) -> AdapterHealthState | None:
        return self._latest_health.get(adapter_id)

    def record_health(
        self,
        health: AdapterHealthState,
    ) -> None:
        current = self._latest_health.get(health.adapter_id)

        if (
            current is not None
            and health.observed_at < current.observed_at
        ):
            return

        self._latest_health[health.adapter_id] = health

    def get_transaction(
        self,
        transaction_id: str,
    ) -> MaterializationTransaction | None:
        return self._transactions.get(transaction_id)

    def transaction_history(
        self,
        transaction_id: str,
    ) -> tuple[MaterializationTransaction, ...]:
        return tuple(
            self._transaction_history.get(
                transaction_id,
                (),
            )
        )

    def record_observation(
        self,
        observed: AdapterObservedState,
    ) -> None:
        current = self._latest_observed.get(
            observed.adapter_id
        )

        if (
            current is None
            or observed.observed_at >= current.observed_at
        ):
            self._latest_observed[
                observed.adapter_id
            ] = observed

    def invalidate_observation(
        self,
        adapter_id: str,
        *,
        at: datetime,
    ) -> None:
        current = self._observation_invalidated_at.get(
            adapter_id
        )

        if current is None or at > current:
            self._observation_invalidated_at[
                adapter_id
            ] = at
            
    def record_confirmation(
        self,
        confirmed: AdapterConfirmedState,
    ) -> None:
        current = self._latest_confirmed.get(
            confirmed.adapter_id
        )

        if (
            current is None
            or confirmed.confirmed_at >= current.confirmed_at
        ):
            self._latest_confirmed[
                confirmed.adapter_id
            ] = confirmed

    def record_transaction(
        self,
        transaction: MaterializationTransaction,
    ) -> None:
        if transaction.transaction_id in self._transactions:
            raise ValueError(
                "Duplicate transaction_id: "
                f"{transaction.transaction_id}"
            )

        if (
            transaction.status
            is not MaterializationTransactionStatus.CREATED
        ):
            raise ValueError(
                "New transaction must be CREATED"
            )

        self._transactions[
            transaction.transaction_id
        ] = transaction

        self._transaction_history[
            transaction.transaction_id
        ] = [transaction]

    def update_transaction(
        self,
        transaction: MaterializationTransaction,
    ) -> None:
        current = self._transactions.get(
            transaction.transaction_id
        )

        if current is None:
            raise ValueError(
                "Unknown transaction_id: "
                f"{transaction.transaction_id}"
            )

        self._require_same_binding(
            current,
            transaction,
        )

        if transaction == current:
            return

        allowed = _ALLOWED_TRANSACTION_TRANSITIONS[
            current.status
        ]

        if transaction.status not in allowed:
            raise ValueError(
                "Invalid transaction transition: "
                f"{current.status.value} -> "
                f"{transaction.status.value}"
            )

        self._transactions[
            transaction.transaction_id
        ] = transaction

        self._transaction_history[
            transaction.transaction_id
        ].append(transaction)

    def apply_verification_result(
        self,
        result: MaterializationVerificationResult,
    ) -> None:
        self.update_transaction(result.transaction)
        self.record_observation(result.observed_state)

        if result.confirmed_state is not None:
            self.record_confirmation(
                result.confirmed_state
            )

    @staticmethod
    def _require_same_binding(
        current: MaterializationTransaction,
        updated: MaterializationTransaction,
    ) -> None:
        current_binding = (
            current.adapter_id,
            current.target_canonical_revision,
            current.target_symbols,
            current.operation,
            current.operation_symbols,
            current.created_at,
        )

        updated_binding = (
            updated.adapter_id,
            updated.target_canonical_revision,
            updated.target_symbols,
            updated.operation,
            updated.operation_symbols,
            updated.created_at,
        )

        if current_binding != updated_binding:
            raise ValueError(
                "Materialization transaction binding "
                "cannot change after creation"
            )
