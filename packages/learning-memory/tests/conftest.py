"""Fixtures and the hypothesis profile for the learning-memory suite.

Property tests build their own store inside the test body (``fresh_store``):
hypothesis re-runs a test body many times against one function-scoped fixture
instance, and a shared database would make the examples depend on each other.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from hypothesis import HealthCheck, settings

if TYPE_CHECKING:
    from collections.abc import Iterator

    from learning_memory import Store

try:  # package-scoped run (pytest "prepend" import mode)
    from _helpers import fresh_store
except ImportError:  # workspace-root run (pytest "importlib" import mode)
    from tests._helpers import fresh_store

settings.register_profile(
    "learning_memory",
    deadline=None,  # every example touches SQLite; a wall-clock deadline just flakes
    max_examples=40,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
settings.load_profile("learning_memory")


@pytest.fixture
def store() -> Iterator[Store]:
    """An installed, empty, in-memory store for example-based tests."""
    with fresh_store() as opened:
        yield opened
