"""Readiness probe for a persona's REAL harness (module-contract v1, lane U1, review F2).

The probes are the harness-matrix lane's (``acceptance/test_harness_matrix_live.py``'s
``PROBES``: ``kiro-cli whoami`` under the scratch environment for kiro, presence for the other
five), imported rather than copied so the two lanes can never disagree about what "ready" means
for a harness. Nothing here runs for the fake agent.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..test_harness_matrix_live import PROBES, _presence_only_probe

if TYPE_CHECKING:
    from collections.abc import Mapping


def harness_probe(name: str, binary: str, env: Mapping[str, str]) -> tuple[bool, str]:
    """``(ok, reason)`` for ``name``'s ``binary`` under ``env`` -- the matrix lane's own probe."""
    probe = PROBES.get(name, _presence_only_probe)
    return probe(binary, env)


__all__ = ["harness_probe"]
