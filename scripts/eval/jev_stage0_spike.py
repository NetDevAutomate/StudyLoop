"""Stage 0 access spike for Jev (TypeSafe System One) against StudyLoop's teach-back rubric.

Disposable. Proves: the pre-release account answers, the SDK surface matches the docs,
the five 1-4 rubric dimensions map onto Score legends, and how much identical calls move.

Reads TYPESAFE_API_KEY from the environment (the SDK does this itself). The value is
never printed. Writes a JSON receipt next to this file.
"""

from __future__ import annotations

import json
import statistics
import sys
import time
from importlib.metadata import version
from pathlib import Path

from typesafe_sdk import Noul, Score, TypeSafeClient

MODEL = "jev-1.13.0"  # pinned on purpose: thresholds must never be tuned against an alias
REPEATS = 3
_RECEIPTS = Path(__file__).resolve().parents[2] / "docs" / "architecture" / "jev-judge" / "receipts"
OUT = _RECEIPTS / "stage0-receipt.json"

# Synthetic teach-back: a networking-background learner explaining Python decorators.
# One factual error is planted on purpose (decoration happens at definition time, not
# per call) so Accuracy should NOT score top and the error Noul should fire.
STATE = (
    "OK so a decorator is basically a function that takes another function and hands "
    "back a new function with extra behaviour wrapped around it. The way I think about "
    "it is like a middlebox on a network path - say a firewall or a WAF sitting in front "
    "of a web server. The server doesn't know it's there, traffic still reaches it, but "
    "the middlebox gets to inspect or modify what goes in and what comes out. The @ "
    "syntax is just sugar: @timer above def fetch() is the same as writing "
    "fetch = timer(fetch) after the definition. The wrapping happens every time you call "
    "the decorated function, not when it's defined, so you pay the wrapping cost on each "
    "call. Inside the decorator you define an inner wrapper that takes *args and "
    "**kwargs, does the extra work - say starting a clock - calls the original, then does "
    "the after-work and returns the result. You need functools.wraps on the wrapper "
    "otherwise the decorated function loses its name and docstring, which bites you when "
    "you introspect it or when tooling reads __name__. Where I'd actually use it: in our "
    "network CLI we retry flaky API calls to the controller in three places with "
    "copy-pasted try/except loops. A @retry(attempts=3, backoff=2) decorator would "
    "collapse that into one place, the same way you'd put NAT on the edge router once "
    "instead of configuring it on every host."
)

# Level descriptors are VERBATIM from agents/shared/teach-back-protocol.md
# (1 Recitation, 2 Paraphrase, 3 Explanation, 4 Teaching). Jev legends are 0-indexed,
# so StudyLoop score = jev score + 1.
RUBRIC: dict[str, tuple[str, list[str]]] = {
    "accuracy": (
        "How factually accurate is the learner's explanation of Python decorators?",
        [
            "Significant errors or omissions",
            "Mostly correct, minor gaps",
            "Accurate with nuanced detail",
            "Accurate and anticipates edge cases",
        ],
    ),
    "own_words": (
        "To what extent does the learner use their own language and framings rather "
        "than textbook phrasing?",
        [
            "Verbatim repetition of source material",
            "Mixed: some own words, some parroted",
            "Consistently uses own language",
            "Creates novel analogies or framings",
        ],
    ),
    "structure": (
        "How well organised is the logical flow of the explanation?",
        [
            "Disconnected facts, no logical flow",
            "Some structure but relationships unclear",
            "Clear logical flow showing cause/effect",
            "Builds narrative sequenced for the listener",
        ],
    ),
    "depth": (
        "How deeply does the explanation go beyond WHAT the concept is?",
        [
            "States WHAT only",
            "States WHAT and partially HOW",
            "Explains WHAT, HOW, and WHY",
            "Addresses WHY, tradeoffs, when NOT to use",
        ],
    ),
    "transfer": (
        "How well does the learner apply the concept to a new context of their own?",
        [
            "Cannot apply to new context",
            "Applies with heavy hints",
            "Independently applies to related scenario",
            "Generates novel examples or counter-examples",
        ],
    ),
}

