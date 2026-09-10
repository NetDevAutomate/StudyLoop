"""Claims-writer harness: the deterministic half of a writer run. Calls NO model.

Binding spec: ``docs/architecture/session-memory/receipts/claims-writer-spec-v1.md``.
Population file: ``docs/architecture/session-memory/receipts/poc-set-g2.json``.
Prompt: ``writer_prompt_v1.md`` beside this module; its sha256 is recorded on every
receipt and is the ``<sha8>`` in the ``writer`` field of every claim row.

The division of labour, from the spec: **the model proposes, the harness disposes.**
The model receives one session's citable prose and its derived flags, and returns
JSON. Everything that decides whether a claim EXISTS -- schema, citation binding,
duplicate detection, insertion -- happens here and in the store's triggers, so a
writer cannot talk its way past a constraint.

This module reads two things only: the store, and the population file it is handed
on the command line. It cannot reach an answer key: there is no such path in it, and
a test greps this file to keep it that way.

Commands::

    population  --store S --poc P --out pop.json
    packet      --store S --session ID --out packet.json
    render      --packet packet.json --prompt writer_prompt_v1.md --out prompt.txt
    ingest      --store S --session ID --response r.json --packet p.json \\
                --writer sonnet5/writer-v1/<sha8> --receipt run.json
    summarise   --receipts DIR --poc P --out g2-progress.json
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import pathlib
import re
import sqlite3
import sys
from typing import Any, Final

from learning_memory import (
    CitationError,
    ClaimValidationError,
    DuplicateClaimError,
    Store,
)
from learning_memory.derive import DERIVATION_VERSION

PROMPT_PATH: Final = pathlib.Path(__file__).with_name("writer_prompt_v1.md")

CLAIM_KINDS: Final[frozenset[str]] = frozenset(
    {"Problem", "Finding", "Decision", "Procedure", "Preference"}
)
MAX_TITLE: Final = 120
MAX_STATEMENT: Final = 500
MIN_TAGS: Final = 2
MAX_TAGS: Final = 5
MIN_CONFIDENCE: Final = 0.5
MAX_CONFIDENCE: Final = 1.0
MAX_CLAIMS: Final = 8
PACKET_TEXT_BUDGET: Final = 48 * 1024
"""48 KiB of evidence text per packet (spec, "Budgets")."""

ROLE_BY_KIND: Final[dict[str, str]] = {"user": "learner", "assistant_prose": "assistant"}

EVIDENCE_DELIMITER: Final = "===== EVIDENCE ====="
FLAGS_DELIMITER: Final = "===== EXCHANGE FLAGS ====="
INSTRUCTION: Final = "Respond with the JSON only."

_FENCE_OPEN: Final = re.compile(r"^\s*```(?:json)?\s*\n", re.IGNORECASE)
_FENCE_CLOSE: Final = re.compile(r"\n\s*```\s*$")
_TAG_OK: Final = re.compile(r"^[a-z0-9][a-z0-9._+-]*$")


# --------------------------------------------------------------------- utilities


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_file(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


def _write_json(path: pathlib.Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def prompt_sha256(prompt: pathlib.Path = PROMPT_PATH) -> str:
    return _sha256_file(prompt)


def writer_id(prompt: pathlib.Path = PROMPT_PATH) -> str:
    """The ``writer`` string the spec mandates on every claim row."""
    return f"sonnet5/writer-v1/{prompt_sha256(prompt)[:8]}"


# -------------------------------------------------------------------- population


def population_order(store: Store, poc: pathlib.Path) -> dict[str, Any]:
    """Ingested population session ids, ordered by ``sha256(session_id)`` ascending.

    The order is a pure function of the ids, so it is reproducible by anyone holding
    the population file and carries no information about which sessions are easy.
    """
    payload = json.loads(poc.read_text(encoding="utf-8"))
    candidates: list[str] = list(payload["session_ids"])
    prose_subset = set(payload.get("prose_ge10_session_ids", []))
    present = {
        str(row["id"]) for row in store.connection.execute("SELECT id FROM sessions").fetchall()
    }
    ingested = sorted(
        (sid for sid in candidates if sid in present), key=lambda sid: _sha256_text(sid)
    )
    return {
        "order": ingested,
        "n": len(ingested),
        "set_sha256": payload.get("set_sha256"),
        "poc_file_sha256": _sha256_file(poc),
        "poc_recorded_ingested": payload.get("ingested_in_store"),
        "denominators": payload.get("denominators", {}),
        "prose_ge10": [sid for sid in ingested if sid in prose_subset],
        "not_ingested": sorted(sid for sid in candidates if sid not in present),
    }


# ------------------------------------------------------------------------ packet


def build_packet(
    store: Store, session_id: str, prompt: pathlib.Path = PROMPT_PATH
) -> dict[str, Any]:
    """One session's citable prose plus its derived flags. Nothing else.

    Evidence comes from ``Store.visible_evidence``, which already carries the
    anchoring event's ``kind``, ``turn_id`` and ``seq``, so the role is a direct
    mapping rather than a second join.
    """
    row = store.connection.execute(
        "SELECT harness FROM sessions WHERE id = ?", (session_id,)
    ).fetchone()
    if row is None:
        raise KeyError(f"no session {session_id!r} in the store")

    rows = sorted(
        store.visible_evidence(session_id),
        key=lambda item: (int(item["turn_id"]), int(item["seq"])),
    )
    kept: list[dict[str, Any]] = []
    used = 0
    for item in rows:
        text = str(item["body"])
        size = len(text.encode("utf-8"))
        if kept and used + size > PACKET_TEXT_BUDGET:
            break
        kept.append(
            {
                "evidence_id": str(item["id"]),
                "role": ROLE_BY_KIND.get(str(item["kind"]), str(item["kind"])),
                "turn_id": int(item["turn_id"]),
                "text": text,
            }
        )
        used += size

    packet: dict[str, Any] = {
        "session_id": session_id,
        "harness": str(row["harness"]),
        "evidence": kept,
        "exchanges": _exchange_flags(store, session_id),
        "truncated": len(kept) < len(rows),
        "rows_dropped": len(rows) - len(kept),
        "bytes": used,
        "derivation_version": DERIVATION_VERSION,
        "prompt_sha256": prompt_sha256(prompt),
    }
    packet["packet_sha256"] = _sha256_text(_canonical(packet))
    return packet


def _exchange_flags(store: Store, session_id: str) -> list[dict[str, Any]]:
    """Derived flags per threaded exchange, with concept tags. Quarantines omitted."""
    flags: list[dict[str, Any]] = []
    for row in store.connection.execute(
        """
        SELECT id, turn_id, is_question, had_error, resolved
        FROM exchanges
        WHERE session_id = ? AND derivation_version = ? AND resolved IS NOT NULL
        ORDER BY turn_id
        """,
        (session_id, DERIVATION_VERSION),
    ).fetchall():
        concepts = [
            str(tag["canonical"])
            for tag in store.connection.execute(
                """
                SELECT DISTINCT c.canonical FROM concept_tags t
                JOIN concepts c ON c.id = t.concept_id
                WHERE t.exchange_id = ? ORDER BY c.canonical
                """,
                (int(row["id"]),),
            ).fetchall()
        ]
        flags.append(
            {
                "turn_id": int(row["turn_id"]),
                "is_question": bool(row["is_question"]),
                "had_error": bool(row["had_error"]),
                "resolved": bool(row["resolved"]),
                "concepts": concepts,
            }
        )
    return flags


# ------------------------------------------------------------------------ render


def render_prompt(packet: dict[str, Any], prompt: pathlib.Path = PROMPT_PATH) -> str:
    """The exact bytes the orchestrator hands to the model. Byte-deterministic."""
    parts: list[str] = [prompt.read_text(encoding="utf-8").rstrip("\n"), ""]
    parts.append(EVIDENCE_DELIMITER)
    parts.append(f"session={packet['session_id']} harness={packet['harness']}")
    parts.append("")
    for index, item in enumerate(packet["evidence"], start=1):
        parts.append(
            f"[E{index}] evidence_id={item['evidence_id']} "
            f"role={item['role']} turn={item['turn_id']}"
        )
        parts.append(str(item["text"]))
        parts.append("")
    parts.append(FLAGS_DELIMITER)
    parts.append("turn\tis_question\thad_error\tresolved\tconcepts")
    for flag in packet["exchanges"]:
        parts.append(
            "\t".join(
                [
                    str(flag["turn_id"]),
                    "yes" if flag["is_question"] else "no",
                    "yes" if flag["had_error"] else "no",
                    "yes" if flag["resolved"] else "no",
                    ", ".join(flag["concepts"]),
                ]
            )
        )
    parts.append("")
    parts.append(INSTRUCTION)
    return "\n".join(parts) + "\n"


# ------------------------------------------------------------------------ ingest


class ResponseError(Exception):
    """The model's response is not the declared shape. The whole run is refused."""


