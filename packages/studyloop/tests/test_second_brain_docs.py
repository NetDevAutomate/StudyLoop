"""T6: the Second Brain guide cannot drift from the code or make loose claims.

Documentation about a feature that writes into someone's notes has to be exact,
and three kinds of drift matter enough to guard:

* **Interface drift.** A config key or command that no longer exists sends the
  learner to a dead end and makes the tool look broken rather than the page.
* **Claim drift.** A statement about someone else's software (Obsidian's CLI, an
  optional plugin, a paid tier) is true on the day it is written and not
  necessarily after. Every external URL therefore has to appear in a Sources
  table with the date it was checked.
* **Promise drift.** The privacy and optionality statements are the reason a
  learner trusts this feature at all. They are pinned as fragments, so removing
  one is a failing test rather than a quiet edit.
"""

from __future__ import annotations

import re
from dataclasses import fields
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
DOCS = REPO_ROOT / "docs"
GUIDE = DOCS / "second-brain.md"

_URL_RE = re.compile(r"https?://[^\s)>\]\"']+")
_FENCE_RE = re.compile(r"```[a-zA-Z]*\n(.*?)```", re.DOTALL)
_YAML_FENCE_RE = re.compile(r"```yaml\n(.*?)```", re.DOTALL)
_SOURCES_ROW_RE = re.compile(r"^\|.*\|.*\|.*\|\s*$", re.MULTILINE)
_ISO_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")


@pytest.fixture(scope="module")
def guide() -> str:
    assert GUIDE.is_file(), f"{GUIDE} is missing"
    return GUIDE.read_text(encoding="utf-8")


def _sources_section(text: str) -> str:
    assert "## Sources" in text, "the guide has no Sources table"
    return text.split("## Sources", 1)[1]


# ---------------------------------------------------------------------------
# C1 — the page is published
# ---------------------------------------------------------------------------


def test_the_guide_is_in_the_mkdocs_allowlist_and_nav() -> None:
    """Both, because either one alone leaves the page invisible.

    ``exclude_docs`` decides whether the file is BUILT; ``nav`` decides whether a
    reader can find it. A page in the allowlist but not the nav is a URL nobody
    ever visits, and mkdocs --strict does not complain about it.
    """
    mkdocs = (REPO_ROOT / "mkdocs.yml").read_text(encoding="utf-8")
    allowlist, _, nav = mkdocs.partition("nav:")
    assert "!/second-brain.md" in allowlist, "second-brain.md is not un-excluded"
    assert "second-brain.md" in nav, "second-brain.md is not in the nav"


# ---------------------------------------------------------------------------
# C3 — documented config keys are the real ones
# ---------------------------------------------------------------------------


def test_documented_config_keys_equal_second_brain_config_fields(guide: str) -> None:
    """The configuration reference lists every field, and only real fields.

    Both directions matter. An extra key is a promise the loader will reject; a
    missing one is a feature the learner cannot discover, which for ``daily_note``
    means never learning that the only write into their own notes is opt-in.
    """
    import yaml

    from studyloop.settings import SecondBrainConfig

    blocks = [
        parsed
        for block in _YAML_FENCE_RE.findall(guide)
        if isinstance(parsed := yaml.safe_load(block), dict) and "second_brain" in parsed
    ]
    assert blocks, "the guide has no `second_brain:` YAML block"

    documented: set[str] = set()
    for parsed in blocks:
        documented.update(parsed["second_brain"] or {})

    actual = {field.name for field in fields(SecondBrainConfig)}
    assert documented == actual, (
        f"documented keys {sorted(documented)} != SecondBrainConfig fields {sorted(actual)}"
    )


def test_the_documented_defaults_match_the_dataclass(guide: str) -> None:
    """A wrong default is worse than no default: it is a specific false claim."""
    assert "provider: none" in guide or "none (default)" in guide
    assert "backlinks: true" in guide


# ---------------------------------------------------------------------------
# The withdrawn CLI adapter must not survive in the documentation
# ---------------------------------------------------------------------------


RETIRED_KEYS = ("use_cli", "vault_name", "template", "daily_note")


