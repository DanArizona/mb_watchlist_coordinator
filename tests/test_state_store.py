from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from mb_watchlist_coordinator.adapter_state import (
    AdapterConfirmedState,
    AdapterObservedState,
)
from mb_watchlist_coordinator.state_store import (
    AdapterStateStore,
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


def make_transaction(
    transaction_id="T19",
) -> MaterializationTransaction:
    return MaterializationTransaction(
        transaction_id=transaction_id,
        adapter_id="tos",
        target_canonical_revision=44,
        target_symbols=frozenset(
            {"AAPL", "NVDA", "TEMC"}
        ),
        operation="ADD",
        operation_symbols=frozenset({"TEMC"}),
        created_at=NOW,
    )


def make_observed(
    symbols: set[str],
    *,
    observed_at=NOW,
) -> AdapterObservedState:
    return AdapterObservedState(
        adapter_id="tos",
        symbols=frozenset(symbols),
        observed_at=observed_at,
    )


def test_empty_store_has_no_adapter_state():
    store = AdapterStateStore()

    assert store.latest_observed("tos") is None
    assert store.latest_confirmed("tos") is None


def test_record_observation_sets_latest_observed():
    store = AdapterStateStore()

    observed = make_observed({"AAPL", "NVDA"})

    store.record_observation(observed)

    assert store.latest_observed("tos") == observed


def test_older_observation_does_not_replace_newer_observation():
    store = AdapterStateStore()

    newer = make_observed(
        {"AAPL", "NVDA"},
        observed_at=NOW + timedelta(minutes=5),
    )
    older = make_observed(
        {"AAPL"},
        observed_at=NOW,
    )

    store.record_observation(newer)
    store.record_observation(older)

    assert store.latest_observed("tos") == newer


def test_record_confirmation_sets_latest_confirmed():
    store = AdapterStateStore()

    confirmed = AdapterConfirmedState(
        adapter_id="tos",
        canonical_revision=44,
        symbols=frozenset({"AAPL", "NVDA"}),
        confirmed_at=NOW,
        transaction_id="T19",
    )

    store.record_confirmation(confirmed)

    assert store.latest_confirmed("tos") == confirmed


def test_older_confirmation_does_not_replace_newer_confirmation():
    store = AdapterStateStore()

    newer = AdapterConfirmedState(
        adapter_id="tos",
        canonical_revision=45,
        symbols=frozenset({"AAPL", "NVDA", "TEMC"}),
        confirmed_at=NOW + timedelta(minutes=5),
        transaction_id="T20",
    )

    older = AdapterConfirmedState(
        adapter_id="tos",
        canonical_revision=44,
        symbols=frozenset({"AAPL", "NVDA"}),
        confirmed_at=NOW,
        transaction_id="T19",
    )

    store.record_confirmation(newer)
    store.record_confirmation(older)

    assert store.latest_confirmed("tos") == newer


def test_record_created_transaction():
    store = AdapterStateStore()
    transaction = make_transaction()

    store.record_transaction(transaction)

    assert store.get_transaction("T19") == transaction
    assert store.transaction_history("T19") == (
        transaction,
    )


def test_duplicate_transaction_id_is_rejected():
    store = AdapterStateStore()
    transaction = make_transaction()

    store.record_transaction(transaction)

    with pytest.raises(
        ValueError,
        match="Duplicate transaction_id",
    ):
        store.record_transaction(transaction)


def test_transaction_update_records_state_history():
    store = AdapterStateStore()

    created = make_transaction()

    active = start_transaction(
        created,
        at=NOW + timedelta(seconds=1),
    )

    store.record_transaction(created)
    store.update_transaction(active)

    assert store.get_transaction("T19") == active
    assert store.transaction_history("T19") == (
        created,
        active,
    )


def test_transaction_binding_cannot_change():
    store = AdapterStateStore()

    created = make_transaction()

    active = start_transaction(
        created,
        at=NOW + timedelta(seconds=1),
    )

    changed = replace(
        active,
        target_canonical_revision=45,
    )

    store.record_transaction(created)

    with pytest.raises(
        ValueError,
        match="binding cannot change",
    ):
        store.update_transaction(changed)


def test_invalid_transaction_transition_is_rejected():
    store = AdapterStateStore()

    created = make_transaction()

    invalid = replace(
        created,
        status=MaterializationTransactionStatus.SUCCESS,
        completed_at=NOW + timedelta(seconds=5),
    )

    store.record_transaction(created)

    with pytest.raises(
        ValueError,
        match="Invalid transaction transition",
    ):
        store.update_transaction(invalid)


def test_successful_verification_updates_all_adapter_state():
    store = AdapterStateStore()

    created = make_transaction()
    active = start_transaction(
        created,
        at=NOW + timedelta(seconds=1),
    )

    store.record_transaction(created)
    store.update_transaction(active)

    observed = make_observed(
        {"AAPL", "NVDA", "TEMC"},
        observed_at=NOW + timedelta(seconds=5),
    )

    result = verify_materialization(
        active,
        observed,
        at=NOW + timedelta(seconds=6),
    )

    store.apply_verification_result(result)

    assert store.get_transaction("T19").status is (
        MaterializationTransactionStatus.SUCCESS
    )

    assert store.latest_observed("tos") == observed

    confirmed = store.latest_confirmed("tos")
    assert confirmed is not None
    assert confirmed.canonical_revision == 44
    assert confirmed.transaction_id == "T19"


def test_failed_verification_does_not_advance_confirmation():
    store = AdapterStateStore()

    previous_confirmation = AdapterConfirmedState(
        adapter_id="tos",
        canonical_revision=43,
        symbols=frozenset({"AAPL", "NVDA"}),
        confirmed_at=NOW - timedelta(minutes=5),
        transaction_id="T18",
    )

    store.record_confirmation(previous_confirmation)

    created = make_transaction()
    active = start_transaction(
        created,
        at=NOW + timedelta(seconds=1),
    )

    store.record_transaction(created)
    store.update_transaction(active)

    observed = make_observed(
        {"AAPL", "NVDA"},
        observed_at=NOW + timedelta(seconds=5),
    )

    result = verify_materialization(
        active,
        observed,
        at=NOW + timedelta(seconds=6),
    )

    store.apply_verification_result(result)

    assert store.get_transaction("T19").status is (
        MaterializationTransactionStatus.FAILED
    )

    assert store.latest_observed("tos") == observed

    assert (
        store.latest_confirmed("tos")
        == previous_confirmation
    )
