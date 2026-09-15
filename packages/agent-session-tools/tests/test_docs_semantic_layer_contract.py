"""Doc-contract tests for the shipped embedding substrate and hybrid mode.

Session memory docs described schema 47 and framed the shipped v48 embedding
substrate (`message_embeddings`, chunked/hashed, plus a sqlite-vec sidecar) as
an unmerged research branch, documented two dead config keys
(`fts_weight`/`semantic_weight` -- RRF fusion in `retrieval.py` is unweighted)
and omitted the real `hybrid` gate, hid the shipped hybrid mode behind a
docstring that claimed `session_search`'s mode was always "lexical", and
repeated a stale "schema-30 candidate" warning across four files. Every check
below compares a SET derived from real code symbols against what a small
parser extracts from the doc, per the council's TEST SHAPE ruling (A20): no
line numbers, no copied prose, no full click-tree substring sweeps, and the
hybrid-mode proof never needs a real embedding model.
"""

from __future__ import annotations

import re
import sqlite3
from importlib.resources import files
from pathlib import Path

import pytest
import yaml

from agent_session_tools import config_loader, maintenance, query_sessions, retrieval
from agent_session_tools.migrations import migrate

REPO_ROOT = Path(__file__).resolve().parents[3]
DOCS_DIR = REPO_ROOT / "docs"
SESSION_MEMORY_MD = DOCS_DIR / "session-memory.md"
SETUP_GUIDE_MD = DOCS_DIR / "setup-guide.md"
CLI_REFERENCE_MD = DOCS_DIR / "cli-reference.md"
ARCH_README_MD = DOCS_DIR / "architecture" / "session-memory" / "README.md"
SEMANTIC_RECEIPTS_DIR = (
    DOCS_DIR / "architecture" / "session-memory" / "receipts" / "semantic-layer"
)
STAGE4_RECORD_MD = SEMANTIC_RECEIPTS_DIR / "stage4-record-2026-09-12.md"

#: This file's own repo-relative path -- it legitimately names every forbidden
#: token it checks for (in comments, identifiers and the grep patterns
#: themselves), so every git-grep-based check below excludes it explicitly
#: rather than tripping on itself.
_THIS_FILE = Path(__file__).resolve().relative_to(REPO_ROOT).as_posix()


# ---------------------------------------------------------------------------
# (a) W06: docs/session-memory.md's schema statement matches CURRENT_VERSION
# ---------------------------------------------------------------------------


def test_session_memory_doc_cites_current_schema_version() -> None:
    from agent_session_tools.migrations import CURRENT_VERSION

    text = SESSION_MEMORY_MD.read_text(encoding="utf-8")
    numbers = {int(n) for n in re.findall(r"schema (\d+)", text)}
    assert numbers == {CURRENT_VERSION}


def test_session_memory_doc_no_longer_frames_v48_as_unmerged() -> None:
    """The v48 substrate is mainline, not "an unmerged Phase 2 work" branch."""
    text = SESSION_MEMORY_MD.read_text(encoding="utf-8")
    assert "unmerged" not in text.lower()
    assert "message_embeddings" in text


# ---------------------------------------------------------------------------
# (b) W07: setup-guide.md's semantic_search yaml example vs DEFAULT_CONFIG
# ---------------------------------------------------------------------------


