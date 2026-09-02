"""studyloop — AuDHD study pipeline CLI."""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


def _package_version() -> str:
    try:
        from importlib.metadata import version

        return version("studyloop")
    except Exception:
        return "0.0.0+unknown"


__version__ = _package_version()


def _load_dotenv_once() -> Path | None:
    """Load `.env` from the first parent dir that has one, on import.

    The content-generation panel's HTTP adapters look up provider API
    keys via ``os.environ`` (per the registry's ``auth_env`` field). A
    long-lived web service or one-shot CLI both want those keys to be
    present without the user having to ``set -a; source .env`` in
    every shell.

    ``override=False`` means an explicitly-exported shell var always
    wins over the file -- safer for CI / cross-machine setups.

    Walks up at most six parent dirs to find a `.env`. If none is
    found, this is a silent no-op -- the env is what it is. If
    python-dotenv isn't installed (older deployments), also silent
    no-op rather than ImportError-cascading at package import time.

    Returns the `.env` path that was loaded, or ``None`` if none was found
    (or python-dotenv is unavailable) -- the caller needs it to name the
    file in the R-09 test-hatch warning below.
    """
    if os.environ.get("STUDYLOOP_SKIP_DOTENV") == "1":
        return None
    try:
        from dotenv import load_dotenv
    except ImportError:
        return None

    here = Path.cwd()
    for candidate in (here, *here.parents[:6]):
        env_file = candidate / ".env"
        if env_file.is_file():
            load_dotenv(env_file, override=False)
            return env_file
    return None


def _scrub_dotenv_test_hatch(pre_dotenv_test_keys: frozenset[str], env_file: Path | None) -> None:
    """Refuse any STUDYLOOP_TEST_* hatch that only arrived via a planted `.env`.

    STUDYLOOP_TEST_AGENT_CMD / STUDYLOOP_TEST_ACP_CMD are shell=True-executed
    test-only escape hatches, read unconditionally in the production
    session-start path. `_load_dotenv_once()`'s `override=False` only skips a
    name the real shell already exported -- so a `.env` planted in or above
    whatever directory a user runs `studyloop` from can set the hatch itself,
    on a machine with no exported shell var to stop it (R-09).

    The e2e harness exports these variables for real, directly in the
    process's environment, before this package is even imported -- so a name
    already present BEFORE `_load_dotenv_once()` ran is trusted and kept.
    Anything with the same prefix that shows up only AFTER the dotenv load
    was never in the real environment; delete it and log once, naming the key
    and the `.env` path that introduced it, so a planted file cannot silently
    grant shell execution on the next session start.
    """
    if env_file is None:
        return
    for key in [k for k in os.environ if k.startswith("STUDYLOOP_TEST_")]:
        if key in pre_dotenv_test_keys:
            continue
        del os.environ[key]
        logger.warning(
            "Ignoring %s loaded from %s: STUDYLOOP_TEST_* test hatches are "
            "only honoured when exported in the real process environment, "
            "never when set by a .env file.",
            key,
            env_file,
        )


_pre_dotenv_test_keys = frozenset(k for k in os.environ if k.startswith("STUDYLOOP_TEST_"))
_dotenv_path = _load_dotenv_once()
_scrub_dotenv_test_hatch(_pre_dotenv_test_keys, _dotenv_path)
