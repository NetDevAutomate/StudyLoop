"""Sentinel for the intentionally reconcile-first `session-sync all` default."""

import inspect

from agent_session_tools.sync import sync_all


def test_sync_all_reconcile_defaults_to_true_today() -> None:
    assert inspect.signature(sync_all).parameters["reconcile"].default is True, (
        "sync_all's reconcile default changed; update the release contract and changelog"
    )
