"""Read-only Schwab token lifetime inspection and startup policy."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import SecureSchwabConfig


UTC = timezone.utc
DEFAULT_ACCESS_TOKEN_LIFETIME = timedelta(minutes=30)
DEFAULT_REFRESH_TOKEN_LIFETIME = timedelta(days=7)
SCHWABDEV_INTERACTIVE_REFRESH_THRESHOLD = timedelta(
    seconds=3_630,
)
DEFAULT_POLLING_SAFETY_MARGIN = timedelta(minutes=15)
DEFAULT_POLLING_REFRESH_MARGIN = (
    SCHWABDEV_INTERACTIVE_REFRESH_THRESHOLD
    + DEFAULT_POLLING_SAFETY_MARGIN
)


class SchwabTokenStatusError(RuntimeError):
    """Token lifetime metadata cannot be read or is not usable."""


class SchwabCredentialPreflightError(SchwabTokenStatusError):
    """Stored credentials cannot safely cover a requested run horizon."""


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def _parse_timestamp(value: object, name: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise SchwabTokenStatusError(
            f"Schwab token database has no valid {name} timestamp"
        )
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise SchwabTokenStatusError(
            f"Schwab token database has an invalid {name} timestamp"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class SchwabTokenStatus:
    """Non-secret lifetime metadata for one Schwabdev token database."""

    tokens_db: Path
    observed_at: datetime
    access_token_issued_at: datetime
    refresh_token_issued_at: datetime
    access_token_expires_at: datetime
    refresh_token_expires_at: datetime

    def __post_init__(self) -> None:
        for name in (
            "observed_at",
            "access_token_issued_at",
            "refresh_token_issued_at",
            "access_token_expires_at",
            "refresh_token_expires_at",
        ):
            _require_aware(getattr(self, name), name)

    @property
    def access_remaining(self) -> timedelta:
        return self.access_token_expires_at - self.observed_at

    @property
    def refresh_remaining(self) -> timedelta:
        return self.refresh_token_expires_at - self.observed_at

    def require_refresh_valid_through(
        self,
        required_through: datetime,
    ) -> None:
        """Raise unless refresh-token validity covers ``required_through``."""

        _require_aware(required_through, "required_through")
        required_utc = required_through.astimezone(UTC)
        if self.refresh_token_expires_at < required_utc:
            raise SchwabCredentialPreflightError(
                "Schwab refresh token cannot cover the requested run: "
                f"expires {self.refresh_token_expires_at.isoformat()}, "
                f"required through {required_utc.isoformat()}. "
                "Run mb-schwab-auth before starting the poller."
            )


def read_schwab_token_status(
    config: SecureSchwabConfig,
    *,
    observed_at: datetime | None = None,
) -> SchwabTokenStatus:
    """Read token issue times without decrypting tokens or refreshing them."""

    if not isinstance(config, SecureSchwabConfig):
        raise TypeError("config must be a SecureSchwabConfig")
    now = observed_at or datetime.now(UTC)
    _require_aware(now, "observed_at")
    now = now.astimezone(UTC)

    database_path = config.tokens_db.expanduser().resolve()
    if not database_path.is_file():
        raise SchwabTokenStatusError(
            f"Schwab token database does not exist: {database_path}"
        )

    connection: sqlite3.Connection | None = None
    try:
        uri = database_path.as_uri() + "?mode=ro"
        connection = sqlite3.connect(uri, uri=True, timeout=5)
        row = connection.execute(
            """
            SELECT access_token_issued,
                   refresh_token_issued,
                   expires_in
            FROM schwabdev
            LIMIT 1
            """
        ).fetchone()
    except sqlite3.Error as exc:
        raise SchwabTokenStatusError(
            f"Could not read Schwab token status: {exc}"
        ) from exc
    finally:
        if connection is not None:
            connection.close()

    if row is None:
        raise SchwabTokenStatusError(
            "Schwab token database contains no token record"
        )

    access_issued = _parse_timestamp(row[0], "access-token issue")
    refresh_issued = _parse_timestamp(row[1], "refresh-token issue")
    expires_in = row[2]
    access_lifetime = DEFAULT_ACCESS_TOKEN_LIFETIME
    if isinstance(expires_in, int) and not isinstance(expires_in, bool):
        if expires_in > 0:
            access_lifetime = timedelta(seconds=expires_in)

    return SchwabTokenStatus(
        tokens_db=database_path,
        observed_at=now,
        access_token_issued_at=access_issued,
        refresh_token_issued_at=refresh_issued,
        access_token_expires_at=access_issued + access_lifetime,
        refresh_token_expires_at=(
            refresh_issued + DEFAULT_REFRESH_TOKEN_LIFETIME
        ),
    )
