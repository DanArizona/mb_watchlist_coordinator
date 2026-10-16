from datetime import datetime, timedelta, timezone

import pytest

from mb_watchlist_coordinator.adapter_state import (
    AdapterConfirmedState,
    AdapterObservedState,
)
from mb_watchlist_coordinator.execution import (
    MaterializationExecutionResult,
    MaterializationExecutionStatus,
)
from mb_watchlist_coordinator.orchestration import (
    apply_materialization_execution_result,
)
from mb_watchlist_coordinator.state_store import (
    AdapterStateStore,
)
from mb_watchlist_coordinator.transactions import (
    MaterializationTransaction,
    MaterializationTransactionStatus,
    start_transaction,
)
from mb_watchlist_coordinator.health import (
    AdapterHealthState,
    AdapterHealthStatus,
)


NOW = datetime(2026, 8, 25, 18, 0, tzinfo=timezone.utc)


def make_active_transaction() -> MaterializationTransaction:
    created = MaterializationTransaction(
        transaction_id="T19",
        adapter_id="tos",
        target_canonical_revision=44,
        target_symbols=frozenset(
            {"AAPL", "NVDA", "TEMC"}
        ),
        operation="ADD",
        operation_symbols=frozenset({"TEMC"}),
        created_at=NOW,
    )

    return start_transaction(
        created,
        at=NOW + timedelta(seconds=1),
    )


def make_store_with_active(
    active: MaterializationTransaction,
) -> AdapterStateStore:
    store = AdapterStateStore()

    created = MaterializationTransaction(
        transaction_id=active.transaction_id,
        adapter_id=active.adapter_id,
        target_canonical_revision=(
            active.target_canonical_revision
        ),
        target_symbols=active.target_symbols,
        operation=active.operation,
        operation_symbols=active.operation_symbols,
        created_at=active.created_at,
    )

    store.record_transaction(created)
    store.update_transaction(active)

    return store


def test_observed_matching_target_marks_success():
    active = make_active_transaction()
    store = make_store_with_active(active)

    observed = AdapterObservedState(
        adapter_id="tos",
        symbols=frozenset(
            {"AAPL", "NVDA", "TEMC"}
        ),
        observed_at=NOW + timedelta(seconds=5),
        evidence_ref="verified-WL.csv",
    )

    execution = MaterializationExecutionResult(
        transaction_id="T19",
        status=MaterializationExecutionStatus.OBSERVED,
        observed_state=observed,
    )

    verification = apply_materialization_execution_result(
        store,
        active,
        execution,
        at=NOW + timedelta(seconds=6),
    )

    assert verification is not None
    assert store.get_transaction("T19").status is (
        MaterializationTransactionStatus.SUCCESS
    )
    assert store.latest_observed("tos") == observed

    confirmed = store.latest_confirmed("tos")
    assert confirmed is not None
    assert confirmed.canonical_revision == 44


def test_observed_mismatch_marks_failed():
    active = make_active_transaction()
    store = make_store_with_active(active)

    observed = AdapterObservedState(
        adapter_id="tos",
        symbols=frozenset({"AAPL", "NVDA"}),
        observed_at=NOW + timedelta(seconds=5),
    )

    execution = MaterializationExecutionResult(
        transaction_id="T19",
        status=MaterializationExecutionStatus.OBSERVED,
        observed_state=observed,
    )

    verification = apply_materialization_execution_result(
        store,
        active,
        execution,
        at=NOW + timedelta(seconds=6),
    )

    assert verification is not None
    assert store.get_transaction("T19").status is (
        MaterializationTransactionStatus.FAILED
    )
    assert store.latest_observed("tos") == observed
    assert store.latest_confirmed("tos") is None


def test_definite_execution_failure_marks_transaction_failed():
    active = make_active_transaction()
    store = make_store_with_active(active)

    execution = MaterializationExecutionResult(
        transaction_id="T19",
        status=MaterializationExecutionStatus.FAILED,
        reason="ToS mutation definitely failed",
    )

    result = apply_materialization_execution_result(
        store,
        active,
        execution,
        at=NOW + timedelta(seconds=6),
    )

    assert result is None

    transaction = store.get_transaction("T19")
    assert transaction is not None
    assert transaction.status is (
        MaterializationTransactionStatus.FAILED
    )
    assert transaction.failure_reason == (
        "ToS mutation definitely failed"
    )


