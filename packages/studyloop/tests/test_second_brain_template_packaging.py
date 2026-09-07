"""The Obsidian templates must reach an installed user, not just a checkout.

Marked ``integration`` and building a real wheel, following
``test_dev_asset_packaging.py``: reading a template through
``importlib.resources`` succeeds in a source tree whether or not the file is
packaged, so a test that only reads it proves nothing about what a user gets.
This is the half that can only be checked by looking inside the wheel.
"""

from __future__ import annotations

import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[3]

WHEEL_TEMPLATE_FRAGMENT = "studyloop/data/templates/obsidian/"

EXPECTED_TEMPLATES = (
    "Study Plan.md",
    "Today.md",
    "README.md",
    "Due reviews (Dataview).md",
)


@pytest.fixture(scope="module")
def built_wheel(tmp_path_factory) -> Path:
    if shutil.which("uv") is None:
        pytest.skip("uv is not on PATH, so the wheel cannot be built here")
    out = tmp_path_factory.mktemp("template-packaging")
    # agent-session-tools is a required dependency of the studyloop wheel but
    # is not on PyPI, so build the companion too — a release ships both.
    for package in ("studyloop", "agent-session-tools"):
        proc = subprocess.run(
            ["uv", "build", "--package", package, "--wheel", "-o", str(out)],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=300,
        )
        if proc.returncode != 0:
            pytest.fail(f"wheel build failed for {package}:\n{proc.stdout}\n{proc.stderr}")
    wheels = list(out.glob("studyloop-*.whl"))
    assert len(wheels) == 1, f"expected one wheel, got {wheels}"
    return wheels[0]


def test_wheel_contains_obsidian_templates(built_wheel: Path) -> None:
    with zipfile.ZipFile(built_wheel) as archive:
        names = archive.namelist()
    shipped: set[str] = {
        name.split(WHEEL_TEMPLATE_FRAGMENT, 1)[1]
        for name in names
        if WHEEL_TEMPLATE_FRAGMENT in name
    }
    expected: set[str] = set(EXPECTED_TEMPLATES)
    missing = expected - shipped
    assert not missing, f"the wheel is missing template(s): {sorted(missing)}"


def test_templates_load_from_the_installed_wheel(built_wheel: Path, tmp_path) -> None:
    """Install the wheel into a bare venv and read a template from it.

    The strongest available check: no workspace, no source tree, no sibling
    package — exactly the situation a user is in.
    """
    if shutil.which("uv") is None:
        pytest.skip("uv is not on PATH")

    venv = tmp_path / "venv"
    subprocess.run(["uv", "venv", str(venv)], check=True, capture_output=True)
    python = venv / "bin" / "python"
    companion = next(built_wheel.parent.glob("agent_session_tools-*.whl"))
    subprocess.run(
        [
            "uv",
            "pip",
            "install",
            "--python",
            str(python),
            str(companion),
            str(built_wheel),
        ],
        check=True,
        capture_output=True,
        timeout=300,
    )
    proc = subprocess.run(
        [
            str(python),
            "-c",
            "from importlib.resources import files;"
            "print((files('studyloop') / 'data' / 'templates' / 'obsidian' / 'Today.md')"
            ".read_text(encoding='utf-8'))",
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    assert "## Next action" in proc.stdout
