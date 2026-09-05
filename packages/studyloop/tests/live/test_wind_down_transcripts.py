"""WD-5/WD-6 — transcript acceptance for the wind-down offer, in a real harness.

Claude Code headless (the one harness with attested flags: ``-p``,
``--mcp-config``, ``--append-system-prompt-file``, ``--output-format
stream-json``, ``--resume``), pointed at the LiteLLM gateway so no vendor
credential is needed. Marked ``live_provider``: burns gateway spend, opt in
with ``just gate-checks``.

The three gate checks, graded on captured transcripts:

* **S1** ``provider: none``, no connector — the wind-down says nothing about
  second brains.
* **S2** ``provider: xtiles``, no connector — same silence.
* **S3** ``provider: xtiles`` + the stub ``xtiles`` server — the offer is made
  exactly once, the learner declines, and the subject never returns. 3/3 runs
  required: this is the multi-turn claim a single lucky run flatters.

Every silent-state assertion carries D4's positive control: the transcript
must show the harness actually ran ``studyloop brain wind-down`` and read its
decision, or a crashed run, a wrong prompt file or an unauthenticated CLI
would all "pass" by producing an absence.

The weakest honest assertions, and nothing stronger (per the arbitrated plan):
the pinned sentence appears **at most once** across the whole transcript,
never "in turn N"; silence means neither the pinned sentence nor second-brain
vocabulary appears in assistant prose *while the positive control does*; and a
declined offer leaves the stub's call log empty. One retry only for a
pre-response infrastructure failure, and the flake count is written into the
artefact rather than smoothed.

Secrets discipline: the gateway key is read from the proxy's own config file
at call time, enters the child's environment only, and is never printed,
logged, asserted on, or passed in argv.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest
import yaml

from studyloop.second_brain.wind_down import (
    PUBLISH_OFFER_SENTENCE,
    XTILES_OFFER_SENTENCE,
)

pytestmark = [
    pytest.mark.live_provider,
    # Three harness turns at ~15-25s each, plus one permitted infra retry —
    # the suite-wide 60s signal timeout would kill a healthy S3 run.
    pytest.mark.timeout(900),
]

REPO_ROOT = Path(__file__).resolve().parents[4]
STUB = Path(__file__).resolve().parents[1] / "_xtiles_stub_server.py"
PROTOCOL = REPO_ROOT / "agents" / "shared" / "wind-down-protocol.md"

GATEWAY = os.environ.get("STUDYLOOP_GATE_GATEWAY", "http://localhost:4000")
MODEL = os.environ.get("STUDYLOOP_GATE_MODEL", "claude-sonnet-4-6")
PROXY_ENV = Path.home() / ".config" / "litellm-proxy-docker" / ".env"

#: Words that must not appear in assistant prose during a silent state or
#: after a decline. Lower-cased comparison; both the spaced and hyphenated
#: forms of "second brain" (the first live capture said "second-brain
#: decision" and a space-only needle missed it).
SECOND_BRAIN_VOCAB = ("second brain", "second-brain", "obsidian", "xtiles")

_EVIDENCE = Path(
    os.environ.get(
        "STUDYLOOP_EVIDENCE_DIR",
        REPO_ROOT / "reviews" / "2026-09-04-gate-checks" / "evidence" / "gate-checks",
    )
)

#: Collected across tests and flushed by the session fixture, so a partial run
#: still leaves a summary naming what it did and did not capture.
_SUMMARY: list[dict] = []


def _gateway_key() -> str:
    """The proxy's real key, from its own config file. NEVER printed."""
    if not PROXY_ENV.is_file():
        pytest.skip(f"gateway config not found: {PROXY_ENV}")
    for line in PROXY_ENV.read_text(encoding="utf-8").splitlines():
        for name in ("LITELLM_MASTER_KEY", "LITELLM_API_KEY"):
            if line.startswith(f"{name}="):
                return line.split("=", 1)[1].strip().strip("'\"")
    pytest.skip("no gateway key in the proxy config file")


