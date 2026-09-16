"""UAT plan journeys (#15, T6.3): the three plan doors, one sign-off, one bundle.

Three cells, each a required sign-off cell under the strict runner
(:mod:`acceptance.uat.strict_runner`, council D-13), run against ONE hermetic
world — one plans directory, one sessions database, one session directory —
shared by every process the journeys start:

``architect_launch``
    The real web UI in a real browser: the Plans view's **Plan with
    architect** button → one ``POST /api/session/start`` with
    ``purpose: "planning"`` → the existing Study Session console, labelled as
    a planning session; the label survives a reload; no plan document exists
    afterwards. The "agent" is the PTY stub every ``test_web_*`` module uses
    (``echo agent-stub-ready; exec cat``), which also copies the persona file
    it was handed into a directory this module owns, so the brief's
    STRUCTURE is evidence — never its wording (council D-16: no simulated
    mentor is graded; none is graded here).

``mcp_lifecycle``
    The real ``studyloop-mcp`` server as a subprocess over stdio, pointed at
    the SAME plans directory and database, driven with the official ``mcp``
    client: the nine plan tools listed, ``create_study_plan`` →
    ``set_study_plan_status active`` → ``evaluate_study_plan record=true``
    (both sinks ``saved``) → ``set_study_plan_milestone`` → the checkpoint
    visible through ``get_study_plan include_history=true``; then the SAME
    plan read back through the web server's ``GET /api/plans/<id>``.

``now_with_active_plan``
    The Today view in the browser, now that a ready active plan exists: the
    one next action carries "Advances plan: <title …>", and ``/api/now`` names
    the plan in the primary's ``plan_refs`` with ``active_plans`` listed —
    plan-aware guidance with tested ranking rules (D-16), observed through
    the product surface rather than the engine.

The last test applies the strict sign-off rule to the recorded outcomes
(zero cells or any skipped/failed required cell → FAIL) and writes the full
evidence bundle (:mod:`acceptance.uat.bundle`) to the durable root — private,
atomic, hash-pinned — plus a redacted summary through the pinned redaction
rules. What this run proves is the three journeys' mechanics through the real
surfaces with a fake agent; it grades no pedagogy (the rubric's criteria are
about a mentor's conversation, and there is no mentor here), so
``per_criterion_scores`` is empty and the arbitration note says so.

Gated behind ``STUDYLOOP_ACC=1`` and ``STUDYLOOP_UAT=1`` like every test in
this tree::

    just testuat "" scripted packages/studyloop/tests/acceptance/uat/test_plan_journeys.py
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

pytest.importorskip("playwright")
pytest.importorskip("fastapi")
pytest.importorskip("uvicorn")
pytest.importorskip("mcp")

# tests/acceptance/uat/test_plan_journeys.py -> tests/
_tests_dir = Path(__file__).resolve().parents[2]
if str(_tests_dir) not in sys.path:
    sys.path.insert(0, str(_tests_dir))

from _helpers import run_async  # noqa: E402
from _playwright_helpers import (  # noqa: E402
    _isolated_child_env,
    auth_context_fixture_factory,
    effective_credentials,
    start_web_server,
)
from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402

from acceptance.uat.bundle import (  # noqa: E402
    ManifestFields,
    RunCounts,
    resolve_durable_root,
    write_bundle,
)
from acceptance.uat.redaction import load_redaction_rules, redact_summary  # noqa: E402
from acceptance.uat.rubric import load_rubric  # noqa: E402
from acceptance.uat.strict_runner import CellOutcome, evaluate_signoff  # noqa: E402
from studyloop.mcp.inventory import PLAN_TOOL_NAMES  # noqa: E402

if TYPE_CHECKING:
    from collections.abc import Generator, Iterator

    from playwright.sync_api import BrowserContext, Page

pytestmark = [pytest.mark.acceptance, pytest.mark.uat, pytest.mark.timeout(240)]

#: Distinct from every other fixed port (tests/test_port_uniqueness.py).
WEB_PORT = 18627
BASE = f"http://127.0.0.1:{WEB_PORT}"

REQUIRED_CELLS = ("architect_launch", "mcp_lifecycle", "now_with_active_plan")

PLAN_ID = "sql-windows"
PLAN_TITLE = "SQL Windows"
ANSWERS: dict[str, object] = {
    "why": "Ship analytics queries without help",
    "success": ["Write a RANK() query unaided"],
    "topics": ["sql"],
    "milestones": [
        {"title": "OVER clause", "concepts": ["window function"]},
        {"title": "RANK vs DENSE_RANK", "concepts": ["rank"]},
    ],
}

#: Persona section headings whose presence proves the brief's STRUCTURE.
BRIEF_STRUCTURE = (
    "## Planning brief",
    "### Interview",
    "### Evidence from the learner's history",
    "### Existing plans",
    "## Tooling",
)

#: Outcomes and evidence accumulate across the cells; the sign-off test reads them.
RESULTS: dict[str, CellOutcome] = {}
EVIDENCE: dict[str, bytes] = {}


# ---------------------------------------------------------------------------
# One world, one web server, one MCP environment
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def world() -> Generator[dict[str, Path], None, None]:
    root = Path(tempfile.mkdtemp(prefix="studyloop-uat-plan-journeys-"))
    dirs = {
        "root": root,
        "plans": root / "study-plans",
        "sessions": root / "session-dir",
        "personas": root / "personas-seen",
        "db": root / "sessions.db",
    }
    for key, path in dirs.items():
        if key != "db":
            path.mkdir(parents=True, exist_ok=True)
    try:
        yield dirs
    finally:
        # The durable evidence lives in the tier's private bundle, not here;
        # ``mkdtemp`` leaves this world behind unless we remove it (review 5,
        # GPT F13: "no temporary artifacts remain" needs a cleanup step).
        shutil.rmtree(root, ignore_errors=True)


def _shared_env(world: dict[str, Path]) -> dict[str, str]:
    """The keys BOTH children must agree on for the journeys to meet."""
    return {
        "STUDYLOOP_PLANS_DIR": str(world["plans"]),
        "STUDYLOOP_DB": str(world["db"]),
    }


@pytest.fixture(scope="module")
def web_server(world: dict[str, Path]):
    agent_cmd = (
        f'cp "{{persona_file}}" "{world["personas"]}/$(date +%s%N).md"; '
        "echo agent-stub-ready; exec cat"
    )
    proc = start_web_server(
        WEB_PORT,
        extra_env={
            **_shared_env(world),
            "STUDYLOOP_TEST_AGENT_CMD": agent_cmd,
            "STUDYLOOP_SESSION_DIR": str(world["sessions"]),
        },
    )
    try:
        yield proc
    finally:
        _end_session_over_http()
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
            proc.wait(timeout=5)


@pytest.fixture(scope="module")
def mcp_env(world: dict[str, Path]) -> dict[str, str]:
    """A hermetic environment for the stdio server, sharing only the plans
    directory and the database with the web server."""
    return _isolated_child_env(_shared_env(world))


@pytest.fixture(scope="module")
def mcp_transcript(web_server, mcp_env: dict[str, str]) -> dict[str, Any]:
    """Run the MCP lifecycle once for the module, on the suite's background loop.

    A fixture rather than a step inside one test because pytest groups the
    browser-parametrised tests (``[chromium]``) together and would otherwise
    run the Today cell before the MCP cell had created the plan it reads. Any
    failure here surfaces as an ERROR on both dependent cells, which the
    strict runner then reports as "never ran" — a fail, never a pass.
    """
    _ = web_server
    return run_async(_mcp_lifecycle(mcp_env))


auth_context = auth_context_fixture_factory()


@pytest.fixture()
def page(web_server, auth_context: BrowserContext) -> Generator[Page, None, None]:
    _ = web_server
    page = auth_context.new_page()
    try:
        yield page
    finally:
        page.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _http(path: str, method: str = "GET") -> Any:
    user, password = effective_credentials()
    req = urllib.request.Request(f"{BASE}{path}", method=method)
    if password:
        import base64

        creds = base64.b64encode(f"{user}:{password}".encode()).decode()
        req.add_header("Authorization", f"Basic {creds}")
    with urllib.request.urlopen(req, timeout=10) as resp:
        raw = resp.read()
    return json.loads(raw) if raw else {}


def _end_session_over_http() -> None:
    with contextlib.suppress(Exception):
        _http("/api/session/end", method="POST")


@contextlib.contextmanager
def _cell(name: str) -> Iterator[None]:
    """Record the cell's outcome for the strict runner; a failure stays a failure."""
    try:
        yield
    except BaseException:
        RESULTS[name] = CellOutcome.FAILED
        raise
    RESULTS[name] = CellOutcome.PASSED


