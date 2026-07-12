"""Shared test helpers for agent-session-tools.

Import ``run_async`` in test files that need to call async code from sync
test bodies or fixtures.
"""

from __future__ import annotations

import asyncio
import threading
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Coroutine


# A single dedicated event loop, reused for every run_async() call across the
# whole test session, running on its own background thread.
#
# WHY NOT asyncio.run(): asyncio.run() raises "cannot be called from a
# running event loop" if ANY loop is already running on the calling thread.
# In a full multi-package suite run, pytest-asyncio (asyncio_mode=strict) can
# leave a loop installed/running on the main thread after an async test in a
# *sibling* package collected into the same session, so a later bare
# asyncio.run() in a sync test/fixture here would explode. See
# packages/studyloop/tests/_helpers.py for the sibling package's identical
# fix and the full incident writeup (commit 86d2579).
#
# Running on a background thread means run_async() works regardless of
# whether the *calling* thread already has a running loop.
_loop: asyncio.AbstractEventLoop | None = None
_loop_thread: threading.Thread | None = None
_loop_lock = threading.Lock()


def _ensure_loop() -> asyncio.AbstractEventLoop:
    """Return the shared background event loop, starting it on first use."""
    global _loop, _loop_thread
    with _loop_lock:
        if _loop is not None and _loop.is_running():
            return _loop
        _loop = asyncio.new_event_loop()
        _loop_thread = threading.Thread(
            target=_loop.run_forever,
            name="agent-session-tools-test-loop",
            daemon=True,
        )
        _loop_thread.start()
        return _loop


def run_async(coro: Coroutine[Any, Any, Any]) -> Any:
    """Run ``coro`` to completion on a dedicated background event loop.

    Drop-in replacement for ``asyncio.run(coro)`` in synchronous test code
    that is robust to an already-running loop on the calling thread.
    """
    loop = _ensure_loop()
    return asyncio.run_coroutine_threadsafe(coro, loop).result()
