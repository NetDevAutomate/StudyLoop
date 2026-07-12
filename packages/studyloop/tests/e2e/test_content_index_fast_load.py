"""Minimal smoke test for fast content index loading and real-time left pane status.

DEPRECATED as a standalone test. The authoritative end-to-end test is now
`test_representative_user_journey.py`, which has been expanded to cover the
complete representative user flow:

    Body Double → Socratic study session → Flashcards (≥5 + support) →
    Quizzes (≥5 + support) → Mastery tab with real-time RHS/index updates.

This narrow smoke test is retained only for rapid iteration while the
index/UI sync bug (provider dropdown never appears) is being fixed.
Once that bug is resolved, `test_representative_user_journey.py` becomes
the single canonical gate for the full product.
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("playwright")
pytest.importorskip("requests")

from playwright.sync_api import ConsoleMessage, Page, expect, TimeoutError as PlaywrightTimeout

from _playwright_helpers import start_web_server

pytestmark = [pytest.mark.e2e]

WEB_PORT = 18592
DEBUG = bool(os.getenv("STUDYLOOP_E2E_DEBUG"))


def _capture_diagnostics(
    page: Page | None,
    test_name: str,
    console_messages: list[dict[str, Any]] | None = None,
    extra_note: str = "",
) -> None:
    """Capture rich failure diagnostics (best practice for E2E tests)."""
    ts = int(time.time())
    results_dir = Path("test-results")
    results_dir.mkdir(exist_ok=True)

    artifacts: list[str] = []

    if page:
        try:
            png_path = results_dir / f"{test_name}-{ts}.png"
            page.screenshot(path=str(png_path), full_page=True)
            artifacts.append(str(png_path))

            html_path = results_dir / f"{test_name}-{ts}.html"
            html_path.write_text(page.content())
            artifacts.append(str(html_path))
        except Exception as exc:
            print(f"[diagnostics] Screenshot/HTML failed: {exc}")

    if console_messages:
        errors = [m for m in console_messages if m["type"] in ("error", "warning")]
        if errors:
            log_path = results_dir / f"{test_name}-{ts}-console.txt"
            with open(log_path, "w") as f:
                for m in errors:
                    f.write(f"[{m['type'].upper()}] {m['text']}\n")
            artifacts.append(str(log_path))

    if artifacts:
        print("\n[diagnostics] Failure artifacts saved:")
        for a in artifacts:
            print(f"  - {a}")
    if extra_note:
        print(f"[diagnostics] Note: {extra_note}")

    if DEBUG:
        print("[diagnostics] DEBUG mode active.")


@pytest.fixture(scope="module")
def running_server():
    proc = start_web_server(WEB_PORT)
    try:
        yield f"http://127.0.0.1:{WEB_PORT}"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()


def test_index_loads_fast_and_left_pane_updates(browser, running_server: str) -> None:
    """Iteration 1: Force index via CLI, then validate UI + session status."""
    base_url = running_server
    context = browser.new_context()
    page: Page = context.new_page()

    console_messages: list[dict[str, Any]] = []

    def on_console(msg: ConsoleMessage) -> None:
        console_messages.append({"type": msg.type, "text": msg.text})

    page.on("console", on_console)

    try:
        # === Data-driven fix: Force fresh index using the working CLI ===
        print("[iteration-1] Forcing content index refresh via CLI...")
        result = subprocess.run(
            ["uv", "run", "studyloop", "content", "index", "--force"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            print(result.stderr)
            pytest.fail("Content index refresh failed. See output above.")

        print("[iteration-1] Index refresh complete. Loading Generate tab...")

        page.goto(f"{base_url}/#generate")
        page.wait_for_load_state("domcontentloaded")

        # Early diagnostic for provider dropdown
        try:
            page.wait_for_selector("select[name='provider']", timeout=6000)
            page.select_option("select[name='provider']", label="ArjanCodes")
        except PlaywrightTimeout:
            _capture_diagnostics(
                page,
                "content_index_fast_load",
                console_messages,
                extra_note="Provider dropdown still missing after CLI index refresh.",
            )
            pytest.fail("Provider dropdown did not appear. Check diagnostics in test-results/.")

        expect(page.locator("select[name='course'] option")).not_to_have_text(
            "— pick a publisher first —", timeout=8000
        )

        # Session start + left pane checks
        import requests

        topic = "Software Design Mastery 1/3 | CORE DESIGNER - Abstraction and Coupling"
        resp = requests.post(
            f"{base_url}/api/session/start",
            json={
                "topic": topic,
                "energy": 7,
                "agent": "Claude Code",
                "transport": "Browser terminal (xterm.js)",
            },
            timeout=10,
        )

        if not resp.ok:
            _capture_diagnostics(page, "content_index_fast_load", console_messages)
            pytest.fail(f"Session start failed: {resp.status_code} {resp.text[:300]}")

        expect(page.locator("#activity-feed")).to_contain_text(
            "Session live — wins and parked questions appear here", timeout=8000
        )
        expect(page.locator("#session-meta")).to_contain_text("Abstraction", timeout=5000)

        print("\n✅ Iteration 1 passed — provider dropdown and session status working.")

    except Exception:
        _capture_diagnostics(page, "content_index_fast_load", console_messages)
        raise
    finally:
        page.remove_listener("console", on_console)
        context.close()
