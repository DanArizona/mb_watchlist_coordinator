"""
Secure Schwabdev integration for mb_tools.

This package uses mb_tools.secure_config to load Schwabdev credentials
and the Schwabdev token database encryption key from an encrypted .ecfg file.
"""

from .config import (
    REQUIRED_ECFG_KEYS,
    SecureSchwabConfig,
    SecureSchwabConfigError,
    config_from_dict,
    load_secure_schwab_config,
    validate_schwabdev_key_shape,
    validate_secure_schwab_dict,
)


from .client import (
    MINIMUM_SCHWABDEV_VERSION,
    SchwabdevNotInstalledError,
    SchwabdevVersionError,
    console_auth_callback,
    make_client_from_config,
    make_secure_schwab_client,
)
from .status import (
    DEFAULT_POLLING_REFRESH_MARGIN,
    SCHWABDEV_INTERACTIVE_REFRESH_THRESHOLD,
    SchwabCredentialPreflightError,
    SchwabTokenStatus,
    SchwabTokenStatusError,
    read_schwab_token_status,
)
from .reauthorize import (
    SchwabForceReauthorizationError,
    SchwabForceReauthorizationResult,
    force_schwab_reauthorization,
    token_database_backup_path,
)


__all__ = [
    "REQUIRED_ECFG_KEYS",
    "SecureSchwabConfig",
    "SecureSchwabConfigError",
    "config_from_dict",
    "load_secure_schwab_config",
    "validate_schwabdev_key_shape",
    "validate_secure_schwab_dict",
    "SchwabdevNotInstalledError",
    "SchwabdevVersionError",
    "MINIMUM_SCHWABDEV_VERSION",
    "console_auth_callback",
    "make_client_from_config",
    "make_secure_schwab_client",
    "DEFAULT_POLLING_REFRESH_MARGIN",
    "SCHWABDEV_INTERACTIVE_REFRESH_THRESHOLD",
    "SchwabCredentialPreflightError",
    "SchwabTokenStatus",
    "SchwabTokenStatusError",
    "read_schwab_token_status",
    "SchwabForceReauthorizationError",
    "SchwabForceReauthorizationResult",
    "force_schwab_reauthorization",
    "token_database_backup_path",
]
