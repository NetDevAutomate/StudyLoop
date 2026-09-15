"""§5 stream (council D-12): the adopt/reject verdict for the prose-OR widen candidate.

The pre-registration (``docs/architecture/session-memory/receipts/lexical/
preregistration-2026-09-15.md``) froze four clauses before any number existed.
This module evaluates them **from a gold receipt**, by code, so the verdict is
a function of the receipt and the tree and not of a reader's eye:

1. the DEV macro recall@K paired-bootstrap delta ``candidate - control`` has a
   CI95 lower bound strictly above zero;
2. the macro precision@K drop ``control - candidate`` is at most
   :data:`PRECISION_DROP_MAX` absolute;
3. the explicit door holds on the tree that produced the receipt -- the same
   three assertions ``tests/test_query_planner_or_fallback.py`` pins, re-run
   here against the live planner;
4. ``tests/golden/session_search_pre_planner.json`` is byte-identical to the
   form committed at ``d060d3f2``.

The same registration's prose names two rejects that sit *in front of* the
clauses, and the council review of 2026-09-15 asked for them to be encoded
rather than left to a reader: "crashes appeared" is a reject, and "a different
arm won" is a new hypothesis, never an adoption under this rule. :func:`judge`
therefore checks **eligibility** first -- the pair judged is the registered
pair, and neither arm crashed -- and names a failed check in ``decided_by``
ahead of any failed clause. The four clauses keep their names and numbers.

A receipt that cannot be judged -- a non-finite number, a reversed interval, a
crash count its own per-item rows contradict -- is refused with
``ValueError``, the way a missing arm is refused with ``KeyError``: a
malformed receipt is an error, never a verdict, so the door fails closed.

It also derives the *committed* form of the receipt: the raw gold receipt with
every digest written in ``sha256:<hex>`` notation and the commit as
``git:<sha>``, plus the verdict block. The repository's ``detect-secrets`` hook
flags any bare quoted hex string (a 16-character prefix included), and a
prefixed digest is both hook-clean and checkable in full.
"""

from __future__ import annotations

import copy
import hashlib
import math
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agent_session_tools.retrieval import QueryPlan, plan_query

from . import K

if TYPE_CHECKING:
    from collections.abc import Mapping

#: Clause 2's frozen threshold: absolute macro precision@K drop the candidate may cost.
PRECISION_DROP_MAX = 0.05
#: Clause 4's fixture and its committed digest (a content hash of a public file).
PRE_PLANNER_GOLDEN_RELATIVE = Path(
    "packages/agent-session-tools/tests/golden/session_search_pre_planner.json"
)
PRE_PLANNER_GOLDEN_SHA256 = "7152dae40af4918dffd6a51cc4b7d399c433384a3caa9a7ca64164e7a56795f6"  # pragma: allowlist secret
#: Where the rule these clauses implement is written down.
RULE = "docs/architecture/session-memory/receipts/lexical/preregistration-2026-09-15.md"
#: The one pair :data:`RULE` registers; any other pair is compared, never adopted.
DEFAULT_CANDIDATE = "mcp:and_then_prose_or"
DEFAULT_CONTROL = "mcp"

#: Eligibility checks from the registration's prose, named in ``decided_by``
#: when they fail. They are not clauses and do not renumber the four.
ELIGIBILITY_REGISTERED_PAIR = "eligibility:registered_pair"
ELIGIBILITY_NO_CRASHES = "eligibility:no_crashes"

#: Receipt keys whose values are bare hex digests in the raw gold receipt.
_SHA256_KEYS = frozenset({"sha256", "fingerprint", "metrics_sha256"})
_GIT_KEYS = frozenset({"git_commit"})


def repo_root() -> Path:
    return Path(__file__).resolve().parents[5]


def explicit_door_holds() -> dict[str, bool]:
    """Clause 3, re-evaluated on the live planner: the three S.1 explicit-door assertions."""
    prefixed = plan_query("fts:error OR authentication")
    return {
        "fts_prefix_is_verbatim": prefixed
        == QueryPlan(explicit=True, terms=(), queries=("error OR authentication",)),
        "uppercase_operator_outside_quotes_is_verbatim": (
            plan_query("error OR authentication").explicit
            and plan_query('"exact phrase" OR authentication').explicit
            and plan_query("error OR authentication").queries
            == ("error OR authentication",)
        ),
        "quoted_operator_is_not_explicit": (
            not plan_query('"error OR warning" recovery').explicit
            and not plan_query('"error or warning" recovery').explicit
        ),
    }


