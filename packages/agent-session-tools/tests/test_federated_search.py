"""Tests for federated (hot + full) search and tier-aware sync helpers."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timedelta

import pytest

from agent_session_tools import query_db
from agent_session_tools.export_sessions import init_db
from agent_session_tools.query_logic import search
from agent_session_tools.sync import _FTS_REPAIR_SQL, _pruned_session_ids
from agent_session_tools.tiering import fts_integrity, prune_hot, sync_to_full


@pytest.fixture
def tiered_config(tmp_path, monkeypatch):
    """Config with hot + full paths inside tmp_path, active via STUDYLOOP_CONFIG."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    hot = config_dir / "sessions.db"
    full_dir = tmp_path / "external" / "DB"
    full_dir.mkdir(parents=True)
    full = full_dir / "sessions_full.db"

    config_file = config_dir / "config.yaml"
    config_file.write_text(
        f"""
database:
  path: {hot}
  full_db_path: {full}
"""
    )
    monkeypatch.setenv("STUDYLOOP_CONFIG", str(config_file))
    # query_db caches config at module level — reset per test
    monkeypatch.setattr(query_db, "_config", None)
    return {"hot": hot, "full": full, "config_dir": config_dir}


def _seed_and_prune(cfg) -> None:
    """Hot gets an old + a new session; sync; prune the old one from hot."""
    conn = init_db(str(cfg["hot"]))
    old = (datetime.now() - timedelta(days=90)).isoformat()
    new = datetime.now().isoformat()
    conn.execute(
        "INSERT INTO sessions (id, source, created_at, updated_at, content_hash) "
        "VALUES ('old1', 'claude_code', ?, ?, 'h-old1')",
        (old, old),
    )
    conn.execute(
        "INSERT INTO messages (id, session_id, role, content, timestamp) "
        "VALUES ('old1-m0', 'old1', 'user', 'ancient decorators wisdom', ?)",
        (old,),
    )
    conn.execute(
        "INSERT INTO sessions (id, source, created_at, updated_at, content_hash) "
        "VALUES ('new1', 'kiro_cli', ?, ?, 'h-new1')",
        (new, new),
    )
    conn.execute(
        "INSERT INTO messages (id, session_id, role, content, timestamp) "
        "VALUES ('new1-m0', 'new1', 'user', 'fresh decorators question', ?)",
        (new,),
    )
    conn.commit()
    conn.close()
    sync_to_full()
    prune_hot(days=30, dry_run=False)


def _search_json(capsys, **kwargs) -> list[dict]:
    capsys.readouterr()  # flush seeding output (migration prints)
    conn = query_db.get_connection()
    try:
        search(conn, "decorators", output_format="json", **kwargs)
    finally:
        conn.close()
    return json.loads(capsys.readouterr().out)


class TestFederatedSearch:
    def test_pruned_history_found_with_full_tier_tag(self, tiered_config, capsys):
        _seed_and_prune(tiered_config)
        results = _search_json(capsys)
        by_id = {r["session_id"]: r for r in results}
        assert by_id["new1"]["tier"] == "local"
        assert by_id["old1"]["tier"] == "full"  # pruned locally, found in record

    def test_local_only_excludes_history(self, tiered_config, capsys):
        _seed_and_prune(tiered_config)
        results = _search_json(capsys, include_full=False)
        ids = {r["session_id"] for r in results}
        assert ids == {"new1"}

    def test_unmounted_full_falls_back_silently(self, tiered_config, capsys):
        _seed_and_prune(tiered_config)
        shutil.rmtree(tiered_config["full"].parent)  # "unmount"
        results = _search_json(capsys)
        ids = {r["session_id"] for r in results}
        assert ids == {"new1"}  # local results only, no error

    def test_no_duplicates_for_unpruned_sessions(self, tiered_config, capsys):
        """Sessions in both tiers surface once, from local."""
        _seed_and_prune(tiered_config)
        results = _search_json(capsys)
        ids = [r["session_id"] for r in results]
        assert len(ids) == len(set(ids))
        assert {r["session_id"]: r["tier"] for r in results}["new1"] == "local"


class TestPruneAwarePull:
    def test_pruned_ids_detected(self, tiered_config):
        _seed_and_prune(tiered_config)
        # 'old1' was pruned (present in full); 'ghost' is genuinely new
        result = _pruned_session_ids({"old1", "ghost"})
        assert result == {"old1"}

    def test_empty_when_tiering_disabled(self, tiered_config):
        cfg_file = tiered_config["config_dir"] / "config.yaml"
        cfg_file.write_text(f"database:\n  path: {tiered_config['hot']}\n")
        import agent_session_tools.sync as sync_mod

        sync_mod._config = None  # reset module cache
        try:
            assert _pruned_session_ids({"anything"}) == set()
        finally:
            sync_mod._config = None


class TestFtsSafeImport:
    def test_repair_sql_fixes_replace_trigger_leak(self, tiered_config):
        """INSERT OR REPLACE doesn't fire delete triggers -> orphaned FTS
        rows. The repair SQL appended to every sync import must fix that."""
        db = tiered_config["hot"]
        conn = init_db(str(db))
        conn.execute("INSERT INTO sessions (id, source) VALUES ('s1', 'claude_code')")
        conn.execute(
            "INSERT INTO messages (id, session_id, role, content) "
            "VALUES ('m1', 's1', 'user', 'original decorators content')"
        )
        conn.commit()

        # Simulate what a sync import does to an updated message
        conn.execute(
            "INSERT OR REPLACE INTO messages (id, session_id, role, content) "
            "VALUES ('m1', 's1', 'user', 'updated decorators content')"
        )
        conn.commit()
        leaked = fts_integrity(conn)
        assert not leaked.healthy  # the bug: orphan row from the REPLACE

        conn.executescript(_FTS_REPAIR_SQL)
        conn.commit()
        repaired = fts_integrity(conn)
        assert repaired.healthy
        hits = conn.execute(
            "SELECT COUNT(*) FROM messages_fts WHERE messages_fts MATCH 'updated'"
        ).fetchone()[0]
        conn.close()
        assert hits == 1
