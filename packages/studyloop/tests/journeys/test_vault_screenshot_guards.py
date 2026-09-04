"""Guards on the vault screenshot script.

The script produces images intended for a public website, from a hermetic world, and
labels them as not being Obsidian. Each of those three properties can silently stop
being true, and the last one is the one that would matter: an image a reader
recognises as an app, that is not that app, is a false claim in the same family as
the prose claims this campaign kept finding by review rather than by CI.

The script is not a test, so these guards read it as text and as an AST.
"""

from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[4] / "scripts" / "capture-vault-screenshots.py"

#: Headings the projections always carry, present before any data arrives. A shot
#: gated on one of these photographs an empty note and calls it a success.
HEADINGS = frozenset(
    {
        "Today",
        "Next action",
        "Due reviews",
        "Active topics",
        "Mission",
        "Why",
        "Milestones",
        "Learning Records",
        "Resources",
        "Checkpoints",
        "Notes",
        "Success looks like",
        "Constraints",
        "Out of scope",
    }
)


@pytest.fixture(scope="module")
def source() -> str:
    return SCRIPT.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def module():
    """Import the script by path — it is a script, not a package member."""
    spec = importlib.util.spec_from_file_location("capture_vault_screenshots", SCRIPT)
    assert spec and spec.loader
    loaded = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = loaded
    spec.loader.exec_module(loaded)
    return loaded


def test_the_script_exists(source: str) -> None:
    assert source.strip(), f"missing {SCRIPT}"


def test_every_shot_gates_on_content_not_a_heading(module) -> None:
    """The trap this guard exists for, walked into while writing the script.

    The Today shot was first gated on ``"Next action"`` — a heading, always present.
    It produced a picture of three empty states, which is exactly what the website's
    first Web UI screenshots did before the same mistake was caught there. A heading
    proves the renderer ran; only content proves there was anything to render.
    """
    offenders = [
        f"{shot.filename}: expect={shot.expect!r}"
        for shot in module.SHOTS
        if shot.expect.strip() in HEADINGS
    ]
    assert offenders == [], (
        "a shot is gated on a heading, so it would happily photograph an empty "
        "note:\n" + "\n".join(offenders)
    )


def test_every_shot_expects_something_substantial(module) -> None:
    """A two-character expectation is not a gate."""
    for shot in module.SHOTS:
        assert len(shot.expect) >= 8, (
            f"{shot.filename} expects {shot.expect!r}, short enough to match by accident"
        )


def test_the_footer_says_these_are_not_obsidian(module, source: str) -> None:
    """The disclaimer has to travel with the pixels.

    A caption in the surrounding page can be cropped off or recycled with new words.
    The claim that this is not Obsidian is the one claim that must survive the image
    being copied somewhere else.
    """
    assert "not Obsidian" in module.FOOTER, (
        f"the in-pixel footer no longer disclaims Obsidian: {module.FOOTER!r}"
    )
    assert "FOOTER" in source
    tree = ast.parse(source, filename=str(SCRIPT))
    rendered_with_footer = any(
        isinstance(node, ast.Name) and node.id == "FOOTER"
        for function in ast.walk(tree)
        if isinstance(function, ast.FunctionDef) and function.name == "_render"
        for node in ast.walk(function)
    )
    assert rendered_with_footer, (
        "_render no longer puts FOOTER into the page, so the disclaimer is a constant nobody draws"
    )


def test_no_obsidian_chrome_is_imitated(source: str) -> None:
    """The page must not pretend to be the application.

    Allowed: the word Obsidian inside the disclaimer and in the module docstring
    that explains the decision. Not allowed: a sidebar, a ribbon, a tab bar, a
    titlebar — the furniture that would make a reader believe they are looking at a
    screenshot of the app.
    """
    lowered = source.lower()
    for furniture in ("ribbon", "titlebar", "title-bar", "tab-bar", "vault-switcher"):
        assert furniture not in lowered, (
            f"the preview draws {furniture!r}, which imitates Obsidian's interface"
        )

    # The word itself may appear only where it is being disclaimed or discussed.
    tree = ast.parse(source, filename=str(SCRIPT))
    style_strings = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]
    css = [value for value in style_strings if "{" in value and ":" in value]
    for block in css:
        assert "obsidian" not in block.lower(), (
            "a stylesheet mentions Obsidian, which suggests it is styling itself to look like it"
        )


