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
        from studyloop.doctor.deps import check_optional_deps

        with patch("importlib.util.find_spec", return_value=True):
            results = check_optional_deps()
        assert all(r.status == "pass" for r in results)
        assert len(results) == len(OPTIONAL_DEPS)

    def test_none_installed(self):
        from studyloop.doctor.deps import OPTIONAL_DEPS as REAL_DEPS
        from studyloop.doctor.deps import check_optional_deps

        with patch("importlib.util.find_spec", return_value=None):
            results = check_optional_deps()
        assert all(r.status == "info" for r in results)
        # The install line is a command, filed as one: nothing to parse out of prose.
        for row in results:
            _display, install_cmd = REAL_DEPS[row.name.removeprefix("dep_")]
            assert row.fix_command == install_cmd, row
            assert row.fix_note is None, row
            assert row.fix_hint == install_cmd, row

    def test_an_installed_dep_has_no_fix(self):
        from studyloop.doctor.deps import check_optional_deps

        with patch("importlib.util.find_spec", return_value=True):
            (row, *_rest) = check_optional_deps()
        assert row.fix_command is None and row.fix_note is None and row.fix_hint == ""

    def test_partial_installed(self):
        from studyloop.doctor.deps import check_optional_deps

        def selective_find(name):
            return True if name == "fastapi" else None

        with patch("importlib.util.find_spec", side_effect=selective_find):
            results = check_optional_deps()
        statuses = {r.name: r.status for r in results}
        assert statuses["dep_fastapi"] == "pass"
        assert statuses["dep_pymupdf"] == "info"
