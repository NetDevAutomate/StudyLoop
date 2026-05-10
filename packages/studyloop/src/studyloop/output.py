"""Shared utilities — importable without pulling in CLI machinery.

This breaks the circular dependency where ``session/`` modules needed
``cli/_shared.console`` but ``cli/`` imports from ``session/``.
"""

from __future__ import annotations

from rich.console import Console

console = Console()


def energy_to_label(energy: int) -> str:
    """Map integer energy level (1-10) to a label for the DB."""
    if energy <= 3:
        return "low"
    if energy <= 7:
        return "medium"
    return "high"
