from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo


EASTERN = ZoneInfo("America/New_York")


def session_start(session_date: date) -> datetime:
    return datetime.combine(
        session_date,
        time.min,
        tzinfo=EASTERN,
    )


def session_expiration(session_date: date) -> datetime:
    return datetime.combine(
        session_date + timedelta(days=1),
        time.min,
        tzinfo=EASTERN,
    )