def _evidence(name: str, payload: Any) -> None:
    EVIDENCE[name] = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _goto_plans(page: Page) -> None:
    page.goto(f"{BASE}/")
    page.wait_for_load_state("domcontentloaded")
    page.wait_for_function("() => !!window.Alpine", timeout=5000)
    page.evaluate("() => window.Alpine.store('nav').go('study-plans')")
    page.wait_for_function(
        "() => window.Alpine.store('plans') && window.Alpine.store('plans').initDone === true",
        timeout=8000,
    )
    page.locator('[data-testid="plan-architect"]').wait_for(state="visible", timeout=8000)
    # The Plans-view door goes through the Study Session timer's one start path,
    # which refuses (with the picker's own hint) until the picker has resolved an
    # agent. Wait for that resolution as a learner would see the picker fill in;
    # a click before it is a structured refusal, not a launch.
    page.wait_for_function(
        """() => {
          const root = document.querySelector('[x-data="sessionTimer()"]');
          if (!root) return false;
          const d = window.Alpine.$data(root);
          return !!(d && d.agent);
        }""",
        timeout=15000,
    )


def _wait_for_console(page: Page) -> None:
    page.wait_for_function("() => window.location.hash === '#study-session'", timeout=10000)
    page.wait_for_function(
        """() => {
          const selector = '.agent-console[x-data="liveAgentConsole()"]';
          return [...document.querySelectorAll(selector)].some((el) => {
            const d = window.Alpine.$data(el);
            return d && d.terminalMode === 'xterm' && d.connected === true;
          });
        }""",
        timeout=20000,
    )


