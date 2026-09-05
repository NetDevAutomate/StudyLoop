import json

import pytest

from experiments.evidence_context.metadata_value.normalization_audit import parse_diagnostic


def test_fence_removal_preserves_string_escapes():
    answer = {"quote": "first\nsecond", "literal": r"\n", "ticks": "```"}
    encoded = json.dumps(answer)
    assert parse_diagnostic(encoded) == (answer, "original_json")
    assert parse_diagnostic("```json\n" + encoded + "\n```") == (answer, "complete_fence_removed")


@pytest.mark.parametrize(
    "text",
    [
        'Here is JSON: {"x": 1}',
        '```json\n{"x": 1}\n``` followed by prose',
        '```json\n{"x": 1}\n```\n```json\n{"x": 2}\n```',
        '```json\n{"x": }\n```',
        '```python\n{"x": 1}\n```',
    ],
)
def test_diagnostic_does_not_repair_or_extract_arbitrary_content(text):
    with pytest.raises(ValueError):
        parse_diagnostic(text)
