"""R-64 guards: five small, independent doc/copy fixes bundled under one item.

Each assertion below pins one of the sub-fixes so a future edit that
reintroduces the drift fails loudly instead of silently:

1. first-week.md's harness count matches harnesses.RELEASE_HARNESSES (was a
   hardcoded, stale "eight"; the number is read live here so THIS test goes
   stale, not the doc, if the harness count ever changes again).
2. cli-reference.md's Web UI section no longer calls itself "Web PWA" and
   states the installable-but-not-offline qualifier used elsewhere.
3. index.html's plan brain-dump hint no longer claims an agent decomposes it
   -- submitPlan() ships it verbatim.
4. agent-install.md's OpenCode section distinguishes the global install-time
   write from the project-local session-start-time write.
"""

from __future__ import annotations

from pathlib import Path

from studyloop.harnesses import RELEASE_HARNESSES

REPO_ROOT = Path(__file__).resolve().parents[3]
DOCS_DIR = REPO_ROOT / "docs"


def test_first_week_defers_the_real_number_of_harnesses() -> None:
    text = (DOCS_DIR / "first-week.md").read_text(encoding="utf-8")
    number_words = {2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight"}
    expected = number_words[len(RELEASE_HARNESSES)]
    assert f"All {expected} agent CLIs" in text, (
        f"first-week.md should say 'All {expected} agent CLIs' "
        f"({len(RELEASE_HARNESSES)} harnesses in RELEASE_HARNESSES)"
    )
    assert "eight agent" not in text.lower()


def test_cli_reference_web_ui_not_web_pwa_and_states_offline_limit() -> None:
    text = (DOCS_DIR / "cli-reference.md").read_text(encoding="utf-8")
    assert "Web PWA" not in text
    assert "### Web UI" in text
    assert "does not work offline" in text


def test_index_html_plan_hint_does_not_claim_agent_decomposition() -> None:
    index_html = (
        REPO_ROOT
        / "packages"
        / "studyloop"
        / "src"
        / "studyloop"
        / "web"
        / "static"
        / "index.html"
    )
    text = index_html.read_text(encoding="utf-8")
    assert "study-plan agent can turn it" not in text
    assert "kept with the plan exactly as written" in text


def test_agent_install_distinguishes_opencode_install_from_session_start() -> None:
    text = (DOCS_DIR / "agent-install.md").read_text(encoding="utf-8")
    section = text[text.index("### OpenCode") :]
    assert "install agents --tool opencode" in section
    assert "study --agent opencode" in section
    assert "global" in section.lower()
    assert "project-local" in section.lower()