def parse_response(raw: str) -> tuple[list[Any], bool, int]:
    """Strictly parse ``{"claims": [...]}``. Returns ``(claims, fence_stripped, dropped_over_cap)``.

    More than ``MAX_CLAIMS`` claims: keep the first ``MAX_CLAIMS`` in the writer's own order
    and record how many were dropped. (Pilot batch 1 deviation from spec v1, which read the
    cap as refuse-the-response: session 00 proposed 9 claims with 10/10 citations bound and
    lost all of them to a near-miss. Truncation lets the per-claim resolver judge each one.)

    One leading ```` ```json ```` fence and its trailing ```` ``` ```` are stripped and
    recorded -- models emit them habitually and the spec says to record, not to
    forgive silently. Anything else that is not the declared object is refused.
    """
    text = raw.strip()
    fence_stripped = False
    opened = _FENCE_OPEN.match(text)
    if opened:
        text = text[opened.end() :]
        closed = _FENCE_CLOSE.search(text)
        if closed:
            text = text[: closed.start()]
        fence_stripped = True
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as err:
        raise ResponseError(f"not JSON: {err}") from err
    if not isinstance(payload, dict):
        raise ResponseError(f"top level is {type(payload).__name__}, expected an object")
    if set(payload) != {"claims"}:
        raise ResponseError(f"top-level keys are {sorted(payload)}, expected exactly ['claims']")
    claims = payload["claims"]
    if not isinstance(claims, list):
        raise ResponseError(f"'claims' is {type(claims).__name__}, expected a list")
    dropped_over_cap = max(0, len(claims) - MAX_CLAIMS)
    return claims[:MAX_CLAIMS], fence_stripped, dropped_over_cap


