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

The imports are parsed from the source files with ``ast`` rather than listed
here, and every import root is classified -- standard library, first party,
or a known distribution -- so a NEW third-party import fails this test as
"unclassified" instead of being silently ignored (council review 9, A4). The
per-backend lists the doctor probes (``embedding_store.RUNTIME_MODULES``) are
checked against the same parsed imports, not against a second hand list.
"""

from __future__ import annotations

import ast
import re
import sys
import tomllib
from pathlib import Path

import pytest

from agent_session_tools import embedding_store

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = PACKAGE_ROOT / "pyproject.toml"
SRC = PACKAGE_ROOT / "src" / "agent_session_tools"
FIRST_PARTY = "agent_session_tools"

# Import root -> distribution the extra must declare. Every third-party root
# the semantic layer imports must appear here; an unknown root FAILS.
MODULE_TO_DIST = {
    "onnxruntime": "onnxruntime",
    "tokenizers": "tokenizers",
    "huggingface_hub": "huggingface-hub",
    "numpy": "numpy",
    "sqlite_vec": "sqlite-vec",
    "sentence_transformers": "sentence-transformers",
}

#: Which source files make up each query-encoder path. ``sqlite_vec`` is the
#: vector store both paths search with, so ``embedding_store.py`` belongs to both.
BACKEND_FILES = {
    "onnx": ("onnx_encoder.py", "embedding_store.py"),
    "torch": ("embeddings.py", "embedding_store.py"),
}
SEMANTIC_LAYER_FILES = (
    "onnx_encoder.py",
    "embedding_store.py",
    "embeddings.py",
    "query_encoders.py",
)

_DEP_NAME_RE = re.compile(r"^([A-Za-z0-9_.\-]+)")


def _import_roots(source: str) -> set[str]:
    """Every top-level module an ``import``/``from … import`` names, anywhere in the file.

    ``ast`` sees indented imports, ``import x as y``, comma lists and imports
    inside ``try/except ImportError`` -- the forms a regex over line starts
    missed. Relative imports have no root and are first party by construction.
    """
    roots: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def _third_party_roots(source: str) -> set[str]:
    return {
        root
        for root in _import_roots(source)
        if root not in sys.stdlib_module_names and root != FIRST_PARTY
    }


def _semantic_extra_dists() -> set[str]:
    project = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]
    declared = project["optional-dependencies"]["semantic"]
    names: set[str] = set()
    for dep in declared:
        match = _DEP_NAME_RE.match(dep)
        assert match is not None, f"unparseable dependency specifier: {dep!r}"
        names.add(match.group(1).lower().replace("_", "-"))
    return names


def _layer_imports() -> dict[str, set[str]]:
    """``{file: {third-party root, ...}}`` over the semantic layer's source."""
    return {
        name: _third_party_roots((SRC / name).read_text(encoding="utf-8"))
        for name in SEMANTIC_LAYER_FILES
    }


class TestTheScanner:
    """Guard the guard: prove the scan detects what the contract relies on."""

    def test_sees_indented_aliased_and_guarded_imports(self):
        source = (
            "def f():\n"
            "    import onnxruntime as ort\n"
            "    try:\n"
            "        from tokenizers import Tokenizer\n"
            "    except ImportError:\n"
            "        pass\n"
            "    import numpy, sqlite_vec\n"
            "from . import local\n"
            "import os\n"
        )
        assert _third_party_roots(source) == {
            "onnxruntime",
            "tokenizers",
            "numpy",
            "sqlite_vec",
        }

    def test_sees_the_onnx_path_in_the_real_source(self):
        imports = _layer_imports()
        assert "onnxruntime" in imports["onnx_encoder.py"], imports
        assert "sqlite_vec" in imports["embedding_store.py"], imports

    def test_an_unknown_third_party_root_is_reported_not_ignored(self):
        unknown = _third_party_roots("import some_new_library\n") - set(MODULE_TO_DIST)
        assert unknown == {"some_new_library"}


def test_every_third_party_import_is_classified():
    """A new direct dependency must be added to MODULE_TO_DIST (and the extra) deliberately."""
    unclassified = {
        name: sorted(roots - set(MODULE_TO_DIST))
        for name, roots in _layer_imports().items()
    }
    unclassified = {name: roots for name, roots in unclassified.items() if roots}
    assert not unclassified, (
        f"third-party imports not in MODULE_TO_DIST: {unclassified}"
    )


def test_semantic_extra_declares_every_direct_import():
    declared = _semantic_extra_dists()
    undeclared: dict[str, list[str]] = {}
    for name, roots in _layer_imports().items():
        for root in roots:
            dist = MODULE_TO_DIST.get(root)
            if dist and dist not in declared:
                undeclared.setdefault(dist, []).append(name)
    assert not undeclared, (
        f"imported directly but not declared by [semantic]: {undeclared}; declared: {sorted(declared)}"
    )


@pytest.mark.parametrize("backend", sorted(BACKEND_FILES))
def test_runtime_module_list_covers_what_its_path_imports(backend: str):
    """The doctor probes ``RUNTIME_MODULES[backend]``; it must name every third-party
    module that path's own files import, so a missing one cannot go unreported."""
    imports = _layer_imports()
    imported = set().union(*(imports[name] for name in BACKEND_FILES[backend]))
    probed = set(embedding_store.RUNTIME_MODULES[backend])
    assert imported <= probed, (
        f"{backend}: imported but not probed: {sorted(imported - probed)}"
    )
    assert probed <= set(MODULE_TO_DIST), f"{backend}: probes an unclassified module"


def test_runtime_module_lists_name_only_the_backends_in_the_registry():
    assert set(embedding_store.RUNTIME_MODULES) == set(BACKEND_FILES)
