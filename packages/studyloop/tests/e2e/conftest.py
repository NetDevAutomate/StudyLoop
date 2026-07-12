"""Make shared test helpers in ``tests/`` importable from the e2e package."""

import sys
from pathlib import Path

_TESTS_DIR = str(Path(__file__).resolve().parent.parent)
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)
