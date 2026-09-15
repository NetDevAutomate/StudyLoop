"""Docs contract: the ACTOR matrix in docs/acceptance-testing.md is derived
from the code, not maintained by hand.

Test shape per the lane's binding rule (council A20): compare SETS derived
from code symbols against what a PARSER extracts from the doc -- never
copied prose, never line numbers.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_tests_dir = Path(__file__).parent
if str(_tests_dir) not in sys.path:
    sys.path.insert(0, str(_tests_dir))

from acceptance.actors.direct import ENV_MODEL as DIRECT_ENV_MODEL  # noqa: E402
from acceptance.actors.direct import ENV_PROVIDER as DIRECT_ENV_PROVIDER  # noqa: E402
from acceptance.actors.direct import SUPPORTED_ADAPTERS  # noqa: E402
from acceptance.actors.factory import KNOWN_ACTORS  # noqa: E402
from acceptance.actors.gateway import ENV_API_KEY as GATEWAY_ENV_API_KEY  # noqa: E402
from acceptance.actors.gateway import ENV_BASE_URL as GATEWAY_ENV_BASE_URL  # noqa: E402
from acceptance.actors.gateway import ENV_MODEL as GATEWAY_ENV_MODEL  # noqa: E402
from acceptance.actors.harness import ENV_COMMAND as HARNESS_ENV_COMMAND  # noqa: E402
from acceptance.actors.protocol import TerminationOutcome  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]
DOC = REPO_ROOT / "docs" / "acceptance-testing.md"


def _doc_text() -> str:
    return DOC.read_text(encoding="utf-8")


def _backticked_tokens(text: str) -> set[str]:
    """Every `backticked` token in the document."""
    return set(re.findall(r"`([^`\n]+)`", text))


class TestActorMatrix:
    def test_every_known_actor_is_documented(self) -> None:
        tokens = _backticked_tokens(_doc_text())
        missing = {actor for actor in KNOWN_ACTORS if actor not in tokens}
        assert not missing, f"docs/acceptance-testing.md does not name actor(s): {sorted(missing)}"

    def test_doc_names_no_actor_the_code_does_not_have(self) -> None:
        """The doc's own ACTOR table rows must all be real actors.

        Parses the ``STUDYLOOP_ACC_ACTOR`` table row that lists the
        supported values, rather than scanning the whole document (which
        legitimately mentions other backticked words).
        """
        text = _doc_text()
        match = re.search(r"^\|\s*Actor\s*\|.*$\n\|[-\s|]+\|$\n((?:^\|.*$\n)+)", text, re.M)
        assert match, "docs/acceptance-testing.md has no ACTOR matrix table"
        rows = match.group(1).strip().splitlines()
        documented = set()
        for row in rows:
            first_cell = row.split("|")[1].strip()
            names = re.findall(r"`([^`]+)`", first_cell)
            documented.update(names)
        assert documented == set(KNOWN_ACTORS), (
            f"ACTOR matrix rows {sorted(documented)} != KNOWN_ACTORS {sorted(KNOWN_ACTORS)}"
        )


class TestEnvVarsDocumented:
    def test_every_actor_env_var_is_documented(self) -> None:
        tokens = _backticked_tokens(_doc_text())
        expected = {
            GATEWAY_ENV_API_KEY,
            GATEWAY_ENV_BASE_URL,
            GATEWAY_ENV_MODEL,
            DIRECT_ENV_PROVIDER,
            DIRECT_ENV_MODEL,
            HARNESS_ENV_COMMAND,
        }
        missing = expected - tokens
        assert not missing, (
            f"docs/acceptance-testing.md does not name env var(s): {sorted(missing)}"
        )


class TestTerminationOutcomesDocumented:
    def test_every_termination_outcome_value_is_documented(self) -> None:
        tokens = _backticked_tokens(_doc_text())
        expected = {outcome.value for outcome in TerminationOutcome}
        missing = expected - tokens
        assert not missing, (
            f"docs/acceptance-testing.md does not name termination outcome(s): {sorted(missing)}"
        )


class TestDirectProvidersDocumented:
    def test_supported_adapter_names_are_documented(self) -> None:
        tokens = _backticked_tokens(_doc_text())
        missing = SUPPORTED_ADAPTERS - tokens
        assert not missing, (
            f"docs/acceptance-testing.md does not name direct adapter(s): {sorted(missing)}"
        )


class TestStaleClaimsRemoved:
    def test_docs_no_longer_claim_only_scripted_is_supported(self) -> None:
        """B1's doc said gateway/direct/harness were "a later lane's job".
        This lane IS that later lane, so the claim must be gone -- a
        structural check on the phrase pattern, not on prose wording.
        """
        text = _doc_text()
        stale = re.search(r"currently supports only\s+`scripted`", text, re.I)
        assert stale is None, "docs/acceptance-testing.md still claims only `scripted` is supported"
