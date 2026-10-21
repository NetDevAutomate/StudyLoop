"""Contract tests for ``scripts/security/trufflehog_redacted.py``.

The wrapper is the commit gate's trufflehog layer and the only thing standing
between trufflehog's raw ``--json`` stream and a terminal or CI log. It must
never print a raw match, and it must never turn output it cannot read into a
clean result: an unrecognised line is a scanner-format change, not "no
secrets".

The finding shape below is the one trufflehog 3.99.2 writes (probed live on
2026-10-21 against a scratch repo with a planted, runtime-built token; only key
names were recorded). Values here are inert sentinels, not credentials.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from types import ModuleType

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "security" / "trufflehog_redacted.py"
SENTINEL = "SENTINEL-RAW-VALUE-7731"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("trufflehog_redacted", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _finding(**overrides: Any) -> str:
    item: dict[str, Any] = {
        "SourceMetadata": {
            "Data": {
                "Git": {
                    "commit": "ab" * 20,
                    "file": "leak.txt",
                    "line": 3,
                    "repository": "file://.",
                    "repository_local_path": ".",
                    "timestamp": "2026-10-21 18:22:07 +0100",
                }
            }
        },
        "SourceID": 1,
        "SourceType": 16,
        "SourceName": "trufflehog - git",
        "DetectorType": 8,
        "DetectorName": "Github",
        "DetectorDescription": "GitHub token",
        "DecoderName": "PLAIN",
        "Verified": False,
        "VerificationFromCache": False,
        "Raw": SENTINEL,
        "RawV2": SENTINEL,
        "Redacted": SENTINEL,
        "SecretParts": {"key": SENTINEL},
        "ExtraData": None,
        "StructuredData": None,
    }
    item.update(overrides)
    return json.dumps(item)


def _run(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *,
    stdout: str,
    returncode: int,
) -> tuple[int, str, list[list[str]]]:
    module = _load()
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(list(cmd))
        return subprocess.CompletedProcess(cmd, returncode, stdout, "")

    monkeypatch.setattr(module.shutil, "which", lambda _name: "/fake/bin/trufflehog")
    monkeypatch.setattr(module.subprocess, "run", fake_run)
    code = module.main([])
    captured = capsys.readouterr()
    return code, captured.out + captured.err, calls


def test_clean_scan_passes(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    code, output, _ = _run(monkeypatch, capsys, stdout="", returncode=0)
    assert code == 0
    assert "trufflehog findings: 0" in output


def test_real_shape_finding_fails_without_echoing_the_match(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    code, output, _ = _run(monkeypatch, capsys, stdout=_finding() + "\n", returncode=183)
    assert code == 1
    assert "Github" in output
    assert "leak.txt:3" in output
    assert SENTINEL not in output


@pytest.mark.parametrize(
    ("stdout", "returncode"),
    [
        pytest.param('{"DetectorName": "Github", "Raw": "' + SENTINEL, 0, id="truncated-json"),
        pytest.param(json.dumps({"detector_name": "Github", "Raw": SENTINEL}), 0, id="renamed-key"),
        pytest.param("5", 0, id="json-scalar"),
        pytest.param(json.dumps([SENTINEL]), 0, id="json-list"),
        pytest.param(f"Found unverified result {SENTINEL}", 0, id="plain-text"),
        pytest.param(_finding() + "\n{not json " + SENTINEL, 183, id="unparsed-beside-finding"),
        pytest.param("", 183, id="fail-code-but-nothing-parsed"),
    ],
)
def test_unrecognised_output_fails_closed_and_is_not_echoed(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    stdout: str,
    returncode: int,
) -> None:
    code, output, _ = _run(monkeypatch, capsys, stdout=stdout, returncode=returncode)
    assert code == 2, "output the wrapper cannot read must not pass, nor count as a plain 1"
    assert SENTINEL not in output, "an unreadable line may hold the raw secret"


def test_tool_error_without_findings_is_an_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    code, _, _ = _run(monkeypatch, capsys, stdout="", returncode=1)
    assert code == 2


def test_trufflehog_is_asked_to_signal_findings_in_its_exit_code(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """``--fail`` makes trufflehog exit 183 when it found anything, which gives
    the wrapper a second, parser-independent signal: 183 with no parsed row is
    a format change, never a clean scan."""
    _, _, calls = _run(monkeypatch, capsys, stdout="", returncode=0)
    assert len(calls) == 1
    assert "--fail" in calls[0]
    assert "--json" in calls[0]


def test_missing_metadata_still_counts_as_a_finding(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    code, output, _ = _run(
        monkeypatch, capsys, stdout=_finding(SourceMetadata="unexpected") + "\n", returncode=183
    )
    assert code == 1
    assert SENTINEL not in output
