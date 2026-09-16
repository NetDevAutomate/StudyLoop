#!/usr/bin/env -S uv run --group dev python
"""Per-harness release evidence for GitHub issue #21, recorded as data.

Runs the five evidence items the issue names for ONE harness, each under a
fresh scratch HOME built by the acceptance tier's own isolation helpers
(``tests/acceptance/isolation.py``), and writes a redacted JSON + Markdown
receipt per item. Nothing here asserts; the receipt is the deliverable and
the tier decision is made from it afterwards.

Items (issue #21 numbering):

1. install -- ``studyloop install agents --tool <h>`` into the scratch HOME,
   then ``studyloop doctor --json`` in the same scratch.
2. launch + 4. live release check -- the harness-matrix live lane
   (``tests/acceptance/test_harness_matrix_live.py``) for that harness only,
   run as a pytest subprocess with ``STUDYLOOP_ACC=1``; its evidence bundle is
   harvested into the receipt directory.
3. export -- ``session-export --<h>-only`` against whatever transcript the
   scratch harness wrote (after one typed prompt in a real session), else the
   exporter's own fixture tests, and the receipt says which.
5. plan-architect -- ``studyloop study --mode plan-architect --agent <h>``
   launched for real (no model turn), persona file checked, then ended.

Every captured line passes through :func:`redact` first: the VALUE of any
environment variable whose NAME is credential-shaped (the same patterns
``studyloop.session.child_env`` scrubs) is replaced by ``<redacted:NAME>``, so
a harness that echoes a secret can never put it in a receipt.

Usage::

    uv run --group dev python scripts/harness-evidence.py pi \
        --receipts-dir docs/architecture/plan-integration/receipts/harness-evidence-2026-09-16

Run ONE harness at a time: the one-session authority and the harnesses' own
config directories are not designed for concurrent runs.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
_TESTS_DIR = REPO_ROOT / "packages" / "studyloop" / "tests"
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

from acceptance.isolation import ScratchEnv, create_scratch_environment, sweep_scratch  # noqa: E402
from harness.tmux import TmuxHarness  # noqa: E402

from studyloop.harnesses import RELEASE_HARNESSES, get_harness  # noqa: E402
from studyloop.session.child_env import (  # noqa: E402
    CHILD_ENV_DENY,
    CHILD_ENV_DENY_PAT,
    CHILD_ENV_DENY_SEGMENT_PAT,
    CHILD_ENV_DENY_SQUASHED,
)

#: Where each harness keeps its own files under a HOME (relative). Used only
#: to list what the install wrote and to find transcripts for the exporter.
HARNESS_HOME_DIRS: dict[str, tuple[str, ...]] = {
    "pi": (".pi",),
    "opencode": (".config/opencode", ".local/share/opencode"),
    "grok": (".grok",),
    "kiro": (".kiro",),
    "codex": (".codex",),
    "claude": (".claude",),
}

#: The one prompt typed into the item-3 session so the harness has a chance to
#: persist a transcript. Under a scratch HOME no harness is authenticated, so
#: this is not a billed turn; if a harness IS authenticated it is one turn.
TRANSCRIPT_PROMPT = "In one short sentence, what is a Python decorator?"

_LANE_TEST = "packages/studyloop/tests/acceptance/test_harness_matrix_live.py"


# --------------------------------------------------------------------------
# Redaction
# --------------------------------------------------------------------------


def _is_credential_name(name: str) -> bool:
    if name in CHILD_ENV_DENY:
        return True
    if CHILD_ENV_DENY_PAT.search(name) or CHILD_ENV_DENY_SEGMENT_PAT.search(name):
        return True
    squashed = name.replace("_", "").lower()
    return any(word in squashed for word in CHILD_ENV_DENY_SQUASHED)


def _secret_values(env: dict[str, str]) -> list[tuple[str, str]]:
    """(value, name) pairs to redact -- longest values first so prefixes never win."""
    pairs = [(v, k) for k, v in env.items() if _is_credential_name(k) and len(v) >= 8]
    pairs.sort(key=lambda p: len(p[0]), reverse=True)
    return pairs


_SECRETS = _secret_values(dict(os.environ))
_GENERIC_SECRET_PAT = re.compile(
    r"(ghp_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9_-]{16,}|Bearer\s+[A-Za-z0-9._~+/=-]{16,})"
)


def redact(text: str) -> str:
    """Replace every known secret value (and common token shapes) in ``text``."""
    for value, name in _SECRETS:
        if value in text:
            text = text.replace(value, f"<redacted:{name}>")
    return _GENERIC_SECRET_PAT.sub("<redacted:token-shaped>", text)


# --------------------------------------------------------------------------
# Command capture
# --------------------------------------------------------------------------


@dataclass
class CommandRecord:
    argv: list[str]
    exit_code: int | None
    stdout: str
    stderr: str
    seconds: float
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def run_recorded(
    argv: list[str],
    *,
    env: dict[str, str],
    cwd: Path | None = None,
    timeout: float = 120,
    note: str = "",
    tail: int = 4000,
) -> CommandRecord:
    started = time.monotonic()
    try:
        done = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            env=env,
            cwd=str(cwd) if cwd else None,
            timeout=timeout,
            check=False,
        )
        code: int | None = done.returncode
        out, err = done.stdout, done.stderr
    except subprocess.TimeoutExpired as exc:
        code = None
        out = (exc.stdout or b"").decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        err = (exc.stderr or b"").decode() if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        note = f"{note} TIMEOUT after {timeout}s".strip()
    return CommandRecord(
        argv=[redact(a) for a in argv],
        exit_code=code,
        stdout=redact(out[-tail:]),
        stderr=redact(err[-tail:]),
        seconds=round(time.monotonic() - started, 2),
        note=note,
    )


# --------------------------------------------------------------------------
# Scratch environment
# --------------------------------------------------------------------------


def build_scratch(
    root: Path, harness: str, *, path_prepend: list[str], real_auth: bool = False
) -> tuple[ScratchEnv, dict[str, str]]:
    """A fresh scratch world plus the env every child command receives.

    ``PATH`` is prepended with ``path_prepend`` so a harness binary resolves to
    a real executable rather than a version-manager shim that needs the REAL
    home to work (mise's shims fail under a scratch HOME on this machine).
    Grok Build additionally gets ``GROK_HOME`` pinned inside the scratch, the
    belt-and-braces to its own ``$HOME``-derived default -- in the scrubbed
    mode only; ``real_auth`` deliberately leaves the harness's real home (and
    so its real ``~/.grok``) in place, see ``isolation.build_real_harness_auth_env``.
    """
    scratch = create_scratch_environment(root, real_harness_auth=real_auth)
    env = dict(scratch.env)
    if path_prepend:
        env["PATH"] = os.pathsep.join([*path_prepend, env.get("PATH", "")])
    if harness == "grok" and not real_auth:
        env["GROK_HOME"] = str(scratch.home / ".grok")
    # The evidence run's own opt-in knobs are never credentials; a harness
    # under test must see the same PATH the recorder resolved its binary on.
    env.setdefault("TERM", "xterm-256color")
    return scratch, env


def list_tree(root: Path, *, max_entries: int = 200) -> list[str]:
    if not root.exists():
        return []
    entries: list[str] = []
    for path in sorted(root.rglob("*")):
        if ".cache" in path.parts or "node_modules" in path.parts:
            continue
        rel = path.relative_to(root)
        kind = "L" if path.is_symlink() else ("D" if path.is_dir() else "F")
        entries.append(f"{kind} {rel}")
        if len(entries) >= max_entries:
            entries.append("... (truncated)")
            break
    return entries


def harness_version(harness: str, env: dict[str, str]) -> CommandRecord:
    binary = get_harness(harness).binary
    resolved = shutil.which(binary, path=env.get("PATH")) or binary
    rec = run_recorded([resolved, "--version"], env=env, timeout=20, note=f"resolved={resolved}")
    return rec


# --------------------------------------------------------------------------
# Items
# --------------------------------------------------------------------------


@dataclass
class ItemResult:
    item: str
    verdict: str  # PASS | FAIL | SKIP | INFO
    decisive: str
    commands: list[dict[str, Any]] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)


def _python() -> str:
    return sys.executable


def item1_install_and_doctor(harness: str, scratch: ScratchEnv, env: dict[str, str]) -> ItemResult:
    py = _python()
    before = {d: list_tree(scratch.home / d) for d in HARNESS_HOME_DIRS.get(harness, ())}
    install = run_recorded(
        [
            py,
            "-m",
            "studyloop.cli",
            "install",
            "agents",
            "--repo-root",
            str(REPO_ROOT),
            "--tool",
            harness,
        ],
        env=env,
        cwd=REPO_ROOT,
        timeout=180,
    )
    after = {d: list_tree(scratch.home / d) for d in HARNESS_HOME_DIRS.get(harness, ())}
    doctor = run_recorded(
        [py, "-m", "studyloop.cli", "doctor", "--json"],
        env=env,
        cwd=REPO_ROOT,
        timeout=180,
        tail=2_000_000,
    )
    relevant: list[dict[str, Any]] = []
    totals: dict[str, int] = {}
    parsed = False
    try:
        report = json.loads(doctor.stdout)
        parsed = True
    except json.JSONDecodeError:
        report = None
    if parsed:
        # The full report is hundreds of checks about the scratch world; keep
        # the receipt readable and put the harness-relevant subset in details.
        doctor.stdout = f"<{len(report) if isinstance(report, list) else '?'} checks; parsed>"
    if isinstance(report, list):
        label = get_harness(harness).label.lower()
        for check in report:
            if not isinstance(check, dict):
                continue
            status = str(check.get("status") or check.get("level") or "").lower()
            totals[status] = totals.get(status, 0) + 1
            name = str(check.get("name") or "")
            message = str(check.get("message") or "").lower()
            if (
                re.search(rf"(^|_){re.escape(harness)}(_|$)", name)
                or message.startswith(f"{harness}:")
                or label in message
            ):
                relevant.append(check)
    written = any(after[d] != before[d] for d in after)
    if install.exit_code == 0 and written:
        verdict = "PASS"
        n_entries = sum(len(v) for v in after.values())
        decisive = f"install exit 0; {n_entries} entries now under scratch harness dirs"
    else:
        verdict = "FAIL"
        decisive = f"install exit {install.exit_code}; wrote={written}"
    if not parsed:
        verdict = "FAIL"
        decisive += "; doctor --json did not return JSON"
    return ItemResult(
        item="1-install-doctor",
        verdict=verdict,
        decisive=decisive,
        commands=[install.as_dict(), doctor.as_dict()],
        details={
            "scratch_harness_dirs_after_install": after,
            "doctor_parsed": parsed,
            "doctor_status_totals": totals,
            "doctor_checks_naming_harness": relevant,
        },
    )


def _wait(pred, *, timeout: float, interval: float = 0.25) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return True
        time.sleep(interval)
    return False


def _wait_for_pane_quiescence(
    tmux: TmuxHarness,
    pane: str,
    *,
    max_seconds: float = 150.0,
    poll: float = 3.0,
    min_seconds: float = 30.0,
    stable_polls: int = 3,
) -> tuple[bool, float]:
    """Wait until the pane stops changing (a reply finished) or the budget runs out.

    Returns (quiescent, seconds_waited). ``stable_polls`` consecutive identical
    captures, after the first change and never before ``min_seconds`` have
    passed, count as quiet. The floor exists because a full-screen TUI
    (OpenCode) can sit visually still for several seconds while its model
    call is in flight -- the 2026-09-16 opencode run ended its session on a
    6 s lull and the assistant row it left behind had no content at all.
    """
    started = time.monotonic()
    previous = tmux.capture_pane(pane, lines=60)
    changed_once = False
    stable = 0
    while time.monotonic() - started < max_seconds:
        time.sleep(poll)
        current = tmux.capture_pane(pane, lines=60)
        if current != previous:
            changed_once = True
            stable = 0
        elif changed_once:
            stable += 1
            if stable >= stable_polls and time.monotonic() - started >= min_seconds:
                return True, round(time.monotonic() - started, 1)
        previous = current
    return False, round(time.monotonic() - started, 1)


def _launch_session(
    harness: str,
    env: dict[str, str],
    scratch: ScratchEnv,
    *,
    topic: str,
    mode: str | None,
    settle_seconds: float,
    typed_prompt: str | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Start a real ``studyloop study`` session, optionally type one prompt, end it."""
    py = _python()
    argv = [py, "-m", "studyloop.cli", "study", topic, "--energy", "5", "--agent", harness]
    if mode:
        argv += ["--mode", mode]
    commands: list[dict[str, Any]] = []
    details: dict[str, Any] = {}
    state_file = scratch.config_dir / "session-state.json"
    tmux = TmuxHarness(env=env)
    launch = run_recorded(argv, env=env, cwd=REPO_ROOT, timeout=45)
    commands.append(launch.as_dict())
    session_name = ""

    def _fresh_state() -> bool:
        # The scratch is reused across items, so an ENDED prior session's state
        # file may already exist: wait for THIS topic in a non-ended state.
        if not state_file.exists():
            return False
        try:
            current = json.loads(state_file.read_text())
        except json.JSONDecodeError:
            return False
        return current.get("topic") == topic and current.get("mode") != "ended"

    try:
        details["state_file_appeared"] = _wait(_fresh_state, timeout=20)
        state: dict[str, Any] = {}
        if details["state_file_appeared"]:
            state = json.loads(state_file.read_text())
        details["state_after_launch"] = {
            k: state.get(k)
            for k in (
                "session_dir",
                "mode",
                "topic",
                "agent",
                "tmux_session",
                "tmux_main_pane",
                "persona_file",
                "persona_hash",
                "session_mode",
                "energy",
            )
        }
        session_name = str(state.get("tmux_session", ""))
        main_pane = state.get("tmux_main_pane")
        if session_name:
            tmux.track_session(session_name)
            details["tmux_session_exists"] = _wait(
                lambda: tmux.session_exists(session_name), timeout=15
            )
        if main_pane:
            details["agent_process_in_pane"] = _wait(
                lambda: tmux.pane_has_children(main_pane), timeout=20
            )
            # A full-screen TUI (grok with seven MCP servers, opencode) can take
            # longer than a fixed settle to draw; a prompt typed into a blank
            # pane is dropped. Wait for the first rendered lines, then settle.
            details["tui_rendered"] = _wait(
                lambda: (
                    len(
                        [
                            ln
                            for ln in tmux.capture_pane(main_pane, lines=60).splitlines()
                            if ln.strip()
                        ]
                    )
                    >= 3
                ),
                timeout=45,
            )
            time.sleep(settle_seconds)
            details["pane_after_settle"] = redact(tmux.capture_pane(main_pane, lines=40))
            if typed_prompt and details.get("agent_process_in_pane"):
                tmux.send_keys(main_pane, typed_prompt, enter=True)
                quiet_for, waited = _wait_for_pane_quiescence(tmux, main_pane)
                details["reply_wait_seconds"] = waited
                details["pane_quiescent"] = quiet_for
                details["pane_after_prompt"] = redact(tmux.capture_pane(main_pane, lines=60))
                # Give the harness a moment to flush its transcript before --end.
                time.sleep(3.0)
        persona_file = state.get("persona_file")
        if persona_file and Path(persona_file).exists():
            text = Path(persona_file).read_text(encoding="utf-8", errors="replace")
            details["persona_file"] = persona_file
            details["persona_first_lines"] = redact("\n".join(text.splitlines()[:3]))
            details["persona_mentions_plan_architect"] = "Study Plan Architect" in text
            details["persona_bytes"] = len(text)
    finally:
        end = run_recorded(
            [py, "-m", "studyloop.cli", "study", "--end"], env=env, cwd=REPO_ROOT, timeout=30
        )
        commands.append(end.as_dict())
        if session_name:
            details["tmux_session_gone_after_end"] = _wait(
                lambda: not tmux.session_exists(session_name), timeout=15
            )
        tmux.cleanup()
        if state_file.exists():
            final = json.loads(state_file.read_text())
            details["final_mode"] = final.get("mode")
    return commands, details