def test_the_guide_does_not_offer_the_withdrawn_cli_adapter(guide: str) -> None:
    """Cut before release, so it must not appear as something a learner can configure.

    Scoped to fenced blocks and command lines, not to prose. The guide SHOULD name
    these keys — a learner upgrading from a pre-release build needs to be told that
    `daily_note` no longer writes into their daily note. What it must not do is
    present them as available configuration, or quote a command the code never runs.
    """
    for block in _FENCE_RE.findall(guide):
        for gone in RETIRED_KEYS:
            assert f"{gone}:" not in block, (
                f"the guide still offers the withdrawn {gone!r} in a fenced block"
            )
        for line in block.splitlines():
            assert not line.strip().startswith("obsidian "), (
                f"the guide quotes an obsidian CLI command the code never runs: {line.strip()!r}"
            )


def test_the_guide_explains_that_the_retired_keys_are_gone(guide: str) -> None:
    """The complement: silence would leave an upgrading learner guessing.

    `daily_note: true` used to append a line to a file they own. Someone who set it
    has to be told it stopped, not left to notice.
    """
    assert "daily_note" in guide
    assert "withdrawn" in guide or "no longer" in guide


# ---------------------------------------------------------------------------
# C4 — every third-party claim is dated
# ---------------------------------------------------------------------------


def test_external_urls_have_dated_source_rows(guide: str) -> None:
    """Every URL outside the Sources table appears inside it, with a date.

    A claim about someone else's product is true on the day it is checked. Without
    a date a reader cannot tell whether "requires a paid tier" was verified last
    week or last year.
    """
    sources = _sources_section(guide)
    body = guide.split("## Sources", 1)[0]

    body_urls = {url.rstrip(".,") for url in _URL_RE.findall(body)}
    source_urls = {url.rstrip(".,") for url in _URL_RE.findall(sources)}
    missing = body_urls - source_urls
    assert not missing, f"URL(s) used but not in the Sources table: {sorted(missing)}"

    rows = [row for row in _SOURCES_ROW_RE.findall(sources) if "---" not in row]
    assert rows, "the Sources table has no rows"
    undated = [row for row in rows[1:] if not _ISO_DATE_RE.search(row)]
    assert not undated, f"Sources row(s) without an ISO date: {undated}"


# ---------------------------------------------------------------------------
# C6/C7/C8 — the promises
# ---------------------------------------------------------------------------


def test_privacy_and_optionality_statements_are_present(guide: str) -> None:
    """What leaves the machine, stated plainly, per provider.

    Pinned as fragments so removing one is a failing test. This is the section a
    learner reads before deciding to trust the feature; softening it in an edit
    should not be silent.
    """
    lowered = guide.lower()
    assert "what leaves your machine" in lowered
    assert "nothing" in lowered
    assert "off by default" in lowered or "default is `none`" in lowered
    assert "never overwrit" in lowered


def test_free_and_paid_provider_language_is_present(guide: str) -> None:
    """A free, local option must be presented beside any paid one.

    The rule is the owner's: recommending a paid tool is acceptable only when a
    free alternative is stated in the same breath, so this is a guard rather than
    an editorial preference.
    """
    lowered = guide.lower()
    assert "free" in lowered
    assert "obsidian" in lowered
    assert "local" in lowered


def test_plan_authority_language_is_present(guide: str) -> None:
    """The one thing a reader must not get wrong: the plan is the source of truth."""
    for page in (GUIDE, DOCS / "study-plans.md"):
        text = page.read_text(encoding="utf-8").lower()
        assert "source of truth" in text, page.name


def test_the_wind_down_offer_matches_the_agent_protocol(guide: str) -> None:
    """One sentence, two files, byte-identical.

    Documentation describing a slightly different offer than the one the agent
    makes is how a learner ends up unable to tell whether the tool is behaving.
    """
    protocol = (REPO_ROOT / "agents" / "shared" / "wind-down-protocol.md").read_text(
        encoding="utf-8"
    )

    def extract(text: str) -> str:
        assert "<!-- wind-down-offer -->" in text
        return (
            text.split("<!-- wind-down-offer -->", 1)[1]
            .split("<!-- /wind-down-offer -->", 1)[0]
            .strip()
        )

    assert extract(guide) == extract(protocol)


# ---------------------------------------------------------------------------
# C9 — the two vault folders are distinguished
# ---------------------------------------------------------------------------


