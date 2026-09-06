import json
from agent_session_tools.exporters.grok import GrokExporter


def fixture_history(tmp_path):
    folder = tmp_path / "sessions" / "project" / "native-id"
    folder.mkdir(parents=True)
    (folder / "summary.json").write_text(
        json.dumps(
            {
                "info": {"id": "native-id", "cwd": "/work/repo"},
                "created_at": "2026-09-01T12:00:00Z",
                "updated_at": "2026-09-01T13:00:00Z",
            }
        )
    )
    history = folder / "chat_history.jsonl"
    records = [
        {"type": "system", "content": "instructions"},
        {"type": "user", "content": "synthetic", "synthetic_reason": "context"},
        {"type": "user", "content": [{"type": "text", "text": "question"}]},
        {"type": "assistant", "content": "answer", "model_id": "test-model"},
    ]
    history.write_text("\n".join(json.dumps(r) for r in records) + "\n")
    return history, GrokExporter(tmp_path / "sessions")


def test_capture_repeat_and_continuation(tmp_path, migrated_db):
    c, _ = migrated_db
    history, exporter = fixture_history(tmp_path)
    assert exporter.export_all(c).added == 1
    rows = c.execute(
        "SELECT role,content,timestamp FROM messages ORDER BY seq"
    ).fetchall()
    assert [tuple(r) for r in rows] == [
        ("user", "question", None),
        ("assistant", "answer", None),
    ]
    assert exporter.export_all(c).skipped == 1
    with history.open("a") as f:
        f.write(json.dumps({"type": "user", "content": "follow-up"}) + "\n")
    assert exporter.export_all(c).updated == 1
    assert c.execute("SELECT count(*) FROM messages").fetchone()[0] == 3
    assert exporter.export_all(c).skipped == 1


def test_partial_write_keeps_last_good_import(tmp_path, migrated_db):
    c, _ = migrated_db
    history, exporter = fixture_history(tmp_path)
    exporter.export_all(c)
    old = c.execute("SELECT import_fingerprint FROM sessions").fetchone()[0]
    with history.open("a") as f:
        f.write('{"type":')
    assert exporter.export_all(c).errors == 1
    assert c.execute("SELECT count(*) FROM messages").fetchone()[0] == 2
    assert c.execute("SELECT import_fingerprint FROM sessions").fetchone()[0] == old
