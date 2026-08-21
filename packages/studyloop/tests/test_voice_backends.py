"""One validated vocabulary for ``tts.backend``, and an observable choice.

Before this module existed there were three disagreeing defaults for the same
config key (``speak.py`` "kokoro", ``doctor/voice.py`` "kokoro",
``learning/voice.py`` "openvox") and *no* validation anywhere — every call site
was a bare string compare, so a typo like ``backend: openvoxx`` silently fell
through to macOS ``say``. These tests pin the vocabulary, the single default,
and — the part that actually protects the learner — the fact that callers can
SEE which backend produced the audio.

``studyloop`` and ``agent_session_tools`` are independently publishable and must
not import each other, so the vocabulary is mirrored in both packages. The
parity tests here are what keep the mirrors honest; they are the only place the
two are allowed to meet.
"""

from __future__ import annotations

import pathlib
from typing import TYPE_CHECKING

import pytest

from studyloop.learning import voice as learning_voice
from studyloop.tts_backends import (
    DEFAULT_BACKEND,
    VALID_BACKENDS,
    UnknownBackendError,
    resolve_backend,
)

if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# The vocabulary itself
# ---------------------------------------------------------------------------


def test_valid_backends_are_the_documented_four() -> None:
    assert set(VALID_BACKENDS) == {"openvox", "kokoro", "qwen3", "macos"}


def test_default_backend_is_kokoro() -> None:
    """Terminal, CLI, and MCP voice default to the local Kokoro backend."""
    assert DEFAULT_BACKEND == "kokoro"
    assert DEFAULT_BACKEND in VALID_BACKENDS


@pytest.mark.parametrize("raw", ["openvox", " OpenVox ", "OPENVOX"])
def test_resolve_backend_normalises_case_and_whitespace(raw: str) -> None:
    assert resolve_backend(raw) == "openvox"


@pytest.mark.parametrize("raw", [None, "", "   ", 17, ["kokoro"]])
def test_resolve_backend_uses_default_when_unset(raw: object) -> None:
    assert resolve_backend(raw) == DEFAULT_BACKEND


def test_resolve_backend_honours_explicit_default() -> None:
    assert resolve_backend(None, default="macos") == "macos"


def test_resolve_backend_rejects_unknown_value() -> None:
    with pytest.raises(UnknownBackendError) as excinfo:
        resolve_backend("openvoxx")
    message = str(excinfo.value)
    assert "openvoxx" in message
    # The error must be actionable — list what IS allowed.
    for name in VALID_BACKENDS:
        assert name in message


def test_resolve_backend_rejects_unknown_explicit_default() -> None:
    """A bad default is a programming error, not a user typo — still loud."""
    with pytest.raises(UnknownBackendError):
        resolve_backend(None, default="espeak")


# ---------------------------------------------------------------------------
# Cross-package parity (the mirrors must not drift)
# ---------------------------------------------------------------------------


def test_agent_session_tools_mirrors_the_vocabulary() -> None:
    from agent_session_tools import tts_backends as ast_backends

    assert ast_backends.VALID_BACKENDS == VALID_BACKENDS
    assert ast_backends.DEFAULT_BACKEND == DEFAULT_BACKEND


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "",
        "  KOKORO ",
        "openvox",
        "qwen3",
        "macos",
    ],
)
def test_agent_session_tools_resolve_backend_agrees(raw: object) -> None:
    from agent_session_tools import tts_backends as ast_backends

    assert ast_backends.resolve_backend(raw) == resolve_backend(raw)


def test_agent_session_tools_resolve_backend_also_rejects_unknown() -> None:
    from agent_session_tools import tts_backends as ast_backends

    with pytest.raises(ValueError, match="openvoxx"):
        ast_backends.resolve_backend("openvoxx")


@pytest.mark.parametrize(
    "raw",
    [
        {"tts.backend": "openvox"},
        {"tts": {"backend": "kokoro"}, "tts.backend": "openvox"},
        {"tts": {"voice": "af_bella"}, "tts.backend": "openvox"},
        {"review.export.enabled": True},
        {"tts": "openvox", "tts.backend": "kokoro"},
        {"a.b.c": 1, "a": {"b": {"d": 2}}},
    ],
)
def test_dotted_key_expansion_is_identical_in_both_packages(raw: dict) -> None:
    """The two loaders parse the SAME config.yaml — they must agree on syntax.

    ``a7eabb6`` fixed dotted keys in ``studyloop.settings`` only and claimed it
    "fixes all 6 consumers at once". It missed ``agent_session_tools``, whose
    loader is independent by design. This test is the tripwire for the next
    time one side changes.
    """
    from agent_session_tools.config_loader import (
        _expand_dotted_keys as ast_expand,
    )
    from studyloop.settings import _expand_dotted_keys as sl_expand

    assert ast_expand(dict(raw)) == sl_expand(dict(raw))


