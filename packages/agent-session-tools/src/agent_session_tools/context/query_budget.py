"""Finite VM work for an owned read connection; never a wall-clock guarantee."""

from contextlib import contextmanager


class QueryBudgetExceeded(RuntimeError):
    """No result from the interrupted request may be released."""


@contextmanager
def query_budget(conn, *, steps=1_000_000):
    """Caller owns a read connection with no other progress handler installed.

    SQLite runs this callback every 1000 VM operations. It does not account for
    Python hashing, filesystem latency or every byte read; callers must also cap
    candidate count, body bytes and dependency fanout.
    """
    if type(steps) is not int or steps < 1000:
        raise ValueError("Query work budget must be at least 1000 VM steps")
    work = {"vm_steps": 0, "limit": steps}
    interrupted = False

    def tick():
        nonlocal interrupted
        work["vm_steps"] += 1000
        interrupted = work["vm_steps"] >= steps
        return int(interrupted)

    conn.set_progress_handler(tick, 1000)
    try:
        yield work
    except Exception as exc:
        if interrupted:
            raise QueryBudgetExceeded(
                "Annotation query work budget exhausted; no context returned. "
                "Narrow the request or repair the query plan before retrying."
            ) from exc
        raise
    finally:
        conn.set_progress_handler(None, 0)
