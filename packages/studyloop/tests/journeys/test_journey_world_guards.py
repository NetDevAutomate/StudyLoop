"""Prove the journey world can never reach a real directory.

The journey tests in this package drive the real CLI as subprocesses. A subprocess
does not inherit pytest's fixtures, monkeypatches or autouse isolation — it gets an
environment and nothing else. So every isolation guarantee the unit suite gets for
free has to be re-established here explicitly, and these guards are what prove it.

The specific hazard: `~/Obsidian/Personal` is the hard-coded default vault, and a
journey that published into it would write real files into the owner's real notes.
The unit suite's session-finish hook would notice afterwards; that is too late.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ._world import (
    JourneyWorld,
    UnsafeJourneyWorldError,
    assert_world_is_hermetic,
    journey_world,
)

REAL_VAULT = Path.home() / "Obsidian" / "Personal"
REAL_CONFIG_DIR = Path.home() / ".config" / "studyloop"


@pytest.fixture()
def world(tmp_path):
    with journey_world(tmp_path) as built:
        yield built


def test_the_week_world_cannot_resolve_the_personal_vault(world: JourneyWorld) -> None:
    """The one mistake that would be unrecoverable."""
    assert world.vault.resolve() != REAL_VAULT.resolve()
    assert REAL_VAULT not in world.vault.resolve().parents
    assert str(Path.home()) not in str(world.vault.resolve()) or str(world.root) in str(
        world.vault.resolve()
    )


def test_the_week_world_cannot_resolve_the_real_config_dir(world: JourneyWorld) -> None:
    assert world.config.resolve() != REAL_CONFIG_DIR.resolve()
    assert REAL_CONFIG_DIR not in world.config.resolve().parents


def test_every_world_path_lives_under_the_temp_root(world: JourneyWorld) -> None:
    """Named individually, because a single wrong path is the whole failure."""
    root = world.root.resolve()
    for name in ("home", "config", "plans", "vault", "session_db"):
        candidate = getattr(world, name).resolve()
        assert root in candidate.parents or candidate == root, (
            f"{name} resolves to {candidate}, outside the journey root {root}"
        )


def test_the_week_world_starts_with_no_provider(world: JourneyWorld) -> None:
    """The journey has to be able to enable a provider as its own first act.

    A world that arrived pre-configured would skip the step where a learner
    chooses, which is the step most likely to be wrong.
    """
    result = world.run("brain", "status", "--json")
    assert result.exit_code == 0, result.stderr
    assert json.loads(result.stdout)["provider"] == "none"


def test_the_cli_runs_inside_the_world_not_the_host(world: JourneyWorld) -> None:
    """A subprocess gets an environment, not a fixture.

    Checked by asking the child itself where it thinks HOME is, rather than by
    inspecting the dict we passed — the point is what the child resolves.
    """
    result = world.run_python(
        "import os, pathlib; print(os.environ['HOME']); print(pathlib.Path.home())"
    )
    assert result.exit_code == 0, result.stderr
    reported = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    assert reported, result.stdout
    for line in reported:
        assert str(world.root) in line, f"child resolved {line}, outside the world"


def test_the_environment_handed_to_the_child_names_no_real_directory(
    world: JourneyWorld,
) -> None:
    """Belt and braces: no value in the child env may point at a real StudyLoop dir.

    A path that merely exists in the environment is a path a future code change
    could start reading.
    """
    forbidden = (str(REAL_VAULT), str(REAL_CONFIG_DIR))
    offenders = [
        f"{key}={value}" for key, value in world.env.items() for bad in forbidden if bad in value
    ]
    assert offenders == [], f"child environment reaches real directories: {offenders}"


def test_a_journey_transcript_records_every_command_and_its_output(
    world: JourneyWorld,
) -> None:
    """The transcript is the evidence artefact, so it is part of the contract.

    A transcript missing a step makes the evidence describe a journey nobody ran.
    """
    world.run("brain", "status")
    world.run("plan", "list")
    transcript = world.transcript_text()
    assert "brain status" in transcript
    assert "plan list" in transcript
    assert transcript.count("$ studyloop") == 2, transcript


# ---------------------------------------------------------------------------
# The hermeticity check itself, exercised with deliberately bad input.
#
# Without these, mutating the builder made every guard above ERROR during fixture
# setup — the mistake was caught, but no guard ran to name it, and nothing proved
# the check worked. A guard that only ever sees good input is a guard nobody has
# tested.
# ---------------------------------------------------------------------------


def _safe_env(root: Path) -> dict[str, str]:
    return {
        "PATH": "/usr/bin:/bin",
        "HOME": str(root / "home"),
        "STUDYLOOP_CONFIG": str(root / "config.yaml"),
    }


def test_the_hermeticity_check_accepts_a_world_that_is_hermetic(tmp_path) -> None:
    root = tmp_path / "journey"
    assert_world_is_hermetic(_safe_env(root), root)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("HOME", str(Path.home())),
        ("STUDYLOOP_CONFIG", str(REAL_CONFIG_DIR / "config.yaml")),
        ("STUDYLOOP_SECOND_BRAIN_VAULT", str(REAL_VAULT)),
        ("XDG_STATE_HOME", str(Path.home() / ".local" / "state")),
    ],
    ids=["home", "config", "vault", "state"],
)
def test_the_hermeticity_check_refuses_a_path_outside_the_world(
    tmp_path, key: str, value: str
) -> None:
    """Each of the four ways a real directory has actually leaked in before."""
    root = tmp_path / "journey"
    env = _safe_env(root) | {key: value}
    with pytest.raises(UnsafeJourneyWorldError, match=r"points outside the world"):
        assert_world_is_hermetic(env, root)


def test_the_hermeticity_check_refuses_an_inherited_virtualenv(tmp_path) -> None:
    """A child with VIRTUAL_ENV set may resolve the host's packages, not the repo's.

    Every gate in this repo is run with `env -u VIRTUAL_ENV` for this reason, and a
    world that quietly reinstated it would test a different StudyLoop than the one
    under change.
    """
    root = tmp_path / "journey"
    env = _safe_env(root) | {"VIRTUAL_ENV": "/somewhere/.venv"}
    with pytest.raises(UnsafeJourneyWorldError, match=r"VIRTUAL_ENV"):
        assert_world_is_hermetic(env, root)


def test_the_check_does_not_exempt_a_key_merely_for_looking_like_a_path(
    tmp_path,
) -> None:
    """Only PATH and PYTHONPATH are exempt, and the exemption is a closed set.

    A prefix rule ("anything ending in _PATH") would have exempted
    STUDYLOOP_SECOND_BRAIN_VAULT's sibling `vault_path` spellings, which is exactly
    the value that must never point at a real vault.
    """
    from ._world import _EXEMPT_KEYS

    assert frozenset({"PATH", "PYTHONPATH"}) == _EXEMPT_KEYS


def test_the_transcript_carries_no_username_or_home_path(world: JourneyWorld) -> None:
    """Evidence artefacts must not name the person who ran them.

    Found by reading the first real transcript rather than by reasoning: a pytest
    temp path is ``/private/var/.../pytest-of-<username>/…``, so every command line
    in the bundle carried the operator's account name. It looked like scaffolding,
    which is exactly why it would have shipped — the plan forbids personal data in
    any artefact, and a username is personal data.
    """
    world.run("brain", "enable", "obsidian", "--vault", str(world.vault))
    world.run("brain", "publish", "--dry-run")
    transcript = world.transcript_text()

    assert str(world.root) not in transcript, "the temp root leaked into the transcript"
    assert "pytest-of-" not in transcript or "pytest-of-<user>" in transcript
    username = Path.home().name
    assert username not in transcript, (
        f"the operator's account name ({username!r}) is in the evidence transcript"
    )
    assert "<world>" in transcript, "paths were not redacted to a placeholder"


def test_redaction_leaves_the_vault_relative_paths_a_reader_needs(
    world: JourneyWorld,
) -> None:
    """Redaction must not remove the thing the transcript is for.

    The whole value of the bundle is that a human can see which notes were written.
    A redactor that swallowed `Study/Today.md` along with the machine path would
    produce a clean, useless artefact.
    """
    world.run("brain", "enable", "obsidian", "--vault", str(world.vault))
    world.run("brain", "publish")
    transcript = world.transcript_text()
    # Today is the one note a publish always writes, with or without a plan.
    assert "Study/Today.md" in transcript, transcript
    assert "<world>/vault" in transcript, "the vault was redacted past usefulness"
