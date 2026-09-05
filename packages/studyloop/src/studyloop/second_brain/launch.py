"""Pure launch policy: where one explicit browser gesture could take the learner.

This module owns the immutable :class:`LaunchTarget` value and the
provider-neutral resolver. It is deliberately inert — it computes a
destination, it never opens one — and it imports configuration types and
standard-library path/URL utilities only: no provider backend, no web code, no
network client, no subprocess facility. ``tests/test_second_brain_launch.py``
pins that boundary statically, so launchability stays independent of publish
availability and the full truth table is testable without I/O beyond
filesystem inspection.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal
from urllib.parse import quote

from studyloop.settings import SECOND_BRAIN_PROVIDERS, ConfigError

if TYPE_CHECKING:
    from pathlib import Path

    from studyloop.settings import SecondBrainConfig

#: Where the browser making the request runs relative to StudyLoop.
#: ``not_applicable`` is reserved for targets that never involve a device
#: decision, such as an ordinary web destination.
DeviceLocality = Literal["local", "remote", "unknown", "not_applicable"]


@dataclass(frozen=True)
class LaunchTarget:
    """One provider's honest launch state: exactly what the API may expose."""

    provider: str
    label: str
    href: str | None
    enabled: bool
    disabled_reason: str | None
    device_locality: DeviceLocality

    def __post_init__(self) -> None:
        if self.enabled:
            if self.href is None:
                raise ValueError("an enabled target requires an href")
            if self.disabled_reason is not None:
                raise ValueError("an enabled target must not carry a disabled reason")
        elif self.href is not None:
            raise ValueError("a disabled target must not carry an href")


NO_PROVIDER_REASON = "No second brain provider is selected."

SAME_DEVICE_REASON = "Obsidian opens only on the device running StudyLoop."

VAULT_UNAVAILABLE_REASON = "The configured Obsidian vault is not an existing absolute directory."

OBSIDIAN_URI_PREFIX = "obsidian://open?path="

NO_DESTINATION_REASON = (
    "No xTiles destination is retained. Run "
    "'studyloop brain destination set --provider xtiles --url URL' to retain one."
)


def _disabled(
    provider: str, label: str, reason: str, device_locality: DeviceLocality
) -> LaunchTarget:
    return LaunchTarget(
        provider=provider,
        label=label,
        href=None,
        enabled=False,
        disabled_reason=reason,
        device_locality=device_locality,
    )


def _contained_today(config: SecondBrainConfig) -> Path | None:
    """The ``<vault>/<folder>/Today.md`` projection, only if it is safe to open.

    ``resolve()`` before the containment check, so a symlink that points
    outside the vault is treated as absent rather than becoming a launch
    vector for an arbitrary filesystem path.
    """
    candidate = config.vault_path / config.folder / "Today.md"
    resolved = candidate.resolve()
    if not resolved.is_file():
        return None
    if not resolved.is_relative_to(config.vault_path.resolve()):
        return None
    return candidate


def _resolve_obsidian(config: SecondBrainConfig, device_locality: DeviceLocality) -> LaunchTarget:
    if device_locality != "local":
        return _disabled("obsidian", "Obsidian", SAME_DEVICE_REASON, device_locality)
    if not config.vault_path.is_absolute() or not config.vault_path.is_dir():
        return _disabled("obsidian", "Obsidian", VAULT_UNAVAILABLE_REASON, "local")
    chosen = _contained_today(config) or config.vault_path
    return LaunchTarget(
        provider="obsidian",
        label="Obsidian",
        href=OBSIDIAN_URI_PREFIX + quote(str(chosen), safe=""),
        enabled=True,
        disabled_reason=None,
        device_locality="local",
    )


def _resolve_xtiles(config: SecondBrainConfig) -> LaunchTarget:
    if config.xtiles_destination_url is None:
        return _disabled("xtiles", "xTiles", NO_DESTINATION_REASON, "not_applicable")
    return LaunchTarget(
        provider="xtiles",
        label="xTiles",
        href=config.xtiles_destination_url,
        enabled=True,
        disabled_reason=None,
        device_locality="not_applicable",
    )


def resolve_launch_target(
    config: SecondBrainConfig, device_locality: DeviceLocality
) -> LaunchTarget:
    """Resolve the selected provider's honest launch state, without side effects."""
    if config.provider == "obsidian":
        return _resolve_obsidian(config, device_locality)
    if config.provider == "xtiles":
        return _resolve_xtiles(config)
    if config.provider != "none":
        raise ConfigError(
            f"Invalid value for 'second_brain.provider': {config.provider!r}. "
            f"Choose one of: {', '.join(SECOND_BRAIN_PROVIDERS)}."
        )
    return _disabled("none", "Second Brain", NO_PROVIDER_REASON, "not_applicable")


__all__ = [
    "NO_DESTINATION_REASON",
    "NO_PROVIDER_REASON",
    "OBSIDIAN_URI_PREFIX",
    "SAME_DEVICE_REASON",
    "VAULT_UNAVAILABLE_REASON",
    "DeviceLocality",
    "LaunchTarget",
    "resolve_launch_target",
]
