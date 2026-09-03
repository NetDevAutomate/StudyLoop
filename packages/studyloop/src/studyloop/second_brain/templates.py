"""The Obsidian note templates StudyLoop ships, and installing them into a vault.

The templates mirror the sections a StudyLoop plan document uses, so a plan the
learner writes by hand in their vault and one StudyLoop published look the same.
``tests/test_second_brain_templates.py`` compares the template's headings against
``render_plan``'s output, so the two cannot drift.

Two deliberate properties:

* **They are package data, read through ``importlib.resources``.** The wheel ships
  ``src/studyloop`` only, so a template located by walking up from ``__file__``
  works in a checkout and fails for an installed user — a bug that surfaces only
  after release. A wheel-content test asserts the packaging half.
* **They carry no ownership marker.** A note the learner creates from a template
  is theirs and is never overwritten. The writer refuses any file without
  StudyLoop's marker, so the marker's ABSENCE is what makes that mechanical
  rather than a convention someone has to remember.

Installation goes through the same writer as a publish, in create-only mode. One
writer means one set of containment rules; a second copy-loop here would be a
second place for the vault boundary to be forgotten.
"""

from __future__ import annotations

import json
import logging
from importlib.resources import files
from pathlib import Path, PurePosixPath

from studyloop.second_brain.core import SecondBrainError
from studyloop.second_brain.obsidian_writer import projection_path, write_projection
from studyloop.second_brain.projection import ProjectionIdentity

logger = logging.getLogger(__name__)

#: Every template shipped, in the order ``--install`` reports them.
#:
#: An explicit tuple rather than a directory listing: it is the allow-list that
#: makes ``read_template`` immune to traversal, and it is reachable from a CLI
#: argument.
TEMPLATE_NAMES: tuple[str, ...] = (
    "Study Plan.md",
    "Today.md",
    "README.md",
    "Due reviews (Dataview).md",
)

#: Sub-folder created inside the learner's templates folder, so StudyLoop's
#: templates sit together and an uninstall is one directory.
INSTALL_SUBFOLDER = "StudyLoop"

#: Where Obsidian records the learner's templates folder, and the fallback.
#: The file's exact shape is not documented by Obsidian, so every unusable value
#: falls back rather than failing.
_TEMPLATES_CONFIG = ".obsidian/templates.json"
DEFAULT_TEMPLATES_FOLDER = "Templates"


def list_templates() -> list[str]:
    """Every template name, for ``brain template`` with no argument."""
    return list(TEMPLATE_NAMES)


def read_template(name: str) -> str:
    """The exact bytes of one packaged template.

    ``name`` is checked against :data:`TEMPLATE_NAMES` rather than joined onto a
    path. This is reachable from a CLI argument, so joining would make
    ``--print ../../../../etc/passwd`` a file read.
    """
    if name not in TEMPLATE_NAMES:
        raise SecondBrainError(
            f"Unknown template {name!r}. Available: {', '.join(TEMPLATE_NAMES)}."
        )
    resource = files("studyloop") / "data" / "templates" / "obsidian" / name
    return resource.read_text(encoding="utf-8")


def templates_folder(vault: Path) -> str:
    """The learner's own templates folder, vault-relative.

    Read from Obsidian's config when it is there and usable, so the templates land
    where the learner already keeps templates rather than in a folder StudyLoop
    invented. Anything unreadable, empty, absolute or containing ``..`` falls back
    to ``Templates``: a bad value here should cost the learner a slightly wrong
    folder, never a failed command or a write outside the vault.
    """
    config = Path(vault).expanduser() / _TEMPLATES_CONFIG
    try:
        raw = json.loads(config.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return DEFAULT_TEMPLATES_FOLDER

    if not isinstance(raw, dict):
        return DEFAULT_TEMPLATES_FOLDER
    folder = raw.get("folder")
    if not isinstance(folder, str):
        return DEFAULT_TEMPLATES_FOLDER
    folder = folder.strip()
    # Absoluteness is checked BEFORE trimming separators: stripping first turns
    # "/etc" into "etc", which passes the check and points outside the vault.
    if not folder or Path(folder).is_absolute() or folder.startswith(("/", "\\")):
        return DEFAULT_TEMPLATES_FOLDER
    folder = folder.strip("/")
    if not folder or ".." in PurePosixPath(folder).parts:
        return DEFAULT_TEMPLATES_FOLDER
    return folder


def install_templates(vault: Path) -> list[str]:
    """Copy every template into the vault, creating only.

    Raises on the FIRST existing file rather than skipping it. Skipping would make
    "installed" mean "some of these are yours and some are mine", which is exactly
    the ambiguity the ownership marker exists to remove — and a learner who edited
    a template needs to be told, not silently half-updated.
    """
    folder = templates_folder(vault)
    # A synthetic identity: templates are NOT projections and carry no marker, but
    # the writer's signature asks for one. create_only=True means it is never
    # consulted -- an existing file is refused before ownership is considered.
    identity = ProjectionIdentity(
        kind="plan-projection",
        plan_id=None,
        learning_record=None,
        source="studyloop/data/templates/obsidian",
    )

    installed: list[str] = []
    for name in TEMPLATE_NAMES:
        target = projection_path(vault, folder, f"{INSTALL_SUBFOLDER}/{name}")
        write_projection(target, read_template(name), identity, create_only=True)
        installed.append(target.relative)
    return installed


__all__ = [
    "DEFAULT_TEMPLATES_FOLDER",
    "INSTALL_SUBFOLDER",
    "TEMPLATE_NAMES",
    "install_templates",
    "list_templates",
    "read_template",
    "templates_folder",
]