def validate_claim(claim: Any, evidence_ids: set[str]) -> tuple[str, str] | None:
    """Return ``(reason, detail)`` if the claim is out of contract, else ``None``."""
    if not isinstance(claim, dict):
        return ("not_an_object", f"claim is {type(claim).__name__}")
    expected = {"kind", "title", "statement", "tags", "confidence", "citations"}
    missing = expected - set(claim)
    if missing:
        return ("missing_fields", f"missing {sorted(missing)}")

    kind = claim["kind"]
    if kind not in CLAIM_KINDS:
        return ("bad_kind", f"{kind!r} not in {sorted(CLAIM_KINDS)}")

    title = claim["title"]
    if not isinstance(title, str) or not title.strip():
        return ("empty_title", "title must be a non-empty string")
    if len(title) > MAX_TITLE:
        return ("title_too_long", f"{len(title)} > {MAX_TITLE}")

    statement = claim["statement"]
    if not isinstance(statement, str) or not statement.strip():
        return ("empty_statement", "statement must be a non-empty string")
    if len(statement) > MAX_STATEMENT:
        return ("statement_too_long", f"{len(statement)} > {MAX_STATEMENT}")

    tags = claim["tags"]
    if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
        return ("bad_tags", "tags must be a list of strings")
    if not MIN_TAGS <= len(tags) <= MAX_TAGS:
        return ("tags_out_of_range", f"{len(tags)} tags, need {MIN_TAGS}..{MAX_TAGS}")
    if len(set(tags)) != len(tags):
        return ("tags_not_distinct", f"{tags}")
    bad_tag = next((tag for tag in tags if not _TAG_OK.match(tag)), None)
    if bad_tag is not None:
        return ("tag_not_lowercase_token", f"{bad_tag!r}")

    confidence = claim["confidence"]
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        return ("bad_confidence", f"{confidence!r} is not a number")
    if not MIN_CONFIDENCE <= float(confidence) <= MAX_CONFIDENCE:
        return ("confidence_out_of_range", f"{confidence} outside [0.5, 1.0]")

    citations = claim["citations"]
    if not isinstance(citations, list) or not citations:
        return ("no_citations", "at least one citation is required")
    for index, citation in enumerate(citations):
        if not isinstance(citation, dict):
            return ("bad_citation", f"citation {index} is {type(citation).__name__}")
        if set(citation) != {"evidence_id", "quote"}:
            return ("bad_citation", f"citation {index} keys {sorted(citation)}")
        if not isinstance(citation["quote"], str) or not citation["quote"]:
            return ("empty_quote", f"citation {index}")
        if citation["evidence_id"] not in evidence_ids:
            return (
                "citation_not_in_packet",
                f"citation {index} names {citation['evidence_id']!r}",
            )
    return None


