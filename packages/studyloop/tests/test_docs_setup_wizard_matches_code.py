"""R-58 guard: docs/setup-guide.md's description of `studyloop setup` must

match `cli/_setup.py`'s real prompts, not `studyloop config init`'s.

The public page previously described `config init`'s three questions
(knowledge bridging, "study material location", Obsidian vault) under the
`studyloop setup` heading -- a first-run reader would wait for prompts that
never come (REPORT.md R-58 / agents/08-docs-congruence.md N1). Rather than
re-deriving `_setup.py`'s exact console strings by hand a second time (which
is exactly how the page drifted in the first place), this test extracts the
same three prompt strings the doc now quotes and asserts they are literally
present in `_setup.py`'s source -- if a future edit to the wizard's copy
doesn't also update the doc, this goes red.
"""

from __future__ import annotations

from pathlib import Path

import studyloop.cli._setup as _setup_cli_module
from studyloop.settings import MAX_ACTIVE_TOPICS

REPO_ROOT = Path(__file__).resolve().parents[3]
SETUP_GUIDE = REPO_ROOT / "docs" / "setup-guide.md"

#: The exact `console.print(...)` prompt text for each of setup's three
#: questions, as they appear LITERALLY in `_setup.py`'s source (the topics
#: question is an f-string template there, not rendered text).
_SOURCE_PROMPT_TEMPLATES = (
    "Where do your study notes live?",
    "Focus on up to {MAX_ACTIVE_TOPICS} topics to start?",
    "Which AI assistant should run your study sessions?",
)

#: The same three prompts as they should appear, RENDERED, in the public doc
#: -- the topics question has the real MAX_ACTIVE_TOPICS number substituted
#: in, imported live rather than hardcoded so a change to that constant
#: fails this test until the doc is updated too.
_DOC_PROMPTS = (
    "Where do your study notes live?",
    f"Focus on up to {MAX_ACTIVE_TOPICS} topics to start?",
    "Which AI assistant should run your study sessions?",
)


def _setup_module_source() -> str:
    source_file = _setup_cli_module.__file__
    assert source_file is not None
    return Path(source_file).read_text(encoding="utf-8")


def _setup_guide_text() -> str:
    return SETUP_GUIDE.read_text(encoding="utf-8")


def test_expected_prompts_are_real_prompts_in_setup_py() -> None:
    """Sanity check: every string this test relies on is actually in the

    wizard's source, not a phrase this test invented independently.
    """
    source = _setup_module_source()
    missing = [prompt for prompt in _SOURCE_PROMPT_TEMPLATES if prompt not in source]
    assert not missing, (
        f"expected prompt(s) not found in cli/_setup.py: {missing} -- "
        "the wizard's copy changed; update _SOURCE_PROMPT_TEMPLATES to match"
    )


def test_setup_guide_names_setups_real_prompts() -> None:
    guide = _setup_guide_text()
    missing = [prompt for prompt in _DOC_PROMPTS if prompt not in guide]
    assert not missing, (
        f"docs/setup-guide.md is missing setup's real prompt string(s): {missing}"
    )


def test_setup_guide_no_longer_describes_config_inits_questions_as_setups() -> None:
    """The specific defect: config init's three questions (bridging, a

    "study material location" question setup never asks, Obsidian vault)
    must not appear under the ``studyloop setup`` heading's own description.
    """
    guide = _setup_guide_text()
    setup_section_start = guide.index("### Interactive Setup")
    config_init_start = guide.index("`studyloop config init` is a separate")
    setup_section = guide[setup_section_start:config_init_start]
    assert "Study material location" not in setup_section
    assert "~/Obsidian/Personal/Study" not in setup_section
