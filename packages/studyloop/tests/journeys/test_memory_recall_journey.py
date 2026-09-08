"""Learner journey: recall captured evidence while a study session is active."""

from __future__ import annotations


def test_active_study_session_can_recall_prior_session_evidence(tmp_path, monkeypatch) -> None:
    from agent_session_tools.export_sessions import init_db
    from agent_session_tools.recall import recall

    db_path = tmp_path / "sessions.db"
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        f"""database:
  path: {db_path}
memory:
  default_scope: unclassified
"""
    )
    monkeypatch.setenv("STUDYLOOP_CONFIG", str(config_path))

    conn = init_db(str(db_path))
    conn.execute(
        "INSERT INTO sessions(id,source,project_path,updated_at) VALUES(?,?,?,?)",
        ("captured-session", "kiro_cli", "/study/sql", "2026-09-08T10:00:00Z"),
    )
    conn.execute(
        "INSERT INTO messages(id,session_id,role,content,timestamp) VALUES(?,?,?,?,?)",
        (
            "captured-message",
            "captured-session",
            "user",
            "window functions calculate values across related rows",
            "2026-09-08T10:01:00Z",
        ),
    )
    conn.execute(
        "INSERT INTO study_sessions(id,session_id,topic,energy_level,started_at) VALUES(?,?,?,?,?)",
        (
            "active-study",
            "captured-session",
            "SQL window functions",
            "medium",
            "2026-09-08T11:00:00Z",
        ),
    )
    conn.commit()
    conn.close()

    report = recall(db_path, "window functions")

    assert [hit.session_id for hit in report.sessions] == ["captured-session"]
    assert "window functions" in report.sessions[0].preview
