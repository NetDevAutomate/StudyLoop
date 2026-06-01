#!/usr/bin/env python3
"""Assert that the semantic test profile has its optional dependencies."""

from __future__ import annotations

import importlib
import sys

REQUIRED_IMPORTS = {
    "numpy": "numpy",
    "sentence_transformers": "sentence-transformers",
}


def missing_dependencies() -> list[str]:
    missing: list[str] = []
    for module_name, package_name in REQUIRED_IMPORTS.items():
        try:
            importlib.import_module(module_name)
        except ImportError:
            missing.append(package_name)
    return missing


def main() -> int:
    missing = missing_dependencies()
    if missing:
        names = ", ".join(missing)
        print(
            f"Missing semantic profile dependencies: {names}. "
            "Run `uv sync --all-packages --group dev --extra semantic`.",
            file=sys.stderr,
        )
        return 1

    print("Semantic profile dependencies are importable.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
