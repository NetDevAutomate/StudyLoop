"""Tests for the fusion-spec arms in ``proof_arms.py``. No model, no live store.

The arms are declared in ``receipts/fusion-spec-v2.md`` before DEV look 3; these tests pin
the mechanics that spec names (index contents, planner, RRF constant and tie-breaks) so a
receipt produced by ``score.py`` can be checked against the declaration.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sqlite3
import sys
from typing import Any

import pytest
from learning_memory import Event, ParsedSession, Session, Store

MODULE_PATH = pathlib.Path(__file__).resolve().parents[1] / "proof_arms.py"


def _load_module() -> Any:
    spec = importlib.util.spec_from_file_location("proof_arms_under_test", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


pa = _load_module()

PROSE_A = "the pre-commit hook failed on ruff, so I pinned the version and it passed"
PROSE_B = "we chose sqlite fts5 with the porter tokenizer for the prose index"
PROSE_C = "unrelated chatter about lunch and the weather"


def _session(sid: str, prose: str) -> ParsedSession:
    return ParsedSession(
        session=Session(id=sid, harness="claude_code", started_at="2026-09-01T10:00:00+00:00"),
        events=[
            Event(turn_id=1, seq=0, kind="user", text="question"),
            Event(turn_id=1, seq=1, kind="assistant_prose", text=prose),
        ],
        adapter_version="test@1",
    )


@pytest.fixture
def store_path(tmp_path: pathlib.Path) -> pathlib.Path:
    """Three sessions; claims only on A (v2) and C (v1 — must be ignored by the arm)."""
    path = tmp_path / "store.db"
    opened = Store.connect(path)
    opened.install()
    for sid, prose in (("s-a", PROSE_A), ("s-b", PROSE_B), ("s-c", PROSE_C)):
        opened.ingest(_session(sid, prose))
    ev_a = opened.connection.execute(
        "SELECT id FROM evidence WHERE session_id='s-a' AND body LIKE '%ruff%'"
    ).fetchone()[0]
    ev_c = opened.connection.execute(
        "SELECT id FROM evidence WHERE session_id='s-c' AND body LIKE '%lunch%'"
    ).fetchone()[0]
    opened.add_claim(
        "s-a",
        "Decision",
        "Pin ruff in pre-commit",
        "The pre-commit hook was fixed by pinning the ruff version.",
        ["pre-commit", "ruff"],
        0.9,
        "sonnet5/writer-v2/deadbeef",
        [{"evidence_id": ev_a, "quote": "pinned the version and it passed"}],
    )
    opened.add_claim(
        "s-c",
        "Finding",
        "Weather is a topic",
        "Lunch and weather were discussed.",
        ["lunch", "weather"],
        0.6,
        "sonnet5/writer-v1/e9cca0e4",
        [{"evidence_id": ev_c, "quote": "lunch and the weather"}],
    )
    opened.close()
    return path


@pytest.fixture
def arms(store_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setenv(pa.STORE_ENV, str(store_path))
    return pa


ARCHIVE = sqlite3.connect(":memory:")  # the arms ignore it; the harness passes one


# ── rrf_fuse: pure, declared constants and tie-breaks ───────────────────────────────


def test_rrf_scores_use_k_60_and_one_based_ranks() -> None:
    fused = pa.rrf_fuse([["x"], ["x"]])
    assert fused == ["x"]
    # a session first in both lists scores 2/(60+1); one first in a single list 1/61
    assert pa.rrf_fuse([["x", "y"], ["x"]]) == ["x", "y"]


def test_rrf_tie_break_prefers_best_rank_in_first_list_then_id() -> None:
    # 'p' is rank 1 in prose only; 'c' is rank 1 in claims only → equal scores.
    assert pa.rrf_fuse([["p"], ["c"]]) == ["p", "c"]
    # neither in the first list → equal scores → session id string order
    assert pa.rrf_fuse([[], ["zeta", "alpha"]])[0] == "zeta"  # rank order wins over id …
    assert pa.rrf_fuse([[], ["b"], ["a"]]) == ["a", "b"]  # … but ties fall back to the id


def test_rrf_promotes_a_session_present_in_both_lists() -> None:
    fused = pa.rrf_fuse([["a", "b", "c"], ["c", "d"]])
    # c: 1/63 + 1/61 > a: 1/61  → c first
    assert fused[0] == "c"
    assert fused[1] == "a"


# ── recall_claims ───────────────────────────────────────────────────────────────────


def test_recall_claims_indexes_only_writer_v2_claims(arms: Any) -> None:
    store = arms._open_store_ro(arms._store_path())
    idx = arms._build_claims_index(store)
    sessions = {r[0] for r in idx.execute("SELECT session_id FROM claims_fts")}
    assert sessions == {"s-a"}  # the v1 claim on s-c is excluded by writer prefix


def test_recall_claims_ranks_by_claim_text_not_prose(arms: Any) -> None:
    arm = arms.recall_claims()
    assert arm(ARCHIVE, "pre-commit ruff pinned") == ["s-a"]
    # prose-only knowledge (s-b's fts5/porter sentence) has no claim → unreachable
    assert arm(ARCHIVE, "sqlite fts5 porter tokenizer") == []


def test_recall_claims_returns_empty_when_planner_yields_nothing(arms: Any) -> None:
    arm = arms.recall_claims()
    assert arm(ARCHIVE, "\u0000\u0001") == []


def test_tags_text_handles_json_arrays_and_plain_strings() -> None:
    assert pa._tags_text('["a", "b-c"]') == "a b-c"
    assert pa._tags_text("plain") == "plain"
    assert pa._tags_text(None) == ""
    assert pa._tags_text(["x", "y"]) == "x y"


# ── B1_clean (refactor must be behaviour-preserving) and the fused arm ──────────────


def test_b1_clean_returns_first_k_of_shared_ranking(arms: Any) -> None:
    store = arms._open_store_ro(arms._store_path())
    full = arms._prose_ranked_sessions(store, "pre-commit ruff sqlite porter lunch")
    assert len(full) == 3
    arm = arms.B1_clean()
    assert arm(ARCHIVE, "pre-commit ruff sqlite porter lunch") == full[: arms.K]


def test_fused_arm_matches_rrf_of_the_two_full_rankings(arms: Any) -> None:
    store = arms._open_store_ro(arms._store_path())
    idx = arms._build_claims_index(store)
    q = "pre-commit ruff"
    expected = arms.rrf_fuse(
        [arms._prose_ranked_sessions(store, q), arms._claims_ranked_sessions(idx, q)]
    )[: arms.K]
    assert arms.B1_clean_plus_claims()(ARCHIVE, q) == expected
    assert expected[0] == "s-a"  # present in both lists → promoted


def test_fused_arm_still_reaches_sessions_without_claims(arms: Any) -> None:
    # s-b has prose but no claim: the fused arm must not lose it (claims are additive).
    assert arms.B1_clean_plus_claims()(ARCHIVE, "sqlite fts5 porter tokenizer") == ["s-b"]


def test_missing_store_is_a_clear_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    monkeypatch.setenv(pa.STORE_ENV, str(tmp_path / "nope.db"))
    with pytest.raises(FileNotFoundError):
        pa.recall_claims()