def golden_sha256(root: Path | None = None) -> str:
    """The current digest of the pre-planner golden under ``root``."""
    path = (root or repo_root()) / PRE_PLANNER_GOLDEN_RELATIVE
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _finite(value: Any, what: str) -> float:
    """``value`` as a finite float, or ``ValueError`` naming ``what`` was wrong.

    A string is refused even when it would parse: a receipt is written by
    :mod:`.receipt` as numbers, and a number that arrives as text has been
    through something the registration did not name. ``+inf`` is refused
    because ``inf > 0`` is true and would otherwise satisfy clause 1.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{what} is not a number: {value!r}")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{what} is not finite: {value!r}")
    return number


def _interval(value: Any, what: str) -> tuple[float, float]:
    """``value`` as a finite ``(lower, upper)`` with ``lower <= upper``."""
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError(f"{what} is not a [lower, upper] pair: {value!r}")
    lower = _finite(value[0], f"{what}[0]")
    upper = _finite(value[1], f"{what}[1]")
    if lower > upper:
        raise ValueError(f"{what} is reversed: lower {lower!r} > upper {upper!r}")
    return lower, upper


def _crashes(arm: Mapping[str, Any], name: str) -> int:
    """The arm's crash count, cross-checked against its own per-item rows.

    :func:`.gold.score_arm` writes a crash twice -- ``error_kind`` on the item
    and the total in ``metrics.crashes`` -- so the two must agree; a count the
    rows contradict is a receipt that has been edited, not measured.
    """
    declared = arm["metrics"]["crashes"]
    if isinstance(declared, bool) or not isinstance(declared, int) or declared < 0:
        raise ValueError(f"arm {name!r}: metrics.crashes is not a count: {declared!r}")
    per_item = arm.get("per_item")
    if isinstance(per_item, dict):
        counted = sum(
            1
            for row in per_item.values()
            if isinstance(row, dict) and row.get("error_kind") is not None
        )
        if counted != declared:
            raise ValueError(
                f"arm {name!r}: metrics.crashes is {declared} but {counted} per-item "
                "rows carry an error_kind"
            )
    return declared


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def judge(
    receipt: dict[str, Any],
    *,
    candidate: str = DEFAULT_CANDIDATE,
    control: str = DEFAULT_CONTROL,
    k: int = K,
    root: Path | None = None,
) -> dict[str, Any]:
    """Evaluate eligibility, then the four frozen clauses, against ``receipt``.

    Never adopts on a missing arm (``KeyError``) or a malformed receipt
    (``ValueError``). ``decided_by`` names every eligibility check and every
    clause that failed, in that order (the rule is a conjunction, so any one
    of them decides a reject); on an adopt it says so explicitly. The four
    clauses are computed and reported for any pair -- that is the generic
    comparison -- but only the registered pair can be labelled ``adopt``.
    """
    arms = receipt["arms"]
    for name in (candidate, control):
        if name not in arms:
            raise KeyError(
                f"arm {name!r} is not in the receipt; present: {sorted(arms)}"
            )
    ineligible: list[str] = []
    if (candidate, control) != (DEFAULT_CANDIDATE, DEFAULT_CONTROL):
        ineligible.append(
            f"{ELIGIBILITY_REGISTERED_PAIR} (the rule registers {DEFAULT_CANDIDATE} "
            f"vs {DEFAULT_CONTROL}; judged {candidate} vs {control})"
        )
    crashes = {name: _crashes(arms[name], name) for name in (candidate, control)}
    if any(crashes.values()):
        crashed = ", ".join(
            f"{name} crashed on {_plural(count, 'item')}"
            for name, count in crashes.items()
            if count
        )
        ineligible.append(f"{ELIGIBILITY_NO_CRASHES} ({crashed})")

    pair = f"{candidate}_vs_{control}"
    recall = receipt["comparisons"][pair]
    lower, _upper = _interval(recall["ci95"], f"comparisons.{pair}.ci95")
    _finite(recall["point"], f"comparisons.{pair}.point")
    precision_key = f"precision@{k}"
    candidate_precision = _finite(
        arms[candidate]["metrics"][precision_key]["macro"],
        f"arms.{candidate}.metrics.{precision_key}.macro",
    )
    control_precision = _finite(
        arms[control]["metrics"][precision_key]["macro"],
        f"arms.{control}.metrics.{precision_key}.macro",
    )
    drop = control_precision - candidate_precision
    door = explicit_door_holds()
    current_golden = golden_sha256(root)
    clauses: dict[str, dict[str, Any]] = {
        "1_recall_ci95_lower_above_zero": {
            "holds": lower > 0.0,
            "point": recall["point"],
            "ci95": list(recall["ci95"]),
            "resamples": recall["resamples"],
            "seed": recall["seed"],
            "clusters": recall["clusters"],
            # The programme's stronger rule, reported beside D-12's weaker one.
            "established_lift_at_min_lift": recall.get("established"),
        },
        "2_precision_drop_at_most_0.05": {
            "holds": drop <= PRECISION_DROP_MAX,
            "control": control_precision,
            "candidate": candidate_precision,
            "drop": drop,
            "max_drop": PRECISION_DROP_MAX,
        },
        "3_explicit_door_tests_pass": {"holds": all(door.values()), **door},
        "4_pre_planner_golden_unchanged": {
            "holds": current_golden == PRE_PLANNER_GOLDEN_SHA256,
            "expected": f"sha256:{PRE_PLANNER_GOLDEN_SHA256}",
            "actual": f"sha256:{current_golden}",
        },
    }
    failed = [name for name, clause in clauses.items() if not clause["holds"]]
    adopt = not ineligible and not failed
    return {
        "adopt": adopt,
        "candidate": candidate,
        "control": control,
        "k": k,
        "rule": RULE,
        "clauses": clauses,
        "decided_by": [*ineligible, *failed] or ["all four clauses hold"],
    }


def prefix_digests(value: Any) -> Any:
    """Rewrite bare hex digests as ``sha256:<hex>`` / ``git:<sha>``, recursively.

    Idempotent: a value that already carries its prefix is left alone, so the
    derivation can be re-run over its own output.
    """
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, inner in value.items():
            if key in _SHA256_KEYS and isinstance(inner, str) and inner:
                out[key] = inner if inner.startswith("sha256:") else f"sha256:{inner}"
            elif key in _GIT_KEYS and isinstance(inner, str) and inner:
                out[key] = inner if inner.startswith("git:") else f"git:{inner}"
            else:
                out[key] = prefix_digests(inner)
        return out
    if isinstance(value, list):
        return [prefix_digests(inner) for inner in value]
    return value


def derive_receipt(
    raw: dict[str, Any], raw_bytes: bytes, verdict: dict[str, Any], *, raw_path: str
) -> dict[str, Any]:
    """The committed receipt: the raw one, digests prefixed, plus the verdict.

    ``metrics_sha256`` keeps the raw receipt's value (it is the digest of the
    raw stable view, and stays checkable against the raw file named in
    ``derived_from``); the derived document does not claim a digest of itself.
    """
    out = prefix_digests(copy.deepcopy(raw))
    out["derived_from"] = {
        "raw_receipt": raw_path,
        "raw_sha256": f"sha256:{hashlib.sha256(raw_bytes).hexdigest()}",
        "digest_notation": "sha256:<hex> for content digests, git:<sha> for commits; "
        "values are otherwise byte-for-byte the raw receipt's",
    }
    out["verdict"] = verdict
    return out


def format_verdict(verdict: dict[str, Any]) -> str:
    """The console reading of a verdict, one clause per line, ``adopt:`` last."""
    lines = [
        f"rule: {verdict['rule']}",
        f"pair: {verdict['candidate']} vs {verdict['control']}",
    ]
    for name, clause in verdict["clauses"].items():
        detail = {key: value for key, value in clause.items() if key != "holds"}
        lines.append(f"  {name}: {'HOLDS' if clause['holds'] else 'FAILS'}  {detail}")
    lines.append(f"decided_by: {', '.join(verdict['decided_by'])}")
    lines.append(f"adopt: {'true' if verdict['adopt'] else 'false'}")
    return "\n".join(lines)


__all__ = [
    "DEFAULT_CANDIDATE",
    "DEFAULT_CONTROL",
    "ELIGIBILITY_NO_CRASHES",
    "ELIGIBILITY_REGISTERED_PAIR",
    "PRECISION_DROP_MAX",
    "PRE_PLANNER_GOLDEN_RELATIVE",
    "PRE_PLANNER_GOLDEN_SHA256",
    "RULE",
    "derive_receipt",
    "explicit_door_holds",
    "format_verdict",
    "golden_sha256",
    "judge",
    "prefix_digests",
    "repo_root",
]
