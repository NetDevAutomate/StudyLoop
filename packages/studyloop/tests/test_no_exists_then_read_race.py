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
# C7 (council): widened from (session/, web/routes/session/) to the whole
# package -- the shape this guard targets (session release's executor-thread
# unlink racing a read) is not actually confined to those two directories;
# tui/sidebar.py's IPC poll (fixed alongside this widening, same commit) is
# proof. session_state.py is a sibling module, not inside session/, but the
# regression 28a431b/R-06/R-08 guarded against lives here too, so it stays
# named explicitly rather than relying on the whole-package scan alone.
_SCAN_ROOTS = (_SRC_ROOT,)
_EXTRA_FILES = (_SRC_ROOT / "session_state.py",)
# Files with a genuine exists()-then-read pair OUTSIDE the session-authority
# surface this lane (m2) owns (tests/fixtures/lane_ownership.yaml) -- reported
# in evidence/M2/step-9/C7/00-dod.md rather than fixed, per the item's own
# scope: this lane closes races in ITS surface, not the whole codebase.
# Excluded here (not from the whole-package widening's benefit for m2-owned
# code) so the widening can land without also silently laundering a report
# into "the scanner didn't even look."
_UNOWNED_TOCTOU_FILES = frozenset(
    {
        "adapters/kiro.py",  # line 63 -- m5/unmapped
        "agent_launcher.py",  # lines 138, 262 -- unmapped
        "doctor/harness.py",  # line 56 -- m5 (doctor/**)
        "secrets.py",  # line 162 -- unmapped
        "services/flashcard_writer.py",  # line 121 -- unmapped
        "state.py",  # line 46 -- unmapped
    }
)
# Methods that actually READ file content/metadata. unlink()/mkdir() etc are
# deliberately excluded: exists()-then-unlink(missing_ok=True) is not a
# TOCTOU (unlink already tolerates a missing target), and this guard would
# otherwise false-positive on _ipc.py's zombie-clearing loop.
_READ_METHODS = frozenset({"read_text", "read_bytes", "stat", "open"})


def _base_expr(attr_value: ast.expr) -> str:
    """Source text of the object an attribute access is rooted on."""
    return ast.unparse(attr_value)


def _exists_bases(test: ast.expr) -> list[str]:
    """Every ``<base>.exists()`` reachable from ``test``.

    C7 (council): a plain ``if x.exists():`` is one call; ``if x.exists()
    and other_condition:`` (or ``or``, or either wrapped in ``not``) still
    names ``x`` as a base this ``If``/``IfExp`` can read after checking --
    the AST-walk-based `ast.Call` check alone missed this shape entirely,
    since it required `test` itself to BE the call, not merely CONTAIN it.
    """
    bases: list[str] = []

    def _walk(node: ast.expr) -> None:
        if (
            isinstance(node, ast.Call)
            and not node.args
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "exists"
        ):
            bases.append(_base_expr(node.func.value))
        elif isinstance(node, ast.BoolOp):
            for value in node.values:
                _walk(value)
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            _walk(node.operand)

    _walk(test)
    return bases


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
            for base in _exists_bases(node.test):
                method = _reads_base(ast.Module(body=node.body, type_ignores=[]), base)
                if method:
                    findings.append(
                        f"line {node.lineno}: `if ...{base}.exists()...: ... {base}.{method}(...)`"
                    )
        elif isinstance(node, ast.IfExp):
            for base in _exists_bases(node.test):
                method = _reads_base(node.body, base) or _reads_base(node.orelse, base)
                if method:
                    findings.append(
                        f"line {node.lineno}: ternary on `{base}.exists()` / `.{method}(`"
                    )
    return findings


def _session_module_paths() -> list[Path]:
    paths: list[Path] = []
    for root in _SCAN_ROOTS:
        for path in sorted(root.rglob("*.py")):
            if str(path.relative_to(_SRC_ROOT)) in _UNOWNED_TOCTOU_FILES:
                continue
            paths.append(path)
    for extra in _EXTRA_FILES:
        if extra not in paths:
            paths.append(extra)
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

    # C7: an exists() combined with another condition via and/or/not must
    # still fire -- the shape the AST-Call-only check originally missed.
    sample_and = ast.parse("if STATE_FILE.exists() and other:\n    x = STATE_FILE.read_text()\n")
    assert _find_toctou_pairs(sample_and)

    sample_or = ast.parse("if other or STATE_FILE.exists():\n    x = STATE_FILE.read_text()\n")
    assert _find_toctou_pairs(sample_or)

    # `not x.exists()` composed into a ternary's condition must still name
    # x as a base -- proves _walk's ast.UnaryOp branch, not just BoolOp.
    sample_not_ternary = ast.parse(
        "y = '{}' if not STATE_FILE.exists() else STATE_FILE.read_text()"
    )
    assert _find_toctou_pairs(sample_not_ternary)


def test_scans_at_least_the_known_modules() -> None:
    """Guard against the glob silently matching nothing (e.g. a path typo)."""
    scanned = {p.name for p in _session_module_paths()}
    assert "session_state.py" in scanned
    assert "cleanup.py" in scanned
    assert "_dashboard.py" in scanned
