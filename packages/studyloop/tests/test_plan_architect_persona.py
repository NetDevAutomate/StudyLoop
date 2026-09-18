"""The study-plan architect persona prefers the MCP plan tools, CLI as fallback (T4.2, #13b).

The persona the ``planning`` purpose renders (``persona_mode_for("planning")`` →
``plan-architect``, design §5) must name the nine plan lifecycle tools of design
§4 — the six #11 registered and the three #12 lands — in a tooling section that
puts the MCP tools **before** the ``studyloop plan …`` CLI fallback, so an
architect running in a harness with the ``studyloop`` MCP server connected
reaches the plan application layer directly and one without it still has a
working recipe. The interview protocol itself (one question per turn) is not
under test here: these tests are about *which tools* the architect is told to
reach for and in what order of preference, never about the wording of a question.

Two guards ride along. The ``focus`` persona — what every default session
ships and hashes into ``persona_hash`` — is pinned by digest so this change
provably touched only the architect. And the per-harness projections (Claude
and OpenCode frontmatter files, Kiro's ``persona.md``) plus the manifest the
generator writes must still regenerate byte-identically from the canonical
body: there is no projection generator, only the copies and the hash manifest,
so drift is caught here rather than at install time.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
from pathlib import Path

import pytest

from studyloop import session_state
from studyloop.agent_launcher import build_canonical_persona, persona_mode_for


def _find_repo_root(start: Path) -> Path:
    """The checkout that holds ``agents/manifest.json``, searched upwards from ``start``.

    A bounded walk over ``start.parents`` (review 4, F5): the previous
    ``while not …: root = root.parent`` never terminated outside a checkout,
    because ``Path("/").parent`` is ``Path("/")``. Outside one this raises a
    named error instead of hanging collection.
    """
    for candidate in (start, *start.parents):
        if (candidate / "agents/manifest.json").exists():
            return candidate
    msg = f"no agents/manifest.json in {start} or any parent — run from the studyloop checkout"
    raise FileNotFoundError(msg)


_REPO_ROOT = _find_repo_root(Path(__file__).resolve())
_AGENTS = _REPO_ROOT / "agents"
_CANONICAL = _AGENTS / "shared/personas/plan-architect.md"
_MANIFEST_GENERATOR = _REPO_ROOT / "scripts/update-agent-manifest.py"

# Design §4: the nine plan lifecycle tools, in lifecycle order.
PLAN_MCP_TOOLS: tuple[str, ...] = (
    "list_study_plans",
    "get_study_plan",
    "get_planning_interview",
    "create_study_plan",
    "update_study_plan",
    "set_study_plan_status",
    "set_study_plan_milestone",
    "evaluate_study_plan",
    "delete_study_plan",
)

# The CLI fallback must cover every lifecycle step that HAS a CLI command.
# ``delete`` is deliberately absent: there is no ``studyloop plan delete``
# (deletion is the Web UI or ``delete_study_plan`` with explicit confirmation),
# and the prompt-contract test rejects any invocation that does not resolve.
_CLI_FALLBACK_SUBCOMMANDS: tuple[str, ...] = (
    "interview",
    "list",
    "show",
    "new",
    "status",
    "milestone",
    "evaluate",
    "record",
)

_MCP_HEADING_RE = re.compile(r"^#{2,3} .*\bMCP\b.*$", re.MULTILINE)
_CLI_HEADING_RE = re.compile(r"^#{2,3} .*\bCLI fallback\b.*$", re.MULTILINE)

# ``build_canonical_persona("focus", "Python", 5)`` at 205819c7 (the tip
# feat/p4-13b branched from), with the three session paths fixed below so the
# digest does not depend on the machine's config directory. A change here is a
# change to what every default session ships — make it deliberately, in the same
# commit as the persona edit, never as a side effect of an architect change.
# A content digest of a public persona rendering, not a credential.
_FOCUS_SHA256_AT_205819C7 = (
    "2d35c22a99ed72fbc91e8a79ad05312b04af2e36bbb5a7bb4d7ac4a0e9ef11e0"  # pragma: allowlist secret
)


def _planning_persona() -> str:
    """The persona a ``planning``-purpose launch ships (design §5), brief and all."""
    mode = persona_mode_for("planning")
    return build_canonical_persona(mode, "Study plan", 5, brief="- interview item one")


def _section(content: str, heading_re: re.Pattern[str]) -> tuple[int, str]:
    """Return ``(start, text)`` of the section a heading opens, up to the next
    heading of the same or a higher level."""
    match = heading_re.search(content)
    assert match, f"no heading matches {heading_re.pattern!r}"
    level = len(match.group(0)) - len(match.group(0).lstrip("#"))
    closer = re.compile(rf"^#{{1,{level}}} ", re.MULTILINE)
    following = closer.search(content, match.end())
    end = following.start() if following else len(content)
    return match.start(), content[match.start() : end]


def _strip_frontmatter(text: str) -> str:
    if not text.startswith("---\n"):
        return text
    end = text.find("\n---\n", 4)
    assert end != -1, "frontmatter opened with '---' but never closed"
    return text[end + len("\n---\n") :]


# ---------------------------------------------------------------------------
# RED for T4.2: the nine tools, the fallback, and the order of preference.
# ---------------------------------------------------------------------------


def test_plan_architect_persona_names_the_nine_mcp_tools_when_purpose_is_planning() -> None:
    content = _planning_persona()

    missing = [name for name in PLAN_MCP_TOOLS if f"`{name}" not in content]
    assert not missing, f"planning persona does not name {missing}"

    assert "CLI fallback" in content
    _, cli_section = _section(content, _CLI_HEADING_RE)
    absent = [
        sub
        for sub in _CLI_FALLBACK_SUBCOMMANDS
        if not re.search(rf"studyloop plan {sub}\b", cli_section)
    ]
    assert not absent, f"CLI fallback section names no `studyloop plan {absent}`"
    assert "studyloop plan delete" not in content, "there is no such command"


def test_plan_architect_persona_prefers_mcp_over_cli_ordering() -> None:
    content = _planning_persona()

    mcp_at, mcp_section = _section(content, _MCP_HEADING_RE)
    cli_at, _ = _section(content, _CLI_HEADING_RE)
    assert mcp_at < cli_at, "the MCP tools must be introduced before the CLI fallback"
    assert mcp_at + len(mcp_section) <= cli_at, "the MCP section must close before the fallback"
    assert not re.search(r"studyloop plan \w", mcp_section), "a CLI recipe inside the MCP section"

    # Every one of the nine is introduced in the MCP section itself, not only
    # mentioned in passing somewhere after the fallback.
    not_in_mcp = [name for name in PLAN_MCP_TOOLS if f"`{name}" not in mcp_section]
    assert not not_in_mcp, f"MCP section does not introduce {not_in_mcp}"

    # And the fallback is framed as the fallback: no `studyloop plan` recipe
    # appears before the MCP tools have been named.
    first_cli = re.search(r"studyloop plan \w", content)
    assert first_cli is not None
    assert first_cli.start() > mcp_at, "a CLI recipe precedes the MCP tools"


def test_mcp_section_states_the_lifecycle_guards() -> None:
    """The three behaviours the seam enforces and the persona must not talk the
    agent past: activate only when readiness says ready, delete only on explicit
    confirmation, evaluate as a preview unless recording is meant."""
    _, mcp_section = _section(_planning_persona(), _MCP_HEADING_RE)
    lowered = mcp_section.lower()

    assert "readiness" in lowered and "active" in lowered
    assert "confirm" in lowered and "`delete_study_plan" in mcp_section
    assert "record=false" in lowered.replace(" ", "") or "preview" in lowered
    assert "record=true" in lowered.replace(" ", "")


def test_all_nine_persona_tools_are_registered_after_phase_four() -> None:
    """Ground the persona's constant in the real registry: every tool the
    architect is told to prefer exists in the production inventory. Until the
    #12 merge this test tolerated the three not-yet-landed names
    (``_LANDING_WITH_12``); with both Phase-4 branches merged that tolerance
    would let one of them silently disappear (review 4, F4/qwen/Grok), so the
    set is now exact."""
    from studyloop.mcp.server import mcp

    registered = set(mcp._tool_manager._tools)
    missing = [name for name in PLAN_MCP_TOOLS if name not in registered]
    assert not missing, f"the persona names tools the registry lacks: {missing}"
    assert "record_plan_learning" in registered


def test_find_agent_repo_root_fails_when_marker_is_absent(tmp_path: Path) -> None:
    """The walk terminates outside a checkout (review 4, F5) — it does not spin
    at the filesystem root."""
    with pytest.raises(FileNotFoundError, match=r"agents/manifest\.json"):
        _find_repo_root(tmp_path / "nested" / "deeper")
    assert _find_repo_root(Path(__file__).resolve()) == _REPO_ROOT


# ---------------------------------------------------------------------------
# Guards: focus untouched, projections and manifest regenerate byte-identically.
# ---------------------------------------------------------------------------


def test_focus_persona_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(session_state, "STATE_FILE", Path("/fixed/session-state.json"))
    monkeypatch.setattr(session_state, "TOPICS_FILE", Path("/fixed/session-topics.md"))
    monkeypatch.setattr(session_state, "PARKING_FILE", Path("/fixed/session-parking.md"))

    content = build_canonical_persona("focus", "Python", 5)

    assert hashlib.sha256(content.encode("utf-8")).hexdigest() == _FOCUS_SHA256_AT_205819C7


@pytest.mark.parametrize(
    "relative",
    [
        "claude/study-plan-architect.md",
        "opencode/study-plan-architect.md",
        "kiro/study-plan-architect/persona.md",
    ],
)
def test_projected_personas_match_canonical(relative: str) -> None:
    canonical = _CANONICAL.read_text(encoding="utf-8").lstrip("\n")
    projected = _strip_frontmatter((_AGENTS / relative).read_text(encoding="utf-8")).lstrip("\n")
    assert projected == canonical, f"agents/{relative} has drifted from the canonical persona"


def test_manifest_hashes_regenerate_byte_identically_for_the_architect_projections() -> None:
    """Run the generator's own hash over the tracked projections and compare with
    the committed manifest — the check ``studyloop install agents`` and doctor
    rely on, without mutating the tracked manifest from a test."""
    spec = importlib.util.spec_from_file_location("update_agent_manifest", _MANIFEST_GENERATOR)
    assert spec is not None and spec.loader is not None
    generator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generator)

    manifest = json.loads((_AGENTS / "manifest.json").read_text(encoding="utf-8"))["agents"]
    tracked = [
        rel
        for files in generator.TRACKED_FILES.values()
        for rel in files
        if "study-plan-architect" in rel
    ]
    assert tracked, "the generator tracks no architect projection at all"
    stale = {
        rel: (manifest.get(rel, {}).get("hash"), generator.hash_file(_AGENTS / rel))
        for rel in tracked
        if manifest.get(rel, {}).get("hash") != generator.hash_file(_AGENTS / rel)
    }
    assert not stale, f"re-run scripts/update-agent-manifest.py: {stale}"


# ---------------------------------------------------------------------------
# Council review 4 (GPT F2/F3, Grok 🔵, qwen 🔵): the persona's runtime claims
# ---------------------------------------------------------------------------

_SESSION_START_RE = re.compile(r"^## Session Start Protocol$", re.MULTILINE)
_END_OF_SESSION_RE = re.compile(r"^## End-of-Session Protocol$", re.MULTILINE)
_TOOL_ROW_RE = re.compile(r"^\| [^|]+ \| `(?P<name>[a-z_]+)\((?P<args>[^)]*)\)` \|", re.MULTILINE)


def _table_parameter_names(args: str) -> tuple[set[str], bool]:
    """The parameter names a table row's signature shows, and whether it
    abbreviates with an ellipsis (``…``) — top-level commas only, so a default
    such as ``status="draft"`` or ``answers`` stays one parameter."""
    names: set[str] = set()
    elided = False
    depth = 0
    current = ""
    for char in args + ",":
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
        if char == "," and depth == 0:
            token = current.strip()
            current = ""
            if not token:
                continue
            if token == "…":
                elided = True
                continue
            names.add(token.split("=", 1)[0].strip())
        else:
            current += char
    return names, elided


def test_mcp_table_signatures_match_the_registered_schemas() -> None:
    """Every signature the MCP table shows is the registered tool's own
    parameter list (review 4, Grok 🔵: the table had drifted — ``plan_id``,
    ``history_limit`` and ``status`` were missing from three rows). A row may
    abbreviate with ``…`` only as a strict subset; otherwise the names are
    exactly the schema's, so an agent reading the table calls what exists."""
    from studyloop.mcp.server import mcp

    _, mcp_section = _section(_planning_persona(), _MCP_HEADING_RE)
    rows = {m.group("name"): m.group("args") for m in _TOOL_ROW_RE.finditer(mcp_section)}
    assert set(rows) == set(PLAN_MCP_TOOLS), set(rows) ^ set(PLAN_MCP_TOOLS)

    registry = mcp._tool_manager._tools
    # ``record_plan_learning`` is introduced in prose under the table with the
    # same backtick-signature form; hold it to the same rule.
    prose = re.search(r"`record_plan_learning\(([^)]*)\)`", mcp_section)
    assert prose is not None, "record_plan_learning is not introduced with its signature"
    rows["record_plan_learning"] = prose.group(1)

    for name, args in rows.items():
        schema_params = set(registry[name].parameters["properties"])
        shown, elided = _table_parameter_names(args)
        if elided:
            assert shown < schema_params, f"{name}: {shown - schema_params} are not parameters"
        else:
            assert shown == schema_params, (
                f"{name}: table shows {sorted(shown)}, schema has {sorted(schema_params)}"
            )


