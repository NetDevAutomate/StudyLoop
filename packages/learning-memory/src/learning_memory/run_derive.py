"""Run the deterministic derivation over a store, and build the labelling fixture.

    python -m learning_memory.run_derive \\
        --store ~/.local/share/studyloop/knowledge-proof/learning-memory.db \\
        --receipt ~/.local/share/studyloop/knowledge-proof/derive-v1-receipt.json \\
        [--fixture tests/fixtures/derive_label_set.json] [--limit N]

The fixture is a deterministic sample (seed 20260910) of 60 exchanges for the
ORCHESTRATOR to hand-label: 20 from claude_code, 20 from codex+kiro_cli, 20 from
every other harness. Its ``label`` objects are left null on purpose -- a model
filling in its own answer key would measure nothing.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import random
import sys
from typing import Any

from learning_memory import Store
from learning_memory.derive import (
    DERIVATION_VERSION,
    derive_all,
    load_vocabulary,
    split_exchanges,
    strip_user_wrapper,
)
from learning_memory.derive import StoredEvent as _StoredEvent

FIXTURE_SEED = 20260910
FIXTURE_PER_GROUP = 20
GROUPS: tuple[tuple[str, tuple[str, ...] | None], ...] = (
    ("claude_code", ("claude_code",)),
    ("codex_kiro", ("codex", "kiro_cli")),
    ("other_harnesses", None),
)
TEXT_CAP = 400


def _sample_sessions(store: Store, harnesses: tuple[str, ...] | None) -> list[tuple[str, str]]:
    """Deterministic ``(session_id, harness)`` list: sessions with a threaded exchange."""
    if harnesses is None:
        rows = store.connection.execute(
            """
            SELECT DISTINCT x.session_id, s.harness FROM exchanges x
            JOIN sessions s ON s.id = x.session_id
            WHERE x.derivation_version = ?
              AND x.resolved IS NOT NULL
              AND s.harness NOT IN ('claude_code', 'codex', 'kiro_cli')
            ORDER BY x.session_id
            """,
            (DERIVATION_VERSION,),
        ).fetchall()
    else:
        placeholders = ",".join("?" * len(harnesses))
        rows = store.connection.execute(
            f"""
            SELECT DISTINCT x.session_id, s.harness FROM exchanges x
            JOIN sessions s ON s.id = x.session_id
            WHERE x.derivation_version = ?
              AND x.resolved IS NOT NULL
              AND s.harness IN ({placeholders})
            ORDER BY x.session_id
            """,
            (DERIVATION_VERSION, *harnesses),
        ).fetchall()
    return [(str(row["session_id"]), str(row["harness"])) for row in rows]


def build_fixture(store: Store) -> dict[str, Any]:
    """60 exchanges for hand labelling, sampled reproducibly from the real store.

    Within a group the sample is stratified by harness (round-robin over harnesses,
    each shuffled with the same seed) rather than drawn flat. Flat sampling of
    "everything else" returned 14 of 20 from litellm-proxy, whose sessions are
    near-identical probe prompts -- 20 minutes of a human's labelling time spent on
    one shape. Still fully deterministic for the seed.
    """
    rng = random.Random(FIXTURE_SEED)  # nosec B311 - seeded deterministic fixture sampling, not cryptography
    items: list[dict[str, Any]] = []
    for group_name, harnesses in GROUPS:
        by_harness: dict[str, list[tuple[str, int]]] = {}
        for session_id, harness in _sample_sessions(store, harnesses):
            for row in store.connection.execute(
                "SELECT turn_id FROM exchanges WHERE session_id = ? AND derivation_version = ?"
                " AND resolved IS NOT NULL ORDER BY turn_id",
                (session_id, DERIVATION_VERSION),
            ):
                by_harness.setdefault(harness, []).append((session_id, int(row["turn_id"])))

        for candidates in by_harness.values():
            candidates.sort()
            rng.shuffle(candidates)
        chosen: list[tuple[str, int]] = []
        cursors = dict.fromkeys(sorted(by_harness), 0)
        while len(chosen) < FIXTURE_PER_GROUP and any(
            cursors[harness] < len(by_harness[harness]) for harness in cursors
        ):
            for harness in sorted(cursors):
                if len(chosen) >= FIXTURE_PER_GROUP:
                    break
                index = cursors[harness]
                if index < len(by_harness[harness]):
                    chosen.append(by_harness[harness][index])
                    cursors[harness] = index + 1

        for session_id, turn_id in sorted(chosen):
            items.append(_fixture_item(store, group_name, session_id, turn_id))
    return {
        "fixture": "derive_label_set",
        "derivation_version": DERIVATION_VERSION,
        "seed": FIXTURE_SEED,
        "sampling": "stratified by harness within each group, round-robin, seeded shuffle",
        "labelled_by": None,
        "instructions": (
            "Fill each item's `label` object by reading the texts only. Leave a field null "
            "to skip it; the accuracy test reads non-null fields and skips the rest. "
            "`concepts` is a list of canonical vocabulary terms you would expect to be tagged."
        ),
        "groups": [name for name, _ in GROUPS],
        "items": items,
    }


def _fixture_item(store: Store, group: str, session_id: str, turn_id: int) -> dict[str, Any]:
    conn = store.connection
    harness = str(
        conn.execute("SELECT harness FROM sessions WHERE id = ?", (session_id,)).fetchone()[
            "harness"
        ]
    )
    events = [
        _StoredEvent(
            id=int(row["id"]),
            turn_id=int(row["turn_id"]),
            seq=int(row["seq"]),
            kind=str(row["kind"]),
            text=str(row["text"]),
            tool_name=row["tool_name"],
            ts=row["ts"],
        )
        for row in conn.execute(
            "SELECT id, turn_id, seq, kind, text, tool_name, ts FROM events"
            " WHERE session_id = ? ORDER BY seq, id",
            (session_id,),
        )
    ]
    exchange = next(
        (
            candidate
            for candidate in split_exchanges(events)
            if candidate.turn_id == turn_id and candidate.quarantine_reason is None
        ),
        None,
    )
    if exchange is None:  # pragma: no cover - the SQL only offers threaded turns
        raise KeyError(f"{session_id} turn {turn_id} is not a threaded exchange")
    vocab = load_vocabulary()
    prose = [
        event.text[:TEXT_CAP]
        for event in exchange.events
        if event.kind == "assistant_prose" and event.text.strip()
    ][:3]
    return {
        "group": group,
        "harness": harness,
        "session_id": session_id,
        "turn_id": turn_id,
        "user_text": strip_user_wrapper(exchange.events[0].text)[:TEXT_CAP],
        "assistant_prose": prose,
        "tool_calls": [
            event.tool_name
            for event in exchange.events
            if event.kind == "tool_call" and event.tool_name
        ][:10],
        "derived": {
            "is_question": exchange.is_question,
            "had_error": exchange.had_error,
            "retried": exchange.retried,
            "resolved": exchange.resolved,
            "concepts": sorted(
                {
                    canonical
                    for canonical, _ in vocab.tag(
                        [e.text for e in exchange.events if e.kind in ("user", "assistant_prose")]
                    )
                }
            ),
        },
        "label": {
            "is_question": None,
            "had_error": None,
            "retried": None,
            "resolved": None,
            "concepts": None,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", required=True)
    parser.add_argument("--receipt", required=True)
    parser.add_argument("--fixture", default=None, help="also write the labelling fixture here")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--progress-every", type=int, default=1000)
    args = parser.parse_args(argv)

    store_path = pathlib.Path(args.store).expanduser()
    if not store_path.exists():
        raise SystemExit(f"no store at {store_path}")
    receipt_path = pathlib.Path(args.receipt).expanduser()
    receipt_path.parent.mkdir(parents=True, exist_ok=True)

    store = Store.connect(store_path)
    store.install()  # verifies the schema version rather than creating anything
    try:
        receipt = derive_all(store, limit=args.limit, progress_every=args.progress_every)
        receipt["store"] = str(store_path)
        receipt["store_bytes"] = store_path.stat().st_size
        receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        if args.fixture:
            fixture_path = pathlib.Path(args.fixture).expanduser()
            fixture_path.parent.mkdir(parents=True, exist_ok=True)
            fixture = build_fixture(store)
            fixture_path.write_text(json.dumps(fixture, indent=2) + "\n", encoding="utf-8")
            print(f"  fixture: {len(fixture['items'])} items -> {fixture_path}")
    finally:
        store.close()

    exchanges = receipt["exchanges"]
    print(
        f"derived {receipt['sessions']['derived']}/{receipt['sessions']['in_store']} sessions "
        f"in {receipt['wall_seconds']}s"
    )
    print(
        f"  exchanges {exchanges['total']} "
        f"(threaded {exchanges['threaded']}, quarantined {exchanges['quarantined']})"
    )
    print(
        f"  concepts {receipt['concepts']['distinct_tagged']} distinct, "
        f"{receipt['concepts']['total_tags']} tags"
    )
    print(
        f"  recurrence candidates {receipt['recurrence']['candidates']} "
        f"basis {receipt['recurrence']['day_gap_basis']}"
    )
    print(
        f"  intent {receipt['intent_outcome']['intent_fill_rate']:.1%} "
        f"outcome {receipt['intent_outcome']['outcome_fill_rate']:.1%}"
    )
    print(f"  receipt: {receipt_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
