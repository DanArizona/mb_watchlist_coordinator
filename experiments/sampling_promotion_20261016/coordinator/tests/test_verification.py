from datetime import datetime, timedelta, timezone

import pytest

from mb_watchlist_coordinator.adapter_state import (
    AdapterObservedState,
)
from mb_watchlist_coordinator.transactions import (
    MaterializationTransaction,
    MaterializationTransactionStatus,
    start_transaction,
)
from mb_watchlist_coordinator.verification import (
    verify_materialization,
)


NOW = datetime(2026, 8, 25, 14, 0, tzinfo=timezone.utc)


def make_active_transaction(
    *,
    operation="ADD",
    operation_symbols=frozenset({"TEMC"}),
) -> MaterializationTransaction:
    created = MaterializationTransaction(
        transaction_id="T19",
        adapter_id="tos",
        target_canonical_revision=44,
        target_symbols=frozenset(
            {"AAPL", "NVDA", "TEMC"}
        ),
        operation=operation,
        operation_symbols=operation_symbols,
        created_at=NOW,
    )

    return start_transaction(
        created,
        at=NOW + timedelta(seconds=1),
    )


def make_observed(
    symbols: set[str],
    *,
    adapter_id="tos",
    evidence_ref="2026-08-25-10-00-05-WL.csv",
) -> AdapterObservedState:
    return AdapterObservedState(
        adapter_id=adapter_id,
        symbols=frozenset(symbols),
        observed_at=NOW + timedelta(seconds=5),
        evidence_ref=evidence_ref,
    )


def test_exact_complete_target_verification_succeeds():
    transaction = make_active_transaction()

    observed = make_observed(
        {"AAPL", "NVDA", "TEMC"}
    )

    result = verify_materialization(
        transaction,
        observed,
        at=NOW + timedelta(seconds=6),
    )

    assert result.transaction.status is (
        MaterializationTransactionStatus.SUCCESS
    )

    assert result.confirmed_state is not None
    assert result.confirmed_state.canonical_revision == 44
    assert result.confirmed_state.symbols == frozenset(
        {"AAPL", "NVDA", "TEMC"}
    )
    assert result.confirmed_state.transaction_id == "T19"


def test_missing_symbol_causes_verification_failure():
    transaction = make_active_transaction()

    observed = make_observed(
        {"AAPL", "NVDA"}
    )

    result = verify_materialization(
        transaction,
        observed,
        at=NOW + timedelta(seconds=6),
    )

    assert result.transaction.status is (
        MaterializationTransactionStatus.FAILED
    )
    assert result.confirmed_state is None
    assert result.missing_symbols == frozenset({"TEMC"})
    assert result.unexpected_symbols == frozenset()


def test_unexpected_symbol_causes_verification_failure():
    transaction = make_active_transaction(
        operation="REPLACE",
        operation_symbols=frozenset(
            {"AAPL", "NVDA", "TEMC"}
        ),
    )

    observed = make_observed(
        {"AAPL", "NVDA", "TEMC", "AMD"}
    )

    result = verify_materialization(
        transaction,
        observed,
        at=NOW + timedelta(seconds=6),
    )

    assert result.transaction.status is (
        MaterializationTransactionStatus.FAILED
    )
    assert result.confirmed_state is None
    assert result.unexpected_symbols == frozenset({"AMD"})


def test_add_verifies_complete_target_not_only_added_symbols():
    transaction = make_active_transaction(
        operation="ADD",
        operation_symbols=frozenset({"TEMC"}),
    )

    observed = make_observed({"TEMC"})

    result = verify_materialization(
        transaction,
        observed,
        at=NOW + timedelta(seconds=6),
    )

    assert result.transaction.status is (
        MaterializationTransactionStatus.FAILED
    )
    assert result.confirmed_state is None
    assert result.missing_symbols == frozenset(
        {"AAPL", "NVDA"}
    )


def test_successful_verification_preserves_evidence_reference():
    transaction = make_active_transaction()

    observed = make_observed(
        {"AAPL", "NVDA", "TEMC"},
        evidence_ref="verified-WL.csv",
    )

    result = verify_materialization(
        transaction,
        observed,
        at=NOW + timedelta(seconds=6),
    )

    assert result.confirmed_state is not None
    assert result.confirmed_state.evidence_ref == (
        "verified-WL.csv"
    )


def test_verification_rejects_wrong_adapter():
    transaction = make_active_transaction()

    observed = make_observed(
        {"AAPL", "NVDA", "TEMC"},
        adapter_id="other",
    )

    with pytest.raises(
        ValueError,
        match="Adapter mismatch",
    ):
        verify_materialization(
            transaction,
            observed,
            at=NOW + timedelta(seconds=6),
        )


def test_created_transaction_cannot_be_verified():
    transaction = MaterializationTransaction(
        transaction_id="T20",
        adapter_id="tos",
        target_canonical_revision=44,
        target_symbols=frozenset({"AAPL"}),
        operation="ADD",
        operation_symbols=frozenset({"AAPL"}),
        created_at=NOW,
    )

    observed = make_observed({"AAPL"})

    with pytest.raises(
        ValueError,
        match="must be ACTIVE",
    ):
        verify_materialization(
            transaction,
            observed,
            at=NOW + timedelta(seconds=6),
        )