def test_session_protocol_says_where_study_id_comes_from_and_the_empty_default() -> None:
    """``study_id=STUDY_ID`` is not self-explanatory to an agent in a Web PTY
    or ACP console (review 4, GPT F2 / Grok / qwen): the protocol must say the
    value is the live session's ``study_session_id`` from the session state
    file the persona already lists, and that when it cannot be read the
    argument stays at its empty default — never the literal placeholder."""
    _, section = _section(_planning_persona(), _SESSION_START_RE)
    lowered = section.lower()

    assert "study_session_id" in section, "the protocol does not say where STUDY_ID comes from"
    assert "study_id" in section
    assert "empty" in lowered or 'study_id=""' in section, "no rule for when it cannot be read"
    assert "literal" in lowered, "the placeholder itself must be ruled out"


def test_wind_down_names_the_acp_path_for_ending_the_session() -> None:
    """Step 6 is a shell command; an ACP architect has no shell. The protocol
    must name ``end_session`` (the registered MCP tool) for that case and be
    honest that it carries no notes (review 4, qwen 🔵 / Grok 🔵)."""
    from studyloop.mcp.server import mcp

    assert "end_session" in mcp._tool_manager._tools
    _, section = _section(_planning_persona(), _END_OF_SESSION_RE)

    assert "`end_session`" in section, "no MCP path for ending the session over ACP"
    assert "studyloop session end" in section, "the shell path must stay for PTY sessions"
    assert "notes" in section.lower()


