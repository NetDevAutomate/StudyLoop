"""Tests for agent_session_tools.formatters — all pure output formatting functions."""

from __future__ import annotations

import pytest

from agent_session_tools.formatters import (
    format_context_only,
    format_markdown,
    format_summary,
    format_xml,
    render_profile,
)

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def session() -> dict:
    return {
        "id": "abcdef1234567890abcdef1234567890",  # pragma: allowlist secret,
        "project_path": "/home/user/project",
        "updated_at": "2024-06-15T14:30:00",
        "source": "claude_code",
    }


@pytest.fixture
def messages() -> list[dict]:
    return [
        {"role": "user", "content": "How do I write tests?"},
        {
            "role": "assistant",
            "content": "Use pytest. Write small, focused test functions.",
        },
    ]


@pytest.fixture
def messages_with_code() -> list[dict]:
    return [
        {"role": "user", "content": "Show me a fixture"},
        {
            "role": "assistant",
            "content": "Here is an example:\n```python\n@pytest.fixture\ndef db():\n    return connect()\n```\nThat covers it.",
        },
    ]


@pytest.fixture
def messages_with_tools() -> list[dict]:
    return [
        {"role": "user", "content": "Read the file"},
        {"role": "tool_use", "content": "read_file(/tmp/x)"},
        {"role": "tool_result", "content": "file contents here"},
        {"role": "assistant", "content": "The file contains data."},
    ]


# ---------------------------------------------------------------------------
# format_markdown
# ---------------------------------------------------------------------------


class TestFormatMarkdown:
    def test_full_header_includes_session_metadata(self, session, messages):
        result = format_markdown(session, messages, compressed=False)
        assert "# Session Context: /home/user/project" in result
        assert "**Session ID:** abcdef1234567890..." in result
        assert "**Updated:** 2024-06-15T14:30:00" in result
        assert "**Source:** claude_code" in result

    def test_compressed_header_is_shorter(self, session, messages):
        result = format_markdown(session, messages, compressed=True)
        assert "# Context: /home/user/project" in result
        assert "**Session ID:**" not in result
        assert "**Updated:**" not in result

    def test_user_message_formatted_as_q(self, session, messages):
        result = format_markdown(session, messages)
        assert "**Q:** How do I write tests?" in result

    def test_assistant_message_full_mode(self, session, messages):
        result = format_markdown(session, messages, compressed=False)
        assert "### Assistant" in result
        assert "Use pytest." in result

    def test_assistant_message_compressed_mode(self, session, messages):
        result = format_markdown(session, messages, compressed=True)
        assert "**A:** Use pytest." in result
        assert "### Assistant" not in result

    def test_compressed_truncates_long_assistant_without_code(self, session):
        long_text = "First sentence. Second sentence. Third sentence. " + ("x " * 600)
        msgs = [
            {"role": "user", "content": "question"},
            {"role": "assistant", "content": long_text},
        ]
        result = format_markdown(session, msgs, compressed=True)
        assert result.count("**A:**") == 1
        # The truncated version ends with "..."
        a_line = [line for line in result.splitlines() if line.startswith("**A:**")][0]
        assert a_line.endswith("...")

    def test_compressed_does_not_truncate_code_blocks(self, session):
        code_content = "Explanation. " * 100 + "```python\nprint('hi')\n```"
        msgs = [
            {"role": "user", "content": "q"},
            {"role": "assistant", "content": code_content},
        ]
        result = format_markdown(session, msgs, compressed=True)
        a_line = [line for line in result.splitlines() if line.startswith("**A:**")][0]
        # Code block content is preserved because the "```" guard prevents truncation
        assert "```" in a_line

    def test_tool_messages_included(self, session, messages_with_tools):
        result = format_markdown(session, messages_with_tools)
        assert "*[tool_use]*" in result
        assert "*[tool_result]*" in result

    def test_empty_messages(self, session):
        result = format_markdown(session, [])
        # Should still produce header
        assert "# Session Context:" in result

    def test_none_project_path_shows_unknown(self, messages):
        s = {"id": "x" * 32, "project_path": None, "updated_at": None, "source": "test"}
        result = format_markdown(s, messages, compressed=False)
        assert "Unknown" in result

    def test_none_content_does_not_raise(self, session):
        msgs = [{"role": "user", "content": None}]
        # content is accessed as msg["content"] or "" — None is falsy, becomes ""
        result = format_markdown(session, msgs)
        assert "**Q:** " in result


