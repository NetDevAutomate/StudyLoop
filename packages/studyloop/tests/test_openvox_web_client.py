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


class TestVoiceCatalogue:
    def test_unreachable_returns_empty_not_an_exception(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Callers must read empty as 'cannot validate', never 'no voices'."""

        def _down(*_a: object, **_k: object) -> None:
            raise urllib.error.URLError("nope")

        monkeypatch.setattr(learning_voice.urllib.request, "urlopen", _down)
        assert learning_voice.openvox_voices() == {}

    def test_parses_id_and_language(self, monkeypatch: pytest.MonkeyPatch) -> None:
        body = (
            b'{"data":[{"id":"bf_emma","language":"British English"},'
            b'{"id":"af_heart","language":"US English"},{"no_id":true}]}'
        )
        monkeypatch.setattr(
            learning_voice.urllib.request, "urlopen", lambda *a, **k: _FakeResponse(body)
        )
        voices = learning_voice.openvox_voices()
        assert voices == {"bf_emma": "British English", "af_heart": "US English"}
