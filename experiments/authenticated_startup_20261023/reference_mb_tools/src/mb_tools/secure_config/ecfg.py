"""
Password-based encrypted configuration files.

This module provides a small API for saving and loading encrypted
dictionary-like configuration files using a user-supplied password.

The password is not stored. A random salt is embedded in the encrypted
file so that no separate salt file is required.
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


_MAGIC = b"MB_ECFG_V1\n"
_SALT_SIZE = 16
_PBKDF2_ITERATIONS = 390_000


class EcfgError(Exception):
    """Base exception for encrypted configuration errors."""


class EcfgFormatError(EcfgError):
    """Raised when an .ecfg file has an invalid or unsupported format."""


class EcfgDecryptError(EcfgError):
    """Raised when decryption fails, usually due to a wrong password."""


def _normalize_password(password: str | bytes | bytearray) -> bytes:
    if isinstance(password, str):
        return password.encode("utf-8")

    if isinstance(password, bytearray):
        return bytes(password)

    if isinstance(password, bytes):
        return password

    raise TypeError("password must be str, bytes, or bytearray")


def _derive_fernet_key(password: str | bytes | bytearray, salt: bytes) -> bytes:
    password_bytes = _normalize_password(password)

    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=_PBKDF2_ITERATIONS,
    )

    key = base64.urlsafe_b64encode(kdf.derive(password_bytes))
    return key


def _get_fernet(password: str | bytes | bytearray, salt: bytes) -> Fernet:
    return Fernet(_derive_fernet_key(password, salt))


def save_ecfg(
    path: str | Path,
    data: dict[str, Any],
    password: str | bytes | bytearray,
) -> None:
    """
    Save a dictionary to an encrypted .ecfg file.

    Parameters
    ----------
    path:
        Destination file path.

    data:
        Dictionary-compatible data to serialize as JSON.

    password:
        User-supplied password. The password is not stored.
    """
    path = Path(path)

    if not isinstance(data, dict):
        raise TypeError("data must be a dictionary")

    salt = os.urandom(_SALT_SIZE)
    fernet = _get_fernet(password, salt)

    plaintext = json.dumps(data, indent=2, sort_keys=True).encode("utf-8")
    ciphertext = fernet.encrypt(plaintext)

    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("wb") as f:
        f.write(_MAGIC)
        f.write(salt)
        f.write(ciphertext)


def load_ecfg(
    path: str | Path,
    password: str | bytes | bytearray,
) -> dict[str, Any]:
    """
    Load and decrypt an .ecfg file.

    Parameters
    ----------
    path:
        Path to the encrypted file.

    password:
        User-supplied password.

    Returns
    -------
    dict[str, Any]
        The decrypted dictionary.
    """
    path = Path(path)

    raw = path.read_bytes()

    if not raw.startswith(_MAGIC):
        raise EcfgFormatError(f"Not a supported .ecfg file: {path}")

    body = raw[len(_MAGIC):]

    if len(body) <= _SALT_SIZE:
        raise EcfgFormatError(f"Incomplete .ecfg file: {path}")

    salt = body[:_SALT_SIZE]
    ciphertext = body[_SALT_SIZE:]

    fernet = _get_fernet(password, salt)

    try:
        plaintext = fernet.decrypt(ciphertext)
    except InvalidToken as exc:
        raise EcfgDecryptError(
            "Could not decrypt .ecfg file. The password may be incorrect, "
            "or the file may be damaged."
        ) from exc

    try:
        data = json.loads(plaintext.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise EcfgFormatError(
            "The decrypted file did not contain valid JSON."
        ) from exc

    if not isinstance(data, dict):
        raise EcfgFormatError(
            "The decrypted file did not contain a dictionary."
        )

    return data


def read_ecfg_value(
    path: str | Path,
    key: str,
    password: str | bytes | bytearray,
    default: Any = None,
) -> Any:
    """
    Load an encrypted config file and return one value by key.

    Parameters
    ----------
    path:
        Path to the encrypted file.

    key:
        Dictionary key to retrieve.

    password:
        User-supplied password.

    default:
        Value returned if the key is missing.
    """
    data = load_ecfg(path, password)
    return data.get(key, default)
