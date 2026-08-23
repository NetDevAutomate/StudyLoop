"""Tests for the server-side TTS routes.

No OpenVox is required: the voice client is stubbed at the route's import site.
The behaviours pinned here are the ones a browser depends on to decide whether to
use server speech at all, plus the status codes that tell it to fall back rather
than treat the app as broken.
"""

from __future__ import annotations

pytest = __import__("pytest")
pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402  # pyright: ignore[reportMissingImports]

from studyloop.learning.voice import OpenVoxHealth  # noqa: E402
from studyloop.web.app import create_app  # noqa: E402
from studyloop.web.routes import tts as tts_route  # noqa: E402


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(study_dirs=[]))


class TestHealth:
    def test_reports_available_with_english_voices_only(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The catalogue offered to the browser must never include a voice that
        would speak another language -- they are valid ids on the same model."""
        monkeypatch.setattr(
            tts_route,
            "openvox_health",
            lambda: OpenVoxHealth(reachable=True, model="kokoro", voice_count=54),
        )
        monkeypatch.setattr(
            tts_route,
            "openvox_voices",
            lambda: {
                "bf_emma": "British English",
                "af_heart": "US English",
                "zf_xiaobei": "Mandarin Chinese",
                "jf_alpha": "Japanese",
            },
        )
        body = client.get("/api/tts/health").json()
        assert body["available"] is True
        ids = [v["id"] for v in body["voices"]]
        assert ids == ["af_heart", "bf_emma"]
        assert "zf_xiaobei" not in ids
        assert "jf_alpha" not in ids

    def test_marks_british_voices(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            tts_route,
            "openvox_health",
            lambda: OpenVoxHealth(reachable=True, model="kokoro", voice_count=2),
        )
        monkeypatch.setattr(
            tts_route,
            "openvox_voices",
            lambda: {"bf_emma": "British English", "af_heart": "US English"},
        )
        by_id = {v["id"]: v for v in client.get("/api/tts/health").json()["voices"]}
        assert by_id["bf_emma"]["british"] is True
        assert by_id["af_heart"]["british"] is False

    def test_unavailable_explains_why(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A client that only learns 'false' cannot tell the learner what to fix."""
        monkeypatch.setattr(
            tts_route,
            "openvox_health",
            lambda: OpenVoxHealth(
                reachable=False, model="kokoro", voice_count=0, detail="OpenVox is not answering"
            ),
        )
        body = client.get("/api/tts/health").json()
        assert body["available"] is False
        assert "not answering" in body["detail"]
        assert body["voices"] == []


class TestSpeak:
    def test_returns_audio_bytes_with_an_audio_mime_type(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An <audio> element refuses to play without a real audio MIME type."""
        monkeypatch.setattr(
            tts_route, "synthesise_openvox_bytes", lambda *a, **k: (b"RIFFfake-audio", "")
        )
        response = client.post("/api/tts/speak", json={"text": "hello", "voice": "bf_emma"})
        assert response.status_code == 200
        assert response.headers["content-type"] == "audio/wav"
        assert response.content == b"RIFFfake-audio"

    def test_unavailable_is_503_so_the_client_falls_back(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """503 means 'try elsewhere'; 500 would mean 'this app is broken'."""
        monkeypatch.setattr(
            tts_route,
            "synthesise_openvox_bytes",
            lambda *a, **k: (None, "could not reach OpenVox"),
        )
        response = client.post("/api/tts/speak", json={"text": "hello"})
        assert response.status_code == 503
        assert "could not reach" in response.json()["detail"]

    def test_a_refused_voice_is_reported_not_spoken(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            tts_route,
            "synthesise_openvox_bytes",
            lambda *a, **k: (None, "refusing non-English voice 'zf_xiaobei'"),
        )
        response = client.post("/api/tts/speak", json={"text": "hi", "voice": "zf_xiaobei"})
        assert response.status_code == 503
        assert "zf_xiaobei" in response.json()["detail"]

    def test_unsupported_format_is_a_client_error(self, client: TestClient) -> None:
        response = client.post("/api/tts/speak", json={"text": "hi", "response_format": "aiff"})
        assert response.status_code == 400

    def test_empty_text_is_rejected_by_validation(self, client: TestClient) -> None:
        assert client.post("/api/tts/speak", json={"text": ""}).status_code == 422

    def test_absurdly_long_text_is_rejected(self, client: TestClient) -> None:
        """Bounded so one caller cannot ask the host to synthesise a novel."""
        assert client.post("/api/tts/speak", json={"text": "a" * 5000}).status_code == 422


class TestWarm:
    def test_warm_is_reported(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(tts_route, "openvox_warm", lambda: True)
        assert client.post("/api/tts/warm").json() == {"warmed": True}

    def test_warm_failure_is_not_an_error_response(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Failing to warm is not a reason to refuse to try speaking later."""
        monkeypatch.setattr(tts_route, "openvox_warm", lambda: False)
        response = client.post("/api/tts/warm")
        assert response.status_code == 200
        assert response.json() == {"warmed": False}
