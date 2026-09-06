"""Stage 12 evaluator checks use synthetic data; no model or production DB."""

import json

import numpy as np
import pytest

from experiments.evidence_context.retrieval_matrix.pilot import canonical, retrieve, select_pack
from experiments.evidence_context.retrieval_matrix.trial import assess, coverage


class CharacterTokenizer:
    def encode(self, text, **kwargs):
        return list(text)


def record(rid, text="needle", project="personal", at="2026-01-01"):
    return {
        "id": rid,
        "text": text,
        "role": "assistant",
        "at": at,
        "project": project,
        "kind": "conversation_report",
    }


def test_packing_accounts_for_serialized_metadata_and_skips_oversized():
    records = {"large": record("large", "x" * 2000), "small": record("small")}
    pack = select_pack(["large", "small"], records, CharacterTokenizer(), ceiling=150)
    assert [r["id"] for r in pack] == ["small"]
    assert len(canonical(pack)) <= 150


def test_alternatives_count_once_and_empty_control_has_no_recall():
    assert coverage(["a", "b"], [["a", "b"], ["c"]]) == {"covered": 1, "required": 2}
    assert coverage(["noise"], []) == {"covered": 0, "required": 0}


def test_quote_location_cannot_promote_report_to_validation():
    answer = {
        "answer": "Tests passed",
        "evidence_status": "validated",
        "citations": [{"id": "a", "quote": "Tests passed", "supports": "passes"}],
        "limitations": "unknown",
        "next_check": "get logs",
    }
    checks = assess(answer, [record("a", "Tests passed")])
    assert checks["quotes_locatable"] == 1
    assert checks["unsupported_validation_status"]
    answer["citations"][0]["quote"] = "Different test passed"
    assert assess(answer, [record("a")])["bad_quote_or_id_count"] == 1
    answer["citations"][0]["quote"] = ""
    with pytest.raises(ValueError, match="Empty citation"):
        assess(answer, [record("a")])


def test_scope_and_asof_hold_across_every_retrieval_arm(tmp_path, monkeypatch):
    from transformers import AutoTokenizer

    monkeypatch.setattr(AutoTokenizer, "from_pretrained", lambda *a, **kw: CharacterTokenizer())
    records = [record("safe"), record("work", project="work"), record("future", at="2027")]
    corpus = {
        "records": records,
        "edges": [["safe", "work", "link"], ["safe", "future", "link"]],
        "questions": [{"id": "Q", "query": "needle", "project": "personal", "asof": "2026-02-01"}],
    }
    (tmp_path / "corpus.json").write_text(json.dumps(corpus))
    (tmp_path / "config.json").write_text(json.dumps({"tokenizer": "fake"}))
    np.save(tmp_path / "vectors.npy", np.array([[0.1, 0], [1, 0], [1, 0]]))
    np.save(tmp_path / "query-vectors.npy", np.array([[1, 0]]))
    packs = retrieve(tmp_path)
    assert len(packs) == 4
    assert all(p["ids"] == ["safe"] for p in packs)
