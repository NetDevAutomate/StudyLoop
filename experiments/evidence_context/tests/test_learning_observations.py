"""Reproducible current-consumer lesson, including scope and retirement interventions."""

from experiments.evidence_context.learning_observations.runner import run


def test_observation_lesson(tmp_path):
    result = run(tmp_path / "lesson")
    assert result["extractor_calls"] == 3
    assert result["personal_before"][0]["confidence_status"] == "unverified_interpretation"
    assert result["conflicting_personal_reports"][0]["reported_confidences"] == [
        "learning",
        "confident",
    ]
    assert result["after_one_source_removed"][0]["session_count"] == 1
    assert result["after_correction_forgotten"] == []
