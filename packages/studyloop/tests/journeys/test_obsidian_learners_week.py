"""The Obsidian learner's week, as one ordered journey.

Every value asserted here is already proven somewhere in the unit suite. That is
deliberate and it is the point: this file asserts on **what the learner is told**,
which no unit test does. A publish that writes the right bytes and says nothing is
a correct function and a broken experience, and only a test at this level can tell
the difference.

One test, not twelve. The thing under test is the *sequence* — a plan published,
read, annotated, pulled, folded back, republished — and a suite of independent steps
cannot fail on incoherence. The beats are numbered, and the numbers match the
evidence transcript, so a failure names the beat a human can go and look at.

Chosen by three independent planners from different model families; the reasoning is
in `reviews/2026-09-04-user-harness/PLAN.md`.
"""

from __future__ import annotations

import re

import pytest

from ._world import JourneyWorld, evidence_root, journey_world, write_evidence

PLAN_ID = "python-decorators"
TITLE = "Python Decorators"
WHY = "Decorators keep appearing in the codebases I read, and I skip them."
LEARNER_NOTE = "I keep mixing wraps with partial."

#: The two files a first publish creates, as the shipped guide documents them.
TODAY = "Study/Today.md"
PROJECTION = f"Study/Plans/{PLAN_ID}.md"
LEARNER_NOTES_FILE = f"Study/Plans/{PLAN_ID}.notes.md"

#: The three headings the guide promises in Today.
TODAY_HEADINGS = ("## Next action", "## Due reviews", "## Active topics")


@pytest.fixture()
def world(tmp_path):
    with journey_world(tmp_path) as built:
        yield built


def _seed_plan(world: JourneyWorld) -> None:
    """Create the plan the way a learner does, through the real CLI.

    Not through the planning API. Two of the three planners named "is `plan new`
    interactive?" as their highest-risk assumption, because seeding through the API
    would mean the journey starts one step after the learner does. Measured: it is
    fully non-interactive, so the journey starts where they start.
    """
    result = world.run(
        "plan",
        "new",
        "--title",
        TITLE,
        "--why",
        WHY,
        "--topic",
        PLAN_ID,
        "--success",
        "I can explain what functools.wraps preserves, without looking it up",
        "--milestone",
        "Read and explain a decorator someone else wrote (concepts: closures)",
        "--milestone",
        "Write a timing decorator from scratch (concepts: functools.wraps)",
        "--activate",
    )
    assert result.exit_code == 0, result.output
    assert PLAN_ID in result.output, (
        "plan new did not print the id every later command needs: " + result.output
    )


