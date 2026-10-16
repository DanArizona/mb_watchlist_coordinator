from datetime import date, timedelta

from mb_watchlist_coordinator.session import (
    session_expiration,
    session_start,
)


def test_session_starts_at_midnight_eastern():
    start = session_start(date(2026, 8, 24))

    assert start.year == 2026
    assert start.month == 8
    assert start.day == 24
    assert start.hour == 0
    assert start.minute == 0
    assert start.utcoffset() == timedelta(hours=-4)


def test_session_expires_at_next_midnight_eastern():
    expiration = session_expiration(date(2026, 8, 24))

    assert expiration.year == 2026
    assert expiration.month == 8
    assert expiration.day == 25
    assert expiration.hour == 0
    assert expiration.minute == 0
    assert expiration.utcoffset() == timedelta(hours=-4)


def test_session_helpers_follow_standard_time():
    start = session_start(date(2026, 12, 15))

    assert start.utcoffset() == timedelta(hours=-5)
