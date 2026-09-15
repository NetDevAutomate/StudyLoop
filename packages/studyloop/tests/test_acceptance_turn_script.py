"""Unit tests for tests/acceptance/turn_script.py's scripted-actor loader.

(d) TESTS FIRST item: rejects unknown fields, versions the format. Outside
tests/acceptance/ and unmarked, same rationale as test_acceptance_isolation.py
-- this tests the loader, not a live product session.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_tests_dir = Path(__file__).parent
if str(_tests_dir) not in sys.path:
    sys.path.insert(0, str(_tests_dir))

from acceptance.turn_script import (  # noqa: E402
    SUPPORTED_VERSION,
    TurnScriptError,
    load_turn_script,
)


class TestLoadTurnScript:
    def test_loads_a_valid_script(self) -> None:
        script = load_turn_script(
            {
                "version": 1,
                "turns": [
                    {"prompt": "What is a decorator?"},
                    {"prompt": "And a closure?"},
                ],
            }
        )
        assert script.version == SUPPORTED_VERSION
        assert len(script.turns) == 2
        assert script.turns[0].prompt == "What is a decorator?"
        assert script.turns[1].prompt == "And a closure?"

    def test_rejects_expect_contains_until_an_executor_honours_it(self) -> None:
        """(minor finding) expect_contains/expect_not_contains are known,
        parsed fields with NOTHING evaluating them anywhere in the tree.
        Silently accepting a non-empty value would defeat the loader's own
        strict-unknown-field rule through a field that IS known -- reserve
        it loudly instead until an executor honours it."""
        with pytest.raises(TurnScriptError, match="expect_contains"):
            load_turn_script({"version": 1, "turns": [{"prompt": "hi", "expect_contains": ["x"]}]})

    def test_rejects_expect_not_contains_until_an_executor_honours_it(self) -> None:
        with pytest.raises(TurnScriptError, match="expect_not_contains"):
            load_turn_script(
                {"version": 1, "turns": [{"prompt": "hi", "expect_not_contains": ["x"]}]}
            )

    def test_rejects_missing_version(self) -> None:
        with pytest.raises(TurnScriptError, match="version"):
            load_turn_script({"turns": [{"prompt": "hi"}]})

    def test_rejects_unsupported_version(self) -> None:
        with pytest.raises(TurnScriptError, match="version"):
            load_turn_script({"version": 999, "turns": [{"prompt": "hi"}]})

    def test_rejects_unknown_top_level_field(self) -> None:
        with pytest.raises(TurnScriptError, match="unknown"):
            load_turn_script({"version": 1, "turns": [{"prompt": "hi"}], "extra_field": "typo"})

    def test_rejects_unknown_turn_field(self) -> None:
        with pytest.raises(TurnScriptError, match="unknown"):
            load_turn_script({"version": 1, "turns": [{"prompt": "hi", "expectt_contains": ["x"]}]})

    def test_rejects_empty_turns(self) -> None:
        with pytest.raises(TurnScriptError):
            load_turn_script({"version": 1, "turns": []})

    def test_rejects_missing_prompt(self) -> None:
        with pytest.raises(TurnScriptError, match="prompt"):
            load_turn_script({"version": 1, "turns": [{"expect_contains": ["x"]}]})

    def test_rejects_non_dict_input(self) -> None:
        with pytest.raises(TurnScriptError):
            load_turn_script([])  # type: ignore[arg-type]