def test_closing_section_asks_close_or_delete_for_a_checked_non_active_plan() -> None:
    """Owner decision 2026-09-18 (council review 6, open item 2): a fully-checked
    ``abandoned``, ``paused`` or ``draft`` plan may be closed or deleted, and the
    architect asks the learner which. The closing section must name the three
    statuses, both doors (``set_study_plan_status`` to ``complete``;
    ``delete_study_plan`` with ``confirmed=True``), and keep deletion behind the
    learner's explicit word — the persona's standing deletion rule."""
    _, closing = _section(_planning_persona(), re.compile(r"^## Closing a Plan", re.MULTILINE))
    lowered = closing.lower()
    for status in ("abandoned", "paused", "draft"):
        assert f"`{status}`" in closing, f"the closing section does not name {status!r}"
    assert "ask" in lowered and "delete" in lowered
    assert 'set_study_plan_status(plan_id, "complete")' in closing
    assert "delete_study_plan" in closing and "confirmed=true" in lowered
    assert (
        "in so many words" in lowered
        or "said, in so many words" in lowered
        or ("explicitly" in lowered)
    ), "deletion must stay behind the learner's explicit word"


def test_revise_row_says_pause_before_repairing_an_active_plan() -> None:
    """The F1 contract: every write to an active-but-unready document is
    refused, so repairing one means pausing it first. The Revise row must say
    so, or the architect hammers ``update_study_plan`` on a husk (review 4,
    Grok 🔵)."""
    _, mcp_section = _section(_planning_persona(), _MCP_HEADING_RE)
    revise_row = next(
        line
        for line in mcp_section.splitlines()
        if line.startswith("| Revise | `update_study_plan")
    )
    assert "pause" in revise_row.lower(), revise_row


