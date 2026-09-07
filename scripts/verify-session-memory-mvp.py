"""Exercise the installed memory wheel using disposable native conversation data.

Run with a fresh wheel environment's Python, not the workspace's editable Python.
This checks installed capture, repair and retrieval; it does not test SSH or hooks.

WP-8 adds Claude Code and Kiro CLI native-repair coverage through the actual
installed ``session-repair``/``session-query`` binaries (a real subprocess
boundary), using disposable synthetic fixtures:

- Claude Code (exporters/claude.py): ``ClaudeCodeExporter.__init__`` reads the
  ``CLAUDE_CONFIG_DIR`` env var (falling back to ``~/.claude``) *inside the
  subprocess*, so pointing that variable at a fixture directory is enough.
- Kiro CLI (exporters/kiro.py): ``KiroCliExporter`` has **no** constructor
  override and **no** env-var lookup — ``KIRO_DB`` is a bare module constant
  (``Path.home() / "Library/Application Support/kiro-cli/data.sqlite3"``)
  evaluated once, at import time. A literal ``monkeypatch.setattr(...,
  "KIRO_DB", ...)`` (as unit tests such as test_exporter_kiro.py do) only
  rebinds that name in the *current* Python object graph; it has no effect on
  a `session-repair` subprocess, which re-imports the module fresh in its own
  interpreter. The only lever that reaches a subprocess is the environment it
  is launched with, and the only environment input ``KIRO_DB`` derives from is
  ``Path.home()`` (which itself reads ``$HOME``). So here the module constant
  is redirected by launching the subprocess with ``HOME`` set to a fixture
  home directory containing ``Library/Application Support/kiro-cli/
  data.sqlite3`` — not by monkeypatching the attribute in this process.

Never reads a real ``~/.claude`` or ``~/Library/Application Support/kiro-cli``
store: both fixtures live under disposable per-check home directories, and
``--source`` is always passed explicitly so only the exporter under test is
ever instantiated.
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


def write_claude_jsonl(path: Path, texts: tuple[str, ...]) -> Path:
    """Write a synthetic Claude Code JSONL transcript at ``path``.

    Matches the on-disk shape from exporters/claude.py / test_exporter_claude.py:
    one JSON object per line with ``uuid``, ``timestamp`` and a nested
    ``message.role``/``message.content`` pair. Session id is the file stem;
    project path is derived from the parent directory.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    entries = []
    previous_uuid = None
    for index, text in enumerate(texts):
        role = "user" if index % 2 == 0 else "assistant"
        entry_uuid = f"wp8-{index}"
        entries.append(
            {
                "uuid": entry_uuid,
                "parentUuid": previous_uuid,
                "timestamp": f"2026-09-0{index + 1}T00:00:00Z",
                "message": {"role": role, "content": text},
            }
        )
        previous_uuid = entry_uuid
    path.write_text("\n".join(json.dumps(entry) for entry in entries) + "\n")
    return path