@pytest.fixture(scope="session", autouse=True)
def _preconditions():
    if shutil.which("claude") is None:
        pytest.skip("claude CLI not installed")
    import urllib.request

    try:
        with urllib.request.urlopen(f"{GATEWAY}/health/liveliness", timeout=5) as resp:
            assert resp.status == 200
    except Exception:
        pytest.skip(f"gateway not answering at {GATEWAY}")
    _EVIDENCE.mkdir(parents=True, exist_ok=True)
    (_EVIDENCE / "transcripts").mkdir(exist_ok=True)
    yield
    (_EVIDENCE / "summary.json").write_text(json.dumps(_SUMMARY, indent=2), encoding="utf-8")


@pytest.fixture()
def world(tmp_path):
    """An isolated home + StudyLoop config dir. The real vault, the real
    ~/.claude and the real StudyLoop state are unreachable by construction.

    D2 (the council's second defect): the wind-down skill is resolved from
    ``Path.home()`` at install, so a hermetic HOME hides the skill and the
    harness drives a default behaviour that cannot see it — run 3 of the first
    capture proved it (``Unknown skill: studyloop-xtiles-wind-down`` killed
    the offer turn). Fix as ruled: run the REAL installer into the isolated
    home, which also exercises ``studyloop install agents`` for free.
    """
    home = tmp_path / "home"
    home.mkdir()
    # Claude Code first-run: mark onboarding done so headless -p does not stall.
    (home / ".claude.json").write_text(json.dumps({"hasCompletedOnboarding": True}))
    install = subprocess.run(
        [
            str(REPO_ROOT / ".venv" / "bin" / "studyloop"),
            "install",
            "agents",
            "--repo-root",
            str(REPO_ROOT),
            "--tool",
            "claude",
        ],
        capture_output=True,
        text=True,
        env={"HOME": str(home), "PATH": "/usr/bin:/bin"},
        timeout=120,
    )
    assert install.returncode == 0, f"skill install into the isolated home failed: {install.stderr}"
    assert (home / ".claude" / "skills" / "studyloop-xtiles-wind-down" / "SKILL.md").exists(), (
        "the isolated home has no wind-down skill; the harness would test its absence (D2)"
    )
    return home


def _config(home: Path, provider: str | None) -> Path:
    mapping: dict = {"topics": []}
    if provider:
        mapping["second_brain"] = {"provider": provider}
    path = home / "config.yaml"
    path.write_text(yaml.dump(mapping, default_flow_style=False, sort_keys=False))
    return path


def _system_prompt_file(home: Path) -> Path:
    """A minimal preamble plus the REAL protocol file.

    Grading a paraphrase of the protocol would test the paraphrase (the
    wrong-line-numbers lesson). The preamble must also not NAME the feature
    under test: the first S2 capture failed on the phrase "second-brain
    decision" that this preamble itself had planted — the assistant merely
    echoed its instructions.
    """
    text = (
        "You are a StudyLoop study mentor. The learner is finishing a study "
        "session. Follow the wind-down protocol below exactly, using the Bash "
        "tool to run studyloop commands. Skip steps that need session state "
        "this conversation does not have (progress recording, session end, "
        "voice); never skip step 5.\n\n---\n\n" + PROTOCOL.read_text(encoding="utf-8")
    )
    path = home / "wind-down-system-prompt.md"
    path.write_text(text, encoding="utf-8")
    return path


def _mcp_config(home: Path, log_path: Path) -> Path:
    config = {
        "mcpServers": {
            "xtiles": {
                "command": sys.executable,
                "args": [str(STUB)],
                "env": {"XTILES_STUB_CALL_LOG": str(log_path)},
            }
        }
    }
    path = home / "mcp-stub.json"
    path.write_text(json.dumps(config, indent=2))
    return path


def _claude_bin() -> str:
    path = shutil.which("claude")
    if path is None:
        pytest.skip("claude CLI not installed")
    return path


