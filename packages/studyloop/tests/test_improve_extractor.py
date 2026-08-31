"""Contract tests for model-compatible extractor prompt mutation."""

from unittest.mock import MagicMock

from studyloop.extractors.improve_extractor import _mutate_prompt


def _client() -> MagicMock:
    client = MagicMock()
    client.converse.return_value = {
        "output": {
            "message": {
                "content": [
                    {
                        "text": (
                            "<prompt>Keep {vocab} and call emit_struggle_extractions once.</prompt>"
                        )
                    }
                ]
            }
        },
        "usage": {"inputTokens": 1, "outputTokens": 1},
    }
    return client


def test_meta_mutation_omits_temperature_by_default() -> None:
    client = _client()

    prompt, _cost = _mutate_prompt(client, "current", 0.5, "none", "example.model")

    assert prompt is not None
    assert client.converse.call_args.kwargs["inferenceConfig"] == {"maxTokens": 4096}


def test_meta_mutation_forwards_explicit_supported_temperature() -> None:
    client = _client()

    prompt, _cost = _mutate_prompt(
        client,
        "current",
        0.5,
        "none",
        "example.model",
        temperature=0.7,
    )

    assert prompt is not None
    assert client.converse.call_args.kwargs["inferenceConfig"] == {
        "maxTokens": 4096,
        "temperature": 0.7,
    }
