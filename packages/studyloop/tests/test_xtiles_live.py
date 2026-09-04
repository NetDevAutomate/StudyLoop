"""Opt-in Playwright checks against the owner's real xTiles account.

What these test, and why they are shaped this way
------------------------------------------------

StudyLoop has no xTiles code path, so there is nothing of StudyLoop's to drive a
browser at. The learner-visible workflow is:

    StudyLoop's recommendation  ->  the assistant  ->  xTiles  ->  the learner looks

Only the last arrow is a browser. So these tests take the half that a browser can
honestly check: **an assistant wrote something through the MCP connector, and the
learner can see it in xTiles' own interface, exactly as sent.** That closes the
loop the API-level round trip could not — a write can succeed at the API and still
be invisible or wrong in the UI, which is where the learner actually lives.

The write itself is not automated, deliberately. Automating it would mean either
driving xTiles' UI to create the item (which tests xTiles, not StudyLoop) or
embedding an MCP client (which is the explicit stage-2 non-goal). The assistant
does the write; these tests do the seeing.

Two phases, run as two commands
-------------------------------

Phase 1 — after the assistant has written the item::

    STUDYLOOP_LIVE_XTILES=1 \\
    STUDYLOOP_LIVE_XTILES_URL="<the URL the assistant returned>" \\
    STUDYLOOP_LIVE_XTILES_PROBE="StudyLoop round-trip probe" \\
    env -u VIRTUAL_ENV uv run --group dev pytest -m live_xtiles -v

Phase 2 — after it has been deleted, same command plus::

    STUDYLOOP_LIVE_XTILES_EXPECT_REMOVED=1

Two commands rather than one test that deletes, because the honest assertion
differs between the two states and a test that guessed at a third party's delete
affordance would fail for reasons that have nothing to do with StudyLoop. Each
phase asserts only what it can know.

Safety
------

Three gates, and a probe prefix that scopes everything this file looks at:

* ``STUDYLOOP_LIVE_XTILES=1`` — opted in for this run. Otherwise skipped.
* a saved session from ``scripts/xtiles-live-auth.py``. Otherwise skipped, with
  the command to create it.
* ``STUDYLOOP_LIVE_XTILES_PROBE`` — the title prefix the assistant was told to
  use. **Failed, not skipped, when it is missing or too short**: a run that
  asserted against whatever happened to be on the page would either pass by
  accident or read the owner's real content into a log.

Nothing here writes to xTiles, and nothing asserts against text that does not
carry the probe prefix. The account's real content is never read into an
assertion message or an artefact.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.live_xtiles

#: Where `scripts/xtiles-live-auth.py` saves the signed-in session.
DEFAULT_STATE = Path.home() / ".cache" / "studyloop-live" / "xtiles-auth.json"

#: An env file that may hold ``XTILES_USERNAME`` and ``XTILES_PASSWORD``.
#:
#: Read directly and narrowly rather than sourced into the environment: files like
#: this tend to accumulate unrelated secrets (a GitHub token, cloud credentials),
#: and none of those have any business being visible to a process that drives a
#: browser. Exactly two keys are lifted out; everything else is ignored.
DEFAULT_CREDENTIALS_FILE = Path.home() / "tmp" / ".env"

#: Only these. See :func:`_credentials`.
CREDENTIAL_KEYS = ("XTILES_USERNAME", "XTILES_PASSWORD")

#: The xTiles host under test. A dev instance is a different host from the one an
#: assistant's MCP connector is signed in to, so this is explicit rather than
#: assumed -- a test that signed production credentials into a dev box, or the
#: reverse, would be a confusing failure at best.
DEFAULT_HOST = "https://xtiles.app"

#: Where the sign-in form actually lives. ``/login`` is an app route that
#: renders a dashboard shell and no form at all -- aiming at it cost one
#: timeout before anyone looked.
DEFAULT_LOGIN_PATH = "/user/login"

#: A prefix shorter than this is not a scope, it is a substring that could match
#: anything in the owner's workspace.
MIN_PROBE_LENGTH = 12

#: Artefacts land in the gitignored review tree, beside the API-level round trip
#: this complements.
_EVIDENCE = (
    Path(__file__).resolve().parents[3]
    / "reviews"
    / "2026-09-03-second-brain"
    / "evidence"
    / "m8"
    / "xtiles-live"
)

AUTH_HINT = (
    "no xTiles session and no credentials. Either:\n"
    "  * put XTILES_USERNAME and XTILES_PASSWORD in ~/tmp/.env (or point\n"
    "    STUDYLOOP_LIVE_XTILES_ENV_FILE at another file), or\n"
    "  * capture a session once: env -u VIRTUAL_ENV uv run python "
    "scripts/xtiles-live-auth.py"
)


def _credentials() -> tuple[str, str] | None:
    """Lift exactly ``XTILES_USERNAME`` and ``XTILES_PASSWORD`` out of an env file.

    Deliberately NOT ``dotenv`` and deliberately not exported into ``os.environ``.
    A shared ``.env`` is usually a drawer, not a keyring: the one this defaults to
    also holds a GitHub token and a cloud bearer token, and a browser-driving test
    process has no reason to be able to see either. Two keys, by name, returned as
    values -- so nothing else can leak into a child process or a traceback.

    The real environment wins when set, so a run can override without editing a
    file, and CI (which has neither) simply gets ``None``.
    """
    found: dict[str, str] = {}
    for key in CREDENTIAL_KEYS:
        value = os.environ.get(key, "").strip()
        if value:
            found[key] = value

    if len(found) < len(CREDENTIAL_KEYS):
        path = Path(
            os.environ.get("STUDYLOOP_LIVE_XTILES_ENV_FILE", str(DEFAULT_CREDENTIALS_FILE))
        ).expanduser()
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError:
            raw = ""
        for line in raw.splitlines():
            line = line.strip().removeprefix("export ").strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            if key in CREDENTIAL_KEYS and key not in found:
                found[key] = value.strip().strip("\"'")

    if len(found) < len(CREDENTIAL_KEYS):
        return None
    return found["XTILES_USERNAME"], found["XTILES_PASSWORD"]


def _sign_in(page, host: str, username: str, password: str) -> None:
    """Sign in through the real form.

    The path and locators here were found by looking at the page, not guessed. The
    first version aimed at ``/login`` with a role-based email lookup and timed out:
    ``/login`` is an app route that renders a dashboard shell, the sign-in form
    lives at ``/user/login``, and its email field is ``type="text"`` carrying a
    placeholder rather than a label. Placeholders are what this page actually
    offers, so placeholders are what this uses.

    Kept deliberately shallow -- no CSS descent into someone else's markup. When it
    breaks it says so and points at the captured-session route, because a login
    redesign should cost one command rather than a debugging session.
    """
    login_path = os.environ.get("STUDYLOOP_LIVE_XTILES_LOGIN_PATH", DEFAULT_LOGIN_PATH)
    login_url = f"{host.rstrip('/')}/{login_path.lstrip('/')}"
    page.goto(login_url, wait_until="domcontentloaded")
    page.wait_for_timeout(2500)

    try:
        email_box = page.get_by_placeholder(re.compile("e-?mail", re.I)).first
        email_box.wait_for(state="visible", timeout=20000)
        email_box.fill(username)

        password_box = page.locator("input[type='password']").first
        password_box.wait_for(state="visible", timeout=10000)
        password_box.fill(password)

        page.locator("button[type='submit']").first.click()
    except Exception as exc:
        pytest.fail(
            f"could not drive the xTiles sign-in form at {login_url}. "
            "If the form has moved, set STUDYLOOP_LIVE_XTILES_LOGIN_PATH; or capture "
            "a session once instead: "
            "env -u VIRTUAL_ENV uv run python scripts/xtiles-live-auth.py "
            f"({type(exc).__name__})"
        )

    # Wait for the app rather than for a fixed selector: "signed in" is a URL that
    # is no longer the login page.
    for _ in range(30):
        page.wait_for_timeout(1000)
        if not _looks_signed_out(page):
            return

    # Name the most likely cause instead of listing possibilities. Measured on
    # xtiles.app: the form submits, no error is shown, and the page simply stays
    # put -- because it is protected by reCAPTCHA, which a headless browser does
    # not satisfy. That is not a bug to fix here. Defeating a CAPTCHA would be
    # fragile and would be working against a protection the service chose, so the
    # captured-session route exists precisely for this and is the supported path.
    protected = "recaptcha" in page.content().lower()
    pytest.fail(
        f"still on {page.url} after submitting the sign-in form."
        + (
            "\n\nThe page is protected by reCAPTCHA, which a headless browser will "
            "not pass. Credential sign-in only works on a host without it (a dev "
            "instance, typically). For this host, capture a session once in a real "
            "window instead:\n"
            "  env -u VIRTUAL_ENV uv run python scripts/xtiles-live-auth.py"
            if protected
            else "\n\nEither the credentials were rejected, or this host wants a step "
            "the form does not show. Nothing was written."
        )
    )


@pytest.fixture(scope="module")
def evidence_dir() -> Path:
    _EVIDENCE.mkdir(parents=True, exist_ok=True)
    return _EVIDENCE


@pytest.fixture()
def probe() -> str:
    """The title prefix everything in this file is scoped to."""
    if os.environ.get("STUDYLOOP_LIVE_XTILES") != "1":
        pytest.skip("set STUDYLOOP_LIVE_XTILES=1 to run the live xTiles checks")

    value = os.environ.get("STUDYLOOP_LIVE_XTILES_PROBE", "").strip()
    if len(value) < MIN_PROBE_LENGTH:
        pytest.fail(
            "STUDYLOOP_LIVE_XTILES_PROBE must be the distinctive title prefix the "
            f"assistant was told to use, at least {MIN_PROBE_LENGTH} characters "
            f"(got {value!r}). Refusing to run: a short or empty prefix would "
            "match the account's real content."
        )
    return value


@pytest.fixture()
def target_url(probe: str) -> str:
    del probe  # the probe gate must be evaluated before this one can skip
    url = os.environ.get("STUDYLOOP_LIVE_XTILES_URL", "").strip()
    if not url:
        pytest.skip(
            "set STUDYLOOP_LIVE_XTILES_URL to the URL your assistant returned "
            "after writing to xTiles"
        )
    if not url.startswith("https://"):
        pytest.fail(f"STUDYLOOP_LIVE_XTILES_URL must be an https URL; got {url!r}")
    return url


@pytest.fixture()
def signed_in_page(probe: str, target_url: str):
    """A browser signed in to xTiles, on the URL under test.

    Two ways in, tried in this order: a saved session (cheapest, and survives a
    login-form redesign), then username and password. Neither is required to exist
    — with neither, the run skips and says how to supply one.

    Depends on ``probe`` FIRST, and that order is load-bearing rather than
    stylistic. Pytest resolves fixtures in signature order, so when this fixture
    was declared without it, a missing session skipped the run before the
    too-short-prefix check was ever reached — turning the one gate that must fail
    into a skip. Found by running it, not by reading it.
    """
    del probe  # consumed for its gate, not its value

    host = os.environ.get("STUDYLOOP_LIVE_XTILES_HOST", DEFAULT_HOST).strip()
    if not host.startswith("https://"):
        pytest.fail(f"STUDYLOOP_LIVE_XTILES_HOST must be an https URL; got {host!r}")

    state = Path(os.environ.get("STUDYLOOP_LIVE_XTILES_AUTH", str(DEFAULT_STATE))).expanduser()
    try:
        saved_session = state.read_text(encoding="utf-8").strip()
    except OSError:
        saved_session = ""

    credentials = _credentials()
    if not saved_session and credentials is None:
        pytest.skip(AUTH_HINT)

    playwright = pytest.importorskip(
        "playwright.sync_api", reason="playwright is not installed in this environment"
    )

    with playwright.sync_playwright() as play:
        browser = play.chromium.launch()
        context = browser.new_context(
            storage_state=str(state) if saved_session else None,
            viewport={"width": 1440, "height": 900},
        )
        page = context.new_page()
        try:
            if not saved_session:
                assert credentials is not None
                _sign_in(page, host, *credentials)

            page.goto(target_url, wait_until="domcontentloaded")
            # xTiles renders its content after the shell, so "the document loaded"
            # is not "the content is there". Settle, then hand over.
            page.wait_for_timeout(4000)

            if _looks_signed_out(page) and saved_session and credentials is not None:
                # A stale saved session is the common case after a while. Fall
                # back rather than failing: the operator asked for a live check,
                # not for a lecture about cookie lifetimes.
                _sign_in(page, host, *credentials)
                page.goto(target_url, wait_until="domcontentloaded")
                page.wait_for_timeout(4000)

            yield page
        finally:
            browser.close()


def _looks_signed_out(page) -> bool:
    return any(hint in page.url for hint in ("/user/login", "/signin", "/auth"))


def test_the_assistants_write_is_visible_to_the_learner(
    signed_in_page, probe: str, evidence_dir: Path
) -> None:
    """The half the API-level round trip could not prove.

    A connector write can return an id and still be invisible in the interface —
    wrong space, wrong day, rendered empty. This is the learner's own view of it.
    """
    page = signed_in_page

    if os.environ.get("STUDYLOOP_LIVE_XTILES_EXPECT_REMOVED") == "1":
        pytest.skip("this run is checking removal; see the removal test")

    if _looks_signed_out(page):
        pytest.fail(
            f"redirected to {page.url} — the saved session has expired. "
            "Recreate it: env -u VIRTUAL_ENV uv run python scripts/xtiles-live-auth.py"
        )

    match = page.locator(f"text={probe} >> visible=true").first
    try:
        match.wait_for(state="visible", timeout=20000)
    except Exception as exc:
        shot = evidence_dir / "not-found.png"
        page.screenshot(path=str(shot), full_page=True)
        pytest.fail(
            f"nothing carrying the probe prefix {probe!r} is visible at {page.url}.\n"
            f"A screenshot of what was there instead: {shot}\n"
            "Either the assistant did not write it, wrote it somewhere else, or "
            f"xTiles renders it in a way this check cannot see. ({exc})"
        )

    # Assert against the probe-scoped element only. Reading the page's whole text
    # into an assertion would put the owner's real workspace into a test log.
    assert probe in match.inner_text()

    shot = evidence_dir / "visible-in-xtiles.png"
    page.screenshot(path=str(shot))
    (evidence_dir / "visible-in-xtiles.txt").write_text(
        "Live xTiles UI check — the assistant's write, seen by the learner\n"
        "================================================================\n\n"
        f"URL under test : {page.url}\n"
        f"Probe prefix   : {probe}\n"
        f"Matched text   : {match.inner_text().strip()[:200]}\n\n"
        "Nothing was written or deleted by this check. Only the element carrying\n"
        "the probe prefix was read; the rest of the workspace was not.\n",
        encoding="utf-8",
    )


def test_the_item_is_gone_once_it_has_been_deleted(
    signed_in_page, probe: str, evidence_dir: Path
) -> None:
    """The remove half, asserted where the learner would look for it.

    Runs only in the second phase. The API round trip already proves the id
    returns 404; this proves the interface agrees, which is not the same claim —
    a deleted item that still renders is exactly the kind of thing an API check
    cannot see.
    """
    if os.environ.get("STUDYLOOP_LIVE_XTILES_EXPECT_REMOVED") != "1":
        pytest.skip(
            "set STUDYLOOP_LIVE_XTILES_EXPECT_REMOVED=1 and rerun after the item has been deleted"
        )

    page = signed_in_page
    if _looks_signed_out(page):
        pytest.fail(f"redirected to {page.url} — the saved session has expired.")

    count = page.locator(f"text={probe} >> visible=true").count()
    if count:
        shot = evidence_dir / "still-present.png"
        page.screenshot(path=str(shot), full_page=True)
        pytest.fail(
            f"{count} element(s) carrying {probe!r} are still visible at {page.url} "
            f"after deletion. Screenshot: {shot}"
        )

    (evidence_dir / "removed-from-xtiles.txt").write_text(
        "Live xTiles UI check — removal, seen by the learner\n"
        "==================================================\n\n"
        f"URL under test : {page.url}\n"
        f"Probe prefix   : {probe}\n"
        "Result         : no visible element carries the probe prefix.\n\n"
        "The API round trip proves the id returns 404; this proves the interface\n"
        "agrees, which is a different claim.\n",
        encoding="utf-8",
    )
