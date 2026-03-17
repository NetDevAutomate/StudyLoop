"""Optional dependency checks via importlib.util.find_spec()."""

from __future__ import annotations

import importlib.util

from studyctl.doctor.models import CheckResult

OPTIONAL_DEPS: dict[str, tuple[str, str]] = {
    "pymupdf": ("PyMuPDF", "uv pip install pymupdf"),
    "notebooklm": ("notebooklm-py", "uv pip install notebooklm-py"),
    "sentence_transformers": ("sentence-transformers", "uv pip install sentence-transformers"),
    "kokoro_onnx": ("kokoro-onnx", "uv pip install kokoro-onnx"),
    "textual": ("Textual (TUI)", "uv pip install studyctl[tui]"),
    "fastapi": ("FastAPI (web)", "uv pip install studyctl[web]"),
}


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
