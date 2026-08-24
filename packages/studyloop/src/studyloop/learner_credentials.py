"""One-way learner credential verification for LAN access.

The reusable human password must never be persisted or handed to an agent
process.  This module stores only a versioned scrypt verifier and deliberately
accepts exactly one bounded parameter set so a corrupt config cannot turn
verification into an unbounded CPU or memory operation.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

_SCHEME = "scrypt-v1"
_N = 1 << 14
_R = 8
_P = 1
_SALT_BYTES = 16
_KEY_BYTES = 32
_MAX_MEMORY = 64 * 1024 * 1024


class LearnerCredentialError(Exception):
    """Raised when human-owned LAN authority cannot be prepared safely."""


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii")


def _decode(value: str) -> bytes:
    return base64.b64decode(value.encode("ascii"), altchars=b"-_", validate=True)


def hash_password(password: str) -> str:
    """Return a salted, versioned scrypt verifier for a non-empty password."""
    if not isinstance(password, str) or not password:
        raise ValueError("LAN password must not be empty")
    salt = os.urandom(_SALT_BYTES)
    derived = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_N,
        r=_R,
        p=_P,
        dklen=_KEY_BYTES,
        maxmem=_MAX_MEMORY,
    )
    return f"{_SCHEME}${_N}${_R}${_P}${_encode(salt)}${_encode(derived)}"


def _parse_verifier(verifier: str) -> tuple[bytes, bytes] | None:
    try:
        scheme, n_text, r_text, p_text, salt_text, derived_text = verifier.split("$")
        if (scheme, int(n_text), int(r_text), int(p_text)) != (_SCHEME, _N, _R, _P):
            return None
        salt = _decode(salt_text)
        derived = _decode(derived_text)
    except (AttributeError, UnicodeEncodeError, ValueError):
        return None
    if len(salt) != _SALT_BYTES or len(derived) != _KEY_BYTES:
        return None
    return salt, derived


def is_password_verifier(verifier: str) -> bool:
    """Return whether *verifier* is a supported, safely bounded encoding."""
    return _parse_verifier(verifier) is not None


def verify_password(password: str, verifier: str) -> bool:
    """Verify a presented password without retaining it or exposing failures."""
    parsed = _parse_verifier(verifier)
    if parsed is None or not isinstance(password, str):
        return False
    salt, expected = parsed
    try:
        actual = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=_N,
            r=_R,
            p=_P,
            dklen=_KEY_BYTES,
            maxmem=_MAX_MEMORY,
        )
    except (UnicodeEncodeError, ValueError):
        return False
    return hmac.compare_digest(actual, expected)


def prepare_lan_auth(
    *,
    username: str,
    configured_verifier: str,
    emit: Callable[[str], None],
) -> tuple[str, str]:
    """Prepare LAN auth interactively and return only username plus verifier.

    User-entered plaintext never leaves this function. A generated one-time
    password crosses only the deliberately non-retaining output callback.
    """
    normalized_username = username or "study"
    from studyloop.web.runtime_feedback import emit_lan_credential_lines

    if configured_verifier:
        if not is_password_verifier(configured_verifier):
            raise LearnerCredentialError("The configured LAN password verifier is invalid")
        emit_lan_credential_lines(
            username=normalized_username,
            generated_password=None,
            emit=emit,
        )
        return normalized_username, configured_verifier

    import getpass
    import secrets
    import sys

    if not sys.stdin.isatty():
        raise LearnerCredentialError(
            "LAN access needs an interactive terminal to establish the human password. "
            "Run the command directly in a terminal; non-interactive fallback is refused."
        )
    try:
        password = getpass.getpass("LAN password (leave blank to generate one): ")
        generated = not password
        if generated:
            password = secrets.token_urlsafe(16)
        else:
            confirmation = getpass.getpass("Confirm LAN password: ")
            if not hmac.compare_digest(password, confirmation):
                raise LearnerCredentialError("LAN passwords did not match; nothing was started")
        verifier = hash_password(password)
        emit_lan_credential_lines(
            username=normalized_username,
            generated_password=password if generated else None,
            emit=emit,
        )
        return normalized_username, verifier
    except (EOFError, KeyboardInterrupt) as exc:
        raise LearnerCredentialError(
            "LAN password entry was cancelled; nothing was started"
        ) from exc
    finally:
        if "password" in locals():
            password = ""
