"""Tests for the server-side TTS routes.

No OpenVox is required: the voice client is stubbed at the route's import site.
The behaviours pinned here are the ones a browser depends on to decide whether to
use server speech at all, plus the status codes that tell it to fall back rather
than treat the app as broken.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

pytest = __import__("pytest")
pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402  # pyright: ignore[reportMissingImports]

from studyloop.learning.voice import OpenVoxHealth  # noqa: E402
from studyloop.web.app import create_app  # noqa: E402
from studyloop.web.routes import tts as tts_route  # noqa: E402

if TYPE_CHECKING:
    from pytest import MonkeyPatch


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(study_dirs=[]))


class TestHealth:
    def test_uses_voicemode_fallback_when_primary_is_unreachable(
        self, client: TestClient, monkeypatch: MonkeyPatch
    ) -> None:
        candidates = (
            {"base_url": "http://127.0.0.1:8000/v1", "role": "primary"},
            {"base_url": "http://127.0.0.1:8880/v1", "role": "VoiceMode fallback"},
        )
        monkeypatch.setattr(tts_route, "openvox_server_configs", lambda: candidates)
        monkeypatch.setattr(
            tts_route,
            "openvox_health",
            lambda cfg: OpenVoxHealth(
                reachable=cfg["role"] == "VoiceMode fallback",
                model="kokoro",
                voice_count=1 if cfg["role"] == "VoiceMode fallback" else 0,
                detail="primary unavailable",
            ),
        )
        monkeypatch.setattr(tts_route, "openvox_voices", lambda cfg: {"bf_emma": "British"})

        body = client.get("/api/tts/health").json()

        assert body["available"] is True
        assert body["server"] == "VoiceMode fallback"
        assert [voice["id"] for voice in body["voices"]] == ["bf_emma"]

    def test_reports_available_with_english_voices_only(
        self, client: TestClient, monkeypatch: MonkeyPatch
    ) -> None:
        """The catalogue offered to the browser must never include a voice that
        would speak another language -- they are valid ids on the same model."""
        monkeypatch.setattr(
            tts_route,
            "openvox_health",
            lambda _cfg: OpenVoxHealth(reachable=True, model="kokoro", voice_count=54),
        )
        monkeypatch.setattr(
            tts_route,
            "openvox_voices",
            lambda _cfg: {
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

    def test_filters_a_real_servers_full_multilingual_catalogue(
        self, client: TestClient, monkeypatch: MonkeyPatch
    ) -> None:
        """The filter is load-bearing, not precautionary -- proved against a live server.

        VoiceMode's Kokoro on :8880 returns all 67 voices the model ships, across
        seven language families: Spanish (ef_/em_), French (ff_), Hindi (hf_/hm_),
        Italian (if_/im_), Japanese (jf_/jm_), Portuguese (pf_/pm_) and Mandarin
        (zf_/zm_). OpenVox on :8000 does not, which is why this went unnoticed:
        swapping the backend is what makes those ids reachable.

        This payload is that server's actual response, so the test fails if the
        allowlist is ever loosened into a denylist that only knows the two
        prefixes an earlier test happened to name.
        """
        real_catalogue = [
            # English -- must survive.
            "af_alloy",
            "af_aoede",
            "af_bella",
            "af_heart",
            "af_jessica",
            "af_kore",
            "af_nicole",
            "af_nova",
            "af_river",
            "af_sarah",
            "af_sky",
            "am_adam",
            "am_echo",
            "am_eric",
            "am_fenrir",
            "am_liam",
            "am_michael",
            "am_onyx",
            "am_puck",
            "am_santa",
            "bf_alice",
            "bf_emma",
            "bf_isabella",
            "bf_lily",
            "bm_daniel",
            "bm_fable",
            "bm_george",
            "bm_lewis",
            # Everything else -- must be dropped.
            "ef_dora",
            "em_alex",
            "em_santa",
            "ff_siwis",
            "hf_alpha",
            "hf_beta",
            "hm_omega",
            "hm_psi",
            "if_sara",
            "im_nicola",
            "jf_alpha",
            "jf_gongitsune",
            "jf_nezumi",
            "jf_tebukuro",
            "jm_kumo",
            "pf_dora",
            "pm_alex",
            "pm_santa",
            "zf_xiaobei",
            "zf_xiaoni",
            "zf_xiaoxiao",
            "zf_xiaoyi",
            "zm_yunjian",
            "zm_yunxi",
            "zm_yunxia",
            "zm_yunyang",
        ]
        monkeypatch.setattr(
            tts_route,
            "openvox_health",
            lambda _cfg: OpenVoxHealth(
                reachable=True, model="kokoro", voice_count=len(real_catalogue)
            ),
        )
        monkeypatch.setattr(
            tts_route, "openvox_voices", lambda _cfg: dict.fromkeys(real_catalogue, "")
        )
        offered = [v["id"] for v in client.get("/api/tts/health").json()["voices"]]
        assert offered, "the route must still offer the English voices"
        assert all(v.startswith(("af_", "am_", "bf_", "bm_")) for v in offered), (
            f"non-English voice offered to the browser: "
            f"{[v for v in offered if not v.startswith(('af_', 'am_', 'bf_', 'bm_'))]}"
        )
        # Every one of the seven other families must be gone, not just Mandarin.
        for prefix in (
            "ef_",
            "em_",
            "ff_",
            "hf_",
            "hm_",
            "if_",
            "im_",
            "jf_",
            "jm_",
            "pf_",
            "pm_",
            "zf_",
            "zm_",
        ):
            assert not any(v.startswith(prefix) for v in offered), f"{prefix} leaked"

    def test_marks_british_voices(self, client: TestClient, monkeypatch: MonkeyPatch) -> None:
        monkeypatch.setattr(
            tts_route,
            "openvox_health",
            lambda _cfg: OpenVoxHealth(reachable=True, model="kokoro", voice_count=2),
        )
        monkeypatch.setattr(
            tts_route,
            "openvox_voices",
            lambda _cfg: {"bf_emma": "British English", "af_heart": "US English"},
        )
        by_id = {v["id"]: v for v in client.get("/api/tts/health").json()["voices"]}
        assert by_id["bf_emma"]["british"] is True
        assert by_id["af_heart"]["british"] is False

    def test_unavailable_explains_why(self, client: TestClient, monkeypatch: MonkeyPatch) -> None:
        """A client that only learns 'false' cannot tell the learner what to fix."""
        monkeypatch.setattr(
            tts_route,
            "openvox_health",
            lambda _cfg: OpenVoxHealth(
                reachable=False, model="kokoro", voice_count=0, detail="OpenVox is not answering"
            ),
        )
        body = client.get("/api/tts/health").json()
        assert body["available"] is False
        assert "not answering" in body["detail"]
        assert body["voices"] == []


class TestSpeak:
    def test_retries_with_voicemode_when_primary_cannot_synthesise(
        self, client: TestClient, monkeypatch: MonkeyPatch
    ) -> None:
        candidates = (
            {"base_url": "http://127.0.0.1:8000/v1", "role": "primary"},
            {"base_url": "http://127.0.0.1:8880/v1", "role": "VoiceMode fallback"},
        )
        calls: list[str] = []
        monkeypatch.setattr(tts_route, "openvox_server_configs", lambda: candidates)

        def _synthesise(*_args, cfg: dict, **_kwargs):
            calls.append(cfg["role"])
            if cfg["role"] == "primary":
                return None, "primary refused the connection"
            return b"RIFFvoicemode-audio", ""

        monkeypatch.setattr(tts_route, "synthesise_openvox_bytes", _synthesise)

        response = client.post("/api/tts/speak", json={"text": "hello", "voice": "bf_emma"})

        assert response.status_code == 200
        assert response.content == b"RIFFvoicemode-audio"
        assert calls == ["primary", "VoiceMode fallback"]

    def test_returns_audio_bytes_with_an_audio_mime_type(
        self, client: TestClient, monkeypatch: MonkeyPatch
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
        self, client: TestClient, monkeypatch: MonkeyPatch
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
        self, client: TestClient, monkeypatch: MonkeyPatch
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
    def test_warm_is_reported(self, client: TestClient, monkeypatch: MonkeyPatch) -> None:
        monkeypatch.setattr(tts_route, "openvox_warm", lambda _cfg: True)
        assert client.post("/api/tts/warm").json() == {"warmed": True}

    def test_warm_failure_is_not_an_error_response(
        self, client: TestClient, monkeypatch: MonkeyPatch
    ) -> None:
        """Failing to warm is not a reason to refuse to try speaking later."""
        monkeypatch.setattr(tts_route, "openvox_warm", lambda _cfg: False)
        response = client.post("/api/tts/warm")
        assert response.status_code == 200
        assert response.json() == {"warmed": False}
