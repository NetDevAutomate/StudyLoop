"""WD-2 — ``studyloop brain wind-down --json`` in a real subprocess.

Each truth-table row from ``test_wind_down_decision.py`` is re-run through the
actual CLI entry point (``python -m studyloop``), with the provider selected by
a real config file via ``STUDYLOOP_CONFIG``. Red when the CLI and the pure
function disagree, or when the emitted sentence drifts from the pinned
constants by even one byte.

Artefact: the observed table is written to ``wind-down-truth-table.json``
under ``STUDYLOOP_EVIDENCE_DIR`` when that is set (how ``just gate-checks``
captures evidence), and under pytest's tmp dir otherwise.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from studyloop.second_brain.wind_down import (
    PUBLISH_OFFER_SENTENCE,
    XTILES_OFFER_SENTENCE,
)


def _run_wind_down(config_path: Path, *cli_args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["STUDYLOOP_CONFIG"] = str(config_path)
    return subprocess.run(
        [sys.executable, "-m", "studyloop.cli", "brain", "wind-down", *cli_args],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )


def _config(tmp_path: Path, mapping: dict) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(yaml.dump(mapping, default_flow_style=False, sort_keys=False))
    return path


def _decide(config_path: Path, *cli_args: str) -> dict:
    result = _run_wind_down(config_path, "--json", *cli_args)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


#: (row id, second_brain section, extra CLI args, expected channel, offer, sentence).
#: Row 5's unwritable vault is a config whose vault_path is a FILE — configured,
#: publish-capable, not available.
_ROWS = [
    ("row1-none-no-connector", None, (), "none", False, ""),
    ("row2-none-connector", None, ("--connector", "xtiles"), "none", False, ""),
    (
        "row3-obsidian-writable",
        {"provider": "obsidian", "vault_path": "@VAULT@"},
        (),
        "publish",
        True,
        PUBLISH_OFFER_SENTENCE,
    ),
    (
        "row4-obsidian-writable-connector",
        {"provider": "obsidian", "vault_path": "@VAULT@"},
        ("--connector", "xtiles"),
        "publish",
        True,
        PUBLISH_OFFER_SENTENCE,
    ),
    (
        "row5-obsidian-unwritable",
        {"provider": "obsidian", "vault_path": "@NOT_A_DIR@"},
        (),
        "publish",
        True,
        PUBLISH_OFFER_SENTENCE,
    ),
    ("row6-xtiles-no-connector", {"provider": "xtiles"}, (), "none", False, ""),
    (
        "row7-xtiles-connector",
        {"provider": "xtiles"},
        ("--connector", "xtiles"),
        "xtiles",
        True,
        XTILES_OFFER_SENTENCE,
    ),
]


def _materialise(tmp_path: Path, section: dict | None) -> Path:
    mapping: dict = {"topics": []}
    if section is not None:
        section = dict(section)
        if section.get("vault_path") == "@VAULT@":
            vault = tmp_path / "vault"
            (vault / ".obsidian").mkdir(parents=True, exist_ok=True)
            section["vault_path"] = str(vault)
        elif section.get("vault_path") == "@NOT_A_DIR@":
            not_a_dir = tmp_path / "not-a-dir"
            not_a_dir.write_text("occupied")
            section["vault_path"] = str(not_a_dir)
        mapping["second_brain"] = section
    return _config(tmp_path, mapping)


@pytest.mark.parametrize(
    ("row_id", "section", "cli_args", "channel", "offer", "sentence"),
    _ROWS,
    ids=[row[0] for row in _ROWS],
)
def test_cli_matches_the_truth_table_row(
    tmp_path: Path,
    row_id: str,
    section: dict | None,
    cli_args: tuple[str, ...],
    channel: str,
    offer: bool,
    sentence: str,
) -> None:
    payload = _decide(_materialise(tmp_path, section), *cli_args)

    assert payload["channel"] == channel
    assert payload["offer"] is offer
    # Byte-identical, never a substring: the sentence IS the contract.
    assert payload["sentence"] == sentence
    assert payload["reason"]


def test_row8_unknown_provider_fails_naming_the_provider(tmp_path: Path) -> None:
    config = _config(tmp_path, {"topics": [], "second_brain": {"provider": "notion"}})
    result = _run_wind_down(config, "--json")

    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert "notion" in combined


def test_the_whole_table_as_one_artefact(tmp_path: Path) -> None:
    """One run over every decidable row, written as the WD-2 artefact."""
    observed = []
    for row_id, section, cli_args, channel, offer, sentence in _ROWS:
        row_dir = tmp_path / row_id
        row_dir.mkdir()
        payload = _decide(_materialise(row_dir, section), *cli_args)
        observed.append(
            {
                "row": row_id,
                "expected": {"channel": channel, "offer": offer, "sentence": sentence},
                "observed": payload,
                "verdict": (
                    "pass"
                    if (payload["channel"], payload["offer"], payload["sentence"])
                    == (channel, offer, sentence)
                    else "FAIL"
                ),
            }
        )

    evidence_dir = Path(os.environ.get("STUDYLOOP_EVIDENCE_DIR", tmp_path))
    artefact = evidence_dir / "wind-down-truth-table.json"
    artefact.write_text(json.dumps(observed, indent=2))

    failures = [row["row"] for row in observed if row["verdict"] != "pass"]
    assert not failures, f"rows disagreeing with the truth table: {failures} ({artefact})"


def test_human_form_prints_the_same_decision(tmp_path: Path) -> None:
    config = _materialise(tmp_path, {"provider": "xtiles"})
    result = _run_wind_down(config, "--connector", "xtiles")

    assert result.returncode == 0
    assert "channel: xtiles" in result.stdout
    assert "offer: True" in result.stdout
