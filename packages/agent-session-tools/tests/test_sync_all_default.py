"""Sentinel: `sync all` defaults to full reconcile (sync.py:1565-1576 @ 5dfe0f9b).
Flipping to incremental-by-default is Phase 2 item (n); whoever flips it must
change this assertion in the same diff as the CHANGELOG entry.
"""

import inspect

from agent_session_tools.sync import sync_all


def test_sync_all_reconcile_defaults_to_true_today():
    assert inspect.signature(sync_all).parameters["reconcile"].default is True, (
        "sync_all's reconcile default changed — if this is the intended Phase 2 "
        "incremental-default flip, update this assertion and cite the CHANGELOG entry"
    )
