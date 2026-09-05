"""The wind-down second-brain decision, as data instead of protocol prose.

Why this exists
---------------
The wind-down protocol used to ask the agent to derive the one second-brain
offer itself: read ``brain status --json``, combine two flags, remember which
provider means which sentence, and say nothing in every other case. Two of the
three acceptance gate checks for the second-brain layer therefore needed a
human to watch a transcript. This module moves the decision into code so a
deterministic test (and the agent) can read it as one JSON object:
``studyloop brain wind-down --json``.

Two rules, deliberately NOT one conjunction (the 2026-09-04 design council's
D1): computing everything from ``configured and supports_publish`` would make
the xTiles channel permanently silent, because ``XtilesStageOneBackend`` sets
``supports_publish=False`` on purpose — the *publish* sentence must never be
offered to an xTiles learner.

* ``publish`` — ``configured and supports_publish``. Vault writability is NOT
  part of the rule: ``available`` is a runtime condition the publish itself
  reports, so the offer stands for an Obsidian learner whose vault is
  currently unmounted.
* ``xtiles``  — ``provider == "xtiles"`` and a connector named ``xtiles`` is
  attached in this session. Connector state is per-session and only the caller
  knows it, which is why it arrives as an argument (``--connector``) rather
  than being probed here.

The two sentences below are the canonical copies. The agent-facing docs carry
the same bytes between ``<!-- wind-down-offer -->`` /
``<!-- xtiles-wind-down-offer -->`` markers, and
``tests/test_second_brain_docs.py`` pins all copies to these constants, so the
CLI, the protocol, the skill and the guide cannot drift apart.

Import boundary: nothing here imports a provider module — the decision reads a
:class:`~studyloop.second_brain.core.BrainDescription`, whoever produced it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

    from studyloop.second_brain.core import BrainDescription

#: The one publish offer, verbatim. Byte-identical to the delimited sentence in
#: ``agents/shared/wind-down-protocol.md`` and ``docs/second-brain.md``.
PUBLISH_OFFER_SENTENCE = (
    "Want me to publish today's study record and this plan to your Obsidian vault "
    "(Study/Today.md and Study/Plans/<plan-id>.md)? Yes or no — I'll only ask once."
)

#: The one xTiles offer, verbatim. Byte-identical to the delimited sentence in
#: ``agents/skills/studyloop-xtiles-wind-down/SKILL.md``.
XTILES_OFFER_SENTENCE = (
    "Want me to add today's learning record and the next review to your xTiles "
    "project? Yes or no — I'll only ask once."
)

#: The MCP server name the xTiles channel requires, exactly as the skill and
#: the Second Brain guide spell it.
XTILES_CONNECTOR = "xtiles"


@dataclass(frozen=True)
class WindDownDecision:
    """One offer (or none), with the exact sentence and why.

    ``sentence`` is the full pinned sentence or ``""`` — never a template the
    agent must fill. There is deliberately no ``command`` field: nothing
    guarantees a plan id exists at wind-down, and a half-filled command string
    is worse than none (council ruling, 2026-09-04).
    """

    channel: str  # "none" | "publish" | "xtiles"
    offer: bool
    sentence: str
    reason: str

    def to_json_dict(self) -> dict[str, object]:
        return {
            "channel": self.channel,
            "offer": bool(self.offer),
            "sentence": self.sentence,
            "reason": self.reason,
        }


def decide_wind_down(
    description: BrainDescription, connectors: Iterable[str] = ()
) -> WindDownDecision:
    """Which second-brain offer this session's wind-down makes, if any.

    Pure: no config read, no probe, no I/O. ``description`` is what
    ``get_backend().describe()`` returned; ``connectors`` is the caller's list
    of MCP server names attached in this session (only the ``xtiles`` entry
    matters). Unknown providers never reach here — ``get_backend`` raises
    ``ConfigError`` first.
    """
    if description.configured and description.supports_publish:
        return WindDownDecision(
            channel="publish",
            offer=True,
            sentence=PUBLISH_OFFER_SENTENCE,
            reason=(f"provider {description.provider!r} is configured and supports publish"),
        )
    if description.provider == "xtiles":
        if XTILES_CONNECTOR in set(connectors):
            return WindDownDecision(
                channel="xtiles",
                offer=True,
                sentence=XTILES_OFFER_SENTENCE,
                reason="provider is 'xtiles' and an 'xtiles' connector is attached",
            )
        return WindDownDecision(
            channel="none",
            offer=False,
            sentence="",
            reason="provider is 'xtiles' but no 'xtiles' connector is attached this session",
        )
    return WindDownDecision(
        channel="none",
        offer=False,
        sentence="",
        reason="no second brain is configured",
    )


__all__ = [
    "PUBLISH_OFFER_SENTENCE",
    "XTILES_CONNECTOR",
    "XTILES_OFFER_SENTENCE",
    "WindDownDecision",
    "decide_wind_down",
]
