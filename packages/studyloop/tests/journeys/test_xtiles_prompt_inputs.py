"""Can a learner actually produce what the shipped xTiles prompts ask for?

The xTiles half of the guide is three prompts a learner copies into their assistant.
Each names things: a CLI flag whose output they paste, MCP tools the assistant calls,
and fields it is told to put in a tile. None of that is code StudyLoop runs, so
nothing in the suite has ever checked that the inputs exist.

That makes the guide a promise with no test behind it — the exact shape of defect
this campaign kept finding by review rather than by CI. A red test here is a
**documentation** bug: the prose told a learner to do something they cannot do.

Scope, stated so it is not overclaimed: this proves the *inputs* are producible. It
does not prove an assistant produces a good tile from them, which is a property of a
language model and not of StudyLoop.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from ._world import JourneyWorld, evidence_root, journey_world, write_evidence

GUIDE = Path(__file__).resolve().parents[4] / "docs" / "second-brain.md"
PLAN_ID = "python-decorators"

#: Pages the "plan as a project" prompt tells the assistant to create, each of which
#: has to correspond to something in the pasted Markdown or the instruction is
#: unfollowable.
PROJECT_PAGES = ("Mission", "Milestones", "Learning Records", "Resources", "Checkpoints")

#: MCP tools the planner and wind-down prompts call by name.
NAMED_TOOLS = ("get_next_action", "get_due_cards", "record_study_progress")

#: Fields the prompts tell the assistant to carry into xTiles.
NAMED_FIELDS = ("card_hash", "reason", "estimated_minutes")


@pytest.fixture(scope="module")
def guide() -> str:
    return GUIDE.read_text(encoding="utf-8")


@pytest.fixture()
def world(tmp_path):
    with journey_world(tmp_path) as built:
        yield built


def _seed_plan(world: JourneyWorld) -> None:
    result = world.run(
        "plan",
        "new",
        "--title",
        "Python Decorators",
        "--why",
        "Decorators keep appearing in the codebases I read, and I skip them.",
        "--topic",
        PLAN_ID,
        "--success",
        "I can explain what functools.wraps preserves, without looking it up",
        "--milestone",
        "Read and explain a decorator someone else wrote (concepts: closures)",
        "--resource",
        "https://docs.python.org/3/library/functools.html",
        "--activate",
    )
    assert result.exit_code == 0, result.output


def test_the_project_prompt_input_is_producible(world: JourneyWorld, guide: str) -> None:
    """The guide says to paste the output of one command. It has to work, and contain
    the sections the prompt then asks the assistant to split into pages."""
    assert "plan show <plan-id> --markdown" in guide or "plan show" in guide, (
        "the guide no longer tells the learner where the plan Markdown comes from"
    )

    _seed_plan(world)
    shown = world.run("plan", "show", PLAN_ID, "--markdown")
    assert shown.exit_code == 0, (
        "the command the guide tells a learner to paste from failed:\n" + shown.output
    )
    document = shown.stdout
    assert document.strip(), "plan show --markdown printed nothing"

    missing = [page for page in PROJECT_PAGES if f"## {page}" not in document]
    assert missing == [], (
        "the prompt tells the assistant to make a page per section, but the pasted "
        f"Markdown has no heading for: {missing}. Either the renderer changed or the "
        "guide asks for pages that cannot be filled."
    )

    write_evidence(
        world,
        evidence_root() / "xtiles-week" / "prompt-inputs",
        {"plan-show-markdown.md": world.redact(document)},
    )


def test_every_mcp_tool_the_prompts_name_is_actually_registered(guide: str) -> None:
    """A prompt that calls a tool the server does not expose cannot run.

    Rewritten after a validation council pointed out the first version grepped for
    ``def <name>(`` — which a dead function, a nested helper or a function that is
    never registered would all satisfy. Registration is the property that matters,
    so registration is what this asks the server for.
    """
    tools = _registered_tool_names()
    for tool in NAMED_TOOLS:
        assert tool in guide, f"the guide stopped naming {tool}, so this list is stale"
        assert tool in tools, (
            f"the guide's prompts call {tool}, which the MCP server does not register. "
            f"Registered: {sorted(tools)}"
        )


def _registered_tool_names() -> set[str]:
    """Ask the MCP server which tools it actually exposes.

    FastMCP keeps its registrations on the server object. Reached through the real
    registration function rather than by reading source, so a tool that exists but is
    never wired up is absent here — which is the whole point.
    """
    from studyloop.mcp import tools as tools_module

    class _Recorder:
        """Stands in for the FastMCP server and records what gets registered."""

        def __init__(self) -> None:
            self.names: set[str] = set()

        def tool(self, *args, **kwargs):
            def decorate(function):
                self.names.add(getattr(function, "__name__", ""))
                return function

            # Support both @server.tool and @server.tool() spellings.
            if args and callable(args[0]):
                return decorate(args[0])
            return decorate

    recorder = _Recorder()
    register = getattr(tools_module, "register_tools", None)
    if register is None:  # pragma: no cover - shape change, reported not guessed
        pytest.fail(
            "studyloop.mcp.tools has no register_tools(); this check cannot ask the "
            "server what it exposes and must be rewritten rather than weakened"
        )
    register(recorder)
    return recorder.names


def test_the_recommendation_the_planner_prompt_uses_really_carries_its_fields() -> None:
    """Invoke it, rather than searching its module for the field names.

    The council's objection to the previous version was exact: a substring search
    over source passes on a comment, an unrelated model, or an input-only path. The
    planner prompt puts the reason and the estimate in the tile body, so those have
    to be on the object the assistant receives.
    """
    from studyloop.learning.decision import build_now_plan

    plan = build_now_plan(energy="medium", time_minutes=25, modality="recall")
    payload = plan.to_json_dict()
    primary = payload.get("primary") or {}

    for field in ("concept", "reason", "estimated_minutes"):
        assert field in primary, (
            f"the planner prompt tells the assistant to put the {field} in the tile "
            f"body, but get_next_action's primary recommendation has: {sorted(primary)}"
        )
    assert primary["reason"], "the recommendation carries an empty reason"
    assert isinstance(primary["estimated_minutes"], int), (
        f"estimated_minutes is {type(primary['estimated_minutes']).__name__}, which a "
        "prompt cannot put in a tile as minutes"
    )


def test_every_field_the_prompts_name_is_produced_or_declared(guide: str) -> None:
    """Each field a prompt asks the assistant to carry must come from somewhere.

    ``card_hash`` is the one that matters most: the wind-down prompt tells the
    assistant to pass it back to ``record_study_progress``, so if ``get_due_cards``
    stopped returning it, the recorded review would silently go nowhere.
    """
    source = (
        Path(__file__).resolve().parents[2] / "src" / "studyloop" / "mcp" / "tools.py"
    ).read_text(encoding="utf-8")

    assert "card_hash" in guide
    assert "card_hash" in source, (
        "the prompts round-trip card_hash from get_due_cards into "
        "record_study_progress; the MCP layer no longer mentions it"
    )

    # `reason` and the estimate are what make a tile readable rather than a bare
    # title. They come from the recommendation the planner prompt fetches.
    decision = (
        Path(__file__).resolve().parents[2] / "src" / "studyloop" / "learning" / "decision.py"
    ).read_text(encoding="utf-8")
    for field in ("reason", "estimated_minutes"):
        assert field in decision, (
            f"the planner prompt tells the assistant to put the {field} in the tile "
            "body, but the recommendation no longer carries it"
        )


def test_the_prompt_block_count_matches_the_documented_three(guide: str) -> None:
    """Three prompts, said out loud in several places including the skill.

    A fourth prompt appearing without the surrounding prose changing would leave the
    wind-down skill and the website both describing a set that no longer exists.
    """
    xtiles_half = guide.split("## xTiles", 1)[1]
    blocks = re.findall(r"```text\n(.*?)```", xtiles_half, flags=re.DOTALL)
    # Case-insensitive on purpose: the wind-down prompt says "in xTiles" mid-sentence
    # rather than starting with it, and the first version of this filter matched
    # "In xTiles" only — so it reported two prompts and blamed the guide for a
    # defect in the test.
    prompt_blocks = [block for block in blocks if "xtiles" in block.lower()]
    assert len(prompt_blocks) == 3, (
        f"the guide's xTiles half carries {len(prompt_blocks)} prompt blocks, not the "
        "three that the prose, the skill and the website all claim"
    )
    # And each has to be an instruction the learner can hand over verbatim, not a
    # fragment: every one names an xTiles noun to create.
    for block in prompt_blocks:
        assert any(noun in block.lower() for noun in ("task", "project", "page")), (
            f"a prompt block asks the assistant to create nothing: {block[:120]!r}"
        )