def _child_env(home: Path, config_path: Path) -> dict[str, str]:
    claude_dir = str(Path(_claude_bin()).parent)
    return {
        "HOME": str(home),
        "PATH": f"{REPO_ROOT}/.venv/bin:{claude_dir}:/usr/bin:/bin",
        "ANTHROPIC_BASE_URL": GATEWAY,
        "ANTHROPIC_AUTH_TOKEN": _gateway_key(),
        "ANTHROPIC_MODEL": MODEL,
        "STUDYLOOP_CONFIG": str(config_path),
        "STUDYLOOP_PLANS_DIR": str(home / "plans"),
        "DISABLE_AUTOUPDATER": "1",
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
        # Thinking is off because it adds nothing to a protocol-following
        # check and costs tokens. It USED to be mandatory: LiteLLM <= 1.99.x
        # died on extended-thinking blocks over the Bedrock invoke path
        # ("API Error: Content block is not a text block", proxy logs
        # 2026-09-04). Fixed upstream (BerriAI/litellm PR #33315 + the
        # bearer-token repair in #39166); the proxy runs v1.101.0-dev.2 as of
        # 2026-09-05 and a forced thinking block streams cleanly through
        # /v1/messages — verified with an explicit thinking-budget request.
        "MAX_THINKING_TOKENS": "0",
        "TERM": "dumb",
    }


class Turn:
    """One harness turn, parsed from stream-json."""

    def __init__(self, events: list[dict]):
        self.events = events

    @property
    def assistant_text(self) -> str:
        parts: list[str] = []
        for event in self.events:
            if event.get("type") == "assistant":
                for block in event.get("message", {}).get("content", []):
                    if block.get("type") == "text":
                        parts.append(block.get("text", ""))
        return "\n".join(parts)

    @property
    def bash_commands(self) -> list[str]:
        out: list[str] = []
        for event in self.events:
            if event.get("type") == "assistant":
                for block in event.get("message", {}).get("content", []):
                    if block.get("type") == "tool_use" and block.get("name") == "Bash":
                        out.append(str(block.get("input", {}).get("command", "")))
        return out

    @property
    def session_id(self) -> str | None:
        for event in self.events:
            if event.get("type") == "result":
                return event.get("session_id")
        return None

    @property
    def errored(self) -> bool:
        return any(event.get("type") == "result" and event.get("is_error") for event in self.events)


def _run_turn(
    prompt: str,
    *,
    env: dict[str, str],
    system_prompt: Path,
    mcp_config: Path | None = None,
    resume: str | None = None,
) -> Turn:
    argv = [
        _claude_bin(),
        "-p",
        prompt,
        "--output-format",
        "stream-json",
        "--verbose",
        "--model",
        MODEL,
        "--max-turns",
        "10",
        "--allowed-tools",
        # The xtiles tools are ALLOWED whenever the connector is attached, so
        # "declined, and nothing was written" is a real choice the model made
        # — an offer it could not have acted on would pass the no-writes
        # assert vacuously (trap #1).
        "Bash(studyloop:*),mcp__xtiles__*" if mcp_config is not None else "Bash(studyloop:*)",
        "--append-system-prompt-file",
        str(system_prompt),
    ]
    if mcp_config is not None:
        argv += ["--mcp-config", str(mcp_config), "--strict-mcp-config"]
    if resume is not None:
        argv += ["--resume", resume]
    result = subprocess.run(
        argv,
        capture_output=True,
        text=True,
        env=env,
        cwd=env["HOME"],
        timeout=420,
    )
    events = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    turn = Turn(events)
    if result.returncode != 0 and not events:
        raise RuntimeError(f"claude exited {result.returncode}: {result.stderr[-800:]}")
    return turn


