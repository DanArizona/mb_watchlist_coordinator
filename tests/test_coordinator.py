from datetime import datetime, timedelta, timezone

import pytest

from mb_watchlist_coordinator.coordinator import WatchlistCoordinator
from mb_watchlist_coordinator.models import (
    IntentCancellation,
    IntentType,
    ProducerIntent,
)


NOW = datetime(2026, 8, 24, 14, 0, tzinfo=timezone.utc)


def make_intent(
    intent_id: str,
    intent_type: IntentType,
    symbols: set[str],
    *,
    created_at: datetime = NOW,
    expires_at: datetime | None = None,
    supersession_key: str | None = None,
) -> ProducerIntent:
    return ProducerIntent(
        intent_id=intent_id,
        producer_id="test",
        intent_type=intent_type,
        symbols=frozenset(symbols),
        created_at=created_at,
        expires_at=expires_at,
        supersession_key=supersession_key,
    )


def test_accept_base_set_creates_first_canonical_revision():
    coordinator = WatchlistCoordinator()

    base = make_intent(
        "ov-001",
        IntentType.BASE_SET,
        {"AAPL", "NVDA"},
    )

    canonical = coordinator.accept_intent(
        base,
        at=NOW,
    )

    assert canonical.revision == 1
    assert canonical.symbols == frozenset(
        {"AAPL", "NVDA"}
    )
    assert canonical.input_intent_ids == ("ov-001",)
    assert coordinator.current_canonical == canonical


def test_coordinator_owns_adapter_state_store():
    coordinator = WatchlistCoordinator()

    assert coordinator.adapter_state is not None
    assert coordinator.adapter_state.latest_observed("tos") is None
    assert coordinator.adapter_state.latest_confirmed("tos") is None


def test_adapter_state_store_is_stable_coordinator_state():
    coordinator = WatchlistCoordinator()

    first = coordinator.adapter_state
    second = coordinator.adapter_state

    assert first is second
    

def test_ludp_manual_override_and_cancel_create_expected_revisions():
    coordinator = WatchlistCoordinator()

    base = make_intent(
        "ov-001",
        IntentType.BASE_SET,
        {"AAPL", "NVDA"},
        created_at=NOW,
    )
    ludp = make_intent(
        "nasdaq-temc",
        IntentType.ENSURE_PRESENT,
        {"TEMC"},
        created_at=NOW + timedelta(minutes=1),
    )
    manual = make_intent(
        "manual-temc",
        IntentType.FORCE_ABSENT,
        {"TEMC"},
        created_at=NOW + timedelta(minutes=2),
        supersession_key="manual:TEMC:2026-08-24",
    )

    rev1 = coordinator.accept_intent(
        base,
        at=NOW,
    )

    rev2 = coordinator.accept_intent(
        ludp,
        at=NOW + timedelta(minutes=1),
    )

    rev3 = coordinator.accept_intent(
        manual,
        at=NOW + timedelta(minutes=2),
    )

    cancellation = IntentCancellation(
        cancellation_id="cancel-manual-temc",
        intent_id="manual-temc",
        created_at=NOW + timedelta(minutes=3),
    )

    rev4 = coordinator.accept_cancellation(
        cancellation,
        at=NOW + timedelta(minutes=3),
    )

    assert rev1.symbols == frozenset(
        {"AAPL", "NVDA"}
    )

    assert rev2.symbols == frozenset(
        {"AAPL", "NVDA", "TEMC"}
    )

    assert rev3.symbols == frozenset(
        {"AAPL", "NVDA"}
    )

    assert rev4.symbols == frozenset(
        {"AAPL", "NVDA", "TEMC"}
    )

    assert [
        revision.revision
        for revision in coordinator.revision_history
    ] == [1, 2, 3, 4]


def test_same_symbols_with_new_provenance_create_new_revision():
    coordinator = WatchlistCoordinator()

    older = make_intent(
        "ov-001",
        IntentType.BASE_SET,
        {"AAPL", "NVDA"},
        created_at=NOW,
        supersession_key="ov:daily:2026-08-24",
    )

    newer = make_intent(
        "ov-002",
        IntentType.BASE_SET,
        {"AAPL", "NVDA"},
        created_at=NOW + timedelta(minutes=5),
        supersession_key="ov:daily:2026-08-24",
    )

    rev1 = coordinator.accept_intent(
        older,
        at=NOW,
    )

    rev2 = coordinator.accept_intent(
        newer,
        at=NOW + timedelta(minutes=5),
    )

    assert rev1.symbols == rev2.symbols
    assert rev1.revision == 1
    assert rev2.revision == 2

    assert rev1.input_intent_ids == ("ov-001",)
    assert rev2.input_intent_ids == ("ov-002",)


def test_recompute_without_change_does_not_create_revision():
    coordinator = WatchlistCoordinator()

    base = make_intent(
        "ov-001",
        IntentType.BASE_SET,
        {"AAPL"},
    )

    rev1 = coordinator.accept_intent(
        base,
        at=NOW,
    )

    same = coordinator.recompute(
        at=NOW + timedelta(minutes=1),
    )

    assert same is rev1
    assert len(coordinator.revision_history) == 1


def test_no_change_recompute_does_not_consume_revision_number():
    coordinator = WatchlistCoordinator()

    base = make_intent(
        "ov-001",
        IntentType.BASE_SET,
        {"AAPL"},
        created_at=NOW,
    )

    rev1 = coordinator.accept_intent(
        base,
        at=NOW,
    )

    coordinator.recompute(
        at=NOW + timedelta(minutes=1),
    )

    ludp = make_intent(
        "nasdaq-temc",
        IntentType.ENSURE_PRESENT,
        {"TEMC"},
        created_at=NOW + timedelta(minutes=2),
    )

    rev2 = coordinator.accept_intent(
        ludp,
        at=NOW + timedelta(minutes=2),
    )

    assert rev1.revision == 1
    assert rev2.revision == 2


def test_expiration_creates_new_canonical_revision():
    coordinator = WatchlistCoordinator()

    ludp = make_intent(
        "nasdaq-temc",
        IntentType.ENSURE_PRESENT,
        {"TEMC"},
        created_at=NOW,
        expires_at=NOW + timedelta(hours=1),
    )

    rev1 = coordinator.accept_intent(
        ludp,
        at=NOW,
    )

    rev2 = coordinator.recompute(
        at=NOW + timedelta(hours=1),
    )

    assert rev1.symbols == frozenset({"TEMC"})
    assert rev2.symbols == frozenset()
    assert rev2.revision == 2
    assert rev2.input_intent_ids == ()


def test_duplicate_intent_id_is_rejected():
    coordinator = WatchlistCoordinator()

    intent = make_intent(
        "duplicate",
        IntentType.ENSURE_PRESENT,
        {"TEMC"},
    )

    coordinator.accept_intent(
        intent,
        at=NOW,
    )

    with pytest.raises(
        ValueError,
        match="Duplicate intent_id",
    ):
        coordinator.accept_intent(
            intent,
            at=NOW,
        )


def test_cancellation_of_unknown_intent_is_rejected():
    coordinator = WatchlistCoordinator()

    cancellation = IntentCancellation(
        cancellation_id="cancel-001",
        intent_id="missing",
        created_at=NOW,
    )

    with pytest.raises(
        ValueError,
        match="unknown intent_id",
    ):
        coordinator.accept_cancellation(
            cancellation,
            at=NOW,
        )
