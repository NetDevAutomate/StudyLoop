#!/usr/bin/env python3
"""Capture a headless screenshot of the studyctl TUI dashboard.

Requires the [tui] extra: uv pip install studyctl[tui]

Usage:
    uv run scripts/capture_tui_screenshot.py
"""

from __future__ import annotations

import asyncio
from pathlib import Path


async def main() -> None:
    from studyctl.tui.app import StudyApp

    app = StudyApp()
    async with app.run_test(size=(120, 40)) as pilot:
        # Wait for mount and population
        await pilot.pause()
        out = Path("images/socratic_mentor_tui.svg")
        app.save_screenshot(filename=out.name, path=str(out.parent))
        print(f"Screenshot saved to {out}")


if __name__ == "__main__":
    asyncio.run(main())
