"""Second Brain launcher UI — Today action and Settings provider cards.

Browser legs for the two frontend requirements of the provider-aware
launcher: Today renders AT MOST one honest action for the selected provider
and navigates only on an explicit click, and the Settings Second Brain
section explains provider state without ever disclosing the retained
destination URL or offering a web save control.

``window.open`` is replaced with a recorder before any page script runs, so
"the exact destination opens once in a new protected tab" is asserted
without a headless browser ever contacting xtiles.app.

Run:  cd packages/studyloop && uv run pytest tests/e2e/test_second_brain_ui.py -m e2e
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

_tests_dir = str(Path(__file__).resolve().parent.parent)
if _tests_dir not in sys.path:
    sys.path.insert(0, _tests_dir)

from e2e._env import (  # noqa: E402
    ConsoleWatch,
    E2EEnv,
    build_config,
    build_test_world,
    build_vault,
    diag,
    goto_view,
    shutdown,
    start_server,
)

if TYPE_CHECKING:
    from playwright.sync_api import Browser, Page

pytestmark = [pytest.mark.e2e]

PORT_ENABLED = 18641
PORT_NO_DESTINATION = 18642

DESTINATION = "https://xtiles.app/view/e2e-launcher-project"

#: Recorder installed before any page script: the launcher must call the real
#: window.open signature, and the test must see it without leaving the page.
OPEN_RECORDER = """
window.__opened = [];
window.open = (url, target, features) => {
  window.__opened.push({ url, target, features });
  return null;
};
"""


def _launch_with_second_brain(root: Path, port: int, section: str) -> E2EEnv:
    """A hermetic world whose config carries the given ``second_brain`` section."""
    vault = build_vault(root)
    config = build_config(root, vault)
    config.write_text(config.read_text(encoding="utf-8") + section, encoding="utf-8")
    world = build_test_world(root, port, vault_path=vault, config_path=config)
    server = start_server(world)
    return E2EEnv(
        base_url=server.base_url,
        port=port,
        vault=vault,
        config=config,
        proc=server.proc,
        session_dir=world.session_dir,
        env=dict(world.env),
        world=world,
        server=server,
    )


@pytest.fixture(scope="module")
def enabled_env(tmp_path_factory):
    """xTiles selected with a validated exact destination — an enabled target."""
    root = tmp_path_factory.mktemp("brain-ui-enabled")
    section = f"second_brain:\n  provider: xtiles\n  xtiles_destination_url: {DESTINATION}\n"
    e = _launch_with_second_brain(root, PORT_ENABLED, section)
    try:
        yield e
    finally:
        shutdown(e)


@pytest.fixture(scope="module")
def no_destination_env(tmp_path_factory):
    """xTiles selected with no retained destination — a disabled target."""
    root = tmp_path_factory.mktemp("brain-ui-no-destination")
    e = _launch_with_second_brain(root, PORT_NO_DESTINATION, "second_brain:\n  provider: xtiles\n")
    try:
        yield e
    finally:
        shutdown(e)


def _open_today(browser: Browser, env: E2EEnv) -> tuple[Page, ConsoleWatch]:
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    ctx.add_init_script(OPEN_RECORDER)
    page = ctx.new_page()
    watch = ConsoleWatch(page)
    page.goto(f"{env.base_url}/")
    goto_view(page, "today")
    return page, watch


# ---------------------------------------------------------------------------
# Today — one honest action, one explicit gesture, one navigation
# ---------------------------------------------------------------------------


def test_today_enabled_xtiles_action_opens_once_in_a_protected_tab(
    browser: Browser, enabled_env: E2EEnv
) -> None:
    """Scenarios: "Today has an enabled configured provider", "Page loads with
    an enabled target" and "Learner clicks enabled xTiles action"."""
    page, watch = _open_today(browser, enabled_env)
    try:
        action = page.locator(".today-brain-btn")
        action.wait_for(state="visible", timeout=15000)
        assert action.count() == 1, "Today must render exactly one Second Brain action"
        assert action.is_enabled(), "the configured xTiles action must be enabled"
        assert "xTiles" in action.inner_text()

        assert page.evaluate("() => window.__opened") == [], "loading Today must not open anything"

        action.click()

        opened = page.evaluate("() => window.__opened")
        assert opened == [
            {"url": DESTINATION, "target": "_blank", "features": "noopener,noreferrer"}
        ], f"one click must open the exact destination once, protected; got {opened}"
        assert page.url.startswith(enabled_env.base_url), (
            "the current context must not navigate for an xTiles launch"
        )
        watch.assert_clean("launching xTiles from Today")
    except Exception:
        diag(page, "today-brain-enabled", watch)
        raise
    finally:
        page.context.close()


