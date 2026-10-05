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
  a4a focus lands in the terminal (fixed under the U1-review grant; red kept)
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

import dataclasses
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

pytest.importorskip("playwright")

from studyloop.session.module_delivery import EnvelopeValidationError

from .evidence import write_evidence_bundle
from .personas import docs_contract
from .personas import world as pw
from .personas.bundle import (
    EXPECTED_MEMBERS,
    VIOLATIONS_NAME,
    CliRecord,
    write_persona_failure_bundle,
)
from .personas.modules import (
    K8S_OFFLINE,
    MISSING_KIND_DRILL,
    MISSING_KIND_ID,
    build_missing_kind_module,
    copy_module,
)
from .uat.redaction import RedactionLeakError, contains_forbidden_content

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

REPO_ROOT = Path(__file__).resolve().parents[4]
DOCS = REPO_ROOT / "docs"
EVIDENCE_U1 = REPO_ROOT / "openspec" / "changes" / "module-contract-v1" / "evidence" / "U1"
FORCED_FAILURE_BUNDLE = EVIDENCE_U1 / "forced-failure-bundle"

PERSONA_A_BUDGET_S = 6 * 60
PERSONA_B_BUDGET_S = 8 * 60
PERSONA_A_VIEWPORT = (820, 1180)
PERSONA_B_VIEWPORT = (1440, 900)

#: The recovery copy the Labs view renders beside a live drill (index.html, the labs-active
#: section). Quoted verbatim: a5 asserts on the rendered text, not on a class.
CANCEL_RECOVERY_COPY = (
    "Cancel drops the drill and leaves your session as it is. Nothing has been run."
)

#: The scaffold `studyloop module new my-drills` writes (modules/scaffold.py), as the docs name it.
CONTRIBUTOR_MODULE_ID = "my-drills"
CONTRIBUTOR_DRILL_REF = f"{CONTRIBUTOR_MODULE_ID}/getting-started/ready-01"


# ---------------------------------------------------------------------------
# Shared assertions -- the C7 sweep every phase runs, and the lifecycle steps both personas share
# ---------------------------------------------------------------------------


def mentor_only(task: dict) -> tuple[str, str, str]:
    return (task["hint"], task["solution"], task["mentorNotes"])


