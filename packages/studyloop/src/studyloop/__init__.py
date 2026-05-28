"""studyloop — AuDHD study pipeline CLI."""

from __future__ import annotations

import os
from pathlib import Path

__version__ = "2.1.0"


def _load_dotenv_once() -> None:
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
    """
    if os.environ.get("STUDYLOOP_SKIP_DOTENV") == "1":
        return
    try:
        from dotenv import load_dotenv  # noqa: PLC0415 -- import-time optional dep
    except ImportError:
        return

    here = Path.cwd()
    for candidate in (here, *here.parents[:6]):
        env_file = candidate / ".env"
        if env_file.is_file():
            load_dotenv(env_file, override=False)
            return


_load_dotenv_once()
