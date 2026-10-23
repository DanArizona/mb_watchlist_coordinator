"""Recoverable forced Schwab browser reauthorization."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .client import AuthCallback, make_client_from_config
from .config import SecureSchwabConfig
from .status import (
    SchwabTokenStatus,
    SchwabTokenStatusError,
    read_schwab_token_status,
)


UTC = timezone.utc
TOKEN_DATABASE_SIDECAR_SUFFIXES = ("-wal", "-shm", "-journal")


class SchwabForceReauthorizationError(RuntimeError):
    """Forced reauthorization failed or could not be rolled back safely."""


@dataclass(frozen=True, slots=True)
class SchwabForceReauthorizationResult:
    """Verified result of replacing one Schwab token database."""

    tokens_db: Path
    backup_path: Path | None
    status: SchwabTokenStatus


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def token_database_backup_path(
    tokens_db: Path,
    *,
    observed_at: datetime,
) -> Path:
    """Return a timestamped, non-overwriting backup path."""

    _require_aware(observed_at, "observed_at")
    stamp = observed_at.astimezone(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    return tokens_db.with_name(
        f"{tokens_db.stem}.before_forced_reauth_{stamp}{tokens_db.suffix}"
    )


def _sidecar_paths(tokens_db: Path) -> tuple[Path, ...]:
    return tuple(
        Path(f"{tokens_db}{suffix}")
        for suffix in TOKEN_DATABASE_SIDECAR_SUFFIXES
    )


def _close_client(client: object | None) -> None:
    if client is None:
        return
    close = getattr(client, "close", None)
    if callable(close):
        close()


def _remove_replacement_database(tokens_db: Path) -> None:
    for path in (tokens_db, *_sidecar_paths(tokens_db)):
        if path.exists():
            if not path.is_file():
                raise SchwabForceReauthorizationError(
                    f"refusing to remove non-file token artifact: {path}"
                )
            path.unlink()


def _restore_original_database(
    tokens_db: Path,
    backup_path: Path | None,
) -> None:
    _remove_replacement_database(tokens_db)
    if backup_path is not None:
        if not backup_path.is_file():
            raise SchwabForceReauthorizationError(
                f"token database backup is missing: {backup_path}"
            )
        backup_path.replace(tokens_db)


ClientFactory = Callable[..., Any]
StatusReader = Callable[[SecureSchwabConfig], SchwabTokenStatus]


def force_schwab_reauthorization(
    config: SecureSchwabConfig,
    *,
    timeout: int = 10,
    call_on_auth: AuthCallback | None = None,
    observed_at: datetime | None = None,
    client_factory: ClientFactory = make_client_from_config,
    status_reader: StatusReader = read_schwab_token_status,
) -> SchwabForceReauthorizationResult:
    """Rotate the token DB, force OAuth, verify it, and roll back on failure."""

    if not isinstance(config, SecureSchwabConfig):
        raise TypeError("config must be a SecureSchwabConfig")
    now = observed_at or datetime.now(UTC)
    _require_aware(now, "observed_at")
    tokens_db = config.tokens_db.expanduser().resolve()
    tokens_db.parent.mkdir(parents=True, exist_ok=True)

    active_sidecars = [
        path for path in _sidecar_paths(tokens_db) if path.exists()
    ]
    if active_sidecars:
        raise SchwabForceReauthorizationError(
            "token database has SQLite sidecar files; close every Schwab "
            "client before forcing reauthorization: "
            + ", ".join(str(path) for path in active_sidecars)
        )

    previous_status: SchwabTokenStatus | None = None
    backup_path: Path | None = None
    if tokens_db.exists():
        if not tokens_db.is_file():
            raise SchwabForceReauthorizationError(
                f"token database is not a file: {tokens_db}"
            )
        try:
            previous_status = status_reader(config)
        except SchwabTokenStatusError:
            previous_status = None
        backup_path = token_database_backup_path(
            tokens_db,
            observed_at=now,
        )
        if backup_path.exists():
            raise SchwabForceReauthorizationError(
                f"refusing to overwrite token database backup: {backup_path}"
            )
        tokens_db.replace(backup_path)

    client: object | None = None
    try:
        client = client_factory(
            config,
            timeout=timeout,
            call_on_auth=call_on_auth,
        )
        _close_client(client)
        client = None
        if not tokens_db.is_file():
            raise SchwabForceReauthorizationError(
                "authorization completed without creating a token database"
            )
        new_status = status_reader(config)
        if new_status.refresh_remaining <= timedelta(0):
            raise SchwabForceReauthorizationError(
                "replacement refresh token is already expired"
            )
        if (
            previous_status is not None
            and new_status.refresh_token_issued_at
            <= previous_status.refresh_token_issued_at
        ):
            raise SchwabForceReauthorizationError(
                "replacement refresh token is not newer than the backup"
            )
    except BaseException as error:
        try:
            _close_client(client)
            _restore_original_database(tokens_db, backup_path)
        except Exception as rollback_error:
            raise SchwabForceReauthorizationError(
                "forced reauthorization failed and automatic rollback also "
                f"failed; preserve the backup at {backup_path}: "
                f"{rollback_error}"
            ) from error
        if isinstance(error, KeyboardInterrupt):
            raise
        if isinstance(error, SchwabForceReauthorizationError):
            raise
        raise SchwabForceReauthorizationError(
            f"forced reauthorization failed; original token database "
            f"restored: {error}"
        ) from error

    return SchwabForceReauthorizationResult(
        tokens_db=tokens_db,
        backup_path=backup_path,
        status=new_status,
    )