def test_lifecycle_paragraph_does_not_overclaim_the_active_create_refusal() -> None:
    """ "Do not create as active to skip the gate; the seam refuses it" taught a
    blanket ban the seam does not enforce — a *ready* document may be created
    active. The paragraph must say the gate applies at creation too (review
    4, GPT §3)."""
    _, mcp_section = _section(_planning_persona(), _MCP_HEADING_RE)
    lowered = " ".join(mcp_section.lower().split())  # the Markdown is hard-wrapped

    assert "skip the gate" in lowered or "same readiness" in lowered
    assert "the seam refuses it" not in lowered


def test_install_docs_disclose_architect_fallback_limits() -> None:
    """``docs/agent-install.md`` said an agent without MCP "can do the same
    work" at a shell, while the persona is honest that the CLI cannot revise
    an existing plan's fields or delete a plan (review 4, GPT F3 / Grok). It
    then disclosed that the harness-launched Kiro/Claude architects did not
    attach the server. The owner granted them the plan tools on 2026-09-16
    (D-A), so the section now states the granted shape for both harnesses —
    the ten tools, the Kiro visibility/trust arrays and their spelling — and
    no longer points at an open item that has been decided."""
    doc = (_REPO_ROOT / "docs/agent-install.md").read_text(encoding="utf-8")
    start = doc.index("## Study-plan tools over MCP")
    end = doc.index("\n## ", start + 1)
    section = doc[start:end]
    lowered = section.lower()

    assert "the same work" not in lowered, "parity overclaim"
    assert "revis" in lowered and "delet" in lowered and "no cli" in lowered.replace("-", " ")
    assert "kiro" in lowered and "claude" in lowered, "the harness grant is not disclosed"
    for phrase in (
        "`@studyloop/<tool>`",  # Kiro trust spelling
        "`mcp__studyloop__<tool>`",  # Claude allow-list spelling
        "`mcpservers`",
        "`allowedtools`",
        "d-a",
    ):
        assert phrase in lowered, f"the granted shape is not stated: {phrase}"
    assert "nothing else on the `studyloop` server is trusted" in lowered, "least privilege"
    assert "not the learner's authorisation" in lowered, "tool permission ≠ user authorisation"
    assert "open item" not in lowered and "stay cli-limited" not in lowered, (
        "the decision has been taken; the doc must not describe it as open"
    )
    # Council review 6 (GPT F5 / Grok 🔵 c, d, a): the Claude allow-list names
    # tools; the doc must say where the SERVER is registered for Claude, and
    # that path must be the installer's own — not a remembered one. Existing
    # mentor installs gain live tools from the spelling fix; the grant spelling
    # is pinned to a kiro-cli version and the doc must say when to re-probe.
    from studyloop import installers

    assert "claude" in installers._MCP_HARNESSES
    claude_mcp = installers._mcp_config_path("claude")
    assert f"`~/{claude_mcp.relative_to(installers._HOME)}`" in section, (
        "the doc must name the file the installer registers the studyloop server in for Claude"
    )
    assert "study-mentor" in section and "inert" in lowered, "mentor grant activation"
    assert "2.22.0" in section and "re-run" in lowered, "the version-pinned probe"


