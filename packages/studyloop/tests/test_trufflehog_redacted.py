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
    argv: list[str] | None = None,
    commits: dict[str, str] | None = None,
) -> tuple[int, str, list[list[str]]]:
    module = _load()
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(list(cmd))
        return subprocess.CompletedProcess(cmd, returncode, stdout, "")

    monkeypatch.setattr(module.shutil, "which", lambda _name: "/fake/bin/trufflehog")
    monkeypatch.setattr(module.subprocess, "run", fake_run)
    if commits is not None:
        # The refs a PR scan resolves, as `git rev-parse` would answer them here.
        monkeypatch.setattr(
            module, "_resolve_commit", lambda ref: commits.get(ref or ""), raising=False
        )
    code = module.main([] if argv is None else argv)
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


# --- Pull-request range scan (ARBITRATION-pass3 D6) --------------------------
#
# CI scans a pull request's own commits, base..head. The range comes from the
# PR event; when either end is missing or unresolvable the scan must refuse
# (exit 2), never fall back to `--since-commit=HEAD` (HEAD..HEAD in CI: nothing
# scanned, a silent pass) or to a whole-history walk.

BASE_SHA = "ba" * 20
HEAD_SHA = "cd" * 20
RANGE = {"main": BASE_SHA, BASE_SHA: BASE_SHA, "HEAD": HEAD_SHA, HEAD_SHA: HEAD_SHA}


@pytest.mark.parametrize(
    "argv",
    [
        pytest.param(["--base", "", "--head", HEAD_SHA], id="empty-base"),
        pytest.param(["--base", "0" * 40, "--head", HEAD_SHA], id="all-zero-base"),
        pytest.param(["--head", HEAD_SHA], id="no-base-flag"),
        pytest.param(["--base", "ef" * 20, "--head", HEAD_SHA], id="base-not-in-clone"),
        pytest.param(["--base=--all", "--head", HEAD_SHA], id="option-shaped-base"),
    ],
)
def test_pr_scan_missing_base_fails_closed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], argv: list[str]
) -> None:
    code, output, calls = _run(
        monkeypatch, capsys, stdout="", returncode=0, argv=argv, commits=RANGE
    )
    assert code == 2, "a PR scan with no usable base must fail, not pass"
    assert "base" in output
    assert calls == [], "nothing may be scanned in place of the missing range"


@pytest.mark.parametrize(
    "argv",
    [
        pytest.param(["--base", BASE_SHA, "--head", ""], id="empty-head"),
        pytest.param(["--base", BASE_SHA], id="no-head-flag"),
        pytest.param(["--base", BASE_SHA, "--head", BASE_SHA], id="empty-range"),
        pytest.param(["--history", "--base", BASE_SHA, "--head", HEAD_SHA], id="with-history"),
    ],
)
def test_pr_scan_unusable_range_fails_closed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], argv: list[str]
) -> None:
    code, _, calls = _run(monkeypatch, capsys, stdout="", returncode=0, argv=argv, commits=RANGE)
    assert code == 2
    assert calls == []


def test_pr_scan_scans_exactly_base_to_head(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    code, output, calls = _run(
        monkeypatch,
        capsys,
        stdout="",
        returncode=0,
        argv=["--base", "main", "--head", "HEAD"],
        commits=RANGE,
    )
    assert code == 0
    assert len(calls) == 1
    cmd = calls[0]
    assert f"--since-commit={BASE_SHA}" in cmd, "scan from the resolved base commit"
    assert f"--branch={HEAD_SHA}" in cmd, "to the resolved head commit"
    assert "--since-commit=HEAD" not in cmd
    assert "--fail" in cmd
    assert "--json" in cmd
    assert "trufflehog findings: 0" in output


def test_pr_scan_scanner_error_is_still_exit_2(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    code, _, _ = _run(
        monkeypatch,
        capsys,
        stdout="",
        returncode=1,
        argv=["--base", BASE_SHA, "--head", HEAD_SHA],
        commits=RANGE,
    )
    assert code == 2


def test_pr_scan_parsed_finding_is_exit_1_and_redacted(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    code, output, _ = _run(
        monkeypatch,
        capsys,
        stdout=_finding() + "\n",
        returncode=183,
        argv=["--base", BASE_SHA, "--head", HEAD_SHA],
        commits=RANGE,
    )
    assert code == 1
    assert "leak.txt:3" in output
    assert SENTINEL not in output


def test_check_range_validates_without_scanning(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """CI's guard step: the runner has no trufflehog binary, so the check must
    pass or fail on the range alone and never need the scanner."""
    module = _load()
    calls: list[list[str]] = []
    monkeypatch.setattr(module.shutil, "which", lambda _name: None)
    monkeypatch.setattr(module.subprocess, "run", lambda cmd, **_kw: calls.append(cmd))
    monkeypatch.setattr(module, "_resolve_commit", lambda ref: RANGE.get(ref or ""), raising=False)

    assert module.main(["--check-range", "--base", BASE_SHA, "--head", HEAD_SHA]) == 0
    assert BASE_SHA[:10] in capsys.readouterr().out
    assert module.main(["--check-range", "--base", "", "--head", HEAD_SHA]) == 2
    assert module.main(["--check-range"]) == 2
    assert calls == []


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=wrapper-test",
            "-c",
            "user.email=wrapper-test@example.invalid",
            "-c",
            "commit.gpgsign=false",
            *args,
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def test_resolve_commit_reads_the_repository_it_runs_in(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _git(tmp_path, "init", "-q")
    (tmp_path / "f").write_text("f", encoding="utf-8")
    _git(tmp_path, "add", "f")
    _git(tmp_path, "commit", "-q", "-m", "f")
    head = _git(tmp_path, "rev-parse", "HEAD")
    monkeypatch.chdir(tmp_path)
    module = _load()

    assert module._resolve_commit("HEAD") == head
    assert module._resolve_commit(head[:12]) == head, "a short SHA resolves to the full commit"
    assert module._resolve_commit("ef" * 20) is None
    assert module._resolve_commit("0" * 40) is None
    assert module._resolve_commit("") is None
    assert module._resolve_commit("--all") is None
