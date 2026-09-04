"""T4 C8: the wind-down protocol's second-brain offer, and its limits.

An honest note about what these tests can and cannot prove.

They CAN prove: the instruction exists, it is gated on both flags, the sentence is
byte-identical everywhere it appears, and every `studyloop ...` command the
protocol tells an agent to run is a command that exists.

They CANNOT prove that a language model following prose actually offers once and
then stops. No static check can. That is why the gate is expressed as two boolean
fields an agent reads from `brain status --json` rather than as a judgement call,
and why the offer sentence itself says "I'll only ask once" — the instruction is
as mechanical as prose can be made. Runtime evidence is a recorded wind-down
transcript, named in the sign-off.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
AGENTS = REPO_ROOT / "agents"
WIND_DOWN = AGENTS / "shared" / "wind-down-protocol.md"
GUIDE = REPO_ROOT / "docs" / "second-brain.md"

#: The markers that delimit the one sentence that must match everywhere.
#:
#: An explicit marker rather than "the first line containing 'publish'": the guard
#: has to fail when the sentence DRIFTS, and a fuzzy match would quietly keep
#: passing against a sentence that had changed meaning.
OFFER_START = "<!-- wind-down-offer -->"
OFFER_END = "<!-- /wind-down-offer -->"


def _extract_offer(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    assert OFFER_START in text, f"{path.name} is missing {OFFER_START}"
    body = text.split(OFFER_START, 1)[1].split(OFFER_END, 1)[0]
    return body.strip()


def test_the_wind_down_protocol_gates_the_offer_on_both_flags() -> None:
    """`configured` alone is not enough — and the decision is the CLI's.

    xTiles stage 1 IS configured but cannot be published to, so an agent that
    checked only `configured` would offer a command that cannot work — and would do
    it at the end of every session. Since WD-1 the protocol delegates the decision
    to `studyloop brain wind-down --json`, but it must still EXPLAIN the two
    flags, or a reader cannot tell why the command answers as it does.
    """
    text = WIND_DOWN.read_text(encoding="utf-8")
    assert "studyloop brain wind-down --json" in text
    assert "supports_publish" in text
    assert "configured" in text


def test_the_protocol_says_to_stay_silent_otherwise() -> None:
    """The default has to be stated, or "no second brain" becomes "ask anyway"."""
    text = WIND_DOWN.read_text(encoding="utf-8").lower()
    assert "say nothing" in text or "silent" in text


def test_the_offer_sentence_is_identical_in_the_protocol_and_the_guide() -> None:
    """One sentence, two files, byte-identical.

    Documentation that describes a slightly different offer than the one the agent
    makes is how a learner ends up unable to tell whether the tool is behaving.
    """
    if not GUIDE.is_file():
        pytest.skip("the Second Brain guide lands with the documentation task")
    assert _extract_offer(WIND_DOWN) == _extract_offer(GUIDE)


def test_the_offer_names_what_is_written_and_where() -> None:
    """A learner saying yes must already know what is about to happen."""
    offer = _extract_offer(WIND_DOWN)
    assert "Obsidian" in offer
    assert "Study/Today.md" in offer
    assert "Study/Plans/" in offer
    assert "once" in offer.lower()


def test_every_studyloop_command_in_the_agent_protocols_resolves() -> None:
    """A protocol that names a command which does not exist is a dead instruction.

    Checked against `--help` for the real CLI rather than a hand-maintained list of
    command names, so a renamed command fails here instead of at 10pm in someone's
    wind-down.
    """
    pattern = re.compile(r"^\s*studyloop ([a-z-]+)(?: ([a-z-]+))?", re.MULTILINE)
    seen: set[tuple[str, ...]] = set()
    for path in sorted((AGENTS / "shared").glob("*.md")):
        for block in re.findall(r"```(?:bash|sh)?\n(.*?)```", path.read_text(), re.DOTALL):
            for group, sub in pattern.findall(block):
                seen.add((group,) if not sub or sub.startswith("-") else (group, sub))

    assert seen, "no studyloop commands found in the agent protocols; the scan is vacuous"

    for command in sorted(seen):
        result = subprocess.run(
            ["uv", "run", "studyloop", *command, "--help"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode == 0, (
            f"`studyloop {' '.join(command)}` is named in an agent protocol but "
            f"does not resolve:\n{result.stderr}"
        )


def test_the_summary_mirrors_are_in_step_with_the_protocol() -> None:
    """Three other files summarise the wind-down; each must mention the offer.

    Without this, the protocol grows a step and the three summaries silently keep
    describing the previous version — the exact drift the docs guards exist for.
    """
    mirrors = (
        AGENTS / "shared" / "session-protocol.md",
        AGENTS / "claude" / "socratic-mentor.md",
        AGENTS / "codex" / "AGENTS.md",
    )
    for path in mirrors:
        assert path.is_file(), path
        text = path.read_text(encoding="utf-8")
        assert "brain status" in text or "second brain" in text.lower(), path


def test_agent_manifest_hashes_match_the_files_on_disk() -> None:
    """Every recorded hash must match its file's current content.

    Recomputed here rather than by re-running the generator, for two reasons. The
    generator stamps ``updated`` with today's date unconditionally, so
    "regenerating is a no-op" is not a property this repository has — a test
    asserting it would fail every day for a reason that has nothing to do with
    drift. And running the generator from a test would MUTATE a tracked file as a
    side effect, which a guard must never do.

    The hash is the part that matters: it is what the doctor's drift check and
    ``studyloop install agents`` compare against, so a stale one means a learner
    installs an agent definition that does not match the repository.
    """
    import hashlib

    generator = REPO_ROOT / "scripts" / "update-agent-manifest.py"
    if not generator.is_file():
        pytest.skip("no manifest generator in this checkout")

    manifest = json.loads((AGENTS / "manifest.json").read_text(encoding="utf-8"))
    entries = manifest["agents"]
    assert entries, "the manifest is empty; this scan would be vacuous"

    stale = []
    for rel_path, entry in entries.items():
        path = AGENTS / rel_path
        assert path.is_file(), f"the manifest lists {rel_path}, which does not exist"
        actual = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
        if actual != entry["hash"]:
            stale.append(rel_path)
    assert not stale, (
        f"agents/manifest.json is stale for {stale}: re-run "
        "scripts/update-agent-manifest.py and commit the result"
    )


def test_every_file_the_generator_tracks_is_in_the_manifest() -> None:
    """Adding an agent file without registering it must fail here.

    The complement of the hash check: that one catches an edited file, this one
    catches a NEW file nobody added to the manifest, which the hash check cannot
    see at all.
    """
    generator = REPO_ROOT / "scripts" / "update-agent-manifest.py"
    if not generator.is_file():
        pytest.skip("no manifest generator in this checkout")

    source = generator.read_text(encoding="utf-8")
    tracked = set(re.findall(r'"((?:[a-z]+/)+[A-Za-z0-9_.-]+\.(?:md|json))"', source))
    assert tracked, "could not read the generator's file list; the scan is vacuous"

    manifest = json.loads((AGENTS / "manifest.json").read_text(encoding="utf-8"))
    recorded = set(manifest["agents"])
    missing = {rel for rel in tracked if (AGENTS / rel).is_file()} - recorded
    assert not missing, f"tracked but not in the manifest: {sorted(missing)}"