def _fenced_yaml_blocks(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    return re.findall(r"```yaml\n(.*?)```", text, re.DOTALL)


def _semantic_search_block_keys(path: Path) -> set[str]:
    for block in _fenced_yaml_blocks(path):
        parsed = yaml.safe_load(block)
        if isinstance(parsed, dict) and "semantic_search" in parsed:
            value = parsed["semantic_search"]
            assert isinstance(value, dict), "semantic_search block must be a mapping"
            return set(value.keys())
    raise AssertionError(
        f"no fenced yaml block in {path} defines a semantic_search: block"
    )


def test_setup_guide_semantic_search_keys_are_known_and_include_hybrid() -> None:
    doc_keys = _semantic_search_block_keys(SETUP_GUIDE_MD)
    real_keys = set(config_loader.DEFAULT_CONFIG["semantic_search"].keys())
    assert doc_keys <= real_keys, (
        f"doc keys {doc_keys - real_keys} aren't real config keys"
    )
    assert "hybrid" in doc_keys, "setup-guide.md must show the real hybrid on/off gate"


def test_dead_hybrid_weight_keys_are_gone_from_doc_and_default_config() -> None:
    doc_keys = _semantic_search_block_keys(SETUP_GUIDE_MD)
    real_keys = set(config_loader.DEFAULT_CONFIG["semantic_search"].keys())
    dead = {"fts_weight", "semantic_weight"}
    assert not (doc_keys & dead), (
        f"setup-guide.md still documents dead keys {doc_keys & dead}"
    )
    assert not (real_keys & dead), (
        f"config_loader.DEFAULT_CONFIG still carries dead keys {real_keys & dead}"
    )


def test_fts_weight_and_semantic_weight_have_no_reader_in_packages() -> None:
    """A7: RRF fusion in retrieval.py has no weights -- the keys are dead.

    If a future change makes some call site read either key again, this must
    fail loudly rather than let the doc silently drift back out of sync.
    """
    import subprocess

    result = subprocess.run(
        ["git", "grep", "-n", "-E", r"fts_weight|semantic_weight"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    hits = [
        line
        for line in result.stdout.splitlines()
        if line.split(":", 1)[0].endswith(".py") and not line.startswith(_THIS_FILE)
    ]
    assert not hits, f"fts_weight/semantic_weight still read somewhere: {hits}"


# ---------------------------------------------------------------------------
# (c) W07/W34 (bounded): cli-reference.md names every session-maint and
# session-query top-level command, and every top-level [project.scripts]
# console script for both packages.
# ---------------------------------------------------------------------------


def _typer_command_names(app) -> set[str]:
    import click
    from typer.main import get_command

    click_app = get_command(app)
    assert isinstance(click_app, click.Group)
    return set(click_app.commands.keys())


def test_cli_reference_names_every_session_maint_command() -> None:
    text = CLI_REFERENCE_MD.read_text(encoding="utf-8")
    for name in _typer_command_names(maintenance.app):
        assert name in text, f"docs/cli-reference.md is missing `session-maint {name}`"


def test_cli_reference_names_every_session_query_command() -> None:
    text = CLI_REFERENCE_MD.read_text(encoding="utf-8")
    for name in _typer_command_names(query_sessions.app):
        assert name in text, f"docs/cli-reference.md is missing `session-query {name}`"


def _project_scripts(pyproject: Path) -> set[str]:
    data = tomllib_load(pyproject)
    return set(data.get("project", {}).get("scripts", {}).keys())


def tomllib_load(path: Path) -> dict:
    import tomllib

    with path.open("rb") as fh:
        return tomllib.load(fh)


def test_cli_reference_names_every_console_script() -> None:
    text = CLI_REFERENCE_MD.read_text(encoding="utf-8")
    scripts = _project_scripts(
        REPO_ROOT / "packages" / "agent-session-tools" / "pyproject.toml"
    )
    scripts |= _project_scripts(REPO_ROOT / "packages" / "studyloop" / "pyproject.toml")
    # `studyloop` itself is documented at length elsewhere on the page under
    # its own heading; only assert the console-script *names* are present.
    missing = {name for name in scripts if name not in text}
    assert not missing, f"docs/cli-reference.md never names console script(s) {missing}"


# ---------------------------------------------------------------------------
# (d) W08: session_search's docstring documents both retrieval.MODES values
# ---------------------------------------------------------------------------


def _session_search_tool():
    from importlib import import_module

    pytest.importorskip("fastmcp")
    from agent_session_tools.mcp_server import mcp

    run_async = import_module(
        f"{__package__}._helpers" if __package__ else "_helpers"
    ).run_async

    tools = run_async(mcp._list_tools())
    by_name = {tool.name: tool.fn for tool in tools}  # type: ignore[attr-defined]
    return by_name["session_search"]


def test_session_search_docstring_documents_every_retrieval_mode() -> None:
    fn = _session_search_tool()
    doc = fn.__doc__ or ""
    for mode in retrieval.MODES:
        assert f'"{mode}"' in doc, (
            f"session_search docstring never mentions mode {mode!r}"
        )


# ---------------------------------------------------------------------------
# (e) W32: the stale "schema-30 candidate" warning is gone everywhere in scope
# ---------------------------------------------------------------------------


#: The exact scope named in the brief: agents/, packages/*/README.md,
#: packages/*/docs/, and MVP-RELEASE.md.
_SCHEMA_30_SCOPE = (
    "agents/",
    "docs/",
    "packages/agent-session-tools/README.md",
    "packages/agent-session-tools/docs/",
    "packages/studyloop/README.md",
    "MVP-RELEASE.md",
)


def test_no_schema_30_candidate_string_in_scope() -> None:
    import subprocess

    result = subprocess.run(
        ["git", "grep", "-i", "-l", "schema-30", "--", *_SCHEMA_30_SCOPE],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    hits = [line for line in result.stdout.splitlines() if line]
    assert not hits, f"'schema-30' still present in: {hits}"


# ---------------------------------------------------------------------------
# (f) A18: forbidden-token lock -- okf/ontolog only in the ADR-0011 allowlist
# ---------------------------------------------------------------------------

_OKF_ONTOLOG_ALLOWLIST = frozenset(
    {
        "packages/studyloop/src/studyloop/web/static/vendor/dev/js/ghostty-web-0.4.0.js",
        "packages/studyloop/tests/e2e/test_journey_new_user_first_plan.py",
    }
)


def test_okf_ontolog_tokens_only_in_adr0011_allowlist() -> None:
    import subprocess

    result = subprocess.run(
        ["git", "grep", "-i", "-l", "-E", "okf|ontolog", "--", "packages/"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    hits = {line for line in result.stdout.splitlines() if line}
    unexpected = hits - _OKF_ONTOLOG_ALLOWLIST - {_THIS_FILE}
    assert not unexpected, (
        f"okf/ontolog token(s) outside the ADR-0011 allowlist: {unexpected}"
    )


# ---------------------------------------------------------------------------
# (g) A21: hybrid mode is provable without a model
# ---------------------------------------------------------------------------


def _hybrid_db(tmp_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(tmp_path / "sessions.db")
    conn.row_factory = sqlite3.Row
    conn.executescript(files("agent_session_tools").joinpath("schema.sql").read_text())
    migrate(conn)
    conn.execute(
        "INSERT INTO sessions(id, source, updated_at) VALUES ('s-a', 'kiro_cli', '2026-09-01')"
    )
    conn.execute(
        "INSERT INTO messages(id, session_id, role, content, timestamp, seq) "
        "VALUES ('m-a', 's-a', 'assistant', 'a database decision was made here', '2026-09-01T10:00:00', 1)"
    )
    conn.commit()
    return conn


def test_hybrid_mode_without_a_model(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        retrieval,
        "_semantic_ranking",
        lambda conn, query, *, schema: ([], {"model": "stub", "dim": 0}, None),
    )
    conn = _hybrid_db(tmp_path)

    monkeypatch.setenv(retrieval.MODE_ENV, "hybrid")
    result = retrieval.search(conn, "database decision")
    assert result.status.mode == "hybrid"

    monkeypatch.delenv(retrieval.MODE_ENV, raising=False)
    result = retrieval.search(conn, "database decision")
    assert result.status.mode == "lexical"


# ---------------------------------------------------------------------------
# W33: docs/architecture/session-memory/README.md's `hybrid_search` reference
# ---------------------------------------------------------------------------


def test_arch_readme_does_not_reference_dead_hybrid_search_symbol() -> None:
    import subprocess

    result = subprocess.run(
        ["git", "grep", "-n", "hybrid_search", "--", "packages/"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    hits = [
        line for line in result.stdout.splitlines() if not line.startswith(_THIS_FILE)
    ]
    assert not hits, (
        f"hybrid_search symbol exists in packages/; update the addendum: {hits}"
    )

    text = ARCH_README_MD.read_text(encoding="utf-8")
    if "hybrid_search" in text:
        assert "resolve_mode" in text or "_fuse" in text, (
            "README.md references the dead `hybrid_search` symbol without the "
            "dated addendum pointing at retrieval.py's real fusion functions"
        )


# ---------------------------------------------------------------------------
# Lane A1 (council D-1/D-2): the mode-by-surface table names every surface
# retrieval.py actually knows about -- a SET comparison against the real
# enum, never a copied-prose check (TEST SHAPE ruling A20).
# ---------------------------------------------------------------------------


def _mode_table_surfaces(text: str) -> set[str]:
    """Every backticked surface slug in the "Surface | Default | ..." table."""
    lines = text.splitlines()
    header_ix = next(
        i for i, line in enumerate(lines) if line.strip().startswith("| Surface")
    )
    surfaces: set[str] = set()
    for line in lines[header_ix + 2 :]:
        if not line.strip().startswith("|"):
            break
        first_cell = line.split("|")[1]
        match = re.search(r"`([a-z]+)`", first_cell)
        if match:
            surfaces.add(match.group(1))
    return surfaces


def test_arch_readme_mode_table_names_every_surface() -> None:
    text = ARCH_README_MD.read_text(encoding="utf-8")
    assert _mode_table_surfaces(text) == set(retrieval.SURFACES)


def test_arch_readme_states_the_sealed_provisional_note() -> None:
    """Council D-4/O-2: the mcp/web hybrid default is provisional pending the
    owner's separate SEALED obligation -- the doc must say so, not just the
    lane's internal receipts."""
    text = ARCH_README_MD.read_text(encoding="utf-8")
    assert "provisional pending SEALED" in text


def _stage5_preregistration_names(text: str) -> set[str]:
    """Every ``stage5-preregistration-*.md`` filename a document names."""
    return set(re.findall(r"stage5-preregistration-[\w-]+\.md", text))


def test_stage4_record_has_a_successor_section_naming_the_stage5_preregistration() -> (
    None
):
    """Stage 4's own rule: reversing off-by-default is a NEW pre-registration,
    not an edit of that record (E-A6). The record must therefore point forward
    to the document that gates the flip, so a reader of the Stage 4 gate cannot
    miss that a successor supersedes its default."""
    text = STAGE4_RECORD_MD.read_text(encoding="utf-8")
    assert "## Successor" in text
    assert _stage5_preregistration_names(text), (
        "the successor section names no stage5-preregistration receipt"
    )


def test_the_readme_and_the_stage4_successor_cite_the_same_preregistration() -> None:
    """Cross-document consistency: two docs naming DIFFERENT pre-registration
    files means one of them is stale, and the gate a reader checks depends on
    which one they opened."""
    readme = _stage5_preregistration_names(ARCH_README_MD.read_text(encoding="utf-8"))
    stage4 = _stage5_preregistration_names(STAGE4_RECORD_MD.read_text(encoding="utf-8"))
    assert readme and stage4
    assert readme == stage4


def test_the_stage4_successor_refuses_to_reuse_the_146ms_number() -> None:
    """Council D-3: the resident-state gate must never reuse the 146 ms figure,
    which was measured with a cold per-invocation load in the cli-hybrid arm."""
    successor = STAGE4_RECORD_MD.read_text(encoding="utf-8").split("## Successor", 1)[1]
    assert "146 ms" in successor and "not reusable" in successor
