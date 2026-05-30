"""Tests for ``WS /api/content/generate/ws`` (U7).

Pairs the stub-driven REST endpoint with a WS client and asserts the
event stream shape, terminal-frame close, origin guard, and unknown-id
behaviour.

The TestClient's ``websocket_connect`` is synchronous and uses a real
ASGI handshake under the hood, so we exercise the production code path
end-to-end. We pre-load a queue or kick a real job depending on the
test -- both shapes are realistic.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402  # pyright: ignore[reportMissingImports]
from starlette.websockets import WebSocketDisconnect  # noqa: E402  # pyright: ignore[reportMissingImports]

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
def _clean_module_state():
    asyncio.run(active_gen.release())
    cg_route._JOB_QUEUES.clear()
    yield
    asyncio.run(active_gen.release())
    cg_route._JOB_QUEUES.clear()


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    # 3-level: Study/<publisher>/<course>/study-notes/<lesson>.md.
    study = tmp_path / "Study"
    notes = study / "DataCamp" / "Intro_To_Pandas" / "study-notes"
    notes.mkdir(parents=True)
    (notes / "joins.md").write_text("# Joins\n\nINNER, LEFT.", encoding="utf-8")
    return study


@pytest.fixture
def stub_settings(vault: Path, monkeypatch: MonkeyPatch):
    from studyloop.settings import CardGeneratorConfig, ContentConfig, Settings

    s = Settings()
    s.content = ContentConfig(base_path=vault)
    s.card_generator = CardGeneratorConfig(
        backend="stub", max_workers=2, stub_card_count=3
    )
    monkeypatch.setattr("studyloop.settings.load_settings", lambda: s)
    return s


@pytest.fixture
def client(stub_settings) -> TestClient:
    return TestClient(create_app(study_dirs=[]))


def _valid_body() -> dict:
    return {
        "publisher": "DataCamp",
        "course": "Intro_To_Pandas",
        "scope": {
            "kind": "section",
            "publisher": "DataCamp",
            "course": "Intro_To_Pandas",
            "section": "joins",
        },
        "kinds": ["flashcards"],
        "count_per_source": 5,
        "on_existing": "suffix",
        "backend": "stub",
    }


def _kick_job(client: TestClient) -> str:
    resp = client.post("/api/content/generate", json=_valid_body())
    assert resp.status_code == 202, resp.text
    return resp.json()["job_id"]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestStream:
    def test_streams_started_then_task_complete_then_all_done(
        self, client: TestClient
    ) -> None:
        """Happy-path frame sequence ends with ``all_done`` and a clean close."""
        job_id = _kick_job(client)
        with client.websocket_connect(
            f"/api/content/generate/ws?job_id={job_id}",
            headers={"origin": "http://127.0.0.1:8788"},
        ) as ws:
            frames: list[dict] = []
            for _ in range(10):
                frame = ws.receive_json()
                frames.append(frame)
                if frame["type"] == "all_done":
                    break

        types = [f["type"] for f in frames]
        assert types[0] == "started"
        assert "task_complete" in types
        assert types[-1] == "all_done"

        # Singleton released by the orchestrator's finally.
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            if asyncio.run(active_gen.current()) is None:
                break
            time.sleep(0.02)
        assert asyncio.run(active_gen.current()) is None

    def test_started_frame_includes_task_count_and_sources(
        self, client: TestClient
    ) -> None:
        job_id = _kick_job(client)
        with client.websocket_connect(
            f"/api/content/generate/ws?job_id={job_id}",
            headers={"origin": "http://127.0.0.1:8788"},
        ) as ws:
            started = ws.receive_json()

        assert started["type"] == "started"
        assert started["job_id"] == job_id
        assert started["task_count"] == 1
        assert started["sources"][0]["identifier"] == "joins"


class TestRouting:
    def test_unknown_job_id_closes_with_4404(self, client: TestClient) -> None:
        """No queue → close with the 'job not found' application code."""
        with pytest.raises(WebSocketDisconnect) as excinfo:
            with client.websocket_connect(
                "/api/content/generate/ws?job_id=gen-deadbeef",
                headers={"origin": "http://127.0.0.1:8788"},
            ) as ws:
                ws.receive_json()  # Should never arrive.
        assert excinfo.value.code == 4404

    def test_disallowed_origin_closes_with_1008(self, client: TestClient) -> None:
        # Pre-load a queue so the origin guard is the only thing that
        # can reject -- isolates the assertion.
        cg_route._JOB_QUEUES["gen-x"] = asyncio.Queue()
        with pytest.raises(WebSocketDisconnect) as excinfo:
            with client.websocket_connect(
                "/api/content/generate/ws?job_id=gen-x",
                headers={"origin": "http://evil.example.com"},
            ) as ws:
                ws.receive_json()
        assert excinfo.value.code == 1008


class TestTerminalFrames:
    def test_transport_error_frame_terminates_stream(self, client: TestClient) -> None:
        # Pre-load a queue with just a transport_error frame; the
        # handler should send it and close cleanly without waiting
        # for an all_done.
        queue: asyncio.Queue = asyncio.Queue()
        queue.put_nowait({"type": "transport_error", "message": "boom"})
        cg_route._JOB_QUEUES["gen-y"] = queue

        with client.websocket_connect(
            "/api/content/generate/ws?job_id=gen-y",
            headers={"origin": "http://127.0.0.1:8788"},
        ) as ws:
            frame = ws.receive_json()

        assert frame == {"type": "transport_error", "message": "boom"}
        # Queue dropped from the registry after the consumer exits.
        assert "gen-y" not in cg_route._JOB_QUEUES
