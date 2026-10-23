"""
Secure configuration support for Schwabdev.

This module loads Schwabdev-related secrets from an encrypted .ecfg file.

The .ecfg file should contain a dictionary with these keys:

    SCHWAB_APP_KEY
    SCHWAB_APP_SECRET
    SCHWAB_CALLBACK_URL
    SCHWAB_TOKENS_DB
    SCHWAB_TOKEN_DB_FERNET_KEY

The access token and refresh token should remain in Schwabdev's token
database. The token database should be encrypted using the Fernet key
stored in the .ecfg file.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


from mb_tools.secure_config import load_ecfg


REQUIRED_ECFG_KEYS = (
    "SCHWAB_APP_KEY",
    "SCHWAB_APP_SECRET",
    "SCHWAB_CALLBACK_URL",
    "SCHWAB_TOKENS_DB",
    "SCHWAB_TOKEN_DB_FERNET_KEY",
)


@dataclass(frozen=True)
class SecureSchwabConfig:
    """
    Configuration needed to create a Schwabdev client securely.

    The token database path points to Schwabdev's SQLite token database.
    The token_db_fernet_key is passed to Schwabdev as its encryption key.
    """

    app_key: str
    app_secret: str
    callback_url: str
    tokens_db: Path
    token_db_fernet_key: str


class SecureSchwabConfigError(Exception):
    """Raised when secure Schwab configuration is missing or invalid."""

def validate_secure_schwab_dict(data: Mapping[str, Any]) -> None:
    """
    Validate that the decrypted .ecfg dictionary contains required keys.
    """

    missing = [key for key in REQUIRED_ECFG_KEYS if key not in data]

    if missing:
        joined = ", ".join(missing)
        raise SecureSchwabConfigError(
            f"secure Schwab .ecfg file is missing required key(s): {joined}"
        )

    for key in REQUIRED_ECFG_KEYS:
        value = data[key]
        if not isinstance(value, str) or not value.strip():
            raise SecureSchwabConfigError(
                f"secure Schwab .ecfg key {key!r} must be a non-empty string"
            )

    validate_schwabdev_key_shape(
        data["SCHWAB_APP_KEY"].strip(),
        data["SCHWAB_APP_SECRET"].strip(),
    )


def validate_schwabdev_key_shape(app_key: str, app_secret: str) -> None:
    """
    Validate the basic key/secret shape expected by Schwabdev.

    This does not prove the credentials are correct. It only catches values
    that Schwabdev itself will reject before authorization begins.
    """

    if len(app_key) % 2 != 0:
        raise SecureSchwabConfigError(
            "SCHWAB_APP_KEY has odd length. It may have been copied incorrectly."
        )

    if len(app_secret) % 2 != 0:
        raise SecureSchwabConfigError(
            "SCHWAB_APP_SECRET has odd length. It may have been copied incorrectly."
        )

    if len(app_key) + len(app_secret) < 32:
        raise SecureSchwabConfigError(
            "SCHWAB_APP_KEY and SCHWAB_APP_SECRET have combined length less than 32. "
            "One or both values may have been copied incorrectly."
        )







def config_from_dict(data: Mapping[str, Any]) -> SecureSchwabConfig:
    """
    Convert a decrypted .ecfg dictionary into a SecureSchwabConfig.
    """

    validate_secure_schwab_dict(data)

    return SecureSchwabConfig(
        app_key=data["SCHWAB_APP_KEY"].strip(),
        app_secret=data["SCHWAB_APP_SECRET"].strip(),
        callback_url=data["SCHWAB_CALLBACK_URL"].strip(),
        tokens_db=Path(data["SCHWAB_TOKENS_DB"]).expanduser(),
        token_db_fernet_key=data["SCHWAB_TOKEN_DB_FERNET_KEY"].strip(),
    )


def load_secure_schwab_config(
    ecfg_path: str | Path,
    password: str,
) -> SecureSchwabConfig:
    """
    Load Schwabdev configuration from an encrypted .ecfg file.

    Parameters
    ----------
    ecfg_path:
        Path to secure_schwabdev.ecfg.

    password:
        Password used to decrypt the .ecfg file.

    Returns
    -------
    SecureSchwabConfig
        Validated Schwabdev configuration.
    """

    data = load_ecfg(ecfg_path, password)

    if not isinstance(data, Mapping):
        raise SecureSchwabConfigError(
            "secure Schwab .ecfg file did not decrypt to a dictionary-like object"
        )

    return config_from_dict(data)
