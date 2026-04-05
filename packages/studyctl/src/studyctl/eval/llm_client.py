"""Thin HTTP client for Ollama, OpenAI-compatible, and AWS Bedrock LLM endpoints."""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

logger = logging.getLogger(__name__)


class LLMClientError(Exception):
    """Raised on HTTP errors, timeouts, or malformed responses."""


@dataclass
class LLMClient:
    """Client for chat completion APIs (Ollama, OpenAI-compat, Bedrock).

    Args:
        base_url: API base URL (e.g. http://localhost:11434 for Ollama)
        model: Model name (e.g. gemma3:4b, claude-sonnet-4-6-20250514)
        api_key: Optional API key for OpenAI-compat providers
        provider: "ollama", "openai-compat", or "bedrock"
        timeout: Request timeout in seconds
        region: AWS region for Bedrock (default: us-east-1)
    """

    base_url: str
    model: str
    api_key: str = ""
    provider: str = "ollama"  # "ollama" | "openai-compat" | "bedrock"
    timeout: int = 120
    region: str = "us-west-2"

    def chat(self, messages: list[dict], temperature: float = 0.1) -> str:
        """Send a chat completion request. Returns the assistant message content.

        Retries once on 429/503 with 5s backoff.
        Raises LLMClientError on failure.
        """
        if self.provider == "ollama":
            return self._chat_ollama(messages, temperature)
        if self.provider == "bedrock":
            return self._chat_bedrock(messages, temperature)
        return self._chat_openai(messages, temperature)

    def _chat_ollama(self, messages: list[dict], temperature: float) -> str:
        """POST /api/chat for Ollama."""
        url = f"{self.base_url.rstrip('/')}/api/chat"
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": temperature},
        }
        data = self._post(url, payload)
        try:
            return data["message"]["content"]
        except (KeyError, TypeError) as e:
            raise LLMClientError(f"Unexpected Ollama response shape: {data}") from e

    def _chat_openai(self, messages: list[dict], temperature: float) -> str:
        """POST /v1/chat/completions for OpenAI-compatible APIs."""
        url = f"{self.base_url.rstrip('/')}/v1/chat/completions"
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        data = self._post(url, payload)
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, TypeError, IndexError) as e:
            raise LLMClientError(f"Unexpected OpenAI response shape: {data}") from e

    def _chat_bedrock(self, messages: list[dict], temperature: float) -> str:
        """AWS Bedrock Converse API via boto3.

        Uses default AWS credential chain (env vars, ~/.aws/credentials, IAM role).
        Requires boto3 to be installed.
        """
        try:
            import boto3
        except ImportError as e:
            raise LLMClientError(
                "boto3 is required for the bedrock provider. Install with: pip install boto3"
            ) from e

        try:
            client = boto3.client(
                "bedrock-runtime",
                region_name=self.region,
            )

            # Convert messages to Bedrock Converse format
            bedrock_messages = []
            system_prompts = []
            for msg in messages:
                role = msg["role"]
                content = msg["content"]
                if role == "system":
                    system_prompts.append({"text": content})
                else:
                    bedrock_messages.append(
                        {
                            "role": role,
                            "content": [{"text": content}],
                        }
                    )

            kwargs: dict = {
                "modelId": self.model,
                "messages": bedrock_messages,
                "inferenceConfig": {
                    "temperature": temperature,
                    "maxTokens": 4096,
                },
            }
            if system_prompts:
                kwargs["system"] = system_prompts

            response = client.converse(**kwargs)

            # Extract text from response
            output = response.get("output", {})
            message = output.get("message", {})
            content_blocks = message.get("content", [])
            texts = [b["text"] for b in content_blocks if "text" in b]
            if not texts:
                raise LLMClientError(f"No text in Bedrock response: {response}")
            return texts[0]

        except LLMClientError:
            raise
        except Exception as e:
            raise LLMClientError(f"Bedrock API error: {e}") from e

    def _post(self, url: str, payload: dict) -> dict:
        """HTTP POST with retry on 429/503."""
        body = json.dumps(payload).encode()
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        for attempt in range(2):  # max 1 retry
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return json.loads(resp.read())
            except urllib.error.HTTPError as e:
                if e.code in (429, 503) and attempt == 0:
                    logger.warning("LLM API returned %d, retrying in 5s...", e.code)
                    time.sleep(5)
                    continue
                raise LLMClientError(f"HTTP {e.code}: {e.reason}") from e
            except urllib.error.URLError as e:
                raise LLMClientError(f"Connection error: {e.reason}") from e
            except TimeoutError as e:
                raise LLMClientError(f"Request timed out after {self.timeout}s") from e

        raise LLMClientError("Max retries exceeded")  # shouldn't reach here
