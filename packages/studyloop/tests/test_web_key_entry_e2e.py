"""E2E for the Generate-panel inline API-key entry (feature gap #2).

Drives a real browser against a real ``studyloop web`` server. The provider
list and the secrets POST are route-intercepted so the test is deterministic
and never hits a real LLM provider — but the UI logic (show/hide the key form,
POST the right body, reflect success) is exercised for real.

Port 18582 (sisters use 18580 content-gen, 18581 struggling-topics).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Generator
from pathlib import Path

import pytest
from playwright.sync_api import Browser, Page

pytestmark = [pytest.mark.e2e]

WEB_PORT = 18582


@pytest.fixture
def stub_config(tmp_path: Path) -> Path:
    cfg = tmp_path / "studyloop-keyentry.yaml"
    cfg.write_text(
        f"session_db: {tmp_path / 'sessions.db'}\n"
        "card_generator:\n  backend: stub\n",
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


# Provider list with anthropic NOT available (no key) — the trigger for the form.
_PROVIDERS = [
    {
        "slug": "anthropic",
        "label": "Anthropic",
        "adapter": "anthropic_compat",
        "auth_env": "ANTHROPIC_API_KEY",
        "available": False,
        "models": [{"id": "claude-haiku-4-5", "label": "Haiku", "cost_tier": "cheap", "thinking": False, "notes": ""}],
    },
    {
        "slug": "openai",
        "label": "OpenAI",
        "adapter": "openai_compat",
        "auth_env": "OPENAI_API_KEY",
        "available": True,  # already has a key — form must NOT show
        "models": [{"id": "gpt-x", "label": "GPT-X", "cost_tier": "balanced", "thinking": False, "notes": ""}],
    },
]


def _route_providers(page: Page, *, anthropic_available: bool) -> None:
    providers = json.loads(json.dumps(_PROVIDERS))
    providers[0]["available"] = anthropic_available
    page.route(
        "**/api/content/providers",
        lambda route: route.fulfill(
            status=200, content_type="application/json", body=json.dumps(providers)
        ),
    )


def _goto_generate(page: Page) -> None:
    page.goto(f"http://127.0.0.1:{WEB_PORT}/#generate")
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_function("() => !!window.Alpine", timeout=5000)
    page.wait_for_function(
        "() => window.Alpine.store('nav').current === 'generate'", timeout=3000
    )


@pytest.fixture
def page(server, browser: Browser) -> Generator[Page, None, None]:
    context = browser.new_context()
    p = context.new_page()
    try:
        yield p
    finally:
        p.close()
        context.close()


class TestKeyEntryUI:
    def test_key_form_appears_for_unavailable_keyed_provider(self, page: Page) -> None:
        _route_providers(page, anthropic_available=False)
        _goto_generate(page)
        page.wait_for_function(
            "() => window.Alpine.$data(document.querySelector('[x-data=\"generatePanel()\"]')).providers.length > 0",
            timeout=3000,
        )
        # Select anthropic (no key) → the inline key form must appear.
        page.select_option('select[x-model="form.provider"]', "anthropic")
        page.wait_for_selector(".api-key-entry input[type='password']", state="visible", timeout=3000)
        assert page.is_visible(".api-key-entry input[type='password']")

    def test_key_form_hidden_for_available_provider(self, page: Page) -> None:
        _route_providers(page, anthropic_available=False)
        _goto_generate(page)
        page.wait_for_function(
            "() => window.Alpine.$data(document.querySelector('[x-data=\"generatePanel()\"]')).providers.length > 0",
            timeout=3000,
        )
        # OpenAI is available → no key form.
        page.select_option('select[x-model="form.provider"]', "openai")
        page.wait_for_timeout(300)
        assert not page.is_visible(".api-key-entry input[type='password']")

    def test_save_key_posts_and_shows_success(self, page: Page) -> None:
        _route_providers(page, anthropic_available=False)

        posted: dict = {}

        def handle_post(route):
            req = route.request
            posted["body"] = req.post_data_json
            # After a successful save the UI re-fetches providers; flip anthropic
            # to available so the success path is realistic.
            _route_providers(page, anthropic_available=True)
            route.fulfill(status=200, content_type="application/json", body=json.dumps({"ok": True}))

        page.route("**/api/content/secrets", handle_post)

        _goto_generate(page)
        page.wait_for_function(
            "() => window.Alpine.$data(document.querySelector('[x-data=\"generatePanel()\"]')).providers.length > 0",
            timeout=3000,
        )
        page.select_option('select[x-model="form.provider"]', "anthropic")
        page.wait_for_selector(".api-key-entry input[type='password']", state="visible", timeout=3000)
        page.fill(".api-key-entry input[type='password']", "sk-test-12345")
        page.click(".api-key-entry button")

        # Success message appears.
        page.wait_for_selector(".api-key-entry .key-ok", state="visible", timeout=3000)
        assert page.is_visible(".api-key-entry .key-ok")
        # The POST carried the right provider + key.
        assert posted["body"] == {"provider": "anthropic", "key": "sk-test-12345"}

    def test_save_key_shows_error_on_rejection(self, page: Page) -> None:
        _route_providers(page, anthropic_available=False)
        page.route(
            "**/api/content/secrets",
            lambda route: route.fulfill(
                status=400,
                content_type="application/json",
                body=json.dumps({"detail": "Provider rejected the key (401)."}),
            ),
        )
        _goto_generate(page)
        page.wait_for_function(
            "() => window.Alpine.$data(document.querySelector('[x-data=\"generatePanel()\"]')).providers.length > 0",
            timeout=3000,
        )
        page.select_option('select[x-model="form.provider"]', "anthropic")
        page.wait_for_selector(".api-key-entry input[type='password']", state="visible", timeout=3000)
        page.fill(".api-key-entry input[type='password']", "bad-key")
        page.click(".api-key-entry button")
        page.wait_for_selector(".api-key-entry .key-error", state="visible", timeout=3000)
        assert "rejected" in page.inner_text(".api-key-entry .key-error").lower()
