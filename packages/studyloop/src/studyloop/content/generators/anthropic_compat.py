"""Anthropic Messages API-compatible :class:`CardGenerator`.

Covers Anthropic itself plus any shim that speaks the Messages protocol.
(MiniMax's ``/anthropic`` shim was the original second consumer; it was
removed as a provider 2026-06-01, but the protocol-robustness handling it
prompted is retained here — see the inline-XML / tool_result notes below.)
The adapter shape is identical to :class:`OpenAICompatGenerator`; only
the wire format differs:

- POST ``/v1/messages`` (not ``/chat/completions``)
- ``x-api-key: ${env[auth_env]}`` header (not ``Authorization: Bearer``)
- Tool definition shape: ``{name, description, input_schema}`` (vs
  OpenAI's ``{type:"function", function:{name, parameters}}``)
- Forced tool choice: ``tool_choice={"type":"tool","name":...}`` (vs
  OpenAI's ``{type:"function","function":{"name":...}}``)
- Tool result is a ``tool_use`` content block (vs OpenAI's ``tool_calls``
  on the message)

Bedrock vs Anthropic-direct
---------------------------

:class:`BedrockGenerator` calls Bedrock's Converse API which is *similar*
to Messages but uses boto3, profile-based auth, and the Converse-shaped
tool config. We deliberately keep that as a separate path -- collapsing
the two would mean an httpx adapter for Bedrock (drops profile fallback,
requires SigV4 signing) or a boto3 adapter for Anthropic (heavyweight
import for HTTP-only providers). The line between adapter classes is
**SDK choice and auth model**, not just wire format.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

import httpx

from studyloop.content.generators import CardGenerationError
from studyloop.content.generators._retry import CallContext, call_with_correction
from studyloop.content.generators.prompts import (
    FLASHCARD_SYSTEM_PROMPT,
    FLASHCARD_USER_PROMPT_TEMPLATE,
    PRACTICE_SYSTEM_PROMPT,
    PRACTICE_USER_PROMPT_TEMPLATE,
    QUIZ_SYSTEM_PROMPT,
    QUIZ_USER_PROMPT_TEMPLATE,
)
from studyloop.content.schemas import (
    FlashcardDeck,
    PracticeDeck,
    QuizDeck,
    flashcard_deck_json_schema,
    practice_deck_json_schema,
    quiz_deck_json_schema,
)

if TYPE_CHECKING:
    from studyloop.content.generators.provider_profiles import (
        ModelEntry,
        ProviderProfile,
    )
    from studyloop.settings import CardGeneratorConfig


_FLASHCARD_TOOL_NAME = "emit_flashcard_deck"
_QUIZ_TOOL_NAME = "emit_quiz_deck"
_PRACTICE_TOOL_NAME = "emit_practice_deck"

# Anthropic's API requires an api-version header; this is the stable
# value at the time of writing. Update only if the user sees breaking
# behaviour after a vendor announcement.
_ANTHROPIC_API_VERSION = "2023-06-01"

# Reasoning models get a 3x request_timeout multiplier. For Anthropic
# that's `claude-*-thinking` variants and any future thinking flag.
_THINKING_TIMEOUT_MULT = 3.0
# Default thinking budget for thinking-flagged models (Claude only;
# MiniMax ignores this field at time of writing).
_THINKING_BUDGET_TOKENS = 2000

# Default max_tokens for the response. Big enough for a 12-card deck
# with rationales; small enough to bound cost on a runaway model.
_DEFAULT_MAX_TOKENS = 4096


# MiniMax M2.7 sometimes emits the forced tool call as inline XML markup inside
# a text block rather than a native Anthropic tool_use block, e.g.:
#   <minimax:tool_call>
#   <invoke name="emit_quiz_deck">
#   <parameter name="title">"DT"</parameter>
#   <parameter name="questions">[ ... JSON ... ]</parameter>
#   </invoke>
#   </minimax:tool_call>
# Each <parameter> value is the JSON encoding of that key's value. We reassemble
# them into the tool-input dict the schema expects.
_INVOKE_RE = re.compile(r'<invoke\s+name="(?P<name>[^"]+)"\s*>(?P<body>.*?)</invoke>', re.DOTALL)
_PARAM_RE = re.compile(
    r'<parameter\s+name="(?P<key>[^"]+)"\s*>(?P<val>.*?)</parameter>', re.DOTALL
)


def _parse_inline_tool_call(text: str, expected_tool_name: str) -> dict[str, Any] | None:
    """Parse MiniMax's inline ``<invoke>`` markup into a tool-input dict.

    Returns the assembled tool input, or ``None`` if the text contains no
    matching ``<invoke name="<expected_tool_name>">`` block (so a genuine
    text-only refusal still surfaces as an error upstream).
    """
    for m in _INVOKE_RE.finditer(text):
        if m.group("name") != expected_tool_name:
            continue
        body = m.group("body")
        params: dict[str, Any] = {}
        for pm in _PARAM_RE.finditer(body):
            key = pm.group("key")
            raw = pm.group("val").strip()
            try:
                params[key] = json.loads(raw)
            except (ValueError, json.JSONDecodeError):
                # Fall back to the raw string when a value isn't JSON-encoded
                # (e.g. a bare title); the schema validator catches real misses.
                params[key] = raw
        if params:
            return params
    return None


class AnthropicCompatGenerator:
    """Card generator backed by any Anthropic Messages-compatible API.

    Configured via a :class:`ProviderProfile` (base URL, auth env var,
    model list) plus the selected :class:`ModelEntry`.
    """

    def __init__(
        self,
        config: CardGeneratorConfig,
        profile: ProviderProfile,
        model: ModelEntry,
    ) -> None:
        self._config = config
        self._profile = profile
        self._model = model
        self._api_key = self._read_api_key()
        timeout = self._effective_timeout()
        self._client = httpx.Client(
            base_url=profile.base_url.rstrip("/"),
            timeout=timeout,
            headers={
                "x-api-key": self._api_key,
                "anthropic-version": _ANTHROPIC_API_VERSION,
                "Content-Type": "application/json",
            },
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> AnthropicCompatGenerator:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # ------------------------------------------------------------------
    # CardGenerator Protocol
    # ------------------------------------------------------------------

    def generate_flashcards(self, source: str, title: str) -> FlashcardDeck:
        deck = self._generate(
            system_prompt=FLASHCARD_SYSTEM_PROMPT,
            user_prompt=FLASHCARD_USER_PROMPT_TEMPLATE.format(title=title, source=source),
            tool_name=_FLASHCARD_TOOL_NAME,
            tool_description="Emit a flashcard deck matching the provided JSON schema.",
            schema=flashcard_deck_json_schema(),
            model_cls=FlashcardDeck,
        )
        if deck.title != title:
            deck = deck.model_copy(update={"title": title})
        return deck

    def generate_quiz(self, source: str, title: str) -> QuizDeck:
        deck = self._generate(
            system_prompt=QUIZ_SYSTEM_PROMPT,
            user_prompt=QUIZ_USER_PROMPT_TEMPLATE.format(title=title, source=source),
            tool_name=_QUIZ_TOOL_NAME,
            tool_description="Emit a multiple-choice quiz deck matching the provided JSON schema.",
            schema=quiz_deck_json_schema(),
            model_cls=QuizDeck,
        )
        if deck.title != title:
            deck = deck.model_copy(update={"title": title})
        return deck

    def generate_practice(self, source: str, title: str) -> PracticeDeck:
        deck = self._generate(
            system_prompt=PRACTICE_SYSTEM_PROMPT,
            user_prompt=PRACTICE_USER_PROMPT_TEMPLATE.format(title=title, source=source),
            tool_name=_PRACTICE_TOOL_NAME,
            tool_description="Emit a hands-on practice deck matching the provided JSON schema.",
            schema=practice_deck_json_schema(),
            model_cls=PracticeDeck,
        )
        if deck.title != title:
            deck = deck.model_copy(update={"title": title})
        return deck

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _read_api_key(self) -> str:
        # Resolution order (encrypted store -> env var -> None) lives in
        # secrets.get_secret; call it so a key added via the Generate panel
        # (encrypted store) is honoured, not just one exported in the shell.
        from studyloop.secrets import get_secret

        key = (get_secret(self._profile.slug) or "").strip()
        if not key:
            raise CardGenerationError(
                f"{self._profile.label} requires an API key. Add it in the web "
                f"Generate panel (stored encrypted), or set {self._profile.auth_env} "
                f"in your shell env / project-root .env file."
            )
        return key

    def _effective_timeout(self) -> float:
        base = self._config.request_timeout
        return base * _THINKING_TIMEOUT_MULT if self._model.thinking else base

    def _generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        tool_name: str,
        tool_description: str,
        schema: dict[str, Any],
        model_cls: type[FlashcardDeck] | type[QuizDeck] | type[PracticeDeck],
    ) -> Any:
        # Anthropic puts system prompt in a top-level field, not in the
        # messages array. Different from OpenAI -- this is one of the
        # genuine wire-shape divergences between specs.
        base_messages: list[dict[str, Any]] = [
            {"role": "user", "content": user_prompt},
        ]
        tools = [
            {
                "name": tool_name,
                "description": tool_description,
                "input_schema": schema,
            }
        ]
        tool_choice = {"type": "tool", "name": tool_name}

        def call(ctx: CallContext) -> tuple[Any, list[dict[str, Any]]]:
            history = list(ctx.history_extension)
            # On a retry, fill in the real validation error on the tool_result
            # placeholder that the previous attempt appended. The Anthropic
            # Messages spec requires the user turn after an assistant tool_use
            # to be a tool_result for that tool_use id; MiniMax's /anthropic
            # shim enforces this strictly (a plain-text user turn -> error
            # 2013). Carrying the correction AS a tool_result keeps the
            # alternation valid across all providers.
            if ctx.last_error is not None and history:
                last = history[-1]
                if (
                    last.get("role") == "user"
                    and isinstance(last.get("content"), list)
                    and last["content"]
                    and last["content"][0].get("type") == "tool_result"
                ):
                    last["content"][0]["content"] = (
                        f"The previous tool call did not validate against the "
                        f"schema: {ctx.last_error}. Re-emit a corrected payload "
                        f"that conforms exactly."
                    )

            messages = list(base_messages) + history

            payload: dict[str, Any] = {
                "model": self._model.id,
                "system": system_prompt,
                "messages": messages,
                "tools": tools,
                "tool_choice": tool_choice,
                "temperature": self._config.temperature,
                "max_tokens": _DEFAULT_MAX_TOKENS,
            }
            if self._model.thinking:
                payload["thinking"] = {
                    "type": "enabled",
                    "budget_tokens": _THINKING_BUDGET_TOKENS,
                }

            resp = self._post_messages(payload)
            tool_payload, assistant_turn, tool_use_id = self._extract_tool_payload(
                resp, tool_name
            )
            # Append the assistant's tool_use turn followed immediately by a
            # placeholder tool_result so the history stays protocol-valid. If
            # validation fails, the NEXT attempt overwrites the placeholder
            # content with the actual error (above).
            new_history = [
                *history,
                assistant_turn,
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": tool_use_id,
                            "content": "Acknowledged.",
                        }
                    ],
                },
            ]
            return tool_payload, new_history

        return call_with_correction(
            model_cls=model_cls,
            max_retries=self._config.max_retries,
            call_fn=call,
        )

    def _post_messages(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            r = self._client.post("/v1/messages", json=payload)
        except httpx.HTTPError as exc:
            raise CardGenerationError(
                f"{self._profile.label} request failed: {exc!r}"
            ) from exc

        if r.status_code >= 400:
            body = r.text[:500]
            raise CardGenerationError(
                f"{self._profile.label} returned HTTP {r.status_code}: {body}"
            )
        try:
            return r.json()
        except ValueError as exc:
            raise CardGenerationError(
                f"{self._profile.label} returned non-JSON body: {r.text[:200]!r}"
            ) from exc

    def _extract_tool_payload(
        self, resp: dict[str, Any], expected_tool_name: str
    ) -> tuple[dict[str, Any], dict[str, Any], str]:
        """Pull the ``tool_use`` block out of an Anthropic Messages response.

        Anthropic returns ``content`` as a list of typed blocks. With
        forced tool_choice, exactly one of those blocks should be a
        ``{type:"tool_use", name, input}`` block. We assemble the
        assistant turn from the full content list so the correction-turn
        history sees what the model actually said.

        Returns ``(tool_input, assistant_turn, tool_use_id)``. The
        ``tool_use_id`` lets the caller build a protocol-valid
        ``tool_result`` correction turn that references this exact call.
        """
        content = resp.get("content")
        if not isinstance(content, list) or not content:
            raise CardGenerationError(
                f"{self._profile.label} response missing content blocks: "
                f"{json.dumps(resp)[:300]}"
            )

        tool_use_block = None
        for block in content:
            if block.get("type") == "tool_use":
                tool_use_block = block
                break

        if tool_use_block is None:
            # MiniMax M2.7 intermittently narrates the tool call as inline XML
            # markup inside a text block instead of emitting a native tool_use
            # block (a reasoning-model quirk). Parse that fallback before giving
            # up, so generation doesn't fail ~half the time on this provider.
            text_blocks = [b for b in content if b.get("type") == "text"]
            full_text = "".join(b.get("text", "") for b in text_blocks)
            inline = _parse_inline_tool_call(full_text, expected_tool_name)
            if inline is not None:
                assistant_turn = {"role": "assistant", "content": content}
                return inline, assistant_turn, "toolu_inline"
            preview = full_text[:200]
            raise CardGenerationError(
                f"{self._profile.label} response missing tool_use block "
                f"(expected {expected_tool_name!r}). Text content was: {preview!r}"
            )

        if tool_use_block.get("name") != expected_tool_name:
            raise CardGenerationError(
                f"{self._profile.label} called wrong tool: "
                f"got {tool_use_block.get('name')!r}, expected {expected_tool_name!r}"
            )

        args = tool_use_block.get("input")
        if args is None:
            raise CardGenerationError(
                f"{self._profile.label} tool_use missing input field"
            )
        if not isinstance(args, dict):
            raise CardGenerationError(
                f"{self._profile.label} tool_use input is not an object: "
                f"{type(args).__name__}"
            )

        assistant_turn = {"role": "assistant", "content": content}
        tool_use_id = str(tool_use_block.get("id") or "toolu_correction")
        return args, assistant_turn, tool_use_id


__all__ = ["AnthropicCompatGenerator"]
