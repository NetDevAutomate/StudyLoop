"""The commit hook's trufflehog layer, run against the PINNED trufflehog release.

``test_trufflehog_redacted.py`` proves the wrapper with a fake scanner. These
tests run the real one -- the release ``.github/workflows/ci.yml`` pins for
the CI step (``version: <semver>@sha256:<digest>``) -- on a scratch repository
with a runtime-built, revoked-shape AWS key pair, and pin three things the
unit tests cannot:

1. **The hook fails on a revoked or fake key, and that depends on an upstream
   ordering quirk** (plan 4 item 5; ADR-0018, consequences). Under
   ``PRE_COMMIT=1`` -- which pre-commit sets for every hook run -- trufflehog
   means to narrow results to ``verified,unknown`` (``main.go``,
   ``isPreCommitHook``), which would drop the ``unverified`` state a dead key
   verifies to. At the pinned release that override runs after ``--results``
   was parsed into the engine, so the wrapper's
   ``--results=verified,unknown,unverified`` stands. If upstream moves the
   override, the hook silently stops failing on revoked keys and the first
   test here goes red. The second test shows the dependency is real: the
   narrowed flag set drops the same finding.
2. **The wrapper prints detector, state, file and line and never the key.**
3. **What the no-flag mode scans** (plan 3 lane H FNF#1): under
   ``PRE_COMMIT=1`` the staged changes only; by hand also every commit on a
   ref not reachable from HEAD.

Which scanner runs: the ``trufflehog`` on PATH when its version equals the
pin, else the pinned image through docker (the same ``image@digest`` the CI
step runs); when neither is possible the module skips and says why. A
revoked-shape key is only ``unverified`` when the provider was actually asked
and said no, so the first test needs the network to reach AWS STS; with no
network the state is ``unknown`` and the test skips rather than passing on a
state the hook reports regardless of the quirk. Hence ``integration``
(deselected by default; ``-m integration`` opts in).

Every key is built at runtime with ``secrets``; nothing key-shaped is written
in this file, and no scanner output is ever printed by a test: assertions are
on return codes and on precomputed booleans.
"""

from __future__ import annotations

import os
import re
import secrets
import shutil
import string
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import yaml

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = [pytest.mark.integration, pytest.mark.timeout(300)]

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
SCRIPT = REPO_ROOT / "scripts" / "security" / "trufflehog_redacted.py"
#: The official action's default ``image`` input (action.yml at the pinned
#: commit); ci.yml pins only the tag and digest.
IMAGE_REPOSITORY = "ghcr.io/trufflesecurity/trufflehog"
PINNED_SCANNER_IMAGE = re.compile(r"^(\d+\.\d+\.\d+)@sha256:[0-9a-f]{64}$")
#: Environment the docker CLI needs to find its daemon and context.
DOCKER_PASSTHROUGH = ("HOME", "DOCKER_HOST", "DOCKER_CONFIG", "DOCKER_CONTEXT", "DOCKER_CERT_PATH")


def _pinned_scanner() -> tuple[str, str]:
    """``(semver, '<semver>@sha256:<digest>')`` from the CI step's ``version``."""
    data = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    steps = [
        step
        for step in data["jobs"]["secrets"]["steps"]
        if isinstance(step, dict)
        and str(step.get("uses", "")).startswith("trufflesecurity/trufflehog@")
    ]
    assert len(steps) == 1
    ref = str(steps[0]["with"]["version"])
    match = PINNED_SCANNER_IMAGE.match(ref)
    assert match, f"ci.yml must pin the scanner as <semver>@sha256:<digest>: {ref!r}"
    return match.group(1), ref


def _version_of(binary: str) -> str | None:
    proc = subprocess.run(
        [binary, "--version"], capture_output=True, text=True, check=False, timeout=60
    )
    match = re.search(r"\b(\d+\.\d+\.\d+)\b", proc.stdout + proc.stderr)
    return match.group(1) if proc.returncode == 0 and match else None


def _docker() -> str | None:
    found = shutil.which("docker")
    if found:
        return found
    for candidate in ("/opt/homebrew/bin/docker", "/usr/local/bin/docker"):
        if os.access(candidate, os.X_OK):
            return candidate
    return None


def _last_line(text: str) -> str:
    """The error docker prints last; its config-file warnings come first."""
    lines = [line for line in text.strip().splitlines() if line.strip()]
    return lines[-1][-200:] if lines else ""


