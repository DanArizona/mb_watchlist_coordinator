from datetime import datetime, timezone

from mb_watchlist_coordinator.models import (
    CanonicalWatchlist,
    IntentType,
    ProducerIntent,
)

def test_create_base_set_intent():
    intent = ProducerIntent(
        intent_id="ov-20260824-082500",
        producer_id="overnight_volume",
        intent_type=IntentType.BASE_SET,
        symbols=frozenset({"AAPL", "NVDA", "AMD"}),
        created_at=datetime(2026, 8, 24, 12, 25, tzinfo=timezone.utc),
        source_event_id="ov-20260824-final",
        supersession_key="overnight_volume:daily_base_set:2026-08-24",
    )

    assert intent.intent_type is IntentType.BASE_SET
    assert intent.symbols == frozenset({"AAPL", "NVDA", "AMD"})


def test_create_ludp_ensure_present_intent():
    intent = ProducerIntent(
        intent_id="nasdaq-temc-20260824-101432",
        producer_id="nasdaq_halts",
        intent_type=IntentType.ENSURE_PRESENT,
        symbols=frozenset({"TEMC"}),
        created_at=datetime(2026, 8, 24, 14, 14, 32, tzinfo=timezone.utc),
        source_event_id="nasdaq-halt-temc-20260824-101432",
        reason="LUDP",
    )

    assert intent.producer_id == "nasdaq_halts"
    assert intent.symbols == frozenset({"TEMC"})
    assert intent.reason == "LUDP"


def test_producer_intent_is_immutable():
    intent = ProducerIntent(
        intent_id="manual-001",
        producer_id="manual",
        intent_type=IntentType.FORCE_ABSENT,
        symbols=frozenset({"TEMC"}),
        created_at=datetime(2026, 8, 24, 15, 0, tzinfo=timezone.utc),
    )

    try:
        intent.intent_id = "changed"
    except (AttributeError, TypeError):
        pass
    else:
        raise AssertionError("ProducerIntent should be immutable")


def test_create_canonical_watchlist():
    watchlist = CanonicalWatchlist(
        revision=42,
        symbols=frozenset({"AAPL", "NVDA", "TEMC"}),
        created_at=datetime(2026, 8, 24, 15, 30, tzinfo=timezone.utc),
        input_intent_ids=(
            "ov-20260824-082500",
            "nasdaq-temc-20260824-101432",
        ),
        policy_version="v1",
    )

    assert watchlist.revision == 42
    assert watchlist.symbols == frozenset({"AAPL", "NVDA", "TEMC"})
    assert watchlist.input_intent_ids == (
        "ov-20260824-082500",
        "nasdaq-temc-20260824-101432",
    )
    assert watchlist.policy_version == "v1"


def test_canonical_watchlist_is_immutable():
    watchlist = CanonicalWatchlist(
        revision=42,
        symbols=frozenset({"AAPL", "NVDA"}),
        created_at=datetime(2026, 8, 24, 15, 30, tzinfo=timezone.utc),
    )

    try:
        watchlist.revision = 43
    except (AttributeError, TypeError):
        pass
    else:
        raise AssertionError("CanonicalWatchlist should be immutable")
