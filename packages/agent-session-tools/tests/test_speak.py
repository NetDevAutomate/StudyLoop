"""Tests for speak module -- mocked subprocess and filesystem checks."""

import json
from pathlib import Path
from unittest.mock import patch

import agent_session_tools.speak as speak_mod
from agent_session_tools.speak import (
    _ensure_kokoro_models,
    _speak_macos,
    _speak_openvox,
)


class _FakeResponse:
    def __init__(self, data: bytes, *, status: int = 200):
        self.data = data
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _tb):
        return False

    def read(self) -> bytes:
        return self.data


class TestSpeakMacos:
    @patch("agent_session_tools.speak.subprocess.run")
    def test_calls_say_with_correct_args(self, mock_run):
        _speak_macos("Hello world", voice="Samantha")
        mock_run.assert_called_once_with(
            ["say", "-v", "Samantha", "Hello world"], check=True, timeout=60
        )

    @patch("agent_session_tools.speak.subprocess.run")
    def test_returns_true_on_success(self, mock_run):
        assert _speak_macos("test", voice="Alex") is True

    @patch(
        "agent_session_tools.speak.subprocess.run",
        side_effect=FileNotFoundError,
    )
    def test_returns_false_when_say_missing(self, _mock_run):
        assert _speak_macos("test", voice="Alex") is False


class TestEnsureKokoroModels:
    def test_returns_true_when_files_exist(self, tmp_path, monkeypatch):
        model = tmp_path / "kokoro-v1.0.onnx"
        voices = tmp_path / "voices-v1.0.bin"
        model.write_bytes(b"fake-model")
        voices.write_bytes(b"fake-voices")

        monkeypatch.setattr(speak_mod, "_KOKORO_MODEL", model)
        monkeypatch.setattr(speak_mod, "_KOKORO_VOICES", voices)

        assert _ensure_kokoro_models() is True

    def test_returns_false_when_model_missing(self, tmp_path, monkeypatch):
        model = tmp_path / "kokoro-v1.0.onnx"
        voices = tmp_path / "voices-v1.0.bin"
        voices.write_bytes(b"fake-voices")
        # model intentionally not created

        monkeypatch.setattr(speak_mod, "_KOKORO_MODEL", model)
        monkeypatch.setattr(speak_mod, "_KOKORO_VOICES", voices)
        monkeypatch.setattr(speak_mod, "_KOKORO_DIR", tmp_path)

        # wget will fail since it's a fake URL and we don't mock subprocess
        with patch(
            "agent_session_tools.speak.subprocess.run",
            side_effect=FileNotFoundError,
        ):
            assert _ensure_kokoro_models() is False


class TestSpeakOpenVox:
    def test_posts_to_openvox_and_plays_returned_audio(self, monkeypatch):
        played_paths: list[Path] = []

        def fake_run(args, *, check, timeout):
            played_paths.append(Path(args[1]))
            assert args[0] == "/usr/bin/afplay"
            assert check is True
            assert timeout == 72
            assert played_paths[-1].read_bytes() == b"RIFFfake-wav"

        monkeypatch.setattr(speak_mod.shutil, "which", lambda name: "/usr/bin/afplay")

        with (
            patch(
                "agent_session_tools.speak.urllib.request.urlopen",
                return_value=_FakeResponse(b"RIFFfake-wav"),
            ) as mock_urlopen,
            patch("agent_session_tools.speak.subprocess.run", side_effect=fake_run),
        ):
            result = _speak_openvox(
                "Explain LEFT JOINs",
                base_url="http://127.0.0.1:8000/v1/",
                model="kokoro",
                voice="af_bella",
                language="en",
                response_format="wav",
                timeout=12,
            )

        assert result is True
        request = mock_urlopen.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))
        assert request.full_url == "http://127.0.0.1:8000/v1/audio/speech"
        assert payload == {
            "model": "kokoro",
            "input": "Explain LEFT JOINs",
            "language": "en",
            "voice": "af_bella",
            "response_format": "wav",
        }
        assert played_paths
        assert not played_paths[0].exists()

    def test_returns_false_when_afplay_missing(self, monkeypatch):
        monkeypatch.setattr(speak_mod.shutil, "which", lambda name: None)

        with patch("agent_session_tools.speak.urllib.request.urlopen") as mock_urlopen:
            assert (
                _speak_openvox(
                    "Hello",
                    base_url="http://127.0.0.1:8000/v1",
                    model="kokoro",
                    voice="af_bella",
                    language="en",
                    response_format="wav",
                    timeout=1,
                )
                is False
            )

        mock_urlopen.assert_not_called()

    def test_returns_false_when_server_is_busy(self, monkeypatch):
        monkeypatch.setattr(speak_mod.shutil, "which", lambda name: "/usr/bin/afplay")

        with patch(
            "agent_session_tools.speak.urllib.request.urlopen",
            return_value=_FakeResponse(b"busy", status=429),
        ):
            assert (
                _speak_openvox(
                    "Hello",
                    base_url="http://127.0.0.1:8000/v1",
                    model="kokoro",
                    voice="af_bella",
                    language="en",
                    response_format="wav",
                    timeout=1,
                )
                is False
            )
