"""Ordering guards born from the ttyd retirement, one of them ttyd-specific.

A staged deletion can go green while leaving the product in a worse state than
either end point. This module started with two assertions turning the specific
ways that can happen into failures, because a written plan cannot enforce its
own ordering. Both were identified by an independent review of the retirement
plan, which found that the plan as written would have produced exactly these
outcomes.

``test_ttyd_cleanup_outlives_the_ttyd_spawn`` is deleted as of ttyd retirement
stage 6 (R-56): it asserted "if nothing spawns ttyd, cleanup may still exist,
but not the other way around" — a real ordering invariant while the spawn
(stage 2) and the cleanup (stage 5) were being removed in separate commits.
Once stage 5 landed, the assertion became unconditionally, permanently true
(neither side can ever exist again), so it stopped meaning anything: a green
check with nothing left to catch. See PLAN-retire-ttyd.md's manifest and
REMEDIATION-PLAN.md's Gate 1 amendment 6, which both name this deletion.

``test_no_frontend_module_imports_a_deleted_component`` survives — it was
written for the ttyd retirement's stage 3/4 frontend deletions but the
invariant it guards (an eager `main.js` import of a file that stops existing
takes down the whole SPA, not just one panel) applies to any future component
removal, ttyd or not.
"""

from __future__ import annotations

from pathlib import Path

import studyloop

_SRC = Path(studyloop.__file__).parent


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
