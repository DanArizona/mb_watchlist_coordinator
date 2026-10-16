from datetime import datetime, timedelta, timezone

import pytest

from mb_watchlist_coordinator.transactions import (
    MaterializationTransaction,
    MaterializationTransactionStatus,
    fail_transaction,
    interrupt_transaction,
    start_transaction,
    succeed_transaction,
)


NOW = datetime(2026, 8, 25, 14, 0, tzinfo=timezone.utc)


def make_transaction() -> MaterializationTransaction:
    return MaterializationTransaction(
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


def test_new_transaction_starts_created():
    transaction = make_transaction()

    assert transaction.status is (
        MaterializationTransactionStatus.CREATED
    )
    assert transaction.target_canonical_revision == 44
    assert transaction.target_symbols == frozenset(
        {"AAPL", "NVDA", "TEMC"}
    )
    assert transaction.operation == "ADD"
    assert transaction.operation_symbols == frozenset(
        {"TEMC"}
    )


def test_start_transaction_marks_active():
    created = make_transaction()

    active = start_transaction(
        created,
        at=NOW + timedelta(seconds=1),
    )

    assert created.status is (
        MaterializationTransactionStatus.CREATED
    )
    assert active.status is (
        MaterializationTransactionStatus.ACTIVE
    )
    assert active.started_at == NOW + timedelta(seconds=1)


def test_successful_transaction_is_terminal_success():
    active = start_transaction(
        make_transaction(),
        at=NOW + timedelta(seconds=1),
    )

    success = succeed_transaction(
        active,
        at=NOW + timedelta(seconds=5),
    )

    assert success.status is (
        MaterializationTransactionStatus.SUCCESS
    )
    assert success.completed_at == NOW + timedelta(seconds=5)
    assert success.failure_reason is None


def test_failed_transaction_records_reason():
    active = start_transaction(
        make_transaction(),
        at=NOW + timedelta(seconds=1),
    )

    failed = fail_transaction(
        active,
        at=NOW + timedelta(seconds=5),
        reason="Watchlist verification mismatch",
    )

    assert failed.status is (
        MaterializationTransactionStatus.FAILED
    )
    assert failed.completed_at == NOW + timedelta(seconds=5)
    assert failed.failure_reason == (
        "Watchlist verification mismatch"
    )


def test_interrupted_active_transaction_has_unknown_outcome():
    active = start_transaction(
        make_transaction(),
        at=NOW + timedelta(seconds=1),
    )

    interrupted = interrupt_transaction(
        active,
        at=NOW + timedelta(minutes=2),
        reason="MasterBot restarted",
    )

    assert interrupted.status is (
        MaterializationTransactionStatus.INTERRUPTED_OUTCOME_UNKNOWN
    )
    assert interrupted.failure_reason == "MasterBot restarted"


def test_created_transaction_cannot_be_marked_success():
    created = make_transaction()

    with pytest.raises(
        ValueError,
        match="must be ACTIVE",
    ):
        succeed_transaction(
            created,
            at=NOW + timedelta(seconds=1),
        )


def test_successful_transaction_cannot_be_started_again():
    active = start_transaction(
        make_transaction(),
        at=NOW + timedelta(seconds=1),
    )
    success = succeed_transaction(
        active,
        at=NOW + timedelta(seconds=5),
    )

    with pytest.raises(
        ValueError,
        match="must be CREATED",
    ):
        start_transaction(
            success,
            at=NOW + timedelta(seconds=10),
        )


def test_transaction_state_updates_are_immutable():
    created = make_transaction()

    active = start_transaction(
        created,
        at=NOW + timedelta(seconds=1),
    )

    assert created is not active
    assert created.status is (
        MaterializationTransactionStatus.CREATED
    )
    assert created.started_at is None