QUESTIONS = {
    name: Score(instructions=instr, criteria=levels) for name, (instr, levels) in RUBRIC.items()
}
# Positive control: the planted error should be detected.
QUESTIONS["has_factual_error"] = Noul(
    instructions=(
        "The explanation contains at least one factually incorrect statement about how "
        "Python decorators work."
    )
)
# Negative control: must be near 0, or the Noul is just agreeing with everything.
QUESTIONS["not_english"] = Noul(
    instructions="The explanation is written in a language other than English."
)


def _dump(obj: object) -> object:
    """Best-effort raw payload: pydantic model_dump, else vars, else repr."""
    if hasattr(obj, "model_dump"):
        return obj.model_dump()  # type: ignore[attr-defined]
    try:
        return json.loads(json.dumps(vars(obj), default=str))
    except TypeError:
        return repr(obj)


def call_once(client: TypeSafeClient) -> dict:
    t0 = time.perf_counter()
    try:
        resp = client.system_one(state=STATE, questions=QUESTIONS, model=MODEL)
    except TypeError:
        # SDK may not take model= on this call; fall back and record what answered.
        resp = client.system_one(state=STATE, questions=QUESTIONS)
    ms = round((time.perf_counter() - t0) * 1000)
    answers: dict[str, dict] = {}
    for name, ans in resp.answers.items():
        row: dict = {}
        for attr in ("score", "confidence", "noul", "choice", "probabilities", "legend"):
            if hasattr(ans, attr):
                row[attr] = getattr(ans, attr)
        answers[name] = row
    return {
        "latency_ms": ms,
        "model_answered": getattr(resp, "model", None),
        "usage": _dump(getattr(resp, "usage", None)),
        "answers": answers,
        "raw": _dump(resp),
    }


def main() -> int:
    sdk_ver = version("typesafe-sdk")
    calls: list[dict] = []
    with TypeSafeClient() as client:
        for i in range(REPEATS):
            try:
                calls.append(call_once(client))
            except Exception as exc:  # spike: report type + message only, never headers
                print(f"call {i + 1} FAILED: {type(exc).__name__}: {str(exc)[:300]}")
                receipt = {
                    "sdk": sdk_ver,
                    "model_requested": MODEL,
                    "calls": calls,
                    "failed_at": i + 1,
                }
                OUT.write_text(json.dumps(receipt, indent=2, default=str))
                return 1

    # Spread across identical calls, per question.
    spread: dict[str, dict] = {}
    for name in QUESTIONS:
        key = "noul" if name in ("has_factual_error", "not_english") else "score"
        vals = [c["answers"][name][key] for c in calls]
        confs = [c["answers"][name].get("confidence") for c in calls]
        spread[name] = {
            "values": vals,
            "min": min(vals),
            "max": max(vals),
            "range": round(max(vals) - min(vals), 4),
            "stdev": round(statistics.pstdev(vals), 4) if len(vals) > 1 else 0.0,
            "confidence": confs,
        }

    receipt = {
        "sdk": sdk_ver,
        "python": sys.version.split()[0],
        "model_requested": MODEL,
        "repeats": REPEATS,
        "state_chars": len(STATE),
        "calls": calls,
        "spread": spread,
    }
    OUT.write_text(json.dumps(receipt, indent=2, default=str))

    # Human summary.
    print(f"sdk typesafe-sdk=={sdk_ver}  python {receipt['python']}")
    print(f"model requested {MODEL} / answered {calls[0]['model_answered']}")
    print(f"latency ms: {[c['latency_ms'] for c in calls]}   usage(call 1): {calls[0]['usage']}")
    print()
    print("| dimension | jev score x3 | StudyLoop 1-4 (mean) | confidence x3 | range |")
    print("|---|---|---|---|---|")
    for name in RUBRIC:
        s = spread[name]
        mean_sl = round(statistics.mean(s["values"]) + 1, 2)
        print(
            f"| {name} | {[round(v, 3) for v in s['values']]} | {mean_sl} | "
            f"{[round(c, 3) if c is not None else None for c in s['confidence']]} | {s['range']} |"
        )
    for name in ("has_factual_error", "not_english"):
        s = spread[name]
        print(f"| noul:{name} | {[round(v, 3) for v in s['values']]} | - | - | {s['range']} |")
    print(f"\nreceipt: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