def test_fallback_table_does_not_point_at_web_ui_controls_that_do_not_exist() -> None:
    """The Web UI's Study Plans view creates plans, activates them, ticks
    milestones and previews or records checkpoints — it has no control that
    revises an existing plan's fields and none that deletes a plan; those are
    the Web *API*'s ``PATCH``/``DELETE`` and the MCP tools. The persona told
    the architect to "point at the Web UI" for exactly those two steps (found
    while closing council review 5's docs findings). The two rows and the
    no-command sentence must instead tell the architect to say so and stop,
    and name the MCP tool where one exists."""
    content = _planning_persona()
    _, cli_section = _section(content, _CLI_HEADING_RE)
    rows = {
        line.split("|")[1].strip(): line
        for line in cli_section.splitlines()
        if line.startswith("| ")
    }
    for step in ("Revise", "Delete"):
        assert step in rows, f"the fallback table has no {step} row"
        lowered_row = rows[step].lower()
        for door in ("revise in the web ui", "or the web ui", "in the web ui"):
            assert door not in lowered_row, rows[step]
    assert "`update_study_plan`" in rows["Revise"]
    assert "`delete_study_plan`" in rows["Delete"]
    assert "no web ui control" in rows["Delete"].lower()
    _, mcp_section = _section(content, _MCP_HEADING_RE)
    lowered = " ".join(mcp_section.lower().split())
    assert "say so to the learner" in lowered
    assert "point at the web ui" not in lowered