def test_unknown_outcome_marks_transaction_interrupted():
    active = make_active_transaction()
    store = make_store_with_active(active)

    execution = MaterializationExecutionResult(
        transaction_id="T19",
        status=(
            MaterializationExecutionStatus.OUTCOME_UNKNOWN
        ),
        reason="GUI state uncertain after mutation attempt",
    )

    result = apply_materialization_execution_result(
        store,
        active,
        execution,
        at=NOW + timedelta(seconds=6),
    )

    assert result is None

    transaction = store.get_transaction("T19")
    assert transaction is not None
    assert transaction.status is (
        MaterializationTransactionStatus
        .INTERRUPTED_OUTCOME_UNKNOWN
    )


def test_failed_execution_does_not_advance_confirmation():
    active = make_active_transaction()
    store = make_store_with_active(active)

    previous = AdapterConfirmedState(
        adapter_id="tos",
        canonical_revision=43,
        symbols=frozenset({"AAPL", "NVDA"}),
        confirmed_at=NOW - timedelta(minutes=5),
        transaction_id="T18",
    )

    store.record_confirmation(previous)

    execution = MaterializationExecutionResult(
        transaction_id="T19",
        status=MaterializationExecutionStatus.FAILED,
        reason="Mutation failed",
    )

    apply_materialization_execution_result(
        store,
        active,
        execution,
        at=NOW + timedelta(seconds=6),
    )

    assert store.latest_confirmed("tos") == previous


def test_unknown_outcome_does_not_advance_observation():
    active = make_active_transaction()
    store = make_store_with_active(active)

    previous = AdapterObservedState(
        adapter_id="tos",
        symbols=frozenset({"AAPL", "NVDA"}),
        observed_at=NOW - timedelta(minutes=5),
    )

    store.record_observation(previous)

    execution = MaterializationExecutionResult(
        transaction_id="T19",
        status=(
            MaterializationExecutionStatus.OUTCOME_UNKNOWN
        ),
        reason="Could not establish final ToS state",
    )

    apply_materialization_execution_result(
        store,
        active,
        execution,
        at=NOW + timedelta(seconds=6),
    )

    assert store.latest_observed("tos") == previous
    assert store.trusted_observed("tos") is None


def test_execution_result_must_match_transaction():
    active = make_active_transaction()
    store = make_store_with_active(active)

    execution = MaterializationExecutionResult(
        transaction_id="T99",
        status=MaterializationExecutionStatus.FAILED,
        reason="Failure",
    )

    with pytest.raises(
        ValueError,
        match="Transaction mismatch",
    ):
        apply_materialization_execution_result(
            store,
            active,
            execution,
            at=NOW + timedelta(seconds=6),
        )


def test_successful_observation_can_record_degraded_health():
    active = make_active_transaction()
    store = make_store_with_active(active)

    observed = AdapterObservedState(
        adapter_id="tos",
        symbols=frozenset(
            {"AAPL", "NVDA", "TEMC"}
        ),
        observed_at=NOW + timedelta(seconds=5),
    )

    health = AdapterHealthState(
        adapter_id="tos",
        status=AdapterHealthStatus.DEGRADED,
        observed_at=NOW + timedelta(seconds=6),
        reason="Could not restore scheduled exports",
    )

    execution = MaterializationExecutionResult(
        transaction_id="T19",
        status=MaterializationExecutionStatus.OBSERVED,
        observed_state=observed,
        health_state=health,
    )

    apply_materialization_execution_result(
        store,
        active,
        execution,
        at=NOW + timedelta(seconds=6),
    )

    assert store.get_transaction("T19").status is (
        MaterializationTransactionStatus.SUCCESS
    )

    assert store.latest_health("tos") == health
