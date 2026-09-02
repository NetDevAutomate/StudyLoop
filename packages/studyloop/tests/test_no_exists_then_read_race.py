"""Structural guard: no exists()-then-read TOCTOU pair survives in the
session file-IO modules.

Session release (``active.release()``) unlinks the IPC files from an
executor thread (``active.py:130-131``), so a request reading them concurrently
races that unlink. ``28a431b`` fixed this shape for
``parse_topics_file``/``parse_parking_file`` (checked ``exists()`` then called
``read_text()`` as a separate step); R-06 and R-08 (this lane) fixed the two
remaining live instances -- the SSE mtime poll in ``_dashboard.py`` and the
redundant ``exists()`` guard `read_session_state`'s own ``except`` clause had
already made moot but which invited a future edit to narrow that clause and
silently reopen the race.

This test scans the SOURCE (AST, not runtime behaviour), so a future PR that
reintroduces the shape fails immediately in the file that added it, rather
than waiting for a loaded CI run to hit the race again -- the exact
mechanical guard `28a431b`'s own commit message wished for
("any client polling session state ... could hit it") but never added.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_SRC_ROOT = Path(__file__).parents[1] / "src" / "studyloop"
_SCAN_ROOTS = (
    _SRC_ROOT / "session",
    _SRC_ROOT / "web" / "routes" / "session",
)
# session_state.py (R-08's fix, read_session_state) is a sibling module, not
# inside session/ -- the brief names "session/ or web/routes/session/" but
# the regression it is guarding against lives here, so it is scanned too.
_EXTRA_FILES = (_SRC_ROOT / "session_state.py",)
# Methods that actually READ file content/metadata. unlink()/mkdir() etc are
# deliberately excluded: exists()-then-unlink(missing_ok=True) is not a
# TOCTOU (unlink already tolerates a missing target), and this guard would
# otherwise false-positive on _ipc.py's zombie-clearing loop.
_READ_METHODS = frozenset({"read_text", "read_bytes", "stat", "open"})


def _base_expr(attr_value: ast.expr) -> str:
    """Source text of the object an attribute access is rooted on."""
    return ast.unparse(attr_value)


def _exists_base(test: ast.expr) -> str | None:
    """If ``test`` is ``<base>.exists()``, return ``<base>``'s source text."""
    if (
        isinstance(test, ast.Call)
        and not test.args
        and isinstance(test.func, ast.Attribute)
        and test.func.attr == "exists"
    ):
        return _base_expr(test.func.value)
    return None


def _reads_base(node: ast.AST, base: str) -> str | None:
    """If some call under ``node`` reads ``base`` via a read method, name it."""
    for sub in ast.walk(node):
        if (
            isinstance(sub, ast.Call)
            and isinstance(sub.func, ast.Attribute)
            and sub.func.attr in _READ_METHODS
            and _base_expr(sub.func.value) == base
        ):
            return sub.func.attr
    return None


def _find_toctou_pairs(tree: ast.AST) -> list[str]:
    """Every ``<base>.exists()`` whose branch also reads ``<base>``."""
    findings: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.If):
            base = _exists_base(node.test)
            if base is None:
                continue
            method = _reads_base(ast.Module(body=node.body, type_ignores=[]), base)
            if method:
                findings.append(
                    f"line {node.lineno}: `if {base}.exists(): ... {base}.{method}(...)`"
                )
        elif isinstance(node, ast.IfExp):
            base = _exists_base(node.test)
            if base is None:
                continue
            method = _reads_base(node.body, base) or _reads_base(node.orelse, base)
            if method:
                findings.append(f"line {node.lineno}: ternary on `{base}.exists()` / `.{method}(`")
    return findings


def _session_module_paths() -> list[Path]:
    paths: list[Path] = []
    for root in _SCAN_ROOTS:
        paths.extend(sorted(root.rglob("*.py")))
    paths.extend(_EXTRA_FILES)
    return paths


@pytest.mark.parametrize(
    "path",
    _session_module_paths(),
    ids=lambda p: str(p.relative_to(_SRC_ROOT)),
)
def test_no_exists_then_read_toctou(path: Path) -> None:
    tree = ast.parse(path.read_text(), filename=str(path))
    findings = _find_toctou_pairs(tree)
    assert not findings, (
        f"{path.relative_to(_SRC_ROOT)}: exists()-then-read TOCTOU pair(s): "
        f"{findings}. Session release unlinks these files from an executor "
        "thread (session/active.py) -- read first and catch OSError instead "
        "(see 28a431b, R-06, R-08; "
        "docs/architecture/session-authority.md)."
    )


def test_the_scan_itself_is_not_vacuous() -> None:
    """Prove the detector actually fires, against a synthetic sample --
    the coverage gate's own non-vacuity discipline (see agents/07-test-
    quality.md's praise for this pattern elsewhere in the suite)."""
    sample_if = ast.parse("if STATE_FILE.exists():\n    x = STATE_FILE.read_text()\n")
    assert _find_toctou_pairs(sample_if)

    sample_ternary = ast.parse("y = STATE_FILE.read_text() if STATE_FILE.exists() else '{}'")
    assert _find_toctou_pairs(sample_ternary)

    # A same-shaped exists() check that never reads the same object (the
    # _ipc.py zombie-clearing shape: exists()-then-unlink) must NOT fire.
    sample_unlink = ast.parse("if STATE_FILE.exists():\n    STATE_FILE.unlink(missing_ok=True)\n")
    assert not _find_toctou_pairs(sample_unlink)


def test_scans_at_least_the_known_modules() -> None:
    """Guard against the glob silently matching nothing (e.g. a path typo)."""
    scanned = {p.name for p in _session_module_paths()}
    assert "session_state.py" in scanned
    assert "cleanup.py" in scanned
    assert "_dashboard.py" in scanned
