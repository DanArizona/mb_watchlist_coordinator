from datetime import datetime, timezone

import pytest

from mb_watchlist_coordinator.adapter_state import (
    AdapterObservedState,
    AdapterTarget,
)
from mb_watchlist_coordinator.adapters.tos import (
    MaterializationOperation,
    plan_tos_materialization,
    create_tos_materialization_transaction,
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
    assert plan.operation_symbols == frozenset()


def test_matching_tos_state_is_no_op():
    target = make_target({"AAPL", "NVDA"})
    observed = make_observed({"AAPL", "NVDA"})

    plan = plan_tos_materialization(
        target,
        observed,
    )

    assert plan.operation is MaterializationOperation.NO_OP
    assert plan.operation_symbols == frozenset()


def test_missing_symbols_only_uses_add():
    target = make_target({"AAPL", "NVDA", "TEMC"})
    observed = make_observed({"AAPL", "NVDA"})

    plan = plan_tos_materialization(
        target,
        observed,
    )

    assert plan.operation is MaterializationOperation.ADD
    assert plan.operation_symbols == frozenset({"TEMC"})
    assert plan.target_symbols == frozenset(
        {"AAPL", "NVDA", "TEMC"}
    )


def test_unexpected_symbol_requires_replace():
    target = make_target({"AAPL", "NVDA"})
    observed = make_observed({"AAPL", "NVDA", "TEMC"})

    plan = plan_tos_materialization(
        target,
        observed,
    )

    assert plan.operation is MaterializationOperation.REPLACE
    assert plan.operation_symbols == target.symbols


def test_missing_and_unexpected_symbols_require_replace():
    target = make_target({"AAPL", "NVDA", "TEMC"})
    observed = make_observed({"AAPL", "AMD"})

    plan = plan_tos_materialization(
        target,
        observed,
    )

    assert plan.operation is MaterializationOperation.REPLACE
    assert plan.operation_symbols == frozenset(
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


def test_add_plan_creates_materialization_transaction():
    target = make_target({"AAPL", "NVDA", "TEMC"})
    observed = make_observed({"AAPL", "NVDA"})

    plan = plan_tos_materialization(
        target,
        observed,
    )

    transaction = create_tos_materialization_transaction(
        plan,
        transaction_id="T19",
        created_at=NOW,
    )

    assert transaction.transaction_id == "T19"
    assert transaction.target_canonical_revision == 42
    assert transaction.target_symbols == frozenset(
        {"AAPL", "NVDA", "TEMC"}
    )
    assert transaction.operation == "ADD"
    assert transaction.operation_symbols == frozenset({"TEMC"})


def test_replace_plan_creates_materialization_transaction():
    target = make_target({"AAPL", "NVDA"})
    observed = make_observed({"AAPL", "NVDA", "TEMC"})

    plan = plan_tos_materialization(
        target,
        observed,
    )

    transaction = create_tos_materialization_transaction(
        plan,
        transaction_id="T20",
        created_at=NOW,
    )

    assert transaction.operation == "REPLACE"
    assert transaction.target_symbols == frozenset(
        {"AAPL", "NVDA"}
    )
    assert transaction.operation_symbols == frozenset(
        {"AAPL", "NVDA"}
    )


def test_observe_plan_does_not_create_materialization_transaction():
    target = make_target({"AAPL"})

    plan = plan_tos_materialization(
        target,
        None,
    )

    with pytest.raises(
        ValueError,
        match="does not require",
    ):
        create_tos_materialization_transaction(
            plan,
            transaction_id="T21",
            created_at=NOW,
        )


def test_no_op_plan_does_not_create_materialization_transaction():
    target = make_target({"AAPL"})
    observed = make_observed({"AAPL"})

    plan = plan_tos_materialization(
        target,
        observed,
    )

    with pytest.raises(
        ValueError,
        match="does not require",
    ):
        create_tos_materialization_transaction(
            plan,
            transaction_id="T22",
            created_at=NOW,
        )
