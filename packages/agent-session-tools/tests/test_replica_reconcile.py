"""The merge truth table and native immutable identity boundary."""

import pytest
from agent_session_tools.replication.reconcile import decide, Reconciler


@pytest.mark.parametrize(
    "base,local,incoming,expected",
    [
        (None, "same", "same", "identical"),
        (None, "a", "b", "conflict"),
        ("old", "old", "new", "advance"),
        ("old", "new", "old", "keep_local"),
        ("old", "left", "right", "conflict"),
        ("old", "new", "new", "identical"),
    ],
)
def test_exact_three_way_decision(base, local, incoming, expected):
    assert decide(base, local, incoming) == expected


@pytest.mark.parametrize(
    "table,local,incoming",
    [
        (
            "messages",
            {"id": "m", "session_id": "s", "role": "user", "content": "old"},
            {"id": "m", "session_id": "s", "role": "user", "content": "new"},
        ),
        (
            "sessions",
            {"id": "s", "source": "codex", "project_path": "a"},
            {"id": "s", "source": "codex", "project_path": "b"},
        ),
        ("context_evidence", {"id": "e", "body": "old"}, {"id": "e", "body": "new"}),
    ],
)
def test_hash_basis_never_authorizes_immutable_text_or_identity(table, local, incoming):
    reconciler = Reconciler(None, "peer", "local", "personal", None)
    assert reconciler.action(table, local, incoming) == "conflict"