# ---------------------------------------------------------------------------
# learning/voice.py — the chosen backend must be observable
# ---------------------------------------------------------------------------


def _fake_say(monkeypatch: pytest.MonkeyPatch, calls: list[list[str]]) -> None:
    monkeypatch.setattr(learning_voice.shutil, "which", lambda name: f"/usr/bin/{name}")

    def _run(args, **kwargs):
        calls.append(list(args))
        # `say -o <path>` writes the file; emulate that so the caller's
        # `output_path.exists()` check behaves like the real command.
        if "-o" in args:
            pathlib.Path(args[args.index("-o") + 1]).write_bytes(b"AIFFfake")
        return None

    monkeypatch.setattr(learning_voice.subprocess, "run", _run)


def test_file_export_default_backend_is_the_shared_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """learning/voice.py used to default to 'openvox' — disagreeing with
    speak.py, doctor/voice.py and the spec."""
    monkeypatch.setattr(learning_voice, "load_raw_config", dict)
    calls: list[list[str]] = []
    _fake_say(monkeypatch, calls)

    result = learning_voice.synthesize_text_to_file_result(
        "Win: decorators.", tmp_path / "recap.aiff"
    )

    assert result.requested == DEFAULT_BACKEND


def test_file_export_reports_the_macos_fallback_instead_of_hiding_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The old code returned a bare ``True`` here, so ``studyloop recap
    --audio-file`` reported success while writing Apple-voice audio."""
    monkeypatch.setattr(learning_voice, "load_raw_config", lambda: {"tts": {"backend": "kokoro"}})
    calls: list[list[str]] = []
    _fake_say(monkeypatch, calls)

    result = learning_voice.synthesize_text_to_file_result(
        "Win: decorators.", tmp_path / "recap.aiff"
    )

    assert result.ok is True
    assert result.requested == "kokoro"
    assert result.backend == "macos"
    assert result.degraded is True
    assert calls and calls[0][0] == "/usr/bin/say"


def test_file_export_reports_openvox_when_openvox_produced_the_audio(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(learning_voice, "load_raw_config", lambda: {"tts": {"backend": "openvox"}})
    monkeypatch.setattr(learning_voice, "_write_openvox_audio", lambda text, path, cfg: True)

    result = learning_voice.synthesize_text_to_file_result(
        "Win: decorators.", tmp_path / "recap.wav"
    )

    assert result.ok is True
    assert result.backend == "openvox"
    assert result.degraded is False


def test_file_export_rejects_an_invalid_configured_backend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(learning_voice, "load_raw_config", lambda: {"tts": {"backend": "openvoxx"}})

    result = learning_voice.synthesize_text_to_file_result(
        "Win: decorators.", tmp_path / "recap.wav"
    )

    assert result.ok is False
    assert result.backend == ""
    assert "openvoxx" in result.detail


def test_synthesize_text_to_file_keeps_the_boolean_api(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(learning_voice, "load_raw_config", lambda: {"tts": {"backend": "openvox"}})
    monkeypatch.setattr(learning_voice, "_write_openvox_audio", lambda text, path, cfg: True)

    assert learning_voice.synthesize_text_to_file("hi", tmp_path / "r.wav") is True


# ---------------------------------------------------------------------------
# speak_text — the study-speak subprocess must report what it actually used
# ---------------------------------------------------------------------------


class _CompletedProcess:
    def __init__(self, returncode: int = 0, stderr: bytes = b"") -> None:
        self.returncode = returncode
        self.stderr = stderr
        self.stdout = b""


def test_speak_text_result_reads_the_backend_marker_from_study_speak(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(learning_voice, "_study_speak_path", lambda: "/bin/study-speak")
    monkeypatch.setattr(learning_voice, "load_raw_config", lambda: {"tts": {"backend": "openvox"}})
    monkeypatch.setattr(
        learning_voice.subprocess,
        "run",
        lambda *a, **k: _CompletedProcess(stderr=b"some noise\nstudy-speak: backend=macos\n"),
    )

    result = learning_voice.speak_text_result("Hello")

    assert result.ok is True
    assert result.requested == "openvox"
    assert result.backend == "macos"
    assert result.degraded is True


def test_speak_text_result_is_not_degraded_when_the_marker_matches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(learning_voice, "_study_speak_path", lambda: "/bin/study-speak")
    monkeypatch.setattr(learning_voice, "load_raw_config", lambda: {"tts": {"backend": "openvox"}})
    monkeypatch.setattr(
        learning_voice.subprocess,
        "run",
        lambda *a, **k: _CompletedProcess(stderr=b"study-speak: backend=openvox\n"),
    )

    result = learning_voice.speak_text_result("Hello")

    assert result.backend == "openvox"
    assert result.degraded is False


def test_speak_text_keeps_the_boolean_api(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(learning_voice, "_study_speak_path", lambda: "/bin/study-speak")
    monkeypatch.setattr(learning_voice, "load_raw_config", dict)
    monkeypatch.setattr(
        learning_voice.subprocess,
        "run",
        lambda *a, **k: _CompletedProcess(stderr=b"study-speak: backend=kokoro\n"),
    )

    assert learning_voice.speak_text("Hello") is True


# ---------------------------------------------------------------------------
# The user-visible end of the wire: `studyloop recap today`
# ---------------------------------------------------------------------------


def _stub_recap(monkeypatch: pytest.MonkeyPatch) -> None:
    from studyloop.cli import _recap as recap_cli

    class _Recap:
        win = "w"
        repair_target = "r"
        due_item = "d"
        next_action = "n"

        def speakable_text(self) -> str:
            return "Win: decorators."

        def to_json_dict(self) -> dict:
            return {}

    monkeypatch.setattr(recap_cli, "build_daily_recap", _Recap)


def test_recap_speak_names_the_backend_when_it_degrades(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`studyloop recap --speak` must never produce Apple audio silently."""
    from click.testing import CliRunner

    from studyloop.cli import _recap as recap_cli

    _stub_recap(monkeypatch)
    monkeypatch.setattr(
        recap_cli,
        "speak_text_result",
        lambda text: learning_voice.VoiceResult(
            ok=True, backend="macos", requested="openvox", detail=""
        ),
    )

    result = CliRunner().invoke(recap_cli.recap_group, ["today", "--speak"])

    assert result.exit_code == 0
    assert "macos" in result.output
    assert "openvox" in result.output


