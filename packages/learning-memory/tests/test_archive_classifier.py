"""The archive classifier, as an exhaustive table over every shape in the corpus.

Every row here is a shape that was counted in the live archive (read-only) before it
was written down; the counts in the ids are what makes this a table rather than a
guess. A change to any decision is a new ``classifier_version``.
"""

from __future__ import annotations

import pytest

from learning_memory.adapters.archive import (
    ARCHIVE_ADAPTER_VERSION,
    ARCHIVE_CLASSIFIER_VERSION,
    TOOL_XML_TAGS,
    USER_PROSE_XML_TAGS,
    classify,
)

# (id, role, content, source) -> (kind, actor, tool_name, text)
TABLE: list[tuple[str, tuple[str, str | None, str], tuple[str, str, str | None, str]]] = [
    # ---------------------------------------------------------------- user rows
    (
        "user prose (16,757) -> learner voice",
        ("user", "why does the gate fail?", "claude_code"),
        ("user", "learner", None, "why does the gate fail?"),
    ),
    (
        "user prose with leading whitespace stays prose",
        ("user", "\n  what broke?", "kiro_cli"),
        ("user", "learner", None, "\n  what broke?"),
    ),
    (
        "user short prose stays prose (noise filtering is Stage D's)",
        ("user", "4", "claude_code"),
        ("user", "learner", None, "4"),
    ),
    (
        "user [LiteLLM Request: model] (1,319) -> system, tool_name = model",
        ("user", "[LiteLLM Request: anthropic.claude-3-5-haiku-20241022-v1:0]", "litellm-proxy"),
        (
            "system",
            "litellm",
            "anthropic.claude-3-5-haiku-20241022-v1:0",
            "[LiteLLM Request: anthropic.claude-3-5-haiku-20241022-v1:0]",
        ),
    ),
    (
        "user [LiteLLM Request: test-model]",
        ("user", "[LiteLLM Request: test-model]", "litellm-proxy"),
        ("system", "litellm", "test-model", "[LiteLLM Request: test-model]"),
    ),
    (
        "user [LiteLLM Request: ] with no model -> tool_name None",
        ("user", "[LiteLLM Request: ]", "litellm-proxy"),
        ("system", "litellm", None, "[LiteLLM Request: ]"),
    ),
    (
        "user <system-reminder> (237) -> system",
        ("user", "<system-reminder>be careful</system-reminder>", "claude_code"),
        ("system", "claude_code", None, "<system-reminder>be careful</system-reminder>"),
    ),
    (
        "user <command-name> (68) -> system",
        ("user", "<command-name>/login</command-name>", "claude_code"),
        ("system", "claude_code", None, "<command-name>/login</command-name>"),
    ),
    (
        "user <local-command-stdout> (65) -> system",
        ("user", "<local-command-stdout>Login successful</local-command-stdout>", "claude_code"),
        (
            "system",
            "claude_code",
            None,
            "<local-command-stdout>Login successful</local-command-stdout>",
        ),
    ),
    (
        "user <observed_from_primary_session> (3,376) -> system",
        (
            "user",
            "<observed_from_primary_session>\n  ...\n</observed_from_primary_session>",
            "codex",
        ),
        (
            "system",
            "codex",
            None,
            "<observed_from_primary_session>\n  ...\n</observed_from_primary_session>",
        ),
    ),
    (
        "user <file_tree> (415) -> system",
        ("user", "<file_tree>\nsrc/\n</file_tree>", "repoprompt"),
        ("system", "repoprompt", None, "<file_tree>\nsrc/\n</file_tree>"),
    ),
    (
        'user <codex_internal_context source="goal"> (263) -> system',
        ("user", '<codex_internal_context source="goal">x</codex_internal_context>', "codex"),
        (
            "system",
            "codex",
            None,
            '<codex_internal_context source="goal">x</codex_internal_context>',
        ),
    ),
    (
        "user <task> (247) -> LEARNER prose: kilocode wraps the learner's own request",
        (
            "user",
            "<task>\nplease review the repo\n</task>\n<environment_details>x</environment_details>",
            "kilocode_cli",
        ),
        (
            "user",
            "learner",
            None,
            "<task>\nplease review the repo\n</task>\n<environment_details>x</environment_details>",
        ),
    ),
    (
        "user <user_query> (148) -> LEARNER prose",
        ("user", "<user_query>\nwhat model is being used?\n</user_query>", "grok"),
        ("user", "learner", None, "<user_query>\nwhat model is being used?\n</user_query>"),
    ),
    (
        "user <task-notification> (112) -> system: a machine notification, not the learner",
        ("user", "<task-notification>\n<task-id>a1</task-id>\n</task-notification>", "claude_code"),
        (
            "system",
            "claude_code",
            None,
            "<task-notification>\n<task-id>a1</task-id>\n</task-notification>",
        ),
    ),
    (
        "user <teammate-message> (149) -> system: an orchestrator brief, not the learner",
        (
            "user",
            '<teammate-message teammate_id="team-lead" summary="x">\nYour job:\n',
            "claude_code",
        ),
        (
            "system",
            "claude_code",
            None,
            '<teammate-message teammate_id="team-lead" summary="x">\nYour job:\n',
        ),
    ),
    (
        "user <turn_aborted> (74) -> system",
        ("user", "<turn_aborted>", "codex"),
        ("system", "codex", None, "<turn_aborted>"),
    ),
    (
        'user json {"content": [...]} (14) -> system',
        ("user", '{"content":[{"type":"text","text":"x"}]}', "kiro_cli"),
        ("system", "kiro_cli", None, '{"content":[{"type":"text","text":"x"}]}'),
    ),
    (
        "user python-repr {'text': ...} (12) -> system (unwrapping is Stage D's)",
        ("user", "{'text': 'please fix the gemini config'}", "gemini_cli"),
        ("system", "gemini_cli", None, "{'text': 'please fix the gemini config'}"),
    ),
    (
        "user prose containing but not starting with a tag stays prose",
        ("user", "look at <system-reminder> please", "claude_code"),
        ("user", "learner", None, "look at <system-reminder> please"),
    ),
    (
        "user prose containing but not starting with a brace stays prose",
        ("user", "the dict {'a': 1} failed", "claude_code"),
        ("user", "learner", None, "the dict {'a': 1} failed"),
    ),
    (
        "user empty content -> prose with empty text (schema allows '')",
        ("user", "", "claude_code"),
        ("user", "learner", None, ""),
    ),
    # ----------------------------------------------------------- assistant rows
    (
        "assistant bare [tool:Bash] (45,761 of 75,493) -> tool_call, empty text kept",
        ("assistant", "[tool:Bash]", "claude_code"),
        ("tool_call", "claude_code", "Bash", ""),
    ),
    (
        "assistant bare [tool:Read] -> tool_call",
        ("assistant", "[tool:Read]", "claude_code"),
        ("tool_call", "claude_code", "Read", ""),
    ),
    (
        "assistant [tool:mcp__long__name] -> tool_call with the full mcp name",
        ("assistant", "[tool:mcp__plugin_context-mode__ctx_fetch_and_index]", "claude_code"),
        ("tool_call", "claude_code", "mcp__plugin_context-mode__ctx_fetch_and_index", ""),
    ),
    (
        "assistant [tool:Bash] with a payload (4) -> tool_call, payload is the text",
        ("assistant", "[tool:Bash]\n[tool:Bash]", "claude_code"),
        ("tool_call", "claude_code", "Bash", "\n[tool:Bash]"),
    ),
    (
        "assistant marker not at the start (30) -> prose, not a tool call",
        ("assistant", "I ran [tool:Bash] for you", "claude_code"),
        ("assistant_prose", "claude_code", None, "I ran [tool:Bash] for you"),
    ),
    (
        "assistant [LiteLLM Response: N tokens] (180) -> system",
        ("assistant", "[LiteLLM Response: 30 tokens]", "litellm-proxy"),
        ("system", "litellm", None, "[LiteLLM Response: 30 tokens]"),
    ),
    (
        "assistant json-leading (109) -> tool_result",
        ("assistant", '{"risk_level":"low","outcome":"allow"}', "bedrock_proxy"),
        ("tool_result", "bedrock_proxy", None, '{"risk_level":"low","outcome":"allow"}'),
    ),
    (
        "assistant prose (42,242) -> assistant_prose",
        ("assistant", "Because the dedupe collapsed the rows.", "claude_code"),
        ("assistant_prose", "claude_code", None, "Because the dedupe collapsed the rows."),
    ),
    (
        "assistant short prose (7,035) stays prose",
        ("assistant", "Not logged in \u00b7 Please run /login", "claude_code"),
        ("assistant_prose", "claude_code", None, "Not logged in \u00b7 Please run /login"),
    ),
    (
        "assistant <execute_command> (32) -> tool_call: XML tool text is never prose",
        (
            "assistant",
            "<execute_command>\n<command>ls</command>\n</execute_command>",
            "kilocode_cli",
        ),
        (
            "tool_call",
            "kilocode_cli",
            "execute_command",
            "<execute_command>\n<command>ls</command>\n</execute_command>",
        ),
    ),
    (
        "assistant <read_file> (51) -> tool_call",
        ("assistant", "<read_file>\n<args><file>x</file></args>\n</read_file>", "kilocode_cli"),
        (
            "tool_call",
            "kilocode_cli",
            "read_file",
            "<read_file>\n<args><file>x</file></args>\n</read_file>",
        ),
    ),
    (
        "assistant <update_todo_list> (27) -> tool_call",
        ("assistant", "<update_todo_list>\n- [x] done\n</update_todo_list>", "kilocode_cli"),
        (
            "tool_call",
            "kilocode_cli",
            "update_todo_list",
            "<update_todo_list>\n- [x] done\n</update_todo_list>",
        ),
    ),
    (
        "assistant <think> (17) -> thinking",
        ("assistant", "<think>\nThe user is asking about X\n</think>", "kilocode_cli"),
        ("thinking", "kilocode_cli", None, "<think>\nThe user is asking about X\n</think>"),
    ),
    (
        "assistant <chatName=...> (382) -> prose: a title attribute, then real prose",
        ("assistant", '<chatName=\\"K8s Strategy\\"/>\n\n**1. Analysis**', "repoprompt"),
        (
            "assistant_prose",
            "repoprompt",
            None,
            '<chatName=\\"K8s Strategy\\"/>\n\n**1. Analysis**',
        ),
    ),
    (
        "assistant <observation> (64) -> prose: a record, not a tool call",
        ("assistant", "<observation>\n<type>decision</type>\n</observation>", "repoprompt"),
        (
            "assistant_prose",
            "repoprompt",
            None,
            "<observation>\n<type>decision</type>\n</observation>",
        ),
    ),
    (
        "assistant <analysis> (37) -> prose",
        ("assistant", "<analysis>\nThe problem requires...\n</analysis>", "repoprompt"),
        (
            "assistant_prose",
            "repoprompt",
            None,
            "<analysis>\nThe problem requires...\n</analysis>",
        ),
    ),
    (
        "assistant empty content -> prose with empty text",
        ("assistant", "", "claude_code"),
        ("assistant_prose", "claude_code", None, ""),
    ),
    (
        "assistant NULL content -> prose with empty text",
        ("assistant", None, "claude_code"),
        ("assistant_prose", "claude_code", None, ""),
    ),
    # --------------------------------------------------------------- other roles
    (
        "toolResult (127, pi) -> tool_result",
        ("toolResult", "/Users/x/.bun/bin/omp\n---\ntotal 0", "pi"),
        ("tool_result", "tool", None, "/Users/x/.bun/bin/omp\n---\ntotal 0"),
    ),
    (
        "error (61) -> error, actor = harness",
        ("error", "[API Error: Content generator not initialized]", "gemini_cli"),
        ("error", "gemini_cli", None, "[API Error: Content generator not initialized]"),
    ),
    (
        "info (89) -> system",
        ("info", "Update successful!", "gemini_cli"),
        ("system", "gemini_cli", None, "Update successful!"),
    ),
    (
        "system (23) -> system",
        ("system", "You are Claude Code...", "claude_code"),
        ("system", "claude_code", None, "You are Claude Code..."),
    ),
    (
        "an unknown future role -> system, never dropped",
        ("summary", "some new exporter role", "omp"),
        ("system", "omp", None, "some new exporter role"),
    ),
]


