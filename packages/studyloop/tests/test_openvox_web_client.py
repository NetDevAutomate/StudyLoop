"""Tests for the web-facing OpenVox client.

These must pass with NO OpenVox running, because CI has none -- every HTTP call
is stubbed. The behaviours asserted here were each measured against a live
OpenVox first, so the stubs mirror observed responses rather than assumed ones:

  * concurrent requests really do return an immediate 429 (two of three did)
  * the `language` field really is ignored (four different values returned
    byte-identical audio), so the VOICE is the only language control
  * a `zf_*` voice really is a working request, not a 404
"""

from __future__ import annotations

import urllib.error
from typing import Any

import pytest

from studyloop.learning import voice as learning_voice


class _FakeResponse:
    """Minimal stand-in for the urlopen context manager."""

    def __init__(self, body: bytes, status: int = 200) -> None:
        self._body = body
        self.status = status

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def read(self) -> bytes:
        return self._body


def _busy_error() -> urllib.error.HTTPError:
    return urllib.error.HTTPError("http://x", 429, "Too Many Requests", {}, None)  # type: ignore[arg-type]


@pytest.fixture(autouse=True)
def _no_real_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """Never read the developer's own config during these tests."""
    monkeypatch.setattr(learning_voice, "load_raw_config", dict)


class TestEnglishVoiceGuard:
    """The voice selects the language, so the voice is the only guard."""

    @pytest.mark.parametrize("voice", ["af_heart", "am_michael", "bf_emma", "bf_lily", "bm_george"])
    def test_english_voices_pass(self, voice: str) -> None:
        assert learning_voice.openvox_is_english_voice(voice)

    @pytest.mark.parametrize(
        "voice", ["zf_xiaobei", "zm_yunjian", "jf_alpha", "ef_dora", "ff_siwis", "hf_alpha"]
    )
    def test_other_languages_are_rejected(self, voice: str) -> None:
        """These are real voices in the same model -- valid requests that speak
        another language. Rejecting them here is the whole point."""
        assert not learning_voice.openvox_is_english_voice(voice)

    @pytest.mark.parametrize("value", ["", None, 42, "b", "bf", "xx_nobody"])
    def test_junk_is_rejected(self, value: object) -> None:
        assert not learning_voice.openvox_is_english_voice(value)