def test_recap_speak_is_quiet_when_the_configured_backend_was_used(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from click.testing import CliRunner

    from studyloop.cli import _recap as recap_cli

    _stub_recap(monkeypatch)
    monkeypatch.setattr(
        recap_cli,
        "speak_text_result",
        lambda text: learning_voice.VoiceResult(
            ok=True, backend="openvox", requested="openvox", detail=""
        ),
    )

    result = CliRunner().invoke(recap_cli.recap_group, ["today", "--speak"])

    assert result.exit_code == 0
    assert "instead of" not in result.output


def test_recap_audio_file_names_the_backend_when_it_degrades(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from click.testing import CliRunner

    from studyloop.cli import _recap as recap_cli

    _stub_recap(monkeypatch)
    target = tmp_path / "recap.aiff"
    monkeypatch.setattr(
        recap_cli,
        "synthesize_text_to_file_result",
        lambda text, path: learning_voice.VoiceResult(
            ok=True, backend="macos", requested="kokoro", detail=""
        ),
    )

    result = CliRunner().invoke(recap_cli.recap_group, ["today", "--audio-file", str(target)])

    assert result.exit_code == 0
    assert "macos" in result.output


# ---------------------------------------------------------------------------
# doctor — an invalid backend must be reported, not silently coerced
# ---------------------------------------------------------------------------


def test_doctor_flags_an_invalid_tts_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    from studyloop.doctor import voice as doctor_voice

    monkeypatch.setattr(doctor_voice, "load_raw_config", lambda: {"tts": {"backend": "openvoxx"}})

    results = doctor_voice.check_voice_readiness()
    by_name = {r.name: r for r in results}

    assert "backend" in by_name
    assert by_name["backend"].status == "fail"
    assert "openvoxx" in by_name["backend"].message


def test_doctor_reports_the_valid_backend_it_resolved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from studyloop.doctor import voice as doctor_voice

    monkeypatch.setattr(doctor_voice, "load_raw_config", lambda: {"tts": {"backend": "openvox"}})
    monkeypatch.setattr(doctor_voice, "_openvox_reachable", lambda base_url: True)

    by_name = {r.name: r for r in doctor_voice.check_voice_readiness()}

    assert by_name["backend"].status == "pass"
    assert "openvox" in by_name["backend"].message
