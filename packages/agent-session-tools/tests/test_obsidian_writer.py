"""Tests for agent_session_tools.obsidian_writer and related CLI surface.

Pure-dict tests where possible (no DB). Fixtures: populated_db, tmp_path.
CLI tests use typer.testing.CliRunner.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner

from agent_session_tools.config_loader import (
    get_obsidian_config as cfg_loader_get_obsidian_config,
)
from agent_session_tools.export_sessions import _run_export, app
from agent_session_tools.obsidian_writer import (
    _OBSIDIAN_DEFAULTS,
    build_topic_index,
    get_obsidian_config,
    inject_backlinks,
    write_moc,
    write_session_to_vault,
    write_vault_notes,
)

# ---------------------------------------------------------------------------
# Shared fixtures / helpers
# ---------------------------------------------------------------------------

runner = CliRunner()

_SESSION: dict[str, Any] = {
    "id": "deadbeef0000000011112222333344445555",
    "source": "claude_code",
    "project_path": "/home/user/my-project",
    "git_branch": "feat/obsidian-export",
    "created_at": "2024-03-15T09:00:00",
    "updated_at": "2024-03-15T11:00:00",
    "metadata": None,
}

_MESSAGES: list[dict[str, Any]] = [
    {"role": "user", "content": "How do I implement a backlink scanner?"},
    {"role": "assistant", "content": "Parse frontmatter aliases with PyYAML."},
]

_OBSIDIAN_CFG: dict[str, Any] = {
    **_OBSIDIAN_DEFAULTS,
    "backlinks": False,  # disable to avoid touching vault FS in most unit tests
    "granularity": "both",
}


def _make_vault(tmp_path: Path) -> Path:
    """Return a minimal vault root with the .obsidian marker."""
    vault = tmp_path / "TestVault"
    vault.mkdir()
    (vault / ".obsidian").mkdir()
    return vault


def _parse_frontmatter(note_path: Path) -> dict[str, Any]:
    """Parse the YAML frontmatter from a note file; raises on malformed input."""
    text = note_path.read_text(encoding="utf-8")
    assert text.startswith("---"), f"No frontmatter found in {note_path}"
    parts = text.split("---", 2)
    assert len(parts) >= 3, "Frontmatter not closed"
    fm = yaml.safe_load(parts[1])
    assert isinstance(fm, dict), "Frontmatter is not a mapping"
    return fm


# ---------------------------------------------------------------------------
# write_session_to_vault — basic creation
# ---------------------------------------------------------------------------


class TestWriteSessionToVault:
    def test_creates_md_file_in_agent_memory(self, tmp_path: Path) -> None:
        """A new session must produce a .md file inside <vault>/AgentMemory/."""
        vault = _make_vault(tmp_path)
        result = write_session_to_vault(
            _SESSION, _MESSAGES, vault, obsidian_cfg=_OBSIDIAN_CFG
        )

        assert result is not None
        assert result.exists()
        assert result.suffix == ".md"
        # Must be inside AgentMemory (or whatever memory_dir is configured)
        assert result.parent.name == _OBSIDIAN_DEFAULTS["memory_dir"]

    def test_frontmatter_contains_required_keys(self, tmp_path: Path) -> None:
        """The frontmatter must carry all Dataview-required fields."""
        vault = _make_vault(tmp_path)
        result = write_session_to_vault(
            _SESSION, _MESSAGES, vault, obsidian_cfg=_OBSIDIAN_CFG
        )
        assert result is not None

        fm = _parse_frontmatter(result)
        required_keys = {
            "type",
            "id",
            "created",
            "updated",
            "status",
            "source_tool",
            "source_project",
            "session_id",
            "git_branch",
            "tags",
            "date",
            "about",
            "content_hash",
        }
        missing = required_keys - set(fm.keys())
        assert not missing, f"Frontmatter missing keys: {missing}"

    def test_frontmatter_type_is_agent_memory(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        result = write_session_to_vault(
            _SESSION, _MESSAGES, vault, obsidian_cfg=_OBSIDIAN_CFG
        )
        assert result is not None
        fm = _parse_frontmatter(result)
        assert fm["type"] == "agent-memory"

    def test_frontmatter_session_id_matches(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        result = write_session_to_vault(
            _SESSION, _MESSAGES, vault, obsidian_cfg=_OBSIDIAN_CFG
        )
        assert result is not None
        fm = _parse_frontmatter(result)
        assert fm["session_id"] == _SESSION["id"]

    def test_frontmatter_source_tool_matches(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        result = write_session_to_vault(
            _SESSION, _MESSAGES, vault, obsidian_cfg=_OBSIDIAN_CFG
        )
        assert result is not None
        fm = _parse_frontmatter(result)
        assert fm["source_tool"] == _SESSION["source"]

    def test_frontmatter_source_project_is_basename(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        result = write_session_to_vault(
            _SESSION, _MESSAGES, vault, obsidian_cfg=_OBSIDIAN_CFG
        )
        assert result is not None
        fm = _parse_frontmatter(result)
        assert fm["source_project"] == "my-project"

    def test_frontmatter_date_matches_created_at(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        result = write_session_to_vault(
            _SESSION, _MESSAGES, vault, obsidian_cfg=_OBSIDIAN_CFG
        )
        assert result is not None
        fm = _parse_frontmatter(result)
        # date should be the YYYY-MM-DD prefix of created_at
        assert fm["date"] == "2024-03-15"

    def test_body_contains_project_and_date_heading(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        result = write_session_to_vault(
            _SESSION, _MESSAGES, vault, obsidian_cfg=_OBSIDIAN_CFG
        )
        assert result is not None
        body = result.read_text(encoding="utf-8")
        assert "# Session Memory" in body
        assert "my-project" in body
        assert "2024-03-15" in body

    def test_none_project_path_handled(self, tmp_path: Path) -> None:
        """A session with no project_path must not raise."""
        vault = _make_vault(tmp_path)
        session = {**_SESSION, "project_path": None}
        result = write_session_to_vault(
            session, _MESSAGES, vault, obsidian_cfg=_OBSIDIAN_CFG
        )
        assert result is not None
        assert result.exists()

    def test_git_branch_in_frontmatter(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        result = write_session_to_vault(
            _SESSION, _MESSAGES, vault, obsidian_cfg=_OBSIDIAN_CFG
        )
        assert result is not None
        fm = _parse_frontmatter(result)
        assert fm["git_branch"] == "feat/obsidian-export"

    def test_malicious_created_at_cannot_escape_vault(self, tmp_path: Path) -> None:
        """created_at is untrusted; path-traversal must be neutralised.

        A crafted created_at like '../../../tmp/PWNED' must NOT cause a write
        outside the vault memory dir. The date is sanitised to digits/hyphens
        and a containment guard backs it up.
        """
        vault = _make_vault(tmp_path)
        malicious = {
            **_SESSION,
            "created_at": "../../../tmp/PWNED",
            "updated_at": "../../../tmp/PWNED",
        }
        result = write_session_to_vault(
            malicious, _MESSAGES, vault, obsidian_cfg=_OBSIDIAN_CFG
        )
        assert result is not None
        # The written file must live inside the vault's AgentMemory dir.
        memory_dir = (vault / "AgentMemory").resolve()
        assert memory_dir in result.resolve().parents, (
            f"Note escaped the vault: {result}"
        )
        # And nothing was written to the traversal target.
        assert not (tmp_path.parent / "tmp" / "PWNED").exists()


# ---------------------------------------------------------------------------
# write_session_to_vault — idempotency
# ---------------------------------------------------------------------------


class TestWriteSessionToVaultIdempotency:
    def test_second_call_returns_none_for_unchanged_session(
        self, tmp_path: Path
    ) -> None:
        """Re-exporting the same session must return None (content hash match)."""
        vault = _make_vault(tmp_path)
        first = write_session_to_vault(
            _SESSION, _MESSAGES, vault, obsidian_cfg=_OBSIDIAN_CFG
        )
        assert first is not None  # first write succeeded

        second = write_session_to_vault(
            _SESSION, _MESSAGES, vault, obsidian_cfg=_OBSIDIAN_CFG
        )
        assert second is None  # skip — unchanged

    def test_second_call_writes_no_new_files(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        memory_dir = vault / _OBSIDIAN_DEFAULTS["memory_dir"]

        write_session_to_vault(_SESSION, _MESSAGES, vault, obsidian_cfg=_OBSIDIAN_CFG)
        files_after_first = list(memory_dir.glob("*.md"))

        write_session_to_vault(_SESSION, _MESSAGES, vault, obsidian_cfg=_OBSIDIAN_CFG)
        files_after_second = list(memory_dir.glob("*.md"))

        assert len(files_after_first) == len(files_after_second)

    def test_changed_message_triggers_overwrite(self, tmp_path: Path) -> None:
        """If the session content changes the note must be overwritten."""
        vault = _make_vault(tmp_path)
        first = write_session_to_vault(
            _SESSION, _MESSAGES, vault, obsidian_cfg=_OBSIDIAN_CFG
        )
        assert first is not None

        new_messages = [
            *_MESSAGES,
            {"role": "user", "content": "A completely new user question."},
            {"role": "assistant", "content": "A brand new answer changes the hash."},
        ]
        second = write_session_to_vault(
            _SESSION, new_messages, vault, obsidian_cfg=_OBSIDIAN_CFG
        )
        assert second is not None  # overwrite triggered


# ---------------------------------------------------------------------------
# build_topic_index
# ---------------------------------------------------------------------------


class TestBuildTopicIndex:
    def test_empty_vault_returns_empty_dict(self, tmp_path: Path) -> None:
        vault = tmp_path / "EmptyVault"
        vault.mkdir()
        assert build_topic_index(vault) == {}

    def test_non_existent_vault_returns_empty_dict(self, tmp_path: Path) -> None:
        assert build_topic_index(tmp_path / "NonExistent") == {}

    def test_picks_up_note_stem_as_title(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        (vault / "Python.md").write_text("# Python\nSome content.", encoding="utf-8")

        index = build_topic_index(vault)
        assert "python" in index
        assert index["python"] == "Python"

    def test_picks_up_aliases_from_frontmatter(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        note = vault / "Data-Engineering.md"
        note.write_text(
            "---\naliases:\n  - Data Engineering\n  - DE\n---\n# Data Engineering\n",
            encoding="utf-8",
        )

        index = build_topic_index(vault)
        assert "data-engineering" in index
        assert "data engineering" in index
        assert "de" in index
        # All three aliases should resolve to the canonical title
        assert index["data engineering"] == "Data-Engineering"
        assert index["de"] == "Data-Engineering"

    def test_skips_dotfolders(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        # .obsidian is a dotfolder — notes inside must be skipped
        obsidian_note = vault / ".obsidian" / "snippets.md"
        obsidian_note.write_text("# Secret", encoding="utf-8")

        index = build_topic_index(vault)
        assert "snippets" not in index

    def test_skips_smart_env_dotfolder(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        smart_dir = vault / ".smart-env"
        smart_dir.mkdir()
        (smart_dir / "SmartNote.md").write_text("# Smart", encoding="utf-8")

        index = build_topic_index(vault)
        assert "smartnote" not in index

    def test_picks_up_notes_in_subdirectories(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        sub = vault / "Topics"
        sub.mkdir()
        (sub / "GraphRAG.md").write_text("# GraphRAG", encoding="utf-8")

        index = build_topic_index(vault)
        assert "graphrag" in index

    def test_string_alias_is_supported(self, tmp_path: Path) -> None:
        """A scalar (string) alias in frontmatter must be treated as a single alias."""
        vault = _make_vault(tmp_path)
        note = vault / "AWS.md"
        note.write_text(
            "---\naliases: Amazon Web Services\n---\n# AWS\n",
            encoding="utf-8",
        )

        index = build_topic_index(vault)
        assert "amazon web services" in index


# ---------------------------------------------------------------------------
# inject_backlinks
# ---------------------------------------------------------------------------


class TestInjectBacklinks:
    def test_returns_wikilink_for_matched_topic(self) -> None:
        index = {"python": "Python", "aws": "AWS"}
        result = inject_backlinks(["Python"], index)
        assert result == ["[[Python]]"]

    def test_returns_empty_for_unmatched_topic(self) -> None:
        index = {"python": "Python"}
        result = inject_backlinks(["Rust"], index)
        assert result == []

    def test_case_insensitive_match(self) -> None:
        index = {"graphrag": "GraphRAG"}
        result = inject_backlinks(["graphrag"], index)
        assert result == ["[[GraphRAG]]"]

    def test_deduplicates_links(self) -> None:
        """Same topic appearing twice must produce one wikilink."""
        index = {"python": "Python"}
        result = inject_backlinks(["Python", "python"], index)
        assert result == ["[[Python]]"]

    def test_preserves_input_order(self) -> None:
        index = {"python": "Python", "aws": "AWS", "graphrag": "GraphRAG"}
        result = inject_backlinks(["GraphRAG", "Python", "AWS"], index)
        assert result == ["[[GraphRAG]]", "[[Python]]", "[[AWS]]"]

    def test_empty_topics_returns_empty(self) -> None:
        index = {"python": "Python"}
        assert inject_backlinks([], index) == []

    def test_empty_index_returns_empty(self) -> None:
        assert inject_backlinks(["Python"], {}) == []


# ---------------------------------------------------------------------------
# write_moc
# ---------------------------------------------------------------------------


class TestWriteMoc:
    def test_creates_moc_file_in_moc_dir(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        cfg = {**_OBSIDIAN_DEFAULTS, "moc_dir": "AgentMemory/MOC"}
        note_ids = ["2024-03-15-claude-code-my-project-abcd1234"]

        moc_path = write_moc(vault, cfg, "my-project", note_ids)

        assert moc_path.exists()
        assert moc_path.suffix == ".md"
        # Must sit inside the moc_dir
        assert moc_path.parent == vault / "AgentMemory" / "MOC"

    def test_moc_lists_note_ids_as_wikilinks(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        cfg = {**_OBSIDIAN_DEFAULTS, "moc_dir": "AgentMemory/MOC"}
        note_ids = [
            "2024-03-13-claude-code-my-project-aaa",
            "2024-03-15-claude-code-my-project-bbb",
        ]
        moc_path = write_moc(vault, cfg, "my-project", note_ids)

        content = moc_path.read_text(encoding="utf-8")
        assert "[[2024-03-13-claude-code-my-project-aaa]]" in content
        assert "[[2024-03-15-claude-code-my-project-bbb]]" in content

    def test_moc_lists_in_reverse_chronological_order(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        cfg = {**_OBSIDIAN_DEFAULTS, "moc_dir": "AgentMemory/MOC"}
        note_ids = ["2024-03-10-id-a", "2024-03-12-id-b", "2024-03-14-id-c"]
        moc_path = write_moc(vault, cfg, "proj", note_ids)

        content = moc_path.read_text(encoding="utf-8")
        pos_a = content.index("id-a")
        pos_c = content.index("id-c")
        # reverse order means c (latest) should appear before a (earliest)
        assert pos_c < pos_a

    def test_moc_frontmatter_has_type_agent_memory_moc(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        cfg = {**_OBSIDIAN_DEFAULTS, "moc_dir": "AgentMemory/MOC"}
        moc_path = write_moc(vault, cfg, "proj", [])
        fm = _parse_frontmatter(moc_path)
        assert fm["type"] == "agent-memory-moc"

    def test_moc_filename_is_slugified_project(self, tmp_path: Path) -> None:
        vault = _make_vault(tmp_path)
        cfg = {**_OBSIDIAN_DEFAULTS, "moc_dir": "AgentMemory/MOC"}
        moc_path = write_moc(vault, cfg, "My Cool Project", [])
        assert moc_path.stem == "my-cool-project"


# ---------------------------------------------------------------------------
# write_vault_notes — orchestration
# ---------------------------------------------------------------------------


class TestWriteVaultNotes:
    """Integration tests that drive write_vault_notes against populated_db."""

    def test_returns_count_dict_with_written_skipped_mocs(
        self, populated_db: tuple[sqlite3.Connection, Path], tmp_path: Path
    ) -> None:
        conn, _ = populated_db
        vault = _make_vault(tmp_path)
        cfg = {**_OBSIDIAN_DEFAULTS, "backlinks": False}

        counts = write_vault_notes(conn, cfg, vault)

        assert "written" in counts
        assert "skipped" in counts
        assert "mocs" in counts
        assert isinstance(counts["written"], int)

    def test_writes_note_files_to_vault(
        self, populated_db: tuple[sqlite3.Connection, Path], tmp_path: Path
    ) -> None:
        conn, _ = populated_db
        vault = _make_vault(tmp_path)
        cfg = {**_OBSIDIAN_DEFAULTS, "backlinks": False}

        counts = write_vault_notes(conn, cfg, vault)

        memory_dir = vault / _OBSIDIAN_DEFAULTS["memory_dir"]
        md_files = list(memory_dir.glob("*.md"))
        # There is one session in populated_db — expect 1 note written
        assert counts["written"] == 1
        assert len(md_files) == 1

    def test_dry_run_writes_nothing(
        self, populated_db: tuple[sqlite3.Connection, Path], tmp_path: Path
    ) -> None:
        conn, _ = populated_db
        vault = _make_vault(tmp_path)
        cfg = {**_OBSIDIAN_DEFAULTS, "backlinks": False}

        counts = write_vault_notes(conn, cfg, vault, dry_run=True)

        # No .md files should exist anywhere in the vault (aside from .obsidian)
        all_md = [
            p
            for p in vault.rglob("*.md")
            if not any(part.startswith(".") for part in p.relative_to(vault).parts)
        ]
        assert all_md == [], f"dry_run wrote files: {all_md}"
        # But the count should reflect what *would* have been written
        assert counts["written"] == 1

    def test_dry_run_does_not_write_moc_files(
        self, populated_db: tuple[sqlite3.Connection, Path], tmp_path: Path
    ) -> None:
        conn, _ = populated_db
        vault = _make_vault(tmp_path)
        cfg = {**_OBSIDIAN_DEFAULTS, "backlinks": False, "granularity": "both"}

        write_vault_notes(conn, cfg, vault, dry_run=True)

        moc_dir = vault / _OBSIDIAN_DEFAULTS["moc_dir"]
        assert not moc_dir.exists() or list(moc_dir.glob("*.md")) == []

    def test_granularity_session_skips_moc(
        self, populated_db: tuple[sqlite3.Connection, Path], tmp_path: Path
    ) -> None:
        conn, _ = populated_db
        vault = _make_vault(tmp_path)
        cfg = {**_OBSIDIAN_DEFAULTS, "backlinks": False, "granularity": "session"}

        counts = write_vault_notes(conn, cfg, vault)

        assert counts["mocs"] == 0
        moc_dir = vault / _OBSIDIAN_DEFAULTS["moc_dir"]
        assert not moc_dir.exists() or list(moc_dir.glob("*.md")) == []

    def test_granularity_both_writes_moc(
        self, populated_db: tuple[sqlite3.Connection, Path], tmp_path: Path
    ) -> None:
        conn, _ = populated_db
        vault = _make_vault(tmp_path)
        cfg = {**_OBSIDIAN_DEFAULTS, "backlinks": False, "granularity": "both"}

        counts = write_vault_notes(conn, cfg, vault)

        assert counts["mocs"] >= 1

    def test_idempotent_second_run_skips_all(
        self, populated_db: tuple[sqlite3.Connection, Path], tmp_path: Path
    ) -> None:
        conn, _ = populated_db
        vault = _make_vault(tmp_path)
        cfg = {**_OBSIDIAN_DEFAULTS, "backlinks": False}

        first = write_vault_notes(conn, cfg, vault)
        second = write_vault_notes(conn, cfg, vault)

        assert first["written"] == 1
        assert second["written"] == 0
        assert second["skipped"] == 1

    def test_missing_vault_returns_zero_counts(
        self, populated_db: tuple[sqlite3.Connection, Path], tmp_path: Path
    ) -> None:
        conn, _ = populated_db
        nonexistent = tmp_path / "does-not-exist"
        cfg = {**_OBSIDIAN_DEFAULTS}

        counts = write_vault_notes(conn, cfg, nonexistent)

        assert counts == {"written": 0, "skipped": 0, "mocs": 0}


# ---------------------------------------------------------------------------
# get_obsidian_config — unit tests
# ---------------------------------------------------------------------------


class TestGetObsidianConfig:
    """Tests for obsidian_writer.get_obsidian_config and config_loader.get_obsidian_config."""

    def test_returns_dict_with_all_defaults(self) -> None:
        """With a bare config dict, all defaults must be present."""
        result = get_obsidian_config({})
        for key in _OBSIDIAN_DEFAULTS:
            assert key in result, f"Missing key: {key}"

    def test_obsidian_section_overrides_defaults(self) -> None:
        config = {"obsidian": {"memory_dir": "MyMemory", "backlinks": False}}
        result = get_obsidian_config(config)
        assert result["memory_dir"] == "MyMemory"
        assert result["backlinks"] is False
        # Keys not overridden should still be from defaults
        assert result["moc_dir"] == _OBSIDIAN_DEFAULTS["moc_dir"]

    def test_obsidian_base_provides_vault_path_fallback(self) -> None:
        config = {"obsidian_base": "/home/user/Obsidian"}
        result = get_obsidian_config(config)
        assert result["vault_path"] == "/home/user/Obsidian"

    def test_obsidian_section_vault_path_wins_over_obsidian_base(self) -> None:
        config = {
            "obsidian_base": "/home/user/OldVault",
            "obsidian": {"vault_path": "/home/user/NewVault"},
        }
        result = get_obsidian_config(config)
        assert result["vault_path"] == "/home/user/NewVault"

    def test_config_loader_get_obsidian_config_returns_dict(self) -> None:
        """config_loader.get_obsidian_config must also return a dict with known keys."""
        result = cfg_loader_get_obsidian_config({"obsidian": {}})
        # The config_loader version simply returns the obsidian section from load_config;
        # when an empty dict is passed the DEFAULT_CONFIG obsidian section is returned.
        assert isinstance(result, dict)

    def test_studyloop_config_env_var_picked_up(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """STUDYLOOP_CONFIG env var should redirect which YAML is read."""
        config_file = tmp_path / "test-config.yaml"
        config_file.write_text(
            "obsidian:\n  vault_path: /tmp/my-vault\n  export_enabled: true\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("STUDYLOOP_CONFIG", str(config_file))

        from agent_session_tools.config_loader import load_config

        loaded = load_config()
        obs = loaded.get("obsidian", {})
        assert obs.get("vault_path") == "/tmp/my-vault"
        assert obs.get("export_enabled") is True


# ---------------------------------------------------------------------------
# CLI — CliRunner tests
# ---------------------------------------------------------------------------


class TestCliObsidianFlags:
    """Tests for the session-export CLI obsidian-related flags."""

    def _make_db(self, tmp_path: Path) -> Path:
        """Create a minimal populated DB for CLI invocations."""
        db_path = tmp_path / "sessions.db"
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        schema_path = (
            Path(__file__).parent.parent / "src" / "agent_session_tools" / "schema.sql"
        )
        with open(schema_path) as f:
            conn.executescript(f.read())
        conn.execute(
            """
            INSERT INTO sessions (id, source, project_path, git_branch, created_at, updated_at, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "cli-test-session-001",
                "claude_code",
                "/tmp/cli-project",
                "main",
                "2024-04-01T10:00:00",
                "2024-04-01T12:00:00",
                None,
            ),
        )
        conn.commit()
        conn.close()
        return db_path

    def test_no_obsidian_flag_writes_nothing_to_vault(self, tmp_path: Path) -> None:
        """Without --obsidian, no notes should land in the vault."""
        db_path = self._make_db(tmp_path)
        vault = _make_vault(tmp_path)

        result = runner.invoke(
            app,
            [
                "--output",
                str(db_path),
                "--sources",
                "claude",  # pick a fast-failing source (no files to scan)
                "--no-obsidian",
                "--obsidian-vault",
                str(vault),
            ],
        )
        # The exit code should be 0 (vault path guard returns gracefully)
        assert result.exit_code == 0, result.output
        # No notes written
        all_md = [
            p
            for p in vault.rglob("*.md")
            if not any(part.startswith(".") for part in p.relative_to(vault).parts)
        ]
        assert all_md == []

    def test_obsidian_dry_run_writes_nothing(self, tmp_path: Path) -> None:
        """--obsidian --obsidian-dry-run must not write any .md files."""
        db_path = self._make_db(tmp_path)
        vault = _make_vault(tmp_path)

        result = runner.invoke(
            app,
            [
                "--output",
                str(db_path),
                "--sources",
                "claude",
                "--obsidian",
                "--obsidian-vault",
                str(vault),
                "--obsidian-dry-run",
            ],
        )
        assert result.exit_code == 0, result.output
        all_md = [
            p
            for p in vault.rglob("*.md")
            if not any(part.startswith(".") for part in p.relative_to(vault).parts)
        ]
        assert all_md == []

    def test_obsidian_without_dry_run_writes_notes(self, tmp_path: Path) -> None:
        """--obsidian (no dry-run) must produce .md files in the vault."""
        db_path = self._make_db(tmp_path)
        vault = _make_vault(tmp_path)

        result = runner.invoke(
            app,
            [
                "--output",
                str(db_path),
                "--sources",
                "claude",
                "--obsidian",
                "--obsidian-vault",
                str(vault),
                # Backfill so the pre-inserted DB session is exported regardless
                # of what (if anything) the import touched this run — keeps the
                # test hermetic on a clean CI runner with no ~/.claude sessions.
                "--obsidian-backfill",
            ],
        )
        assert result.exit_code == 0, result.output

        all_md = [
            p
            for p in vault.rglob("*.md")
            if not any(part.startswith(".") for part in p.relative_to(vault).parts)
        ]
        assert len(all_md) >= 1, (
            f"Expected at least one note in {vault}, output: {result.output}"
        )

    def test_obsidian_output_reports_written_count(self, tmp_path: Path) -> None:
        """CLI output must mention 'written=' after an Obsidian export."""
        db_path = self._make_db(tmp_path)
        vault = _make_vault(tmp_path)

        result = runner.invoke(
            app,
            [
                "--output",
                str(db_path),
                "--sources",
                "claude",
                "--obsidian",
                "--obsidian-vault",
                str(vault),
                # Backfill: export the pre-inserted session deterministically
                # (see test_obsidian_without_dry_run_writes_notes).
                "--obsidian-backfill",
            ],
        )
        assert result.exit_code == 0, result.output
        assert "written=" in result.output

    def test_obsidian_dry_run_output_says_dry_run(self, tmp_path: Path) -> None:
        """Dry-run output must include the '(dry-run)' tag."""
        db_path = self._make_db(tmp_path)
        vault = _make_vault(tmp_path)

        result = runner.invoke(
            app,
            [
                "--output",
                str(db_path),
                "--sources",
                "claude",
                "--obsidian",
                "--obsidian-vault",
                str(vault),
                "--obsidian-dry-run",
                # Backfill so the writer runs (and prints the dry-run tag) even
                # when nothing was imported this run — hermetic on clean CI.
                "--obsidian-backfill",
            ],
        )
        assert result.exit_code == 0, result.output
        assert "dry-run" in result.output

    def _count_notes(self, vault: Path) -> int:
        """Count non-dotfolder .md notes in a vault."""
        return len(
            [
                p
                for p in vault.rglob("*.md")
                if not any(part.startswith(".") for part in p.relative_to(vault).parts)
            ]
        )

    def test_incremental_skips_untouched_but_backfill_exports_all(
        self, tmp_path: Path
    ) -> None:
        """Regression: --obsidian-backfill must differ from a normal run.

        A session pre-existing in the DB and NOT touched by any exporter this
        run must be skipped on a normal incremental --obsidian run (touched-ID
        diff is empty) but written on --obsidian-backfill. This proves the
        backfill flag is wired and that incremental runs do not full-scan.

        Uses an empty source set so no real sessions are imported — fully
        hermetic, no dependency on ~/.claude.
        """
        db_path = self._make_db(tmp_path)  # inserts cli-test-session-001

        # --- Incremental run: nothing touched -> no notes written -----------
        inc_root = tmp_path / "inc"
        inc_root.mkdir()
        vault_inc = _make_vault(inc_root)
        _run_export(
            output_path=db_path,
            sources=set(),  # import nothing this run
            incremental=True,
            obsidian=True,
            obsidian_vault=vault_inc,
            obsidian_backfill=False,
        )
        assert self._count_notes(vault_inc) == 0, (
            "Incremental run wrote a note for an untouched session"
        )

        # --- Backfill run: the pre-existing session IS exported -------------
        bf_root = tmp_path / "bf"
        bf_root.mkdir()
        vault_bf = _make_vault(bf_root)
        _run_export(
            output_path=db_path,
            sources=set(),
            incremental=True,
            obsidian=True,
            obsidian_vault=vault_bf,
            obsidian_backfill=True,
        )
        assert self._count_notes(vault_bf) >= 1, (
            "Backfill run did not export the pre-existing session"
        )
