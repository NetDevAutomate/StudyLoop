"""Clause 8: this feature holds no credential, proven by snapshot not by grep.

The original proof was `rg -n "secrets" .../second_brain` printing nothing. A
reviewer was right to reject it: that is a search for a word, not a property. Code
can write a credential through a helper with an unrelated name, or through the
settings and state APIs, without the string "secrets" appearing anywhere — so the
check could not fail, which makes it worse than no check at all.

This snapshots the three directories a credential could plausibly land in, around
every backend and CLI operation, and fails if any of them changed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import yaml
from click.testing import CliRunner

from studyloop.cli._brain import brain_group
from studyloop.planning import Mission, StudyPlan, create_plan
from studyloop.second_brain import get_backend
from studyloop.settings import SecondBrainConfig, Settings

if TYPE_CHECKING:
    from pathlib import Path

PLAN_ID = "python-decorators"


def _snapshot(*roots: Path) -> dict[str, tuple[int, int]]:
    """Every file under each root, with its size and mtime."""
    found: dict[str, tuple[int, int]] = {}
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            try:
                info = path.stat()
            except OSError:
                continue
            if path.is_file():
                found[str(path)] = (info.st_size, info.st_mtime_ns)
    return found


@pytest.fixture()
def watched(tmp_path, monkeypatch):
    """Isolated secrets, config and state directories, plus a vault and plans dir."""
    secrets = tmp_path / "secrets"
    config_dir = tmp_path / "config"
    state = tmp_path / "state"
    plans = tmp_path / "plans"
    vault = tmp_path / "vault"
    for directory in (secrets, config_dir, state, plans, vault / ".obsidian"):
        directory.mkdir(parents=True)

    config = config_dir / "config.yaml"
    config.write_text(
        yaml.dump(
            {
                "second_brain": {
                    "provider": "obsidian",
                    "vault_path": str(vault),
                    "backlinks": False,
                }
            }
        )
    )
    monkeypatch.setenv("STUDYLOOP_CONFIG", str(config))
    monkeypatch.setenv("STUDYLOOP_PLANS_DIR", str(plans))
    monkeypatch.setenv("STUDYLOOP_STATE_DIR", str(state))

    create_plan(
        StudyPlan(
            plan_id=PLAN_ID,
            title="Master Python Decorators",
            status="active",
            topics=["python"],
            mission=Mission(why="Because they keep coming up."),
        )
    )
    return {"secrets": secrets, "config_dir": config_dir, "state": state, "vault": vault}


def test_no_backend_operation_touches_secrets_config_or_state(watched) -> None:
    """Every operation, one snapshot. The vault is expected to change; nothing else is."""
    settings = Settings()
    settings.second_brain = SecondBrainConfig(
        provider="obsidian", vault_path=watched["vault"], backlinks=False
    )
    backend = get_backend(settings)

    before = _snapshot(watched["secrets"], watched["state"])
    config_before = (watched["config_dir"] / "config.yaml").read_bytes()

    backend.describe()
    backend.is_available()
    backend.publish_plan(PLAN_ID)
    backend.publish_today()
    backend.pull_notes(PLAN_ID)

    assert _snapshot(watched["secrets"], watched["state"]) == before
    assert (watched["config_dir"] / "config.yaml").read_bytes() == config_before

    # And the vault DID change, so this test is not vacuous.
    assert (watched["vault"] / "Study" / "Plans" / f"{PLAN_ID}.md").is_file()


def test_no_brain_command_touches_secrets_or_state(watched) -> None:
    """The CLI is the other surface a credential could be written from."""
    before = _snapshot(watched["secrets"], watched["state"])

    runner = CliRunner()
    for args in (
        ["status", "--json"],
        ["publish", "--json"],
        ["publish", "--dry-run", "--json"],
        ["pull", PLAN_ID, "--json"],
        ["template"],
        ["template", "--print", "Today.md"],
    ):
        result = runner.invoke(brain_group, args)
        assert result.exit_code == 0, (args, result.output)

    assert _snapshot(watched["secrets"], watched["state"]) == before


def test_the_secrets_module_is_never_imported_by_this_feature() -> None:
    """Belt and braces on the snapshots: the API is not even reachable.

    Run in a SUBPROCESS. An in-process `sys.modules` assertion passes or fails on test
    ORDER here -- something else in this suite legitimately imports the secrets store,
    and once it is in `sys.modules` no later assertion can tell who put it there. A
    fresh interpreter that imports only this feature is the one form of this check that
    means what it says.
    """
    import subprocess
    import sys

    program = (
        "import sys;"
        "from studyloop.second_brain import get_backend;"
        "from studyloop.settings import SecondBrainConfig, Settings;"
        "s = Settings();"
        "s.second_brain = SecondBrainConfig(provider='none');"
        "get_backend(s).describe();"
        "leaked = [n for n in sys.modules if 'secrets' in n or 'keyring' in n];"
        "print('LEAKED' if leaked else 'CLEAN', leaked)"
    )
    result = subprocess.run(
        [sys.executable, "-c", program], capture_output=True, text=True, timeout=120
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("CLEAN"), result.stdout
