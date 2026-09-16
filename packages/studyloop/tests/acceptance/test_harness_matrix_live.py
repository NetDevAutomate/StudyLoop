"""Harness x surface x transport coverage: the CLI/tmux acceptance matrix.

Extends B1's web-ACP Kiro lane (test_kiro_web_acp_lane.py) to the CLI/tmux
path -- E-B8 says that is where all SIX harnesses actually launch, not just
Kiro-over-web -- so ``STUDYLOOP_ACC=1 just testacc HARNESS=codex`` drives the
REAL harness binary through ``studyloop study --agent codex`` under a
scratch env, with the scripted learner supplying deterministic turns and
B1's deterministic gate/skip machinery. Coverage is published as a MATRIX,
never one green check per harness (council D-19) -- see
docs/acceptance-testing.md's coverage inventory for the tracked exclusions.

ORDER (this lane's brief, council amendment): codex + claude first (E-03
usage), then the rest of CORE over tmux (kiro -- its web-ACP coverage in B1
does not certify the CLI path -- and pi, core since 2026-09-16), then the
PREVIEW harnesses opencode/grok, never a blocker. ``HARNESS_ORDER`` is a literal re-ordering of
``RELEASE_HARNESSES``, not a hand-maintained separate list -- the structural
guard that keeps the two from drifting apart lives in
``tests/test_harness_matrix_live_mechanics.py`` (an UNGATED module, not
behind the ``acceptance`` marker: council D-19/D-26's "matrix, never one
green check" applies to drift guards too -- a guard that only runs under
``STUDYLOOP_ACC=1`` never actually guards CI).

Every live turn is budget-guarded (``harness.drive.PaneDriver``, grok F9): a
per-turn timeout AND a max-turns ceiling, so a runaway real binary can never
hang an acceptance run indefinitely. Pane text is evidence attached to the
per-run bundle (``acceptance/evidence.py``) -- never itself an assertion
target (D-17); validators here stay at the mechanical tier B1's Kiro lane
already establishes (a real session started, real turns got real replies,
the session ended without a crash) rather than DB-row-level
(topic/struggle rows, `session_search` id-set membership) -- that schema
belongs to the session-memory subsystem and its evidence-writer wiring is
tracked as B4's job, same LEFT OUT this lane's brief and B1's Kiro lane both
already name.

AVAILABILITY (per-harness quirks as fixtures, not if/else soup): every
harness gets a named skip when its binary is missing. Only ``kiro`` has a
verified, side-effect-free "authenticated under THIS scratch HOME" probe
(``kiro-cli whoami``, the same check B1's Kiro lane uses) -- the other five
fall back to binary-presence-only, a TRACKED EXCLUSION (see
docs/acceptance-testing.md) rather than a silently weaker check nobody
wrote down. A live run against an unauthenticated real binary still cannot
do real damage: it drives through a scratch HOME with no real credentials
seeded, and PaneDriver's per-turn timeout cuts it off as budget-exhausted
rather than hanging.
"""

from __future__ import annotations

import json
import platform
import secrets
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from studyloop.harnesses import get_harness

_tests_dir = Path(__file__).resolve().parent.parent
if str(_tests_dir) not in sys.path:
    sys.path.insert(0, str(_tests_dir))

from harness.drive import PaneDriver, TurnBudgetExceededError  # noqa: E402
from harness.tmux import TmuxHarness  # noqa: E402

from acceptance.conftest import require_harness  # noqa: E402
from acceptance.evidence import write_evidence_bundle  # noqa: E402
from acceptance.turn_script import load_turn_script  # noqa: E402

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from acceptance.isolation import ScratchEnv

pytestmark = [
    pytest.mark.acceptance,
    pytest.mark.skipif(not shutil.which("tmux"), reason="tmux not installed"),
    # The suite-wide pytest-timeout is 60 s (pyproject.toml), which is LESS
    # than one of this lane's 90 s per-turn budgets: on the first grok run
    # (2026-09-16) pytest-timeout killed the test while PaneDriver was still
    # waiting, so the documented budget-exhausted outcome was unreachable.
    # Three turns + every fixed wait is ~400 s worst case; pinned with
    # headroom by test_harness_matrix_live_mechanics.TestLaneTimeoutBudget.
    pytest.mark.timeout(600),
]

