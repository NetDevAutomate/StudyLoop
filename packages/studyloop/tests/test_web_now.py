"""Tests for GET /api/now."""

from __future__ import annotations

pytest = __import__("pytest")
pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402  # pyright: ignore[reportMissingImports]

from studyloop.learning.decision import LearningRecommendation, NowPlan  # noqa: E402
from studyloop.web.app import create_app  # noqa: E402


def test_api_now_returns_decision_contract(monkeypatch) -> None:
    def fake_plan(**kwargs):
        rec = LearningRecommendation(
            concept="decorators",
            topic="python",
            reason="due",
            action_type="recall",
            estimated_minutes=10,
            source="study_progress:python:decorators",
            evidence_command='studyloop progress "decorators" -t "python" -c learning',
            score=100,
        )
        return NowPlan(
            energy=kwargs["energy"],
            time_minutes=kwargs["time_minutes"],
            modality=kwargs["modality"],
            interleave=kwargs["interleave"],
            generated_at="2026-01-01T00:00:00+00:00",
            primary=rec,
            alternates=[],
            interleave_ratio={},
        )

    monkeypatch.setattr("studyloop.web.routes.now.build_now_plan", fake_plan)
    client = TestClient(create_app(study_dirs=[]))

    resp = client.get("/api/now?energy=high&time=15&modality=visual&interleave=adaptive")

    assert resp.status_code == 200
    data = resp.json()
    assert data["primary"]["concept"] == "decorators"
    assert data["energy"] == "high"
    assert data["time_minutes"] == 15
