"""WD-1 — the wind-down decision truth table, as a pure function.

Every row of the acceptance-suite truth table
(`reviews/2026-09-04-acceptance-harness/PLAN.md`), asserted against
:func:`studyloop.second_brain.wind_down.decide_wind_down` with hand-built
``BrainDescription`` values — no config file, no probe, no I/O. If any row's
``channel`` or ``offer`` flips, exactly one of these tests goes red.

The two-rules-not-one-conjunction property (D1) gets its own tests: the
publish sentence must never be offered to an xTiles learner, and the xTiles
channel must not be computed from ``supports_publish``.
"""

from __future__ import annotations

import pytest

from studyloop.second_brain.core import (
    BrainDescription,
    NullBackend,
    XtilesStageOneBackend,
)
from studyloop.second_brain.wind_down import (
    PUBLISH_OFFER_SENTENCE,
    XTILES_OFFER_SENTENCE,
    decide_wind_down,
)


def _obsidian_description(*, available: bool) -> BrainDescription:
    """What ObsidianBackend.describe() reports; only ``available`` varies."""
    return BrainDescription(
        provider="obsidian",
        configured=True,
        available=available,
        supports_publish=True,
        supports_pull_notes=True,
        vault_path="/tmp/vault",
        folder="Study",
        detail="test double",
    )


# ---------------------------------------------------------------------------
# The 8 rows. Descriptions for none/xtiles come from the REAL backends so a
# drift in what they report flips these rows rather than a test double.
# ---------------------------------------------------------------------------


class TestTruthTable:
    def test_row_1_provider_none_no_connector(self) -> None:
        decision = decide_wind_down(NullBackend().describe(), ())
        assert (decision.channel, decision.offer) == ("none", False)
        assert decision.sentence == ""

    def test_row_2_provider_none_connector_present(self) -> None:
        """An attached connector alone is not consent — provider gates it."""
        decision = decide_wind_down(NullBackend().describe(), ("xtiles",))
        assert (decision.channel, decision.offer) == ("none", False)
        assert decision.sentence == ""

    def test_row_3_obsidian_writable_no_connector(self) -> None:
        decision = decide_wind_down(_obsidian_description(available=True), ())
        assert (decision.channel, decision.offer) == ("publish", True)
        assert decision.sentence == PUBLISH_OFFER_SENTENCE

    def test_row_4_obsidian_writable_connector_present(self) -> None:
        """Publish outranks the connector: an Obsidian learner gets ONE offer."""
        decision = decide_wind_down(_obsidian_description(available=True), ("xtiles",))
        assert (decision.channel, decision.offer) == ("publish", True)
        assert decision.sentence == PUBLISH_OFFER_SENTENCE

    def test_row_5_obsidian_unwritable_vault_offer_stands(self) -> None:
        """``available`` is a runtime condition the publish itself reports."""
        decision = decide_wind_down(_obsidian_description(available=False), ())
        assert (decision.channel, decision.offer) == ("publish", True)
        assert decision.sentence == PUBLISH_OFFER_SENTENCE

    def test_row_6_xtiles_no_connector(self) -> None:
        decision = decide_wind_down(XtilesStageOneBackend().describe(), ())
        assert (decision.channel, decision.offer) == ("none", False)
        assert decision.sentence == ""

    def test_row_7_xtiles_connector_present(self) -> None:
        decision = decide_wind_down(XtilesStageOneBackend().describe(), ("xtiles",))
        assert (decision.channel, decision.offer) == ("xtiles", True)
        assert decision.sentence == XTILES_OFFER_SENTENCE

    def test_row_8_unknown_provider_raises_config_error(self) -> None:
        """Unknown providers never reach the decision — get_backend raises."""
        from studyloop.second_brain import get_backend
        from studyloop.settings import ConfigError, SecondBrainConfig, Settings

        settings = Settings(second_brain=SecondBrainConfig(provider="notion"))
        with pytest.raises(ConfigError, match="notion"):
            get_backend(settings)


# ---------------------------------------------------------------------------
# D1 — two rules, not one conjunction
# ---------------------------------------------------------------------------


class TestTwoRulesNotOneConjunction:
    def test_the_publish_sentence_never_reaches_an_xtiles_learner(self) -> None:
        for connectors in ((), ("xtiles",), ("xtiles", "playwright")):
            decision = decide_wind_down(XtilesStageOneBackend().describe(), connectors)
            assert decision.sentence != PUBLISH_OFFER_SENTENCE
            assert decision.channel != "publish"

    def test_the_xtiles_channel_is_not_permanently_false(self) -> None:
        """The straw man computed everything from supports_publish, which
        XtilesStageOneBackend sets False on purpose — the suite would have
        'passed' by asserting silence in the one state whose point is an offer."""
        decision = decide_wind_down(XtilesStageOneBackend().describe(), ("xtiles",))
        assert decision.offer is True

    def test_connector_matching_is_by_exact_name(self) -> None:
        decision = decide_wind_down(
            XtilesStageOneBackend().describe(), ("xtiles-staging", "my-xtiles")
        )
        assert (decision.channel, decision.offer) == ("none", False)


# ---------------------------------------------------------------------------
# The payload shape the harness (and the agent) reads
# ---------------------------------------------------------------------------


class TestPayload:
    def test_json_dict_carries_exactly_the_four_ruled_fields(self) -> None:
        """No ``command`` field: nothing guarantees a plan id at wind-down."""
        payload = decide_wind_down(NullBackend().describe(), ()).to_json_dict()
        assert sorted(payload) == ["channel", "offer", "reason", "sentence"]

    def test_every_decision_names_a_reason(self) -> None:
        cases = [
            (NullBackend().describe(), ()),
            (XtilesStageOneBackend().describe(), ()),
            (XtilesStageOneBackend().describe(), ("xtiles",)),
            (_obsidian_description(available=True), ()),
        ]
        for description, connectors in cases:
            assert decide_wind_down(description, connectors).reason
