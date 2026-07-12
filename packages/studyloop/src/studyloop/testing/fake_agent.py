"""studyloop-fake-agent — deterministic stand-in agent for e2e harness runs.

A real console script (so ``shutil.which`` finds it like any agent binary)
that speaks just enough "agent" to exercise the spawn → PTY → WebSocket →
terminal path without an LLM:

- prints a recognisable banner (``FAKE-AGENT READY``) on startup
- echoes each stdin line back as a canned mentor-ish reply
- exits cleanly on EOF or SIGTERM so session teardown is exercised

It is registered as the ``fake`` adapter ONLY when ``STUDYLOOP_TEST_AGENT=1``
(see ``adapters/fake.py``), so it never appears in a real user's picker.
"""

from __future__ import annotations

import signal
import sys

BANNER = "FAKE-AGENT READY"
REPLY_PREFIX = "FAKE-AGENT SAYS:"


def main() -> int:
    """Run the echo loop. Deterministic, line-buffered, TTY-safe."""
    # Under pty.fork() stdout is a tty and line-buffering applies, but be
    # explicit: every write is flushed so tests never race the buffer.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))

    # Ignore the persona-file argument (argv[1]) — a real agent reads it;
    # the fake only needs to prove bytes flow both ways.
    sys.stdout.write(BANNER + "\r\n")
    sys.stdout.flush()

    try:
        for line in sys.stdin:
            text = line.strip()
            if not text:
                continue
            if text.lower() in {"exit", "quit"}:
                break
            sys.stdout.write(f"{REPLY_PREFIX} I hear you on {text!r} — tell me more.\r\n")
            sys.stdout.flush()
    except (KeyboardInterrupt, BrokenPipeError):
        pass

    sys.stdout.write("FAKE-AGENT BYE\r\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