def item5_plan_architect(harness: str, scratch: ScratchEnv, env: dict[str, str]) -> ItemResult:
    commands, details = _launch_session(
        harness,
        env,
        scratch,
        topic=f"Plan Architect Evidence: {harness}",
        mode="plan-architect",
        settle_seconds=4.0,
        typed_prompt=None,
    )
    ok = (
        details.get("state_file_appeared")
        and details.get("tmux_session_exists")
        and details.get("agent_process_in_pane")
        and details.get("persona_mentions_plan_architect")
        and details.get("final_mode") == "ended"
    )
    decisive = (
        f"persona_file={details.get('persona_file')} "
        f"plan-architect={details.get('persona_mentions_plan_architect')} "
        f"agent_in_pane={details.get('agent_process_in_pane')} "
        f"final_mode={details.get('final_mode')}"
    )
    return ItemResult(
        item="5-plan-architect",
        verdict="PASS" if ok else "FAIL",
        decisive=decisive,
        commands=commands,
        details=details,
    )


def _count_sources(db: Path) -> dict[str, int]:
    import sqlite3

    if not db.exists():
        return {}
    conn = sqlite3.connect(db)
    try:
        rows = conn.execute("SELECT source, COUNT(*) FROM sessions GROUP BY source").fetchall()
        return {str(s): int(n) for s, n in rows}
    finally:
        conn.close()


