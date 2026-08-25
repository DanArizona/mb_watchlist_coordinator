from datetime import datetime, timezone

import pytest

from mb_watchlist_coordinator.adapter_state import (
    AdapterObservedState,
)
from mb_watchlist_coordinator.execution import (
    MaterializationExecutionResult,
    MaterializationExecutionStatus,
    AdapterObservationResult,
)
from mb_watchlist_coordinator.health import (
    AdapterHealthState,
    AdapterHealthStatus,
)


NOW = datetime(2026, 8, 25, 18, 0, tzinfo=timezone.utc)


def make_observed() -> AdapterObservedState:
    return AdapterObservedState(
        adapter_id="tos",
        symbols=frozenset({"AAPL", "NVDA", "TEMC"}),
        observed_at=NOW,
        evidence_ref="verified-WL.csv",
    )


def test_observed_execution_result_contains_observation():
    observed = make_observed()

    result = MaterializationExecutionResult(
        transaction_id="T19",
        status=MaterializationExecutionStatus.OBSERVED,
        observed_state=observed,
    )

    assert result.transaction_id == "T19"
    assert result.status is (
        MaterializationExecutionStatus.OBSERVED
    )
    assert result.observed_state == observed
    assert result.reason is None


def test_failed_execution_result_contains_reason():
    result = MaterializationExecutionResult(
        transaction_id="T19",
        status=MaterializationExecutionStatus.FAILED,
        reason="ToS mutation definitely failed",
    )

    assert result.status is (
        MaterializationExecutionStatus.FAILED
    )
    assert result.observed_state is None
    assert result.reason == "ToS mutation definitely failed"


def test_outcome_unknown_execution_result_contains_reason():
    result = MaterializationExecutionResult(
        transaction_id="T19",
        status=(
            MaterializationExecutionStatus.OUTCOME_UNKNOWN
        ),
        reason="GUI state uncertain after mutation attempt",
    )

    assert result.status is (
        MaterializationExecutionStatus.OUTCOME_UNKNOWN
    )
    assert result.observed_state is None


def test_observed_result_requires_observed_state():
    with pytest.raises(
        ValueError,
        match="requires an observed_state",
    ):
        MaterializationExecutionResult(
            transaction_id="T19",
            status=MaterializationExecutionStatus.OBSERVED,
        )


def test_observed_result_rejects_failure_reason():
    with pytest.raises(
        ValueError,
        match="must not include a failure reason",
    ):
        MaterializationExecutionResult(
            transaction_id="T19",
            status=MaterializationExecutionStatus.OBSERVED,
            observed_state=make_observed(),
            reason="This combination is invalid",
        )


def test_failed_result_rejects_observed_state():
    with pytest.raises(
        ValueError,
        match="must not include observed_state",
    ):
        MaterializationExecutionResult(
            transaction_id="T19",
            status=MaterializationExecutionStatus.FAILED,
            observed_state=make_observed(),
            reason="Mutation failed",
        )


def test_failed_result_requires_reason():
    with pytest.raises(
        ValueError,
        match="requires a reason",
    ):
        MaterializationExecutionResult(
            transaction_id="T19",
            status=MaterializationExecutionStatus.FAILED,
        )


def test_observation_result_can_include_health():
    observed = make_observed()

    health = AdapterHealthState(
        adapter_id="tos",
        status=AdapterHealthStatus.DEGRADED,
        observed_at=NOW,
        reason="Scheduled exports could not be restored",
    )

    result = AdapterObservationResult(
        observed_state=observed,
        health_state=health,
    )

    assert result.observed_state == observed
    assert result.health_state == health


def test_observation_result_rejects_health_for_other_adapter():
    observed = make_observed()

    health = AdapterHealthState(
        adapter_id="other",
        status=AdapterHealthStatus.DEGRADED,
        observed_at=NOW,
        reason="Other adapter degraded",
    )

    with pytest.raises(
        ValueError,
        match="same adapter",
    ):
        AdapterObservationResult(
            observed_state=observed,
            health_state=health,
        )