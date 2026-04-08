"""Context generators for resuming, branching, or summarising a session.

These helpers are consumed by ``query_logic.continue_session`` and exposed
through it for backward compatibility.  Keeping them in their own module
makes the token-manipulation logic easy to test in isolation.
"""

from __future__ import annotations

import logging

from agent_session_tools.tokens import (
    TIKTOKEN_AVAILABLE,
    count_tokens,
    truncate_to_tokens,
)

logger = logging.getLogger(__name__)


def estimate_tokens(text: str, accurate: bool = True) -> int:
    """Count tokens in text.

    Uses tiktoken for accurate counting if available, otherwise estimates.
    Duplicated here (thin wrapper) so this module is self-contained; the
    canonical re-export lives in query_logic for backward compatibility.
    """
    return count_tokens(text, accurate=accurate)


def generate_resume_context(session: dict, messages: list, max_tokens: int) -> str:
    """Generate context for resuming where a conversation left off.

    Extracts the last user request, last assistant response, key code blocks,
    decisions and outstanding TODOs then assembles them into a compact prompt.
    """
    lines = []
    lines.append(f"# Resume Session: {session['project_path'] or 'Unknown'}")
    lines.append("")

    user_msgs = [m for m in messages if m["role"] == "user"]
    assistant_msgs = [m for m in messages if m["role"] == "assistant"]

    if user_msgs:
        lines.append("## Last Request")
        lines.append(f"**User:** {user_msgs[-1]['content'][:500]}")
        lines.append("")

    if assistant_msgs:
        lines.append("## Last Response")
        lines.append(f"**Assistant:** {assistant_msgs[-1]['content'][:800]}")
        lines.append("")

    # Extract key artefacts (code blocks, decisions, TODOs)
    code_blocks: list[str] = []
    todos: list[str] = []
    decisions: list[str] = []

    for msg in messages:
        content = msg["content"] or ""

        if "```" in content:
            parts = content.split("```")
            for i in range(1, len(parts), 2):
                if parts[i].strip():
                    code_blocks.append(parts[i].strip()[:300])

        for line in content.split("\n"):
            line_lower = line.lower().strip()
            if any(marker in line_lower for marker in ["todo", "fixme", "next steps"]):
                todos.append(line.strip()[:200])
            elif any(
                marker in line_lower
                for marker in ["decided", "chosen", "implemented", "using"]
            ):
                decisions.append(line.strip()[:200])

    if code_blocks:
        lines.append("## Key Code")
        for block in code_blocks[-3:]:
            lines.append(f"```\n{block}\n```")
        lines.append("")

    if decisions:
        lines.append("## Key Decisions")
        for decision in decisions[-3:]:
            lines.append(f"- {decision}")
        lines.append("")

    if todos:
        lines.append("## Outstanding Items")
        for todo in todos[-3:]:
            lines.append(f"- {todo}")
        lines.append("")

    lines.append("## Continue From Here")
    lines.append("*Ready to continue the conversation with full context above.*")

    content = "\n".join(lines)
    token_count = estimate_tokens(content, accurate=TIKTOKEN_AVAILABLE)

    if token_count > max_tokens:
        content = truncate_to_tokens(
            content, max_tokens, strategy="middle", accurate=TIKTOKEN_AVAILABLE
        )
        token_count = estimate_tokens(content, accurate=TIKTOKEN_AVAILABLE)

    result_lines = list(content.split("\n"))
    result_lines.append("")
    result_lines.append(f"*Context: {token_count} tokens*")

    return "\n".join(result_lines)


def generate_branch_context(session: dict, messages: list, max_tokens: int) -> str:
    """Generate context for branching in a new direction.

    Summarises what the previous conversation accomplished (using the first
    sentence of each assistant message as a key point) then signals the
    branch point.
    """
    lines = []
    lines.append(f"# Branch Session: {session['project_path'] or 'Unknown'}")
    lines.append("")
    lines.append("## Previous Work Summary")

    key_points: list[str] = []
    for msg in messages:
        if msg["role"] == "assistant" and msg["content"]:
            first_sentence = msg["content"].split(".")[0].strip()[:150]
            if first_sentence and len(first_sentence) > 20:
                key_points.append(first_sentence)

    for point in key_points[-5:]:
        lines.append(f"- {point}")

    lines.append("")
    lines.append("## Branch Point")
    lines.append("*Starting new direction based on previous work above.*")

    content = "\n".join(lines)
    token_count = estimate_tokens(content, accurate=TIKTOKEN_AVAILABLE)

    if token_count > max_tokens:
        content = truncate_to_tokens(content, max_tokens, accurate=TIKTOKEN_AVAILABLE)
        token_count = estimate_tokens(content, accurate=TIKTOKEN_AVAILABLE)

    return content + f"\n\n*Context: {token_count} tokens*"


def generate_summary_context(session: dict, messages: list, max_tokens: int) -> str:
    """Generate a high-level summary suitable for a fresh-start continuation.

    Reports the original goal, message count, code block count and session
    duration from the session metadata.
    """
    lines = []
    lines.append(f"# Session Summary: {session['project_path'] or 'Unknown'}")
    lines.append("")

    user_msgs = [m for m in messages if m["role"] == "user"]
    if user_msgs:
        lines.append(f"**Goal:** {user_msgs[0]['content'][:300]}")
        lines.append("")

    lines.append("## Outcomes")
    lines.append(f"- {len(messages)} total messages")
    lines.append(
        f"- {len([m for m in messages if '```' in (m['content'] or '')])} code blocks"
    )
    # sqlite3.Row doesn't have .get() — use dict() conversion for safe access
    session_dict = dict(session) if not isinstance(session, dict) else session
    lines.append(
        f"- Session duration: {session_dict.get('created_at', '')} to {session_dict.get('updated_at', '')}"
    )

    content = "\n".join(lines)
    token_count = estimate_tokens(content, accurate=TIKTOKEN_AVAILABLE)

    return content + f"\n\n*Context: {token_count} tokens*"