def seed_kiro_conversations_v2(db_path: Path, texts: tuple[str, ...]) -> Path:
    """Create a synthetic Kiro CLI ``conversations_v2`` database at ``db_path``.

    Schema and history shape confirmed against exporters/kiro.py's module
    docstring and tests/test_exporter_kiro.py's ``kiro_db``/``_insert_v2``
    fixtures: ``conversations_v2(key, conversation_id, value, created_at,
    updated_at)``, ``value`` a JSON blob with a ``history`` list. Each history
    entry here is the real on-disk shape — a list of turn dicts — with one
    user turn per text: ``{"content": {"Prompt": {"prompt": text}}}``.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE conversations_v2 ("
        "key TEXT NOT NULL, conversation_id TEXT NOT NULL, value TEXT NOT NULL, "
        "created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL, "
        "PRIMARY KEY (key, conversation_id))"
    )
    history = [[{"content": {"Prompt": {"prompt": text}}}] for text in texts]
    payload = {"conversation_id": "wp8-kiro", "history": history}
    conn.execute(
        "INSERT INTO conversations_v2 (key, conversation_id, value, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (
            "/tmp/wp8-kiro-project",
            "wp8-kiro",
            json.dumps(payload),
            1_700_000_000_000,
            1_700_000_000_000,
        ),
    )
    conn.commit()
    conn.close()
    return db_path


def exercise_native_repair(
    cli,
    env: dict,
    source: str,
    db: Path,
    native_fixture: Path,
    original_bytes: bytes,
    texts: tuple[str, ...],
) -> list[str]:
    """Exercise one native source through the installed repair/query CLIs.

    ``db`` must already be an initialised, empty database. ``native_fixture``
    is the on-disk source the exporter reads (JSONL file for Claude, SQLite
    file for Kiro); ``original_bytes`` is its content captured before any
    repair run, to prove the source is never mutated.
    """
    checks = []
    preview = cli("session-repair", "--db", str(db), "--source", source, env=env)
    assert not preview["applied"], f"{source}: preview must not apply"
    assert preview["missing_messages"] >= len(texts), (
        f"{source}: preview found {preview['missing_messages']} missing message(s), "
        f"expected at least {len(texts)}"
    )
    with sqlite3.connect(db) as check:
        assert check.execute("SELECT count(*) FROM messages").fetchone()[0] == 0, (
            f"{source}: preview mutated the target database"
        )
    checks.append(f"{source} repair CLI preview leaves target conversation unchanged")

    applied = cli("session-repair", "--db", str(db), "--source", source, "--apply", env=env)
    assert applied["applied"] and applied["backup"], f"{source}: apply reported no backup"
    backup_path = Path(applied["backup"])
    assert backup_path.exists(), f"{source}: pre-change backup file missing on disk"
    with sqlite3.connect(backup_path) as backup:
        assert backup.execute("SELECT count(*) FROM messages").fetchone()[0] == 0, (
            f"{source}: backup was not taken before the change"
        )
    checks.append(f"{source} repair CLI applies recovered rows with pre-change backup")

    repeat = cli("session-repair", "--db", str(db), "--source", source, env=env)
    assert repeat["missing_messages"] == repeat["changed_messages"] == 0, (
        f"{source}: repeat repair was not zero-delta"
    )
    checks.append(f"{source} repeat repair reports no conversation changes")

    for text in texts:
        results = cli(
            "session-query",
            "search",
            text,
            "--db",
            str(db),
            "--local-only",
            "--output-format",
            "json",
            env=env,
        )
        assert text in json.dumps(results), f"{source}: {text!r} not retrievable via query CLI"
    checks.append(f"{source} query CLI finds recovered conversation messages")

    assert native_fixture.read_bytes() == original_bytes, f"{source}: native source was mutated"
    with sqlite3.connect(db) as check:
        assert check.execute("PRAGMA quick_check").fetchone()[0] == "ok", (
            f"{source}: quick_check failed after repair"
        )
        assert not check.execute("PRAGMA foreign_key_check").fetchall(), (
            f"{source}: foreign_key_check not empty after repair"
        )
    checks.append(f"{source} database integrity and original native source preserved")
    return checks


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

        def cli(name, *args, env=None):
            result = subprocess.run(
                [str(Path(sys.executable).parent / name), *args],
                cwd=root,
                env=env if env is not None else environment,
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

        # --- WP-8: native Claude Code repair, isolated via CLAUDE_CONFIG_DIR.
        claude_home = root / "claude-home"
        claude_fixture = claude_home / "projects" / "wp8-project" / "wp8-session.jsonl"
        claude_texts = ("claude p0 first", "claude p0 continued")
        write_claude_jsonl(claude_fixture, claude_texts)
        claude_original = claude_fixture.read_bytes()
        claude_db = root / "claude.db"
        init_db(str(claude_db)).close()
        claude_env = {**environment, "CLAUDE_CONFIG_DIR": str(claude_home)}
        checks += exercise_native_repair(
            cli, claude_env, "claude", claude_db, claude_fixture, claude_original, claude_texts
        )

        # --- WP-8: native Kiro CLI repair, isolated via HOME (see module
        # docstring for why HOME, not a KIRO_DB monkeypatch, is the only
        # lever that reaches the session-repair subprocess).
        kiro_home = root / "kiro-home"
        kiro_fixture = kiro_home / "Library" / "Application Support" / "kiro-cli" / "data.sqlite3"
        kiro_texts = ("kiro p0 first",)
        seed_kiro_conversations_v2(kiro_fixture, kiro_texts)
        kiro_original = kiro_fixture.read_bytes()
        kiro_db = root / "kiro.db"
        init_db(str(kiro_db)).close()
        kiro_env = {**environment, "HOME": str(kiro_home)}
        checks += exercise_native_repair(
            cli, kiro_env, "kiro", kiro_db, kiro_fixture, kiro_original, kiro_texts
        )

    for check in checks:
        print(f"PASS: {check}")
    print(f"{len(checks)} checks passed")


if __name__ == "__main__":
    main()