def _rows_for_this_run(db: Path, harness: str, session_dir: str) -> list[dict[str, Any]]:
    """Sessions rows produced by THIS driver run, by the cwd every exporter records.

    Every harness runs with the StudyLoop session dir as its cwd and every
    exporter records that cwd as ``project_path``. The driver's scratch roots
    carry run-unique prefixes (``sl-ev-<harness>-`` for its own sessions,
    ``sl-lane-<harness>-`` for the pytest lane's), so matching on those
    separates tonight's transcripts from everything else a real harness home
    already holds -- including the lane session, whose transcript is the one
    a harness most reliably flushes (three prompts, then ``--end``).
    """
    import sqlite3

    if not db.exists():
        return []
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(sessions)")}
        if "project_path" not in cols:
            return []
        patterns = [f"%sl-ev-{harness}-%", f"%sl-lane-{harness}-%"]
        if session_dir:
            patterns.append(f"%{Path(session_dir).name}%")
        where = " OR ".join("project_path LIKE ?" for _ in patterns)
        rows = conn.execute(
            "SELECT id, source, project_path, created_at, "
            "(SELECT COUNT(*) FROM messages m WHERE m.session_id = sessions.id) AS messages "
            f"FROM sessions WHERE {where}",
            patterns,
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def item3_export(harness: str, scratch: ScratchEnv, env: dict[str, str]) -> ItemResult:
    """Export from a transcript the scratch harness wrote, else fixture tests."""
    py = _python()
    commands, launch_details = _launch_session(
        harness,
        env,
        scratch,
        topic=f"Export Evidence: {harness}",
        mode=None,
        settle_seconds=5.0,
        typed_prompt=TRANSCRIPT_PROMPT,
    )
    transcripts = (
        {"(real harness home: not listed)": []}
        if scratch.real_harness_auth
        else {d: list_tree(scratch.home / d) for d in HARNESS_HOME_DIRS.get(harness, ())}
    )
    db = scratch.home / "evidence-sessions.db"
    export = run_recorded(
        [py, "-m", "agent_session_tools.export_sessions", f"--{harness}-only", "-o", str(db)],
        env=env,
        cwd=REPO_ROOT,
        timeout=180,
    )
    commands.append(export.as_dict())
    counts = _count_sources(db)
    session_dir = str(launch_details.get("state_after_launch", {}).get("session_dir") or "")
    this_session = _rows_for_this_run(db, harness, session_dir)
    details: dict[str, Any] = {
        "launch": launch_details,
        "scratch_harness_dirs_after_session": transcripts,
        "export_db": str(db),
        "rows_by_source": counts,
        "session_dir": session_dir,
        "rows_for_this_run": this_session,
    }
    if export.exit_code == 0 and counts.get(harness, 0) > 0 and this_session:
        return ItemResult(
            item="3-export",
            verdict="PASS",
            decisive=(
                f"live transcript exported: {len(this_session)} sessions row(s) from THIS "
                f"run with source={harness!r} "
                f"({sum(r['messages'] for r in this_session)} messages); rows by source={counts}"
            ),
            commands=commands,
            details=details,
        )
    # No live transcript to export -- fall back to the exporter's own fixture tests, and say so.
    test_file = {
        "pi": "packages/agent-session-tools/tests/test_pi_exporter.py",
        "opencode": "packages/agent-session-tools/tests/test_exporter_opencode.py",
        "grok": "packages/agent-session-tools/tests/test_exporter_grok.py",
    }.get(harness)
    fixture = None
    if test_file:
        fixture = run_recorded(
            [
                py,
                "-m",
                "pytest",
                test_file,
                "packages/agent-session-tools/tests/test_export_cli_sources.py",
                "-q",
                "-p",
                "no:cacheprovider",
            ],
            env={**dict(os.environ), "PYTHONDONTWRITEBYTECODE": "1"},
            cwd=REPO_ROOT,
            timeout=600,
        )
        commands.append(fixture.as_dict())
        details["fixture_tests"] = test_file
    verdict = "PASS-FIXTURE" if fixture is not None and fixture.exit_code == 0 else "FAIL"
    decisive = (
        f"no live transcript under scratch (export exit {export.exit_code}, rows={counts}); "
        f"exporter fixture tests {'passed' if verdict == 'PASS-FIXTURE' else 'FAILED'}: "
        f"{(fixture.stdout.strip().splitlines() or [''])[-1] if fixture else 'n/a'}"
    )
    return ItemResult(
        item="3-export", verdict=verdict, decisive=decisive, commands=commands, details=details
    )


#: Pane fragments that mean "the harness did not talk to a model" -- an
#: interpretation aid for the receipt, never a lane assertion (council D-17).
_NO_MODEL_MARKERS = (
    "No API key found",
    "No models available",
    "Use /login",
    "not logged in",
    "authentication",
    "Unauthorized",
    "credentials",
    "ExpiredToken",
    "AccessDenied",
)


def _audit_turns(turns_path: Path) -> dict[str, Any]:
    """Count turns whose pane shows a no-model marker vs a plausible reply."""
    if not turns_path.exists():
        return {"turns": 0}
    turns = json.loads(turns_path.read_text())
    no_model = 0
    slow = 0
    for turn in turns:
        pane = str(turn.get("pane_output", ""))
        if any(marker.lower() in pane.lower() for marker in _NO_MODEL_MARKERS):
            no_model += 1
        if float(turn.get("elapsed") or 0) >= 1.0:
            slow += 1
    return {
        "turns": len(turns),
        "turns_with_no_model_marker": no_model,
        "turns_over_1s": slow,
        "real_model_reply_plausible": len(turns) > 0 and no_model == 0 and slow == len(turns),
    }


def item24_live_lane(
    harness: str,
    receipts_dir: Path,
    base_env: dict[str, str],
    *,
    actor: str,
    real_auth: bool = False,
) -> ItemResult:
    """Run the harness-matrix live lane for one harness and harvest its bundle."""
    basetemp = Path(tempfile.mkdtemp(prefix=f"sl-lane-{harness}-", dir="/tmp"))
    env = {
        **base_env,
        "STUDYLOOP_ACC": "1",
        "STUDYLOOP_ACC_HARNESS": harness,
        "STUDYLOOP_ACC_ACTOR": actor,
        "STUDYLOOP_ACC_REAL_AUTH": "1" if real_auth else "0",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    argv = [
        _python(),
        "-m",
        "pytest",
        "-m",
        "acceptance",
        _LANE_TEST,
        "-k",
        f"[{harness}]",
        "-q",
        "-rA",
        "-p",
        "no:cacheprovider",
        f"--basetemp={basetemp}",
    ]
    rec = run_recorded(argv, env=env, cwd=REPO_ROOT, timeout=1500, tail=12000)
    bundles: list[dict[str, Any]] = []
    harvest_dir = receipts_dir / f"{harness}{'-real-auth' if real_auth else ''}-lane-evidence"
    for manifest in sorted(basetemp.rglob("evidence/*/manifest.json")):
        run_dir = manifest.parent
        dest = harvest_dir / run_dir.name
        dest.mkdir(parents=True, exist_ok=True)
        for f in run_dir.iterdir():
            if f.is_file():
                (dest / f.name).write_text(
                    redact(f.read_text(encoding="utf-8", errors="replace")), encoding="utf-8"
                )
        bundles.append({"run_dir": str(dest), "manifest": json.loads(manifest.read_text())})
    shutil.rmtree(basetemp, ignore_errors=True)
    summary = ""
    for line in reversed(rec.stdout.splitlines()):
        if re.search(r"\d+ (passed|failed|skipped|error)", line):
            summary = line.strip()
            break
    if rec.exit_code == 0 and "passed" in summary and "skipped" not in summary:
        verdict = "PASS"
    elif "skipped" in summary and "failed" not in summary and "error" not in summary:
        verdict = "SKIP"
    else:
        verdict = "FAIL"
    outcomes = [b["manifest"].get("outcome") for b in bundles]
    reply_audit = [_audit_turns(Path(b["run_dir"]) / "turns.json") for b in bundles]
    decisive = (
        f"pytest exit {rec.exit_code}: {summary or '(no summary line)'}; "
        f"bundle outcome(s)={outcomes}; turn audit={reply_audit}"
    )
    return ItemResult(
        item="2+4-live-lane",
        verdict=verdict,
        decisive=decisive,
        commands=[rec.as_dict()],
        details={
            "bundles": bundles,
            "turn_audit": reply_audit,
            "real_auth": real_auth,
            "actor_requested": actor,
            "note": (
                "The matrix lane drives the LEARNER side with its own 3 scripted prompts "
                "and records actor='scripted' in its bundle regardless of "
                "STUDYLOOP_ACC_ACTOR; the actor value is "
                "validated by the gate but does not add gateway spend to this lane."
            ),
        },
    )


# --------------------------------------------------------------------------
# Receipt rendering
# --------------------------------------------------------------------------


def _fence(text: str, limit: int = 3000) -> str:
    text = text.strip()
    if len(text) > limit:
        text = "... (head truncated)\n" + text[-limit:]
    return "```text\n" + text + "\n```"


def render_markdown(harness: str, meta: dict[str, Any], items: list[ItemResult]) -> str:
    h = get_harness(harness)
    mode = "real-harness-auth" if meta.get("real_auth_for_live_items") else "scrubbed scratch"
    lines = [f"## {h.label} (`{harness}`) — live items in {mode} mode", ""]
    lines.append(
        f"- binary: `{meta['binary_resolved']}` — `--version` → `{meta['binary_version']}`"
    )
    lines.append(
        f"- recorded: {meta['recorded_at']} on {meta['platform']}; "
        f"repo `{meta['repo_sha']}` (dirty={meta['dirty']})"
    )
    lines.append(f"- scratch root: `{meta['scratch_root']}` (swept: {meta['swept']})")
    lines.append("")
    lines.append("| # | Item | Verdict | Decisive line |")
    lines.append("| --- | --- | --- | --- |")
    for it in items:
        lines.append(
            f"| {it.item} | {it.item.split('-', 1)[1]} | **{it.verdict}** | {redact(it.decisive)} |"
        )
    lines.append("")
    for it in items:
        lines.append(f"### {harness} — item {it.item} — {it.verdict}")
        lines.append("")
        for cmd in it.commands:
            lines.append(
                f"`$ {' '.join(cmd['argv'])}` → exit `{cmd['exit_code']}` "
                f"({cmd['seconds']}s){' — ' + cmd['note'] if cmd['note'] else ''}"
            )
            if cmd["stdout"].strip():
                lines.append("")
                lines.append("stdout:")
                lines.append(_fence(cmd["stdout"]))
            if cmd["stderr"].strip():
                lines.append("")
                lines.append("stderr:")
                lines.append(_fence(cmd["stderr"], 1500))
            lines.append("")
        keep = {k: v for k, v in it.details.items() if k not in {"bundles"}}
        lines.append("details:")
        lines.append("```json")
        lines.append(redact(json.dumps(keep, indent=2, default=str))[:6000])
        lines.append("```")
        lines.append("")
    return "\n".join(lines)


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=False
    ).stdout.strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("harness", choices=RELEASE_HARNESSES)
    parser.add_argument("--receipts-dir", type=Path, required=True)
    parser.add_argument(
        "--items", default="1,2,3,5", help="comma list from {1,2,3,5}; 2 also covers 4"
    )
    parser.add_argument("--actor", default="gateway", help="STUDYLOOP_ACC_ACTOR for the live lane")
    parser.add_argument(
        "--path-prepend",
        action="append",
        default=[],
        help="directories placed ahead of PATH for every child (repeatable)",
    )
    parser.add_argument("--keep-scratch", action="store_true", help="do not sweep the scratch HOME")
    parser.add_argument(
        "--real-auth",
        action="store_true",
        help=(
            "items 2/3/5 run in the opt-in real-harness-auth mode (STUDYLOOP_ACC_REAL_AUTH=1): "
            "the harness keeps its real home and credentials, StudyLoop pointers stay scratch. "
            "Item 1 (install) always uses the scrubbed scratch."
        ),
    )
    args = parser.parse_args(argv)

    harness: str = args.harness
    receipts_dir: Path = args.receipts_dir
    receipts_dir.mkdir(parents=True, exist_ok=True)
    wanted = {s.strip() for s in args.items.split(",") if s.strip()}

    root = Path(tempfile.mkdtemp(prefix=f"sl-ev-{harness}-", dir="/tmp"))
    scratch, env = build_scratch(root, harness, path_prepend=args.path_prepend)
    live_scratch, live_env = scratch, env
    if args.real_auth:
        live_root = Path(tempfile.mkdtemp(prefix=f"sl-ev-{harness}-real-", dir="/tmp"))
        live_scratch, live_env = build_scratch(
            live_root, harness, path_prepend=args.path_prepend, real_auth=True
        )
    version = harness_version(harness, env)
    meta: dict[str, Any] = {
        "harness": harness,
        "recorded_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "platform": platform.platform(),
        "repo_sha": git("rev-parse", "--short", "HEAD"),
        "dirty": bool(git("status", "--porcelain")),
        "scratch_root": str(root),
        "binary_resolved": version.note.removeprefix("resolved="),
        "binary_version": (version.stdout.strip() or version.stderr.strip()).splitlines()[-1:]
        or [""],
        "path_prepend": args.path_prepend,
        "grok_home_pinned": env.get("GROK_HOME"),
        "real_auth_for_live_items": args.real_auth,
        "swept": False,
    }
    meta["binary_version"] = meta["binary_version"][0] if meta["binary_version"] else ""

    items: list[ItemResult] = []
    try:
        if "1" in wanted:
            items.append(item1_install_and_doctor(harness, scratch, env))
        if "5" in wanted:
            items.append(item5_plan_architect(harness, live_scratch, live_env))
        if "2" in wanted or "4" in wanted:
            lane_env = dict(os.environ)
            if args.path_prepend:
                lane_env["PATH"] = os.pathsep.join([*args.path_prepend, lane_env.get("PATH", "")])
            items.append(
                item24_live_lane(
                    harness, receipts_dir, lane_env, actor=args.actor, real_auth=args.real_auth
                )
            )
        # Export LAST so the lane's transcript (the one a harness most reliably
        # flushes) is already on disk when the exporter runs.
        if "3" in wanted:
            items.append(item3_export(harness, live_scratch, live_env))
    finally:
        if not args.keep_scratch:
            sweep_scratch(scratch)
            shutil.rmtree(root, ignore_errors=True)
            if live_scratch is not scratch:
                sweep_scratch(live_scratch)
                shutil.rmtree(live_scratch.home.parent, ignore_errors=True)
            meta["swept"] = not root.exists() and not live_scratch.home.exists()

    # Order the table by issue numbering.
    order = {"1-install-doctor": 0, "2+4-live-lane": 1, "3-export": 2, "5-plan-architect": 3}
    items.sort(key=lambda it: order.get(it.item, 9))

    receipt = {"meta": meta, "items": [asdict(it) for it in items]}
    tag = f"{harness}-real-auth" if args.real_auth else harness
    json_path = receipts_dir / f"{tag}.json"
    json_path.write_text(
        redact(json.dumps(receipt, indent=2, default=str)) + "\n", encoding="utf-8"
    )
    md_path = receipts_dir / f"{tag}.md"
    md_path.write_text(render_markdown(harness, meta, items) + "\n", encoding="utf-8")

    print(f"{harness}: " + ", ".join(f"{it.item}={it.verdict}" for it in items))
    print(f"receipt: {json_path}")
    print(f"receipt: {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
