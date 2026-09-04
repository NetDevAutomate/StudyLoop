"""The xTiles learner's day, on StudyLoop's side of the boundary.

StudyLoop never talks to xTiles. So the journey a test can honestly walk ends at the
assistant: choose the provider, do a day's studying, and find out what StudyLoop
will and will not do for you. What happens in xTiles afterwards belongs to
``test_xtiles_live.py``, which observes it in a browser and is not re-walked here.

The experience being tested is the one most likely to be wrong, because it is the
one where the software has to say *no* usefully. A learner who has chosen xTiles
runs ``brain publish`` — probably at the end of every session, since the wind-down
protocol may call it — and gets nothing written. That has to read as "this provider
works through your assistant", not as a failure, an empty success, or a crash.

`test_xtiles_journey.py` already proves the setup sequence and that exactly one file
changes. This file starts after that: a study day, and the two promises that matter
across it — nothing written, no credential kept.
"""

from __future__ import annotations

import json

import pytest

from ._world import JourneyWorld, evidence_root, journey_world, write_evidence

PLAN_ID = "python-decorators"

#: Anything matching these in the world after a day is a credential StudyLoop kept.
CREDENTIAL_HINTS = ("XTILES_", "PASSWORD", "TOKEN", "SECRET", "BEARER")


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
        "--activate",
    )
    assert result.exit_code == 0, result.output


def test_a_study_day_when_the_provider_cannot_publish(world: JourneyWorld) -> None:
    """A day's work, and the refusal that has to read as a design rather than a fault."""
    _seed_plan(world)
    world.note("00 plan created")

    enabled = world.run("brain", "enable", "xtiles")
    assert enabled.exit_code == 0, enabled.output
    world.note("01 xtiles chosen")

    # -- the learner is told what this provider is, in words ---------------
    # The JSON shape is already pinned by test_second_brain_cli_core.py. What is
    # unproven is whether the HUMAN output explains the arrangement.
    status = world.run("brain", "status")
    assert status.exit_code == 0, status.output
    human = status.output
    assert "xtiles" in human.lower(), f"status does not name the provider:\n{human}"
    assert "not configured" not in human.lower(), (
        f"status says unconfigured after enabling xtiles:\n{human}"
    )
    world.note("02 status explained the provider")

    # -- a day's studying, which must be unaffected by the provider --------
    progress = world.run(
        "progress",
        "functools.wraps",
        "--topic",
        PLAN_ID,
        "--confidence",
        "learning",
    )
    assert progress.exit_code == 0, (
        "recording progress broke because a second brain was configured:\n" + progress.output
    )
    world.note("03 recorded a day's progress")

    # -- the refusal, which a wind-down may run every single session -------
    published = world.run("brain", "publish")
    assert published.exit_code == 0, (
        "publish exited non-zero for a provider that cannot publish. A wind-down "
        "runs this unconditionally, so this is a nightly failure the learner "
        "cannot fix:\n" + published.output
    )
    assert published.output.strip(), (
        "publish printed nothing at all, which reads as a hang or a swallowed error"
    )
    lowered = published.output.lower()
    assert "traceback" not in lowered and "notimplemented" not in lowered, (
        f"publish leaked an implementation detail at the learner:\n{published.output}"
    )
    # It has to point somewhere. A skip with no next step leaves the learner stuck
    # holding a provider they chose on purpose.
    assert any(
        pointer in lowered for pointer in ("assistant", "second brain", "docs", "guide", "mcp")
    ), (
        "publish skipped without telling the learner how xTiles actually receives "
        f"anything:\n{published.output}"
    )
    world.note("04 publish skipped, with a next step")

    # -- and it really wrote nothing, anywhere -----------------------------
    assert world.vault_tree() == [], f"an xTiles publish wrote into the vault: {world.vault_tree()}"
    stray = [
        path.relative_to(world.root).as_posix()
        for path in world.root.rglob("Study")
        if path.is_dir()
    ]
    assert stray == [], f"a Study/ directory appeared somewhere in the world: {stray}"
    world.note("05 nothing written anywhere")

    # -- pulling is equally not an error -----------------------------------
    pulled = world.run("brain", "pull", PLAN_ID, "--json")
    assert pulled.exit_code == 0, pulled.output
    assert json.loads(pulled.stdout)["found"] is False
    world.note("06 pull reported nothing found, without failing")

    write_evidence(world, evidence_root() / "xtiles-week", {})


