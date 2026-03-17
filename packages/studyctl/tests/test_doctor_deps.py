"""Tests for doctor optional dependency checks."""

from __future__ import annotations

from unittest.mock import patch

OPTIONAL_DEPS = {
    "pymupdf": "PyMuPDF",
    "notebooklm": "notebooklm-py",
    "sentence_transformers": "sentence-transformers",
    "kokoro_onnx": "kokoro-onnx",
    "textual": "Textual (TUI)",
    "fastapi": "FastAPI (web)",
}


class TestOptionalDepsCheck:
    def test_all_installed(self):
        from studyctl.doctor.deps import check_optional_deps

        with patch("importlib.util.find_spec", return_value=True):
            results = check_optional_deps()
        assert all(r.status == "pass" for r in results)
        assert len(results) == len(OPTIONAL_DEPS)

    def test_none_installed(self):
        from studyctl.doctor.deps import check_optional_deps

        with patch("importlib.util.find_spec", return_value=None):
            results = check_optional_deps()
        assert all(r.status == "info" for r in results)

    def test_partial_installed(self):
        from studyctl.doctor.deps import check_optional_deps

        def selective_find(name):
            return True if name == "fastapi" else None

        with patch("importlib.util.find_spec", side_effect=selective_find):
            results = check_optional_deps()
        statuses = {r.name: r.status for r in results}
        assert statuses["dep_fastapi"] == "pass"
        assert statuses["dep_pymupdf"] == "info"
