"""``get_next_action(..., interleave="off")`` — the D-8 last-writer commit (T3.5).

The CLI (``studyloop now --interleave``) and the Web (``GET /api/now?interleave=``)
already expose the engine's ``InterleaveMode``; the MCP tool did not, so an
agent could not ask for the adaptive mix a learner can ask for at a shell. MCP
``interleave`` parity is #10's acceptance criterion (design §4: "#11 → #12 →
#10's final ``interleave`` commit"; council review 3 landed it after #11 with
#12 not yet started, the file being otherwise quiet).

The argument is a plain string like ``energy`` and ``modality`` — MCP clients
send strings — validated against ``get_args(InterleaveMode)`` before the
engine is called, with the same ``ToolError`` wording pattern, then ``cast``
and forwarded. Nothing else in ``mcp/tools.py`` moves in that commit.

Isolated like ``test_now_plan_guidance.py``: an empty world and a frozen clock,
so the default call can be compared with the golden the no-plan emit is pinned
to.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("mcp")

from mcp.server.fastmcp.exceptions import ToolError
from test_now_plan_guidance import isolate_now_world

from studyloop.learning import decision

GOLDEN = Path(__file__).parent / "golden" / "now_plan_no_active.json"


@pytest.fixture(autouse=True)
def now_world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    return isolate_now_world(tmp_path, monkeypatch)


def _registry():
    from studyloop.mcp.server import mcp

    return mcp._tool_manager._tools


def _tool():
    return _registry()["get_next_action"].fn


def _schema() -> dict[str, Any]:
    return _registry()["get_next_action"].parameters


def test_get_next_action_schema_adds_interleave_default_off() -> None:
    props = _schema()["properties"]

    assert set(props) == {"energy", "time_minutes", "modality", "interleave"}
    assert props["interleave"]["default"] == "off"
    assert "interleave" not in _schema().get("required", [])
    # The three existing arguments and their defaults are untouched.
    assert props["energy"]["default"] == "medium"
    assert props["time_minutes"]["default"] == 25
    assert props["modality"]["default"] == "recall"


def test_get_next_action_forwards_adaptive_interleave_once(monkeypatch) -> None:
    """The tool is a thin door: one ``build_now_plan`` call with the validated
    literal, and the response is that plan's ``to_json_dict()``."""
    calls: list[dict[str, Any]] = []
    real = decision.build_now_plan

    def spy(**kwargs):
        calls.append(kwargs)
        return real(**kwargs)

    monkeypatch.setattr(decision, "build_now_plan", spy)

    payload = _tool()(energy="high", time_minutes=40, modality="visual", interleave="adaptive")

    assert calls == [
        {"energy": "high", "time_minutes": 40, "modality": "visual", "interleave": "adaptive"}
    ]
    assert payload["interleave"] == "adaptive"
    assert payload["energy"] == "high"


@pytest.mark.parametrize("energy", ["medium", "high"])
def test_get_next_action_adaptive_returns_nonempty_ratio(energy: decision.EnergyLevel) -> None:
    """Parity with ``studyloop now --interleave adaptive``: the response reports the
    adaptive mix for the energy, exactly as the engine's ``INTERLEAVE_RATIOS``."""
    payload = _tool()(energy=energy, interleave="adaptive")

    assert payload["interleave"] == "adaptive"
    assert payload["interleave_ratio"] == decision.INTERLEAVE_RATIOS[energy]
    assert sum(payload["interleave_ratio"].values()) == 100


@pytest.mark.parametrize("bad", ["ADAPTIVE", "random", "", "on"])
def test_get_next_action_invalid_interleave_names_choices_without_engine_call(
    monkeypatch, bad: str
) -> None:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(decision, "build_now_plan", lambda **kw: calls.append(kw))

    with pytest.raises(ToolError, match=r"^Invalid interleave") as caught:
        _tool()(interleave=bad)

    message = str(caught.value)
    assert repr(bad) in message
    assert "'off'" in message
    assert "'adaptive'" in message
    assert calls == [], "a refused value never reaches the engine"


def test_get_next_action_default_and_explicit_off_match_unchanged_golden() -> None:
    """The default call is byte-for-byte what it was before the argument existed
    (the no-plan golden), and ``interleave="off"`` is the same call."""
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))

    assert _tool()() == golden
    assert _tool()(interleave="off") == golden
    assert _tool()()["interleave"] == "off"


def test_get_next_action_energy_and_modality_validation_unchanged() -> None:
    """The existing refusals keep their wording; the new one sits beside them."""
    with pytest.raises(ToolError, match=r"^Invalid energy 'LOW'"):
        _tool()(energy="LOW")
    with pytest.raises(ToolError, match=r"^Invalid modality 'recal'"):
        _tool()(modality="recal")