def ingest_response(
    store: Store,
    session_id: str,
    packet: dict[str, Any],
    raw_response: str,
    writer: str,
) -> dict[str, Any]:
    """Validate and insert a response. Never partially inserts a claim.

    ``writer`` must carry the prompt's own sha8: a claim row labelled with a prompt
    that did not produce it is unfalsifiable provenance, so a mismatch fails the run
    rather than being recorded and shipped.
    """
    expected_writer_suffix = str(packet["prompt_sha256"])[:8]
    if not writer.endswith(expected_writer_suffix):
        raise ResponseError(
            f"writer {writer!r} does not end in the packet's prompt sha8 {expected_writer_suffix!r}"
        )
    if packet["session_id"] != session_id:
        raise ResponseError(f"packet is for {packet['session_id']!r}, run is for {session_id!r}")

    evidence_ids = {str(item["evidence_id"]) for item in packet["evidence"]}
    receipt: dict[str, Any] = {
        "receipt": "claims-writer-run",
        "session_id": session_id,
        "writer": writer,
        "prompt_sha256": packet["prompt_sha256"],
        "packet_sha256": packet["packet_sha256"],
        "claims_proposed": 0,
        "claims_inserted": 0,
        "inserted_claim_ids": [],
        "refused": [],
        "duplicates": 0,
        "recheck_mismatches": 0,
        "fence_stripped": False,
        "dropped_over_cap": 0,
        "response_error": None,
        "created_utc": _now(),
    }

    try:
        claims, fence_stripped, dropped_over_cap = parse_response(raw_response)
        receipt["dropped_over_cap"] = dropped_over_cap
    except ResponseError as err:
        receipt["response_error"] = str(err)
        return receipt
    receipt["fence_stripped"] = fence_stripped
    receipt["claims_proposed"] = len(claims)

    inserted: list[str] = []
    for index, claim in enumerate(claims):
        problem = validate_claim(claim, evidence_ids)
        if problem is not None:
            reason, detail = problem
            receipt["refused"].append({"index": index, "reason": reason, "detail": detail})
            continue
        try:
            claim_id = store.add_claim(
                session_id,
                claim["kind"],
                claim["title"],
                claim["statement"],
                list(claim["tags"]),
                float(claim["confidence"]),
                writer,
                [
                    {"evidence_id": citation["evidence_id"], "quote": citation["quote"]}
                    for citation in claim["citations"]
                ],
            )
        except DuplicateClaimError as err:
            receipt["duplicates"] += 1
            receipt["refused"].append(
                {"index": index, "reason": "duplicate", "detail": str(err)[:300]}
            )
            continue
        except CitationError as err:
            receipt["refused"].append(
                {
                    "index": index,
                    "reason": "citation_unbound",
                    "detail": "; ".join(
                        f"{problem.reason}: {problem.detail}" for problem in err.problems
                    )[:300],
                }
            )
            continue
        except ClaimValidationError as err:
            receipt["refused"].append(
                {"index": index, "reason": "claim_validation", "detail": str(err)[:300]}
            )
            continue
        except sqlite3.IntegrityError as err:  # a trigger refused it
            receipt["refused"].append(
                {"index": index, "reason": "store_refused", "detail": str(err)[:300]}
            )
            continue
        inserted.append(claim_id)

    receipt["claims_inserted"] = len(inserted)
    receipt["inserted_claim_ids"] = inserted
    receipt["recheck_mismatches"] = recheck_citations(store, inserted)
    return receipt


