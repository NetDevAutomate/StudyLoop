"""CLI surface coverage — the learner's other front door, walked for real.

The CLI is half of StudyLoop's product surface, and the mandatory coverage gate
(``tests/test_e2e_coverage_gate.py``) flagged these commands as never invoked by
any test. Each is exercised as a subprocess against an **isolated config** (temp
vault + temp session DB), so the assertions are about real behaviour rather than
``--help`` text.

Two kinds of assertion appear here, and the difference is deliberate:

* **Behavioural** — the command changes state or reports state, and the test
  asserts the change (``backlog add`` → the topic appears in ``backlog list``).
* **Graceful-degradation** — the command needs an external service the learner
  may not have (NotebookLM, a provider). The user-visible contract is then "a
  clear message and a non-zero exit", never a traceback. That is asserted
  explicitly: a Python traceback in the output fails the test.

Run:  cd packages/studyloop && uv run pytest tests/e2e/test_cli_surface.py -m e2e
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_tests_dir = str(Path(__file__).resolve().parent.parent)
if _tests_dir not in sys.path:
    sys.path.insert(0, _tests_dir)

from e2e._env import STUDY_TOPIC, build_test_world  # noqa: E402
from e2e._env import TestWorld as E2ETestWorld  # noqa: E402

pytestmark = [pytest.mark.e2e]

TRACEBACK_MARKERS = ("Traceback (most recent call last)", "\nTypeError", "\nAttributeError")


class Cli:
    """Runs ``studyloop <args>`` in a process bound to an isolated config."""

    def __init__(self, world: E2ETestWorld) -> None:
        self.root = world.root
        self.config = world.config
        self.vault = world.vault
        self.env = dict(world.env)

    def run(self, *args: str, timeout: int = 120) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "studyloop.cli", *args],
            capture_output=True,
            text=True,
            env=self.env,
            timeout=timeout,
            check=False,
        )

    def ok(self, *args: str, timeout: int = 120) -> str:
        """Run and require a clean exit; returns combined output."""
        proc = self.run(*args, timeout=timeout)
        out = proc.stdout + proc.stderr
        assert proc.returncode == 0, f"`studyloop {' '.join(args)}` failed:\n{out}"
        return out

    def graceful(self, *args: str, timeout: int = 120) -> str:
        """Run a command that needs an external service; require no traceback."""
        proc = self.run(*args, timeout=timeout)
        out = proc.stdout + proc.stderr
        for marker in TRACEBACK_MARKERS:
            assert marker not in out, (
                f"`studyloop {' '.join(args)}` crashed with a traceback instead of "
                f"reporting a missing dependency to the learner:\n{out}"
            )
        assert out.strip(), f"`studyloop {' '.join(args)}` said nothing at all"
        return out


@pytest.fixture(scope="module")
def cli(tmp_path_factory) -> Cli:
    root = tmp_path_factory.mktemp("cli-surface")
    return Cli(build_test_world(root, port=0))


# ---------------------------------------------------------------------------
# Backlog — the AuDHD parking-lot workflow from the terminal
# ---------------------------------------------------------------------------


def test_backlog_add_list_resolve_roundtrip(cli: Cli) -> None:
    """A topic added on the CLI is listed, then disappears once resolved."""
    added = cli.ok("backlog", "add", "Why does functools.wraps matter?", "--tech", "Python")
    listed = cli.ok("backlog", "list")
    assert "functools.wraps" in listed, f"added topic is not listed:\n{listed}"

    # The id is echoed by add (e.g. "#12") or discoverable from list output.
    import re

    ids = re.findall(r"#(\d+)", added + listed)
    assert ids, f"no topic id in add/list output:\n{added}\n{listed}"
    topic_id = ids[0]

    cli.ok("backlog", "resolve", topic_id)
    after = cli.ok("backlog", "list")
    assert "functools.wraps" not in after, f"resolved topic is still in the pending list:\n{after}"


def test_backlog_suggest_ranks_without_data(cli: Cli) -> None:
    """`backlog suggest` degrades to a helpful message on an empty backlog."""
    out = cli.ok("backlog", "suggest", "--limit", "3")
    assert out.strip(), "suggest printed nothing"


def test_backlog_list_filters_by_tech(cli: Cli) -> None:
    """The --tech filter actually filters."""
    cli.ok("backlog", "add", "Window functions vs GROUP BY", "--tech", "SQL")
    sql_only = cli.ok("backlog", "list", "--tech", "SQL")
    assert "Window functions" in sql_only
    python_only = cli.ok("backlog", "list", "--tech", "Python")
    assert "Window functions" not in python_only, (
        f"--tech Python returned a SQL topic:\n{python_only}"
    )


# ---------------------------------------------------------------------------
# Active-learning commands
# ---------------------------------------------------------------------------


def test_chat_note_builds_a_socratic_context_pack(cli: Cli) -> None:
    """`chat-note` turns a real note into a machine-readable prompt pack."""
    # The note must live inside a configured vault root — chat-note refuses
    # arbitrary paths on purpose (it will not read files outside the study
    # vault), so the fixture writes into the temp vault the config points at.
    note = cli.vault / "StudyLoopTest" / "Python_Deep_Dive" / "study-notes" / "chat-note.md"
    note.write_text(
        "# Python Decorators\n\n"
        "A decorator wraps a function. `functools.wraps` keeps the metadata.\n\n"
        "```mermaid\nflowchart LR\n  a-->b\n```\n",
        encoding="utf-8",
    )
    out = cli.ok("chat-note", str(note), "--mode", "recall", "--json")
    start = out.find("{")
    assert start != -1, f"--json produced no JSON object:\n{out}"
    pack = json.loads(out[start : out.rindex("}") + 1])
    assert pack, "empty context pack"
    blob = json.dumps(pack).lower()
    assert "decorator" in blob, f"context pack is not about the note's topic: {pack}"

    # The diagram mode must produce a different pack, not the same one.
    diagram = cli.ok("chat-note", str(note), "--mode", "diagram", "--json")
    assert diagram != out, "--mode diagram produced the same pack as --mode recall"


def test_chat_note_refuses_a_note_outside_the_vault(cli: Cli) -> None:
    """Reading arbitrary paths is refused with a message, not a traceback.

    The guard matters: ``chat-note`` takes a path from the user and feeds the
    file to an agent, so "any path on disk" would be an exfiltration surface.
    """
    outside = cli.root / "outside-note.md"
    outside.write_text("# Secret\n\nnot in the vault\n", encoding="utf-8")
    proc = cli.run("chat-note", str(outside))
    assert proc.returncode != 0, "a note outside the vault was accepted"
    out = proc.stdout + proc.stderr
    for marker in TRACEBACK_MARKERS:
        assert marker not in out, f"the guard crashed instead of reporting:\n{out}"
    assert "vault" in out.lower() or "outside" in out.lower(), out


def test_practice_verify_records_an_attempt(cli: Cli) -> None:
    """`practice verify` grades a real task deck and records the attempt."""
    deck = cli.root / "decorators-practice.json"
    deck.write_text(
        json.dumps(
            {
                "title": "Python Decorators practice",
                "tasks": [
                    {
                        "taskType": "build",
                        "prompt": "Write a @timed decorator that preserves metadata.",
                        "setup": "",
                        "successCriteria": [
                            "uses functools.wraps",
                            "returns the wrapper",
                        ],
                        "hint": "Start from def timed(func):",
                        "expectedLearningOutcome": (
                            "Can write a metadata-preserving decorator unaided."
                        ),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    out = cli.ok(
        "practice",
        "verify",
        str(deck),
        "--task",
        "1",
        "--notes",
        "Wrote @timed with functools.wraps and returned wrapper",
        "--json",
    )
    start = out.find("{")
    assert start != -1, f"--json produced no JSON object:\n{out}"
    attempt = json.loads(out[start : out.rindex("}") + 1])
    assert attempt, "empty attempt record"

    # An out-of-range task index must be rejected, not silently recorded.
    bad = cli.run("practice", "verify", str(deck), "--task", "9")
    assert bad.returncode != 0, "an invalid task index exited 0"


def test_recap_today_reports_the_four_slots(cli: Cli) -> None:
    """`recap today --json` returns the win / repair / due / next structure."""
    out = cli.ok("recap", "today", "--json")
    start = out.find("{")
    assert start != -1, f"--json produced no JSON object:\n{out}"
    recap = json.loads(out[start : out.rindex("}") + 1])
    # The AuDHD contract is four slots, present even when empty — an absent key
    # would make the caller branch on missing data instead of "nothing yet".
    for key in ("win", "repair", "due", "next"):
        assert any(key in k for k in recap), f"recap has no {key!r} slot: {list(recap)}"


def test_mastery_weak_links_reports_for_a_topic(cli: Cli) -> None:
    """`mastery weak-links --topic` answers for a topic with no evidence yet."""
    out = cli.ok("mastery", "weak-links", "--topic", STUDY_TOPIC)
    assert out.strip(), "weak-links printed nothing"
    missing = cli.run("mastery", "weak-links")
    assert missing.returncode != 0, "--topic is documented as required but was optional"


def test_session_effectiveness_reports_per_persona(cli: Cli) -> None:
    """`session effectiveness` degrades cleanly with no recorded sessions."""
    out = cli.ok("session", "effectiveness")
    assert out.strip(), "effectiveness printed nothing"


def test_focus_apply_dry_run_previews_without_moving_data(cli: Cli) -> None:
    """`focus set` then `focus apply --dry-run` previews without moving data.

    Order matters: `focus apply` with no saved focus exits non-zero with
    "nothing to apply", which is the documented behaviour — so the test walks
    the real workflow (set, then apply) and asserts BOTH legs.
    """
    empty = cli.run("focus", "apply", "--dry-run")
    assert empty.returncode != 0, "focus apply with no saved focus should not succeed"
    assert "nothing to apply" in (empty.stdout + empty.stderr).lower()

    cli.ok("focus", "set", "python", "sql")
    shown = cli.ok("focus")
    assert "python" in shown.lower(), f"focus set did not persist:\n{shown}"

    out = cli.ok("focus", "apply", "--dry-run", "--days", "7")
    assert out.strip(), "focus apply --dry-run printed nothing"
    lowered = out.lower()
    assert any(word in lowered for word in ("dry", "preview", "would", "focus")), (
        f"dry-run output does not read as a preview:\n{out}"
    )


# ---------------------------------------------------------------------------
# NotebookLM-backed commands — graceful degradation is the contract
# ---------------------------------------------------------------------------


def test_content_status_reports_without_a_syllabus(cli: Cli) -> None:
    """`content status` answers on a vault with no chunked-generation state."""
    out = cli.graceful("content", "status", "--output-dir", str(cli.root))
    assert out.strip()


def test_content_list_degrades_without_notebooklm(cli: Cli) -> None:
    """`content list` needs NotebookLM; without it, a message not a traceback."""
    cli.graceful("content", "list")


def test_content_generate_requires_its_arguments(cli: Cli) -> None:
    """`content generate` rejects a call with no notebook/chapters."""
    proc = cli.run("content", "generate")
    assert proc.returncode != 0, "content generate ran with no required arguments"
    out = proc.stdout + proc.stderr
    assert "notebook-id" in out or "Missing option" in out, out


def test_content_syllabus_requires_a_notebook(cli: Cli) -> None:
    """`content syllabus` rejects a call with no notebook id."""
    proc = cli.run("content", "syllabus")
    assert proc.returncode != 0, "content syllabus ran with no notebook id"
    out = proc.stdout + proc.stderr
    assert "notebook-id" in out or "Missing option" in out, out


def test_content_process_degrades_on_a_missing_source(cli: Cli) -> None:
    """`content process` on a nonexistent source reports it, not a traceback."""
    proc = cli.run("content", "process", str(cli.root / "no-such-book.pdf"))
    out = proc.stdout + proc.stderr
    for marker in TRACEBACK_MARKERS:
        assert marker not in out, f"content process crashed:\n{out}"
    assert proc.returncode != 0, "a missing source file exited 0"
