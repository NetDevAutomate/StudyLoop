"""Contract tests for the source install script."""

from __future__ import annotations

import subprocess
from pathlib import Path


def test_install_script_help_documents_supported_flags() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    script = repo_root / "scripts" / "install.sh"

    result = subprocess.run(
        ["bash", str(script), "--help"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "--tools-only" in result.stdout
    assert "--agents-only" in result.stdout
    assert "--non-interactive" in result.stdout
    assert "--no-smoke" in result.stdout
