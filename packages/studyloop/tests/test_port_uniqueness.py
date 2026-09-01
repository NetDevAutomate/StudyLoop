"""Every test module that binds a fixed server port must own it exclusively.

Six ports were shared by two modules each. That is survivable in a strictly
serial run -- the previous server has usually exited before the next fixture
starts -- but it produces ``[Errno 48] address already in use`` the moment
teardown is slow, a run overlaps, or a server leaks. Worse, the readiness probe
in ``_playwright_helpers.start_web_server`` could not tell a stranger's response
from its own, so a test could silently drive the wrong server and pass or fail
for reasons unrelated to itself.

This is a static test on purpose: it parses the declarations rather than binding
anything, so it is instant, needs no browser, and -- unlike the e2e suites it
protects -- actually runs in CI.
"""

from __future__ import annotations

import ast
import collections
from pathlib import Path

TESTS_ROOT = Path(__file__).resolve().parent

#: Lowest/highest plausible value for a declared test server port. Narrow enough
#: to ignore unrelated constants that merely have PORT in the name.
PORT_MIN = 10_000
PORT_MAX = 65_535


def _declared_ports() -> dict[int, list[str]]:
    """Map port -> ["<file>:<line> (<NAME>)", ...] across every test module.

    Resolves the one derived form in use (``SOME_PORT + 1``) as well as literals,
    because a derived port collides just as hard as a written one -- and one of
    the six original collisions was exactly that shape.
    """
    found: dict[int, list[str]] = collections.defaultdict(list)

    for path in sorted(TESTS_ROOT.rglob("test_*.py")):
        try:
            tree = ast.parse(path.read_text())
        except (SyntaxError, UnicodeDecodeError):
            # A module that cannot be parsed fails collection loudly elsewhere;
            # it is not this test's job to duplicate that error.
            continue

        seen: dict[str, int] = {}
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign) or len(node.targets) != 1:
                continue
            target = node.targets[0]
            if not isinstance(target, ast.Name) or "PORT" not in target.id.upper():
                continue

            value: int | None = None
            expr = node.value
            if isinstance(expr, ast.Constant) and isinstance(expr.value, int):
                value = expr.value
            elif isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.Add):
                left, right = expr.left, expr.right
                if (
                    isinstance(left, ast.Name)
                    and isinstance(right, ast.Constant)
                    and isinstance(right.value, int)
                    and left.id in seen
                ):
                    value = seen[left.id] + right.value

            if value is None or not (PORT_MIN < value < PORT_MAX):
                continue

            seen[target.id] = value
            rel = path.relative_to(TESTS_ROOT)
            found[value].append(f"{rel}:{node.lineno} ({target.id})")

    return dict(found)


def test_no_two_test_modules_declare_the_same_port() -> None:
    ports = _declared_ports()
    collisions = {port: where for port, where in sorted(ports.items()) if len(where) > 1}

    assert not collisions, "fixed test server ports must be unique:\n" + "\n".join(
        f"  {port}:\n" + "\n".join(f"    {w}" for w in where) for port, where in collisions.items()
    )


def test_the_scan_actually_finds_the_ports() -> None:
    """Guard against the collision test passing because it found nothing.

    A regex or AST walk that silently stops matching would make the test above
    vacuously green -- the failure mode that makes a "no duplicates" assertion
    worthless. Assert a floor on what the scan sees.
    """
    ports = _declared_ports()
    assert len(ports) >= 30, (
        f"only {len(ports)} declared ports found; the scan has probably stopped "
        "matching the declaration style and the uniqueness test is now vacuous"
    )
