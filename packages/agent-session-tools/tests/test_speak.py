"""Tests for speak module -- mocked subprocess and filesystem checks."""

from unittest.mock import patch

import agent_session_tools.speak as speak_mod
from agent_session_tools.speak import _ensure_kokoro_models, _speak_macos


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