@pytest.fixture(scope="module")
def scanner_bin(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A directory whose ``trufflehog`` is the pinned release, or a skip.

    The local binary when its version equals the pin; otherwise a shim that
    runs the pinned image (tag@digest, exactly as CI's step does) with the
    caller's working tree mounted read-only at its own path, so the wrapper's
    ``file://.`` resolves the same inside and out. ``PRE_COMMIT`` is passed
    through only when set, which is how the hook context differs from a run by
    hand.
    """
    version, ref = _pinned_scanner()
    bin_dir = tmp_path_factory.mktemp("pinned-trufflehog")
    local = shutil.which("trufflehog")
    local_version = _version_of(local) if local else None
    if local and local_version == version:
        (bin_dir / "trufflehog").symlink_to(local)
        return bin_dir

    have = f"local trufflehog is {local_version or 'absent'}, the pin is {version}"
    docker = _docker()
    if docker is None:
        pytest.skip(f"{have}; docker is not installed to run the pinned image")
    daemon = subprocess.run(
        [docker, "version", "--format", "{{.Server.Version}}"],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    if daemon.returncode != 0:
        pytest.skip(f"{have}; the docker daemon is not reachable: {_last_line(daemon.stderr)}")
    image = f"{IMAGE_REPOSITORY}:{ref}"
    pull = subprocess.run(
        [docker, "pull", "--quiet", image], capture_output=True, text=True, check=False, timeout=240
    )
    if pull.returncode != 0:
        pytest.skip(f"{have}; could not pull the pinned image: {_last_line(pull.stderr)}")

    shim = bin_dir / "trufflehog"
    shim.write_text(
        "#!/bin/sh\n"
        f'exec "{docker}" run --rm -e PRE_COMMIT -v "$PWD:$PWD:ro" -w "$PWD" "{image}" "$@"\n',
        encoding="utf-8",
    )
    shim.chmod(0o700)
    return bin_dir


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=pinned-image-test",
            "-c",
            "user.email=pinned-image-test@example.invalid",
            "-c",
            "commit.gpgsign=false",
            *args,
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _revoked_shape_aws_pair() -> tuple[str, str]:
    """An access key id and secret in AWS's shape that no account has issued.

    ``AKIA`` + 16 base32 characters, and a 40-character secret, which is what
    trufflehog's AWS detector pairs up. Verified against STS it is rejected,
    so the result is ``unverified`` -- the state a revoked key also lands in.
    """
    key_id = "AKIA" + "".join(secrets.choice(string.ascii_uppercase + "234567") for _ in range(16))
    secret = "".join(secrets.choice(string.ascii_letters + string.digits + "/+") for _ in range(40))
    return key_id, secret


def _credentials_file(key_id: str, secret: str) -> str:
    # Assembled at runtime so this module carries no assignment the repo's own
    # secret hooks (no-aws-tokens, detect-secrets) would have to be told about.
    id_name = "_".join(("aws", "access", "key", "id"))
    secret_name = "_".join(("aws", "secret", "access", "key"))
    return f"[default]\n{id_name} = {key_id}\n{secret_name} = {secret}\n"


@pytest.fixture
def planted_repo(tmp_path: Path) -> Iterator[tuple[Path, tuple[str, str]]]:
    """A repository with one commit and a staged, uncommitted credentials file."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "symbolic-ref", "HEAD", "refs/heads/main")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "init")
    pair = _revoked_shape_aws_pair()
    (repo / "creds.txt").write_text(_credentials_file(*pair), encoding="utf-8")
    _git(repo, "add", "creds.txt")
    yield repo, pair
    shutil.rmtree(repo, ignore_errors=True)


def _env(scanner_bin: Path, *, pre_commit: bool) -> dict[str, str]:
    env = {"PATH": f"{scanner_bin}:/usr/bin:/bin"}
    for name in DOCKER_PASSTHROUGH:
        if name in os.environ:
            env[name] = os.environ[name]
    if pre_commit:
        env["PRE_COMMIT"] = "1"
    return env


def _wrapper(
    repo: Path, scanner_bin: Path, *, pre_commit: bool
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=repo,
        env=_env(scanner_bin, pre_commit=pre_commit),
        capture_output=True,
        text=True,
        check=False,
        timeout=240,
    )


def _leaks(pair: tuple[str, str], *texts: str) -> bool:
    return any(value in text for value in pair for text in texts)


def _rows(output: str) -> list[str]:
    return [line for line in output.splitlines() if line.lstrip().startswith("- ")]


def _hook_run_or_skip(
    repo: Path, scanner_bin: Path, pair: tuple[str, str]
) -> subprocess.CompletedProcess[str]:
    """The wrapper as the hook runs it, or a skip when the provider was unreachable.

    A key the provider could not be asked about is ``unknown``, which the hook
    reports with or without the ordering quirk; only ``unverified`` (asked, and
    refused) exercises it. Offline, the two tests built on this prove nothing
    and say so.
    """
    proc = _wrapper(repo, scanner_bin, pre_commit=True)
    assert not _leaks(pair, proc.stdout, proc.stderr), (
        "the wrapper echoed planted key material (not shown)"
    )
    if (
        proc.returncode == 1
        and "state=unknown" in proc.stdout
        and "state=unverified" not in proc.stdout
    ):
        pytest.skip(
            "the provider could not be asked (no network to AWS STS): the planted key is "
            "`unknown`, a state the hook reports regardless of the ordering quirk"
        )
    return proc


def test_hook_mode_fails_on_a_revoked_shape_aws_key_and_prints_no_key_material(
    scanner_bin: Path, planted_repo: tuple[Path, tuple[str, str]]
) -> None:
    repo, pair = planted_repo
    proc = _hook_run_or_skip(repo, scanner_bin, pair)

    assert proc.returncode == 1, (proc.returncode, proc.stderr[-400:])
    rows = _rows(proc.stdout)
    assert len(rows) == 1, proc.stdout
    assert "AWS" in rows[0]
    assert "state=unverified" in rows[0], (
        "a revoked-shape key must be reported in the state upstream's PRE_COMMIT override would "
        "drop; anything else means the hook no longer catches revoked keys"
    )
    assert "creds.txt:2" in rows[0], "file and line, so the committer can find it"
    assert "Staged" in rows[0], "the staged change, not a commit"


def test_the_catch_depends_on_requesting_unverified_results(
    scanner_bin: Path, planted_repo: tuple[Path, tuple[str, str]]
) -> None:
    """The flag set upstream's ``PRE_COMMIT`` override would install
    (``--results=verified,unknown``) drops the planted key entirely. This is
    the dependency the previous test makes visible; if this ever starts
    finding the key, upstream changed what ``unverified`` means and both the
    docstring and ADR-0018 need re-reading."""
    repo, pair = planted_repo
    _hook_run_or_skip(repo, scanner_bin, pair)
    proc = subprocess.run(
        [
            str(scanner_bin / "trufflehog"),
            "git",
            "file://.",
            "--results=verified,unknown",
            "--no-update",
            "--json",
            "--fail",
            "--since-commit=HEAD",
        ],
        cwd=repo,
        env=_env(scanner_bin, pre_commit=True),
        capture_output=True,
        text=True,
        check=False,
        timeout=240,
    )
    # stdout would carry the raw match if there were one; assert on facts only.
    found_anything = proc.returncode == 183 or bool(proc.stdout.strip())
    assert proc.returncode in (0, 183), proc.stderr[-400:]
    assert not found_anything, (
        "the narrowed flag set reported the planted key: trufflehog's result states changed"
    )


def test_hook_mode_scans_only_the_index_while_a_hand_run_walks_unreachable_commits(
    scanner_bin: Path, planted_repo: tuple[Path, tuple[str, str]]
) -> None:
    """The docstring's two scopes, against the real scanner: a second key
    committed on an unmerged branch is invisible to the hook (HEAD..HEAD plus
    the index) and reported by a run with no ``PRE_COMMIT`` (``--all ^HEAD``)."""
    repo, staged_pair = planted_repo
    branch_pair = _revoked_shape_aws_pair()
    _git(repo, "stash", "-q")
    _git(repo, "checkout", "-q", "-b", "side")
    (repo / "side.txt").write_text(_credentials_file(*branch_pair), encoding="utf-8")
    _git(repo, "add", "side.txt")
    _git(repo, "commit", "-q", "-m", "side")
    _git(repo, "checkout", "-q", "main")
    _git(repo, "stash", "pop", "-q")
    assert _git(repo, "status", "--short") == "A  creds.txt"

    hook = _wrapper(repo, scanner_bin, pre_commit=True)
    by_hand = _wrapper(repo, scanner_bin, pre_commit=False)
    for proc in (hook, by_hand):
        assert not _leaks(staged_pair, proc.stdout, proc.stderr)
        assert not _leaks(branch_pair, proc.stdout, proc.stderr)
        assert proc.returncode == 1, (proc.returncode, proc.stderr[-400:])

    hook_rows = _rows(hook.stdout)
    assert len(hook_rows) == 1 and "creds.txt:2" in hook_rows[0], hook.stdout
    assert "side.txt" not in hook.stdout, "under PRE_COMMIT=1 the range is HEAD..HEAD: index only"

    hand_rows = _rows(by_hand.stdout)
    assert len(hand_rows) == 2, by_hand.stdout
    assert any("creds.txt:2" in row for row in hand_rows)
    assert any("side.txt:2" in row for row in hand_rows), (
        "by hand a base-only scan is --all ^HEAD: the unmerged branch's commit is scanned too"
    )
