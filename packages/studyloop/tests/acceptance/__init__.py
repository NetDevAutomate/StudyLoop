"""The acceptance tier: opt-in (STUDYLOOP_ACC=1), subprocess-isolated tests.

See docs/acceptance-testing.md for the tiers table, every env var, and the
sweeper guarantee. This package is deliberately NOT collected unless a caller
explicitly selects ``-m acceptance`` — both pyproject.toml files deselect the
``acceptance`` marker by default (see tests/test_acceptance_gate.py).
"""

from __future__ import annotations
