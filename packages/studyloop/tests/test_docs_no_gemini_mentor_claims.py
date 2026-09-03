"""R-65 guard: Gemini CLI must not be described as a mentor harness anywhere.

`harnesses.py`'s RELEASE_HARNESSES is Kiro CLI, Codex, Claude Code (core)
plus OpenCode and pi (preview) -- Gemini CLI was retired as a mentor
harness. `docs/architecture/current.md`, `docs/architecture/target.md`, and
`docs/system-overview.md` still described it as one (a mentor-selector
diagram node, an "AI agent CLIs" list, an ACP-capable-agents list).

The distinct, TRUE claim that Gemini is a content-generation API provider
(`content/generators/provider_profiles.py`) must survive untouched --
this only checks for the "CLI"/mentor-harness shape, not the API-provider
one, mirroring the distinction docs/content-pipeline.md already draws
correctly.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

_FILES = (
    REPO_ROOT / "docs" / "architecture" / "current.md",
    REPO_ROOT / "docs" / "architecture" / "target.md",
    REPO_ROOT / "docs" / "system-overview.md",
)

#: Matches "Gemini CLI", "Gemini CLI CLI" etc. -- the mentor-harness shape --
#: but not "Gemini API" or a provider-registry "Gemini" among content-gen
#: adapter names (OpenAI/OpenRouter/Gemini/Anthropic).
_GEMINI_CLI_RE = re.compile(r"gemini\s+cli", re.IGNORECASE)
_GEMINI_MENTOR_LIST_RE = re.compile(
    r"(claude[^\n]{0,20}gemini|gemini[^\n]{0,20}kiro|kiro[^\n]{0,20}gemini)",
    re.IGNORECASE,
)


def test_no_gemini_cli_mentor_claim_in_architecture_docs() -> None:
    offenders = []
    for path in _FILES:
        text = path.read_text(encoding="utf-8")
        for line_no, line in enumerate(text.splitlines(), start=1):
            if _GEMINI_CLI_RE.search(line) or _GEMINI_MENTOR_LIST_RE.search(line):
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{line_no}: {line.strip()}")
    assert not offenders, (
        "Gemini described as a mentor harness (RELEASE_HARNESSES has no "
        "'gemini'):\n" + "\n".join(offenders)
    )


def test_gemini_as_a_content_generation_provider_is_untouched() -> None:
    """Sanity check the fix didn't overcorrect: Gemini the API provider is a

    real, true claim (content/generators/provider_profiles.py) and must
    still be mentioned somewhere in these files.
    """
    combined = "\n".join(path.read_text(encoding="utf-8") for path in _FILES)
    assert "Gemini" in combined, (
        "Gemini disappeared entirely -- it should still be named as a "
        "content-generation API provider, just not as a mentor CLI"
    )
