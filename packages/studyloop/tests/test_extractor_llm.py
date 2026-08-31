"""Unit tests for the LLM struggle extractor — fully mocked, zero API cost.

A fake bedrock-runtime client is injected via the ``client=`` arg, so no AWS
call ever happens. These assert the extractor's request shape and its parsing /
validation of the Converse tool-use response — NOT the quality of real
inference (that is the live eval tier).
"""

from __future__ import annotations

import sys
from typing import Any
from unittest.mock import MagicMock

import pytest

from studyloop.extractors import ExtractorResult
from studyloop.extractors.llm import _TOOL_NAME, extract_struggles

_TEST_MODEL = "example.live-model"


def _converse_response(struggles: list[dict[str, Any]], *, usage: dict | None = None) -> dict:
    """Build a Converse response with a forced tool-use block."""
    return {
        "output": {
            "message": {
                "content": [
                    {
                        "toolUse": {
                            "toolUseId": "t1",
                            "name": _TOOL_NAME,
                            "input": {"struggles": struggles},
                        }
                    }
                ]
            }
        },
        "stopReason": "tool_use",
        "usage": usage or {"inputTokens": 100, "outputTokens": 20},
    }


def _mock_client(response: dict) -> MagicMock:
    client = MagicMock()
    client.converse.return_value = response
    return client


def test_model_is_required_for_every_live_extraction() -> None:
    client = _mock_client(_converse_response([]))

    with pytest.raises(TypeError):
        extract_struggles(  # type: ignore[call-arg]
            [{"role": "user", "content": "explain protocols"}],
            "sess-model-required",
            client=client,
        )


def test_live_extractor_uses_ambient_aws_identity_without_hardcoded_profile_or_region(
    monkeypatch,
) -> None:
    bedrock = _mock_client(_converse_response([]))
    boto3 = MagicMock()
    boto3.Session.return_value.client.return_value = bedrock
    monkeypatch.setitem(sys.modules, "boto3", boto3)

    extract_struggles(
        [{"role": "user", "content": "explain protocols"}],
        "sess-ambient-aws",
        model="example.live-model",
    )

    boto3.Session.assert_called_once_with()
    boto3.Session.return_value.client.assert_called_once_with("bedrock-runtime")


def test_returns_validated_results_from_tool_use() -> None:
    client = _mock_client(
        _converse_response(
            [
                {
                    "topic": "Python",
                    "concept": "ABC-vs-Protocol",
                    "confidence": "struggling",
                    "evidence_quote": "I don't understand the difference",
                }
            ]
        )
    )
    results = extract_struggles(
        [{"role": "user", "content": "explain ABC vs Protocol"}],
        "sess-1",
        model=_TEST_MODEL,
        client=client,
    )
    assert len(results) == 1
    r = results[0]
    assert isinstance(r, ExtractorResult)
    assert r.topic == "python"  # normalised lower
    assert r.concept == "abc-vs-protocol"
    assert r.confidence == "struggling"
    assert r.notes == "I don't understand the difference"


def test_zero_user_messages_returns_empty_without_calling_bedrock() -> None:
    client = _mock_client(_converse_response([]))
    results = extract_struggles([], "sess-empty", model=_TEST_MODEL, client=client)
    assert results == []
    client.converse.assert_not_called()  # short-circuits before any API call


def test_only_tool_role_messages_returns_empty() -> None:
    """Transcript with no user/assistant turns yields empty (nothing to send)."""
    client = _mock_client(_converse_response([]))
    msgs = [{"role": "tool_use", "content": "{}"}, {"role": "tool_result", "content": "{}"}]
    results = extract_struggles(msgs, "sess-tools", model=_TEST_MODEL, client=client)
    assert results == []
    client.converse.assert_not_called()


def test_invalid_confidence_dropped_not_crash() -> None:
    """A bad confidence value drops that entry; valid entries survive."""
    client = _mock_client(
        _converse_response(
            [
                {"topic": "python", "concept": "abc", "confidence": "BOGUS", "evidence_quote": "x"},
                {
                    "topic": "sql",
                    "concept": "joins",
                    "confidence": "struggling",
                    "evidence_quote": "y",
                },
            ]
        )
    )
    results = extract_struggles(
        [{"role": "user", "content": "q"}], "sess-2", model=_TEST_MODEL, client=client
    )
    assert len(results) == 1
    assert results[0].topic == "sql"


def test_empty_topic_entry_dropped() -> None:
    client = _mock_client(
        _converse_response(
            [
                {"topic": "", "concept": "abc", "confidence": "struggling", "evidence_quote": "x"},
                {
                    "topic": "python",
                    "concept": "decorators",
                    "confidence": "learning",
                    "evidence_quote": "y",
                },
            ]
        )
    )
    results = extract_struggles(
        [{"role": "user", "content": "q"}], "sess-3", model=_TEST_MODEL, client=client
    )
    assert len(results) == 1
    assert results[0].concept == "decorators"


def test_model_skips_tool_returns_empty() -> None:
    """If the model emits text instead of the forced tool, return empty (not crash)."""
    client = _mock_client(
        {
            "output": {"message": {"content": [{"text": "I refuse"}]}},
            "stopReason": "end_turn",
            "usage": {"inputTokens": 10, "outputTokens": 5},
        }
    )
    results = extract_struggles(
        [{"role": "user", "content": "q"}], "sess-4", model=_TEST_MODEL, client=client
    )
    assert results == []


def test_request_shape_forces_the_tool() -> None:
    """The default request forces tool use without model-specific temperature."""
    client = _mock_client(_converse_response([]))
    extract_struggles(
        [{"role": "user", "content": "q"}], "sess-5", model=_TEST_MODEL, client=client
    )
    client.converse.assert_called_once()
    kwargs = client.converse.call_args.kwargs
    assert kwargs["toolConfig"]["toolChoice"] == {"tool": {"name": _TOOL_NAME}}
    assert kwargs["inferenceConfig"] == {"maxTokens": 2048}
    tool_names = [t["toolSpec"]["name"] for t in kwargs["toolConfig"]["tools"]]
    assert _TOOL_NAME in tool_names


def test_explicit_temperature_is_forwarded_for_models_that_support_it() -> None:
    client = _mock_client(_converse_response([]))
    extract_struggles(
        [{"role": "user", "content": "q"}],
        "sess-temp",
        model=_TEST_MODEL,
        client=client,
        temperature=0.0,
    )

    kwargs = client.converse.call_args.kwargs
    assert kwargs["inferenceConfig"] == {"maxTokens": 2048, "temperature": 0.0}


def test_usage_recorded_for_cost_tracking() -> None:
    client = _mock_client(_converse_response([], usage={"inputTokens": 555, "outputTokens": 66}))
    extract_struggles(
        [{"role": "user", "content": "q"}], "sess-6", model=_TEST_MODEL, client=client
    )
    assert extract_struggles.last_usage == {"inputTokens": 555, "outputTokens": 66}