def _capture_session(
    home: Path,
    provider: str | None,
    *,
    with_connector: bool,
    decline_turns: bool,
) -> tuple[list[Turn], Path | None, int]:
    """Run one wind-down conversation. Returns (turns, stub_log, flakes)."""
    config_path = _config(home, provider)
    system_prompt = _system_prompt_file(home)
    stub_log: Path | None = None
    mcp_config: Path | None = None
    if with_connector:
        stub_log = home / "stub-calls.json"
        mcp_config = _mcp_config(home, stub_log)
    env = _child_env(home, config_path)

    flakes = 0

    def once(prompt: str, resume: str | None) -> Turn:
        nonlocal flakes

        def attempt() -> Turn:
            return _run_turn(
                prompt,
                env=env,
                system_prompt=system_prompt,
                mcp_config=mcp_config,
                resume=resume,
            )

        try:
            turn = attempt()
        except (RuntimeError, subprocess.TimeoutExpired):
            # One retry, for a PRE-RESPONSE infrastructure failure only, and
            # counted rather than smoothed (the arbitrated flake rule).
            flakes += 1
            time.sleep(5)
            return attempt()
        if turn.errored and len(turn.assistant_text.strip()) < 200:
            # An is_error result with no real assistant prose is the gateway
            # failing before a response (observed: "API Error: Content block
            # is not a text block" from the un-restarted proxy). Same rule.
            flakes += 1
            time.sleep(5)
            return attempt()
        return turn

    turns = [once("Let's wrap up today's session, please run the wind-down.", None)]
    if decline_turns:
        session_id = turns[0].session_id
        assert session_id, "no session id in the first turn; cannot resume"
        turns.append(once("No thanks.", session_id))
        turns.append(
            once("One more thing — what's a good way to consolidate today's topic?", session_id)
        )
    return turns, stub_log, flakes


def _save_transcript(name: str, turns: list[Turn]) -> None:
    (_EVIDENCE / "transcripts" / f"{name}.json").write_text(
        json.dumps([t.events for t in turns], indent=2), encoding="utf-8"
    )


def _positive_control(turns: list[Turn]) -> bool:
    """D4: the wind-down actually consulted the decision command."""
    return any("brain wind-down" in cmd for turn in turns for cmd in turn.bash_commands)


def _sentence_count(turns: list[Turn], sentence: str) -> int:
    return sum(turn.assistant_text.count(sentence) for turn in turns)


def _vocab_hits(turns: list[Turn], *, ignoring: str = "") -> list[str]:
    hits: list[str] = []
    for i, turn in enumerate(turns):
        text = turn.assistant_text.replace(ignoring, "").lower()
        hits.extend(f"turn {i + 1}: {w}" for w in SECOND_BRAIN_VOCAB if w in text)
    return hits


def _record(state: str, *, expected: str, observed: str, runs: int, flakes: int, ok: bool) -> None:
    _SUMMARY.append(
        {
            "state": state,
            "expected": expected,
            "observed": observed,
            "runs": runs,
            "flakes": flakes,
            "verdict": "pass" if ok else "FAIL",
        }
    )


# ---------------------------------------------------------------------------
# WD-5 — the three gate checks
# ---------------------------------------------------------------------------


def test_s1_provider_none_is_silent(world) -> None:
    turns, _, flakes = _capture_session(world, None, with_connector=False, decline_turns=False)
    _save_transcript("s1-provider-none", turns)

    assert _positive_control(turns), (
        "the harness never ran `studyloop brain wind-down` — silence would be vacuous (D4)"
    )
    hits = _vocab_hits(turns)
    count = _sentence_count(turns, PUBLISH_OFFER_SENTENCE) + _sentence_count(
        turns, XTILES_OFFER_SENTENCE
    )
    observed = "silent" if not hits and count == 0 else f"spoke: {hits or 'offer sentence'}"
    _record(
        "s1-provider-none",
        expected="silent",
        observed=observed,
        runs=1,
        flakes=flakes,
        ok=not hits and count == 0,
    )
    assert count == 0, "an offer sentence was made with no provider configured"
    assert not hits, f"second-brain vocabulary in a silent state: {hits}"


def test_s2_xtiles_without_connector_is_silent(world) -> None:
    turns, _, flakes = _capture_session(world, "xtiles", with_connector=False, decline_turns=False)
    _save_transcript("s2-xtiles-no-connector", turns)

    assert _positive_control(turns), (
        "the harness never ran `studyloop brain wind-down` — silence would be vacuous (D4)"
    )
    hits = _vocab_hits(turns)
    count = _sentence_count(turns, PUBLISH_OFFER_SENTENCE) + _sentence_count(
        turns, XTILES_OFFER_SENTENCE
    )
    observed = "silent" if not hits and count == 0 else f"spoke: {hits or 'offer sentence'}"
    _record(
        "s2-xtiles-no-connector",
        expected="silent",
        observed=observed,
        runs=1,
        flakes=flakes,
        ok=not hits and count == 0,
    )
    assert count == 0, "an offer sentence was made with no connector attached"
    assert not hits, f"second-brain vocabulary in a silent state: {hits}"