def test_the_capture_goes_through_the_hermetic_builder(source: str, module) -> None:
    """Renamed, because the old name claimed more than the test did.

    A validation council pointed out the previous version never invoked the script
    with a poisoned ``HOME`` — it statically found ``journey_world`` and then, quite
    separately, tested ``assert_world_is_hermetic`` with unrelated input. Two true
    statements that did not add up to the claim in the name.

    This asserts the mechanism honestly: the script builds its world through
    ``journey_world``, which refuses any path outside the world. The end-to-end
    refusal is covered by
    ``test_the_script_refuses_to_publish_into_a_real_looking_vault`` below.
    """
    tree = ast.parse(source, filename=str(SCRIPT))
    calls = [
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    ]
    assert "journey_world" in calls, (
        "the script does not build its vault through journey_world, so nothing "
        "stops it from publishing into a real one"
    )

    from ._world import UnsafeJourneyWorldError, assert_world_is_hermetic

    with pytest.raises(UnsafeJourneyWorldError):
        assert_world_is_hermetic({"HOME": str(Path.home())}, Path("/tmp/nowhere"))


def test_the_script_publishes_through_the_real_cli(source: str) -> None:
    """The picture has to be of what the product writes, not of what the script draws.

    If the script ever renders markdown it composed itself, the image stops being
    evidence of anything.

    Parsed rather than grepped: the first version searched for the literal
    ``'"plan", "new"'`` and failed the moment the formatter split that call across
    lines. A formatting-sensitive guard is a guard that goes red for the wrong reason
    and then gets deleted.
    """
    tree = ast.parse(source, filename=str(SCRIPT))
    commands = {
        tuple(
            argument.value
            for argument in node.args
            if isinstance(argument, ast.Constant) and isinstance(argument.value, str)
        )
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "run"
    }
    firsts = {command[:2] for command in commands if len(command) >= 2}

    assert ("brain", "publish") in firsts, (
        "the script no longer publishes through the CLI, so the notes in the "
        f"picture were not written by StudyLoop. Commands found: {sorted(firsts)}"
    )
    assert ("plan", "new") in firsts, (
        f"the plan in the picture was not created by the CLI. Found: {sorted(firsts)}"
    )
    assert ("brain", "enable") in firsts, "the script does not enable the provider through the CLI"


def test_a_shot_with_no_content_is_skipped_not_faked(source: str) -> None:
    """A missing note must produce no file, and say so."""
    assert "refusing to publish a picture of an" in source, (
        "the script no longer explains why it skipped a shot"
    )
    assert "skipped.append" in source


def test_the_script_refuses_to_publish_into_a_real_looking_vault(tmp_path) -> None:
    """Run the real builder with a poisoned root and watch it refuse.

    The end-to-end half the renamed guard above does not cover. A council found the
    original claiming the script "refuses a real home" while never invoking anything
    with a real home, so this invokes the actual world builder the script uses, with
    a root that would put the child's ``HOME`` outside itself.
    """
    from ._world import UnsafeJourneyWorldError, journey_world

    # `journey_world` derives every path from the root it is given. Handing it the
    # real home as a root is the closest thing to the mistake being guarded against:
    # a caller who passes a path they should not.
    #
    # This test found a real hole on its first run. Every other check compares a
    # value against the root, so a root of `~/journey` satisfied all of them — and
    # the builder created `~/journey/home` and `~/journey/vault` in the operator's
    # own directory before anything complained. The root is now checked itself.
    with (
        pytest.raises(UnsafeJourneyWorldError, match=r"inside the operator's home"),
        journey_world(Path.home()) as world,
    ):
        # If we ever get here, the builder accepted a world whose HOME is the
        # operator's own. Say so with the resolved path rather than a bare fail.
        msg = f"builder accepted a world at {world.home}"
        raise AssertionError(msg)


def test_a_partial_screenshot_set_is_not_reported_as_success(source: str) -> None:
    """Two of three shots missing used to exit 0.

    A docs build could then publish an incomplete set and see a green step. Partial
    is now something the caller asks for by name.
    """
    assert "--allow-partial" in source, "there is no way to opt into a partial set"
    assert "allow_partial" in source
    tree = ast.parse(source, filename=str(SCRIPT))
    main = next(
        node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "main"
    )
    guarded = any(
        isinstance(node, ast.If)
        and "allow_partial" in ast.dump(node.test)
        and "skipped" in ast.dump(node.test)
        for node in ast.walk(main)
    )
    assert guarded, (
        "main() does not gate its exit status on whether shots were skipped, so a "
        "partial set still reports success"
    )
