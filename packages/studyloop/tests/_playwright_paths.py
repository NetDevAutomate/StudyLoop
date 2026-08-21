"""Canonical repository locations for Playwright evidence.

Keep committed visual baselines separate from transient failure diagnostics:

* ``playwright/snapshots`` contains reviewed ``to_have_screenshot`` baselines;
* ``playwright/artifacts`` contains screenshots, HTML, traces, console logs,
  terminal buffers, and other run output.

The paths are anchored to the repository, rather than the process working
directory, so running pytest from the repository root or a package directory
produces the same layout.
"""

from __future__ import annotations

from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
PLAYWRIGHT_ROOT = REPOSITORY_ROOT / "playwright"
PLAYWRIGHT_ARTIFACTS = PLAYWRIGHT_ROOT / "artifacts"
PLAYWRIGHT_SNAPSHOTS = PLAYWRIGHT_ROOT / "snapshots"
