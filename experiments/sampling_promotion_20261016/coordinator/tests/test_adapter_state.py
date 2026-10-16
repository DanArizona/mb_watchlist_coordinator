from datetime import datetime, timezone

from mb_watchlist_coordinator.adapter_state import (
    AdapterConfirmedState,
    AdapterObservedState,
    AdapterTarget,
)


NOW = datetime(2026, 8, 25, 4, 0, tzinfo=timezone.utc)


def test_create_adapter_target():
    target = AdapterTarget(
        adapter_id="tos",
        canonical_revision=42,
        symbols=frozenset({"AAPL", "NVDA"}),
    )

    assert target.adapter_id == "tos"
    assert target.canonical_revision == 42
    assert target.symbols == frozenset({"AAPL", "NVDA"})


def test_create_adapter_observed_state():
    observed = AdapterObservedState(
        adapter_id="tos",
        symbols=frozenset({"AAPL", "NVDA", "TEMC"}),
        observed_at=NOW,
        evidence_ref="2026-08-24-23-00-00-WL.csv",
    )

    assert observed.adapter_id == "tos"
    assert observed.symbols == frozenset(
        {"AAPL", "NVDA", "TEMC"}
    )
    assert observed.observed_at == NOW
    assert observed.evidence_ref == (
        "2026-08-24-23-00-00-WL.csv"
    )


def test_create_adapter_confirmed_state():
    confirmed = AdapterConfirmedState(
        adapter_id="tos",
        canonical_revision=42,
        symbols=frozenset({"AAPL", "NVDA", "TEMC"}),
        confirmed_at=NOW,
        transaction_id="T42",
        evidence_ref="2026-08-24-23-00-00-WL.csv",
    )

    assert confirmed.adapter_id == "tos"
    assert confirmed.canonical_revision == 42
    assert confirmed.symbols == frozenset(
        {"AAPL", "NVDA", "TEMC"}
    )
    assert confirmed.transaction_id == "T42"


def test_adapter_observed_state_is_immutable():
    observed = AdapterObservedState(
        adapter_id="tos",
        symbols=frozenset({"AAPL"}),
        observed_at=NOW,
    )

    try:
        observed.symbols = frozenset({"NVDA"})
    except (AttributeError, TypeError):
        pass
    else:
        raise AssertionError(
            "AdapterObservedState should be immutable"
        )


def test_observed_and_confirmed_states_may_disagree():
    confirmed = AdapterConfirmedState(
        adapter_id="tos",
        canonical_revision=42,
        symbols=frozenset({"AAPL", "NVDA", "TEMC"}),
        confirmed_at=NOW,
        transaction_id="T42",
    )

    observed = AdapterObservedState(
        adapter_id="tos",
        symbols=frozenset({"AAPL", "NVDA"}),
        observed_at=NOW,
    )

    assert observed.symbols != confirmed.symbols
    assert confirmed.canonical_revision == 42
