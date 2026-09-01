"""Ordering guards for the ttyd retirement.

A staged deletion can go green while leaving the product in a worse state than
either end point. These two assertions turn the specific ways that can happen
into failures, because a written plan cannot enforce its own ordering.

Both were identified by an independent review of the retirement plan, which found
that the plan as written would have produced exactly these outcomes.
"""

from __future__ import annotations

from pathlib import Path

import studyloop

_SRC = Path(studyloop.__file__).parent


def _sources() -> list[Path]:
    return [p for p in _SRC.rglob("*.py") if "__pycache__" not in p.parts]


def test_ttyd_cleanup_outlives_the_ttyd_spawn() -> None:
    """If nothing spawns ttyd, cleanup may go. Not before.

    The retirement plan assigned the ttyd CLEANUP to a stage but never assigned
    the SPAWN to any stage at all. Landed in that order, every `studyloop study`
    would still start a writable ttyd and record its pid, while session teardown
    no longer killed it -- an orphaned process holding a terminal attached to the
    learner's session, and a silent security regression dressed as progress.

    So the invariant is directional: cleanup is allowed to disappear only once no
    caller can create the thing it cleans up.
    """
    spawners = [
        p.relative_to(_SRC)
        for p in _sources()
        if "start_ttyd_background(" in p.read_text(encoding="utf-8", errors="replace")
        and "def start_ttyd_background(" not in p.read_text(encoding="utf-8", errors="replace")
    ]
    cleanup = _SRC / "session" / "cleanup.py"
    cleanup_text = cleanup.read_text(encoding="utf-8", errors="replace")
    cleans_ttyd = "ttyd" in cleanup_text

    if spawners and not cleans_ttyd:
        raise AssertionError(
            "ttyd cleanup has been removed while these files still spawn ttyd: "
            f"{[str(p) for p in spawners]}. Delete the spawn first, or restore "
            "the cleanup — this ordering leaves an orphaned writable terminal."
        )


def test_no_frontend_module_imports_a_deleted_component() -> None:
    """main.js imports its components eagerly, so a missing file breaks all of them.

    ES module resolution fails before any Alpine component registers, so deleting
    a component file while main.js still imports it does not degrade one panel --
    it takes down the entire frontend. The plan's stage 3 named the component file
    and omitted the import site.

    Generalised beyond ttyd: the same failure applies to any component removal.
    """
    static = _SRC / "web" / "static" / "js"
    main = static / "main.js"
    if not main.exists():  # pragma: no cover - layout changed
        return

    missing: list[str] = []
    for line in main.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if not stripped.startswith("import ") or "from" not in stripped:
            continue
        if "'" not in stripped and '"' not in stripped:
            continue
        quote = "'" if "'" in stripped else '"'
        spec = stripped.split(quote)[1]
        if not spec.startswith("."):
            continue  # bare specifier, not a local file
        target = (main.parent / spec).resolve()
        if not target.exists():
            missing.append(spec)

    assert missing == [], (
        f"main.js imports files that do not exist: {missing}. ES module resolution "
        "fails before any component registers, so this breaks the whole frontend, "
        "not just the missing panel."
    )
