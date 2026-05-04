"""AWS Bedrock-backed :class:`CardGenerator` using Claude.

Uses the Bedrock Runtime ``Converse`` API with **tool-use** as the
structured-output mechanism. The pydantic schema becomes a tool's
``inputSchema.json``; ``toolChoice`` forces the model to invoke that
tool, so the model's reply is guaranteed to be a ``toolUse`` block
with a payload matching our schema.

Why tool-use and not the older ``invoke_model`` + Anthropic beta
headers:

- Converse is the current-generation Bedrock API with a unified
  message format. Fewer surprises, better SDK support.
- ``toolChoice: {"tool": {"name": ...}}`` (available in Converse
  since late 2024) is the canonical way to force Claude into
  structured output on Bedrock. No beta headers, no SSE parsing.
- The legacy ``response_format: {"type": "json_object"}`` does not
  exist on Bedrock Claude. Tool-use is the only robust path.

Profile fallback
----------------

Try ``config.bedrock.profile`` first; if it's missing or the call
fails with a credential error, try ``config.bedrock.profile_fallback``.
This keeps one ``config.yaml`` usable across machines where only one
profile exists on each.

Networking analogy
------------------

Profile fallback here is like **BGP local-pref with a secondary peer**:
we prefer the prod peer (``bedrock-prod``) when reachable, but if the
session can't be established (credentials chain broken on this host),
we silently fall back to the secondary peer (``bedrock-local``) rather
than blackholing traffic. The CallerIdentity check is the peer
keepalive.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from studyctl.content.generators import CardGenerationError
from studyctl.content.generators.prompts import (
    FLASHCARD_SYSTEM_PROMPT,
    FLASHCARD_USER_PROMPT_TEMPLATE,
    QUIZ_SYSTEM_PROMPT,
    QUIZ_USER_PROMPT_TEMPLATE,
)
from studyctl.content.schemas import (
    FlashcardDeck,
    QuizDeck,
    flashcard_deck_json_schema,
    quiz_deck_json_schema,
)

if TYPE_CHECKING:
    from studyctl.settings import CardGeneratorConfig

_DECK_MODELS = FlashcardDeck | QuizDeck

# Tool names the model must invoke. Exposed as constants so tests can
# stub the Converse response without hard-coding these strings in two
# places.
_FLASHCARD_TOOL_NAME = "emit_flashcard_deck"
_QUIZ_TOOL_NAME = "emit_quiz_deck"


class BedrockGenerator:
    """Card generator backed by AWS Bedrock (Claude via Converse API).

    Satisfies the :class:`studyctl.content.generators.CardGenerator`
    Protocol structurally.
    """

    def __init__(self, config: CardGeneratorConfig) -> None:
        self._config = config
        self._bedrock = config.bedrock
        self._client, self._client_model = self._build_client(
            region=self._bedrock.region, model=self._bedrock.model
        )
        # Optional fallback client for cross-region failover on throttle.
        self._fallback_client: Any | None = None
        self._fallback_model: str | None = None
        if (
            self._bedrock.fallback_region
            and self._bedrock.fallback_model
            and self._bedrock.fallback_region != self._bedrock.region
        ):
            try:
                self._fallback_client, self._fallback_model = self._build_client(
                    region=self._bedrock.fallback_region,
                    model=self._bedrock.fallback_model,
                )
            except CardGenerationError:
                # Fallback unavailable is not fatal -- primary still works.
                self._fallback_client = None
                self._fallback_model = None

    def close(self) -> None:
        """No-op -- boto3 clients don't need explicit close.

        Kept for symmetry with :class:`OllamaGenerator` so the Protocol
        users can treat any backend identically.
        """
        return None

    def __enter__(self) -> BedrockGenerator:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Client construction with profile fallback
    # ------------------------------------------------------------------

    def _build_client(self, *, region: str, model: str) -> tuple[Any, str]:
        """Create a ``bedrock-runtime`` client for the given region.

        Tries the primary profile first; falls back to ``profile_fallback``
        on missing profile / credential errors / STS keepalive failure.
        Returns ``(client, model)`` so callers can associate the returned
        client with the model that will run on it (useful for the
        region-fallback case where primary and fallback use different
        inference-profile IDs).
        """
        # Local import so users on the ``[content]``-only install don't pull boto3.
        try:
            import boto3
            from botocore.config import Config as BotoConfig
            from botocore.exceptions import (
                NoCredentialsError,
                ProfileNotFound,
            )
        except ImportError as exc:
            raise CardGenerationError(
                "Bedrock backend requires boto3. Install with: pip install 'studyctl[bedrock]'."
            ) from exc

        # Explicit read/connect timeouts for the Converse client. The
        # user-facing ``request_timeout`` is the read timeout; connect
        # stays conservative at 10 s.
        boto_config = BotoConfig(
            connect_timeout=10,
            read_timeout=self._config.request_timeout,
            retries={"max_attempts": 1, "mode": "standard"},
        )
        # STS keepalive uses a tight timeout -- a profile that fails to
        # resolve should fall back in seconds, not wait the full
        # request_timeout before giving up.
        sts_config = BotoConfig(
            connect_timeout=5,
            read_timeout=5,
            retries={"max_attempts": 1, "mode": "standard"},
        )

        profiles: list[str] = [self._bedrock.profile]
        if self._bedrock.profile_fallback and self._bedrock.profile_fallback not in profiles:
            profiles.append(self._bedrock.profile_fallback)

        last_error: Exception | None = None
        for profile in profiles:
            if not profile:
                continue
            try:
                session = boto3.Session(profile_name=profile)
                client = session.client(
                    "bedrock-runtime",
                    region_name=region,
                    config=boto_config,
                )
            except ProfileNotFound as exc:
                last_error = exc
                continue
            except NoCredentialsError as exc:
                last_error = exc
                continue

            # Verify creds actually resolve via STS before returning. This
            # catches expired creds / revoked roles *here*, not mid-Converse.
            try:
                sts = session.client("sts", region_name=region, config=sts_config)
                sts.get_caller_identity()
            except Exception as exc:
                last_error = exc
                continue

            return client, model

        # Both profiles failed. Surface a helpful error.
        tried = ", ".join(repr(p) for p in profiles if p)
        raise CardGenerationError(
            f"Could not authenticate to Bedrock with profiles: {tried}. "
            f"Region: {region}. "
            f"Last error: {last_error!r}. "
            "Check ``aws configure list-profiles`` and "
            "``aws --profile <name> sts get-caller-identity``."
        )

    # ------------------------------------------------------------------
    # Public Protocol surface
    # ------------------------------------------------------------------

    def generate_flashcards(self, source: str, title: str) -> FlashcardDeck:
        user_prompt = FLASHCARD_USER_PROMPT_TEMPLATE.format(title=title, source=source)
        deck = self._generate(
            system_prompt=FLASHCARD_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            tool_name=_FLASHCARD_TOOL_NAME,
            tool_description=("Emit a flashcard deck matching the provided JSON schema."),
            schema=flashcard_deck_json_schema(),
            model_cls=FlashcardDeck,
        )
        if deck.title != title:
            deck = deck.model_copy(update={"title": title})
        return deck

    def generate_quiz(self, source: str, title: str) -> QuizDeck:
        user_prompt = QUIZ_USER_PROMPT_TEMPLATE.format(title=title, source=source)
        deck = self._generate(
            system_prompt=QUIZ_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            tool_name=_QUIZ_TOOL_NAME,
            tool_description=(
                "Emit a multiple-choice quiz deck matching the provided JSON schema."
            ),
            schema=quiz_deck_json_schema(),
            model_cls=QuizDeck,
        )
        if deck.title != title:
            deck = deck.model_copy(update={"title": title})
        return deck

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _generate[T: _DECK_MODELS](
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        tool_name: str,
        tool_description: str,
        schema: dict[str, Any],
        model_cls: type[T],
    ) -> T:
        """Call Bedrock Converse with tool-use; retry on parse/validation failure."""
        messages: list[dict[str, Any]] = [
            {"role": "user", "content": [{"text": user_prompt}]},
        ]
        last_error: str | None = None

        tool_config = {
            "tools": [
                {
                    "toolSpec": {
                        "name": tool_name,
                        "description": tool_description,
                        "inputSchema": {"json": schema},
                    }
                }
            ],
            "toolChoice": {"tool": {"name": tool_name}},
        }

        for attempt in range(self._config.max_retries + 1):
            tool_payload = self._converse_once(
                system_prompt=system_prompt,
                messages=messages,
                tool_config=tool_config,
                expected_tool_name=tool_name,
            )

            try:
                return model_cls.model_validate(tool_payload)
            except ValidationError as exc:
                last_error = f"Tool input did not match schema: {exc.errors()!r}"

            # Append the model's bad reply + a correction turn so it can
            # self-correct. Converse requires a toolResult for every
            # toolUse in the prior assistant turn.
            if attempt < self._config.max_retries:
                messages = [
                    *messages,
                    {
                        "role": "assistant",
                        "content": [
                            {
                                "toolUse": {
                                    "toolUseId": f"retry-{attempt}",
                                    "name": tool_name,
                                    "input": tool_payload,
                                }
                            }
                        ],
                    },
                    {
                        "role": "user",
                        "content": [
                            {
                                "toolResult": {
                                    "toolUseId": f"retry-{attempt}",
                                    "status": "error",
                                    "content": [
                                        {
                                            "text": (
                                                f"Invalid output. {last_error} "
                                                "Retry with a payload that exactly "
                                                "matches the schema."
                                            )
                                        }
                                    ],
                                }
                            }
                        ],
                    },
                ]

        raise CardGenerationError(
            f"Bedrock ({self._bedrock.model}) failed to produce valid output "
            f"after {self._config.max_retries + 1} attempts. Last error: {last_error}"
        )

    def _converse_once(
        self,
        *,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tool_config: dict[str, Any],
        expected_tool_name: str,
    ) -> dict[str, Any]:
        """Single Converse call with optional cross-region failover on throttle.

        Tries the primary ``(client, model)`` pair. If that raises a
        ``ThrottlingException`` and a fallback is configured, fails over
        once to the fallback region/model. All other errors propagate
        immediately.

        Fallback detection inspects the chained ``__cause__`` (the
        original ``botocore.exceptions.ClientError``) for the
        ``"ThrottlingException"`` error code. Substring-matching on the
        wrapped :class:`CardGenerationError` message would false-positive
        on any error text that happens to contain that string.
        """
        try:
            return self._converse_call(
                client=self._client,
                model=self._client_model,
                system_prompt=system_prompt,
                messages=messages,
                tool_config=tool_config,
                expected_tool_name=expected_tool_name,
            )
        except CardGenerationError as exc:
            if (
                self._is_throttle(exc)
                and self._fallback_client is not None
                and self._fallback_model is not None
            ):
                return self._converse_call(
                    client=self._fallback_client,
                    model=self._fallback_model,
                    system_prompt=system_prompt,
                    messages=messages,
                    tool_config=tool_config,
                    expected_tool_name=expected_tool_name,
                )
            raise

    @staticmethod
    def _is_throttle(exc: CardGenerationError) -> bool:
        """Return True iff ``exc`` wraps a Bedrock ``ThrottlingException``.

        Inspects ``exc.__cause__`` (set by ``raise ... from exc`` in
        :meth:`_converse_call`) rather than string-matching on the
        wrapped message. That way a non-throttle error whose text
        happens to contain the word ``ThrottlingException`` (e.g.
        a validation error complaining about throttle config) will
        NOT trigger the fallback path.
        """
        cause = exc.__cause__
        if cause is None:
            return False
        response = getattr(cause, "response", None)
        if not isinstance(response, dict):
            return False
        code = response.get("Error", {}).get("Code")
        return code == "ThrottlingException"

    def _converse_call(
        self,
        *,
        client: Any,
        model: str,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tool_config: dict[str, Any],
        expected_tool_name: str,
    ) -> dict[str, Any]:
        """Single Converse call on one specific client/model pair.

        Separated from :meth:`_converse_once` so the fallback path can
        reuse the same request logic. Returns the tool-use input dict.
        """
        # botocore exceptions imported locally to keep the top-of-module
        # import light for users without the bedrock extra.
        from botocore.exceptions import BotoCoreError, ClientError

        try:
            response = client.converse(
                modelId=model,
                system=[{"text": system_prompt}],
                messages=messages,
                inferenceConfig={
                    "temperature": self._config.temperature,
                    "maxTokens": self._bedrock.max_tokens,
                },
                toolConfig=tool_config,
            )
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            msg = exc.response.get("Error", {}).get("Message", str(exc))
            raise CardGenerationError(
                f"Bedrock Converse returned {code}: {msg} (model={model!r})."
            ) from exc
        except BotoCoreError as exc:
            raise CardGenerationError(f"Bedrock Converse transport error: {exc}") from exc

        # Extract the forced tool-use block from the response.
        output_message = response.get("output", {}).get("message", {})
        content_blocks = output_message.get("content", [])

        for block in content_blocks:
            tool_use = block.get("toolUse")
            if tool_use and tool_use.get("name") == expected_tool_name:
                tool_input = tool_use.get("input")
                if not isinstance(tool_input, dict):
                    raise CardGenerationError(
                        f"Bedrock tool-use input is not a dict: {tool_input!r}"
                    )
                return tool_input

        # Model didn't emit the tool we forced. Dump what we got for debugging.
        stop_reason = response.get("stopReason", "<unknown>")
        raise CardGenerationError(
            f"Bedrock did not call the forced tool {expected_tool_name!r}. "
            f"stopReason={stop_reason!r}. content={json.dumps(content_blocks)[:500]}"
        )


__all__ = ["BedrockGenerator"]
