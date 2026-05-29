"""Tests for ``POST /api/content/generate`` (U5).

The REST handler resolves scope synchronously, acquires the
active-generation singleton, and spawns the orchestrator on a
background task. We exercise:

- 202 + plan summary on the happy path (stub backend).
- 400/404 on ill-formed / empty scopes.
- 409 on a second concurrent request.
- Singleton released after the spawned task completes.

The stub backend is deterministic, offline, and free, so these tests
run in milliseconds and don't touch any provider keys.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402  # pyright: ignore[reportMissingImports]

from studyloop.content import active_gen  # noqa: E402
from studyloop.web.app import create_app  # noqa: E402
from studyloop.web.routes import content_gen as cg_route  # noqa: E402

if TYPE_CHECKING:
    from pathlib import Path

    from pytest import MonkeyPatch


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _release_singleton_and_queues():
    """Module state for both the singleton and the queue map must be clean."""
    asyncio.run(active_gen.release())
    cg_route._JOB_QUEUES.clear()
    yield
    asyncio.run(active_gen.release())
    cg_route._JOB_QUEUES.clear()


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    """Tiny on-disk Study/<course>/<section>/<file.md> tree."""
    study = tmp_path / "Study"
    course = study / "DataCamp"
    (course / "advanced-pandas").mkdir(parents=True)
    (course / "advanced-pandas" / "ch1.md").write_text(
        "# Pandas\n\nGroupby.", encoding="utf-8"
    )
    (course / "joins").mkdir()
    (course / "joins" / "intro.md").write_text(
        "# Joins\n\nINNER, LEFT.", encoding="utf-8"
    )
    return study


@pytest.fixture
def stub_settings(vault: Path, monkeypatch: MonkeyPatch):
    """Patch ``load_settings`` so the route uses our tmp vault + stub backend."""
    from studyloop.settings import CardGeneratorConfig, ContentConfig, Settings

    s = Settings()
    s.content = ContentConfig(base_path=vault)
    s.card_generator = CardGeneratorConfig(
        backend="stub",
        max_workers=2,
        stub_card_count=3,
    )
    monkeypatch.setattr("studyloop.settings.load_settings", lambda: s)
    return s


@pytest.fixture
def client(stub_settings) -> TestClient:
    return TestClient(create_app(study_dirs=[]))


def _wait_for_job_done(timeout: float = 5.0) -> None:
    """Poll the singleton until the orchestrator releases it.

    The REST handler returns 202 immediately; the spawned task drains
    the orchestrator and then releases the singleton in a ``finally``.
    Tests that need to know "the job is done" poll instead of inserting
    fixed sleeps.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if asyncio.run(active_gen.current()) is None:
            return
        time.sleep(0.02)
    raise TimeoutError("job did not release singleton within deadline")


def _valid_body(course: str = "DataCamp", section: str = "joins") -> dict:
    return {
        "course": course,
        "scope": {"kind": "section", "course": course, "section": section},
        "kinds": ["flashcards"],
        "count_per_source": 5,
        "on_existing": "suffix",
        "backend": "stub",
    }


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestHappyPath:
    def test_returns_202_with_job_id_and_plan(self, client: TestClient) -> None:
        resp = client.post("/api/content/generate", json=_valid_body())
        assert resp.status_code == 202, resp.text
        data = resp.json()
        assert data["job_id"].startswith("gen-")
        assert data["plan"]["task_count"] == 1
        assert data["plan"]["kinds"] == ["flashcards"]
        assert data["plan"]["backend"] == "stub"
        assert len(data["plan"]["sources"]) == 1
        assert data["plan"]["sources"][0]["identifier"] == "joins"
        _wait_for_job_done()

    def test_course_scope_includes_all_sections_in_plan(self, client: TestClient) -> None:
        body = _valid_body()
        body["scope"] = {"kind": "course", "course": "DataCamp"}
        resp = client.post("/api/content/generate", json=body)
        assert resp.status_code == 202, resp.text
        identifiers = {s["identifier"] for s in resp.json()["plan"]["sources"]}
        assert identifiers == {"advanced-pandas", "joins"}
        _wait_for_job_done()


# ---------------------------------------------------------------------------
# Validation / error paths
# ---------------------------------------------------------------------------


class TestValidation:
    def test_missing_course_dir_returns_400_or_404(self, client: TestClient) -> None:
        body = _valid_body(course="NotARealCourse")
        body["scope"]["course"] = "NotARealCourse"
        resp = client.post("/api/content/generate", json=body)
        # The resolver says "Course directory not found" — either bucket
        # is acceptable; we settled on 404 for "not found".
        assert resp.status_code == 404, resp.text
        assert "not found" in resp.json()["detail"].lower()

    def test_section_scope_missing_section_returns_400(self, client: TestClient) -> None:
        body = _valid_body()
        body["scope"]["section"] = ""  # required when kind=section
        resp = client.post("/api/content/generate", json=body)
        assert resp.status_code == 400, resp.text

    def test_empty_kinds_rejected_at_validation(self, client: TestClient) -> None:
        body = _valid_body()
        body["kinds"] = []
        resp = client.post("/api/content/generate", json=body)
        # FastAPI returns 422 on pydantic constraint violations.
        assert resp.status_code == 422, resp.text


# ---------------------------------------------------------------------------
# Concurrency
# ---------------------------------------------------------------------------


class TestSingleton:
    def test_second_concurrent_request_returns_409(self, client: TestClient) -> None:
        # Hold the singleton manually so the second POST sees a busy
        # slot. This is the only way to get a deterministic 409 in a
        # TestClient (the stub job can finish before a second request
        # even arrives).
        asyncio.run(active_gen.acquire(job_id="gen-held", request=None))
        try:
            resp = client.post("/api/content/generate", json=_valid_body())
            assert resp.status_code == 409, resp.text
            assert "active" in resp.json()["detail"].lower()
        finally:
            asyncio.run(active_gen.release())

    def test_singleton_released_after_job_completes(self, client: TestClient) -> None:
        resp = client.post("/api/content/generate", json=_valid_body())
        assert resp.status_code == 202
        _wait_for_job_done()
        # A second POST must succeed — no 409.
        resp2 = client.post("/api/content/generate", json=_valid_body())
        assert resp2.status_code == 202
        _wait_for_job_done()