def recheck_citations(store: Store, claim_ids: list[str]) -> int:
    """Re-prove every citation inserted in this run using SQLite's own ``substr()``.

    The insert already passed the bound-proof trigger; this asks the database the
    question again, independently, after the transaction closed. It is the line on
    the receipt that makes "unbound writes = 0" a measurement rather than a promise.
    """
    if not claim_ids:
        return 0
    placeholders = ",".join("?" * len(claim_ids))
    row = store.connection.execute(
        f"""
        SELECT count(*) AS n
        FROM claim_citations c JOIN evidence e ON e.id = c.evidence_id
        WHERE c.claim_id IN ({placeholders})
          AND substr(e.body, c."start" + 1, c."end" - c."start") != c.quote
        """,
        tuple(claim_ids),
    ).fetchone()
    return int(row["n"])


# --------------------------------------------------------------------- summarise


def summarise_receipts(receipts_dir: pathlib.Path, poc: pathlib.Path) -> dict[str, Any]:
    """Aggregate run receipts into G2 progress on both declared denominators."""
    payload = json.loads(poc.read_text(encoding="utf-8"))
    denominators = payload.get("denominators", {})
    prose_set = set(payload.get("prose_ge10_session_ids", []))
    n_prose = int(denominators.get("n_prose_ge10", len(prose_set)))
    n_messages = int(denominators.get("n_messages_ge10", len(payload.get("session_ids", []))))

    runs: list[dict[str, Any]] = []
    for path in sorted(receipts_dir.glob("*.json")):
        try:
            candidate = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict) and candidate.get("receipt") == "claims-writer-run":
            runs.append(candidate)

    attempted: dict[str, int] = {}
    for run in runs:
        session_id = str(run["session_id"])
        attempted[session_id] = attempted.get(session_id, 0) + int(run["claims_inserted"])

    with_claims = {sid for sid, count in attempted.items() if count > 0}
    prose_attempted = {sid for sid in attempted if sid in prose_set}
    prose_with_claims = with_claims & prose_set

    refusals: dict[str, int] = {}
    for run in runs:
        for refusal in run.get("refused", []):
            reason = str(refusal["reason"])
            refusals[reason] = refusals.get(reason, 0) + 1

    return {
        "receipt": "claims-writer-progress",
        "created_utc": _now(),
        "writer_runs_used": len(runs),
        "sessions_attempted": len(attempted),
        "sessions_with_claims": len(with_claims),
        "yield": {
            "prose_ge10_primary": {
                "denominator": n_prose,
                "attempted": len(prose_attempted),
                "with_claims": len(prose_with_claims),
                "over_attempted": _ratio(len(prose_with_claims), len(prose_attempted)),
                "over_full_denominator": _ratio(len(prose_with_claims), n_prose),
            },
            "messages_ge10_literal": {
                "denominator": n_messages,
                "attempted": len(attempted),
                "with_claims": len(with_claims),
                "over_attempted": _ratio(len(with_claims), len(attempted)),
                "over_full_denominator": _ratio(len(with_claims), n_messages),
            },
        },
        "claims_total": sum(int(run["claims_inserted"]) for run in runs),
        "claims_proposed_total": sum(int(run["claims_proposed"]) for run in runs),
        "duplicates_total": sum(int(run.get("duplicates", 0)) for run in runs),
        "refusals_by_reason": dict(sorted(refusals.items(), key=lambda kv: (-kv[1], kv[0]))),
        "recheck_mismatches_total": sum(int(run["recheck_mismatches"]) for run in runs),
        "response_errors": [
            {"session_id": run["session_id"], "error": run["response_error"]}
            for run in runs
            if run.get("response_error")
        ],
        "fence_stripped_runs": sum(1 for run in runs if run.get("fence_stripped")),
    }


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


# --------------------------------------------------------------------------- CLI


