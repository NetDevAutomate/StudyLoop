"""Canonical vocabulary for the ``tts.backend`` config key.

Every voice code path used to compare bare strings against its own private
default, and the defaults disagreed: ``speak.py`` and ``doctor/voice.py`` said
``kokoro`` while ``learning/voice.py`` said ``openvox``. Nothing validated the
value at all, so ``backend: openvoxx`` matched no branch and fell straight
through to macOS ``say`` — Apple audio, no error, no explanation.

``kokoro`` is the default for terminal/CLI/MCP voice because the supported
product behaviour is to use local ``kokoro-onnx``; ``openvox`` stays an
explicit opt-in.

MIRROR WARNING
--------------
``agent_session_tools.tts_backends`` is a byte-for-byte-equivalent copy. The two
packages are independently publishable and must not import each other (see
``agent_session_tools.config_loader``'s module docstring), so the vocabulary is
duplicated on purpose. ``packages/studyloop/tests/test_voice_backends.py``
asserts the two stay in step — change one, change both.
"""

from __future__ import annotations

#: Backends ``study-speak`` / the CLI / the doctor understand.
VALID_BACKENDS: frozenset[str] = frozenset({"openvox", "kokoro", "qwen3", "macos"})

#: The one default. Do not re-declare a different one at a call site.
DEFAULT_BACKEND: str = "kokoro"


class UnknownBackendError(ValueError):
    """Raised for a ``tts.backend`` value outside :data:`VALID_BACKENDS`."""


def resolve_backend(value: object, *, default: str = DEFAULT_BACKEND) -> str:
    """Normalise and validate a configured or CLI-supplied backend name.

    Unset (``None``, blank, or a non-string such as a YAML list) means "use the
    default". A *present but unrecognised* value is a mistake worth surfacing:
    it raises rather than quietly degrading, because quiet degradation is the
    bug this module exists to kill.

    Raises:
        UnknownBackendError: for an unrecognised backend name.
    """
    if default not in VALID_BACKENDS:
        raise UnknownBackendError(_unknown_message(default))
    if not isinstance(value, str):
        return default
    name = value.strip().lower()
    if not name:
        return default
    if name not in VALID_BACKENDS:
        raise UnknownBackendError(_unknown_message(value))
    return name


def _unknown_message(value: object) -> str:
    allowed = ", ".join(sorted(VALID_BACKENDS))
    return f"unknown tts backend {value!r} — valid backends are: {allowed}"