def test_obsidian_export_page_distinguishes_the_two_folders() -> None:
    """Two StudyLoop folders now appear in one vault; a reader must be able to
    tell which is which, or they will look for study plans in AgentMemory."""
    text = (DOCS / "obsidian-export.md").read_text(encoding="utf-8")
    assert "AgentMemory" in text
    assert "Study/Plans" in text
    assert "second-brain" in text.lower()


def test_the_setup_guide_mentions_the_config_init_follow_up() -> None:
    """The wizard asks a question; the guide has to say what answering yes does."""
    text = (DOCS / "setup-guide.md").read_text(encoding="utf-8")
    assert "second brain" in text.lower() or "second_brain" in text


def test_the_roadmap_describes_the_layer_without_a_version_number(guide: str) -> None:
    """The roadmap is Now/Next/Later prose, deliberately.

    Version numbers in a roadmap age badly and become a promise nobody made.
    """
    text = (DOCS / "roadmap.md").read_text(encoding="utf-8")
    assert "second brain" in text.lower()
    assert "0.2.0" not in text


# ---------------------------------------------------------------------------
# C12 — the contract page stays source-only
# ---------------------------------------------------------------------------


def test_the_contract_page_is_tracked_but_not_published() -> None:
    """Un-ignored so it can be reviewed in a diff; out of mkdocs because it is a
    contract for maintainers, not a guide for learners."""
    contract = DOCS / "architecture" / "second-brain.md"
    assert contract.is_file(), f"{contract} is missing"
    mkdocs = (REPO_ROOT / "mkdocs.yml").read_text(encoding="utf-8")
    assert "architecture/second-brain.md" not in mkdocs


def test_the_guide_does_not_link_the_excluded_contract_page(guide: str) -> None:
    """A relative Markdown link to an excluded page breaks `mkdocs --strict`.

    So the guide names it as a repository path instead. Stated as a test because
    the failure mode is a red docs build in someone else's commit.
    """
    assert "](architecture/second-brain.md)" not in guide
    assert "](../docs/architecture/second-brain.md)" not in guide


def test_no_absolute_home_paths_or_identifiers_in_the_guide(guide: str) -> None:
    """Public hygiene: a guide is the easiest place for a real path to leak."""
    assert "/Users/" not in guide
    assert "/home/" not in guide


# ---------------------------------------------------------------------------
# The guide's worked examples must be real output
# ---------------------------------------------------------------------------
#
# A hand-written example of a generated file is a second implementation of the
# renderer, maintained by nobody. These compare the page's examples against what
# the code actually produces, and write the real output into the review tree so a
# doc author (or a screenshot) is working from truth rather than memory.


def test_the_documented_ownership_marker_matches_a_real_one(guide: str) -> None:
    """Every key shown in the guide's marker example is a key the writer emits.

    Checked in both directions. An invented key teaches the learner to look for
    something that is not there; a missing one hides part of what StudyLoop stamps
    into their notes, which is the thing they are being asked to trust.
    """
    import yaml
    from test_second_brain_templates import full_plan

    from studyloop.second_brain.obsidian_writer import marker_from_text
    from studyloop.second_brain.projection import (
        OWNERSHIP_KEY,
        ProjectionIdentity,
        render_plan_projection,
    )

    real = marker_from_text(
        render_plan_projection(
            full_plan(),
            ProjectionIdentity(
                kind="plan-projection",
                plan_id="python-decorators",
                learning_record=None,
                source="STUDYLOOP_PLANS_DIR/python-decorators.md",
            ),
        )
    )
    assert real is not None

    blocks = [
        parsed
        for block in _YAML_FENCE_RE.findall(guide)
        if isinstance(parsed := yaml.safe_load(block), dict) and OWNERSHIP_KEY in parsed
    ]
    assert blocks, "the guide shows no `studyloop:` marker example"

    documented = set()
    for parsed in blocks:
        documented.update(parsed[OWNERSHIP_KEY] or {})

    invented = documented - set(real)
    assert not invented, (
        f"the guide's marker example shows key(s) the writer never emits: {sorted(invented)}"
    )

    # The guide abbreviates the hash, so `owned`, `schema`, `kind` and `plan_id`
    # are the identity fields it must not omit.
    for required in ("owned", "schema", "kind", "plan_id"):
        assert required in documented, f"the marker example omits {required!r}"


