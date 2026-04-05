"""YAML scenario loader for the persona evaluation harness."""

from __future__ import annotations

from pathlib import Path

import yaml

from studyctl.eval.models import Scenario

REQUIRED_FIELDS: frozenset[str] = frozenset({"id", "name", "topic", "energy", "prompt"})


def load_scenarios(path: Path) -> list[Scenario]:
    """Load scenarios from a YAML file at *path*.

    Raises:
        FileNotFoundError: if the file does not exist.
        ValueError: if any scenario is missing a required field.
    """
    if not path.exists():
        raise FileNotFoundError(f"Scenario file not found: {path}")

    with path.open() as fh:
        data = yaml.safe_load(fh)

    raw_scenarios: list[dict] = data.get("scenarios", [])
    scenarios: list[Scenario] = []

    for raw in raw_scenarios:
        missing = REQUIRED_FIELDS - raw.keys()
        if missing:
            # Report all missing fields but put the first alphabetically in the
            # message so tests can match a single consistent field name.
            first_missing = sorted(missing)[0]
            raise ValueError(
                f"Scenario {raw.get('id', '<unknown>')!r} missing required field(s): "
                f"{', '.join(sorted(missing))} (first: {first_missing!r})"
            )

        scenarios.append(
            Scenario(
                id=raw["id"],
                name=raw["name"],
                priority=raw.get("priority", "normal"),
                topic=raw["topic"],
                energy=int(raw["energy"]),
                prompt=raw["prompt"],
                elapsed_minutes=int(raw.get("elapsed_minutes", 10)),
                setup_prompts=list(raw.get("setup_prompts", [])),
                heuristic_checks=list(raw.get("heuristic_checks", [])),
                rubric_weights={k: float(v) for k, v in raw.get("rubric_weights", {}).items()},
            )
        )

    return scenarios


def builtin_scenarios_path() -> Path:
    """Return the path to the bundled study.yaml scenario file."""
    return Path(__file__).parent / "scenarios" / "study.yaml"