# ---------------------------------------------------------------------------
# format_xml
# ---------------------------------------------------------------------------


class TestFormatXml:
    def test_xml_declaration(self, session, messages):
        result = format_xml(session, messages)
        assert result.startswith('<?xml version="1.0" encoding="UTF-8"?>')

    def test_session_element_attributes(self, session, messages):
        result = format_xml(session, messages)
        assert 'id="abcdef1234567890"' in result  # pragma: allowlist secret
        assert 'project="/home/user/project"' in result

    def test_metadata_elements(self, session, messages):
        result = format_xml(session, messages)
        assert "<updated>2024-06-15T14:30:00</updated>" in result
        assert "<source>claude_code</source>" in result

    def test_user_turn(self, session, messages):
        result = format_xml(session, messages)
        assert '<turn role="user">' in result
        assert "<content>How do I write tests?</content>" in result

    def test_assistant_turn_plain_text(self, session, messages):
        result = format_xml(session, messages)
        assert '<turn role="assistant">' in result
        assert "Use pytest." in result

    def test_xml_escapes_special_characters(self, session):
        msgs = [{"role": "user", "content": "a < b & c > d"}]
        result = format_xml(session, msgs)
        assert "a &lt; b &amp; c &gt; d" in result
        # The raw characters must not appear unescaped in content
        content_section = result.split("<content>")[1].split("</content>")[0]
        assert "<" not in content_section.replace("&lt;", "").replace("&gt;", "")

    def test_code_block_extraction(self, session, messages_with_code):
        result = format_xml(session, messages_with_code)
        assert '<code language="python">' in result
        assert "@pytest.fixture" in result
        assert "</code>" in result

    def test_closing_tags(self, session, messages):
        result = format_xml(session, messages)
        assert result.strip().endswith("</session>")
        assert "</conversation>" in result

    def test_empty_messages(self, session):
        result = format_xml(session, [])
        assert "<conversation>" in result
        assert "</conversation>" in result

    def test_none_project_path(self, messages):
        s = {"id": "a" * 32, "project_path": None, "updated_at": "t", "source": "s"}
        result = format_xml(s, messages)
        assert 'project="unknown"' in result


# ---------------------------------------------------------------------------
# format_summary
# ---------------------------------------------------------------------------


class TestFormatSummary:
    def test_header(self, session, messages):
        result = format_summary(session, messages)
        assert "# Session Summary: /home/user/project" in result

    def test_topic_from_first_user_message(self, session, messages):
        result = format_summary(session, messages)
        assert "**Topic:** How do I write tests?" in result

    def test_key_points_section(self, session, messages):
        result = format_summary(session, messages)
        assert "## Key Points" in result
        assert "1. Use pytest." in result

    def test_code_blocks_extracted(self, session, messages_with_code):
        result = format_summary(session, messages_with_code)
        assert "## Key Code" in result
        assert "@pytest.fixture" in result

    def test_limits_code_blocks_to_three(self, session):
        # Build an assistant message with 5 code blocks
        code_parts = [f"```python\nblock_{i}\n```" for i in range(5)]
        msgs = [
            {"role": "user", "content": "many blocks"},
            {"role": "assistant", "content": "\n".join(code_parts)},
        ]
        result = format_summary(session, msgs)
        # Only first 3 blocks kept
        assert "block_0" in result
        assert "block_2" in result
        assert "block_3" not in result

    def test_limits_key_points_to_five(self, session):
        msgs = [{"role": "user", "content": "topic"}]
        for i in range(7):
            msgs.append({"role": "assistant", "content": f"Point number {i}."})
        result = format_summary(session, msgs)
        assert "Point number 4" in result
        assert "Point number 5" not in result

    def test_no_user_messages(self, session):
        msgs = [{"role": "assistant", "content": "unsolicited advice"}]
        result = format_summary(session, msgs)
        assert "**Topic:**" not in result

    def test_empty_messages(self, session):
        result = format_summary(session, [])
        assert "## Key Points" in result

    def test_key_points_strip_code_prefix(self, session):
        """Text before a code block is used as the key point."""
        msgs = [
            {"role": "user", "content": "q"},
            {"role": "assistant", "content": "Explanation here.\n```python\ncode\n```"},
        ]
        result = format_summary(session, msgs)
        point_line = [line for line in result.splitlines() if line.startswith("1.")][0]
        assert "Explanation here." in point_line
        # Code fence should have been stripped from the key point
        assert "```" not in point_line


