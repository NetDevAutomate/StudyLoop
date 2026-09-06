"""A reserve and a complete group are different allocation units."""

from experiments.evidence_context.contrary_selection.runner import run


def test_whole_group_policy_keeps_counterevidence_and_reports_impossible_groups(tmp_path):
    report = run(tmp_path)
    rows = {row["case"]["name"]: row["results"] for row in report["cases"]}
    for name in ("byte_pressure", "long_quotes", "multi_source_group"):
        assert rows[name]["reserve_20"]["contrary_groups"] == 0
        assert rows[name]["anchor_then_relations"]["contrary_groups"] == 1
    for policy in rows["group_cannot_fit"].values():
        assert policy["contrary_groups"] == 0
        assert policy["conflict_review"]["status"] == "known_relations_omitted"
    assert all(value["anchor_retained"] for row in rows.values() for value in row.values())
    assert report["claims"]["semantic_accuracy"] == "not_measured"