def _open_store(path: str) -> Store:
    store = Store.connect(pathlib.Path(path).expanduser())
    store.install()  # verifies the schema version; creates nothing on a live store
    return store


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    population = sub.add_parser("population", help="ingested population, in writer order")
    population.add_argument("--store", required=True)
    population.add_argument("--poc", required=True)
    population.add_argument("--out", required=True)

    packet = sub.add_parser("packet", help="build one session's writer packet")
    packet.add_argument("--store", required=True)
    packet.add_argument("--session", required=True)
    packet.add_argument("--prompt", default=str(PROMPT_PATH))
    packet.add_argument("--out", required=True)

    render = sub.add_parser("render", help="render the exact prompt text for a packet")
    render.add_argument("--packet", required=True)
    render.add_argument("--prompt", default=str(PROMPT_PATH))
    render.add_argument("--out", required=True)

    ingest = sub.add_parser("ingest", help="validate and insert a model response")
    ingest.add_argument("--store", required=True)
    ingest.add_argument("--session", required=True)
    ingest.add_argument("--response", required=True)
    ingest.add_argument("--packet", required=True)
    ingest.add_argument("--writer", required=True)
    ingest.add_argument("--receipt", required=True)

    summarise = sub.add_parser("summarise", help="aggregate run receipts")
    summarise.add_argument("--receipts", required=True)
    summarise.add_argument("--poc", required=True)
    summarise.add_argument("--out", required=True)

    args = parser.parse_args(argv)

    if args.command == "population":
        store = _open_store(args.store)
        try:
            result = population_order(store, pathlib.Path(args.poc).expanduser())
        finally:
            store.close()
        _write_json(pathlib.Path(args.out).expanduser(), result)
        total = len(result["order"]) + len(result["not_ingested"])
        print(f"population {result['n']} ingested of {total}")
        print(f"  prose_ge10 subset: {len(result['prose_ge10'])}")
        print(f"  first 3 in writer order: {result['order'][:3]}")
        return 0

    if args.command == "packet":
        store = _open_store(args.store)
        try:
            built = build_packet(store, args.session, pathlib.Path(args.prompt).expanduser())
        finally:
            store.close()
        _write_json(pathlib.Path(args.out).expanduser(), built)
        print(
            f"packet {args.session}: {len(built['evidence'])} evidence rows, "
            f"{built['bytes']} bytes, truncated={built['truncated']} "
            f"(dropped {built['rows_dropped']}), exchanges={len(built['exchanges'])}"
        )
        return 0

    if args.command == "render":
        built = json.loads(pathlib.Path(args.packet).expanduser().read_text(encoding="utf-8"))
        text = render_prompt(built, pathlib.Path(args.prompt).expanduser())
        out = pathlib.Path(args.out).expanduser()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        print(f"rendered {len(text.encode('utf-8'))} bytes -> {out}")
        return 0

    if args.command == "ingest":
        built = json.loads(pathlib.Path(args.packet).expanduser().read_text(encoding="utf-8"))
        raw = pathlib.Path(args.response).expanduser().read_text(encoding="utf-8")
        store = _open_store(args.store)
        try:
            receipt = ingest_response(store, args.session, built, raw, args.writer)
        finally:
            store.close()
        _write_json(pathlib.Path(args.receipt).expanduser(), receipt)
        print(
            f"ingest {args.session}: proposed {receipt['claims_proposed']}, "
            f"inserted {receipt['claims_inserted']}, refused {len(receipt['refused'])}, "
            f"duplicates {receipt['duplicates']}, "
            f"recheck_mismatches {receipt['recheck_mismatches']}"
        )
        if receipt["response_error"]:
            print(f"  response refused: {receipt['response_error']}")
        return 1 if receipt["recheck_mismatches"] else 0

    result = summarise_receipts(
        pathlib.Path(args.receipts).expanduser(), pathlib.Path(args.poc).expanduser()
    )
    _write_json(pathlib.Path(args.out).expanduser(), result)
    primary = result["yield"]["prose_ge10_primary"]
    print(
        f"runs {result['writer_runs_used']}, sessions with claims "
        f"{result['sessions_with_claims']}/{result['sessions_attempted']} attempted"
    )
    print(
        f"  primary yield: {primary['with_claims']}/{primary['attempted']} attempted "
        f"= {primary['over_attempted']}, over {primary['denominator']} "
        f"= {primary['over_full_denominator']}"
    )
    print(f"  claims {result['claims_total']}, recheck {result['recheck_mismatches_total']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
