"""
Client factory for creating Schwabdev clients from encrypted .ecfg config.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Callable
import webbrowser

from .config import SecureSchwabConfig, load_secure_schwab_config


AuthCallback = Callable[[str], str]


class SchwabdevNotInstalledError(ImportError):
    """
    Raised when Schwabdev is not installed.

    Install with:

        pip install -e ".[schwab]"
    """


class SchwabdevVersionError(RuntimeError):
    """Raised when an unsafe, unsupported Schwabdev release is installed."""


MINIMUM_SCHWABDEV_VERSION = (4, 0, 0)


def _installed_schwabdev_version(module: object) -> str:
    module_version = getattr(module, "__version__", None)
    if isinstance(module_version, str) and module_version:
        return module_version
    try:
        return version("schwabdev")
    except PackageNotFoundError as exc:
        raise SchwabdevVersionError(
            "Could not determine the installed Schwabdev version. "
            'Reinstall with: pip install -e ".[schwab]"'
        ) from exc


def _numeric_version(value: str) -> tuple[int, ...]:
    pieces: list[int] = []
    for piece in value.split("."):
        digits = "".join(character for character in piece if character.isdigit())
        if not digits:
            break
        pieces.append(int(digits))
    return tuple(pieces)


def _require_supported_schwabdev(module: object) -> None:
    installed = _installed_schwabdev_version(module)
    parsed = _numeric_version(installed)
    if parsed < MINIMUM_SCHWABDEV_VERSION:
        raise SchwabdevVersionError(
            "Schwabdev 4.0.0 or newer is required because earlier releases "
            "can leave the shared token database locked after failed "
            "authorization. "
            f"Installed: {installed}. "
            'Upgrade with: python -m pip install "schwabdev>=4,<5"'
        )



def console_auth_callback(auth_url: str) -> str:
    """
    Console-based authorization callback for Schwabdev.

    Schwabdev calls this when user authorization is required, usually when
    the refresh token needs to be created or renewed.

    Do not log the returned callback URL. It may contain an authorization code.
    """

    print()
    print("Schwab authorization is required.")
    print("Opening browser for Schwab authorization...")
    print()

    webbrowser.open(auth_url)

    callback_url = input(
        "After approving access in the browser, paste the full redirected URL here:\n> "
    ).strip()

    return callback_url



def make_client_from_config(
    config: SecureSchwabConfig,
    *,
    timeout: int = 10,
    call_on_auth: AuthCallback | None = None,
):
    """
    Create a Schwabdev Client from a SecureSchwabConfig.

    The .ecfg file does not store access/refresh tokens. Those remain in
    Schwabdev's token database, encrypted with config.token_db_fernet_key.
    """

    try:
        import schwabdev
    except ImportError as exc:
        raise SchwabdevNotInstalledError(
            'Schwabdev is not installed. Install with: pip install -e ".[schwab]"'
        ) from exc

    _require_supported_schwabdev(schwabdev)

    auth_callback = call_on_auth or console_auth_callback

    # Ensure parent folder exists before Schwabdev attempts to use the DB.
    config.tokens_db.parent.mkdir(parents=True, exist_ok=True)

    return schwabdev.Client(
        app_key=config.app_key,
        app_secret=config.app_secret,
        callback_url=config.callback_url,
        tokens_db=str(config.tokens_db),
        encryption=config.token_db_fernet_key,
        timeout=timeout,
        call_on_auth=auth_callback,
        open_browser_for_auth=False,
    )


def make_secure_schwab_client(
    ecfg_path: str | Path,
    password: str,
    *,
    timeout: int = 10,
    call_on_auth: AuthCallback | None = None,
):
    """
    Load secure_schwabdev.ecfg and create a Schwabdev Client.

    This is the main convenience function most programs should use.
    """

    config = load_secure_schwab_config(ecfg_path, password)

    return make_client_from_config(
        config,
        timeout=timeout,
        call_on_auth=call_on_auth,
    )

