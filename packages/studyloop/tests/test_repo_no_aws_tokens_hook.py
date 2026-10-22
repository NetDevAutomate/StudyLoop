"""The ``no-aws-tokens`` commit hook passes the tree and still catches a real key.

The hook (``.pre-commit-config.yaml``, a ``pygrep`` regex) was red on
``pre-commit run no-aws-tokens --all-files`` at 6db996b3: it matched AWS's
documented sample secret access key, which ``openspec/specs/session-export/spec.md``
quotes on purpose to record the scrubber's unquoted-assignment miss. A gate that
is red on a clean tree cannot be run in CI, and a contributor who learns to
ignore it ignores the real hit too. Plan 2, C3.

The fix exempts the documented sample *value* -- exactly, case-sensitively, and
not as a prefix -- rather than the files that quote it, so a real-shaped key
pasted into those same files still fails. These tests run pre-commit's own
``pygrep`` implementation against the hook's configured pattern, so they check
what the commit gate executes, not a re-typed copy of the regex.

No key-shaped literal is committed here: the documented sample is read from the
spec at runtime, every real-shaped key is generated at runtime, and the hook's
output (which echoes the matched line) is captured, never printed.
"""

from __future__ import annotations

import re
import secrets
import string
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
PRE_COMMIT_CONFIG = REPO_ROOT / ".pre-commit-config.yaml"
SPEC = REPO_ROOT / "openspec" / "specs" / "session-export" / "spec.md"

_KEY_ALPHABET = string.ascii_letters + string.digits + "/+"
_SPEC_ASSIGNMENT = re.compile(r"export AWS_SECRET_ACCESS_KEY=([A-Za-z0-9/+=]+)")


def _documented_sample() -> str:
    """AWS's documented sample secret access key, as the spec quotes it.

    The shape check keeps this honest: AWS's sample is 40 characters ending in
    ``EXAMPLEKEY``. Any other value the spec might quote is not the one the hook
    exempts, and the acceptance tests below would then fail rather than follow it.
    """
    match = _SPEC_ASSIGNMENT.search(SPEC.read_text(encoding="utf-8"))
    assert match, f"{SPEC.name} no longer quotes an unquoted AWS_SECRET_ACCESS_KEY assignment"
    value = match.group(1)
    assert len(value) == 40, "the quoted value is not secret-access-key shaped"
    assert value.endswith("EXAMPLEKEY"), "the quoted value is not AWS's documented sample"
    return value


def _real_shaped_key() -> str:
    """A fresh 40-character value in the secret-access-key alphabet."""
    return "".join(secrets.choice(_KEY_ALPHABET) for _ in range(40))


def _hook() -> dict[str, Any]:
    config = yaml.safe_load(PRE_COMMIT_CONFIG.read_text(encoding="utf-8"))
    hooks = [
        hook
        for repo in config["repos"]
        for hook in repo.get("hooks", [])
        if hook.get("id") == "no-aws-tokens"
    ]
    assert len(hooks) == 1, "expected exactly one no-aws-tokens hook"
    return hooks[0]


def _hook_fails_on(path: Path) -> bool:
    """Run the configured hook the way pre-commit does; True when it reports a hit."""
    hook = _hook()
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pre_commit.languages.pygrep",
            *hook.get("args", []),
            hook["entry"],
            str(path),
        ],
        capture_output=True,  # pygrep echoes the matched line: keep it out of the log
        check=False,
    )
    assert proc.returncode in (0, 1), "pygrep itself failed (bad pattern?)"
    return proc.returncode == 1


def _write(tmp_path: Path, line: str) -> Path:
    target = tmp_path / "sample.md"
    target.write_text(f"Some prose.\n{line}\nMore prose.\n", encoding="utf-8")
    return target


def test_hook_is_pygrep_and_exempts_no_files() -> None:
    """The exemption lives in the pattern; a file exclude would hide a real key there."""
    hook = _hook()
    assert hook["language"] == "pygrep"
    assert "exclude" not in hook
    assert "files" not in hook


def test_hook_passes_the_committed_spec() -> None:
    _documented_sample()  # the spec still quotes the sample, so this is not vacuous
    assert not _hook_fails_on(SPEC)


@pytest.mark.parametrize(
    "template",
    [
        pytest.param("export AWS_SECRET_ACCESS_KEY={value}", id="export"),
        pytest.param('aws_secret_access_key = "{value}"', id="double-quoted"),
        pytest.param("aws_secret_access_key: '{value}'", id="yaml-single-quoted"),
    ],
)
def test_hook_accepts_the_documented_sample_value(tmp_path: Path, template: str) -> None:
    assert not _hook_fails_on(_write(tmp_path, template.format(value=_documented_sample())))


@pytest.mark.parametrize(
    "value",
    [
        pytest.param(_real_shaped_key, id="random-real-shaped"),
        pytest.param(lambda: _documented_sample() + "Q", id="sample-as-prefix"),
        pytest.param(lambda: _documented_sample().lower(), id="sample-other-case"),
        pytest.param(lambda: _real_shaped_key()[:30] + "EXAMPLEKEY", id="ends-like-sample"),
    ],
)
@pytest.mark.parametrize(
    "template",
    [
        pytest.param("export AWS_SECRET_ACCESS_KEY={value}", id="export"),
        pytest.param('aws_secret_access_key = "{value}"', id="quoted"),
    ],
)
def test_hook_still_fails_a_real_shaped_key(tmp_path: Path, template: str, value: Any) -> None:
    # Computed outside the assert so a failure cannot echo the generated value.
    caught = _hook_fails_on(_write(tmp_path, template.format(value=value())))
    assert caught, "the hook let a real-shaped key through (value withheld)"


def test_hook_still_fails_a_real_key_planted_in_the_spec(tmp_path: Path) -> None:
    """The file that quotes the sample gets no blanket pass."""
    planted = tmp_path / "spec.md"
    planted.write_text(
        SPEC.read_text(encoding="utf-8")
        + f"\n  `export AWS_SECRET_ACCESS_KEY={_real_shaped_key()}`\n",
        encoding="utf-8",
    )
    caught = _hook_fails_on(planted)
    assert caught, "the hook let a real-shaped key in the spec through (value withheld)"
