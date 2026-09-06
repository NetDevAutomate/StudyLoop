"""Exercise the installed memory wheel using disposable native conversation data.

Run with a fresh wheel environment's Python, not the workspace's editable Python.
This checks installed capture, repair and retrieval; it does not test SSH or hooks.
"""

import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

from agent_session_tools.export_sessions import init_db
from agent_session_tools.exporters.codex import CodexExporter


def main():
    assert importlib.util.find_spec("studyloop") is None, "Use a memory-only environment"
    checks = []
    with tempfile.TemporaryDirectory(prefix="session-memory-mvp-") as directory:
        root = Path(directory)
        archive = root / "codex" / "sessions" / "rollout-mvp.jsonl"
        archive.parent.mkdir(parents=True)
        native = [
            {"type": "session_meta", "payload": {"id": "mvp", "cwd": str(root / "project")}},
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": "Explain the archivecanary decision"}
                    ],
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "content": [
                        {"type": "output_text", "text": "The archivecanary answer is recorded"}
                    ],
                },
            },
        ]
        archive.write_text("\n".join(map(json.dumps, native)) + "\n")
        source, target = root / "source.db", root / "target.db"
        conn = init_db(str(source))
        exporter = CodexExporter(sessions_dir=archive.parent)
        first = exporter.export_all(conn)
        assert first.added == 1 and first.errors == 0
        checks.append("installed native exporter captures conversation")
        native.append(
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "Continue the archivecanary"}],
                },
            }
        )
        archive.write_text("\n".join(map(json.dumps, native)) + "\n")
        original_native = archive.read_bytes()
        continued = exporter.export_all(conn)
        assert continued.errors == 0
        assert conn.execute("SELECT count(*) FROM messages").fetchone()[0] == 3
        exporter.export_all(conn)
        assert conn.execute("SELECT count(*) FROM messages").fetchone()[0] == 3
        conn.close()
        checks.append("continued native conversation imports without duplicates")
        init_db(str(target)).close()
        config = root / "config.json"
        config.write_text(json.dumps({"database": {"path": str(target)}}))
        environment = {**os.environ, "STUDYLOOP_CONFIG": str(config), "STUDYLOOP_DB": str(target)}
        for key in (
            "PYTHONPATH",
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
            "OPENROUTER_API_KEY",
            "GEMINI_API_KEY",
            "AWS_BEARER_TOKEN_BEDROCK",
        ):
            environment.pop(key, None)

        def cli(name, *args):
            result = subprocess.run(
                [str(Path(sys.executable).parent / name), *args],
                cwd=root,
                env=environment,
                text=True,
                capture_output=True,
                timeout=30,
                check=True,
            )
            return json.loads(result.stdout)

        args = ("--db", str(target), "--from-db", str(source))
        preview = cli("session-repair", *args)
        assert preview["missing_messages"] == 3 and not preview["applied"]
        with sqlite3.connect(target) as check:
            assert check.execute("SELECT count(*) FROM messages").fetchone()[0] == 0
        checks.append("repair CLI preview leaves target conversation unchanged")
        applied = cli("session-repair", *args, "--apply")
        assert applied["applied"] and applied["backup"]
        with sqlite3.connect(applied["backup"]) as backup:
            assert backup.execute("SELECT count(*) FROM messages").fetchone()[0] == 0
        checks.append("repair CLI applies recovered rows with pre-change backup")
        repeat = cli("session-repair", *args)
        assert repeat["missing_messages"] == repeat["changed_messages"] == 0
        checks.append("repeat repair reports no conversation changes")
        results = cli(
            "session-query",
            "search",
            "archivecanary",
            "--db",
            str(target),
            "--local-only",
            "--output-format",
            "json",
        )
        assert "archivecanary" in json.dumps(results) and len(results) == 3
        checks.append("query CLI finds all three recovered conversation messages")
        with sqlite3.connect(target) as check:
            assert check.execute("PRAGMA quick_check").fetchone()[0] == "ok"
            assert not check.execute("PRAGMA foreign_key_check").fetchall()
        assert archive.read_bytes() == original_native
        checks.append("database integrity and original native transcript preserved")
    print(json.dumps({"passed": len(checks), "checks": checks}, indent=2))


if __name__ == "__main__":
    main()
