from datetime import datetime, timedelta, timezone

import pytest

from mb_watchlist_coordinator.adapter_state import (
    AdapterObservedState,
)
from mb_watchlist_coordinator.adapters.tos import (
    MaterializationOperation,
)
from mb_watchlist_coordinator.adapters.tos_runtime import (
    run_tos_reconciliation_step,
)
from mb_watchlist_coordinator.coordinator import (
    WatchlistCoordinator,
)
from mb_watchlist_coordinator.execution import (
    MaterializationExecutionResult,
    MaterializationExecutionStatus,
)
from mb_watchlist_coordinator.models import (
    IntentType,
    ProducerIntent,
)
from mb_watchlist_coordinator.transactions import (
    MaterializationTransactionStatus,
)
from mb_watchlist_coordinator.execution import (
    AdapterObservationResult,
    MaterializationExecutionResult,
    MaterializationExecutionStatus,
)
from mb_watchlist_coordinator.health import (
    AdapterHealthState,
    AdapterHealthStatus,
)


NOW = datetime(2026, 8, 25, 18, 0, tzinfo=timezone.utc)


def make_coordinator(
    symbols: set[str],
) -> WatchlistCoordinator:
    coordinator = WatchlistCoordinator()

    intent = ProducerIntent(
        intent_id="ov-001",
        producer_id="test",
        intent_type=IntentType.BASE_SET,
        symbols=frozenset(symbols),
        created_at=NOW,
    )

    coordinator.accept_intent(
        intent,
        at=NOW,
    )

    return coordinator


class FakeToSExecutor:
    def __init__(
        self,
        *,
        observation: AdapterObservedState | None = None,
        materialized_observation: AdapterObservedState | None = None,
        materialization_status=(
            MaterializationExecutionStatus.OBSERVED
        ),
        reason: str | None = None,
    ) -> None:
        self.observation = observation
        self.materialized_observation = materialized_observation
        self.materialization_status = materialization_status
        self.reason = reason

        self.observe_calls = 0
        self.materialize_calls = []

    def observe(self) -> AdapterObservationResult:
        self.observe_calls += 1

        if self.observation is None:
            raise RuntimeError(
                "Fake executor has no observation"
            )

        return AdapterObservationResult(
            observed_state=self.observation
        )

    def materialize(
        self,
        transaction,
    ) -> MaterializationExecutionResult:
        self.materialize_calls.append(transaction)

        if (
            self.materialization_status
            is MaterializationExecutionStatus.OBSERVED
        ):
            if self.materialized_observation is None:
                raise RuntimeError(
                    "Fake executor has no materialized observation"
                )

            return MaterializationExecutionResult(
                transaction_id=transaction.transaction_id,
                status=MaterializationExecutionStatus.OBSERVED,
                observed_state=self.materialized_observation,
            )

        return MaterializationExecutionResult(
            transaction_id=transaction.transaction_id,
            status=self.materialization_status,
            reason=self.reason,
        )


def test_first_step_observes_unknown_tos_state():
    coordinator = make_coordinator(
        {"AAPL", "NVDA", "TEMC"}
    )

    observed = AdapterObservedState(
        adapter_id="tos",
        symbols=frozenset({"AAPL", "NVDA"}),
        observed_at=NOW,
    )

    executor = FakeToSExecutor(
        observation=observed
    )

    result = run_tos_reconciliation_step(
        coordinator,
        executor,
        at=NOW,
    )

    assert result.plan.operation is (
        MaterializationOperation.OBSERVE
    )
    assert result.transaction is None
    assert result.observed_state == observed

    assert executor.observe_calls == 1
    assert executor.materialize_calls == []

    assert (
        coordinator.adapter_state.trusted_observed(
            "tos"
        )
        == observed
    )


def test_second_step_after_observation_plans_add():
    coordinator = make_coordinator(
        {"AAPL", "NVDA", "TEMC"}
    )

    observed = AdapterObservedState(
        adapter_id="tos",
        symbols=frozenset({"AAPL", "NVDA"}),
        observed_at=NOW,
    )

    coordinator.adapter_state.record_observation(
        observed
    )

    verified = AdapterObservedState(
        adapter_id="tos",
        symbols=frozenset(
            {"AAPL", "NVDA", "TEMC"}
        ),
        observed_at=NOW + timedelta(seconds=5),
    )

    executor = FakeToSExecutor(
        materialized_observation=verified
    )

    result = run_tos_reconciliation_step(
        coordinator,
        executor,
        at=NOW + timedelta(seconds=1),
        transaction_id_factory=lambda: "T19",
    )

    assert result.plan.operation is (
        MaterializationOperation.ADD
    )
    assert result.plan.operation_symbols == frozenset(
        {"TEMC"}
    )

    assert result.transaction is not None
    assert result.transaction.status is (
        MaterializationTransactionStatus.SUCCESS
    )

    confirmed = coordinator.adapter_state.latest_confirmed(
        "tos"
    )

    assert confirmed is not None
    assert confirmed.symbols == frozenset(
        {"AAPL", "NVDA", "TEMC"}
    )


def test_matching_state_is_no_op():
    coordinator = make_coordinator(
        {"AAPL", "NVDA"}
    )

    observed = AdapterObservedState(
        adapter_id="tos",
        symbols=frozenset({"AAPL", "NVDA"}),
        observed_at=NOW,
    )

    coordinator.adapter_state.record_observation(
        observed
    )

    executor = FakeToSExecutor()

    result = run_tos_reconciliation_step(
        coordinator,
        executor,
        at=NOW,
    )

    assert result.plan.operation is (
        MaterializationOperation.NO_OP
    )
    assert result.transaction is None

    assert executor.observe_calls == 0
    assert executor.materialize_calls == []


