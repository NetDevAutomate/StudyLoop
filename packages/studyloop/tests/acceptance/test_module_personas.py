"""Persona A and Persona B scripted acceptance journeys (module-contract v1, design.md §6; lane U1).

Two representative users drive the REAL product -- a subprocess ``studyloop web`` with the
deterministic harness agent, the real CLI in subprocesses, a real headless browser -- at the
acceptance tier (``STUDYLOOP_ACC=1``; ``just testacc TESTS=<this file>``). Each persona is one
class: ordered phases sharing one world (lane W's pattern in ``e2e/test_module_labs_journey.py``,
re-expressed here with the §6 additions), a ``WallClockBudget`` the last phase asserts, and a
failure bundle written on ANY phase failure (``personas/bundle.py``: server log, CLI transcript,
``modules.lock.json`` diff, attempt envelope, screenshot, HTML, console -- redacted, verified).

Persona A -- AuDHD learner on a tablet over ``--lan`` (viewport 820x1180, budget 6 min)
  a1 load: no Labs entry, no prerequisite text anywhere
  a2 `module add <valid-scaffold>` via the CLI; reload; exactly one Labs entry, ids + prompts only
  a3 start one drill: inside the single claimed session, no `module-attempts` appears
  a4a focus lands in the terminal                       -- xfail(strict): gap, see the test
  a4b Tab / Shift-Tab traverse the Labs controls, focus visible (Escape is a5's cancel key)
  a5 Escape cancels: the recovery copy quoted in the test, the session where it was
  a6 reload re-attaches: same study_session_id, still one console
  a7 the missing-`kind` module: `add` accepts a conforming module (proposal §7), `doctor` names
     `kind` concisely, `drill` refuses before consent; nothing created; one Labs entry still
  a8 `module remove`; reload; Labs gone
  a9 the wall clock: under 6 minutes, measured
  Throughout: no overdue counter, no hint, no solution, no mentor notes in the rendered text.

Persona B -- new contributor on a clean machine (viewport 1440x900, budget 8 min)
  b1 the documented `uv` setup commands (docs/contributor-environment.md) that need no network
  b2 `module new` scaffolds   b3 `module check` passes it
  b4-b7 the Persona-A lifecycle on the contributor's own module:
        add -> Labs -> start -> cancel -> remove
  b8 break one fixture (remove `cleanupCommand` from a kubeconfig-context copy -> MC017), read the
     `--json` failure (rule id, file, line), repair it, re-check green
  b9 the docs' commands and the observed output agree (module-contract.md, cli-reference.md)
  b10 the wall clock: under 8 minutes, measured

Red-first (briefs/U1-persona-journeys.md): every phase is red "before the fixture flips it".
``STUDYLOOP_ACC_FORCE_FAIL=<phase id>`` flips THAT phase's precondition -- the CLI call it
depends on is skipped, or the opposite state is set up -- so its first assertion fails on its
own merit and the failure bundle is written. The transcripts live under
``openspec/changes/module-contract-v1/evidence/U1/``; the forced-failure bundle proof is
``evidence/U1/forced-failure-bundle/`` (``STUDYLOOP_ACC_FORCE_FAIL=a5``).

Run:  just testacc "" scripted packages/studyloop/tests/acceptance/test_module_personas.py
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

pytest.importorskip("playwright")

from .evidence import write_evidence_bundle
from .personas import world as pw
from .personas.bundle import (
    EXPECTED_MEMBERS,
    VIOLATIONS_NAME,
    CliRecord,
    write_persona_failure_bundle,
)
from .personas.modules import (
    MISSING_KIND_DRILL,
    MISSING_KIND_ID,
    build_missing_kind_module,
)
from .uat.redaction import contains_forbidden_content

_tests_dir = str(Path(__file__).resolve().parent.parent)
if _tests_dir not in sys.path:
    sys.path.insert(0, _tests_dir)

# Lane W's PUBLIC constants only; its helpers are private and copied into personas/world.py.
from e2e.test_module_labs_journey import DRILL_REF, TASK, VALID_SCAFFOLD  # noqa: E402

if TYPE_CHECKING:
    from collections.abc import Generator

    from playwright.sync_api import Page

    from .personas.world import PersonaWorld

pytestmark = [
    pytest.mark.acceptance,
    pytest.mark.timeout(600),
    # Markers run before ANY fixture: without this the session-scoped Playwright `browser`
    # would launch Chromium before the tier's function-scoped gate could skip (the lesson
    # `conftest.not_selected_marker` records). The autouse `_acceptance_gate` still runs.
    pytest.mark.skipif(
        os.environ.get("STUDYLOOP_ACC") != "1",
        reason="acceptance tests require STUDYLOOP_ACC=1 (see docs/acceptance-testing.md)",
    ),
]

PERSONA_A_BUDGET_S = 6 * 60
PERSONA_A_VIEWPORT = (820, 1180)

#: The recovery copy the Labs view renders beside a live drill (index.html, the labs-active
#: section). Quoted verbatim: a5 asserts on the rendered text, not on a class.
CANCEL_RECOVERY_COPY = (
    "Cancel drops the drill and leaves your session as it is. Nothing has been run."
)

# NOTE (commit 3 of lane U1): Persona B lands in the next commit with its own red transcripts.


# ---------------------------------------------------------------------------
# Shared assertions -- the C7 sweep every phase runs, and the lifecycle steps both personas share
# ---------------------------------------------------------------------------


def assert_c7_clean(page: Page, *tasks: dict) -> None:
    """No overdue counter, no hint, no solution, no mentor notes -- in the RENDERED text and in the
    DOM (proposal §5.6, C7). ``tasks`` are the deck tasks whose mentor-only strings must not
    appear; the fixture task from valid-scaffold is always included."""
    text = pw.visible_text(page)
    lowered = text.lower()
    assert "overdue" not in lowered, "an overdue counter is rendered"
    assert "mentor notes" not in lowered, "mentor notes are rendered"
    html = page.content()
    for task in (TASK, *tasks):
        for key in ("hint", "solution", "mentorNotes"):
            needle = task[key]
            assert needle not in text, f"mentor-side {key} is rendered: {needle!r}"
            assert needle not in html, f"mentor-side {key} reached the DOM: {needle!r}"


def assert_called(world: PersonaWorld, method: str, path: str) -> None:
    assert (method, path) in world.api_calls, (
        f"the UI never issued {method} {path}; recent API calls: {world.api_calls[-12:]}"
    )


def deck_task(module_dir: Path, deck_id: str, task_id: str) -> dict:
    deck = json.loads((module_dir / "decks" / f"{deck_id}.json").read_text("utf-8"))
    assert deck["id"] == deck_id, deck
    return next(task for task in deck["tasks"] if task["id"] == task_id)


def step_labs_lists_the_installed_module(
    world: PersonaWorld, page: Page, *, module_id: str, task: dict, extra_tasks: tuple = ()
) -> None:
    """After `module add`: reload; exactly ONE Labs entry; the view lists ids and prompts only."""
    pw.reload(page)
    pw.wait_labs_entry(page, visible=True)
    assert page.locator("[data-testid='nav-labs']").count() == 1, "exactly ONE Labs entry"
    options = pw.api(page, "/api/session/options")
    assert [m["module_id"] for m in options["labs"]] == [module_id], options.get("labs")
    pw.goto(page, world, "labs")
    page.wait_for_selector("[data-testid='labs-view']", state="visible", timeout=15_000)
    page.wait_for_selector(
        f"[data-testid='labs-start-{task['id']}']", state="visible", timeout=15_000
    )
    view_text = page.locator("[data-testid='labs-view']").inner_text()
    for needle in (module_id, task["id"], task["prompt"], task["successCriteria"][0]):
        assert needle in view_text, f"{needle!r} missing from the Labs view"
    assert "prerequisite" not in view_text.lower(), "Labs renders prerequisite text"
    assert "studyloop drill check" not in view_text, "the commands belong to the live strip only"
    assert_c7_clean(page, task, *extra_tasks)
    assert pw.study_consoles(page) == 0, "a session-less page mounts no Study Session console"


def step_start_runs_inside_the_one_claimed_session(
    world: PersonaWorld, page: Page, *, drill_ref: str, task_id: str, flipped: bool
) -> None:
    pw.goto(page, world, "labs")
    page.wait_for_function(
        """() => {
            const sel = document.querySelector('#labs-agent-select');
            return sel && sel.value === 'codex';
        }""",
        timeout=30_000,
    )
    if not flipped:
        page.locator(f"[data-testid='labs-start-{task_id}']").click()
        world.facts["drill_started"] = {"ref": drill_ref, "at_s": round(world.budget.elapsed(), 3)}
    # The one start path: POST /api/modules/labs/start, then the Study Session view adopts
    # the live session on load and the console -- the mentor pane -- mounts.
    page.wait_for_function("() => location.hash === '#study-session'", timeout=15_000)
    page.wait_for_selector(".session-active-layout .xterm-mount", state="visible", timeout=60_000)
    pw.wait_for_terminal_text(page, "FAKE-AGENT READY")
    pw.wait_for_terminal_text(page, "FAKE-AGENT TOPIC: Lab: " + drill_ref)
    assert pw.study_consoles(page) >= 1
    assert pw.body_double_consoles(page) == 0, "the Body Double console must not cross-fire"

    state = pw.api(page, "/api/session/state")
    assert state["origin"] == "study"
    assert state["labs_drill"]["ref"] == drill_ref
    assert state["topic"] == f"Lab: {drill_ref}"
    world.facts["session_id"] = state["study_session_id"]

    on_disk = world.state_file()
    assert on_disk["study_session_id"] == state["study_session_id"], "one session, one record"
    assert on_disk["web_port"] == world.server.port
    assert on_disk["practice_check_token"], "the capability for the CLI hop sits beside the port"
    mode = (world.world.session_dir / "session-state.json").stat().st_mode & 0o777
    assert mode == 0o600, oct(mode)
    # Labs never executes a phase: no attempt directory exists anywhere in the world.
    assert world.attempt_dirs() == [], "a phase ran from Labs"


def step_escape_cancels_with_clear_recovery_copy(
    world: PersonaWorld, page: Page, *, task_id: str, flipped: bool
) -> None:
    pw.goto(page, world, "labs")
    page.wait_for_selector("[data-testid='labs-active-drill']", state="visible", timeout=15_000)
    strip = page.locator("[data-testid='labs-active-drill']").inner_text()
    assert CANCEL_RECOVERY_COPY in strip, f"the recovery copy is not rendered; strip: {strip!r}"
    assert "Cancel drill" in strip, strip
    page.locator("[data-testid='labs-cancel-drill']").focus()
    if not flipped:
        page.keyboard.press("Escape")
    page.wait_for_selector("[data-testid='labs-active-drill']", state="hidden", timeout=15_000)
    assert_called(world, "POST", "/api/modules/labs/cancel")
    assert ("POST", "/api/session/end") not in world.api_calls, "cancel must never end the session"
    state = pw.api(page, "/api/session/state")
    assert state["study_session_id"] == world.facts["session_id"]
    assert state["mode"] != "ended"
    assert state.get("labs_drill") is None
    assert world.attempt_dirs() == [], "a phase ran"
    # The Start button is offered again for the drill that was cancelled -- nothing to undo.
    start = page.locator(f"[data-testid='labs-start-{task_id}']")
    assert not start.is_disabled()
    assert start.inner_text().strip() == "Start drill"
    assert_c7_clean(page)


def step_remove_takes_labs_away(
    world: PersonaWorld, page: Page, *, module_id: str, flipped: bool
) -> None:
    if not flipped:
        result = world.cli("module", "remove", module_id)
        assert result.returncode == 0, result.stdout + result.stderr
        assert f"removed {module_id}" in result.stdout, result.stdout
    assert pw.api(page, "/api/modules/labs")["labs"] == [], "the Labs listing is not empty"
    # A full reload with a stale #labs hash (a hash-only goto is a same-document navigation).
    page.evaluate("() => { window.location.hash = 'labs'; }")
    pw.reload(page)
    pw.wait_labs_loaded(page)
    assert not pw.labs_entry_visible(page), "Labs is gone with the lockfile emptied"
    assert "labs" not in pw.api(page, "/api/session/options")
    page.wait_for_function("() => window.Alpine.store('nav').current === 'today'", timeout=15_000)
    assert not page.locator("[data-testid='labs-view']").is_visible(), (
        "a stale #labs hash does not resurrect the view"
    )
    assert_c7_clean(page)


def step_under_budget(world: PersonaWorld, page: Page, *, flipped: bool) -> None:
    elapsed = world.budget.elapsed()
    # Flipped: a budget no run can meet, so the assertion is seen to bite.
    limit = 0.001 if flipped else world.budget.limit_s
    world.facts["wall_clock_s"] = round(elapsed, 1)
    print(f"[persona {world.persona}] wall-clock {elapsed:.1f}s of the {limit:.0f}s budget")
    assert world.server.proc.poll() is None, "the server died during the persona"
    page_errors = [e for e in world.console_errors if "pageerror" in e]
    assert not page_errors, page_errors
    assert elapsed < limit, f"Persona {world.persona} took {elapsed:.1f}s; budget {limit:.0f}s"


# ---------------------------------------------------------------------------
# The failure bundle -- mechanics, without a browser (the forced-failure proof is a run, see
# evidence/U1/forced-failure-bundle/)
# ---------------------------------------------------------------------------


class TestBundleWriter:
    def test_positive_control_the_detector_flags_dirty_input(self) -> None:
        """Prove the UAT detector flags what the bundle must not carry BEFORE trusting it to
        certify a bundle clean (acceptance/uat/redaction.py's own instruction)."""
        dirty = "wrote /Users/someone/.config/studyloop/modules.lock.json with sk-abcdefghijklmnop"
        violations = contains_forbidden_content(dirty)
        assert any("home path" in v for v in violations), violations
        assert any("key-like" in v for v in violations), violations

    def test_failure_bundle_carries_the_seven_artefacts_redacted(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        lan_credential = "lan-" + "x" * 20  # a stand-in for the run's --lan credential
        bundle, violations = write_persona_failure_bundle(
            tmp_path / "evidence",
            run_id="unit-bundle",
            persona="A",
            outcome="forced",
            phases=[{"phase": "a1", "status": "passed", "elapsed_s": 0.1}],
            server_log=f"LAN password: {lan_credential}\nvault {home}/study-materials\n"
            f"digest sha256:{'ab' * 32}\n",
            cli_records=[
                CliRecord(("module", "add", str(home / "mod")), "", 0, "installed\n", "", 0.2)
            ],
            lockfile_before=None,
            lockfile_after=json.dumps({"modules": [{"id": "echo-drills", "digest": "ab" * 32}]}),
            attempt_envelope={"labs_drill": {"ref": DRILL_REF}, "path": str(home)},
            screenshot_png=b"\x89PNG\r\n\x1a\n",
            page_html=f"<html><body>{home}</body></html>",
            console={"errors": [f"console.error: {home}/x.js"], "api_calls": []},
            homes=[home],
            secrets={"lan_password": lan_credential},
        )
        names = {p.name for p in bundle.run_dir.iterdir()}
        assert set(EXPECTED_MEMBERS) <= names, sorted(names)
        assert VIOLATIONS_NAME not in names, (bundle.run_dir / VIOLATIONS_NAME).read_text()
        assert violations == []
        manifest = json.loads(bundle.manifest_path.read_text())
        assert manifest["artifacts"] == {
            "server_log": "server.log",
            "cli_transcript": "cli-transcript.txt",
            "lockfile_diff": "modules.lock.diff",
            "attempt_envelope": "attempt-envelope.json",
        }
        server_log = (bundle.run_dir / "server.log").read_text()
        assert "<REDACTED:lan_password>" in server_log and lan_credential not in server_log
        assert "<WORLD>/study-materials" in server_log
        assert "sha256:abababababab…" in server_log, server_log
        diff = (bundle.run_dir / "modules.lock.diff").read_text()
        assert diff.startswith("--- modules.lock.json (before)") and "+{" in diff, diff
        transcript = (bundle.run_dir / "cli-transcript.txt").read_text()
        assert "$ studyloop module add <WORLD>/mod" in transcript and "[exit 0" in transcript
        envelope = json.loads((bundle.run_dir / "attempt-envelope.json").read_text())
        assert envelope == {
            "persona": "A",
            "envelope": {"labs_drill": {"ref": DRILL_REF}, "path": "<WORLD>"},
        }

    def test_write_evidence_bundle_without_members_keeps_the_pre_u1_manifest(
        self, tmp_path: Path
    ) -> None:
        """Existing callers must not change: no member passed -> the eight keys, no `artifacts`."""
        bundle = write_evidence_bundle(
            tmp_path,
            run_id="plain",
            harness="codex",
            actor="scripted",
            outcome="completed",
            turns=[],
        )
        manifest = json.loads(bundle.manifest_path.read_text())
        assert set(manifest) == {
            "run_id",
            "harness",
            "actor",
            "outcome",
            "turn_count",
            "platform",
            "auth_mode",
            "harness_version",
        }
        assert bundle.server_log_path is None and bundle.attempt_envelope_path is None
        assert {p.name for p in bundle.run_dir.iterdir()} == {"manifest.json", "turns.json"}


# ---------------------------------------------------------------------------
# Persona A -- AuDHD learner on a tablet over --lan
# ---------------------------------------------------------------------------


@pytest.fixture(scope="class")
def persona_a(
    tmp_path_factory: pytest.TempPathFactory, browser
) -> Generator[PersonaWorld, None, None]:
    root = tmp_path_factory.mktemp("persona-a")
    world = pw.launch_persona_world(root, persona="A", budget_s=PERSONA_A_BUDGET_S, lan=True)
    try:
        pw.open_page(browser, world, viewport=PERSONA_A_VIEWPORT)
        yield world
    finally:
        pw.stop_persona_world(world)


@pytest.fixture()
def page_a(persona_a: PersonaWorld) -> Page:
    assert persona_a.page is not None
    return persona_a.page


class TestPersonaA:
    def test_a1_load_shows_no_labs_entry_and_no_prerequisite_text(
        self, persona_a: PersonaWorld, page_a: Page
    ) -> None:
        world, page = persona_a, page_a
        with world.phase("a1", "load: no Labs entry, no prerequisite text"):
            if world.flipped("a1"):  # the opposite state: a module already installed
                world.cli("module", "add", str(VALID_SCAFFOLD))
            assert world.lan_password, "Persona A's server runs with --lan"
            assert world.server.base_url.startswith("http://127.0.0.1:"), world.server.base_url
            page.goto(f"{world.server.base_url}/#today")
            pw.wait_labs_loaded(page)
            assert_called(world, "GET", "/api/modules/labs")
            assert not pw.labs_entry_visible(page), "Labs must be hidden with an empty lockfile"
            assert "labs" not in pw.api(page, "/api/session/options"), "options carry no Labs"
            assert pw.api(page, "/api/modules/labs")["labs"] == []
            assert "prerequisite" not in pw.visible_text(page).lower(), "no prerequisite text"
            assert_c7_clean(page)

    def test_a2_module_add_then_exactly_one_labs_entry_with_ids_and_prompts(
        self, persona_a: PersonaWorld, page_a: Page
    ) -> None:
        world, page = persona_a, page_a
        with world.phase("a2", "module add via the CLI; reload; one Labs entry"):
            if not world.flipped("a2"):
                result = world.cli("module", "add", str(VALID_SCAFFOLD))
                assert result.returncode == 0, result.stdout + result.stderr
                assert "installed echo-drills" in result.stdout, result.stdout
            step_labs_lists_the_installed_module(world, page, module_id="echo-drills", task=TASK)

    def test_a3_start_one_drill_inside_the_single_claimed_session(
        self, persona_a: PersonaWorld, page_a: Page
    ) -> None:
        world, page = persona_a, page_a
        with world.phase("a3", "start one drill inside the one claimed session"):
            step_start_runs_inside_the_one_claimed_session(
                world, page, drill_ref=DRILL_REF, task_id="echo-01", flipped=world.flipped("a3")
            )

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "GAP (design.md §6 step 4 'focus lands in the terminal'): after a Labs start the "
            "Study Session console mounts xterm (web/static/js/components/live-agent-console.js, "
            "term.open at ~259) without ever calling term.focus(); the fresh-start path also "
            "reloads the page (labs.js startDrill), so document.activeElement is <body>. Product "
            "change needed: focus the terminal when the console (re)attaches."
        ),
    )
    def test_a4a_focus_lands_in_the_terminal(self, persona_a: PersonaWorld, page_a: Page) -> None:
        world, page = persona_a, page_a
        with world.phase("a4a", "focus lands in the terminal after the start", bundle=False):
            pw.goto(page, world, "study-session")
            page.wait_for_selector(
                ".session-active-layout .xterm-mount", state="visible", timeout=30_000
            )
            page.wait_for_timeout(500)
            assert pw.terminal_has_focus(page), (
                f"focus is on {pw.active_element_description(page)}, not in the terminal"
            )

    def test_a4b_tab_and_shift_tab_traverse_the_labs_controls_with_visible_focus(
        self, persona_a: PersonaWorld, page_a: Page
    ) -> None:
        world, page = persona_a, page_a
        with world.phase("a4b", "keyboard-only traversal: Tab / Shift-Tab, focus visible"):
            pw.goto(page, world, "labs")
            page.wait_for_selector(
                "[data-testid='labs-active-drill']", state="visible", timeout=15_000
            )
            strip = page.locator("[data-testid='labs-active-drill']").inner_text()
            assert f"studyloop drill check {DRILL_REF}" in strip, "the live strip names the command"
            if not world.flipped("a4b"):
                page.locator("[data-testid='labs-open-session']").focus()
            page.keyboard.press("Tab")
            focused = pw.active_testid(page)
            assert focused == "labs-cancel-drill", (
                f"Tab landed on {pw.active_element_description(page)}"
            )
            assert page.evaluate("() => document.activeElement.matches(':focus-visible')"), (
                "the focused control carries no visible focus"
            )
            page.keyboard.press("Shift+Tab")
            assert pw.active_testid(page) == "labs-open-session", (
                f"Shift-Tab landed on {pw.active_element_description(page)}"
            )
            page.keyboard.press("Tab")
            page.keyboard.press("Tab")
            assert page.evaluate("() => document.activeElement.id") == "labs-agent-select", (
                f"Tab landed on {pw.active_element_description(page)} (expected the agent select)"
            )
            assert pw.body_double_consoles(page) == 0
            assert_c7_clean(page)

    def test_a5_escape_cancels_with_clear_recovery_copy(
        self, persona_a: PersonaWorld, page_a: Page
    ) -> None:
        world, page = persona_a, page_a
        with world.phase("a5", "cancel: Escape, the recovery copy, the session untouched"):
            step_escape_cancels_with_clear_recovery_copy(
                world, page, task_id="echo-01", flipped=world.flipped("a5")
            )

    def test_a6_reload_reattaches_with_no_second_session(
        self, persona_a: PersonaWorld, page_a: Page
    ) -> None:
        world, page = persona_a, page_a
        with world.phase("a6", "reload: re-attach, still one session"):
            before = pw.api(page, "/api/session/state")
            errors_before = len(world.console_errors)
            if world.flipped("a6"):  # the opposite state: no running session to re-attach to
                page.evaluate("async () => { await fetch('/api/session/end', {method: 'POST'}); }")
            pw.reload(page)
            pw.goto(page, world, "study-session")
            after = pw.api(page, "/api/session/state")
            assert after.get("study_session_id") == before["study_session_id"], (
                f"the session changed across the reload: {after}"
            )
            assert after["study_session_id"] == world.facts["session_id"]
            assert after.get("mode") != "ended", "the session did not survive the reload"
            page.wait_for_selector(
                ".session-active-layout .xterm-mount", state="visible", timeout=30_000
            )
            # A re-attach does not replay earlier output; this line is the proof the SAME running
            # session was adopted rather than a new one started.
            pw.wait_for_terminal_text(page, "reattached to your running session", timeout=30_000)
            assert world.state_file()["study_session_id"] == world.facts["session_id"]
            assert pw.study_consoles(page) >= 1 and pw.body_double_consoles(page) == 0
            pw.goto(page, world, "labs")
            page.wait_for_selector(
                "[data-testid='labs-start-echo-01']", state="visible", timeout=15_000
            )
            assert not page.locator("[data-testid='labs-active-drill']").is_visible(), (
                "the cancelled drill came back after the reload"
            )
            post_reload = [
                err
                for err in world.console_errors[errors_before:]
                if not ("Event" in err and "htmx" in err)
            ]
            assert not post_reload, f"reload produced unexpected console errors: {post_reload}"
            assert_c7_clean(page)

    def test_a7_missing_kind_module_reports_the_prerequisite_and_creates_nothing(
        self, persona_a: PersonaWorld, page_a: Page
    ) -> None:
        """Design.md §6 (7): "install a fixture missing `kind`, assert a concise prerequisite
        report and no resource creation". On the shipped product (and proposal §5.4 / §7):
        `module add` is the STATIC check (MC001-MC017) and accepts a conforming module whatever
        is on the PATH; the prerequisite report is `studyloop doctor`'s ("kind not found (needed
        by <module>)"), and `studyloop drill` refuses the phase BEFORE consent, naming `kind`,
        with no attempt opened and nothing spawned. The U1 brief's "exit non-zero, no snapshot
        published" reading of this step is reported, not asserted -- it would need `module add`
        to probe the PATH, which proposal §7 does not ask for."""
        world, page = persona_a, page_a
        with world.phase("a7", "the missing-kind module: report named, nothing created"):
            module_dir = build_missing_kind_module(world.world.root / "missing-kind-module")
            checked = world.cli("module", "check", str(module_dir))
            assert checked.returncode == 0, checked.stdout + checked.stderr
            cli_env = dict(world.world.env)
            if world.flipped("a7"):  # the opposite state: a `kind` IS on the learner's PATH
                fake_bin = world.world.root / "fake-bin"
                fake_bin.mkdir(exist_ok=True)
                fake_kind = fake_bin / "kind"
                fake_kind.write_text("#!/bin/sh\necho kind v0.0.0\n", encoding="utf-8")
                fake_kind.chmod(fake_kind.stat().st_mode | stat.S_IXUSR)
                cli_env["PATH"] = f"{fake_bin}{os.pathsep}{cli_env['PATH']}"
            if not world.flipped("a7"):
                assert shutil.which("kind", path=cli_env["PATH"]) is None, (
                    "precondition: this persona runs on a machine with no `kind` on the PATH"
                )
            labs_before = pw.api(page, "/api/modules/labs")["labs"]
            lockfile_before = world.lockfile_text()

            added = world.cli("module", "add", str(module_dir), env=cli_env)
            assert added.returncode == 0, added.stdout + added.stderr  # proposal §7: check only
            assert f"installed {MISSING_KIND_ID}" in added.stdout, added.stdout

            # The concise prerequisite report: doctor, reports only (proposal §5.4). The rich
            # table wraps cells across rows (columns interleave), so the learner-facing table is
            # checked for its row -- a failed `deps` row whose first line names `kind not found`
            # -- and the exact message is read back through --json.
            doctor = world.cli("doctor", env=cli_env)
            kind_rows = [line for line in doctor.stdout.splitlines() if "kind not found" in line]
            assert kind_rows and "✗" in kind_rows[0], doctor.stdout
            assert MISSING_KIND_ID in doctor.stdout and "Install kind" in doctor.stdout
            assert doctor.returncode != 0, "a missing prerequisite is not a clean doctor run"
            rows = json.loads(world.cli("doctor", "--json", env=cli_env).stdout)
            row = next(r for r in rows if r["name"] == "module_prereq_kind")
            assert row["category"] == "deps" and row["status"] == "fail", row
            assert row["message"] == f"kind not found (needed by {MISSING_KIND_ID})", row
            world.facts["a7_doctor_row"] = row

            # The drill refuses BEFORE consent, naming the tool; nothing is created.
            refused = world.cli("drill", "check", MISSING_KIND_DRILL, stdin="y\n", env=cli_env)
            assert refused.returncode != 0, refused.stdout
            output = refused.stdout + refused.stderr
            assert "prerequisite 'kind' is not on your PATH" in output, output
            assert "Run this phase now?" not in refused.stdout, "consent was asked before refusing"
            assert world.attempt_dirs() == [], "an attempt was opened for a refused phase"

            # No Labs change: still exactly ONE Labs entry; the installed module is listed by id
            # and prompt only -- no prerequisite text reaches the DOM.
            pw.reload(page)
            pw.wait_labs_entry(page, visible=True)
            assert page.locator("[data-testid='nav-labs']").count() == 1
            listed = pw.api(page, "/api/modules/labs")["labs"]
            assert [m["module_id"] for m in listed] == [
                *[m["module_id"] for m in labs_before],
                MISSING_KIND_ID,
            ]
            pw.goto(page, world, "labs")
            page.wait_for_selector("[data-testid='labs-view']", state="visible", timeout=15_000)
            view_text = page.locator("[data-testid='labs-view']").inner_text()
            assert MISSING_KIND_ID in view_text
            lowered = view_text.lower()
            for phrase in ("prerequisite", "kind not found", "install kind", "not on your path"):
                assert phrase not in lowered, f"prerequisite text reached the Labs view: {phrase!r}"
            assert_c7_clean(page)

            # Leave the lockfile as a8 expects: one module, the one a2 installed.
            removed = world.cli("module", "remove", MISSING_KIND_ID, env=cli_env)
            assert removed.returncode == 0, removed.stdout + removed.stderr
            assert world.lockfile_text() == lockfile_before, "remove did not restore the lockfile"

    def test_a8_module_remove_then_labs_gone(self, persona_a: PersonaWorld, page_a: Page) -> None:
        world, page = persona_a, page_a
        with world.phase("a8", "module remove; reload; Labs gone"):
            step_remove_takes_labs_away(
                world, page, module_id="echo-drills", flipped=world.flipped("a8")
            )

    def test_a9_the_whole_persona_finished_under_six_minutes(
        self, persona_a: PersonaWorld, page_a: Page
    ) -> None:
        with persona_a.phase("a9", "wall clock under the 6-minute budget"):
            step_under_budget(persona_a, page_a, flipped=persona_a.flipped("a9"))
