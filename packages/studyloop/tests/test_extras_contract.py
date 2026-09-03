"""R-29 guard: `studyloop[sessions]` / `studyloop[all]` must not advertise a

dependency that cannot resolve outside the uv workspace.

`agent-session-tools` is not published anywhere -- `[tool.uv.sources]
agent-session-tools = { workspace = true }` only ever worked inside this
repo's own uv workspace, so a wheel built with `--no-sources` (or any install
from a hypothetical future PyPI release) advertised an unresolvable
dependency (REPORT.md F-02 / R-29; DECISIONS.md B1).

`agent-session-tools` reaches the studyloop tool venv today via
`install_workspace_tools()`'s unconditional `--with-editable` flag
(`installers.py`), completely independent of any extra -- that is the "hard
dependency on the source-install path" DECISIONS.md B1 describes. The extra
was always redundant with that mechanism and never actually needed by it, so
dropping it changes nothing about the real, tested install flow.

`[all]` stays, because `install_workspace_tools()` still requests it
unconditionally for both workspace packages -- but it is redefined to the six
extras that genuinely resolve from a bare wheel (proved per-extra in
test_wheel_extras_smoke.py), with `sessions` removed from its expansion.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PACKAGE_PYPROJECT = REPO_ROOT / "packages" / "studyloop" / "pyproject.toml"

RESOLVABLE_EXTRAS = {"content", "bedrock", "notebooklm", "tui", "web", "mcp"}


def _optional_dependencies() -> dict[str, list[str]]:
    with PACKAGE_PYPROJECT.open("rb") as pyproject_file:
        pyproject = tomllib.load(pyproject_file)
    return pyproject.get("project", {}).get("optional-dependencies", {})


def test_sessions_extra_is_not_advertised() -> None:
    extras = _optional_dependencies()
    assert "sessions" not in extras, (
        "studyloop[sessions] must not be advertised -- agent-session-tools "
        "cannot resolve outside the uv workspace (R-29)"
    )


def test_all_extra_no_longer_expands_to_sessions() -> None:
    extras = _optional_dependencies()
    assert "all" in extras, (
        "studyloop[all] must still exist -- install_workspace_tools() in "
        "installers.py requests it unconditionally for both workspace packages"
    )
    (spec,) = extras["all"]
    assert "sessions" not in spec, f"studyloop[all] must not reference sessions; got {spec!r}"


def test_all_extra_expands_to_exactly_the_resolvable_extras() -> None:
    extras = _optional_dependencies()
    (spec,) = extras["all"]
    # spec looks like 'studyloop[content,bedrock,web,notebooklm,tui,mcp]'
    inner = spec.split("[", 1)[1].rstrip("]")
    named = {name.strip() for name in inner.split(",")}
    assert named == RESOLVABLE_EXTRAS, (
        f"studyloop[all] should expand to exactly {sorted(RESOLVABLE_EXTRAS)}; got {sorted(named)}"
    )
    assert named <= extras.keys(), "studyloop[all] names an extra that does not exist"


def test_no_uv_source_maps_the_dropped_agent_session_tools_extra() -> None:
    """The `[tool.uv.sources]` entry existed only to resolve the now-removed

    `sessions` extra; leaving it behind would be dead configuration pointing
    at a name this file no longer references anywhere.
    """
    with PACKAGE_PYPROJECT.open("rb") as pyproject_file:
        pyproject = tomllib.load(pyproject_file)
    sources = pyproject.get("tool", {}).get("uv", {}).get("sources", {})
    assert "agent-session-tools" not in sources


# ---------------------------------------------------------------------------
# R-30b: every mcp/fastmcp dependency, anywhere, carries an upper bound.
# ---------------------------------------------------------------------------

import re  # noqa: E402

_DEP_NAME_RE = re.compile(r"^([A-Za-z0-9_.\-]+)")

_ALL_PYPROJECTS = (
    REPO_ROOT / "pyproject.toml",
    REPO_ROOT / "packages" / "studyloop" / "pyproject.toml",
    REPO_ROOT / "packages" / "agent-session-tools" / "pyproject.toml",
)


def _iter_all_dependency_specs():
    """Yield (label, spec) for every dependency string in all three

    pyproject.toml files: base [project.dependencies],
    [project.optional-dependencies.*], and [dependency-groups.*].
    """
    for path in _ALL_PYPROJECTS:
        with path.open("rb") as pyproject_file:
            data = tomllib.load(pyproject_file)
        rel = path.relative_to(REPO_ROOT)
        project = data.get("project", {})
        for spec in project.get("dependencies", []):
            yield (f"{rel}", spec)
        for extra, specs in project.get("optional-dependencies", {}).items():
            for spec in specs:
                yield (f"{rel} [{extra}]", spec)
        for group, specs in data.get("dependency-groups", {}).items():
            for spec in specs:
                if isinstance(spec, str):
                    yield (f"{rel} (dependency-groups.{group})", spec)


def test_every_mcp_and_fastmcp_dependency_has_an_upper_bound() -> None:
    """R-30b: `fastmcp>=3.1.1` (no upper bound) resolved to fastmcp 4.0.2 in a

    fresh (non-locked) install, which transitively pulled in mcp==2.1.1 /
    mcp-types==2.1.1 -- the exact unbounded-transitive-dependency risk R-30
    already fixed for the *direct* mcp[cli] requirement. This scans every
    dependency string in all three pyproject.toml files (base deps, every
    optional-dependencies extra, every dependency-groups group) for anything
    named mcp or fastmcp and requires an upper bound on each, so neither
    package can silently regress into this again.
    """
    offenders = [
        f"{label}: {spec!r}"
        for label, spec in _iter_all_dependency_specs()
        if (match := _DEP_NAME_RE.match(spec))
        and match.group(1).lower() in {"mcp", "fastmcp"}
        and "<" not in spec
    ]
    assert not offenders, "mcp/fastmcp dependency with no upper bound:\n" + "\n".join(offenders)
