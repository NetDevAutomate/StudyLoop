"""The contributor guide quotes the ``just sync-*`` recipes as they are written.

``docs/contributor-environment.md`` tells a new contributor what ``just sync-dev``
runs. Lane 7 (plan 1) added ``--inexact`` to every workspace sync recipe so that
one sync no longer strips the extras another installed, but the guide kept quoting
the old command. A contributor who copies the quoted line by hand then gets the
exact sync the recipe deliberately avoids. Plan 2, C2.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
JUSTFILE = REPO_ROOT / "Justfile"  # the git-tracked spelling; CI runs on a case-sensitive host
GUIDE = REPO_ROOT / "docs" / "contributor-environment.md"

#: A recipe header followed by its single indented command line.
_RECIPE = re.compile(r"^(sync-[\w-]+):[ \t]*\n[ \t]+(\S[^\n]*)$", re.MULTILINE)
#: The guide's form for a quoted recipe: "`just sync-dev` runs `uv sync ...`".
_QUOTED = re.compile(r"`just (sync-[\w-]+)` runs `([^`]+)`")


def _sync_recipes() -> dict[str, str]:
    text = JUSTFILE.read_text(encoding="utf-8")
    return {name: body.strip() for name, body in _RECIPE.findall(text)}


def test_the_justfile_has_single_line_sync_recipes() -> None:
    """If the recipes change shape, the comparison below would pass on nothing."""
    recipes = _sync_recipes()
    assert "sync-dev" in recipes, "justfile has no single-line sync-dev recipe"
    assert recipes["sync-dev"].startswith("uv sync "), recipes["sync-dev"]


def test_guide_quotes_each_sync_recipe_exactly() -> None:
    recipes = _sync_recipes()
    quoted = _QUOTED.findall(GUIDE.read_text(encoding="utf-8"))
    assert quoted, f"{GUIDE.name} no longer says what any `just sync-*` recipe runs"
    for recipe, command in quoted:
        assert recipe in recipes, f"{GUIDE.name} quotes `just {recipe}`, which does not exist"
        assert command == recipes[recipe], (
            f"{GUIDE.name} says `just {recipe}` runs `{command}`; "
            f"the justfile runs `{recipes[recipe]}`"
        )