#: Literal re-order of RELEASE_HARNESSES -- see the module docstring's ORDER
#: section. Verified a pure re-ordering (never a hand-drifted separate list)
#: by test_harness_matrix_live_mechanics.py's
#: test_harness_order_is_exactly_release_harnesses_reordered (an UNGATED
#: module -- see that file's module docstring for why this guard must not
#: live behind the acceptance marker).
HARNESS_ORDER: tuple[str, ...] = ("codex", "claude", "kiro", "pi", "opencode", "grok")

#: D-21(2) requires "start -> >=3 scripted turns -> ...". Three free-form
#: turns, not scripted around any particular expected reply (D-17: pane
#: text is evidence, never an assertion target).
SCRIPT = load_turn_script(
    {
        "version": 1,
        "turns": [
            {"prompt": "In one short sentence, what is a Python decorator?"},
            {"prompt": "Thanks. In one short sentence, what is a closure?"},
            {"prompt": "One more: in one short sentence, what is a generator?"},
        ],
    }
)

_MAX_TURNS = len(SCRIPT.turns)
_PER_TURN_TIMEOUT = 90.0


def _kiro_probe(binary: str, env: Mapping[str, str]) -> tuple[bool, str]:
    """Mirrors test_kiro_web_acp_lane.py's ``_kiro_available`` login check.

    Probes ``kiro-cli whoami`` under the SAME scratch env the real launch
    will get -- a real-HOME-authenticated developer machine must not pass
    this probe while the scratch HOME the child actually receives has no
    credentials at all (that gap is exactly what would otherwise turn into
    a 90s hang instead of a named skip)."""
    try:
        result = subprocess.run(
            [binary, "whoami"], capture_output=True, timeout=5, text=True, env=dict(env)
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return False, f"{binary} whoami errored: {exc}"
    if result.returncode != 0:
        detail = result.stderr.strip()[:200] or "whoami exited non-zero"
        return False, f"{binary} not logged in under this scratch HOME ({detail})"
    return True, ""


def _presence_only_probe(binary: str, env: Mapping[str, str]) -> tuple[bool, str]:
    """Fallback for the five harnesses with no verified auth-check probe.

    TRACKED EXCLUSION (docs/acceptance-testing.md): a binary can be present
    and still fail live (missing login, missing quota) -- that failure
    surfaces as a live-run FAILURE via PaneDriver's budget cutoff, not a
    named skip, until each harness gets its own probe."""
    del env
    return True, ""


#: Per-harness availability probes -- a fixture-shaped dict, not an
#: if/elif chain inside the test body (this lane's brief, deliverable 4).
PROBES: dict[str, Callable[[str, Mapping[str, str]], tuple[bool, str]]] = {
    "kiro": _kiro_probe,
    "codex": _presence_only_probe,
    "claude": _presence_only_probe,
    "opencode": _presence_only_probe,
    "pi": _presence_only_probe,
    "grok": _presence_only_probe,
}


def auth_mode_for(harness_name: str, scratch: ScratchEnv) -> str:
    """The ``auth_mode`` the evidence bundle records (council D-21(7)).

    ``real-auth`` when the scratch was built with the opt-in real-harness-auth
    mode (the harness saw its own credentials -- the only mode in which a
    recorded reply can be a model's); ``verified`` for kiro's whoami probe
    under a scrubbed scratch; ``presence-only`` otherwise, which the coverage
    inventory tracks as an exclusion.
    """
    if scratch.real_harness_auth:
        return "real-auth"
    return "verified" if harness_name == "kiro" else "presence-only"


def harness_available(name: str, env: Mapping[str, str]) -> tuple[bool, str]:
    """Named-skip predicate (D-13): report WHICH binary/step is missing.

    Resolves the binary against ``env``'s OWN ``PATH`` -- the same PATH the
    child launch below actually gets -- rather than this test process's
    PATH (review finding, B2 fix round 1): ``build_scratch_child_env``
    preserves PATH today, so the two currently agree, but that agreement is
    an invariant of the scratch-env builder, not of this function, and must
    not silently start depending on which PATH ``shutil.which`` happened to
    default to."""
    harness = get_harness(name)
    binary = shutil.which(harness.binary, path=env.get("PATH"))
    if not binary:
        return False, f"{harness.binary} not on PATH"
    probe = PROBES.get(name, _presence_only_probe)
    return probe(binary, env)


class TestHarnessMatrixLive:
    """One real-binary acceptance lane per RELEASE_HARNESS, council order.

    Parametrized rather than one bespoke test per harness: per-harness
    quirks live in ``PROBES`` above, not duplicated test bodies."""

    @pytest.fixture(autouse=True)
    def _select_harness(self, harness_name: str) -> None:
        """Named-skip BEFORE ``scratch_env`` builds anything (autouse
        fixtures run first within their scope), so
        ``STUDYLOOP_ACC_HARNESS=codex`` never starts a real, possibly
        billed session for a harness that was not asked to run."""
        require_harness(harness_name)

    @pytest.mark.parametrize("harness_name", HARNESS_ORDER)
    def test_cli_tmux_lane_completes_a_full_scripted_lifecycle(
        self,
        harness_name: str,
        scratch_env: ScratchEnv,
        tmp_path: Path,
    ) -> None:
        ok, reason = harness_available(harness_name, scratch_env.env)
        if not ok:
            pytest.skip(f"{harness_name}: {reason}")

        topic = f"Harness Matrix Live: {harness_name}"
        launch = subprocess.run(
            [
                sys.executable,
                "-m",
                "studyloop.cli",
                "study",
                topic,
                "--energy",
                "5",
                "--agent",
                harness_name,
            ],
            capture_output=True,
            text=True,
            env=scratch_env.env,
            timeout=30,
        )

        # `TmuxHarness(env=scratch_env.env)`, NOT a bare `TmuxHarness()`:
        # every tmux invocation this instance makes must resolve the SAME
        # `TMUX_TMPDIR` the child process below actually received, or every
        # `session_exists`/`capture_pane`/`send_keys` call silently talks
        # to the wrong (or no) tmux server (review finding, B2 fix round 1;
        # see `TmuxHarness.__init__`'s docstring and
        # `test_harness_matrix_live_mechanics.py`'s positive control).
        tmux = TmuxHarness(env=scratch_env.env)
        state_file = scratch_env.config_dir / "session-state.json"
        outcome = "errored"
        session_name = ""
        # `driver` stays None if an earlier wait_for (session-state.json,
        # tmux session, pane children) is what fails -- the outer finally
        # below must still write A bundle in that case (review finding, B2
        # fix round 1: previously `write_evidence_bundle` lived in an INNER
        # finally scoped only to the turn loop, so exactly those failures
        # -- the ones findings 1 and 2 guaranteed -- wrote no bundle at all,
        # making the `outcome = "errored"` initialisation above dead code).
        driver: PaneDriver | None = None
        try:
            tmux.wait_for(
                state_file.exists,
                timeout=15,
                msg=(
                    f"{harness_name}: session-state.json "
                    f"(exit={launch.returncode}, stderr={launch.stderr[-500:]!r})"
                ),
            )
            state = json.loads(state_file.read_text())
            session_name = state.get("tmux_session", "")
            assert session_name.startswith("study-"), (
                f"{harness_name}: expected a study-* tmux session, got {session_name!r}"
            )
            tmux.track_session(session_name)
            tmux.wait_for(
                lambda: tmux.session_exists(session_name),
                timeout=15,
                msg=f"{harness_name}: tmux session {session_name}",
            )

            main_pane = state.get("tmux_main_pane")
            assert main_pane, f"{harness_name}: no main pane in session state"
            tmux.wait_for(
                lambda: tmux.pane_has_children(main_pane),
                timeout=20,
                msg=f"{harness_name}: agent process not running in main pane",
            )

            driver = PaneDriver(
                tmux, main_pane, max_turns=_MAX_TURNS, per_turn_timeout=_PER_TURN_TIMEOUT
            )
            for turn in SCRIPT.turns:
                driver.send_turn(turn.prompt)
            outcome = "completed"
        except TurnBudgetExceededError:
            outcome = "budget-exhausted"
            raise
        finally:
            subprocess.run(
                [sys.executable, "-m", "studyloop.cli", "study", "--end"],
                capture_output=True,
                text=True,
                env=scratch_env.env,
                timeout=15,
            )
            if session_name:
                tmux.wait_for(
                    lambda: not tmux.session_exists(session_name),
                    timeout=15,
                    msg=f"{harness_name}: tmux session not destroyed after --end",
                )
            tmux.cleanup()
            write_evidence_bundle(
                tmp_path / "evidence",
                # A random suffix, not just second-granularity time(): two
                # harnesses (or two runs of this same harness) finishing
                # within the same wall-clock second must never collide on a
                # run id -- write_evidence_bundle raises FileExistsError on
                # a collision, from inside THIS finally, which would mask
                # whatever real failure is already in flight.
                run_id=f"{harness_name}-{int(time.time())}-{secrets.token_hex(4)}",
                harness=harness_name,
                actor="scripted",
                outcome=outcome,
                platform=platform.platform(),
                auth_mode=auth_mode_for(harness_name, scratch_env),
                turns=[
                    {"prompt": r.prompt, "pane_output": r.pane_output, "elapsed": r.elapsed}
                    for r in (driver.records if driver is not None else [])
                ],
            )

        final_state = json.loads(state_file.read_text())
        assert final_state.get("mode") == "ended", (
            f"{harness_name}: expected mode='ended', got {final_state.get('mode')!r}"
        )

        # D-21(2): "start -> >=3 scripted turns -> topic logged -> wind-down
        # -> RESUME" -- the lifecycle is not complete at wind-down alone.
        # `studyloop study --resume` rebuilds the (dead, but preserved)
        # session directory; this is the SAME CLI path
        # test_study_integration.py's TestSessionResume already exercises
        # against a stub agent, driven here for real against `harness_name`.
        resume = subprocess.run(
            [sys.executable, "-m", "studyloop.cli", "study", "--resume"],
            capture_output=True,
            text=True,
            env=scratch_env.env,
            timeout=30,
        )
        resumed_session_name = ""
        try:
            tmux.wait_for(
                lambda: json.loads(state_file.read_text()).get("mode") != "ended",
                timeout=15,
                msg=(
                    f"{harness_name}: --resume never moved mode off 'ended' "
                    f"(exit={resume.returncode}, stderr={resume.stderr[-500:]!r})"
                ),
            )
            resumed_state = json.loads(state_file.read_text())
            resumed_session_name = resumed_state.get("tmux_session", "")
            assert resumed_session_name.startswith("study-"), (
                f"{harness_name}: resume produced no study-* tmux session, "
                f"got {resumed_session_name!r}"
            )
            tmux.track_session(resumed_session_name)
            tmux.wait_for(
                lambda: tmux.session_exists(resumed_session_name),
                timeout=15,
                msg=f"{harness_name}: resumed tmux session {resumed_session_name}",
            )
        finally:
            subprocess.run(
                [sys.executable, "-m", "studyloop.cli", "study", "--end"],
                capture_output=True,
                text=True,
                env=scratch_env.env,
                timeout=15,
            )
            if resumed_session_name:
                tmux.wait_for(
                    lambda: not tmux.session_exists(resumed_session_name),
                    timeout=15,
                    msg=f"{harness_name}: resumed tmux session not destroyed after --end",
                )
            tmux.cleanup()

        resumed_final_state = json.loads(state_file.read_text())
        assert resumed_final_state.get("mode") == "ended", (
            f"{harness_name}: expected mode='ended' after the resumed session's own "
            f"--end, got {resumed_final_state.get('mode')!r}"
        )
