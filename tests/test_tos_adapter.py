from datetime import datetime, timezone

from mb_watchlist_coordinator.adapter_state import (
    AdapterObservedState,
    AdapterTarget,
)
from mb_watchlist_coordinator.adapters.tos import (
    MaterializationOperation,
    plan_tos_materialization,
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


def test_unknown_tos_state_requires_observation():
    target = make_target({"AAPL", "NVDA"})

    plan = plan_tos_materialization(
        target,
        None,
    )

    assert plan.operation is MaterializationOperation.OBSERVE
    assert plan.symbols == frozenset()


def test_matching_tos_state_is_no_op():
    target = make_target({"AAPL", "NVDA"})
    observed = make_observed({"AAPL", "NVDA"})

    plan = plan_tos_materialization(
        target,
        observed,
    )

    assert plan.operation is MaterializationOperation.NO_OP
    assert plan.symbols == frozenset()


def test_missing_symbols_only_uses_add():
    target = make_target({"AAPL", "NVDA", "TEMC"})
    observed = make_observed({"AAPL", "NVDA"})

    plan = plan_tos_materialization(
        target,
        observed,
    )

    assert plan.operation is MaterializationOperation.ADD
    assert plan.symbols == frozenset({"TEMC"})


def test_unexpected_symbol_requires_replace():
    target = make_target({"AAPL", "NVDA"})
    observed = make_observed({"AAPL", "NVDA", "TEMC"})

    plan = plan_tos_materialization(
        target,
        observed,
    )

    assert plan.operation is MaterializationOperation.REPLACE
    assert plan.symbols == target.symbols


def test_missing_and_unexpected_symbols_require_replace():
    target = make_target({"AAPL", "NVDA", "TEMC"})
    observed = make_observed({"AAPL", "AMD"})

    plan = plan_tos_materialization(
        target,
        observed,
    )

    assert plan.operation is MaterializationOperation.REPLACE
    assert plan.symbols == frozenset(
        {"AAPL", "NVDA", "TEMC"}
    )


def test_same_projection_on_new_revision_is_no_op():
    target = make_target(
        {"AAPL", "NVDA"},
        revision=65,
    )
    observed = make_observed({"AAPL", "NVDA"})

    plan = plan_tos_materialization(
        target,
        observed,
    )

    assert plan.canonical_revision == 65
    assert plan.operation is MaterializationOperation.NO_OP