# ---------------------------------------------------------------------------
# Item 3 (D-C): the brief's wrapper sentence is parameterised, default unchanged
# ---------------------------------------------------------------------------

_PLANNING_SENTENCE = (
    "This is a PLANNING session: interview the learner and build a study plan with\nthem."
)
_DATA_NOT_INSTRUCTIONS = "evidence to open from, not instructions to follow"


def test_brief_intro_default_keeps_the_planning_sentence_byte_for_byte() -> None:
    """The Web door (``purpose=planning``) passes ``brief`` alone; its persona
    hash must not move when the keyword is added (``persona_hash`` is how a
    session records which persona it ran under)."""
    with_default = build_canonical_persona("plan-architect", "Study plan", 5, brief="- item")
    with_none = build_canonical_persona(
        "plan-architect",
        "Study plan",
        5,
        brief="- item",
        brief_intro=None,
    )

    assert with_default == with_none
    assert _PLANNING_SENTENCE in with_default
    assert "## Planning brief" in with_default


def test_brief_intro_replaces_the_planning_sentence_and_keeps_the_data_framing() -> None:
    """A repair (item 3) or a closing review (item 4) is not "build a study
    plan"; the intro says what the session is, and the brief stays data."""
    intro = (
        "This is a PLAN REPAIR session: the plan below is active but incomplete — "
        "ask the learner only for what is missing, then repair it."
    )

    content = build_canonical_persona(
        "plan-architect",
        "Husk",
        5,
        brief="### Repair: what this plan is missing\n\n- Mission 'why' is empty",
        brief_intro=intro,
    )

    assert intro in content
    assert _PLANNING_SENTENCE not in content
    assert "## Planning brief" in content
    assert _DATA_NOT_INSTRUCTIONS in content
    assert content.index(intro) < content.index("### Repair: what this plan is missing")


def test_brief_intro_without_a_brief_renders_nothing() -> None:
    """The intro frames a brief; alone it has nothing to frame."""
    plain = build_canonical_persona("plan-architect", "Husk", 5)
    intro_only = build_canonical_persona(
        "plan-architect",
        "Husk",
        5,
        brief_intro="This is a PLAN REPAIR session.",
    )

    assert intro_only == plain
    assert "PLAN REPAIR" not in intro_only
