"""BL-3 supervised export and sweep verification receipts."""

from __future__ import annotations

import sqlite3
from types import SimpleNamespace

from agent_session_tools.exporters.base import ExportStats


def test_run_export_records_verified_per_source_receipt(tmp_path, monkeypatch) -> None:
    from agent_session_tools import export_sessions

    class Exporter:
        def export_all(self, conn, incremental):
            conn.execute(
                "INSERT INTO sessions(id,source) VALUES('verified-session','claude_code')"
            )
            conn.execute(
                "INSERT INTO messages(id,session_id,role,content) "
                "VALUES('verified-message','verified-session','user','captured')"
            )
            return ExportStats(added=1)

    monkeypatch.setattr(export_sessions, "get_exporter", lambda _source: Exporter())
    monkeypatch.setattr(
        export_sessions,
        "refresh_ontology_after_export",
        lambda *_args, **_kwargs: SimpleNamespace(
            mode="incremental", fallback_reason=None, candidate_sessions=1
        ),
    )
    monkeypatch.setattr("agent_session_tools.tiering.maybe_spawn_sync", lambda: False)

    db_path = tmp_path / "sessions.db"
    summary = export_sessions._run_export(db_path, {"claude"}, incremental=True)

    with sqlite3.connect(db_path) as conn:
        assert conn.execute(
            "SELECT source,sessions_seen,messages_seen,errors,verified "
            "FROM session_export_runs"
        ).fetchall() == [("claude", 1, 1, 0, 1)]
    assert summary["export_verification"] == {"claude": True}
