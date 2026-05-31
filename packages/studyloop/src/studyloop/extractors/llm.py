"""LLM struggle extractor — AWS Bedrock Converse API with forced tool-use.

Implements the same ``extract_struggles(messages, session_id) -> list[
ExtractorResult]`` contract as :mod:`studyloop.extractors.stub`, but infers real
struggle signals from session transcripts.

Transport: AWS Bedrock Converse API with ``toolChoice`` forcing a single
``emit_struggle_extractions`` tool call — the same structured-output mechanism
the card generator uses (see ``content/generators/bedrock.py``).  NOT httpx /
LiteLLM (the handoff was wrong about the transport).

Determinism: ``temperature=0`` on every call, so the eval signal is stable.

The system prompt embeds the canonical topic vocabulary
(``extractors/topic_vocab.json``) so the model normalises onto known keys,
keeping the quality-eval's Jaccard matching stable across prompt edits.

Testability: ``_build_client()`` is monkeypatchable and ``extract_struggles``
accepts an optional pre-built ``client``/``model`` — unit tests inject a Mock
bedrock-runtime client and never touch AWS.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

from studyloop.extractors import VALID_CONFIDENCE, ExtractorResult

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = logging.getLogger(__name__)

_TOOL_NAME = "emit_struggle_extractions"
_VOCAB_PATH = Path(__file__).resolve().parent / "topic_vocab.json"

# Default Bedrock target. Overridable via the function args; kept as module
# constants so the eval runner and tests reference one source of truth.
DEFAULT_MODEL = "us.anthropic.claude-sonnet-4-6"
DEFAULT_REGION = "us-east-1"
DEFAULT_PROFILE = "arraafat+prod-user"

# The JSON schema the model must satisfy. evidence_quote is required so the
# model must ground each struggle in the transcript (discourages hallucination)
# and so post-hoc human review is fast.
_TOOL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "struggles": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "Canonical topic domain key from the vocabulary.",
                    },
                    "concept": {
                        "type": "string",
                        "description": "Specific concept within the topic (kebab-case).",
                    },
                    "confidence": {
                        "type": "string",
                        "enum": sorted(VALID_CONFIDENCE),
                        "description": (
                            "'struggling' = confusion / repeated question / correction; "
                            "'learning' = new-topic exploration without confusion; "
                            "'confident' = demonstrated mastery."
                        ),
                    },
                    "evidence_quote": {
                        "type": "string",
                        "description": "Verbatim user-turn quote justifying this label.",
                    },
                },
                "required": ["topic", "concept", "confidence", "evidence_quote"],
            },
        }
    },
    "required": ["struggles"],
}


@lru_cache(maxsize=1)
def _load_vocab() -> dict[str, list[str]]:
    with open(_VOCAB_PATH, encoding="utf-8") as f:
        return json.load(f)


# Initial baseline prompt. This is the editable surface the P6 hill-climber
# mutates; for the P4 baseline it is a single reasonable starting point.
INITIAL_PROMPT = """\
You analyse a learner's study-session transcript and identify the specific \
topics they STRUGGLED with.

A topic is a STRUGGLE when the user turns show one or more of:
- the same question asked 2+ times, or a concept re-explained after the first try
- explicit confusion ("I don't understand", "still confused", "wait", "why does")
- the assistant correcting the user's mistake on that concept
- the user explicitly saying a concept was hard

Use confidence='learning' for genuine new-topic exploration WITHOUT confusion, \
and confidence='confident' only when the user demonstrably mastered something. \
Do NOT flag routine tool/debug output, build steps, or commands as struggles \
unless the user expressed confusion about the underlying concept.

Normalise every topic/concept onto the canonical vocabulary below. Pick the \
closest existing key; only invent a new concept (kebab-case) when nothing fits. \
Every struggle MUST include a verbatim evidence_quote from a user turn.

CANONICAL VOCABULARY (topic -> allowed concepts):
{vocab}

