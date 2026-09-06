"""Request-local access consistency for finite read responses.

Readers keep their own data snapshots. Before any completed response is released,
its configured scope and every participating database's access generation must
still match. This is optimistic validation, not a lock on the external config.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from pathlib import Path
from threading import RLock
import inspect
import sqlite3

from .scope import ScopeError

MESSAGE = (
    "Context access changed while preparing this response; no context returned. "
    "Retry after applying the current scope policy."
)


class ScopeConflict(ScopeError):
    """The unfinished read response cannot be released consistently."""


def _generation(conn, schema="main"):
    if not conn.execute(
        f"SELECT 1 FROM {schema}.sqlite_master WHERE name='context_access_state'"
    ).fetchone():
        raise ScopeError(
            "Consistent context reads need the access-generation migration; "
            "run session-context policy apply before retrying"
        )
    row = conn.execute(
        f"SELECT instance,revision FROM {schema}.context_access_state WHERE id=1"
    ).fetchone()
    if row is None:
        raise ScopeError(
            "Context access state is missing; repair the database before reading"
        )
    return tuple(row)


class ReadFrame:
    def __init__(self):
        self.policy = None
        self.scope = None
        self.failed = False
        self.closed = False
        self.monitors = {}
        self.lock = RLock()

    @property
    def used(self):
        return self.policy is not None

    def conflict(self):
        self.failed = True
        raise ScopeConflict(MESSAGE)

    def observe_policy(self, policy):
        with self.lock:
            if (
                self.closed
                or self.failed
                or (self.policy is not None and self.policy != policy)
            ):
                self.conflict()
            self.policy = policy

    def observe_scope(self, policy, scope):
        with self.lock:
            self.observe_policy(policy)
            if self.scope is not None and self.scope != scope:
                self.conflict()
            self.scope = scope

    def observe_database(self, conn, schema):
        with self.lock:
            filename = next(
                (r[2] for r in conn.execute("PRAGMA database_list") if r[1] == schema),
                "",
            )
            if not filename:
                raise ScopeError(
                    "Consistent response reads require a file-backed session database"
                )
            path = Path(filename).resolve()
            observed = _generation(conn, schema)
            if path not in self.monitors:
                monitor = sqlite3.connect(
                    path.as_uri() + "?mode=ro", uri=True, check_same_thread=False
                )
                try:
                    identity = (path.stat().st_dev, path.stat().st_ino)
                    fresh = _generation(monitor)
                    if observed != fresh:
                        self.conflict()
                    self.monitors[path] = (monitor, identity, fresh)
                except BaseException:
                    monitor.close()
                    raise
            if observed != self.monitors[path][2]:
                self.conflict()

    def validate(self):
        from .scope import active_policy

        with self.lock:
            if self.failed:
                self.conflict()
            if not self.used:
                return
            policy = active_policy()
            if self.scope is not None:
                self.observe_scope(policy, policy.request_scope())
            for path, (monitor, identity, generation) in self.monitors.items():
                try:
                    stat = path.stat()
                    changed = identity != (stat.st_dev, stat.st_ino)
                    changed |= _generation(monitor) != generation
                    if changed:
                        self.conflict()
                except (OSError, sqlite3.Error) as exc:
                    self.failed = True
                    raise ScopeConflict(MESSAGE) from exc

    def close(self):
        with self.lock:
            self.closed = True
            for monitor, *_ in self.monitors.values():
                monitor.close()
            self.monitors.clear()


_current: ContextVar[ReadFrame | None] = ContextVar(
    "session_context_read_frame", default=None
)


def observe_policy(policy):
    frame = _current.get()
    if frame is not None:
        frame.observe_policy(policy)


def observe_scope(policy, scope):
    frame = _current.get()
    if frame is not None:
        frame.observe_scope(policy, scope)
    return scope


def observe_database(conn, schema):
    frame = _current.get()
    if frame is not None:
        try:
            frame.observe_database(conn, schema)
        except ScopeError:
            frame.failed = True
            raise
        except (OSError, sqlite3.Error) as exc:
            frame.failed = True
            raise ScopeConflict(MESSAGE) from exc


@contextmanager
def read_boundary():
    """Buffer the caller's return value until validation; never wrap business writes."""
    existing = _current.get()
    if existing is not None:
        yield existing
        existing.validate()
        return
    frame = ReadFrame()
    token = _current.set(frame)
    try:
        yield frame
        frame.validate()
    finally:
        _current.reset(token)
        frame.close()


def consistent_read(function):
    """Preserve the declared tool signature and sync/async execution semantics."""
    if inspect.iscoroutinefunction(function):

        @wraps(function)
        async def asynchronous(*args, **kwargs):
            with read_boundary():
                return await function(*args, **kwargs)

        return asynchronous

    @wraps(function)
    def synchronous(*args, **kwargs):
        with read_boundary():
            return function(*args, **kwargs)

    return synchronous
