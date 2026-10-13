"""The ``semantic`` extra declares what the semantic layer imports (issue #46 item 2).

``agent-session-tools[semantic]`` is the install the hints and docs name for
the semantic layer, so it has to resolve every third-party module the layer
imports directly. It declared ``sentence-transformers``, ``numpy``, ``einops``
and ``sqlite-vec`` -- the torch path -- while the default ``auto`` backend
concretises to ONNX for the shipped model and ``onnx_encoder.py`` imports
``onnxruntime``, ``tokenizers`` and ``huggingface_hub`` directly. ``[all]``
worked only because ``kokoro-onnx`` in ``[tts]`` happened to drag
``onnxruntime`` in; ``[semantic]`` alone failed at ``onnxruntime is not
installed``.

The imports are scanned from the source files rather than listed here, so a
new direct import without a matching declaration fails this test instead of
the next learner's install.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from agent_session_tools import embedding_store

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = PACKAGE_ROOT / "pyproject.toml"
SRC = PACKAGE_ROOT / "src" / "agent_session_tools"

# Module imported in source -> distribution name the extra must declare.
# Stdlib and first-party modules are not in this map and are ignored.
MODULE_TO_DIST = {
    "onnxruntime": "onnxruntime",
    "tokenizers": "tokenizers",
    "huggingface_hub": "huggingface-hub",
    "numpy": "numpy",
    "sqlite_vec": "sqlite-vec",
    "sentence_transformers": "sentence-transformers",
}

SEMANTIC_LAYER_FILES = (
    "onnx_encoder.py",
    "embedding_store.py",
    "embeddings.py",
    "query_encoders.py",
)

_IMPORT_RE = re.compile(r"^\s*(?:from|import)\s+([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE)
_DEP_NAME_RE = re.compile(r"^([A-Za-z0-9_.\-]+)")


def _semantic_extra_dists() -> set[str]:
    project = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]
    declared = project["optional-dependencies"]["semantic"]
    names: set[str] = set()
    for dep in declared:
        match = _DEP_NAME_RE.match(dep)
        assert match is not None, f"unparseable dependency specifier: {dep!r}"
        names.add(match.group(1).lower().replace("_", "-"))
    return names


def _directly_imported_dists() -> dict[str, set[str]]:
    """``{distribution: {file, ...}}`` for every mapped module the layer imports."""
    found: dict[str, set[str]] = {}
    for name in SEMANTIC_LAYER_FILES:
        text = (SRC / name).read_text(encoding="utf-8")
        for module in _IMPORT_RE.findall(text):
            dist = MODULE_TO_DIST.get(module)
            if dist:
                found.setdefault(dist, set()).add(name)
    return found


def test_the_scan_sees_the_onnx_path_at_all():
    """Guard the guard: if the regex stopped matching, the main test would pass vacuously."""
    imported = _directly_imported_dists()
    assert "onnxruntime" in imported, imported
    assert "sqlite-vec" in imported, imported


def test_semantic_extra_declares_every_direct_import():
    declared = _semantic_extra_dists()
    imported = _directly_imported_dists()
    undeclared = {
        dist: sorted(files) for dist, files in imported.items() if dist not in declared
    }
    assert not undeclared, (
        f"imported directly but not declared by [semantic]: {undeclared}; "
        f"declared: {sorted(declared)}"
    )


def test_runtime_module_lists_match_the_direct_imports():
    """The doctor probes ``RUNTIME_MODULES``; it must name exactly what each path imports."""
    for backend, modules in embedding_store.RUNTIME_MODULES.items():
        assert modules, backend
        for module in modules:
            assert module in MODULE_TO_DIST, (backend, module)
    assert set(embedding_store.RUNTIME_MODULES["onnx"]) == {
        "onnxruntime",
        "tokenizers",
        "huggingface_hub",
        "numpy",
        "sqlite_vec",
    }
    assert set(embedding_store.RUNTIME_MODULES["torch"]) == {
        "sentence_transformers",
        "numpy",
        "sqlite_vec",
    }