@pytest.mark.parametrize("run_number", [1, 2, 3])
def test_s3_offer_once_then_decline_then_silence(world, run_number: int) -> None:
    """3/3 required — never a quorum that averages a violation away."""
    turns, stub_log, flakes = _capture_session(
        world, "xtiles", with_connector=True, decline_turns=True
    )
    _save_transcript(f"s3-offer-decline-run{run_number}", turns)

    assert _positive_control(turns), "the wind-down never consulted the decision command (D4)"

    offer_count = _sentence_count(turns, XTILES_OFFER_SENTENCE)
    publish_count = _sentence_count(turns, PUBLISH_OFFER_SENTENCE)
    after_decline_hits = _vocab_hits(turns[1:])
    declined_writes = json.loads(stub_log.read_text()) if stub_log and stub_log.is_file() else []

    ok = offer_count == 1 and publish_count == 0 and not after_decline_hits and not declined_writes
    _record(
        f"s3-offer-decline-run{run_number}",
        expected="offer once, decline honoured, then silence, no writes",
        observed="as expected"
        if ok
        else (
            f"offer x{offer_count}, publish-sentence x{publish_count}, "
            f"after-decline {after_decline_hits}, stub writes {len(declined_writes)}"
        ),
        runs=1,
        flakes=flakes,
        ok=ok,
    )
    assert offer_count == 1, f"the xTiles offer appeared {offer_count} times, not exactly once"
    assert publish_count == 0, "the PUBLISH sentence reached an xTiles learner (D1 violation)"
    assert not after_decline_hits, (
        f"second brains came back after the decline: {after_decline_hits}"
    )
    assert not declined_writes, "the learner declined but the stub logged writes"


# ---------------------------------------------------------------------------
# WD-6 — observation only: which tool the planner wording selects
# ---------------------------------------------------------------------------


def test_wd6_tool_routing_observation(world) -> None:
    """Records, never gates. One sample is not a distribution (ruling D3)."""
    stub_log = world / "stub-calls.json"
    mcp_config = _mcp_config(world, stub_log)
    env = _child_env(world, _config(world, "xtiles"))
    prompt = (
        "My next study action is 'Study: Python decorators' — reason: they keep "
        "appearing in code review; estimated 25 minutes. There are no due "
        "reviews. First tell me in one short sentence what you are about to "
        "do, then, in xTiles, add ONE item to today's planner as a tile built "
        'from Markdown, titled "Study: Python decorators", with the reason '
        "and estimated minutes. Do not create a project. Tell me the page URL "
        "when you are done."
    )
    system_prompt = world / "wd6-system-prompt.md"
    system_prompt.write_text(
        "You are an assistant with an xtiles MCP server connected. Use its "
        "tools directly; do not ask for confirmation.",
        encoding="utf-8",
    )
    turn = _run_turn(prompt, env=env, system_prompt=system_prompt, mcp_config=mcp_config)
    if turn.errored and len(turn.assistant_text.strip()) < 200:
        # One retry for a pre-response gateway failure, same rule as WD-5.
        time.sleep(5)
        turn = _run_turn(prompt, env=env, system_prompt=system_prompt, mcp_config=mcp_config)

    calls = json.loads(stub_log.read_text()) if stub_log.is_file() else []
    (_EVIDENCE / "tool-routing.json").write_text(
        json.dumps(
            {
                "wording": "P1b planner-tile prompt",
                "model": MODEL,
                "tools_called": [c["tool"] for c in calls],
                "note": "observation only — one sample is not a distribution (D3)",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    _save_transcript("wd6-tool-routing", [turn])
    # The only assertion is that the observation was CAPTURED — a run that
    # called nothing recorded nothing worth keeping.
    assert calls, "the harness made no stub call, so there is no routing to record"