Call the emit_struggle_extractions tool exactly once with all struggles found. \
If the transcript contains no genuine struggles, return an empty struggles list."""


def _build_system_prompt(prompt_template: str = INITIAL_PROMPT) -> str:
    vocab = _load_vocab()
    vocab_lines = "\n".join(f"- {k}: {', '.join(v)}" for k, v in vocab.items())
    return prompt_template.format(vocab=vocab_lines)


def _build_client(
    *, profile: str = DEFAULT_PROFILE, region: str = DEFAULT_REGION
) -> Any:
    """Create a bedrock-runtime client. Monkeypatched in unit tests.

    boto3 is imported lazily so the ``[sessions]``-only install does not need
    it; the eval / live path requires the ``[bedrock]`` extra.
    """
    try:
        import boto3
    except ImportError as exc:  # pragma: no cover - install-time guard
        raise RuntimeError(
            "LLM extractor requires boto3. Install with: "
            "uv pip install 'studyloop[bedrock]' (or run eval via uv run --with boto3)."
        ) from exc
    return boto3.Session(profile_name=profile).client(
        "bedrock-runtime", region_name=region
    )


def _transcript_text(messages: Sequence[dict[str, Any]], *, max_chars: int = 15000) -> str:
    """Flatten user+assistant turns into a bounded transcript string."""
    parts: list[str] = []
    for m in messages:
        role = m.get("role")
        if role not in ("user", "assistant"):
            continue
        content = (m.get("content") or "").strip()
        if not content:
            continue
        parts.append(f"[{role}] {content}")
    text = "\n".join(parts)
    return text[:max_chars]


def _to_results(payload: dict[str, Any]) -> list[ExtractorResult]:
    """Normalise the tool-use payload into validated ExtractorResults.

    Invalid entries are dropped (logged), not fatal — a single malformed item
    must not sink an otherwise-good extraction.
    """
    out: list[ExtractorResult] = []
    for item in payload.get("struggles", []):
        try:
            result = ExtractorResult(
                topic=str(item.get("topic", "")).strip().lower(),
                concept=str(item.get("concept", "")).strip().lower(),
                confidence=str(item.get("confidence", "")).strip().lower(),
                notes=item.get("evidence_quote"),
            ).validate()
        except (ValueError, AttributeError) as exc:
            logger.warning("Dropping invalid extraction %r: %s", item, exc)
            continue
        out.append(result)
    return out


def extract_struggles(
    messages: Sequence[dict[str, Any]],
    session_id: str,
    *,
    client: Any | None = None,
    model: str = DEFAULT_MODEL,
    prompt_template: str = INITIAL_PROMPT,
    temperature: float = 0.0,
    max_tokens: int = 2048,
) -> list[ExtractorResult]:
    """Extract struggle signals from a session transcript via Bedrock Converse.

    Returns the *last* usage dict on the function as ``extract_struggles.last_usage``
    so the eval runner can tally cost without changing the return type.
    """
    transcript = _transcript_text(messages)
    if not transcript:
        extract_struggles.last_usage = {}  # type: ignore[attr-defined]
        return []

    bedrock = client if client is not None else _build_client()
    tool_config = {
        "tools": [
            {
                "toolSpec": {
                    "name": _TOOL_NAME,
                    "description": "Emit the struggle signals found in this session.",
                    "inputSchema": {"json": _TOOL_SCHEMA},
                }
            }
        ],
        "toolChoice": {"tool": {"name": _TOOL_NAME}},
    }

    response = bedrock.converse(
        modelId=model,
        system=[{"text": _build_system_prompt(prompt_template)}],
        messages=[
            {
                "role": "user",
                "content": [
                    {"text": f"Session {session_id} transcript:\n\n{transcript}"}
                ],
            }
        ],
        inferenceConfig={"temperature": temperature, "maxTokens": max_tokens},
        toolConfig=tool_config,
    )

    extract_struggles.last_usage = response.get("usage", {})  # type: ignore[attr-defined]

    for block in response.get("output", {}).get("message", {}).get("content", []):
        tool_use = block.get("toolUse")
        if tool_use and tool_use.get("name") == _TOOL_NAME:
            payload = tool_use.get("input")
            if isinstance(payload, dict):
                return _to_results(payload)
            logger.warning("tool-use input not a dict for %s: %r", session_id, payload)
            return []

    stop = response.get("stopReason", "<unknown>")
    logger.warning("Model did not call %s for %s (stopReason=%s)", _TOOL_NAME, session_id, stop)
    return []


# Initialised so callers can read it even before the first call.
extract_struggles.last_usage = {}  # type: ignore[attr-defined]

__all__ = ["extract_struggles", "INITIAL_PROMPT", "DEFAULT_MODEL", "DEFAULT_REGION", "DEFAULT_PROFILE"]
