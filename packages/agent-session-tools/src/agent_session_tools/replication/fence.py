"""Request-local checks at replica transaction commits; inactive for other callers."""

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Callable

_check: ContextVar[Callable[[], None] | None] = ContextVar(
    "replica_fence", default=None
)


def check():
    callback = _check.get()
    if callback is not None:
        callback()


@contextmanager
def guarded(callback):
    token = _check.set(callback)
    try:
        callback()
        yield
        callback()
    finally:
        _check.reset(token)
