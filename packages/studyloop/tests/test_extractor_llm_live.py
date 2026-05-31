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

import sqlite3
from pathlib import Path

import pytest

from studyloop.extractors import VALID_CONFIDENCE, ExtractorResult
from studyloop.extractors.pipeline import pre_filter

pytestmark = pytest.mark.live_provider

_DB = Path.home() / ".config" / "studyloop" / "sessions.db"
_PROFILE = "arraafat+prod-user"
_REGION = "us-east-1"

# Real sessions, confirmed present in the live DB.
_STUDY_SESSION = "kiro_0b7a9687-2735-48f7-b287-31a0085dfd93"  # type-hints, 4 user turns, clean
_NEGATIVE_SESSION = "agent-a7ccf07"  # claude_code build subagent — must yield zero


def _real_client():
    """Build a real bedrock-runtime client, or skip if unavailable."""
    try:
        import boto3
    except ImportError:
        pytest.skip("boto3 not installed (need the [bedrock] extra) — skipping live test")
    try:
        session = boto3.Session(profile_name=_PROFILE)
        # STS keepalive: skip (don't fail) if creds are expired/missing.
        session.client("sts", region_name=_REGION).get_caller_identity()
        return session.client("bedrock-runtime", region_name=_REGION)
    except Exception as exc:  # noqa: BLE001 — any cred/profile failure → skip, not fail
        pytest.skip(f"AWS profile {_PROFILE!r} unavailable ({type(exc).__name__}) — skipping")


def _fetch(session_id: str) -> list[dict]:
    if not _DB.exists():
        pytest.skip(f"live sessions.db not found at {_DB}")
    conn = sqlite3.connect(_DB)
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


def _source(session_id: str) -> str | None:
    conn = sqlite3.connect(_DB)
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

    client = _real_client()
    messages = _fetch(_STUDY_SESSION)
    results = extract_struggles(messages, _STUDY_SESSION, client=client)

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

    messages = _fetch(_NEGATIVE_SESSION)
    source = _source(_NEGATIVE_SESSION)

    # Production path: pre_filter gates the extractor.
    if pre_filter(_NEGATIVE_SESSION, source, messages):
        # Should not happen for a claude_code session, but if it did, the
        # extractor output must still be empty — assert the stronger invariant.
        client = _real_client()
        results = extract_struggles(messages, _NEGATIVE_SESSION, client=client)
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

    client = _real_client()
    if not _DB.exists():
        pytest.skip(f"live sessions.db not found at {_DB}")

    # nova-lite is known to emit invalid ToolUse on some real transcripts.
    metrics, _cost, scores = ev.run_eval(
        "train", db_path=_DB, model="amazon.nova-lite-v1:0", client=client
    )

    expected_n = len(ev._load(ev._SPLIT_PATH)["train"])
    assert len(scores) == expected_n, "run did not complete all sessions — isolation failed"
    # metrics are still computable even with one or more crashed sessions.
    assert "f1" in metrics
    # if any session errored, it is flagged (not silently dropped).
    for s in scores:
        if s.error is not None:
            assert "Exception" in s.error or "Error" in s.error


def test_real_extraction_respects_temperature_zero_determinism() -> None:
    """Two real runs on the same session return the same normalised topic set.

    temperature=0 should make the (topic, concept) key set stable across runs.
    Tolerant by design: asserts set equality of normalised keys, not full
    object equality (notes/evidence quotes may vary).
    """
    from studyloop.extractors.llm import extract_struggles

    client = _real_client()
    messages = _fetch(_STUDY_SESSION)

    def keyset(rs: list[ExtractorResult]) -> set[tuple[str, str]]:
        return {(r.topic, r.concept) for r in rs}

    first = keyset(extract_struggles(messages, _STUDY_SESSION, client=client))
    second = keyset(extract_struggles(messages, _STUDY_SESSION, client=client))
    assert first == second, f"temperature=0 not stable: {first} vs {second}"
