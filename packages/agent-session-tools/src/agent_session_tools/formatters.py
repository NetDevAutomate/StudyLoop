"""Output formatters for session data — markdown, XML, summary, context-only, profiles."""

from __future__ import annotations

from string import Template


def render_profile(profile: dict, session: dict, messages: list) -> str:
    """Render session using profile template with placeholder substitution.

    Uses string.Template ($-substitution) instead of str.format() to prevent
    format string injection from user-controlled YAML templates. A crafted
    template with {__class__} could access Python internals via str.format().

    Supported placeholders:
    - $session_id, $project_path, $source, $updated_at
    - $messages - formatted message content
    - $message_count - number of messages
    """
    template_str = profile.get("template", "")
    if not template_str:
        # Fall back to compressed markdown if no template
        return format_markdown(session, messages, compressed=True)

    # Format messages for insertion
    msg_lines = []
    for msg in messages:
        role = msg["role"].upper()
        content = msg.get("content", "")
        if content:
            msg_lines.append(f"**{role}**: {content}")

    # Safe substitution — ignores missing placeholders, blocks attribute access
    tmpl = Template(template_str)
    return tmpl.safe_substitute(
        session_id=session.get("id", ""),
        project_path=session.get("project_path", ""),
        source=session.get("source", ""),
        updated_at=session.get("updated_at", ""),
        messages="\n\n".join(msg_lines),
        message_count=len(messages),
    )


def format_markdown(session: dict, messages: list, compressed: bool = False) -> str:
    """Format session as Markdown."""
    lines = []

    if not compressed:
        lines.append(f"# Session Context: {session['project_path'] or 'Unknown'}")
        lines.append(f"**Session ID:** {session['id'][:16]}...")
        lines.append(f"**Updated:** {session['updated_at'] or 'Unknown'}")
        lines.append(f"**Source:** {session['source']}")
        lines.append("")
    else:
        lines.append(f"# Context: {session['project_path'] or 'Session'}")
        lines.append("")

    for msg in messages:
        role = msg["role"]
        content = msg["content"] or ""

        if role == "user":
            lines.append(f"**Q:** {content}")
            lines.append("")
        elif role == "assistant":
            if compressed:
                # Compress long responses
                if len(content) > 1000 and "```" not in content:
                    # Extract key points (first few sentences)
                    sentences = content.split(". ")[:3]
                    content = ". ".join(sentences) + "..."
                lines.append(f"**A:** {content}")
            else:
                lines.append("### Assistant")
                lines.append(content)
            lines.append("")
        elif role in ("tool_use", "tool_result"):
            # Only included if --include-tools flag set
            lines.append(f"*[{role}]*")
            lines.append("")

    return "\n".join(lines)


def format_xml(session: dict, messages: list) -> str:
    """Format session as Claude-optimized XML."""
    lines = []
    lines.append('<?xml version="1.0" encoding="UTF-8"?>')
    lines.append(
        f'<session id="{session["id"][:16]}" '
        f'project="{session["project_path"] or "unknown"}">'
    )
    lines.append("  <metadata>")
    lines.append(f"    <updated>{session['updated_at']}</updated>")
    lines.append(f"    <source>{session['source']}</source>")
    lines.append("  </metadata>")
    lines.append("  <conversation>")

    for msg in messages:
        role = msg["role"]
        content = msg["content"] or ""

        # Escape XML special characters
        content = (
            content.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        )

        if role == "user":
            lines.append('    <turn role="user">')
            lines.append(f"      <content>{content}</content>")
            lines.append("    </turn>")
        elif role == "assistant":
            lines.append('    <turn role="assistant">')
            # Extract code blocks
            if "```" in content:
                parts = content.split("```")
                for i, part in enumerate(parts):
                    if i % 2 == 0:
                        if part.strip():
                            lines.append(f"      <content>{part.strip()}</content>")
                    else:
                        # Code block
                        code_lines = part.split("\n", 1)
                        lang = code_lines[0] if code_lines else ""
                        code = code_lines[1] if len(code_lines) > 1 else ""
                        lines.append(f'      <code language="{lang}">')
                        lines.append(f"{code}")
                        lines.append("      </code>")
            else:
                lines.append(f"      <content>{content}</content>")
            lines.append("    </turn>")

    lines.append("  </conversation>")
    lines.append("</session>")

    return "\n".join(lines)


def format_summary(session: dict, messages: list) -> str:
    """Format as concise summary with key points."""
    lines = []
    lines.append(f"# Session Summary: {session['project_path'] or 'Unknown'}")
    lines.append("")

    # Extract key information
    user_msgs = [m for m in messages if m["role"] == "user"]
    assistant_msgs = [m for m in messages if m["role"] == "assistant"]

    # Main topic (first user message)
    if user_msgs:
        lines.append(f"**Topic:** {user_msgs[0]['content'][:200]}...")
        lines.append("")

    # Extract code blocks from all messages
    code_blocks = []
    for msg in assistant_msgs:
        if msg["content"] and "```" in msg["content"]:
            # Extract code
            parts = msg["content"].split("```")
            for i in range(1, len(parts), 2):
                code_blocks.append(parts[i])

    if code_blocks:
        lines.append("## Key Code")
        for block in code_blocks[:3]:  # Limit to 3 blocks
            lines.append(f"```{block}```")
            lines.append("")

    # Key points (from assistant messages)
    lines.append("## Key Points")
    for i, msg in enumerate(assistant_msgs[:5], 1):  # Limit to 5 messages
        if msg["content"]:
            # Extract first sentence or two
            content = msg["content"][:300]
            if "```" in content:
                content = content.split("```")[0]  # Text before code
            lines.append(f"{i}. {content.strip()}")
    lines.append("")

    return "\n".join(lines)


def format_context_only(session: dict, messages: list) -> str:
    """Format as context-only (code + technical info)."""
    lines = []
    lines.append(f"# Technical Context: {session['project_path'] or 'Project'}")
    lines.append("")

    # Extract all code blocks
    lines.append("## Code Implementations")
    lines.append("")

    for msg in messages:
        if msg["content"] and "```" in msg["content"]:
            # Extract code blocks
            parts = msg["content"].split("```")
            for i in range(1, len(parts), 2):
                lines.append(f"```{parts[i]}```")
                lines.append("")

    return "\n".join(lines)
