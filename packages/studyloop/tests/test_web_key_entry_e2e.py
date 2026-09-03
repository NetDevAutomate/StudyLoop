"""E2E for the Generate-panel inline API-key entry (feature gap #2).

Drives a real browser against a real ``studyloop web`` server. The provider
list and the secrets POST are route-intercepted so the test is deterministic
and never hits a real LLM provider — but the UI logic (show/hide the key form,
POST the right body, reflect success) is exercised for real.

Port 18582 (sisters use 18580 content-gen, 18581 struggling-topics).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

_tests_dir = str(Path(__file__).parent)
if _tests_dir not in sys.path:
    sys.path.insert(0, _tests_dir)

from _playwright_helpers import start_web_server  # noqa: E402

if TYPE_CHECKING:
    import subprocess
    from collections.abc import Generator

    from playwright.sync_api import Browser, Page

pytestmark = [pytest.mark.e2e]

WEB_PORT = 18582
GENERATE_PANEL = "document.querySelector('[x-data=\"generatePanel()\"]')"
PROVIDERS_READY = f"() => window.Alpine.$data({GENERATE_PANEL}).providers.length > 0"
NEEDS_KEY = f"() => window.Alpine.$data({GENERATE_PANEL}).needsKey"


@pytest.fixture
def stub_config(tmp_path: Path) -> Path:
    cfg = tmp_path / "studyloop-keyentry.yaml"
    cfg.write_text(
        f"session_db: {tmp_path / 'sessions.db'}\ncard_generator:\n  backend: ollama\n",
        encoding="utf-8",
    )
    return cfg


@pytest.fixture
def server(stub_config: Path) -> Generator[subprocess.Popen, None, None]:
    """C13/R-49g: routed through the shared, hermetic ``start_web_server``
    instead of a hand-rolled ``env = os.environ.copy()`` + polling loop."""
    proc = start_web_server(WEB_PORT, extra_env={"STUDYLOOP_CONFIG": str(stub_config)})
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
        "models": [
            {
                "id": "claude-haiku-4-5",
                "label": "Haiku",
                "cost_tier": "cheap",
                "thinking": False,
                "notes": "",
            }
        ],
    },
    {
        "slug": "openai",
        "label": "OpenAI",
        "adapter": "openai_compat",
        "auth_env": "OPENAI_API_KEY",
        "available": True,  # already has a key — form must NOT show
        "models": [
            {
                "id": "gpt-x",
                "label": "GPT-X",
                "cost_tier": "balanced",
                "thinking": False,
                "notes": "",
            }
        ],
    },
    {
        # Bedrock uses AWS SigV4 creds, not a typed key. Unavailable → it must
        # show the AWS-creds hint (not the key box) and block Generate.
        "slug": "bedrock",
        "label": "AWS Bedrock",
        "adapter": "bedrock",
        "auth_env": "AWS_PROFILE",
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
        "() => window.Alpine.store('nav').current === 'generate'",
        timeout=3000,
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
        page.wait_for_function(PROVIDERS_READY, timeout=3000)
        # Select anthropic (no key) → the inline key form must appear.
        page.select_option('select[x-model="form.provider"]', "anthropic")
        page.wait_for_selector(
            ".api-key-entry input[type='password']", state="visible", timeout=3000
        )
        assert page.is_visible(".api-key-entry input[type='password']")

    def test_key_form_hidden_for_available_provider(self, page: Page) -> None:
        _route_providers(page, anthropic_available=False)
        _goto_generate(page)
        page.wait_for_function(PROVIDERS_READY, timeout=3000)
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
            route.fulfill(
                status=200, content_type="application/json", body=json.dumps({"ok": True})
            )

        page.route("**/api/content/secrets", handle_post)

        _goto_generate(page)
        page.wait_for_function(PROVIDERS_READY, timeout=3000)
        page.select_option('select[x-model="form.provider"]', "anthropic")
        page.wait_for_selector(
            ".api-key-entry input[type='password']", state="visible", timeout=3000
        )
        page.fill(".api-key-entry input[type='password']", "sk-test-12345")
        page.click(".api-key-entry button")

        # Success message appears.
        page.wait_for_selector(".api-key-entry .key-ok", state="visible", timeout=3000)
        assert page.is_visible(".api-key-entry .key-ok")
        # The POST carried the right provider + key.
        assert posted["body"] == {"provider": "anthropic", "key": "sk-test-12345"}

    def test_generate_button_disabled_while_key_missing(self, page: Page) -> None:
        """Generate must be disabled when the key-entry form is showing.

        Otherwise a user can click Generate with no key; the job reaches the
        backend, the generator raises CardGenerationError, and the failure
        arrives as an async WebSocket error frame instead of a clean
        disabled-button pre-flight signal. The form says 'you need a key' —
        the button must agree.
        """
        _route_providers(page, anthropic_available=False)
        _goto_generate(page)
        page.wait_for_function(PROVIDERS_READY, timeout=3000)
        # Satisfy every OTHER submit precondition so needsKey is the only thing
        # that could block submission (publisher+course set; kinds/scope default ok).
        page.evaluate(
            f"() => {{ const d = window.Alpine.$data({GENERATE_PANEL});"
            " d.form.publisher = 'p'; d.form.course = 'c'; }"
        )
        # Select the keyless provider → key form shows, needsKey === true.
        page.select_option('select[x-model="form.provider"]', "anthropic")
        page.wait_for_selector(
            ".api-key-entry input[type='password']", state="visible", timeout=3000
        )

        # Sanity: needsKey is genuinely true (otherwise the test proves nothing).
        needs_key = page.evaluate(NEEDS_KEY)
        assert needs_key is True, (
            "precondition: needsKey must be true for this test to be meaningful"
        )

        # The Generate button must be disabled while the key is missing.
        assert page.is_disabled('button[type="submit"]'), (
            "Generate button is enabled despite needsKey=true — canSubmit() lacks a needsKey guard"
        )

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
        page.wait_for_function(PROVIDERS_READY, timeout=3000)
        page.select_option('select[x-model="form.provider"]', "anthropic")
        page.wait_for_selector(
            ".api-key-entry input[type='password']", state="visible", timeout=3000
        )
        page.fill(".api-key-entry input[type='password']", "bad-key")
        page.click(".api-key-entry button")
        page.wait_for_selector(".api-key-entry .key-error", state="visible", timeout=3000)
        assert "rejected" in page.inner_text(".api-key-entry .key-error").lower()


class TestBedrockCredsHint:
    """Bedrock authenticates with AWS creds, not a typed key.

    When Bedrock is selected but unavailable it must NOT show the API-key
    box (you can't type a SigV4 credential), must show the AWS-creds hint
    instead, and must block Generate so the job never reaches the backend
    only to die with a CardGenerationError.
    """

    def test_bedrock_shows_aws_hint_not_key_box(self, page: Page) -> None:
        _route_providers(page, anthropic_available=False)
        _goto_generate(page)
        page.wait_for_function(
            "() => window.Alpine.$data("
            "document.querySelector('[x-data=\"generatePanel()\"]')"
            ").providers.length > 0",
            timeout=3000,
        )
        page.select_option('select[x-model="form.provider"]', "bedrock")

        # AWS-creds hint visible; API-key input NOT present.
        page.wait_for_selector(".bedrock-creds-hint", state="visible", timeout=3000)
        assert page.is_visible(".bedrock-creds-hint")
        assert not page.is_visible(".api-key-entry input[type='password']")

        # needsBedrockCreds true, needsKey false.
        state = page.evaluate(
            "() => { const d = window.Alpine.$data("
            "document.querySelector('[x-data=\"generatePanel()\"]'));"
            " return { bedrock: d.needsBedrockCreds, key: d.needsKey }; }"
        )
        assert state["bedrock"] is True
        assert state["key"] is False

        # The rendered <option>.label must say AWS credentials, NOT "API key".
        # x-show on a nested <span> is silently ignored inside <option> (the
        # browser flattens option text), so the suffix is built in
        # providerOptionLabel() and asserted here on the real .label property.
        label = page.eval_on_selector(
            "select[x-model='form.provider'] option[value='bedrock']",
            "el => el.label",
        )
        assert "needs AWS credentials" in label, label
        assert "API key" not in label, label

    def test_available_provider_option_has_no_suffix(self, page: Page) -> None:
        # Regression: the suffix must NOT appear on available providers. The
        # original nested-span x-show rendered it on every option regardless.
        _route_providers(page, anthropic_available=True)
        _goto_generate(page)
        page.wait_for_function(
            "() => window.Alpine.$data("
            "document.querySelector('[x-data=\"generatePanel()\"]')"
            ").providers.length > 0",
            timeout=3000,
        )
        label = page.eval_on_selector(
            "select[x-model='form.provider'] option[value='anthropic']",
            "el => el.label",
        )
        assert label == "Anthropic", f"available provider should have no suffix, got: {label!r}"

    def test_bedrock_unavailable_blocks_generate(self, page: Page) -> None:
        _route_providers(page, anthropic_available=False)
        _goto_generate(page)
        page.wait_for_function(
            "() => window.Alpine.$data("
            "document.querySelector('[x-data=\"generatePanel()\"]')"
            ").providers.length > 0",
            timeout=3000,
        )
        # Satisfy every OTHER submit precondition so the bedrock-creds guard is
        # the only thing that could block submission.
        page.evaluate(
            "() => { const d = window.Alpine.$data("
            "document.querySelector('[x-data=\"generatePanel()\"]'));"
            " d.form.publisher = 'p'; d.form.course = 'c'; }"
        )
        page.select_option('select[x-model="form.provider"]', "bedrock")
        page.wait_for_selector(".bedrock-creds-hint", state="visible", timeout=3000)

        assert page.is_disabled('button[type="submit"]'), (
            "Generate enabled despite needsBedrockCreds=true — canSubmit() lacks the guard"
        )