def assert_c7_clean(page: Page, *tasks: dict) -> None:
    """The C7 sweep (personas/world.py `c7_sweep`), called mid-phase where a view was just
    rendered; the phase wrapper runs the same sweep at the end of EVERY browser phase with the
    persona's registered texts. ``tasks`` add their mentor-only strings; valid-scaffold's task
    is always included."""
    texts = [*mentor_only(TASK)]
    for task in tasks:
        texts.extend(mentor_only(task))
    pw.c7_sweep(page, texts)


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
    pw.wait_labs_loaded(page)
    pw.settle(page, "() => window.Alpine.store('labs').available === true")
    assert pw.labs_entry_visible(page), (
        f"expected the Labs entry in the sidebar after `module add {module_id}`; "
        f"the lockfile lists {[m['module_id'] for m in pw.api(page, '/api/modules/labs')['labs']]}"
    )
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
    # The picker pre-selects the first detected agent (the fake agent rides the codex adapter);
    # a selected real harness is chosen explicitly, exactly as the learner would.
    page.wait_for_function(
        """() => {
            const sel = document.querySelector('#labs-agent-select');
            return sel && sel.value !== '';
        }""",
        timeout=30_000,
    )
    if world.fake_mentor:
        assert page.locator("#labs-agent-select").input_value() == "codex"
    else:
        page.select_option("#labs-agent-select", world.harness)
        assert page.locator("#labs-agent-select").input_value() == world.harness
    if not flipped:
        page.locator(f"[data-testid='labs-start-{task_id}']").click()
        world.facts["drill_started"] = {"ref": drill_ref, "at_s": round(world.budget.elapsed(), 3)}
    # The one start path: POST /api/modules/labs/start, then the Study Session view adopts
    # the live session on load and the console -- the mentor pane -- mounts.
    pw.settle(page, "() => location.hash === '#study-session'")
    assert page.evaluate("() => location.hash") == "#study-session", (
        f"expected the Study Session view after Start on {drill_ref}; the page is still on "
        f"{page.evaluate('() => location.hash')!r} and the session state is "
        f"{pw.api(page, '/api/session/state').get('study_session_id')!r}"
    )
    page.wait_for_selector(".session-active-layout .xterm-mount", state="visible", timeout=60_000)
    if world.fake_mentor:
        pw.wait_for_terminal_text(page, "FAKE-AGENT READY")
        pw.wait_for_terminal_text(page, "FAKE-AGENT TOPIC: Lab: " + drill_ref)
    assert pw.study_consoles(page) >= 1
    assert pw.body_double_consoles(page) == 0, "the Body Double console must not cross-fire"

    state = pw.api(page, "/api/session/state")
    assert state["origin"] == "study"
    assert state["labs_drill"]["ref"] == drill_ref
    assert state["topic"] == f"Lab: {drill_ref}"
    assert state.get("agent") == ("codex" if world.fake_mentor else world.harness), state
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
    pw.settle(
        page,
        """() => { const el = document.querySelector("[data-testid='labs-active-drill']");
                  return !el || el.offsetParent === null; }""",
    )
    assert not page.locator("[data-testid='labs-active-drill']").is_visible(), (
        "expected the live-drill strip to be gone after Escape; it is still shown and the "
        f"state file still names {world.state_file().get('labs_drill')!r}"
    )
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
        bundle = write_persona_failure_bundle(
            tmp_path / "evidence",
            run_id="unit-bundle",
            persona="A",
            outcome="forced",
            phases=[{"phase": "a1", "status": "passed", "elapsed_s": 0.1}],
            server_log=f"LAN password: {lan_credential}\nvault {home}/study-materials\n"
            f"digest sha256:{'ab' * 32}\nsource {tmp_path}/repo/fixtures /Users/someone/x\n",
            cli_records=[
                CliRecord(("module", "add", str(home / "mod")), "", 0, "installed\n", "", 0.2)
            ],
            lockfile_before=None,
            lockfile_after=json.dumps({"modules": [{"id": "echo-drills", "digest": "ab" * 32}]}),
            labs_binding={"labs_drill": {"ref": DRILL_REF}, "path": str(home)},
            screenshot_png=b"\x89PNG\r\n\x1a\n",
            page_html=f"<html><body>{home}</body></html>",
            console={"errors": [f"console.error: {home}/x.js"], "api_calls": []},
            homes=[home, tmp_path / "repo", Path("/Users/someone")],
            secrets={"lan_password": lan_credential},
        )
        names = {p.name for p in bundle.run_dir.iterdir()}
        assert set(EXPECTED_MEMBERS) <= names, sorted(names)
        assert VIOLATIONS_NAME not in names, "a clean bundle writes no violations file"
        manifest = json.loads(bundle.manifest_path.read_text())
        assert manifest["artifacts"] == {
            "server_log": "server-log.txt",
            "cli_transcript": "cli-transcript.txt",
            "lockfile_diff": "modules.lock.diff",
            "labs_binding": "labs-binding.json",
            "practice_envelope": None,
        }
        server_log = (bundle.run_dir / "server-log.txt").read_text()
        assert "<REDACTED:lan_password>" in server_log and lan_credential not in server_log
        assert "<WORLD>/study-materials" in server_log
        assert "sha256:abababababab…" in server_log, server_log
        assert "source <REPO>/fixtures <HOME>/x" in server_log, server_log
        diff = (bundle.run_dir / "modules.lock.diff").read_text()
        assert diff.startswith("--- modules.lock.json (before)") and "+{" in diff, diff
        transcript = (bundle.run_dir / "cli-transcript.txt").read_text()
        assert "$ studyloop module add <WORLD>/mod" in transcript and "[exit 0" in transcript
        binding = json.loads((bundle.run_dir / "labs-binding.json").read_text())
        assert binding == {
            "persona": "A",
            "binding": {"labs_drill": {"ref": DRILL_REF}, "path": "<WORLD>"},
        }

    def _bundle_inputs(self, tmp_path: Path, outcome: str) -> dict:
        home = tmp_path / "home"
        return {
            "run_id": "leak-check",
            "persona": "B",
            "outcome": outcome,
            "phases": [],
            "server_log": "",
            "cli_records": [],
            "lockfile_before": None,
            "lockfile_after": None,
            "labs_binding": None,
            "screenshot_png": None,
            "page_html": None,
            "console": {"errors": [], "api_calls": []},
            "homes": [home, tmp_path / "repo", Path("/Users/someone")],
            "secrets": {},
        }

    def test_the_outcome_is_redacted_before_it_enters_the_manifest(self, tmp_path: Path) -> None:
        """U1-review F3: B8's flipped run put the venv interpreter path into `outcome` raw
        (persona-b-b8.red.txt). The outcome goes through the same redaction as every member."""
        venv_python = tmp_path / "repo" / ".venv" / "bin" / "python"
        write_persona_failure_bundle(
            tmp_path / "evidence",
            **self._bundle_inputs(tmp_path, f"exit 0: CompletedProcess(args=['{venv_python}'])"),
        )
        manifest = json.loads((tmp_path / "evidence" / "leak-check" / "manifest.json").read_text())
        assert str(venv_python) not in manifest["outcome"], manifest["outcome"]
        assert "<REPO>/.venv/bin/python" in manifest["outcome"], manifest["outcome"]

    def test_a_leak_the_redactor_cannot_label_fails_the_bundle_naming_it(
        self, tmp_path: Path
    ) -> None:
        """U1-review F3: detection without failure is no gate. A home path under a root the
        redactor does not know is written to redaction-violations.txt AND raises, naming the
        bundle and the violation."""
        with pytest.raises(RedactionLeakError, match="leak-check") as leaked:
            write_persona_failure_bundle(
                tmp_path / "evidence",
                **self._bundle_inputs(tmp_path, "wrote /Users/nobody/.config/studyloop/x"),
            )
        assert "home path leaked" in str(leaked.value), str(leaked.value)
        violations = tmp_path / "evidence" / "leak-check" / VIOLATIONS_NAME
        assert violations.is_file() and "/Users/nobody/" in violations.read_text()

    def test_the_committed_bundle_names_the_labs_binding_for_what_it_is(self) -> None:
        """U1-review F4: the member that used to be called `attempt-envelope.json` holds the Labs
        start binding (session, drill, nonce, attempt ids), NOT the production
        PracticeCheckEnvelope -- it is named `labs-binding.json`, and `practice-envelope.json`
        exists only when a drill phase actually ran (neither persona runs one)."""
        bundle_dir = FORCED_FAILURE_BUNDLE
        manifest = json.loads((bundle_dir / "manifest.json").read_text())
        artifacts = manifest["artifacts"]
        assert "attempt_envelope" not in artifacts, artifacts
        assert artifacts["labs_binding"] == "labs-binding.json", artifacts
        assert (bundle_dir / "labs-binding.json").is_file()
        assert not (bundle_dir / "attempt-envelope.json").exists()
        binding = json.loads((bundle_dir / "labs-binding.json").read_text())
        assert binding["binding"]["labs_drill"]["ref"] == DRILL_REF, binding
        assert artifacts["practice_envelope"] is None, "no persona runs a drill phase"
        assert not (bundle_dir / "practice-envelope.json").exists()

    def test_a_practice_envelope_is_validated_before_it_is_written(self, tmp_path: Path) -> None:
        """A production envelope member is written only through
        session.module_delivery.validate_envelope -- an invalid one is refused by field name."""
        envelope = {
            "module_id": "echo-drills",
            "module_digest": "sha256:" + "ab" * 32,
            "deck_id": "echo-basics",
            "task_id": "echo-01",
            "attempt_id": "20261005T110000Z-abcdef01",
            "phase": "check",
            "exit_class": "passed",
            "exit_code": 0,
            "duration_s": 0.1,
            "stdout_tail": "ready\n",
            "stderr_tail": "",
            "triggered_by": "learner",
        }
        with pytest.raises(EnvelopeValidationError, match="exit_class"):
            write_persona_failure_bundle(
                tmp_path / "refused",
                practice_envelope={**envelope, "exit_class": "nope"},
                **self._bundle_inputs(tmp_path, "forced"),
            )
        bundle = write_persona_failure_bundle(
            tmp_path / "evidence",
            practice_envelope=envelope,
            **self._bundle_inputs(tmp_path, "forced"),
        )
        written = json.loads((bundle.run_dir / "practice-envelope.json").read_text())
        assert written["attempt_id"] == envelope["attempt_id"] and written["phase"] == "check"
        assert written["module_digest"].startswith("sha256:")
        manifest = json.loads(bundle.manifest_path.read_text())
        assert manifest["artifacts"]["practice_envelope"] == "practice-envelope.json"

    @pytest.mark.parametrize(
        "member",
        sorted({*EXPECTED_MEMBERS, "practice-envelope.json", "manifest.json", "turns.json"}),
    )
    def test_every_bundle_member_name_survives_the_repositorys_gitignore(self, member: str) -> None:
        """U1-review F1: a member the manifest names must be committable under evidence/U1/ --
        `*.log` is gitignored (.gitignore `# Logs`), so a `server.log` member is written, named
        in the manifest, and silently absent from the tree."""
        path = str((FORCED_FAILURE_BUNDLE / member).relative_to(REPO_ROOT))
        probe = subprocess.run(
            ["git", "check-ignore", "-v", "--no-index", "--", path],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert probe.returncode == 1, (
            f"bundle member {member!r} is ignored by the repository: {probe.stdout.strip()}"
        )

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
        assert bundle.server_log_path is None and bundle.labs_binding_path is None
        assert {p.name for p in bundle.run_dir.iterdir()} == {"manifest.json", "turns.json"}


# ---------------------------------------------------------------------------
# The documented module-command contract (U1-review F7): what docs/module-contract.md,
# docs/cli-reference.md and the --help texts promise about `module new|check|list|add`, parsed,
# so B9 can compare the observed output against it rather than against literals.
# ---------------------------------------------------------------------------


class TestDocsContract:
    def test_the_documented_expectations_are_parsed_from_the_pages_and_the_help(self) -> None:
        contract = docs_contract.load_documented_contract(DOCS)
        assert contract.finding_template == "MCnnn <file>:<line>: <message>"
        assert contract.check_exit_codes == {"conforming": 0, "findings": 1, "not a dir": 2}
        assert contract.json_report_keys == ("ok", "findings")
        assert contract.json_finding_keys == ("rule_id", "message", "path", "line")
        assert contract.list_digest_hex == 12
        assert {"module.yaml", "mentor/brief.md", "README.md", "LICENSE", "CHANGELOG.md"} <= set(
            contract.scaffold_files
        )
        assert contract.check_script_prints == "ready" and contract.check_script_exit == 0
        assert contract.snapshot_dir_template == "modules/snapshots/<digest>"
        assert contract.drill_ref == CONTRIBUTOR_DRILL_REF
        shapes = {docs_contract.command_shape(c) for c in contract.documented_commands}
        assert {"new <id>", "check <path>", "check --json <path>", "add <path>", "list"} <= shapes

    def test_a_tampered_copy_of_the_doc_makes_the_comparison_fail(self, tmp_path: Path) -> None:
        """The sensitivity proof the brief asks for: copy the two pages, edit one fenced command
        (`module list` -> `module ls`) and one prose template (12 -> 8 hex digits), and the
        comparison against REAL observed output names both."""
        docs_copy = tmp_path / "docs"
        docs_copy.mkdir()
        for name in ("module-contract.md", "cli-reference.md"):
            (docs_copy / name).write_text((DOCS / name).read_text(encoding="utf-8"), "utf-8")
        page = docs_copy / "module-contract.md"
        page.write_text(
            page.read_text("utf-8").replace("studyloop module list\n", "studyloop module ls\n", 1),
            "utf-8",
        )
        digest = "ab" * 32
        snapshot = f"/x/modules/snapshots/sha256-{digest}"
        observed = docs_contract.ObservedModuleOutputs(
            commands_run=(
                "new my-drills",
                "check /x/my-drills",
                "check --json /x/my-drills",
                "add /x/my-drills",
                "list",
                "remove my-drills",
            ),
            check_finding_lines=("MC017 decks/cluster.json:14: task current-context has no x",),
            check_exit_codes={"conforming": 0, "findings": 1, "not a dir": 2},
            json_report={
                "ok": False,
                "findings": [{"rule_id": "MC017", "message": "m", "path": "p", "line": 14}],
            },
            list_lines=(f"my-drills  0.1.0      {digest[:12]}  {snapshot}",),
            lockfile_entries=(
                {
                    "id": "my-drills",
                    "version": "0.1.0",
                    "digest": f"sha256:{digest}",
                    "snapshot": snapshot,
                },
            ),
            add_stdout=f"installed my-drills 0.1.0 (sha256:{digest})\nsnapshot: {snapshot}\n",
            scaffold_dir=None,
            check_script_stdout="ready\n",
            check_script_exit=0,
        )
        clean = docs_contract.compare_observed(
            docs_contract.load_documented_contract(DOCS), observed
        )
        assert clean == [], clean
        tampered = docs_contract.load_documented_contract(docs_copy)
        mismatches = docs_contract.compare_observed(tampered, observed)
        assert any("ls" in m for m in mismatches), mismatches
        # Help text is the product's, not the page's: tamper the parsed value directly.
        tampered8 = dataclasses.replace(tampered, list_digest_hex=8)
        mismatches = docs_contract.compare_observed(tampered8, observed)
        assert any("8 hex digits" in m for m in mismatches), mismatches


# ---------------------------------------------------------------------------
# Which mentor the personas drive (design.md §6, ruled at U1-review): the harness
# STUDYLOOP_ACC_HARNESS selects when one is selected, the e2e fake agent otherwise.
# ---------------------------------------------------------------------------


class TestHarnessSelection:
    def test_no_selection_means_the_fake_agent_and_the_bundle_says_so(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.delenv("STUDYLOOP_ACC_HARNESS", raising=False)
        world = pw.launch_persona_world(tmp_path / "w", persona="A", budget_s=10, lan=False)
        try:
            assert "STUDYLOOP_TEST_AGENT_CMD" in world.world.env, "no harness selected: fake agent"
            assert world.harness == "fake-agent", "the bundle's harness names the stand-in honestly"
        finally:
            pw.stop_persona_world(world)

    def test_a_selected_harness_runs_without_the_fake_agent(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """U1-review F2: with a harness selected the world must drive THAT binary -- the
        server's environment carries no STUDYLOOP_TEST_AGENT_CMD and its agent options see the
        real binary. Skips by name when the binary is not on this host."""
        harness, binary = "kiro", "kiro-cli"
        if shutil.which(binary) is None:
            pytest.skip(f"{harness}: {binary} not on PATH")
        monkeypatch.setenv("STUDYLOOP_ACC_HARNESS", harness)
        world = pw.launch_persona_world(tmp_path / "w", persona="A", budget_s=10, lan=False)
        try:
            # start_server(world) hands the subprocess exactly world.env (e2e/_env.py).
            assert "STUDYLOOP_TEST_AGENT_CMD" not in world.world.env, (
                "the fake agent was injected although a harness is selected"
            )
            assert world.harness == harness
            with urllib.request.urlopen(
                f"{world.server.base_url}/api/modules/labs", timeout=10
            ) as r:
                agents = {a["value"]: a for a in json.load(r)["agents"]}
            assert agents[harness]["available"] is True, agents[harness]
        finally:
            pw.stop_persona_world(world)


# ---------------------------------------------------------------------------
# Persona A -- AuDHD learner on a tablet over --lan
# ---------------------------------------------------------------------------


@pytest.fixture(scope="class")
def persona_a(
    tmp_path_factory: pytest.TempPathFactory, browser
) -> Generator[PersonaWorld, None, None]:
    root = tmp_path_factory.mktemp("persona-a")
    world = pw.launch_persona_world(root, persona="A", budget_s=PERSONA_A_BUDGET_S, lan=True)
    pw.require_mentor_ready(world)
    world.register_mentor_only(*mentor_only(TASK))
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

    def test_a4a_focus_lands_in_the_terminal(self, persona_a: PersonaWorld, page_a: Page) -> None:
        world, page = persona_a, page_a
        """design.md §6 step 4. Was xfail(strict=True) against the shipped UI (the console mounted
        xterm without focusing it; persona-a-a4a-focus-gap.red.txt is this test's red); fixed
        under the U1-review grant: term.focus() on (re)attach in live-agent-console.js and the
        attached-start path in labs.js."""
        with world.phase("a4a", "focus lands in the terminal after the start"):
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
            # The console re-opens its WebSocket to the SAME running session (its `connected`
            # flag); a re-attach does not replay earlier output and says so in the pane -- a line
            # a full-screen TUI harness redraws over, so it is read only with the fake agent.
            pw.wait_console_connected(page)
            assert pw.console_connected(page)
            if world.fake_mentor:
                pw.wait_for_terminal_text(
                    page, "reattached to your running session", timeout=30_000
                )
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


# ---------------------------------------------------------------------------
# Persona B -- new contributor on a clean machine
# ---------------------------------------------------------------------------


def contributor_shell_env(world: PersonaWorld, tools: dict[str, str]) -> dict[str, str]:
    """A new contributor's shell: the clean HOME of the persona's world, the tools they installed
    (step 1 of docs/contributor-environment.md) and nothing of this developer's StudyLoop.

    ``UV_OFFLINE=1`` turns any network reach into a loud failure rather than a silent download;
    ``UV_CACHE_DIR`` reuses this machine's uv cache (packages, not learner data) -- the only
    concession to "clean machine", recorded in the report."""
    dirs: list[str] = []
    for path in tools.values():
        parent = str(Path(path).parent)
        if parent not in dirs:
            dirs.append(parent)
    home = world.world.home
    return {
        "PATH": os.pathsep.join((*dirs, os.defpath)),
        "HOME": str(home),
        "TMPDIR": str(world.world.tmp_dir),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "XDG_CACHE_HOME": str(home / ".cache"),
        "XDG_STATE_HOME": str(home / ".local" / "state"),
        "LANG": "C",
        "LC_ALL": "C",
        "NO_COLOR": "1",
        "TERM": "dumb",
        "UV_OFFLINE": "1",
        "UV_CACHE_DIR": os.environ.get("UV_CACHE_DIR", str(Path.home() / ".cache" / "uv")),
    }


def shell(
    world: PersonaWorld,
    argv: list[str],
    *,
    env: dict[str, str],
    cwd: Path,
    stdin: str = "",
    timeout: int = 180,
) -> subprocess.CompletedProcess[str]:
    """A contributor's shell command, transcribed into the persona's CLI transcript."""
    started = time.monotonic()
    result = subprocess.run(
        argv,
        env=env,
        cwd=cwd,
        input=stdin,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    world.cli_records.append(
        CliRecord(
            argv=("[shell]", *argv),
            stdin=stdin,
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
            duration_s=time.monotonic() - started,
        )
    )
    return result


def documented_version_line() -> str:
    """The exact `--version` output docs/contributor-environment.md promises."""
    text = (DOCS / "contributor-environment.md").read_text(encoding="utf-8")
    match = re.search(r"`--version` prints `([^`]+)`", text)
    assert match, "contributor-environment.md no longer states the --version output"
    return match.group(1)


@pytest.fixture(scope="class")
def persona_b(
    tmp_path_factory: pytest.TempPathFactory, browser
) -> Generator[PersonaWorld, None, None]:
    root = tmp_path_factory.mktemp("persona-b")
    world = pw.launch_persona_world(root, persona="B", budget_s=PERSONA_B_BUDGET_S, lan=False)
    pw.require_mentor_ready(world)
    world.register_mentor_only(*mentor_only(TASK))
    (world.world.root / "contributor").mkdir(exist_ok=True)
    try:
        pw.open_page(browser, world, viewport=PERSONA_B_VIEWPORT)
        yield world
    finally:
        pw.stop_persona_world(world)


@pytest.fixture()
def page_b(persona_b: PersonaWorld) -> Page:
    assert persona_b.page is not None
    return persona_b.page


class TestPersonaB:
    @staticmethod
    def contributor_dir(world: PersonaWorld) -> Path:
        return world.world.root / "contributor"

    def test_b1_the_documented_uv_setup_commands_succeed_offline(
        self, persona_b: PersonaWorld
    ) -> None:
        """docs/contributor-environment.md steps 1, 3 and 4, run as written in a clean HOME.

        Skipped on purpose, with the reason the brief asks for:
        - `just sync-dev` (`uv sync --all-packages --group dev`): resolves and downloads into
          the clean HOME's empty uv cache -> network. The worktree's own venv, already synced,
          is what `uv run` below exercises.
        - `uv run --group dev playwright install chromium`: a browser download -> network.
        - `uv run --group dev pre-commit install`: writes a git hook into THIS checkout's
          `.git` (a worktree shares its parent's hooks), i.e. into the developer's repository,
          not the scratch env.
        """
        world = persona_b
        with world.phase("b1", "documented uv setup commands, offline"):
            tools = {name: pw.resolve_tool(name) for name in ("uv", "tmux", "node")}
            missing = sorted(name for name, path in tools.items() if path is None)
            if missing:
                pytest.skip(f"contributor tools not installed on this machine: {missing}")
            env = contributor_shell_env(world, {k: v for k, v in tools.items() if v})
            world.facts["b1_skipped"] = {
                "just sync-dev": "network (uv sync into an empty cache)",
                "uv run --group dev playwright install chromium": "network (browser download)",
                "uv run --group dev pre-commit install": "writes into this checkout's .git hooks",
            }
            cwd = REPO_ROOT if not world.flipped("b1") else world.world.home

            # Step 1: every tool answers.
            for argv in (["uv", "--version"], ["tmux", "-V"], ["node", "--version"]):
                result = shell(world, argv, env=env, cwd=cwd)
                assert result.returncode == 0, f"{argv}: {result.stdout}{result.stderr}"
                assert result.stdout.strip(), f"{argv} printed nothing"

            # Step 3: the import proof -- a path under THIS checkout.
            proof = shell(
                world,
                ["uv", "run", "python", "-c", "import studyloop; print(studyloop.__file__)"],
                env=env,
                cwd=cwd,
            )
            assert proof.returncode == 0, proof.stdout + proof.stderr
            printed = Path(proof.stdout.strip())
            assert printed.is_relative_to(REPO_ROOT), (
                f"import resolved outside the checkout: {printed}"
            )
            assert str(printed).endswith("packages/studyloop/src/studyloop/__init__.py"), printed

            # Step 4: the smoke checks, with the documented outputs.
            version = shell(world, ["uv", "run", "studyloop", "--version"], env=env, cwd=cwd)
            assert version.returncode == 0, version.stderr
            assert version.stdout.strip() == documented_version_line(), version.stdout
            setup = shell(
                world, ["uv", "run", "studyloop", "setup"], env=env, cwd=cwd, stdin="\n\n"
            )
            assert setup.returncode == 0, setup.stdout + setup.stderr
            config = world.world.home / ".config" / "studyloop" / "config.yaml"
            assert config.is_file(), "setup wrote no config.yaml under the clean HOME"
            doctor = shell(world, ["uv", "run", "studyloop", "doctor"], env=env, cwd=cwd)
            # Documented: 0 = nothing failed, 1 = a fix is available ("the tool working"),
            # 2 = a core check failed and cannot be fixed. 2 is the only failure.
            assert doctor.returncode in (0, 1), f"doctor exit {doctor.returncode}:\n{doctor.stdout}"
            if doctor.returncode == 1:
                assert "Fix" in doctor.stdout, "exit 1 without the documented Fix column"
            world.facts["b1_doctor_exit"] = doctor.returncode

    def test_b2_module_new_scaffolds_a_module(self, persona_b: PersonaWorld) -> None:
        world = persona_b
        with world.phase("b2", "studyloop module new scaffolds"):
            cwd = self.contributor_dir(world)
            if world.flipped("b2"):  # the opposite state: the destination is already taken
                (cwd / CONTRIBUTOR_MODULE_ID).mkdir()
                (cwd / CONTRIBUTOR_MODULE_ID / "stale.txt").write_text("x", encoding="utf-8")
            result = world.cli("module", "new", CONTRIBUTOR_MODULE_ID, cwd=cwd)
            assert result.returncode == 0, result.stdout + result.stderr
            world.facts["new_stdout"] = result.stdout
            module_dir = cwd / CONTRIBUTOR_MODULE_ID
            assert f"created {module_dir}" in result.stdout, result.stdout
            assert f"next: studyloop module check {module_dir}" in result.stdout, result.stdout
            for rel in (
                "module.yaml",
                "decks/getting-started.json",
                "scripts/check.sh",
                "mentor/brief.md",
                "README.md",
                "LICENSE",
                "CHANGELOG.md",
                "tests/check.sh",
            ):
                assert (module_dir / rel).is_file(), f"the scaffold did not write {rel}"
            world.facts["module_dir"] = str(module_dir)

    def test_b3_module_check_passes_the_scaffold(self, persona_b: PersonaWorld) -> None:
        world = persona_b
        with world.phase("b3", "studyloop module check passes it"):
            module_dir = Path(world.facts["module_dir"])
            if world.flipped("b3"):  # the opposite state: a required file is gone (MC003)
                (module_dir / "LICENSE").unlink()
            checked = world.cli("module", "check", str(module_dir), cwd=module_dir.parent)
            assert checked.returncode == 0, checked.stdout + checked.stderr
            assert "conforms to module contract v1" in checked.stdout, checked.stdout
            as_json = world.cli("module", "check", "--json", str(module_dir))
            assert as_json.returncode == 0, as_json.stdout + as_json.stderr
            assert json.loads(as_json.stdout) == {"ok": True, "findings": []}
            world.facts["check_exit_conforming"] = checked.returncode

    def test_b4_module_add_then_labs_lists_the_contributors_module(
        self, persona_b: PersonaWorld, page_b: Page
    ) -> None:
        world, page = persona_b, page_b
        with world.phase("b4", "lifecycle: add -> one Labs entry"):
            module_dir = Path(world.facts["module_dir"])
            task = deck_task(module_dir, "getting-started", "ready-01")
            world.facts["task"] = task
            world.register_mentor_only(*mentor_only(task))
            page.goto(f"{world.server.base_url}/#today")
            pw.wait_labs_loaded(page)
            assert not pw.labs_entry_visible(page), "Labs must be hidden before the add"
            if not world.flipped("b4"):
                added = world.cli("module", "add", str(module_dir))
                assert added.returncode == 0, added.stdout + added.stderr
                assert f"installed {CONTRIBUTOR_MODULE_ID}" in added.stdout, added.stdout
                world.facts["add_stdout"] = added.stdout
            listed = world.cli("module", "list")
            world.facts["list_stdout"] = listed.stdout
            world.facts["lockfile_entries"] = json.loads(world.lockfile_text() or "{}").get(
                "modules", []
            )
            step_labs_lists_the_installed_module(
                world, page, module_id=CONTRIBUTOR_MODULE_ID, task=task
            )

    def test_b5_start_one_drill_inside_the_single_claimed_session(
        self, persona_b: PersonaWorld, page_b: Page
    ) -> None:
        world, page = persona_b, page_b
        with world.phase("b5", "lifecycle: start inside the one claimed session"):
            step_start_runs_inside_the_one_claimed_session(
                world,
                page,
                drill_ref=CONTRIBUTOR_DRILL_REF,
                task_id="ready-01",
                flipped=world.flipped("b5"),
            )

    def test_b6_escape_cancels_with_clear_recovery_copy(
        self, persona_b: PersonaWorld, page_b: Page
    ) -> None:
        world, page = persona_b, page_b
        with world.phase("b6", "lifecycle: cancel"):
            step_escape_cancels_with_clear_recovery_copy(
                world, page, task_id="ready-01", flipped=world.flipped("b6")
            )

    def test_b7_module_remove_then_labs_gone(self, persona_b: PersonaWorld, page_b: Page) -> None:
        world, page = persona_b, page_b
        with world.phase("b7", "lifecycle: remove -> Labs gone"):
            step_remove_takes_labs_away(
                world, page, module_id=CONTRIBUTOR_MODULE_ID, flipped=world.flipped("b7")
            )

    def test_b8_break_one_rule_read_the_json_failure_repair_and_recheck(
        self, persona_b: PersonaWorld
    ) -> None:
        world = persona_b
        with world.phase("b8", "break one fixture -> MC017 in --json; repair; green"):
            copy = copy_module(K8S_OFFLINE, self.contributor_dir(world) / "k8s-copy")
            clean = world.cli("module", "check", str(copy))
            assert clean.returncode == 0, clean.stdout + clean.stderr
            deck_path = copy / "decks" / "cluster.json"
            original = deck_path.read_text(encoding="utf-8")
            deck = json.loads(original)
            if not world.flipped("b8"):
                del deck["tasks"][0]["verification"]["cleanupCommand"]
                deck_path.write_text(json.dumps(deck, indent=2) + "\n", encoding="utf-8")

            broken = world.cli("module", "check", "--json", str(copy))
            assert broken.returncode == 1, (
                f"exit {broken.returncode}: {broken.stdout}{broken.stderr}"
            )
            as_text = world.cli("module", "check", str(copy))
            world.facts["check_exit_findings"] = as_text.returncode
            world.facts["check_finding_lines"] = [
                line for line in as_text.stdout.splitlines() if line.startswith("MC")
            ]
            report = json.loads(broken.stdout)
            world.facts["check_json_report"] = report
            assert report["ok"] is False
            assert all(set(f) == {"rule_id", "message", "path", "line"} for f in report["findings"])
            rule_ids = {f["rule_id"] for f in report["findings"]}
            # The removed cleanup is MC017; the now-unused `cleanup` capability is MC016.
            assert rule_ids == {"MC017", "MC016"}, rule_ids
            mc017 = next(f for f in report["findings"] if f["rule_id"] == "MC017")
            assert mc017["path"] == "decks/cluster.json", mc017
            assert isinstance(mc017["line"], int) and mc017["line"] > 0, mc017
            lines = deck_path.read_text(encoding="utf-8").splitlines()
            assert '"verification"' in lines[mc017["line"] - 1], (
                f"line {mc017['line']} is {lines[mc017['line'] - 1]!r}"
            )
            assert "cleanupCommand" in mc017["message"], mc017["message"]
            world.facts["b8_json_keys"] = sorted(report)

            deck_path.write_text(original, encoding="utf-8")  # the repair
            repaired = world.cli("module", "check", str(copy))
            assert repaired.returncode == 0, repaired.stdout + repaired.stderr

    def test_b9_the_docs_commands_and_the_observed_output_agree(
        self, persona_b: PersonaWorld
    ) -> None:
        """The observed half of docs/module-contract.md and docs/cli-reference.md (U1-review F7):
        the pages' fenced commands, prose templates and the shipped --help texts are PARSED into
        the documented contract (personas/docs_contract.py) and every observation this persona
        made of `module new`, `module check`, `module list` and `module add` is compared with
        it; the structural half (every fenced `studyloop` line resolves) is test_docs_drift.py's."""
        world = persona_b
        with world.phase("b9", "docs' commands vs observed output"):
            contract = docs_contract.load_documented_contract(DOCS)
            module_dir = Path(world.facts["module_dir"])
            task = world.facts["task"]
            assert task["id"] == contract.drill_ref.rsplit("/", 1)[1], (
                f"the documented drill ref {contract.drill_ref} names a task the scaffold did not "
                f"write ({task['id']})"
            )

            # module-contract.md step 1: the scaffold's check script, run as the module would.
            check_sh = shell(
                world,
                ["/bin/sh", str(module_dir / "scripts" / "check.sh")],
                env={"PATH": os.defpath, "HOME": str(world.world.home)},
                cwd=module_dir,
            )
            # cli-reference.md: "2 not a dir" -- observed here, the other two codes in b3 / b8.
            not_a_dir = world.cli("module", "check", str(module_dir / "module.yaml"))
            assert "is not a directory" in not_a_dir.stderr, not_a_dir.stderr

            list_lines = [line for line in world.facts["list_stdout"].splitlines() if line.strip()]
            if world.flipped("b9"):  # the opposite state: an observation the docs do not describe
                list_lines = [
                    line.replace(line.split()[2], line.split()[2][:8], 1) for line in list_lines
                ]
            observed = docs_contract.ObservedModuleOutputs(
                commands_run=docs_contract.observed_commands(r.argv for r in world.cli_records),
                check_finding_lines=tuple(world.facts["check_finding_lines"]),
                check_exit_codes={
                    "conforming": world.facts["check_exit_conforming"],
                    "findings": world.facts["check_exit_findings"],
                    "not a dir": not_a_dir.returncode,
                },
                json_report=world.facts["check_json_report"],
                list_lines=tuple(list_lines),
                lockfile_entries=tuple(world.facts["lockfile_entries"]),
                add_stdout=world.facts["add_stdout"],
                scaffold_dir=module_dir,
                check_script_stdout=check_sh.stdout,
                check_script_exit=check_sh.returncode,
            )
            mismatches = docs_contract.compare_observed(contract, observed)
            assert mismatches == [], "the docs and the observed output disagree:\n- " + "\n- ".join(
                mismatches
            )
            # The empty-state line once removed (b7) -- observed, and not something the pages
            # describe, so recorded as a fact rather than compared.
            empty = world.cli("module", "list")
            world.facts["list_empty_stdout"] = empty.stdout.strip()
            assert empty.returncode == 0

    def test_b10_the_whole_persona_finished_under_eight_minutes(
        self, persona_b: PersonaWorld, page_b: Page
    ) -> None:
        with persona_b.phase("b10", "wall clock under the 8-minute budget"):
            step_under_budget(persona_b, page_b, flipped=persona_b.flipped("b10"))
