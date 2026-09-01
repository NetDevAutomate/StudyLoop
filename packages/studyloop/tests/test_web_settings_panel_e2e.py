"""E2E for the Settings → LLM Providers admin panel.

Drives a real browser against a real ``studyloop web`` server. The provider
list and the secrets / provider-test routes are route-intercepted so the test
is deterministic and never hits a real provider, AWS, or Ollama — but the UI
logic (per-auth_kind controls, save POST body, test loading/ok/error states)
is exercised for real.

Port 18583 (sisters: 18582 key-entry, 18581 struggling-topics, 18580 gen).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from playwright.sync_api import Browser, Page

pytestmark = [pytest.mark.e2e]

WEB_PORT = 18588


# Provider list spanning all three auth kinds, with mixed availability.
_PROVIDERS = [
    {
        "slug": "openai",
        "label": "OpenAI",
        "adapter": "openai_compat",
        "auth_env": "OPENAI_API_KEY",
        "auth_kind": "api_key",
        "available": False,
        "models": [
            {"id": "gpt-x", "label": "GPT-X", "cost_tier": "cheap", "thinking": False, "notes": ""}
        ],
    },
    {
        "slug": "bedrock",
        "label": "AWS Bedrock",
        "adapter": "bedrock",
        "auth_env": "AWS_PROFILE",
        "auth_kind": "bedrock_bearer",
        "available": False,
        "models": [
            {
                "id": "us.anthropic.claude-haiku-4-5-20251001-v1:0",
                "label": "Claude Haiku 4.5 (Bedrock)",
                "cost_tier": "cheap",
                "thinking": False,
                "notes": "",
            }
        ],
    },
    {
        "slug": "ollama",
        "label": "Ollama (local)",
        "adapter": "ollama",
        "auth_env": "",
        "auth_kind": "local_keyless",
        "available": False,
        "base_url": "http://localhost:11434",
        "models": [
            {
                "id": "qwen2.5:7b",
                "label": "Qwen 2.5 7B",
                "cost_tier": "cheap",
                "thinking": False,
                "notes": "",
            }
        ],
    },
]


@pytest.fixture
def stub_config(tmp_path: Path) -> Path:
    cfg = tmp_path / "studyloop-settings.yaml"
    cfg.write_text(
        f"session_db: {tmp_path / 'sessions.db'}\ncard_generator:\n  backend: ollama\n",
        encoding="utf-8",
    )
    return cfg


@pytest.fixture
def server(stub_config: Path) -> Generator[subprocess.Popen, None, None]:
    env = os.environ.copy()
    env["STUDYLOOP_CONFIG"] = str(stub_config)
    proc = subprocess.Popen(
        [sys.executable, "-m", "studyloop.cli", "web", "--port", str(WEB_PORT)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
    )
    for _ in range(40):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{WEB_PORT}/", timeout=1)
            break
        except urllib.error.HTTPError:
            break
        except Exception:
            time.sleep(0.3)
    else:
        proc.kill()
        raise RuntimeError(f"web server failed to start on {WEB_PORT}")
    try:
        yield proc
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
            proc.wait(timeout=5)


def _route_providers(page: Page) -> None:
    page.route(
        "**/api/content/providers",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(_PROVIDERS),
        ),
    )


def _goto_settings(page: Page) -> None:
    page.goto(f"http://127.0.0.1:{WEB_PORT}/#settings")
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_function("() => !!window.Alpine", timeout=5000)
    page.wait_for_function("() => window.Alpine.store('nav').current === 'settings'", timeout=3000)


@pytest.fixture
def page(server, browser: Browser) -> Generator[Page, None, None]:
    context = browser.new_context()
    p = context.new_page()
    try:
        yield p
    finally:
        p.close()
        context.close()


def _wait_rows(page: Page) -> None:
    page.wait_for_function(
        "() => window.Alpine.$data("
        "document.querySelector('[x-data=\"settingsPanel()\"]')"
        ").providers.length > 0",
        timeout=3000,
    )


def _row(page: Page, label: str):
    """Return the single .provider-row whose label is exactly ``label``.

    Filtering on an exact ``.provider-label`` avoids substring collisions
    (e.g. 'OpenAI' ⊂ 'OpenRouter') that break strict-mode locators.
    """
    return page.locator(
        ".provider-row",
        has=page.get_by_text(label, exact=True),
    )


class TestSettingsNavigation:
    def test_settings_button_in_sidebar(self, page: Page) -> None:
        _route_providers(page)
        page.goto(f"http://127.0.0.1:{WEB_PORT}/")
        page.wait_for_function("() => !!window.Alpine", timeout=5000)
        assert page.is_visible(".sidebar button:has-text('Settings')")

    def test_settings_panel_shows_on_nav(self, page: Page) -> None:
        _route_providers(page)
        _goto_settings(page)
        assert page.is_visible(".settings-panel")
        assert page.is_visible(".settings-section:has-text('LLM Providers')")


class TestProviderRowControls:
    def test_api_key_row_shows_password_input(self, page: Page) -> None:
        _route_providers(page)
        _goto_settings(page)
        _wait_rows(page)
        row = _row(page, "OpenAI")
        # Every provider row renders all three auth-kind control divs (x-show
        # hides the inactive ones but they stay in the DOM), so an unscoped
        # input[type=password] matches the api_key AND the hidden bedrock_bearer
        # input. Scope to the visible control to avoid the strict-mode collision.
        assert row.locator("input[type='password']:visible").is_visible()
        assert row.locator("button:visible:has-text('Test & save')").is_visible()

    def test_bedrock_row_shows_bearer_input_and_hint(self, page: Page) -> None:
        _route_providers(page)
        _goto_settings(page)
        _wait_rows(page)
        row = _row(page, "AWS Bedrock")
        assert row.locator("input[type='password']:visible").is_visible()
        assert "AWS_BEARER_TOKEN_BEDROCK" in row.inner_text()

    def test_ollama_row_shows_url_input_not_password(self, page: Page) -> None:
        _route_providers(page)
        _goto_settings(page)
        _wait_rows(page)
        row = _row(page, "Ollama (local)")
        assert row.locator("input[type='text']:visible").is_visible()
        # Hidden api_key/bedrock password inputs still exist in the DOM (x-show);
        # assert no VISIBLE password input rather than none in the DOM.
        assert row.locator("input[type='password']:visible").count() == 0
        assert row.locator("button:visible:has-text('Test connection')").is_visible()


class TestSaveKeyFlow:
    def test_save_key_posts_to_secrets_route(self, page: Page) -> None:
        _route_providers(page)
        posted: dict = {}

        def handle_post(route):
            posted["body"] = route.request.post_data_json
            route.fulfill(
                status=200, content_type="application/json", body=json.dumps({"ok": True})
            )

        page.route("**/api/content/secrets", handle_post)
        _goto_settings(page)
        _wait_rows(page)
        row = _row(page, "OpenAI")
        row.locator("input[type='password']:visible").fill("sk-test-123")
        row.locator("button:visible:has-text('Test & save')").click()
        # Wait for THIS row's success marker to become visible (every row has a
        # .key-ok element; only the acted-on row's is shown via x-show).
        row.locator(".key-ok").wait_for(state="visible", timeout=3000)
        assert posted["body"] == {"provider": "openai", "key": "sk-test-123"}


class TestTestButtonStates:
    def test_ollama_test_success_shows_ok(self, page: Page) -> None:
        _route_providers(page)
        page.route(
            "**/api/content/providers/ollama/test",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"ok": True, "message": "Ollama produced 3 cards"}),
            ),
        )
        _goto_settings(page)
        _wait_rows(page)
        row = _row(page, "Ollama (local)")
        row.locator("button:visible:has-text('Test connection')").click()
        row.locator(".key-ok").wait_for(state="visible", timeout=5000)
        assert "3 cards" in row.inner_text()

    def test_ollama_test_failure_shows_error(self, page: Page) -> None:
        _route_providers(page)
        page.route(
            "**/api/content/providers/ollama/test",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"ok": False, "message": "unreachable at localhost"}),
            ),
        )
        _goto_settings(page)
        _wait_rows(page)
        row = _row(page, "Ollama (local)")
        row.locator("button:visible:has-text('Test connection')").click()
        row.locator(".key-error").wait_for(state="visible", timeout=5000)
        assert "unreachable" in row.inner_text()
