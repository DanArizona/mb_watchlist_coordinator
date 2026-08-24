from datetime import datetime, timezone

from mb_watchlist_coordinator.models import IntentType, ProducerIntent
from mb_watchlist_coordinator.policy import build_canonical_watchlist


NOW = datetime(2026, 8, 24, 20, 0, tzinfo=timezone.utc)


def make_intent(
    intent_id: str,
    intent_type: IntentType,
    symbols: set[str],
) -> ProducerIntent:
    return ProducerIntent(
        intent_id=intent_id,
        producer_id="test",
        intent_type=intent_type,
        symbols=frozenset(symbols),
        created_at=NOW,
    )


def test_base_set_becomes_canonical_watchlist():
    base = make_intent(
        "ov-001",
        IntentType.BASE_SET,
        {"AAPL", "NVDA", "AMD"},
    )

    canonical = build_canonical_watchlist(
        [base],
        revision=1,
        created_at=NOW,
    )

    assert canonical.revision == 1
    assert canonical.symbols == frozenset({"AAPL", "NVDA", "AMD"})
    assert canonical.input_intent_ids == ("ov-001",)


def test_ensure_present_adds_symbols():
    base = make_intent(
        "ov-001",
        IntentType.BASE_SET,
        {"AAPL", "NVDA"},
    )
    ludp = make_intent(
        "nasdaq-temc",
        IntentType.ENSURE_PRESENT,
        {"TEMC"},
    )

    canonical = build_canonical_watchlist(
        [base, ludp],
        revision=2,
        created_at=NOW,
    )

    assert canonical.symbols == frozenset(
        {"AAPL", "NVDA", "TEMC"}
    )


def test_ensure_absent_wins_over_ensure_present():
    base = make_intent(
        "ov-001",
        IntentType.BASE_SET,
        {"AAPL", "NVDA"},
    )
    include = make_intent(
        "include-temc",
        IntentType.ENSURE_PRESENT,
        {"TEMC"},
    )
    exclude = make_intent(
        "exclude-temc",
        IntentType.ENSURE_ABSENT,
        {"TEMC"},
    )

    canonical = build_canonical_watchlist(
        [base, include, exclude],
        revision=3,
        created_at=NOW,
    )

    assert canonical.symbols == frozenset({"AAPL", "NVDA"})


def test_force_present_wins_over_ensure_absent():
    base = make_intent(
        "ov-001",
        IntentType.BASE_SET,
        {"AAPL"},
    )
    exclude = make_intent(
        "exclude-temc",
        IntentType.ENSURE_ABSENT,
        {"TEMC"},
    )
    force_present = make_intent(
        "manual-temc",
        IntentType.FORCE_PRESENT,
        {"TEMC"},
    )

    canonical = build_canonical_watchlist(
        [base, exclude, force_present],
        revision=4,
        created_at=NOW,
    )

    assert canonical.symbols == frozenset({"AAPL", "TEMC"})


def test_force_absent_wins_over_ensure_present():
    base = make_intent(
        "ov-001",
        IntentType.BASE_SET,
        {"AAPL"},
    )
    include = make_intent(
        "nasdaq-temc",
        IntentType.ENSURE_PRESENT,
        {"TEMC"},
    )
    force_absent = make_intent(
        "manual-temc",
        IntentType.FORCE_ABSENT,
        {"TEMC"},
    )

    canonical = build_canonical_watchlist(
        [base, include, force_absent],
        revision=5,
        created_at=NOW,
    )

    assert canonical.symbols == frozenset({"AAPL"})


def test_policy_records_all_input_intent_ids():
    base = make_intent(
        "ov-001",
        IntentType.BASE_SET,
        {"AAPL"},
    )
    ludp = make_intent(
        "nasdaq-temc",
        IntentType.ENSURE_PRESENT,
        {"TEMC"},
    )

    canonical = build_canonical_watchlist(
        [base, ludp],
        revision=6,
        created_at=NOW,
    )

    assert canonical.input_intent_ids == (
        "ov-001",
        "nasdaq-temc",
    )


def test_policy_records_suppressed_intent_as_input():
    base = make_intent(
        "ov-001",
        IntentType.BASE_SET,
        {"AAPL"},
    )
    ludp = make_intent(
        "nasdaq-temc",
        IntentType.ENSURE_PRESENT,
        {"TEMC"},
    )
    force_absent = make_intent(
        "manual-temc",
        IntentType.FORCE_ABSENT,
        {"TEMC"},
    )

    canonical = build_canonical_watchlist(
        [base, ludp, force_absent],
        revision=7,
        created_at=NOW,
    )

    assert canonical.symbols == frozenset({"AAPL"})
    assert canonical.input_intent_ids == (
        "ov-001",
        "nasdaq-temc",
        "manual-temc",
    )