def test_unexpected_symbol_plans_replace():
    coordinator = make_coordinator(
        {"AAPL", "NVDA"}
    )

    observed = AdapterObservedState(
        adapter_id="tos",
        symbols=frozenset(
            {"AAPL", "NVDA", "TEMC"}
        ),
        observed_at=NOW,
    )

    coordinator.adapter_state.record_observation(
        observed
    )

    verified = AdapterObservedState(
        adapter_id="tos",
        symbols=frozenset({"AAPL", "NVDA"}),
        observed_at=NOW + timedelta(seconds=5),
    )

    executor = FakeToSExecutor(
        materialized_observation=verified
    )

    result = run_tos_reconciliation_step(
        coordinator,
        executor,
        at=NOW + timedelta(seconds=1),
        transaction_id_factory=lambda: "T20",
    )

    assert result.plan.operation is (
        MaterializationOperation.REPLACE
    )

    assert result.transaction is not None
    assert result.transaction.status is (
        MaterializationTransactionStatus.SUCCESS
    )


def test_mismatched_verification_marks_transaction_failed():
    coordinator = make_coordinator(
        {"AAPL", "NVDA", "TEMC"}
    )

    observed = AdapterObservedState(
        adapter_id="tos",
        symbols=frozenset({"AAPL", "NVDA"}),
        observed_at=NOW,
    )

    coordinator.adapter_state.record_observation(
        observed
    )

    still_missing = AdapterObservedState(
        adapter_id="tos",
        symbols=frozenset({"AAPL", "NVDA"}),
        observed_at=NOW + timedelta(seconds=5),
    )

    executor = FakeToSExecutor(
        materialized_observation=still_missing
    )

    result = run_tos_reconciliation_step(
        coordinator,
        executor,
        at=NOW + timedelta(seconds=1),
        transaction_id_factory=lambda: "T21",
    )

    assert result.transaction is not None
    assert result.transaction.status is (
        MaterializationTransactionStatus.FAILED
    )

    assert (
        coordinator.adapter_state.latest_confirmed(
            "tos"
        )
        is None
    )


def test_definite_execution_failure_marks_failed():
    coordinator = make_coordinator(
        {"AAPL", "NVDA", "TEMC"}
    )

    observed = AdapterObservedState(
        adapter_id="tos",
        symbols=frozenset({"AAPL", "NVDA"}),
        observed_at=NOW,
    )

    coordinator.adapter_state.record_observation(
        observed
    )

    executor = FakeToSExecutor(
        materialization_status=(
            MaterializationExecutionStatus.FAILED
        ),
        reason="Import dialog definitely failed",
    )

    result = run_tos_reconciliation_step(
        coordinator,
        executor,
        at=NOW + timedelta(seconds=1),
        transaction_id_factory=lambda: "T22",
    )

    assert result.transaction is not None
    assert result.transaction.status is (
        MaterializationTransactionStatus.FAILED
    )


def test_unknown_outcome_forces_future_observation():
    coordinator = make_coordinator(
        {"AAPL", "NVDA", "TEMC"}
    )

    old_observation = AdapterObservedState(
        adapter_id="tos",
        symbols=frozenset({"AAPL", "NVDA"}),
        observed_at=NOW,
    )

    coordinator.adapter_state.record_observation(
        old_observation
    )

    executor = FakeToSExecutor(
        materialization_status=(
            MaterializationExecutionStatus.OUTCOME_UNKNOWN
        ),
        reason="GUI mutation outcome uncertain",
    )

    result = run_tos_reconciliation_step(
        coordinator,
        executor,
        at=NOW + timedelta(seconds=1),
        transaction_id_factory=lambda: "T23",
    )

    assert result.transaction is not None
    assert result.transaction.status is (
        MaterializationTransactionStatus
        .INTERRUPTED_OUTCOME_UNKNOWN
    )

    assert (
        coordinator.adapter_state.latest_observed(
            "tos"
        )
        == old_observation
    )

    assert (
        coordinator.adapter_state.trusted_observed(
            "tos"
        )
        is None
    )

    next_context = coordinator.adapter_context("tos")

    assert next_context.observed is None


def test_mutation_requires_transaction_id_factory():
    coordinator = make_coordinator(
        {"AAPL", "NVDA", "TEMC"}
    )

    observed = AdapterObservedState(
        adapter_id="tos",
        symbols=frozenset({"AAPL", "NVDA"}),
        observed_at=NOW,
    )

    coordinator.adapter_state.record_observation(
        observed
    )

    executor = FakeToSExecutor()

    with pytest.raises(
        ValueError,
        match="transaction_id_factory",
    ):
        run_tos_reconciliation_step(
            coordinator,
            executor,
            at=NOW + timedelta(seconds=1),
        )


def test_observe_records_returned_health():
    coordinator = make_coordinator(
        {"AAPL", "NVDA"}
    )

    observed = AdapterObservedState(
        adapter_id="tos",
        symbols=frozenset({"AAPL", "NVDA"}),
        observed_at=NOW,
    )

    health = AdapterHealthState(
        adapter_id="tos",
        status=AdapterHealthStatus.DEGRADED,
        observed_at=NOW,
        reason="Scheduled exports unavailable",
    )

    class HealthReportingExecutor(FakeToSExecutor):
        def observe(self) -> AdapterObservationResult:
            self.observe_calls += 1

            return AdapterObservationResult(
                observed_state=observed,
                health_state=health,
            )

    executor = HealthReportingExecutor()

    result = run_tos_reconciliation_step(
        coordinator,
        executor,
        at=NOW,
    )

    assert result.observed_state == observed
    assert result.health_state == health
    assert (
        coordinator.adapter_state.latest_health("tos")
        == health
    )