def _visible_purpose_labels(page: Page) -> list[str]:
    return page.evaluate(
        """() => [...document.querySelectorAll('[data-testid="console-purpose-label"]')]
             .filter((el) => el.offsetParent !== null
                             && window.getComputedStyle(el).display !== 'none')
             .map((el) => el.textContent.trim())"""
    )


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=_tests_dir.parents[1], capture_output=True, text=True, check=True
    ).stdout.strip()


def _structured(result) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    assert not result.isError, result
    if getattr(result, "structuredContent", None):
        return dict(result.structuredContent)
    return json.loads(result.content[0].text)


# ---------------------------------------------------------------------------
# The cells
# ---------------------------------------------------------------------------


class TestPlanJourneys:
    def test_architect_launch(self, page: Page, world: dict[str, Path]) -> None:
        with _cell("architect_launch"):
            plans_before = sorted(p.name for p in world["plans"].glob("*.md"))
            _goto_plans(page)
            posts: list[dict[str, Any]] = []

            def _on_response(response) -> None:  # type: ignore[no-untyped-def]
                request = response.request
                if request.method == "POST" and request.url.endswith("/api/session/start"):
                    posts.append(
                        {"body": json.loads(request.post_data or "{}"), "status": response.status}
                    )

            page.on("response", _on_response)
            page.locator('[data-testid="plan-architect-subject"]').fill("SQL window functions")
            with page.expect_response(
                lambda r: r.request.method == "POST" and r.url.endswith("/api/session/start"),
                timeout=20000,
            ):
                page.get_by_role("button", name="Plan with architect").click()
            _wait_for_console(page)
            page.wait_for_timeout(600)
            page.remove_listener("response", _on_response)

            assert len(posts) == 1, posts
            assert posts[0]["status"] == 201 and posts[0]["body"]["purpose"] == "planning"
            labels = _visible_purpose_labels(page)
            assert labels and all("planning" in label.lower() for label in labels), labels

            # Reload: the label is derived from persisted state, not the click.
            page.reload()
            page.wait_for_load_state("domcontentloaded")
            page.wait_for_function("() => !!window.Alpine", timeout=5000)
            state = _http("/api/session/state")
            assert state["purpose"] == "planning"
            assert state["topic"] == "SQL window functions"
            assert "plan_id" not in state

            # The persona the architect was handed has the brief's structure.
            seen = sorted(world["personas"].glob("*.md"))
            assert len(seen) == 1, seen
            persona = seen[0].read_text(encoding="utf-8")
            positions = [persona.find(heading) for heading in BRIEF_STRUCTURE]
            assert all(p >= 0 for p in positions), dict(
                zip(BRIEF_STRUCTURE, positions, strict=True)
            )
            assert positions == sorted(positions), "brief sections out of order"
            assert persona.count("## Planning brief") == 1

            # The click created nothing: the plan documents are what they were.
            plans_after = sorted(p.name for p in world["plans"].glob("*.md"))
            assert plans_after == plans_before, (plans_before, plans_after)
            assert sorted(row["plan_id"] for row in _http("/api/plans")["plans"]) == [
                Path(name).stem for name in plans_before
            ]

            EVIDENCE["architect_launch/screenshot.png"] = page.screenshot()
            _evidence(
                "architect_launch/evidence.json",
                {
                    "post": posts[0],
                    "purpose_labels": labels,
                    "session_state_after_reload": state,
                    "brief_structure_positions": dict(zip(BRIEF_STRUCTURE, positions, strict=True)),
                    "plans_before_click": plans_before,
                    "plans_after_click": plans_after,
                },
            )
            _end_session_over_http()

    def test_mcp_lifecycle(self, mcp_transcript: dict[str, Any], world: dict[str, Path]) -> None:
        with _cell("mcp_lifecycle"):
            transcript = mcp_transcript
            assert set(PLAN_TOOL_NAMES) <= set(transcript["tools_listed"])
            assert transcript["created"]["plan"]["status"] == "draft"
            assert transcript["created"]["readiness"]["ready"] is True
            assert transcript["activated"]["plan"]["status"] == "active"
            recorded = transcript["recorded"]
            assert recorded["db_write"] == "saved" and recorded["document_write"] == "saved"
            assert recorded["recording_complete"] is True
            assert transcript["milestone"]["milestones"][0]["done"] is True
            assert len(transcript["history"]["checkpoints"]) == 1

            # The same plan, through the web server: one store, one seam.
            detail = _http(f"/api/plans/{PLAN_ID}")
            assert detail["plan"]["status"] == "active"
            assert detail["plan"]["milestone_done"] == 1
            document = (world["plans"] / f"{PLAN_ID}.md").read_text(encoding="utf-8")
            assert "- [x] **OVER clause**" in document
            assert "- [ ] **RANK vs DENSE_RANK**" in document

            _evidence(
                "mcp_lifecycle/transcript.json",
                {**transcript, "web_detail": detail},
            )
            EVIDENCE["mcp_lifecycle/plan-document.md"] = document.encode("utf-8")

    def test_now_with_active_plan(self, page: Page, mcp_transcript: dict[str, Any]) -> None:
        assert mcp_transcript["activated"]["plan"]["status"] == "active"
        with _cell("now_with_active_plan"):
            page.goto(f"{BASE}/")
            page.wait_for_load_state("domcontentloaded")
            page.wait_for_function("() => !!window.Alpine", timeout=5000)
            page.evaluate("() => window.Alpine.store('nav').go('today')")
            card = page.locator(".today-card:not(.today-starter)")
            card.wait_for(state="visible", timeout=10000)
            plan_line = page.locator(".today-plan")
            plan_line.wait_for(state="visible", timeout=10000)
            label = plan_line.inner_text()
            assert PLAN_TITLE in label, label

            now = _http("/api/now")
            assert now["starter"] is False
            assert [p["plan_id"] for p in now["active_plans"]] == [PLAN_ID]
            refs = now["primary"]["plan_refs"]
            assert refs and refs[0]["plan_id"] == PLAN_ID, now["primary"]
            # Milestone 0 is done, so the plan's next milestone is index 1.
            assert refs[0]["milestone_index"] == 1
            assert now["primary"]["source"].startswith(f"study_plan:{PLAN_ID}:")

            EVIDENCE["now_with_active_plan/screenshot.png"] = page.screenshot()
            _evidence(
                "now_with_active_plan/evidence.json",
                {"today_card_plan_line": label, "now": now},
            )

    def test_signoff_and_evidence_bundle(self, world: dict[str, Path]) -> None:
        """Strict sign-off over the three cells, then the bundle and its redacted summary."""
        verdict = evaluate_signoff(required_cells=REQUIRED_CELLS, results=RESULTS)
        assert verdict.passed, verdict.reasons

        rubric = load_rubric()
        rules = load_redaction_rules()
        repo_sha = _git("rev-parse", "--short", "HEAD")
        dirty = bool(_git("status", "--porcelain"))
        run_at = datetime.now(UTC)
        run_id = f"uat-plan-journeys-{run_at:%Y%m%d-%H%M%S}-{repo_sha}"
        counts = RunCounts(
            passed=sum(1 for o in RESULTS.values() if o is CellOutcome.PASSED),
            skipped=sum(1 for o in RESULTS.values() if o is CellOutcome.SKIPPED),
            failed=sum(1 for o in RESULTS.values() if o is CellOutcome.FAILED),
        )
        fields = ManifestFields(
            run_id=run_id,
            date=run_at.isoformat(timespec="seconds"),
            repo_sha=repo_sha,
            dirty=dirty,
            harness="fake-agent",
            harness_version=None,
            actor_backend="scripted",
            actor_model=None,
            platform=sys.platform,
            rubric_version=str(rubric.version),
            rubric_hash=rubric.content_hash,
            counts=counts,
        )
        run_dir = resolve_durable_root(real_env=os.environ, run_id=run_id)
        files = dict(EVIDENCE)
        files["cells.json"] = (
            json.dumps({name: str(outcome) for name, outcome in RESULTS.items()}, indent=2) + "\n"
        ).encode("utf-8")
        manifest_path = write_bundle(run_dir, fields, files=files)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["counts"] == counts.as_dict()
        for name in files:
            assert name in manifest["file_inventory"]

        summary = redact_summary(
            {
                "run_id": run_id,
                "date": fields.date,
                "repo_sha": repo_sha,
                "harness": "fake-agent",
                "harness_version": None,
                "actor_backend": "scripted",
                "actor_model": None,
                "rubric_version": rubric.version,
                "rubric_hash": rubric.content_hash,
                "journeys": {name: str(outcome) for name, outcome in RESULTS.items()},
                "per_criterion_scores": {},
                "arbitration_note": (
                    "Mechanics sign-off only: the three plan journeys passed through the "
                    "real web UI, the real stdio MCP server and the real now engine with a "
                    "fake (stub) agent. No mentor conversation took place, so no rubric "
                    "criterion was graded and no council seat was consulted; the rubric "
                    "version and hash are recorded so a graded run can cite the same document."
                ),
                "private_bundle_digest": "sha256:"
                + hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
                # Deliberately outside the allowlist; must be dropped by the rules.
                "absolute_bundle_path": str(run_dir),
            },
            rules,
        )
        assert "absolute_bundle_path" not in summary
        (run_dir / "redacted-summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(f"\nUAT plan-journeys bundle: {run_dir}")


async def _mcp_lifecycle(env: dict[str, str]) -> dict[str, Any]:
    """The MCP door, over the real stdio transport, in lifecycle order."""
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "studyloop.mcp.server"], env=env
    )
    transcript: dict[str, Any] = {}
    async with (
        stdio_client(params) as (read, write),
        ClientSession(read, write) as session,
    ):
        init = await session.initialize()
        transcript["server"] = init.serverInfo.name
        tools = await session.list_tools()
        transcript["tools_listed"] = sorted(t.name for t in tools.tools)
        transcript["created"] = _structured(
            await session.call_tool(
                "create_study_plan",
                {"title": PLAN_TITLE, "answers": ANSWERS, "plan_id": PLAN_ID},
            )
        )
        transcript["activated"] = _structured(
            await session.call_tool(
                "set_study_plan_status", {"plan_id": PLAN_ID, "status": "active"}
            )
        )
        transcript["recorded"] = _structured(
            await session.call_tool(
                "evaluate_study_plan", {"plan_id": PLAN_ID, "phase": "start", "record": True}
            )
        )
        transcript["milestone"] = _structured(
            await session.call_tool(
                "set_study_plan_milestone", {"plan_id": PLAN_ID, "index": 0, "done": True}
            )
        )
        transcript["history"] = _structured(
            await session.call_tool("get_study_plan", {"plan_id": PLAN_ID, "include_history": True})
        )
    return transcript