# ---------------------------------------------------------------------------
# format_context_only
# ---------------------------------------------------------------------------


class TestFormatContextOnly:
    def test_header(self, session, messages):
        result = format_context_only(session, messages)
        assert "# Technical Context: /home/user/project" in result

    def test_code_implementations_section(self, session, messages_with_code):
        result = format_context_only(session, messages_with_code)
        assert "## Code Implementations" in result
        assert "@pytest.fixture" in result

    def test_no_code_blocks_still_has_section_header(self, session, messages):
        result = format_context_only(session, messages)
        assert "## Code Implementations" in result

    def test_extracts_code_from_all_roles(self, session):
        msgs = [
            {"role": "user", "content": "```bash\nls -la\n```"},
            {"role": "assistant", "content": "```python\nprint('hi')\n```"},
        ]
        result = format_context_only(session, msgs)
        assert "ls -la" in result
        assert "print('hi')" in result

    def test_none_content_skipped(self, session):
        msgs = [{"role": "assistant", "content": None}]
        # content is None, so "```" in None would TypeError — but the guard
        # msg["content"] and "```" in msg["content"] short-circuits
        result = format_context_only(session, msgs)
        assert "## Code Implementations" in result

    def test_none_project_path(self, messages):
        s = {"id": "z", "project_path": None, "updated_at": "", "source": ""}
        result = format_context_only(s, messages)
        assert "# Technical Context: Project" in result

    def test_empty_messages(self, session):
        result = format_context_only(session, [])
        assert "## Code Implementations" in result


# ---------------------------------------------------------------------------
# render_profile
# ---------------------------------------------------------------------------


class TestRenderProfile:
    def test_template_substitution(self, session, messages):
        profile = {
            "template": "Session: {session_id}\nPath: {project_path}\nCount: {message_count}",
        }
        result = render_profile(profile, session, messages)
        assert f"Session: {session['id']}" in result
        assert "Path: /home/user/project" in result
        assert "Count: 2" in result

    def test_messages_placeholder(self, session, messages):
        profile = {"template": "Messages:\n{messages}"}
        result = render_profile(profile, session, messages)
        assert "**USER**: How do I write tests?" in result
        assert "**ASSISTANT**: Use pytest." in result

    def test_all_placeholders(self, session, messages):
        profile = {
            "template": (
                "{session_id}|{project_path}|{source}|{updated_at}|"
                "{message_count}|{messages}"
            ),
        }
        result = render_profile(profile, session, messages)
        assert session["id"] in result
        assert session["project_path"] in result
        assert session["source"] in result
        assert session["updated_at"] in result
        assert "2" in result  # message_count

    def test_empty_template_falls_back_to_compressed_markdown(self, session, messages):
        profile = {"template": ""}
        result = render_profile(profile, session, messages)
        # Compressed markdown uses "# Context:" header
        assert "# Context:" in result

    def test_missing_template_key_falls_back(self, session, messages):
        profile = {}
        result = render_profile(profile, session, messages)
        assert "# Context:" in result

    def test_messages_with_empty_content_skipped(self, session):
        msgs = [
            {"role": "user", "content": "question"},
            {"role": "assistant", "content": ""},
            {"role": "assistant", "content": "answer"},
        ]
        profile = {"template": "{messages}"}
        result = render_profile(profile, session, msgs)
        # Empty content message should be excluded
        assert "**USER**: question" in result
        assert "**ASSISTANT**: answer" in result
        # Should only have 2 message lines, not 3
        assert result.count("**ASSISTANT**") == 1

    def test_missing_session_fields_default_to_empty(self, messages):
        profile = {"template": ">{session_id}<>{project_path}<>{source}<>{updated_at}<"}
        empty_session: dict = {}
        result = render_profile(profile, empty_session, messages)
        assert "><>" in result  # empty values produce adjacent delimiters
