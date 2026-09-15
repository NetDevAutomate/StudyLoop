"""The UAT tier's OWN, additional opt-in on top of acceptance (council D-13).

Every test under this package already inherits ``tests/acceptance/conftest.py``'s
autouse ``_acceptance_gate`` (``STUDYLOOP_ACC=1``) simply by living under
``tests/acceptance/``. This module adds the second, UAT-specific gate the
brief's council amendments describe: ``STUDYLOOP_UAT=1``, required in
ADDITION to ``STUDYLOOP_ACC=1``, never instead of it.

Missing either variable is a named skip, the same "skip by name, never
fail" discipline the acceptance tier's own gate uses -- see
docs/acceptance-testing.md.
"""

from __future__ import annotations

import os

import pytest

_UAT_ENV = "STUDYLOOP_UAT"


@pytest.fixture(autouse=True)
def _uat_gate() -> None:
    if os.environ.get(_UAT_ENV) != "1":
        pytest.skip(
            f"UAT sign-off tests require {_UAT_ENV}=1 in addition to STUDYLOOP_ACC=1 "
            "(see docs/acceptance-testing.md)"
        )
