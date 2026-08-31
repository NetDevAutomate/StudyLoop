"""LIVE real-data tests for the struggle extractor — actual Bedrock + real sessions.

Why these exist: a mock encodes our *assumption* about how the model behaves.
When the assumption is wrong, the mock passes and production breaks. Tonight
``nova-lite`` passed every mock and the tiny probe, then raised
``ModelErrorException`` on a real transcript. These tests run the REAL
extractor against REAL kiro sessions from the live sessions.db, so that class
of failure surfaces here, not in production.

Gated by ``@pytest.mark.live_provider`` (excluded from the default run; opt in
with ``-m live_provider``). Skip cleanly when boto3 or AWS creds are absent, so
a machine without the bedrock extra / profile does not fail the suite.

Assertions are STRUCTURAL only (LLM output is non-deterministic at the string
level): valid ExtractorResult shape, valid confidence vocabulary, and the
negative-session invariant (a build session must yield zero rows once the real
pre_filter runs). We never assert exact topic strings.

Budget: 2-3 real Converse calls on the cheap default; < $0.10 per full run.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

from studyloop.extractors import VALID_CONFIDENCE, ExtractorResult
from studyloop.extractors.pipeline import pre_filter

pytestmark = pytest.mark.live_provider


def _required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        pytest.skip(f"{name} is required for opt-in live extractor evidence")
    return value


def _live_db() -> Path:
    path = Path(_required_env("STUDYLOOP_LIVE_SESSION_DB")).expanduser()
    if not path.is_file():
        pytest.skip("configured live session database does not exist")
    return path


def _real_client():
    """Build a real bedrock-runtime client, or skip if unavailable."""
    try:
        import boto3
    except ImportError:
        pytest.skip("boto3 not installed (need the [bedrock] extra) — skipping live test")
    try:
        session = boto3.Session()
        session.client("sts").get_caller_identity()
        return session.client("bedrock-runtime")
    except Exception as exc:
        pytest.skip(f"ambient AWS identity unavailable ({type(exc).__name__})")


def _fetch(db_path: Path, session_id: str) -> list[dict]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT role, content FROM messages WHERE session_id = ? ORDER BY seq",
            (session_id,),
        ).fetchall()
    finally:
        conn.close()
    if not rows:
        pytest.skip(f"session {session_id} not in live DB — skipping")
    return [{"role": r["role"], "content": r["content"]} for r in rows]


def _source(db_path: Path, session_id: str) -> str | None:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT source FROM sessions WHERE id = ?", (session_id,)).fetchone()
    finally:
        conn.close()
    return row["source"] if row else None


def test_real_study_session_yields_valid_results() -> None:
    """Extractor runs on a REAL kiro study transcript and returns valid shapes.

    This is the test nova-lite would have failed — a real transcript through the
    real Converse tool-use path. We assert structure, never exact topics.
    """
    from studyloop.extractors.llm import extract_struggles

    db_path = _live_db()
    session_id = _required_env("STUDYLOOP_LIVE_STUDY_SESSION_ID")
    model = _required_env("STUDYLOOP_LIVE_EXTRACTOR_MODEL")
    client = _real_client()
    messages = _fetch(db_path, session_id)
    results = extract_struggles(messages, session_id, model=model, client=client)

    # The extractor must not crash and must return a (possibly empty) list of
    # structurally-valid results.
    assert isinstance(results, list)
    for r in results:
        assert isinstance(r, ExtractorResult)
        r.validate()  # raises if topic/concept empty or confidence invalid
        assert r.confidence in VALID_CONFIDENCE
        assert r.topic == r.topic.strip().lower()

    # This particular session (type-hint syntax confusion) should surface at
    # least one signal — a smoke check that the extractor isn't silently empty
    # on a session a human labelled as a real struggle.
    assert results, "expected >=1 extraction from a known-struggle study session"


def test_real_negative_session_yields_zero_via_pipeline() -> None:
    """A real claude_code build session must produce ZERO rows through the pipeline.

    The non-negotiable false-positive gate, exercised end-to-end on real data:
    pre_filter rejects the non-kiro source, so the extractor is never called and
    nothing is written. No API spend on this test (filtered before the call).
    """
    from studyloop.extractors.llm import extract_struggles

    db_path = _live_db()
    session_id = _required_env("STUDYLOOP_LIVE_NEGATIVE_SESSION_ID")
    model = _required_env("STUDYLOOP_LIVE_EXTRACTOR_MODEL")
    messages = _fetch(db_path, session_id)
    source = _source(db_path, session_id)

    # Production path: pre_filter gates the extractor.
    if pre_filter(session_id, source, messages):
        # Should not happen for a claude_code session, but if it did, the
        # extractor output must still be empty — assert the stronger invariant.
        client = _real_client()
        results = extract_struggles(messages, session_id, model=model, client=client)
        assert results == [], f"negative session leaked {len(results)} rows"
    else:
        # Expected branch: filtered out, zero cost, zero rows.
        assert source != "kiro_cli"


def test_eval_run_survives_a_crashing_model() -> None:
    """A model that crashes on a real transcript must NOT kill the eval run.

    Regression for the real failure observed 2026-05-31: nova-lite raised
    ModelErrorException ('invalid sequence as part of ToolUse') on a real
    session, killing the whole run. The eval now isolates per-session errors.
    We reproduce with the ACTUAL crashing model, not a mock — the point is to
    assert against the real failure mode an unattended loop will hit.
    """
    from studyloop.extractors import eval_runner as ev

    db_path = _live_db()
    model = _required_env("STUDYLOOP_LIVE_CRASHING_MODEL")
    client = _real_client()

    metrics, _cost, scores = ev.run_eval("train", db_path=db_path, model=model, client=client)

    expected_n = len(ev._load(ev._SPLIT_PATH)["train"])
    assert len(scores) == expected_n, "run did not complete all sessions — isolation failed"
    # metrics are still computable even with one or more crashed sessions.
    assert "f1" in metrics
    # if any session errored, it is flagged (not silently dropped).
    for s in scores:
        if s.error is not None:
            assert "Exception" in s.error or "Error" in s.error


def test_real_extraction_returns_validated_normalised_keys() -> None:
    """A real current model returns only validated normalised topic keys."""
    from studyloop.extractors.llm import extract_struggles

    db_path = _live_db()
    session_id = _required_env("STUDYLOOP_LIVE_STUDY_SESSION_ID")
    model = _required_env("STUDYLOOP_LIVE_EXTRACTOR_MODEL")
    client = _real_client()
    messages = _fetch(db_path, session_id)

    results = extract_struggles(messages, session_id, model=model, client=client)
    assert all(result.topic == result.topic.strip().lower() for result in results)
    assert all(result.concept == result.concept.strip().lower() for result in results)
