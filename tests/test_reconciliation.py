from datetime import datetime, timezone

import pytest

from mb_watchlist_coordinator.adapter_state import (
    AdapterObservedState,
    AdapterTarget,
)
from mb_watchlist_coordinator.reconciliation import (
    ReconciliationStatus,
    assess_reconciliation,
)


NOW = datetime(2026, 8, 25, 4, 0, tzinfo=timezone.utc)


def make_target(
    symbols: set[str],
    *,
    revision: int = 42,
) -> AdapterTarget:
    return AdapterTarget(
        adapter_id="tos",
        canonical_revision=revision,
        symbols=frozenset(symbols),
    )


def make_observed(
    symbols: set[str],
) -> AdapterObservedState:
    return AdapterObservedState(
        adapter_id="tos",
        symbols=frozenset(symbols),
        observed_at=NOW,
    )


def test_missing_observation_requires_observation():
    target = make_target({"AAPL", "NVDA"})

    assessment = assess_reconciliation(
        target,
        None,
    )

    assert (
        assessment.status
        is ReconciliationStatus.OBSERVATION_REQUIRED
    )
    assert assessment.missing_symbols == frozenset()
    assert assessment.unexpected_symbols == frozenset()


def test_matching_observation_is_current():
    target = make_target({"AAPL", "NVDA"})
    observed = make_observed({"AAPL", "NVDA"})

    assessment = assess_reconciliation(
        target,
        observed,
    )

    assert assessment.status is ReconciliationStatus.CURRENT
    assert assessment.missing_symbols == frozenset()
    assert assessment.unexpected_symbols == frozenset()


def test_missing_symbol_requires_reconciliation():
    target = make_target({"AAPL", "NVDA", "TEMC"})
    observed = make_observed({"AAPL", "NVDA"})

    assessment = assess_reconciliation(
        target,
        observed,
    )

    assert (
        assessment.status
        is ReconciliationStatus.RECONCILIATION_REQUIRED
    )
    assert assessment.missing_symbols == frozenset({"TEMC"})
    assert assessment.unexpected_symbols == frozenset()


def test_unexpected_symbol_requires_reconciliation():
    target = make_target({"AAPL", "NVDA"})
    observed = make_observed({"AAPL", "NVDA", "TEMC"})

    assessment = assess_reconciliation(
        target,
        observed,
    )

    assert (
        assessment.status
        is ReconciliationStatus.RECONCILIATION_REQUIRED
    )
    assert assessment.missing_symbols == frozenset()
    assert assessment.unexpected_symbols == frozenset({"TEMC"})


def test_missing_and_unexpected_symbols_are_reported():
    target = make_target({"AAPL", "NVDA", "TEMC"})
    observed = make_observed({"AAPL", "AMD"})

    assessment = assess_reconciliation(
        target,
        observed,
    )

    assert assessment.missing_symbols == frozenset(
        {"NVDA", "TEMC"}
    )
    assert assessment.unexpected_symbols == frozenset({"AMD"})


def test_revision_change_with_same_projection_is_current():
    target = make_target(
        {"AAPL", "NVDA"},
        revision=65,
    )
    observed = make_observed({"AAPL", "NVDA"})

    assessment = assess_reconciliation(
        target,
        observed,
    )

    assert assessment.canonical_revision == 65
    assert assessment.status is ReconciliationStatus.CURRENT


def test_observation_from_wrong_adapter_is_rejected():
    target = make_target({"AAPL"})

    observed = AdapterObservedState(
        adapter_id="other",
        symbols=frozenset({"AAPL"}),
        observed_at=NOW,
    )

    with pytest.raises(
        ValueError,
        match="Adapter mismatch",
    ):
        assess_reconciliation(
            target,
            observed,
        )