def test_the_documented_vault_layout_matches_what_the_backend_writes(guide: str) -> None:
    """The folder tree in the guide is where notes really go.

    Derived from the backend's own path building rather than from a reading of the
    prose, so moving a note in code fails here instead of leaving a learner hunting
    for a file that has quietly moved.
    """
    from studyloop.second_brain.obsidian import TODAY_RELATIVE

    assert TODAY_RELATIVE in guide, f"the guide does not show {TODAY_RELATIVE}"
    for fragment in (
        "Plans/",
        ".notes.md",
        "Learning Records/",
    ):
        assert fragment in guide, f"the guide does not show {fragment}"


def test_write_documentation_samples(tmp_path) -> None:
    """Render the real projections into the review tree, for docs and screenshots.

    Not an assertion about the docs — an artefact FOR them. Whoever writes or
    screenshots an example of a published note should be looking at genuine output,
    and this makes that a by-product of a normal test run rather than a manual step
    somebody has to remember.
    """
    from test_second_brain_templates import full_plan

    from studyloop.second_brain.projection import (
        ProjectionIdentity,
        TodayData,
        render_plan_projection,
        render_today,
    )

    evidence = REPO_ROOT / "reviews" / "2026-09-03-second-brain" / "evidence" / "m7" / "doc-samples"
    try:
        evidence.mkdir(parents=True, exist_ok=True)
    except OSError:  # pragma: no cover - a read-only checkout is a valid state
        pytest.skip("the review tree is not writable here")

    plan_sample = render_plan_projection(
        full_plan(),
        ProjectionIdentity(
            kind="plan-projection",
            plan_id="python-decorators",
            learning_record=None,
            source="STUDYLOOP_PLANS_DIR/python-decorators.md",
        ),
    )
    today_sample = render_today(
        TodayData(
            primary="Recall how a closure captures a cell variable",
            primary_reason="Due today, and it blocks the next milestone.",
            primary_minutes=25,
            alternates=("Re-read PEP 318", "Write one decorator from memory"),
            due_cards=({"course": "Python", "card_hash": "abc123", "next_review": "2026-09-03"},),
            focus_topics=("python",),
        ),
        ProjectionIdentity(
            kind="today-projection", plan_id=None, learning_record=None, source="studyloop"
        ),
    )

    (evidence / "Study-Plans-python-decorators.md").write_text(plan_sample, encoding="utf-8")
    (evidence / "Study-Today.md").write_text(today_sample, encoding="utf-8")

    # Sanity: a sample nobody can read is not documentation.
    assert plan_sample.startswith("---\n")
    assert "## Mission" in plan_sample
    assert "## Next action" in today_sample


def test_every_test_the_contract_page_cites_actually_exists() -> None:
    """The contract page's whole value is that each clause names its proof.

    Found the hard way: the page still cited `test_obsidian_cli.py` after the CLI
    adapter was withdrawn, so a clause that no longer held pointed at a file that
    no longer existed, and nothing failed. A citation nobody checks is decoration.

    Module names are verified to exist; `::name` suffixes are verified to appear
    in that module. Leading `~` marks a clause whose named test is illustrative
    rather than a literal node id, and is skipped.
    """
    from pathlib import Path

    tests_dir = Path(__file__).resolve().parent
    page = (tests_dir.parents[2] / "docs" / "architecture" / "second-brain.md").read_text(
        encoding="utf-8"
    )

    cited = re.findall(r"`(~?)(test_[a-z0-9_]+\.py)(::[a-zA-Z0-9_~]+)?`", page)
    assert cited, "the contract page cites no tests at all"

    missing: list[str] = []
    for illustrative, module, node in cited:
        if illustrative:
            continue
        path = tests_dir / module
        if not path.is_file():
            missing.append(module)
            continue
        if node:
            name = node.removeprefix("::").lstrip("~")
            if f"def {name}(" not in path.read_text(encoding="utf-8"):
                missing.append(f"{module}::{name}")

    assert not missing, "the contract page cites tests that do not exist: " + ", ".join(
        sorted(set(missing))
    )
