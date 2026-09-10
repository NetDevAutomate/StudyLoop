"""Tests for the claims-writer harness. No model is called anywhere in this file.

The harness is the half of a writer run that decides whether a claim EXISTS, so the
tests are mostly refusals: every shape a model can emit that must not reach the store.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import sys
from typing import Any

import pytest
from learning_memory import Event, ParsedSession, Session, Store
from learning_memory.derive import derive_session, load_vocabulary

MODULE_PATH = pathlib.Path(__file__).resolve().parents[1] / "claims_writer.py"


def _load_module() -> Any:
    spec = importlib.util.spec_from_file_location("claims_writer_under_test", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


cw = _load_module()

BODY_A = "the pre-commit hook failed on ruff, so I pinned the version and it passed"
BODY_B = "same phrase twice: the gate failed. and again: the gate failed."
PROMPT = MODULE_PATH.parent / "writer_prompt_v1.md"


@pytest.fixture
def store() -> Any:
    """Two derived sessions: one to write claims about, one to steal evidence from."""
    opened = Store.connect(":memory:")
    opened.install()
    opened.ingest(
        ParsedSession(
            session=Session(
                id="s-target", harness="claude_code", started_at="2026-09-01T10:00:00+00:00"
            ),
            events=[
                Event(turn_id=1, seq=0, kind="user", text="why did the pre-commit hook fail?"),
                Event(turn_id=1, seq=1, kind="tool_call", text="", tool_name="Bash"),
                Event(turn_id=1, seq=2, kind="assistant_prose", text=BODY_A),
                Event(turn_id=2, seq=3, kind="user", text="and the ambiguous one?"),
                Event(turn_id=2, seq=4, kind="assistant_prose", text=BODY_B),
            ],
            adapter_version="test@1",
        )
    )
    opened.ingest(
        ParsedSession(
            session=Session(id="s-other", harness="codex", started_at="2026-09-02T10:00:00+00:00"),
            events=[
                Event(turn_id=1, seq=0, kind="user", text="a different session entirely"),
                Event(turn_id=1, seq=1, kind="assistant_prose", text="with its own evidence row"),
            ],
            adapter_version="test@1",
        )
    )
    vocab = load_vocabulary()
    derive_session(opened, "s-target", vocab)
    derive_session(opened, "s-other", vocab)
    yield opened
    opened.close()


def _packet(store: Any, session_id: str = "s-target") -> dict[str, Any]:
    return cw.build_packet(store, session_id, PROMPT)


def _evidence_id(packet: dict[str, Any], needle: str) -> str:
    for item in packet["evidence"]:
        if needle in item["text"]:
            return str(item["evidence_id"])
    raise AssertionError(f"no evidence row containing {needle!r}")


def _claim(**overrides: Any) -> dict[str, Any]:
    claim: dict[str, Any] = {
        "kind": "Finding",
        "title": "pinning ruff fixed the pre-commit hook",
        "statement": "Pinning the ruff version made the pre-commit hook pass.",
        "tags": ["ruff", "pre-commit"],
        "confidence": 0.9,
        "citations": [],
    }
    claim.update(overrides)
    return claim


def _response(*claims: dict[str, Any]) -> str:
    return json.dumps({"claims": list(claims)})


def _ingest(store: Any, raw: str, packet: dict[str, Any] | None = None) -> dict[str, Any]:
    built = packet if packet is not None else _packet(store)
    return cw.ingest_response(store, "s-target", built, raw, cw.writer_id(PROMPT))


# ------------------------------------------------------------------- population


def test_population_order_is_sha256_of_the_session_id(store: Any, tmp_path: Any) -> None:
    poc = tmp_path / "poc.json"
    poc.write_text(
        json.dumps(
            {
                "session_ids": ["s-other", "s-target", "s-not-ingested"],
                "prose_ge10_session_ids": ["s-target"],
                "set_sha256": "deadbeef",
                "ingested_in_store": 2,
                "denominators": {"n_messages_ge10": 3, "n_prose_ge10": 1},
            }
        ),
        encoding="utf-8",
    )
    result = cw.population_order(store, poc)

    expected = sorted(["s-other", "s-target"], key=lambda sid: cw._sha256_text(sid))
    assert result["order"] == expected
    assert result["n"] == 2
    assert result["not_ingested"] == ["s-not-ingested"], "uningested ids are named, not dropped"
    assert result["prose_ge10"] == ["s-target"]
    assert result["set_sha256"] == "deadbeef"
    assert len(result["poc_file_sha256"]) == 64


def test_population_order_is_stable_across_calls(store: Any, tmp_path: Any) -> None:
    poc = tmp_path / "poc.json"
    poc.write_text(
        json.dumps({"session_ids": ["s-target", "s-other"], "set_sha256": "x"}), encoding="utf-8"
    )
    first = cw.population_order(store, poc)["order"]
    second = cw.population_order(store, poc)["order"]
    assert first == second


# ----------------------------------------------------------------------- packet


def test_packet_shape_and_roles(store: Any) -> None:
    packet = _packet(store)
    assert packet["session_id"] == "s-target"
    assert packet["harness"] == "claude_code"
    assert [item["role"] for item in packet["evidence"]] == [
        "learner",
        "assistant",
        "learner",
        "assistant",
    ]
    assert [item["turn_id"] for item in packet["evidence"]] == [1, 1, 2, 2]
    assert all(len(item["evidence_id"]) == 64 for item in packet["evidence"])
    assert packet["truncated"] is False
    assert packet["rows_dropped"] == 0
    assert packet["prompt_sha256"] == cw.prompt_sha256(PROMPT)
    assert len(packet["packet_sha256"]) == 64
    # Tool text is not citable, so it cannot appear in the packet.
    assert all("[tool:" not in item["text"] for item in packet["evidence"])


def test_packet_carries_derived_exchange_flags(store: Any) -> None:
    packet = _packet(store)
    flags = {flag["turn_id"]: flag for flag in packet["exchanges"]}
    assert set(flags) == {1, 2}
    assert flags[1]["is_question"] is True
    assert flags[1]["had_error"] is True, "'failed' is in the failure lexicon"
    assert isinstance(flags[1]["concepts"], list)
    assert "pre-commit" in flags[1]["concepts"]


def test_packet_truncation_records_rows_dropped(store: Any) -> None:
    big = "x" * 20_000
    store.ingest(
        ParsedSession(
            session=Session(id="s-big", harness="kiro_cli", started_at="2026-09-03T10:00:00+00:00"),
            events=[
                Event(turn_id=1, seq=0, kind="user", text="a question about a big thing?"),
                *[
                    Event(turn_id=1, seq=index + 1, kind="assistant_prose", text=f"{big}{index}")
                    for index in range(5)
                ],
            ],
            adapter_version="test@1",
        )
    )
    packet = _packet(store, "s-big")
    assert packet["truncated"] is True
    assert packet["rows_dropped"] > 0
    assert packet["bytes"] <= cw.PACKET_TEXT_BUDGET
    assert len(packet["evidence"]) + packet["rows_dropped"] == 6


def test_packet_keeps_one_row_even_if_it_exceeds_the_budget(store: Any) -> None:
    """An empty packet cannot be written about; one oversized row is kept deliberately."""
    store.ingest(
        ParsedSession(
            session=Session(
                id="s-huge", harness="kiro_cli", started_at="2026-09-04T10:00:00+00:00"
            ),
            events=[Event(turn_id=1, seq=0, kind="user", text="y" * (cw.PACKET_TEXT_BUDGET + 10))],
            adapter_version="test@1",
        )
    )
    packet = _packet(store, "s-huge")
    assert len(packet["evidence"]) == 1
    assert packet["bytes"] > cw.PACKET_TEXT_BUDGET
    assert packet["truncated"] is False


def test_packet_for_an_unknown_session_raises(store: Any) -> None:
    with pytest.raises(KeyError):
        _packet(store, "s-nope")


# ----------------------------------------------------------------------- render


def test_render_is_byte_deterministic(store: Any) -> None:
    packet = _packet(store)
    first = cw.render_prompt(packet, PROMPT)
    second = cw.render_prompt(packet, PROMPT)
    assert first == second
    assert cw._sha256_text(first) == cw._sha256_text(second)


def test_render_contains_the_prompt_the_rows_and_the_instruction(store: Any) -> None:
    packet = _packet(store)
    text = cw.render_prompt(packet, PROMPT)
    assert PROMPT.read_text(encoding="utf-8").splitlines()[0] in text
    assert cw.EVIDENCE_DELIMITER in text
    assert cw.FLAGS_DELIMITER in text
    assert text.rstrip("\n").endswith(cw.INSTRUCTION)
    for index, item in enumerate(packet["evidence"], start=1):
        assert (
            f"[E{index}] evidence_id={item['evidence_id']} "
            f"role={item['role']} turn={item['turn_id']}"
        ) in text
        assert item["text"] in text


def test_render_does_not_leak_the_store_path_or_ids_beyond_evidence(store: Any) -> None:
    text = cw.render_prompt(_packet(store), PROMPT)
    assert "s-other" not in text, "the writer sees one session only"
    assert ".db" not in text


# ------------------------------------------------------------- response parsing


@pytest.mark.parametrize(
    ("raw", "fragment"),
    [
        ("not json at all", "not JSON"),
        ("[]", "top level is list"),
        ('{"claims": {}}', "'claims' is dict"),
        ('{"claims": [], "extra": 1}', "expected exactly ['claims']"),
        ('{"items": []}', "expected exactly ['claims']"),
        ("", "not JSON"),
    ],
)
def test_parse_response_refuses_bad_shapes(raw: str, fragment: str) -> None:
    with pytest.raises(cw.ResponseError, match=fragment.replace("[", r"\[").replace("]", r"\]")):
        cw.parse_response(raw)


def test_parse_response_truncates_more_than_eight_claims_and_records_it() -> None:
    """Pilot batch 1 changed the cap from refuse-the-response to keep-the-first-eight:
    a 9-claim response with every citation bound had been discarded on a near-miss."""
    claims, fence, dropped = cw.parse_response(
        json.dumps({"claims": [_claim() for _ in range(11)]})
    )
    assert len(claims) == cw.MAX_CLAIMS
    assert dropped == 3
    assert fence is False
    claims, _, dropped = cw.parse_response(json.dumps({"claims": [_claim() for _ in range(8)]}))
    assert len(claims) == 8 and dropped == 0


def test_non_json_response_is_recorded_not_raised(store: Any) -> None:
    receipt = _ingest(store, "I could not find anything worth keeping.")
    assert receipt["response_error"] is not None
    assert receipt["claims_proposed"] == 0
    assert receipt["claims_inserted"] == 0
    assert store.row_counts()["claims"] == 0


def test_fence_stripping_is_recorded(store: Any) -> None:
    packet = _packet(store)
    quote = "pinned the version"
    good = _claim(citations=[{"evidence_id": _evidence_id(packet, quote), "quote": quote}])
    fenced = "```json\n" + _response(good) + "\n```"
    receipt = _ingest(store, fenced, packet)
    assert receipt["fence_stripped"] is True
    assert receipt["claims_inserted"] == 1


def test_unfenced_response_records_no_fence(store: Any) -> None:
    packet = _packet(store)
    quote = "pinned the version"
    good = _claim(citations=[{"evidence_id": _evidence_id(packet, quote), "quote": quote}])
    receipt = _ingest(store, _response(good), packet)
    assert receipt["fence_stripped"] is False
    assert receipt["claims_inserted"] == 1


# ------------------------------------------------------------------- insertion


def test_a_valid_claim_inserts_and_rechecks_clean(store: Any) -> None:
    packet = _packet(store)
    evidence_id = _evidence_id(packet, "pinned the version")
    receipt = _ingest(
        store,
        _response(_claim(citations=[{"evidence_id": evidence_id, "quote": "pinned the version"}])),
        packet,
    )
    assert receipt["claims_proposed"] == 1
    assert receipt["claims_inserted"] == 1
    assert receipt["refused"] == []
    assert receipt["recheck_mismatches"] == 0
    assert receipt["writer"] == cw.writer_id(PROMPT)
    assert receipt["prompt_sha256"] == cw.prompt_sha256(PROMPT)

    counts = store.row_counts()
    assert (counts["claims"], counts["claim_citations"]) == (1, 1)
    bound = store.claim_citations(receipt["inserted_claim_ids"][0])[0]
    assert bound["quote"] == "pinned the version"
    assert BODY_A[bound["start"] : bound["end"]] == "pinned the version"


def test_two_citations_on_one_claim_both_bind(store: Any) -> None:
    packet = _packet(store)
    receipt = _ingest(
        store,
        _response(
            _claim(
                citations=[
                    {"evidence_id": _evidence_id(packet, "pinned"), "quote": "pinned the version"},
                    {
                        "evidence_id": _evidence_id(packet, "pre-commit hook fail"),
                        "quote": "why did the pre-commit hook fail?",
                    },
                ]
            )
        ),
        packet,
    )
    assert receipt["claims_inserted"] == 1
    assert receipt["recheck_mismatches"] == 0
    assert store.row_counts()["claim_citations"] == 2


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"kind": "Rumour"}, "bad_kind"),
        ({"kind": "finding"}, "bad_kind"),
        ({"title": "t" * 121}, "title_too_long"),
        ({"title": ""}, "empty_title"),
        ({"statement": "s" * 501}, "statement_too_long"),
        ({"statement": "   "}, "empty_statement"),
        ({"tags": ["only-one"]}, "tags_out_of_range"),
        ({"tags": ["a", "b", "c", "d", "e", "f"]}, "tags_out_of_range"),
        ({"tags": ["dup", "dup"]}, "tags_not_distinct"),
        ({"tags": ["Ruff", "pre-commit"]}, "tag_not_lowercase_token"),
        ({"tags": ["two words", "pre-commit"]}, "tag_not_lowercase_token"),
        ({"confidence": 0.4}, "confidence_out_of_range"),
        ({"confidence": 1.1}, "confidence_out_of_range"),
        ({"confidence": "high"}, "bad_confidence"),
        ({"citations": []}, "no_citations"),
    ],
)
def test_schema_refusals(store: Any, overrides: dict[str, Any], reason: str) -> None:
    packet = _packet(store)
    quote = "pinned the version"
    good_citation = [{"evidence_id": _evidence_id(packet, quote), "quote": quote}]
    claim = _claim(**{"citations": good_citation, **overrides})
    receipt = _ingest(store, _response(claim), packet)
    assert receipt["claims_inserted"] == 0
    assert [item["reason"] for item in receipt["refused"]] == [reason]
    assert store.row_counts()["claims"] == 0, "a refused claim writes nothing"


def test_missing_fields_are_refused(store: Any) -> None:
    receipt = _ingest(store, _response({"kind": "Finding", "title": "t"}))
    assert [item["reason"] for item in receipt["refused"]] == ["missing_fields"]


def test_quote_not_in_the_evidence_is_refused(store: Any) -> None:
    packet = _packet(store)
    receipt = _ingest(
        store,
        _response(
            _claim(
                citations=[
                    {
                        "evidence_id": _evidence_id(packet, "pinned the version"),
                        "quote": "I paraphrased this instead",
                    }
                ]
            )
        ),
        packet,
    )
    assert [item["reason"] for item in receipt["refused"]] == ["citation_unbound"]
    assert "quote_not_found" in receipt["refused"][0]["detail"]
    assert store.row_counts()["claims"] == 0


def test_ambiguous_quote_is_refused(store: Any) -> None:
    packet = _packet(store)
    receipt = _ingest(
        store,
        _response(
            _claim(
                citations=[
                    {
                        "evidence_id": _evidence_id(packet, "same phrase twice"),
                        "quote": "the gate failed",
                    }
                ]
            )
        ),
        packet,
    )
    assert [item["reason"] for item in receipt["refused"]] == ["citation_unbound"]
    assert "ambiguous_quote" in receipt["refused"][0]["detail"]


def test_cross_session_evidence_id_is_refused(store: Any) -> None:
    """The writer only ever sees one session, so a foreign id cannot be honest."""
    other = _packet(store, "s-other")
    foreign_id = other["evidence"][0]["evidence_id"]
    receipt = _ingest(
        store,
        _response(
            _claim(citations=[{"evidence_id": foreign_id, "quote": "a different session entirely"}])
        ),
    )
    assert [item["reason"] for item in receipt["refused"]] == ["citation_not_in_packet"]
    assert store.row_counts()["claims"] == 0


def test_empty_quote_is_refused(store: Any) -> None:
    packet = _packet(store)
    receipt = _ingest(
        store,
        _response(_claim(citations=[{"evidence_id": _evidence_id(packet, "pinned"), "quote": ""}])),
        packet,
    )
    assert [item["reason"] for item in receipt["refused"]] == ["empty_quote"]


def test_one_bad_and_one_good_claim_inserts_exactly_the_good_one(store: Any) -> None:
    packet = _packet(store)
    evidence_id = _evidence_id(packet, "pinned the version")
    bad = _claim(
        title="this one is over the limit " + "x" * 120,
        citations=[{"evidence_id": evidence_id, "quote": "pinned the version"}],
    )
    good = _claim(
        title="the good one",
        statement="Pinning ruff made the hook pass.",
        citations=[{"evidence_id": evidence_id, "quote": "it passed"}],
    )
    receipt = _ingest(store, _response(bad, good), packet)

    assert receipt["claims_proposed"] == 2
    assert receipt["claims_inserted"] == 1
    assert [item["index"] for item in receipt["refused"]] == [0]
    assert receipt["recheck_mismatches"] == 0
    row = store.connection.execute("SELECT title FROM claims").fetchone()
    assert row["title"] == "the good one"


def test_running_the_same_response_twice_counts_duplicates(store: Any) -> None:
    packet = _packet(store)
    evidence_id = _evidence_id(packet, "pinned the version")
    raw = _response(
        _claim(citations=[{"evidence_id": evidence_id, "quote": "pinned the version"}]),
        _claim(
            title="second distinct claim",
            statement="The hook passed after the pin.",
            citations=[{"evidence_id": evidence_id, "quote": "it passed"}],
        ),
    )
    first = _ingest(store, raw, packet)
    assert (first["claims_inserted"], first["duplicates"]) == (2, 0)

    second = _ingest(store, raw, packet)
    assert second["claims_inserted"] == 0
    assert second["duplicates"] == 2
    assert [item["reason"] for item in second["refused"]] == ["duplicate", "duplicate"]
    assert store.row_counts()["claims"] == 2, "nothing was written twice"


def test_receipt_accounting_identity_holds(store: Any) -> None:
    """proposed == inserted + refused-excluding-duplicates + duplicates."""
    packet = _packet(store)
    evidence_id = _evidence_id(packet, "pinned the version")
    receipt = _ingest(
        store,
        _response(
            _claim(citations=[{"evidence_id": evidence_id, "quote": "pinned the version"}]),
            _claim(kind="Rumour", citations=[{"evidence_id": evidence_id, "quote": "it passed"}]),
        ),
        packet,
    )
    non_duplicate = [item for item in receipt["refused"] if item["reason"] != "duplicate"]
    assert receipt["claims_proposed"] == (
        receipt["claims_inserted"] + len(non_duplicate) + receipt["duplicates"]
    )


def test_a_writer_label_that_does_not_match_the_prompt_fails_the_run(store: Any) -> None:
    """A claim row labelled with a prompt that did not produce it is unfalsifiable."""
    packet = _packet(store)
    with pytest.raises(cw.ResponseError, match="prompt sha8"):
        cw.ingest_response(store, "s-target", packet, _response(), "sonnet5/writer-v1/deadbeef")


def test_a_packet_for_another_session_fails_the_run(store: Any) -> None:
    with pytest.raises(cw.ResponseError, match="packet is for"):
        cw.ingest_response(
            store, "s-target", _packet(store, "s-other"), _response(), cw.writer_id(PROMPT)
        )


def test_recheck_returns_zero_with_no_claims(store: Any) -> None:
    assert cw.recheck_citations(store, []) == 0


# -------------------------------------------------------------------- summarise


def test_summarise_reports_both_denominators(store: Any, tmp_path: Any) -> None:
    packet = _packet(store)
    evidence_id = _evidence_id(packet, "pinned the version")
    receipts = tmp_path / "runs"
    receipts.mkdir()

    with_claims = _ingest(
        store,
        _response(_claim(citations=[{"evidence_id": evidence_id, "quote": "pinned the version"}])),
        packet,
    )
    (receipts / "a.json").write_text(json.dumps(with_claims), encoding="utf-8")
    empty = _ingest(store, _response(), packet)
    empty["session_id"] = "s-other"
    (receipts / "b.json").write_text(json.dumps(empty), encoding="utf-8")
    (receipts / "not-a-receipt.json").write_text(json.dumps({"receipt": "other"}), encoding="utf-8")
    (receipts / "broken.json").write_text("{{{", encoding="utf-8")

    poc = tmp_path / "poc.json"
    poc.write_text(
        json.dumps(
            {
                "session_ids": ["s-target", "s-other"],
                "prose_ge10_session_ids": ["s-target"],
                "denominators": {"n_messages_ge10": 345, "n_prose_ge10": 200},
            }
        ),
        encoding="utf-8",
    )
    result = cw.summarise_receipts(receipts, poc)

    assert result["writer_runs_used"] == 2, "non-receipts and broken files are skipped"
    assert result["sessions_attempted"] == 2
    assert result["sessions_with_claims"] == 1
    primary = result["yield"]["prose_ge10_primary"]
    assert primary["denominator"] == 200
    assert (primary["attempted"], primary["with_claims"]) == (1, 1)
    assert primary["over_attempted"] == 1.0
    assert primary["over_full_denominator"] == round(1 / 200, 4)
    literal = result["yield"]["messages_ge10_literal"]
    assert literal["denominator"] == 345
    assert literal["over_attempted"] == 0.5
    assert result["claims_total"] == 1
    assert result["recheck_mismatches_total"] == 0


def test_summarise_on_an_empty_directory(tmp_path: Any) -> None:
    poc = tmp_path / "poc.json"
    poc.write_text(json.dumps({"session_ids": [], "denominators": {}}), encoding="utf-8")
    empty = tmp_path / "runs"
    empty.mkdir()
    result = cw.summarise_receipts(empty, poc)
    assert result["writer_runs_used"] == 0
    assert result["yield"]["prose_ge10_primary"]["over_attempted"] is None


# ------------------------------------------------------------------- blindness


ALLOWED_PATH_MENTIONS = (
    "receipts/claims-writer-spec-v1.md",
    "receipts/poc-set-g2.json",
)


def test_the_harness_cannot_reach_an_answer_key() -> None:
    """The module must not name an answer key, in code or in a default path.

    The two spec/population filenames in the docstring are the only permitted
    ``receipts/`` mentions; they are stripped before the grep so a third one fails.
    """
    body = MODULE_PATH.read_text(encoding="utf-8")
    for allowed in ALLOWED_PATH_MENTIONS:
        body = body.replace(allowed, "<allowed-doc-reference>")
    offenders = [needle for needle in ("gold", "sealed", "receipts/") if needle in body.casefold()]
    assert offenders == [], f"forbidden references in claims_writer.py: {offenders}"


def test_the_packet_is_built_from_the_store_alone(store: Any) -> None:
    """Nothing in a packet comes from a file: it is store rows and the prompt digest."""
    packet = _packet(store)
    payload = json.dumps(packet).casefold()
    for needle in ("gold", "sealed", ".json", ".md"):
        assert needle not in payload, f"{needle!r} reached the packet"