@pytest.mark.parametrize(
    ("role", "content", "source", "expected"),
    [(row[1][0], row[1][1], row[1][2], row[2]) for row in TABLE],
    ids=[row[0] for row in TABLE],
)
def test_classifier_table(
    role: str, content: str | None, source: str, expected: tuple[str, str, str | None, str]
) -> None:
    assert tuple(classify(role, content, source)) == expected


def test_classifier_is_pure() -> None:
    """Same input, same output, no state: a versioned classifier must be replayable."""
    for _ in range(3):
        assert tuple(classify("assistant", "[tool:Bash]", "claude_code")) == (
            "tool_call",
            "claude_code",
            "Bash",
            "",
        )


def test_only_tool_call_may_carry_empty_text() -> None:
    """Empty text is meaningful for a bare marker; elsewhere it means "nothing said"."""
    kind, _, tool_name, text = classify("assistant", "[tool:Bash]", "claude_code")
    assert (kind, tool_name, text) == ("tool_call", "Bash", "")


def test_every_table_kind_is_a_declared_event_kind() -> None:
    from learning_memory import EVENT_KINDS

    assert {row[2][0] for row in TABLE} <= set(EVENT_KINDS)


def test_tool_xml_tags_are_all_lowercase_bare_names() -> None:
    """The allowlist is matched against a parsed tag name, so no brackets or slashes."""
    assert TOOL_XML_TAGS
    assert all(tag == tag.strip().lower() and "<" not in tag for tag in TOOL_XML_TAGS)


def test_user_prose_xml_tags_are_bare_lowercase_names() -> None:
    assert {"task", "user_query"} == USER_PROSE_XML_TAGS
    assert not (USER_PROSE_XML_TAGS & TOOL_XML_TAGS)


def test_versions_are_named() -> None:
    assert ARCHIVE_ADAPTER_VERSION == "archive-v1"
    assert ARCHIVE_CLASSIFIER_VERSION == "archive-classifier-v1"
