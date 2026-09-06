"""T2: the pure launch-policy module — targets, resolver, and its import boundary.

``studyloop.second_brain.launch`` decides *where a browser gesture could go*,
never whether publishing works: launchability and publish availability are
deliberately independent (design: "Keep launch policy in a pure module"). The
tests here pin the full none/Obsidian/xTiles truth table, the disabled-target
invariant, exact URI bytes, containment, locality, and — statically — that the
module can never grow a provider-backend, web, network, or subprocess
dependency without this file going red.
"""

from __future__ import annotations

import dataclasses
import inspect
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import quote, unquote

import pytest

from studyloop.second_brain.launch import DeviceLocality, LaunchTarget, resolve_launch_target
from studyloop.settings import ConfigError, SecondBrainConfig

if TYPE_CHECKING:
    from collections.abc import Callable


def _obsidian_config(vault: Path, folder: str = "Study") -> SecondBrainConfig:
    return SecondBrainConfig(provider="obsidian", vault_path=vault, folder=folder)


def _vault_with_today(tmp_path: Path) -> tuple[Path, Path]:
    vault = tmp_path / "vault"
    today = vault / "Study" / "Today.md"
    today.parent.mkdir(parents=True)
    today.write_text("# Today\n")
    return vault, today


def test_launch_target_has_exactly_the_six_contract_fields() -> None:
    assert [field.name for field in dataclasses.fields(LaunchTarget)] == [
        "provider",
        "label",
        "href",
        "enabled",
        "disabled_reason",
        "device_locality",
    ]


def test_a_disabled_target_cannot_carry_an_href() -> None:
    with pytest.raises(ValueError, match="disabled target"):
        LaunchTarget(
            provider="obsidian",
            label="Obsidian",
            href="obsidian://open?path=%2Fvault",
            enabled=False,
            disabled_reason="whatever",
            device_locality="local",
        )


@pytest.mark.parametrize(
    ("href", "disabled_reason"),
    [
        pytest.param(None, None, id="missing-href"),
        pytest.param("https://xtiles.app/project", "left over", id="leftover-reason"),
    ],
)
def test_an_enabled_target_requires_an_href_and_no_reason(
    href: str | None, disabled_reason: str | None
) -> None:
    with pytest.raises(ValueError, match="enabled target"):
        LaunchTarget(
            provider="xtiles",
            label="xTiles",
            href=href,
            enabled=True,
            disabled_reason=disabled_reason,
            device_locality="not_applicable",
        )