def test_a_learners_week_in_order(world: JourneyWorld) -> None:
    """Twelve beats. Each is a claim about the experience, not about a value."""
    digests: list[tuple[str, str | None]] = []

    def remember(beat: str) -> None:
        """Beat 9: the learner's own file is checked after every single step."""
        digests.append((beat, world.digest(LEARNER_NOTES_FILE)))
        world.note(beat)

    _seed_plan(world)
    remember("00 plan created through the CLI")

    enabled = world.run("brain", "enable", "obsidian", "--vault", str(world.vault))
    assert enabled.exit_code == 0, enabled.output
    remember("01 obsidian enabled")

    # -- beat 1: the dry run must preview ----------------------------------
    dry = world.run("brain", "publish", "--dry-run")
    assert dry.exit_code == 0, dry.output
    for expected in (TODAY, PROJECTION):
        assert expected in dry.output, (
            f"beat 1: the dry run did not name {expected}, so the learner cannot "
            f"preview what it would do. Output was:\n{dry.output}"
        )
    assert world.vault_tree() == [], f"beat 1: the dry run wrote files: {world.vault_tree()}"
    remember("02 dry run previewed and wrote nothing")

    # -- beat 2: the dry run must not lie ----------------------------------
    previewed = [detail for status, detail in dry.results() if status == "would write"]
    published = world.run("brain", "publish")
    assert published.exit_code == 0, published.output
    announced = [detail for status, detail in published.results() if status == "written"]
    written = set(world.vault_tree())
    # Exact, ordered equality. A set comparison let an extra write through, and
    # `previewed <= written` would have passed a publish that wrote three files after
    # promising two — which is the exact surprise a dry run exists to prevent.
    assert previewed == announced, (
        f"beat 2: the dry run promised {previewed} and the publish announced "
        f"{announced} — a preview that surprises you is worse than none"
    )
    assert set(previewed) == written, (
        f"beat 2: the report says {sorted(set(previewed))} but the vault holds {sorted(written)}"
    )

    # -- beat 3: the first publish must say where -------------------------
    for expected in (TODAY, PROJECTION):
        statuses = published.statuses_for(expected)
        assert statuses == ["written"], (
            f"beat 3: publish reported {statuses or 'nothing'} for {expected}, not a "
            f"single 'written'. Output was:\n{published.output!r}"
        )
    remember("03 published, and said where")

    # -- beat 4: the files must be where the guide says --------------------
    # The exact set. Two spot checks passed a vault with extra or duplicated notes
    # in it, and an unexpected file in someone's vault is exactly the complaint this
    # feature has to avoid.
    assert written == {TODAY, PROJECTION}, (
        f"beat 4: a first publish should leave exactly {sorted({TODAY, PROJECTION})}, "
        f"but the vault holds {sorted(written)}"
    )

    # -- beat 5: Today must be readable -----------------------------------
    today = world.read(TODAY)
    for heading in TODAY_HEADINGS:
        assert heading in today, f"beat 5: Today is missing {heading}:\n{today}"
    next_action = today.split(TODAY_HEADINGS[0], 1)[1].split("\n## ", 1)[0]
    # Exactly one action, and it has to carry a duration. "any non-blank line" passed
    # a section holding three actions, or prose with no action at all — either of
    # which defeats the one thing Today is for.
    bullets = [
        line.strip()
        for line in next_action.splitlines()
        if line.strip().startswith("- ") and "**" in line
    ]
    assert len(bullets) == 1, (
        f"beat 5: Today should name exactly one next action; found {len(bullets)}:\n" + next_action
    )
    assert re.search(r"\d+\s*min", bullets[0]), (
        f"beat 5: the next action carries no estimate, so a learner cannot decide "
        f"whether they have time for it: {bullets[0]!r}"
    )

    # -- beat 6: the plan must look like the plan they wrote ---------------
    projection = world.read(PROJECTION)
    for fragment in (TITLE, WHY, "Write a timing decorator from scratch"):
        assert fragment in projection, (
            f"beat 6: the projection does not show {fragment!r}, so it does not "
            "look like the plan the learner wrote"
        )
    remember("04 read Today and the projection")

    # -- beat 8: a missing note must not look like a crash ----------------
    # Before beat 7, because the learner has not written anything yet.
    early_pull = world.run("brain", "pull", PLAN_ID)
    assert early_pull.exit_code == 0, (
        "beat 8: pulling a note that does not exist yet exited non-zero:\n" + early_pull.output
    )
    lines = [line for line in early_pull.output.splitlines() if line.strip()]
    assert len(lines) == 1, (
        "beat 8: pulling a missing note should say one plain thing; it printed "
        f"{len(lines)} lines:\n{early_pull.output}"
    )
    # "any non-empty output that is not a traceback" accepted `Error: failed`, which
    # is precisely the impression this beat exists to rule out.
    lowered = lines[0].lower()
    for scary in ("traceback", "error", "exception", "failed", "fatal"):
        assert scary not in lowered, (
            f"beat 8: a note the learner has not written yet is not an error, but "
            f"the message says {scary!r}: {lines[0]!r}"
        )
    assert LEARNER_NOTES_FILE in lines[0], (
        f"beat 8: the message does not say which file it looked for: {lines[0]!r}"
    )
    remember("05 pulled before writing anything")

    # -- beat 7: pull must return THEIR note, not StudyLoop's --------------
    (world.vault / LEARNER_NOTES_FILE).write_text(
        f"# My notes\n\n{LEARNER_NOTE}\n\nAsk the mentor about decorator factories.\n",
        encoding="utf-8",
    )
    remember("06 learner wrote their own notes file")
    pulled = world.run("brain", "pull", PLAN_ID)
    assert pulled.exit_code == 0, pulled.output
    assert LEARNER_NOTE in pulled.output, (
        f"beat 7: pull did not return the learner's own sentence:\n{pulled.output}"
    )
    for marker in ("studyloop:", "owned: true", "content_hash"):
        assert marker not in pulled.output, (
            f"beat 7: pull leaked StudyLoop's own frontmatter ({marker}) — it read "
            "the projection instead of the learner's note"
        )
    remember("07 pulled the learner's note")

    # -- beat 10: a vanished edit must be explained by name ----------------
    (world.vault / PROJECTION).write_text(
        projection + "\n\nI typed this into the projection by mistake.\n",
        encoding="utf-8",
    )
    republished = world.run("brain", "publish")
    assert republished.exit_code == 0, republished.output
    assert "I typed this into the projection by mistake." not in world.read(PROJECTION), (
        "beat 10: an edited projection survived a republish, so the source is not "
        "the source of truth"
    )
    # The BLOCKER a validation council found: "names the file" was satisfied by
    # `written Study/Plans/<id>.md`, which is character for character what a first
    # publish prints. The learner's ten minutes of typing vanished behind a success
    # line. The product now reports this case distinctly; this asserts the learner
    # is actually told.
    statuses = republished.statuses_for(PROJECTION)
    assert "warning" in statuses, (
        "beat 10: the learner's edit was discarded and the output reported "
        f"{statuses} — indistinguishable from an ordinary write:\n"
        f"{republished.output}"
    )
    warning_line = next(detail for status, detail in republished.results() if status == "warning")
    assert "edit" in warning_line.lower() or "replaced" in warning_line.lower(), (
        f"beat 10: the warning does not say what happened to their text: {warning_line!r}"
    )
    assert ".notes.md" in warning_line, (
        "beat 10: the warning tells the learner their edit is gone without telling "
        f"them where their own writing belongs: {warning_line!r}"
    )
    remember("08 projection edit replaced, and named")

    # -- beat 11: an unchanged republish must say so -----------------------
    quiet = world.run("brain", "publish")
    assert quiet.exit_code == 0, quiet.output
    quiet_results = quiet.results()
    assert quiet_results, (
        "beat 11: republishing an unchanged plan printed nothing, so the learner "
        "cannot tell it worked from it hanging"
    )
    # Every expected path reported unchanged, and NOTHING reported written. Checking
    # only that the word "unchanged" appeared passed output that also claimed three
    # writes.
    for expected in (TODAY, PROJECTION):
        assert quiet.statuses_for(expected) == ["unchanged"], (
            f"beat 11: {expected} was reported as "
            f"{quiet.statuses_for(expected)} on an unchanged republish:\n{quiet.output}"
        )
    assert [status for status, _ in quiet_results if status in {"written", "replaced"}] == [], (
        f"beat 11: an unchanged republish claimed it wrote something:\n{quiet.output}"
    )
    remember("09 unchanged republish said so")

    # -- beat 12: a fold-in must be visible -------------------------------
    before_pct = _progress_pct(world.read(PROJECTION))
    folded = world.run("plan", "milestone", PLAN_ID, "0", "--done")
    assert folded.exit_code == 0, folded.output
    after = world.run("brain", "publish")
    assert after.exit_code == 0, after.output
    final = world.read(PROJECTION)
    after_pct = _progress_pct(final)
    # Exact, not merely different: "the number moved" passed an arbitrary change,
    # and the reader's whole question is *how far along am I*. One of two milestones
    # done is 50%.
    assert after_pct == "progress_pct: 50", (
        f"beat 12: one of two milestones is done, so the projection should read "
        f"progress_pct: 50; it reads {after_pct!r} (was {before_pct!r})"
    )
    # And the milestone must be RENDERED as done, not merely still present.
    milestone_line = next(
        (
            line
            for line in final.splitlines()
            if "Read and explain a decorator someone else wrote" in line
        ),
        None,
    )
    assert milestone_line is not None, (
        "beat 12: the completed milestone vanished from the projection instead of "
        "being shown as done"
    )
    assert milestone_line.strip().startswith("- [x]"), (
        f"beat 12: the milestone is present but not shown as done: {milestone_line!r}"
    )
    remember("10 milestone folded in and visible")

    # -- beat 9: the learner's file was never touched ----------------------
    recorded = [digest for _, digest in digests if digest is not None]
    assert recorded, "beat 9: the learner's note was never observed at all"
    assert len(set(recorded)) == 1, (
        "beat 9: the learner's own notes file changed during the week. Digest per "
        "beat:\n" + "\n".join(f"  {beat}: {digest}" for beat, digest in digests)
    )

    # Evidence last: a bundle written mid-run describes a pass that may not have
    # happened. Same lesson as test_obsidian_live.py.
    write_evidence(
        world,
        evidence_root() / "obsidian-week",
        {
            "Today.md": world.read(TODAY),
            "plan-projection.md": final,
            "learner-note.md": world.read(LEARNER_NOTES_FILE),
            "notes-digest-log.txt": (
                "The learner's own notes file, digested after every beat.\n"
                "One distinct value after it first appears means nothing touched it.\n\n"
                + "\n".join(f"{beat}: {digest or '(absent)'}" for beat, digest in digests)
                + "\n"
            ),
        },
    )


def _progress_pct(projection: str) -> str:
    """The derived progress the reader actually sees in the frontmatter."""
    for line in projection.splitlines():
        if line.startswith("progress_pct:"):
            return line.strip()
    return "(absent)"
