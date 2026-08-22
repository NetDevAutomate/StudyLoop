"""Optional dependency checks via importlib.util.find_spec()."""

from __future__ import annotations

import importlib.util

from studyloop.doctor.models import CheckResult

OPTIONAL_DEPS: dict[str, tuple[str, str]] = {
    "pymupdf": ("PyMuPDF", "uv pip install pymupdf"),
    "notebooklm": ("notebooklm-py", "uv pip install notebooklm-py"),
    "sentence_transformers": ("sentence-transformers", "uv pip install sentence-transformers"),
    "kokoro_onnx": ("kokoro-onnx", "uv pip install kokoro-onnx"),
    "textual": ("Textual (TUI)", "uv pip install studyloop[tui]"),
    "fastapi": ("FastAPI (web)", "uv pip install studyloop[web]"),
}


def check_system_binaries() -> list[CheckResult]:
    """Check for optional system binaries (not Python packages)."""
    import shutil

    results: list[CheckResult] = []

    ttyd_path = shutil.which("ttyd")
    if ttyd_path:
        results.append(
            CheckResult(
                "deps",
                "bin_ttyd",
                "pass",
                f"ttyd installed ({ttyd_path}) — only used by STUDYLOOP_TRANSPORT=ttyd",
                "",
                False,
            )
        )
    else:
        # ADR-0005 retired the ttyd BROWSER surface. The live terminal is
        # xterm.js over a same-origin WebSocket, or an ACP chat surface — neither
        # needs ttyd. Only the maintainer-only STUDYLOOP_TRANSPORT=ttyd server
        # path uses the binary, so this check must NOT suggest installing it:
        # doing so previously told users a missing package was blocking a
        # feature that had already stopped depending on it.
        results.append(
            CheckResult(
                "deps",
                "bin_ttyd",
                "info",
                "ttyd not installed — not needed; the browser terminal uses xterm.js",
                "",
                False,
            )
        )

    return results


def check_optional_deps() -> list[CheckResult]:
    results: list[CheckResult] = []
    for import_name, (display_name, install_cmd) in OPTIONAL_DEPS.items():
        spec = importlib.util.find_spec(import_name)
        if spec is not None:
            results.append(
                CheckResult(
                    "deps", f"dep_{import_name}", "pass", f"{display_name} installed", "", False
                )
            )
        else:
            results.append(
                CheckResult(
                    "deps",
                    f"dep_{import_name}",
                    "info",
                    f"{display_name} not installed (optional)",
                    install_cmd,
                    False,
                )
            )
    return results
