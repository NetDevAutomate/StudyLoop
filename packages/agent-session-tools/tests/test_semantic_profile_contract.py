"""Tests for the semantic profile dependency assertion script."""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_script():
    script_path = Path(__file__).parents[3] / "scripts" / "check-semantic-profile.py"
    spec = importlib.util.spec_from_file_location("check_semantic_profile", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_main_returns_zero_when_dependencies_import(monkeypatch, capsys):
    script = _load_script()

    def import_module(name: str):
        return object()

    monkeypatch.setattr(script.importlib, "import_module", import_module)

    assert script.main() == 0

    captured = capsys.readouterr()
    assert "Semantic profile dependencies are importable." in captured.out


def test_main_returns_one_with_missing_dependency_message(monkeypatch, capsys):
    script = _load_script()

    def import_module(name: str):
        if name == "sentence_transformers":
            raise ImportError("missing")
        return object()

    monkeypatch.setattr(script.importlib, "import_module", import_module)

    assert script.main() == 1

    captured = capsys.readouterr()
    assert (
        "Missing semantic profile dependencies: sentence-transformers." in captured.err
    )
    assert "uv sync --all-packages --group dev --extra semantic" in captured.err
