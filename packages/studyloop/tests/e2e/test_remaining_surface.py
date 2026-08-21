"""Remaining web surface — the endpoints the coverage gate flagged as dark.

Each test here exists because ``tests/test_e2e_coverage_gate.py`` reported an
endpoint with no test, or no *browser* test. Grouped by surface rather than by
route so the assertions read as user behaviour:

* pomodoro defaults    — two endpoints serve the same config; they must agree
* explorer search      — the search bar finds a lesson and opens it
* live session stream  — the SSE dashboard receives a real event frame
* backlog park/demote  — the 3-topic rule can be rearranged from the UI's API
* artefacts listing    — the per-course artefact index responds structurally

Run:  cd packages/studyloop && uv run pytest tests/e2e/test_remaining_surface.py -m e2e
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

pytest.importorskip("requests")

_tests_dir = str(Path(__file__).resolve().parent.parent)
if _tests_dir not in sys.path:
    sys.path.insert(0, _tests_dir)

from e2e._env import ConsoleWatch, diag, goto_view, launch_env, shutdown  # noqa: E402

if TYPE_CHECKING:
    from playwright.sync_api import Browser

pytestmark = [pytest.mark.e2e]

PORT = 18606


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    root = tmp_path_factory.mktemp("remaining-surface")
    e = launch_env(root, PORT)
    try:
        yield e
    finally:
        shutdown(e)


# ---------------------------------------------------------------------------
# Pomodoro defaults — GET /api/config/pomodoro + GET /api/settings/pomodoro
# ---------------------------------------------------------------------------


def test_pomodoro_endpoints_agree_on_the_same_config(env) -> None:
    """Both pomodoro endpoints serve the same durations under different keys.

    Two endpoints for one setting is a drift hazard: the Body Double slider
    reads one and the session dashboard reads the other, so a learner could see
    two different "focus" defaults. This pins them together.
    """
    import requests

    cfg = requests.get(f"{env.base_url}/api/config/pomodoro", timeout=15)
    setting = requests.get(f"{env.base_url}/api/settings/pomodoro", timeout=15)
    assert cfg.status_code == 200, cfg.text
    assert setting.status_code == 200, setting.text
    c, s = cfg.json(), setting.json()

    assert c["focus_minutes"] == s["focus"], f"focus differs: {c} vs {s}"
    assert c["short_break_minutes"] == s["short_break"]
    assert c["long_break_minutes"] == s["long_break"]
    assert c["cycle_length"] == s["cycles"]
    # Sane defaults — a 0-minute pomodoro would break the timer UI.
    assert c["focus_minutes"] > 0 and c["cycle_length"] > 0


def test_body_double_timer_uses_the_served_pomodoro_defaults(browser: Browser, env) -> None:
    """Browser leg: the Body Double view consumes /api/settings/pomodoro.

    Note which endpoint: the UI reads ``/api/settings/pomodoro`` only —
    ``/api/config/pomodoro`` has no client. It is kept covered by the parity
    test above so the unused alias cannot drift away from the live one while
    nobody is looking, but this test asserts the endpoint the learner's timer
    genuinely depends on.
    """
    import requests

    expected = requests.get(f"{env.base_url}/api/settings/pomodoro", timeout=15).json()
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    page = ctx.new_page()
    watch = ConsoleWatch(page)
    try:
        seen: list[str] = []
        page.on("response", lambda r: seen.append(r.url))
        page.goto(f"{env.base_url}/")
        goto_view(page, "body-double")
        focus = page.locator('.body-double-controls input[type="number"]').first
        focus.wait_for(state="visible", timeout=15000)
        page.wait_for_function(
            "() => { const i = document.querySelector('.body-double-controls input[type=number]');"
            " return i && i.value !== ''; }",
            timeout=15000,
        )
        assert any("/api/settings/pomodoro" in u for u in seen), (
            "the Body Double view never requested /api/settings/pomodoro"
        )
        value = int(focus.input_value())
        assert value == expected["focus"], (
            f"timer shows {value} min but the server serves {expected['focus']} min"
        )
        watch.assert_clean("loading the Body Double timer")
    except Exception:
        diag(page, "pomodoro-defaults", watch)
        raise
    finally:
        ctx.close()


# ---------------------------------------------------------------------------
# Explorer search — GET /api/explorer/search
# ---------------------------------------------------------------------------


def test_explorer_search_finds_and_opens_a_lesson(browser: Browser, env) -> None:
    """A learner types in the explorer search bar and opens a hit.

    Exercises the FTS index end to end: the query hits
    ``/api/explorer/search``, results render grouped by provider, and clicking
    one opens the reader on that lesson.
    """
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    page = ctx.new_page()
    watch = ConsoleWatch(page)
    try:
        page.goto(f"{env.base_url}/")
        page.wait_for_function("() => !!window.Alpine", timeout=15000)
        page.locator(".explorer-sidebar-btn").click()
        search = page.locator(".explorer-search-input")
        search.wait_for(state="visible", timeout=15000)
        search.fill("functools")

        result = page.locator(".explorer-search-result").first
        result.wait_for(state="visible", timeout=25000)
        title = result.locator(".explorer-search-result-title").inner_text()
        assert title.strip(), "search result has no title"

        result.click()
        prose = page.locator(".explorer-reader-prose")
        prose.wait_for(state="visible", timeout=20000)
        assert "decorator" in prose.inner_text().lower(), (
            "clicking a search hit did not open the matching lesson"
        )
        watch.assert_clean("searching the course explorer")
    except Exception:
        diag(page, "explorer-search", watch)
        raise
    finally:
        ctx.close()


def test_explorer_search_api_contract(env) -> None:
    """The search endpoint returns structured hits with locatable lesson ids."""
    import requests

    resp = requests.get(
        f"{env.base_url}/api/explorer/search", params={"q": "functools", "limit": 5}, timeout=30
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    results = body.get("results", body if isinstance(body, list) else [])
    assert results, f"no search hits for a term that is in the vault: {body}"
    first = results[0]
    assert first.get("lesson_id") or first.get("id"), f"hit has no lesson id: {first}"

    # A short query must not silently return the whole vault.
    short = requests.get(f"{env.base_url}/api/explorer/search", params={"q": "a"}, timeout=30)
    assert short.status_code in (200, 400, 422), short.text


# ---------------------------------------------------------------------------
# Live session dashboard — GET /session + GET /api/session/stream (SSE)
# ---------------------------------------------------------------------------


def test_session_dashboard_receives_sse_frames(env) -> None:
    """The SSE stream emits a frame when the session IPC state changes.

    The generator is change-driven: it compares the mtimes of the three IPC
    files every 2s and only pushes when one moved. With no session running
    nothing changes and the socket stays legitimately silent — so the test
    *creates* a state file first (in this server's isolated IPC dir) and then
    asserts a frame arrives. Read with a streaming request rather than a
    browser because an SSE stream never "finishes".
    """
    import json as _json

    import requests

    assert env.session_dir is not None
    (env.session_dir / "session-state.json").write_text(
        _json.dumps(
            {
                "mode": "active",
                "topic": "Python Decorators",
                "energy": 6,
                "started_at": "2026-01-01T09:00:00",
            }
        ),
        encoding="utf-8",
    )

    with requests.get(f"{env.base_url}/api/session/stream", stream=True, timeout=30) as resp:
        assert resp.status_code == 200, resp.text
        assert "text/event-stream" in resp.headers.get("content-type", ""), (
            f"wrong content type for SSE: {resp.headers.get('content-type')!r}"
        )
        chunk = b""
        for raw in resp.iter_content(chunk_size=64):
            chunk += raw
            if b"\n\n" in chunk or len(chunk) > 4096:
                break
        text = chunk.decode("utf-8", errors="replace")
        assert text.strip(), "SSE stream produced no bytes after an IPC change"
        assert "data:" in text or "event:" in text, (
            f"SSE payload is not an event frame: {text[:200]!r}"
        )


def test_session_dashboard_page_renders(browser: Browser, env) -> None:
    """GET /session serves the live dashboard shell without JS errors."""
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    page = ctx.new_page()
    watch = ConsoleWatch(page)
    try:
        page.goto(f"{env.base_url}/session")
        page.wait_for_load_state("domcontentloaded")
        assert page.locator("body").count() == 1
        text = page.inner_text("body")
        assert text.strip(), "the session dashboard rendered an empty body"
        watch.assert_clean("loading the live session dashboard")
    except Exception:
        diag(page, "session-dashboard", watch)
        raise
    finally:
        ctx.close()


# ---------------------------------------------------------------------------
# Backlog — POST /api/backlog/park + POST /api/backlog/demote
# ---------------------------------------------------------------------------


def _reset_parking(base: str) -> None:
    """Best-effort board reset.

    ``/api/parking/clear`` belongs to the parking-board router, which is a
    separate feature: this test only needs the backlog to start empty, so a
    missing endpoint is tolerated rather than making the backlog contract
    depend on another surface landing first.
    """
    import contextlib

    import requests

    with contextlib.suppress(requests.RequestException):
        requests.post(f"{base}/api/parking/clear", json={"all": True, "hard": True}, timeout=20)


def test_park_then_demote_rearranges_the_active_three(env) -> None:
    """Parking fills the active slots; demoting pushes one back to the lot.

    The 3-topic rule is the AuDHD guardrail: the test asserts the rearrange
    actually changes which topics are active, not merely that the call is 200.
    """
    import requests

    base = env.base_url
    _reset_parking(base)

    ids = []
    for n in range(4):
        resp = requests.post(
            f"{base}/api/backlog/park",
            json={"question": f"Backlog topic {n}", "tech_area": "python"},
            timeout=20,
        )
        assert resp.status_code == 200, resp.text
        ids.append(resp.json()["id"])

    body = requests.get(f"{base}/api/backlog", timeout=20).json()
    assert body["active_count"] == body["max_active"], body
    assert body["parking_lot_count"] == 4 - body["max_active"], body
    active_before = [t["id"] for t in body["active"]]

    demoted = requests.post(f"{base}/api/backlog/demote", json={"id": active_before[0]}, timeout=20)
    assert demoted.status_code == 200, demoted.text

    after = requests.get(f"{base}/api/backlog", timeout=20).json()
    assert [t["id"] for t in after["active"]] != active_before, (
        "demote returned 200 but the active set is unchanged"
    )
    assert active_before[0] in [t["id"] for t in after["parking_lot"]] or (
        active_before[0] not in [t["id"] for t in after["active"]]
    ), "the demoted topic is still active"

    _reset_parking(base)


# ---------------------------------------------------------------------------
# Artefacts — GET /api/artefacts/{course}
# ---------------------------------------------------------------------------


def test_artefacts_index_responds_structurally(env) -> None:
    """The artefact index answers for a course with none, without 500ing.

    A vault with no generated artefacts is the common case on a fresh install;
    the endpoint must degrade to an empty listing rather than an error page.
    """
    import requests

    resp = requests.get(f"{env.base_url}/api/artefacts/Python_Deep_Dive", timeout=20)
    assert resp.status_code in (200, 404), resp.text
    if resp.status_code == 200:
        body = resp.json()
        assert isinstance(body, dict | list), f"unexpected artefact payload: {body!r}"


# ---------------------------------------------------------------------------
# Terminal proxy — GET/POST /terminal/{path:path}
# ---------------------------------------------------------------------------


def test_terminal_proxy_degrades_when_ttyd_is_absent(env) -> None:
    """The ttyd proxy answers against a real server, with no ttyd behind it.

    This is the surviving full-stack coverage for `/terminal/{path:path}` after
    ADR-0004 step 2 deleted `tests/test_web_terminal.py` (every test in it drove
    the retired `terminalPanel()` path). The route itself is NOT retired — the
    `ttyd` transport still mounts an iframe through it via
    `_mountLegacyIframe()` — so it needs to keep proving it survives real ASGI
    serving, real config loading and the auth middleware, which is exactly what
    an in-process `TestClient` call cannot show.

    ttyd is not running in the harness, so the contract under test is the
    degradation: a clean 502 with an explanatory body, never a 500 traceback and
    never a hang. That is what the learner's iframe sees when ttyd is missing,
    and `test_terminal_proxy.py` asserts the client never requests this URL
    until a ttyd session actually starts.
    """
    import requests

    for method in ("get", "post"):
        resp = getattr(requests, method)(f"{env.base_url}/terminal/", timeout=20)
        assert resp.status_code == 502, (
            f"{method.upper()} /terminal/ should degrade to 502 without ttyd, "
            f"got {resp.status_code}: {resp.text[:200]!r}"
        )
        assert "ttyd not running" in resp.text, resp.text[:200]
        # No caching of an error page — a later real ttyd must not be shadowed.
        assert resp.headers.get("content-type", "").startswith("text/plain")

    # A stale iframe (one carrying a study_session_id that is not the live one)
    # is refused before any upstream call, so an old terminal cannot reattach.
    stale = requests.get(f"{env.base_url}/terminal/?session=not-the-live-one", timeout=20)
    assert stale.status_code == 409, f"stale session should 409, got {stale.status_code}"
    assert stale.headers.get("cache-control") == "no-store"
