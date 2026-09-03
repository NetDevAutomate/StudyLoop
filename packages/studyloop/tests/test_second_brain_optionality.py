"""T1 C7/C8: "off by default" proven, not asserted in prose.

The claim this file defends is the one a learner has to be able to trust
without reading the code: *if you have not configured a second brain, StudyLoop
does not import one, does not write anything, and does not mention it.*

Three independent kinds of evidence, because each catches a different mistake:

* ``sys.modules`` — catches a top-level import that would make every
  ``studyloop --help`` pay for a provider it will never use.
* a ``tmp_path`` tree snapshot — catches a directory created "just in case".
* the command's own output — catches a feature that nags.
"""

from __future__ import annotations

import importlib
import sys

import pytest
import yaml
from click.testing import CliRunner

PROVIDER_MODULES = (
    "studyloop.second_brain.obsidian",
    "studyloop.second_brain.obsidian_cli",
    "studyloop.second_brain.projection",
)


@pytest.fixture()
def clean_provider_modules():
    """Drop any provider module another test imported, and restore after.

    Without this the assertions below would pass or fail depending on test
    order, which would make them worthless as a guard.
    """
    saved = {name: sys.modules[name] for name in PROVIDER_MODULES if name in sys.modules}
    for name in saved:
        del sys.modules[name]
    yield
    for name, module in saved.items():
        sys.modules[name] = module


@pytest.fixture()
def disabled_config(tmp_path, monkeypatch, request):
    """A config directory with either no ``second_brain`` section or ``none``."""
    section = getattr(request, "param", None)
    mapping: dict = {"topics": []}
    if section is not None:
        mapping["second_brain"] = section
    config = tmp_path / "config.yaml"
    config.write_text(yaml.dump(mapping))
    monkeypatch.setenv("STUDYLOOP_CONFIG", str(config))
    monkeypatch.setenv("STUDYLOOP_PLANS_DIR", str(tmp_path / "plans"))
    return tmp_path


ABSENT_OR_NONE = [
    pytest.param(None, id="section-absent"),
    pytest.param({"provider": "none"}, id="provider-none"),
]


def _tree(root) -> list[str]:
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*"))


# ---------------------------------------------------------------------------
# C7 — nothing is imported
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("disabled_config", ABSENT_OR_NONE, indirect=True)
def test_factory_does_not_import_provider_modules_when_absent(
    disabled_config, clean_provider_modules
) -> None:
    factory = importlib.import_module("studyloop.second_brain.factory")
    factory.get_backend().describe()
    assert [name for name in PROVIDER_MODULES if name in sys.modules] == []


@pytest.mark.parametrize("disabled_config", ABSENT_OR_NONE, indirect=True)
def test_status_does_not_import_provider_modules_when_disabled(
    disabled_config, clean_provider_modules
) -> None:
    from studyloop.cli._brain import brain_group

    result = CliRunner().invoke(brain_group, ["status", "--json"])
    assert result.exit_code == 0, result.output
    assert [name for name in PROVIDER_MODULES if name in sys.modules] == []


@pytest.mark.parametrize("disabled_config", ABSENT_OR_NONE, indirect=True)
def test_publish_does_not_import_provider_modules_when_disabled(
    disabled_config, clean_provider_modules
) -> None:
    from studyloop.cli._brain import brain_group

    result = CliRunner().invoke(brain_group, ["publish", "--plan", "missing-plan"])
    assert result.exit_code == 0, result.output
    assert [name for name in PROVIDER_MODULES if name in sys.modules] == []


def test_brain_help_does_not_import_a_backend(clean_provider_modules) -> None:
    """``studyloop brain --help`` must stay as cheap as any other help screen."""
    from studyloop.cli._brain import brain_group

    result = CliRunner().invoke(brain_group, ["--help"])
    assert result.exit_code == 0
    assert [name for name in PROVIDER_MODULES if name in sys.modules] == []


# ---------------------------------------------------------------------------
# C8 — nothing is written, nothing is offered
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("disabled_config", ABSENT_OR_NONE, indirect=True)
def test_disabled_status_creates_no_files_or_offer(disabled_config) -> None:
    from studyloop.cli._brain import brain_group

    before = _tree(disabled_config)
    result = CliRunner().invoke(brain_group, ["status"])
    assert result.exit_code == 0
    assert _tree(disabled_config) == before
    # It may say "not configured"; it must not suggest a command. `supports_publish`
    # is a field name, so the assertion is on the invitation, not the word.
    assert "studyloop brain publish" not in result.output
    assert "Want me to" not in result.output


@pytest.mark.parametrize("disabled_config", ABSENT_OR_NONE, indirect=True)
def test_disabled_publish_creates_no_files_or_offer(disabled_config) -> None:
    from studyloop.cli._brain import brain_group

    before = _tree(disabled_config)
    result = CliRunner().invoke(brain_group, ["publish", "--plan", "missing-plan"])
    assert result.exit_code == 0
    assert _tree(disabled_config) == before


def test_no_automatic_publish_call_sites() -> None:
    """C9 (T4): nothing publishes on its own.

    A static check rather than a mock, because the property is "no module under
    these packages mentions the feature at all" — a mock can only prove that one
    path happened not to call it during one test.

    ``mcp/tools.py`` is exempt for exactly one line: it delegates due-card
    aggregation to a helper the backend also uses, so that the backend never
    has to import ``fastmcp``.
    """
    from pathlib import Path

    src = Path(__file__).resolve().parents[1] / "src" / "studyloop"
    offenders: list[str] = []
    for package in ("session", "web", "mcp"):
        for path in (src / package).rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            for number, line in enumerate(text.splitlines(), start=1):
                if "second_brain" in line or "cli._brain" in line:
                    offenders.append(f"{path.relative_to(src)}:{number}: {line.strip()}")
    assert offenders == [], "automatic second-brain call sites:\n" + "\n".join(offenders)
