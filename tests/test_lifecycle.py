from datetime import datetime, timedelta, timezone

from mb_watchlist_coordinator.lifecycle import (
    is_intent_time_active,
    select_effective_intents,
)
from mb_watchlist_coordinator.models import IntentType, ProducerIntent


NOW = datetime(2026, 8, 24, 20, 0, tzinfo=timezone.utc)


def make_intent(
    *,
    intent_id="test-001",
    intent_type=IntentType.ENSURE_PRESENT,
    symbols=frozenset({"TEMC"}),
    created_at=NOW,
    effective_from=None,
    expires_at=None,
    supersession_key=None,
) -> ProducerIntent:
    return ProducerIntent(
        intent_id=intent_id,
        producer_id="test",
        intent_type=intent_type,
        symbols=frozenset(symbols),
        created_at=created_at,
        effective_from=effective_from,
        expires_at=expires_at,
        supersession_key=supersession_key,
    )


def test_intent_without_time_bounds_is_active():
    intent = make_intent()

    assert is_intent_time_active(intent, at=NOW)


def test_intent_before_effective_from_is_inactive():
    intent = make_intent(
        effective_from=NOW + timedelta(minutes=5),
    )

    assert not is_intent_time_active(intent, at=NOW)


def test_intent_at_effective_from_is_active():
    intent = make_intent(
        effective_from=NOW,
    )

    assert is_intent_time_active(intent, at=NOW)


def test_intent_before_expiration_is_active():
    intent = make_intent(
        expires_at=NOW + timedelta(minutes=5),
    )

    assert is_intent_time_active(intent, at=NOW)


def test_intent_at_expiration_is_inactive():
    intent = make_intent(
        expires_at=NOW,
    )

    assert not is_intent_time_active(intent, at=NOW)


def test_intent_after_expiration_is_inactive():
    intent = make_intent(
        expires_at=NOW - timedelta(minutes=1),
    )

    assert not is_intent_time_active(intent, at=NOW)


def test_intent_before_created_at_is_inactive():
    intent = make_intent(
        created_at=NOW + timedelta(minutes=5),
    )

    assert not is_intent_time_active(intent, at=NOW)


def test_select_effective_intents_keeps_unkeyed_active_intents():
    first = make_intent(
        intent_id="first",
        symbols={"AAPL"},
        created_at=NOW - timedelta(minutes=2),
    )
    second = make_intent(
        intent_id="second",
        symbols={"NVDA"},
        created_at=NOW - timedelta(minutes=1),
    )

    selected = select_effective_intents(
        [first, second],
        at=NOW,
    )

    assert selected == (first, second)


def test_newer_intent_with_same_supersession_key_wins():
    older = make_intent(
        intent_id="ov-old",
        intent_type=IntentType.BASE_SET,
        symbols={"AAPL"},
        created_at=NOW - timedelta(minutes=10),
        supersession_key="ov:daily:2026-08-24",
    )
    newer = make_intent(
        intent_id="ov-new",
        intent_type=IntentType.BASE_SET,
        symbols={"AAPL", "NVDA"},
        created_at=NOW - timedelta(minutes=5),
        supersession_key="ov:daily:2026-08-24",
    )

    selected = select_effective_intents(
        [older, newer],
        at=NOW,
    )

    assert selected == (newer,)


def test_future_superseding_intent_does_not_displace_current_intent():
    current = make_intent(
        intent_id="current",
        created_at=NOW - timedelta(minutes=10),
        supersession_key="manual:TEMC:2026-08-24",
    )
    future = make_intent(
        intent_id="future",
        created_at=NOW - timedelta(minutes=5),
        effective_from=NOW + timedelta(minutes=5),
        supersession_key="manual:TEMC:2026-08-24",
    )

    selected = select_effective_intents(
        [current, future],
        at=NOW,
    )

    assert selected == (current,)


def test_expired_superseding_intent_does_not_revive_older_intent():
    older = make_intent(
        intent_id="older",
        created_at=NOW - timedelta(hours=2),
        supersession_key="manual:TEMC:2026-08-24",
    )
    newer = make_intent(
        intent_id="newer",
        created_at=NOW - timedelta(hours=1),
        expires_at=NOW - timedelta(minutes=1),
        supersession_key="manual:TEMC:2026-08-24",
    )

    selected = select_effective_intents(
        [older, newer],
        at=NOW,
    )

    assert selected == ()


def test_different_supersession_keys_do_not_conflict():
    ov = make_intent(
        intent_id="ov",
        intent_type=IntentType.BASE_SET,
        symbols={"AAPL"},
        created_at=NOW - timedelta(minutes=2),
        supersession_key="ov:daily:2026-08-24",
    )
    manual = make_intent(
        intent_id="manual",
        intent_type=IntentType.FORCE_PRESENT,
        symbols={"TEMC"},
        created_at=NOW - timedelta(minutes=1),
        supersession_key="manual:TEMC:2026-08-24",
    )

    selected = select_effective_intents(
        [ov, manual],
        at=NOW,
    )

    assert selected == (ov, manual)


def test_latest_manual_presence_override_wins():
    absent = make_intent(
        intent_id="manual-absent",
        intent_type=IntentType.FORCE_ABSENT,
        symbols={"TEMC"},
        created_at=NOW - timedelta(minutes=10),
        supersession_key="manual:TEMC:2026-08-24",
    )
    present = make_intent(
        intent_id="manual-present",
        intent_type=IntentType.FORCE_PRESENT,
        symbols={"TEMC"},
        created_at=NOW - timedelta(minutes=5),
        supersession_key="manual:TEMC:2026-08-24",
    )

    selected = select_effective_intents(
        [absent, present],
        at=NOW,
    )

    assert selected == (present,)