def test_today_disabled_action_shows_the_reason_and_never_navigates(
    browser: Browser, no_destination_env: E2EEnv
) -> None:
    """Scenario: "Today has a disabled configured provider" — the action and
    its explanation are visible, and activating it performs no navigation."""
    page, watch = _open_today(browser, no_destination_env)
    try:
        action = page.locator(".today-brain-btn")
        action.wait_for(state="attached", timeout=15000)
        assert action.count() == 1, "Today must render exactly one Second Brain action"
        assert action.is_disabled(), "a target without a destination must be disabled"

        reason = page.locator(".today-brain-reason")
        reason.wait_for(state="visible", timeout=15000)
        assert "studyloop brain destination set" in reason.inner_text()

        page.evaluate("() => document.querySelector('.today-brain-btn').click()")

        assert page.evaluate("() => window.__opened") == []
        assert page.url.startswith(no_destination_env.base_url)
        watch.assert_clean("activating a disabled Second Brain action")
    except Exception:
        diag(page, "today-brain-disabled", watch)
        raise
    finally:
        page.context.close()


# ---------------------------------------------------------------------------
# Settings — honest provider cards, never the URL, never a save control
# ---------------------------------------------------------------------------


def _open_settings(browser: Browser, env: E2EEnv) -> tuple[Page, ConsoleWatch]:
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    page = ctx.new_page()
    watch = ConsoleWatch(page)
    page.goto(f"{env.base_url}/")
    goto_view(page, "settings")
    return page, watch


def test_settings_highlights_the_selected_provider_and_mutes_the_other(
    browser: Browser, enabled_env: E2EEnv
) -> None:
    """Scenario: "Settings shows selected and inactive providers" — xTiles is
    selected, so its card is active, Obsidian is muted with guidance, and the
    section never shows the retained URL or a save control."""
    page, watch = _open_settings(browser, enabled_env)
    try:
        section = page.locator(".second-brain-settings")
        section.wait_for(state="visible", timeout=15000)

        cards = section.locator(".brain-card")
        assert cards.count() == 2, "one card per provider, Obsidian and xTiles"
        active = section.locator(".brain-card.brain-active")
        muted = section.locator(".brain-card.brain-muted")
        assert active.count() == 1 and "xTiles" in active.inner_text()
        assert muted.count() == 1 and "Obsidian" in muted.inner_text()
        assert "studyloop brain enable obsidian" in muted.inner_text()

        text = section.inner_text()
        assert DESTINATION not in text, "the retained URL must never be displayed"
        assert section.locator("input, textarea").count() == 0, (
            "the Second Brain section must offer no web entry control"
        )
        assert section.locator("button").count() == 0, (
            "the Second Brain section must offer no web save control"
        )
        watch.assert_clean("rendering the Settings Second Brain section")
    except Exception:
        diag(page, "settings-brain-matrix", watch)
        raise
    finally:
        page.context.close()


def test_settings_shows_the_destination_command_pattern_when_it_is_missing(
    browser: Browser, no_destination_env: E2EEnv
) -> None:
    """The state-matrix leg the markup already wires: an active-but-disabled
    xTiles card surfaces the API's configuration guidance — the destination
    command pattern — while the section still offers no URL and no control."""
    page, watch = _open_settings(browser, no_destination_env)
    try:
        section = page.locator(".second-brain-settings")
        section.wait_for(state="visible", timeout=15000)

        active = section.locator(".brain-card.brain-active")
        assert active.count() == 1 and "xTiles" in active.inner_text()
        guidance = active.locator(".brain-guidance")
        guidance.wait_for(state="visible", timeout=15000)
        assert "studyloop brain destination set --provider xtiles --url URL" in (
            guidance.inner_text()
        )

        assert "https://" not in section.inner_text()
        assert section.locator("input, textarea, button").count() == 0
        watch.assert_clean("rendering Settings guidance for a missing destination")
    except Exception:
        diag(page, "settings-brain-guidance", watch)
        raise
    finally:
        page.context.close()