def test_the_xtiles_week_stores_no_credential(world: JourneyWorld) -> None:
    """The feature's headline promise, checked with a canary over a whole day.

    ``test_second_brain_no_credentials.py`` snapshots the secrets directory around
    individual operations. This asks a different question: after a learner has chosen
    xTiles and worked for a day, is there anything credential-shaped anywhere in
    their world?

    Rewritten after a validation council found the first version unable to fail. It
    skipped ``.db`` files, matched case-sensitively, and looked for five fixed
    plaintext words — so a lowercase ``token``, a value under a different key, or
    anything written into ``sessions.db`` passed. Now a unique canary is planted in
    the environment on the way in, and every byte of the world is searched for it,
    databases included.
    """
    # A value nothing legitimate could contain, planted where a careless
    # implementation would pick it up: the child's own environment.
    canary = "stdyl00p-canary-6f2b9c4e-must-never-be-written"
    world.env["XTILES_PASSWORD"] = canary
    world.env["XTILES_USERNAME"] = f"canary-{canary}@example.invalid"

    _seed_plan(world)
    assert world.run("brain", "enable", "xtiles").exit_code == 0
    assert world.run("brain", "publish").exit_code == 0
    assert world.run("brain", "status", "--json").exit_code == 0
    assert (
        world.run("progress", "closures", "--topic", PLAN_ID, "--confidence", "confident").exit_code
        == 0
    )

    needle = canary.encode()
    # Raw bytes, every file, nothing skipped. A SQLite page holding the canary is
    # every bit as much a leak as a YAML line holding it, and the first version of
    # this test excluded exactly the file most likely to hold one.
    leaked = [
        path.relative_to(world.root).as_posix()
        for path in sorted(world.root.rglob("*"))
        if path.is_file() and needle in path.read_bytes()
    ]
    assert leaked == [], f"the canary credential was written to: {leaked}"

    # Case-insensitive, and on the whole file rather than a word list, so a key named
    # anything at all is caught.
    suspicious: list[str] = []
    for path in sorted(world.root.rglob("*")):
        if not path.is_file():
            continue
        blob = path.read_bytes().lower()
        for hint in (b"xtiles_password", b"xtiles_username", b"bearer ", b"secret_key"):
            if hint in blob:
                suspicious.append(f"{path.relative_to(world.root).as_posix()}: {hint!r}")
    assert suspicious == [], f"something credential-shaped was stored: {suspicious}"

    # And no secrets store was created at all. StudyLoop has one, and this feature's
    # promise is that it never reaches for it.
    stores = [
        path.relative_to(world.root).as_posix()
        for path in world.root.rglob("*")
        if path.is_file()
        and any(part in path.name.lower() for part in ("secret", "credential", "token"))
    ]
    assert stores == [], f"a credential store was created: {stores}"


def test_the_canary_check_can_actually_fail(world: JourneyWorld, tmp_path) -> None:
    """Prove the search would find a leak, rather than trusting that it would.

    The previous version of the credential test could not have failed for several
    reasons at once, and nothing revealed that because no leak was ever present to
    find. This plants one deliberately — including inside a SQLite file, the case the
    old test explicitly skipped — and asserts the same search catches it.
    """
    import sqlite3

    canary = "stdyl00p-canary-6f2b9c4e-must-never-be-written"
    needle = canary.encode()

    plain = world.root / "leaked.yaml"
    plain.write_text(f"xtiles_password: {canary}\n", encoding="utf-8")

    database = world.root / "leaked.db"
    connection = sqlite3.connect(database)
    try:
        connection.execute("CREATE TABLE t (v TEXT)")
        connection.execute("INSERT INTO t VALUES (?)", (canary,))
        connection.commit()
    finally:
        connection.close()

    found = [
        path.relative_to(world.root).as_posix()
        for path in sorted(world.root.rglob("*"))
        if path.is_file() and needle in path.read_bytes()
    ]
    assert "leaked.yaml" in found, "the byte search misses a plaintext leak"
    assert "leaked.db" in found, (
        "the byte search misses a leak inside SQLite — which is the file the first "
        "version of this test excluded"
    )
