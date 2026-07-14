"""Socratic-steering validation via an LLM judge (live_provider, opt-in).

Validates the BEHAVIOURAL contract that the StudyLoop mentor *asks guiding
questions* rather than *giving the answer* — the core AuDHD Socratic promise.
This cannot be a unit test: it needs a real agent's output. It is marked
``live_provider`` (deselected by default) and judged by a model DIFFERENT from
the mentor, via the local LiteLLM gateway.

Run:  uv run pytest packages/studyloop/tests/e2e/test_socratic_steering.py -m live_provider

Requires the LiteLLM gateway at http://127.0.0.1:4000 with a bearer token in
``$LITELLM_BEARER_TOKEN`` (or the litellm_proxy_docker/.env value). The judge
model is claude-opus-4-8; the mentor persona is built by
``build_canonical_persona`` — the SAME persona StudyLoop ships to agents.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

import pytest

pytestmark = [pytest.mark.live_provider]

GATEWAY = os.environ.get("LITELLM_GATEWAY", "http://127.0.0.1:4000")
JUDGE_MODEL = "claude-opus-4-8"


def _gateway_token() -> str | None:
    tok = os.environ.get("LITELLM_BEARER_TOKEN")
    if tok:
        return tok
    env = os.path.expanduser("~/code/personal/tools/litellm_proxy_docker/.env")
    try:
        with open(env, encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("LITELLM_BEARER_TOKEN"):
                    return line.split("=", 1)[1].strip()
    except OSError:
        return None
    return None


def _chat(model: str, system: str, user: str, token: str) -> str:
    payload = json.dumps(
        {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0,
        }
    ).encode()
    req = urllib.request.Request(
        f"{GATEWAY}/v1/chat/completions",
        data=payload,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read())
    return data["choices"][0]["message"]["content"]


def test_mentor_asks_rather_than_tells() -> None:
    """A judge model scores the mentor's reply: does it ASK (Socratic) or TELL?

    The mentor is driven by StudyLoop's real canonical persona so this tests
    the shipped steering, not an ad-hoc prompt. Judge ≠ mentor model.
    """
    token = _gateway_token()
    if not token:
        pytest.skip("No LiteLLM gateway token available")

    # Sanity: gateway reachable. An HTTP error (e.g. 401) still means it's up.
    try:
        urllib.request.urlopen(
            urllib.request.Request(
                f"{GATEWAY}/v1/models",
                headers={"Authorization": f"Bearer {token}"},
            ),
            timeout=5,
        )
    except urllib.error.HTTPError:
        pass
    except (urllib.error.URLError, OSError):
        pytest.skip(f"LiteLLM gateway not reachable at {GATEWAY}")

    from studyloop.agent_launcher import build_canonical_persona

    persona = build_canonical_persona("focus", "Abstraction and coupling in software design", 7)
    learner_msg = "I don't understand why tight coupling is bad. Just tell me the rule."

    # Mentor model is intentionally NOT the judge model.
    mentor_reply = _chat("claude-sonnet-5", persona, learner_msg, token)

    judge_system = (
        "You are grading whether a study mentor's reply is SOCRATIC. A Socratic "
        "reply guides the learner with questions and prompts toward their own "
        "insight; it does NOT simply state the answer or a rule. Respond with "
        'strict JSON: {"socratic": true|false, "reason": "..."}.'
    )
    judge_user = (
        f"Learner said: {learner_msg!r}\n\nMentor replied: {mentor_reply!r}\n\n"
        "Is the mentor's reply Socratic (asks/guides) rather than didactic (tells)?"
    )
    verdict_raw = _chat(JUDGE_MODEL, judge_system, judge_user, token)
    try:
        verdict = json.loads(verdict_raw[verdict_raw.index("{") : verdict_raw.rindex("}") + 1])
    except (ValueError, json.JSONDecodeError):
        pytest.fail(f"Judge did not return JSON: {verdict_raw[:300]}")

    assert verdict["socratic"] is True, (
        f"Mentor was not Socratic. Judge reason: {verdict.get('reason')}\n"
        f"Mentor reply was: {mentor_reply[:400]}"
    )
