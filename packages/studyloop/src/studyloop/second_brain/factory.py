"""Backend selection for the second-brain layer.

One function, one decision: read the configured provider and return the object
that serves it. The Obsidian backend is imported INSIDE the branch that selects
it, which is the whole reason this lives in its own module — see
:mod:`studyloop.second_brain` for why the import boundary is load-bearing.

Precedent: :mod:`studyloop.multiplexer`'s ``get_backend()``. Three things are
deliberately NOT copied from it: an environment-variable override (selecting a
provider authorises writes into the learner's own files, so it must be a
deliberate config change — ADR-0010), a real default backend (the default here
is "off"), and treating "configured but unavailable" as a factory error (a
vault on an unmounted drive is a runtime condition the CLI reports, not an
import-time crash).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from studyloop.second_brain.core import (
    NullBackend,
    SecondBrain,
    XtilesStageOneBackend,
)

if TYPE_CHECKING:
    from studyloop.settings import Settings

#: Every provider ``get_backend`` will serve, in the message an error quotes.
KNOWN_PROVIDERS = ("none", "obsidian", "xtiles")


def get_backend(settings: Settings | None = None) -> SecondBrain:
    """Return the backend for the configured provider.

    ``settings`` is accepted so a caller that already loaded configuration does
    not pay for a second read, and so a test can hand in a hand-built
    ``Settings`` without writing a config file.

    The provider is re-validated here even though ``load_settings`` validates
    it: a hand-built ``Settings`` never passes through the loader, and silently
    returning ``NullBackend`` for a typo would present "off" as success.
    """
    if settings is None:
        from studyloop.settings import load_settings

        settings = load_settings()

    config = settings.second_brain
    provider = config.provider

    if provider == "none":
        return NullBackend()
    if provider == "xtiles":
        return XtilesStageOneBackend()
    if provider == "obsidian":
        # The ONLY provider import in this package's non-provider modules.
        from studyloop.second_brain.obsidian import ObsidianBackend

        return ObsidianBackend(config)

    from studyloop.settings import ConfigError

    raise ConfigError(
        f"second_brain.provider {provider!r} is not one of: {', '.join(KNOWN_PROVIDERS)}"
    )


__all__ = ["KNOWN_PROVIDERS", "get_backend"]