def test_launch_target_is_immutable() -> None:
    target = LaunchTarget(
        provider="none",
        label="Second Brain",
        href=None,
        enabled=False,
        disabled_reason="No second brain provider is selected.",
        device_locality="not_applicable",
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        target.enabled = True  # type: ignore[misc]


def test_no_selected_provider_resolves_to_a_disabled_none_target() -> None:
    target = resolve_launch_target(SecondBrainConfig(provider="none"), "local")

    assert target.provider == "none"
    assert target.enabled is False
    assert target.href is None


def test_existing_today_projection_resolves_to_its_encoded_absolute_path(tmp_path: Path) -> None:
    vault, today = _vault_with_today(tmp_path)

    target = resolve_launch_target(_obsidian_config(vault), "local")

    assert target.enabled is True
    assert target.href == "obsidian://open?path=" + quote(str(today), safe="")


def test_missing_today_projection_falls_back_to_the_encoded_vault_root(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()

    target = resolve_launch_target(_obsidian_config(vault), "local")

    assert target.enabled is True
    assert target.href == "obsidian://open?path=" + quote(str(vault), safe="")


def test_non_regular_today_projection_falls_back_to_the_encoded_vault_root(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    (vault / "Study" / "Today.md").mkdir(parents=True)

    target = resolve_launch_target(_obsidian_config(vault), "local")

    assert target.enabled is True
    assert target.href == "obsidian://open?path=" + quote(str(vault), safe="")


def test_today_symlink_escaping_the_vault_falls_back_without_exposing_it(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    (vault / "Study").mkdir(parents=True)
    outside = tmp_path / "outside" / "Today.md"
    outside.parent.mkdir()
    outside.write_text("# Not yours to open\n")
    (vault / "Study" / "Today.md").symlink_to(outside)

    target = resolve_launch_target(_obsidian_config(vault), "local")

    assert target.enabled is True
    assert target.href is not None
    assert target.href == "obsidian://open?path=" + quote(str(vault), safe="")
    assert str(outside) not in target.href
    assert quote(str(outside), safe="") not in target.href


def test_reserved_and_unicode_path_characters_are_percent_encoded_exactly_once(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault with spaces #1 ? 100% café"
    today = vault / "Study" / "Today.md"
    today.parent.mkdir(parents=True)
    today.write_text("# Today\n")

    target = resolve_launch_target(_obsidian_config(vault), "local")

    assert target.href is not None
    encoded = target.href.removeprefix("obsidian://open?path=")
    assert encoded == quote(str(today), safe="")
    assert unquote(encoded) == str(today)
    for raw, escaped in ((" ", "%20"), ("#", "%23"), ("?", "%3F"), ("café", "caf%C3%A9")):
        assert raw not in encoded
        assert escaped in encoded
    assert "%25" in encoded
    assert "%2525" not in encoded


def test_a_read_only_local_vault_is_still_launchable(tmp_path: Path) -> None:
    vault, _today = _vault_with_today(tmp_path)
    vault.chmod(0o500)
    try:
        target = resolve_launch_target(_obsidian_config(vault), "local")
    finally:
        vault.chmod(0o700)

    assert target.enabled is True
    assert target.href is not None


@pytest.mark.parametrize("locality", ["remote", "unknown"])
def test_remote_or_unknown_locality_disables_obsidian_with_a_same_device_reason(
    tmp_path: Path, locality: DeviceLocality
) -> None:
    vault, _today = _vault_with_today(tmp_path)

    target = resolve_launch_target(_obsidian_config(vault), locality)

    assert target.enabled is False
    assert target.href is None
    assert target.disabled_reason is not None
    assert "device running StudyLoop" in target.disabled_reason
    assert target.device_locality == locality


def _missing_vault(tmp_path: Path) -> Path:
    return tmp_path / "nowhere"


def _relative_vault(tmp_path: Path) -> Path:
    return Path("relative/vault")


def _file_vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault.md"
    vault.write_text("not a directory\n")
    return vault


@pytest.mark.parametrize("make_vault", [_missing_vault, _relative_vault, _file_vault])
def test_an_unavailable_vault_disables_obsidian_without_exposing_a_path(
    tmp_path: Path, make_vault: Callable[[Path], Path]
) -> None:
    vault = make_vault(tmp_path)

    target = resolve_launch_target(_obsidian_config(vault), "local")

    assert target.enabled is False
    assert target.href is None
    assert target.disabled_reason is not None
    assert str(tmp_path) not in target.disabled_reason
    assert "/" not in target.disabled_reason


XTILES_DESTINATION = "https://xtiles.app/workspaces/abc/projects/def"


def test_xtiles_with_a_retained_destination_launches_exactly_there() -> None:
    config = SecondBrainConfig(provider="xtiles", xtiles_destination_url=XTILES_DESTINATION)

    target = resolve_launch_target(config, "local")

    assert target.provider == "xtiles"
    assert target.enabled is True
    assert target.href == XTILES_DESTINATION
    assert target.device_locality == "not_applicable"


def test_xtiles_without_a_destination_is_disabled_and_names_the_command() -> None:
    config = SecondBrainConfig(provider="xtiles", xtiles_destination_url=None)

    target = resolve_launch_target(config, "local")

    assert target.provider == "xtiles"
    assert target.enabled is False
    assert target.href is None
    assert target.disabled_reason is not None
    assert "studyloop brain destination set --provider xtiles" in target.disabled_reason


@pytest.mark.parametrize("provider", ["none", "obsidian"])
def test_a_retained_destination_never_enables_xtiles_for_another_provider(
    tmp_path: Path, provider: str
) -> None:
    config = SecondBrainConfig(
        provider=provider,
        vault_path=tmp_path / "nowhere",
        xtiles_destination_url=XTILES_DESTINATION,
    )

    target = resolve_launch_target(config, "local")

    assert target.provider == provider
    assert not (target.provider == "xtiles" and target.enabled)
    assert target.href != XTILES_DESTINATION


def test_an_unknown_provider_on_a_hand_built_config_is_a_config_error() -> None:
    """``load_settings`` validates the provider, but a hand-built config never
    passes through it. A silent none-target for a typo would present "off" as
    success — the same reasoning as ``get_backend``."""
    with pytest.raises(ConfigError, match=r"second_brain\.provider"):
        resolve_launch_target(SecondBrainConfig(provider="notion"), "local")


def test_launch_policy_imports_only_config_types_and_stdlib_path_url_utilities() -> None:
    """Design boundary, pinned statically: the pure module can never grow a
    provider-backend, web, network, or subprocess dependency without this
    test going red. An allowlist, not a denylist, so a new dependency is a
    decision rather than a drift.
    """
    import ast

    allowed = {
        "__future__",
        "dataclasses",
        "typing",
        "pathlib",
        "urllib.parse",
        "studyloop.settings",
    }
    source = Path(inspect.getsourcefile(resolve_launch_target) or "")
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            offenders.extend(
                f"line {node.lineno}: import {alias.name}"
                for alias in node.names
                if alias.name not in allowed
            )
        elif isinstance(node, ast.ImportFrom) and node.module not in allowed:
            offenders.append(f"line {node.lineno}: from {node.module} import ...")
    assert offenders == [], "launch policy grew a dependency outside its boundary:\n" + "\n".join(
        offenders
    )


def test_installing_the_launcher_leaves_the_publication_contracts_pinned() -> None:
    """The resolver must not extend ``SecondBrain`` or ``BrainDescription``:
    with the launcher imported, the protocol still exposes exactly six methods
    and the serialized description still exposes its pinned keys only."""
    from studyloop.second_brain.core import BrainDescription, SecondBrain

    protocol_methods = {
        name
        for name, value in vars(SecondBrain).items()
        if not name.startswith("_") and inspect.isfunction(value)
    }
    assert protocol_methods == {
        "describe",
        "is_available",
        "publish_plan",
        "publish_today",
        "publish_learning_record",
        "pull_notes",
    }

    description_keys = set(
        BrainDescription(
            provider="none",
            configured=False,
            available=False,
            supports_publish=False,
            supports_pull_notes=False,
            vault_path=None,
            folder=None,
            detail="Second brain is not configured.",
        ).to_json_dict()
    )
    assert description_keys == {
        "provider",
        "configured",
        "available",
        "supports_publish",
        "supports_pull_notes",
        "vault_path",
        "folder",
        "detail",
    }
    assert not issubclass(LaunchTarget, BrainDescription)
