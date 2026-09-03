"""R-29: every extra `studyloop`'s wheel still advertises must actually

install and import from a **bare** wheel -- no uv workspace, no sibling
package, no `--with-editable`.

This is the other half of the R-29 fix (see test_extras_contract.py for the
"[sessions]/[all] must not lie" half). Dropping `sessions` proved the
*missing* case; this proves the six that remain (`content`, `bedrock`,
`notebooklm`, `tui`, `web`, `mcp`, plus `all` itself) are not making the same
mistake in a way nobody has actually exercised outside the workspace.

`bedrock.py` and `notebooklm_client.py` both lazily import their third-party
dependency (boto3, notebooklm-py) inside a function, specifically so users of
*other* extras are not forced to install them -- so importing the first-party
module alone would not prove those two extras work. Both are checked by also
importing the third-party package directly.

Slow: one wheel build plus one fresh venv + pip install per extra. Marked
``integration`` so it does not run in the default unit sweep; invoked from
``just smoke-extras`` (called from ``just release-check``).
"""

from __future__ import annotations

import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]

pytestmark = pytest.mark.integration

#: extra -> the module(s) that must import cleanly once the extra is
#: installed from a bare wheel. Order matters for the lazy-import cases:
#: first-party module first, then the third-party package it wraps.
EXTRA_SMOKE_IMPORTS: dict[str, tuple[str, ...]] = {
    "content": ("studyloop.content.splitter",),
    "bedrock": ("studyloop.content.generators.bedrock", "boto3"),
    "notebooklm": ("studyloop.content.notebooklm_client", "notebooklm"),
    "tui": ("studyloop.tui.sidebar",),
    "web": ("studyloop.web.app",),
    "mcp": ("studyloop.mcp.server",),
    "all": (
        "studyloop.content.splitter",
        "studyloop.content.generators.bedrock",
        "boto3",
        "studyloop.content.notebooklm_client",
        "notebooklm",
        "studyloop.tui.sidebar",
        "studyloop.web.app",
        "studyloop.mcp.server",
    ),
}


@pytest.fixture(scope="module")
def built_wheel(tmp_path_factory: pytest.TempPathFactory) -> Path:
    if shutil.which("uv") is None:
        pytest.skip("uv is not on PATH, so the wheel cannot be built here")
    out = tmp_path_factory.mktemp("extras-smoke-wheel")
    # --no-sources: build exactly what a real distribution would ship, not
    # what the local workspace's [tool.uv.sources] would substitute. This is
    # the same flag scripts/build-release.sh uses, and the one that exposed
    # R-29 in the first place (a plain `uv build` masks the defect).
    proc = subprocess.run(
        ["uv", "build", "--package", "studyloop", "--no-sources", "--wheel", "-o", str(out)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=300,
    )
    if proc.returncode != 0:
        pytest.fail(f"wheel build failed:\n{proc.stdout}\n{proc.stderr}")
    wheels = list(out.glob("studyloop-*.whl"))
    assert len(wheels) == 1, f"expected one wheel, got {wheels}"
    return wheels[0]


def test_sessions_is_not_advertised_on_the_built_wheel(built_wheel: Path) -> None:
    with zipfile.ZipFile(built_wheel) as wheel:
        metadata_name = next(n for n in wheel.namelist() if n.endswith(".dist-info/METADATA"))
        metadata = wheel.read(metadata_name).decode("utf-8")
    provided_extras = {
        line.removeprefix("Provides-Extra: ").strip()
        for line in metadata.splitlines()
        if line.startswith("Provides-Extra: ")
    }
    assert provided_extras == set(EXTRA_SMOKE_IMPORTS), (
        f"wheel advertises {sorted(provided_extras)}; expected exactly "
        f"{sorted(EXTRA_SMOKE_IMPORTS)} (no 'sessions')"
    )


@pytest.mark.parametrize("extra", sorted(EXTRA_SMOKE_IMPORTS))
def test_extra_installs_and_imports_from_a_bare_wheel(
    extra: str, built_wheel: Path, tmp_path: Path
) -> None:
    venv_dir = tmp_path / f"venv-{extra}"
    venv_proc = subprocess.run(
        ["uv", "venv", str(venv_dir)], capture_output=True, text=True, timeout=60
    )
    assert venv_proc.returncode == 0, f"uv venv failed:\n{venv_proc.stdout}\n{venv_proc.stderr}"
    python = venv_dir / "bin" / "python"

    install = subprocess.run(
        ["uv", "pip", "install", "--python", str(python), f"{built_wheel}[{extra}]"],
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert install.returncode == 0, (
        f"installing studyloop[{extra}] from the bare wheel failed:\n"
        f"{install.stdout}\n{install.stderr}"
    )

    import_line = "; ".join(f"import {module}" for module in EXTRA_SMOKE_IMPORTS[extra])
    check = subprocess.run(
        [str(python), "-c", import_line], capture_output=True, text=True, timeout=30
    )
    assert check.returncode == 0, (
        f"studyloop[{extra}]'s entry module(s) did not import from a bare wheel install "
        f"(ran: {import_line!r}):\n{check.stdout}\n{check.stderr}"
    )