class TestSynthesisRefusesBeforeAnyRequest:
    def test_non_english_voice_never_reaches_the_network(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A refused voice must not produce audio AND must not call OpenVox --
        if the request went out it would succeed and speak Mandarin."""
        calls: list[Any] = []
        monkeypatch.setattr(
            learning_voice.urllib.request,
            "urlopen",
            lambda *a, **k: calls.append(a) or _FakeResponse(b"RIFFxxxx"),
        )
        audio, detail = learning_voice.synthesise_openvox_bytes("hello", voice="zf_xiaobei")
        assert audio is None
        assert "zf_xiaobei" in detail
        assert calls == [], "a rejected voice still hit the network"

    def test_empty_text_is_refused(self) -> None:
        audio, detail = learning_voice.synthesise_openvox_bytes("   ", voice="bf_emma")
        assert audio is None
        assert detail == "nothing to speak"


class TestBusyRetry:
    def test_retries_then_succeeds(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """OpenVox rejects concurrent work instantly; waiting is correct."""
        attempts = {"n": 0}

        def _urlopen(*_a: object, **_k: object) -> _FakeResponse:
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise _busy_error()
            return _FakeResponse(b"RIFFaudio")

        waits: list[float] = []
        monkeypatch.setattr(learning_voice.urllib.request, "urlopen", _urlopen)
        audio, detail = learning_voice.synthesise_openvox_bytes(
            "hello", voice="bf_emma", sleep=waits.append
        )
        assert audio == b"RIFFaudio"
        assert detail == ""
        assert attempts["n"] == 3
        assert len(waits) == 2, "should have waited once per rejection"
        assert waits[1] > waits[0], "backoff should grow"

    def test_gives_up_with_a_readable_reason(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _always_busy(*_a: object, **_k: object) -> None:
            raise _busy_error()

        monkeypatch.setattr(learning_voice.urllib.request, "urlopen", _always_busy)
        audio, detail = learning_voice.synthesise_openvox_bytes(
            "hello", voice="bf_emma", sleep=lambda _s: None
        )
        assert audio is None
        assert "busy" in detail.lower()

    def test_a_non_429_error_does_not_retry(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Retrying a 400 just delays the failure."""
        attempts = {"n": 0}

        def _bad_request(*_a: object, **_k: object) -> None:
            attempts["n"] += 1
            raise urllib.error.HTTPError("http://x", 400, "Bad", {}, None)  # type: ignore[arg-type]

        monkeypatch.setattr(learning_voice.urllib.request, "urlopen", _bad_request)
        audio, detail = learning_voice.synthesise_openvox_bytes(
            "hello", voice="bf_emma", sleep=lambda _s: None
        )
        assert audio is None
        assert "400" in detail
        assert attempts["n"] == 1


class TestHealthIsHonest:
    def test_unreachable_says_where(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _down(*_a: object, **_k: object) -> None:
            raise urllib.error.URLError("connection refused")

        monkeypatch.setattr(learning_voice.urllib.request, "urlopen", _down)
        health = learning_voice.openvox_health()
        assert not health.reachable
        assert "not answering" in health.detail
        assert health.voice_count == 0

    def test_running_but_missing_model_is_not_reachable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A server answering with the wrong models is a different failure from
        a server that is down, and the learner-facing text must say so."""
        monkeypatch.setattr(
            learning_voice.urllib.request,
            "urlopen",
            lambda *a, **k: _FakeResponse(b'{"data":[{"id":"pocket-tts"}]}'),
        )
        health = learning_voice.openvox_health()
        assert not health.reachable
        assert "does not serve" in health.detail

    def test_warm_failure_is_not_fatal(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _down(*_a: object, **_k: object) -> None:
            raise urllib.error.URLError("nope")

        monkeypatch.setattr(learning_voice.urllib.request, "urlopen", _down)
        assert learning_voice.openvox_warm() is False


class TestEnvOverride:
    """Repointing the backend must not require editing config.yaml.

    Swapping between OpenVox, VoiceMode's Kokoro and a container is a URL change,
    so it should be a one-command change -- that is the whole reason the client is
    backend-agnostic.
    """

    def test_env_repoints_the_base_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(learning_voice, "_tts_config", lambda: {})
        monkeypatch.setenv("STUDYLOOP_TTS_BASE_URL", "http://127.0.0.1:8881/v1")
        monkeypatch.setenv("STUDYLOOP_TTS_VOICE", "bf_lily")
        monkeypatch.setenv("STUDYLOOP_TTS_MODEL", "tts-1")
        settings = learning_voice._openvox_settings()
        assert settings["base_url"] == "http://127.0.0.1:8881/v1"
        assert settings["voice"] == "bf_lily"
        assert settings["model"] == "tts-1"

    def test_env_beats_the_config_file(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            learning_voice,
            "_tts_config",
            lambda: {"openvox_base_url": "http://127.0.0.1:8000/v1"},
        )
        monkeypatch.setenv("STUDYLOOP_TTS_BASE_URL", "http://127.0.0.1:8880/v1")
        assert learning_voice._openvox_settings()["base_url"] == "http://127.0.0.1:8880/v1"

    def test_env_never_overrides_an_explicit_cfg(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A caller that named its endpoint must not be silently repointed.

        This is the hazard that makes env-over-everything wrong: a variable left
        in a shell (or a CI runner) would reach into a route or a test that had
        already chosen a specific server, and the failure would look like the
        server misbehaving rather than the environment leaking in.
        """
        monkeypatch.setenv("STUDYLOOP_TTS_BASE_URL", "http://127.0.0.1:9999/v1")
        settings = learning_voice._openvox_settings(
            cfg={"openvox_base_url": "http://127.0.0.1:8000/v1"}
        )
        assert settings["base_url"] == "http://127.0.0.1:8000/v1"

    def test_blank_env_is_ignored_not_treated_as_a_value(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An exported-but-empty var is the shell's idea of unset, not a URL."""
        monkeypatch.setattr(
            learning_voice,
            "_tts_config",
            lambda: {"openvox_base_url": "http://127.0.0.1:8000/v1"},
        )
        monkeypatch.setenv("STUDYLOOP_TTS_BASE_URL", "   ")
        assert learning_voice._openvox_settings()["base_url"] == "http://127.0.0.1:8000/v1"

    def test_server_candidates_default_to_primary_then_voicemode(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            learning_voice,
            "_tts_config",
            lambda: {"openvox_base_url": "http://127.0.0.1:8000/v1"},
        )

        candidates = learning_voice.openvox_server_configs()

        assert [(item["role"], item["base_url"]) for item in candidates] == [
            ("primary", "http://127.0.0.1:8000/v1"),
            ("VoiceMode fallback", "http://127.0.0.1:8880/v1"),
        ]

    def test_primary_voicemode_url_is_not_retried_as_its_own_fallback(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            learning_voice,
            "_tts_config",
            lambda: {"openvox_base_url": "http://127.0.0.1:8880/v1"},
        )

        assert len(learning_voice.openvox_server_configs()) == 1


class TestVoiceCatalogue:
    def test_falls_back_to_the_models_own_voices(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When no known listing path answers, assume the MODEL's voices.

        Changed deliberately from returning empty. Three Kokoro servers use three
        different listing URLs, so a 404 on all of them means "this server
        organises its catalogue differently", not "there are no voices" -- and an
        empty list made the browser refuse server speech outright even though
        synthesis worked. The ids ship with Kokoro-82M, so they belong to the
        model rather than to any server.
        """

        def _down(*_a: object, **_k: object) -> None:
            raise urllib.error.URLError("nope")

        monkeypatch.setattr(learning_voice.urllib.request, "urlopen", _down)
        voices = learning_voice.openvox_voices()
        assert "bf_emma" in voices
        assert "af_heart" in voices
        assert voices["bf_emma"] == "British English"
        assert all(v.startswith(("af_", "am_", "bf_", "bm_")) for v in voices), (
            "the fallback must offer English voices only"
        )

    def test_parses_the_openvox_shape(self, monkeypatch: pytest.MonkeyPatch) -> None:
        body = (
            b'{"data":[{"id":"bf_emma","language":"British English"},'
            b'{"id":"af_heart","language":"US English"},{"no_id":true}]}'
        )
        monkeypatch.setattr(
            learning_voice.urllib.request, "urlopen", lambda *a, **k: _FakeResponse(body)
        )
        voices = learning_voice.openvox_voices()
        assert voices == {"bf_emma": "British English", "af_heart": "US English"}

    def test_parses_the_kokoro_fastapi_shape(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Kokoro-FastAPI returns bare id strings under a different key.

        Verified against a live server on port 8880: it 404s both other paths and
        answers /audio/voices with {"voices": ["af_heart", ...]}.
        """
        calls: list[str] = []

        def _urlopen(request: object, **_k: object):
            url = getattr(request, "full_url", "")
            calls.append(url)
            if url.endswith("/audio/voices"):
                return _FakeResponse(b'{"voices":["af_heart","bf_emma","bm_george"]}')
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)  # type: ignore[arg-type]

        monkeypatch.setattr(learning_voice.urllib.request, "urlopen", _urlopen)
        voices = learning_voice.openvox_voices()
        assert set(voices) == {"af_heart", "bf_emma", "bm_george"}
        # Language is derived from the prefix, since this shape carries no language.
        assert voices["bf_emma"] == "British English"
        assert voices["af_heart"] == ""
        assert any("/models/kokoro/voices" in c for c in calls), "OpenVox path tried first"

    def test_a_404_on_one_path_does_not_stop_the_search(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The first path 404ing must not be read as "no voices"."""
        attempts = {"n": 0}

        def _urlopen(request: object, **_k: object):
            attempts["n"] += 1
            url = getattr(request, "full_url", "")
            if attempts["n"] < 3:
                raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)  # type: ignore[arg-type]
            return _FakeResponse(b'{"voices":["bf_lily"]}')

        monkeypatch.setattr(learning_voice.urllib.request, "urlopen", _urlopen)
        assert set(learning_voice.openvox_voices()) == {"bf_lily"}
        assert attempts["n"] == 3
