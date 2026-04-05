# Persona Evaluation Harness — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an autonomous evaluation harness that runs fixed student scenarios against the study mentor persona, scores responses via heuristic + LLM judge, and tracks scores per persona version.

**Architecture:** Modular orchestrator (`eval/`) with pluggable targets (`test_suite` for existing pytest, `persona` for scenario evaluation) and pluggable judges (`heuristic` fast-pass, `llm` for Ollama/OpenAI-compat scoring). The existing `scripts/test_iterate.py` is refactored into library modules; the script becomes a thin CLI wrapper.

**Tech Stack:** Python 3.12+, Click CLI, Ollama/OpenAI-compat HTTP API, tmux for session interaction, PyYAML for scenario definitions, `urllib.request` for LLM HTTP calls (no new deps).

**Spec:** `docs/plans/2026-04-05-persona-optimisation-tier2-design.md`

**Test runner:** `uv run pytest` from project root. All test files inline their fixtures (no conftest.py — pluggy conflict).

---

## File Map

### New files (eval package)

| File | Responsibility |
|------|---------------|
| `packages/studyctl/src/studyctl/eval/__init__.py` | Package init |
| `packages/studyctl/src/studyctl/eval/models.py` | Dataclasses: `Scenario`, `HeuristicResult`, `JudgeResult`, `EvalSummary` |
| `packages/studyctl/src/studyctl/eval/scenarios.py` | Load + validate YAML scenario files |
| `packages/studyctl/src/studyctl/eval/git_ops.py` | `is_clean()`, `short_hash()`, `abort_if_dirty()` |
| `packages/studyctl/src/studyctl/eval/reporter.py` | TSV logging (`eval-results.tsv`), markdown report generation |
| `packages/studyctl/src/studyctl/eval/orchestrator.py` | `run_evaluation()` loop: per-scenario setup → run → judge → record |
| `packages/studyctl/src/studyctl/eval/targets/__init__.py` | Package init |
| `packages/studyctl/src/studyctl/eval/targets/base.py` | `EvalTarget` Protocol |
| `packages/studyctl/src/studyctl/eval/targets/test_suite.py` | Existing pytest runner (extracted from `test_iterate.py`) |
| `packages/studyctl/src/studyctl/eval/targets/persona.py` | Scenario executor: start session, send prompt, capture response |
| `packages/studyctl/src/studyctl/eval/judge/__init__.py` | Package init |
| `packages/studyctl/src/studyctl/eval/judge/base.py` | `Judge` Protocol |
| `packages/studyctl/src/studyctl/eval/judge/heuristic.py` | Structural checks (contains_question, no_rsd_triggers, etc.) |
| `packages/studyctl/src/studyctl/eval/judge/llm.py` | LLM judge: build prompt, call client, parse JSON scores |
| `packages/studyctl/src/studyctl/eval/llm_client.py` | HTTP client for Ollama + OpenAI-compat |
| `packages/studyctl/src/studyctl/eval/capture.py` | tmux pane capture, ANSI stripping, response extraction |
| `packages/studyctl/src/studyctl/eval/prompts/judge-rubric.md` | Versioned judge prompt template |
| `packages/studyctl/src/studyctl/eval/scenarios/study.yaml` | 7 fixed student scenarios |
| `packages/studyctl/src/studyctl/cli/_eval.py` | CLI commands: `eval run`, `eval history`, `eval setup` |

### New test files

| File | Tests |
|------|-------|
| `packages/studyctl/tests/test_eval_models.py` | Scenario loading, weight calculation, score aggregation |
| `packages/studyctl/tests/test_eval_heuristic.py` | Each heuristic check with pass/fail examples |
| `packages/studyctl/tests/test_eval_llm_client.py` | Mock HTTP for Ollama + OpenAI-compat |
| `packages/studyctl/tests/test_eval_llm_judge.py` | Prompt construction, JSON parsing, score clamping |
| `packages/studyctl/tests/test_eval_reporter.py` | TSV format, markdown generation |
| `packages/studyctl/tests/test_eval_orchestrator.py` | Loop logic with mock target + judge |
| `packages/studyctl/tests/test_eval_capture.py` | ANSI stripping, baseline diff |
| `packages/studyctl/tests/test_eval_cli.py` | CLI invocation via CliRunner |

### Modified files

| File | Change |
|------|--------|
| `scripts/test_iterate.py` | Thin wrapper calling `eval.targets.test_suite` + `eval.reporter` |
| `packages/studyctl/src/studyctl/cli/__init__.py` | Register `eval` command group via LazyGroup |
| `packages/studyctl/src/studyctl/settings.py` | Add `EvalConfig` dataclass + config loading |
| `packages/studyctl/src/studyctl/doctor/config.py` | Add eval provider health check |

---

## Chunk 1: Foundation — Models, Scenarios, Git Ops, Reporter

Extract the reusable core that both targets depend on.

### Task 1: Eval models and scenario loader

**Files:**
- Create: `packages/studyctl/src/studyctl/eval/__init__.py`
- Create: `packages/studyctl/src/studyctl/eval/models.py`
- Create: `packages/studyctl/src/studyctl/eval/scenarios.py`
- Create: `packages/studyctl/src/studyctl/eval/scenarios/study.yaml`
- Test: `packages/studyctl/tests/test_eval_models.py`

- [ ] **Step 1: Write failing tests for models and scenario loading**

```python
# test_eval_models.py
"""Tests for eval models and scenario loading."""
from __future__ import annotations
from pathlib import Path
import pytest

class TestScenarioLoading:
    def test_load_scenarios_from_yaml(self, tmp_path):
        from studyctl.eval.scenarios import load_scenarios
        yaml_content = """
scenarios:
  - id: test-scenario
    name: Test Scenario
    priority: critical
    topic: Python Decorators
    energy: 5
    elapsed_minutes: 10
    prompt: "What is a decorator?"
    heuristic_checks:
      - contains_question
    rubric_weights:
      emotional_safety: 2.0
"""
        f = tmp_path / "test.yaml"
        f.write_text(yaml_content)
        scenarios = load_scenarios(f)
        assert len(scenarios) == 1
        assert scenarios[0].id == "test-scenario"
        assert scenarios[0].energy == 5
        assert scenarios[0].rubric_weights["emotional_safety"] == 2.0

    def test_load_missing_file_raises(self):
        from studyctl.eval.scenarios import load_scenarios
        with pytest.raises(FileNotFoundError):
            load_scenarios(Path("/nonexistent.yaml"))

    def test_scenario_missing_required_field(self, tmp_path):
        from studyctl.eval.scenarios import load_scenarios
        f = tmp_path / "bad.yaml"
        f.write_text("scenarios:\n  - id: no-prompt\n    name: Bad\n")
        with pytest.raises(ValueError, match="prompt"):
            load_scenarios(f)


class TestScoreCalculation:
    def test_weighted_score(self):
        from studyctl.eval.models import JudgeResult
        result = JudgeResult(
            scenario_id="test",
            heuristic_pass=True,
            dimensions={"clarity": 3, "emotional_safety": 4},
            weights={"clarity": 1.0, "emotional_safety": 2.0},
        )
        # (3*1.0 + 4*2.0) / (4*1.0 + 4*2.0) * 100 = 11/12 * 100 = 91.67
        assert abs(result.weighted_score - 91.67) < 0.1

    def test_heuristic_fail_scores_zero(self):
        from studyctl.eval.models import JudgeResult
        result = JudgeResult(
            scenario_id="test",
            heuristic_pass=False,
            dimensions={},
            weights={},
        )
        assert result.weighted_score == 0.0

    def test_passed_property(self):
        from studyctl.eval.models import JudgeResult
        passing = JudgeResult(
            scenario_id="t", heuristic_pass=True,
            dimensions={"clarity": 3}, weights={"clarity": 1.0},
        )
        assert passing.passed  # 75% >= 70%
        failing = JudgeResult(
            scenario_id="t", heuristic_pass=True,
            dimensions={"clarity": 2}, weights={"clarity": 1.0},
        )
        assert not failing.passed  # 50% < 70%
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
uv run pytest packages/studyctl/tests/test_eval_models.py -x -v
```

- [ ] **Step 3: Implement models.py**

```python
# packages/studyctl/src/studyctl/eval/models.py
"""Data models for the evaluation harness."""
from __future__ import annotations
from dataclasses import dataclass, field

PASS_THRESHOLD = 70.0  # minimum weighted score to pass

@dataclass
class Scenario:
    id: str
    name: str
    priority: str  # critical, high, normal
    topic: str
    energy: int
    prompt: str
    elapsed_minutes: int = 10
    setup_prompts: list[str] = field(default_factory=list)
    heuristic_checks: list[str] = field(default_factory=list)
    rubric_weights: dict[str, float] = field(default_factory=dict)

@dataclass
class HeuristicResult:
    passed: bool
    checks: dict[str, bool]  # check_name → pass/fail
    messages: list[str] = field(default_factory=list)  # failure reasons

@dataclass
class JudgeResult:
    scenario_id: str
    heuristic_pass: bool
    dimensions: dict[str, int]  # dimension → 1-4 score
    weights: dict[str, float]   # dimension → weight
    raw_response: str = ""      # LLM judge raw output (for debugging)

    @property
    def weighted_score(self) -> float:
        if not self.heuristic_pass:
            return 0.0
        if not self.dimensions:
            return 0.0
        weighted_sum = sum(
            self.dimensions[d] * self.weights.get(d, 1.0)
            for d in self.dimensions
        )
        max_sum = sum(4.0 * self.weights.get(d, 1.0) for d in self.dimensions)
        return (weighted_sum / max_sum) * 100 if max_sum > 0 else 0.0

    @property
    def passed(self) -> bool:
        return self.heuristic_pass and self.weighted_score >= PASS_THRESHOLD

    @staticmethod
    def timeout(scenario_id: str) -> JudgeResult:
        return JudgeResult(
            scenario_id=scenario_id,
            heuristic_pass=False,
            dimensions={},
            weights={},
            raw_response="TIMEOUT",
        )

@dataclass
class EvalSummary:
    agent: str
    persona_hash: str
    commit: str
    results: list[JudgeResult]
    timestamp: str = ""

    @property
    def avg_score(self) -> float:
        scores = [r.weighted_score for r in self.results]
        return sum(scores) / len(scores) if scores else 0.0

    @property
    def all_passed(self) -> bool:
        return all(r.passed for r in self.results)
```

- [ ] **Step 4: Implement scenarios.py**

```python
# packages/studyctl/src/studyctl/eval/scenarios.py
"""Load and validate YAML scenario definitions."""
from __future__ import annotations
from pathlib import Path
import yaml
from studyctl.eval.models import Scenario

REQUIRED_FIELDS = {"id", "name", "topic", "energy", "prompt"}

def load_scenarios(path: Path) -> list[Scenario]:
    if not path.exists():
        msg = f"Scenario file not found: {path}"
        raise FileNotFoundError(msg)
    raw = yaml.safe_load(path.read_text())
    entries = raw.get("scenarios", [])
    scenarios = []
    for entry in entries:
        missing = REQUIRED_FIELDS - set(entry.keys())
        if missing:
            msg = f"Scenario '{entry.get('id', '?')}' missing fields: {', '.join(sorted(missing))}"
            raise ValueError(msg)
        scenarios.append(Scenario(
            id=entry["id"],
            name=entry["name"],
            priority=entry.get("priority", "normal"),
            topic=entry["topic"],
            energy=entry["energy"],
            prompt=entry["prompt"],
            elapsed_minutes=entry.get("elapsed_minutes", 10),
            setup_prompts=entry.get("setup_prompts", []),
            heuristic_checks=entry.get("heuristic_checks", []),
            rubric_weights=entry.get("rubric_weights", {}),
        ))
    return scenarios

def builtin_scenarios_path() -> Path:
    return Path(__file__).parent / "scenarios" / "study.yaml"
```

- [ ] **Step 5: Create `__init__.py` and study.yaml**

Create empty `packages/studyctl/src/studyctl/eval/__init__.py`.

Create `packages/studyctl/src/studyctl/eval/scenarios/study.yaml` with all 7 scenarios from the spec (confused-student, parking-lot, hyperfocus, win-recognition, wrong-answer, low-energy, deep-dive).

- [ ] **Step 6: Run tests — verify they pass**

```bash
uv run pytest packages/studyctl/tests/test_eval_models.py -x -v
```

- [ ] **Step 7: Commit**

```bash
git add packages/studyctl/src/studyctl/eval/ packages/studyctl/tests/test_eval_models.py
git commit -m "feat(eval): models, scenario loader, and study.yaml scenarios"
```

---

### Task 2: Git ops and reporter

**Files:**
- Create: `packages/studyctl/src/studyctl/eval/git_ops.py`
- Create: `packages/studyctl/src/studyctl/eval/reporter.py`
- Test: `packages/studyctl/tests/test_eval_reporter.py`

- [ ] **Step 1: Write failing tests**

```python
# test_eval_reporter.py
"""Tests for eval reporter — TSV logging and markdown generation."""
from __future__ import annotations
import pytest

class TestGitOps:
    def test_short_hash_returns_string(self):
        from studyctl.eval.git_ops import short_hash
        h = short_hash()
        assert isinstance(h, str)
        assert len(h) == 7 or h == "unknown"

class TestTSVReporter:
    def test_writes_header_on_first_call(self, tmp_path):
        from studyctl.eval.reporter import TSVReporter
        from studyctl.eval.models import JudgeResult, EvalSummary
        tsv = tmp_path / "eval-results.tsv"
        reporter = TSVReporter(tsv)
        summary = EvalSummary(
            agent="claude", persona_hash="abc123", commit="1234567",
            results=[
                JudgeResult(
                    scenario_id="test", heuristic_pass=True,
                    dimensions={"clarity": 3}, weights={"clarity": 1.0},
                ),
            ],
        )
        reporter.record(summary)
        content = tsv.read_text()
        lines = content.strip().splitlines()
        assert "scenario_id" in lines[0]  # header
        assert "test" in lines[1]         # data row
        assert "claude" in lines[1]

    def test_appends_without_duplicating_header(self, tmp_path):
        from studyctl.eval.reporter import TSVReporter
        from studyctl.eval.models import JudgeResult, EvalSummary
        tsv = tmp_path / "eval-results.tsv"
        reporter = TSVReporter(tsv)
        result = JudgeResult(
            scenario_id="t", heuristic_pass=True,
            dimensions={"clarity": 3}, weights={"clarity": 1.0},
        )
        for _ in range(2):
            reporter.record(EvalSummary(
                agent="claude", persona_hash="x", commit="y", results=[result],
            ))
        lines = tsv.read_text().strip().splitlines()
        header_count = sum(1 for l in lines if "scenario_id" in l)
        assert header_count == 1

class TestMarkdownReport:
    def test_report_contains_scenario_names(self, tmp_path):
        from studyctl.eval.reporter import TSVReporter
        from studyctl.eval.models import JudgeResult, EvalSummary
        reporter = TSVReporter(tmp_path / "r.tsv")
        summary = EvalSummary(
            agent="claude", persona_hash="abc", commit="1234567",
            results=[
                JudgeResult(
                    scenario_id="confused-student", heuristic_pass=True,
                    dimensions={"clarity": 4, "emotional_safety": 3},
                    weights={"clarity": 1.0, "emotional_safety": 2.0},
                ),
            ],
        )
        md = reporter.generate_markdown(summary)
        assert "confused-student" in md
        assert "claude" in md
```

- [ ] **Step 2: Run tests — verify they fail**

- [ ] **Step 3: Implement git_ops.py**

Extract `git_is_clean()` and `git_short_hash()` from `scripts/test_iterate.py` into `eval/git_ops.py`. Same logic, just relocated. Add `abort_if_dirty()` that raises `click.ClickException`.

- [ ] **Step 4: Implement reporter.py**

`TSVReporter` class with `record(summary)` and `generate_markdown(summary)`. TSV format matches spec: one row per scenario per run.

- [ ] **Step 5: Run tests — verify they pass**

- [ ] **Step 6: Commit**

```bash
git commit -m "feat(eval): git_ops and TSV/markdown reporter"
```

---

## Chunk 2: Heuristic Judge + LLM Client + LLM Judge

### Task 3: Heuristic judge

**Files:**
- Create: `packages/studyctl/src/studyctl/eval/judge/__init__.py`
- Create: `packages/studyctl/src/studyctl/eval/judge/base.py`
- Create: `packages/studyctl/src/studyctl/eval/judge/heuristic.py`
- Test: `packages/studyctl/tests/test_eval_heuristic.py`

- [ ] **Step 1: Write failing tests for each heuristic check**

Test cases per check:
- `contains_question`: "What do you think?" → pass; "Decorators wrap functions." → fail
- `no_rsd_triggers`: "Let's break this down" → pass; "It's easy, just do X" → fail
- `references_topic`: (topic="decorators") "The decorator pattern..." → pass; "Functions are great" → fail
- `suggests_break`: "Maybe take a quick break?" → pass; "Let's keep going" → fail
- `contains_positive_recognition`: "That connection you made is exactly right" → pass; "OK" → fail
- `recognition_is_specific`: "Your logging wrapper was a decorator" → pass; "Good job!" → fail

- [ ] **Step 2: Run tests — verify they fail**

- [ ] **Step 3: Implement heuristic.py**

Registry of check functions: `CHECKS: dict[str, Callable[[str, Scenario], bool]]`. Each check is a pure function taking `(response_text, scenario)` and returning `bool`. `run_heuristics(response, scenario)` returns `HeuristicResult`.

- [ ] **Step 4: Implement base.py** (Judge Protocol)

- [ ] **Step 5: Run tests — verify they pass**

- [ ] **Step 6: Commit**

```bash
git commit -m "feat(eval): heuristic judge with 6 structural checks"
```

---

### Task 4: LLM client (Ollama + OpenAI-compat)

**Files:**
- Create: `packages/studyctl/src/studyctl/eval/llm_client.py`
- Test: `packages/studyctl/tests/test_eval_llm_client.py`

- [ ] **Step 1: Write failing tests**

Test cases:
- `test_ollama_chat_success`: mock `POST /api/chat` → returns `{"message": {"content": "OK"}}`
- `test_openai_chat_success`: mock `POST /v1/chat/completions` → returns standard OpenAI shape
- `test_ollama_connection_error`: mock connection refused → raises `LLMClientError`
- `test_retry_on_429`: first call returns 429, second succeeds
- `test_timeout`: mock slow response → raises `LLMClientError`
- `test_api_key_passed_in_header`: verify `Authorization: Bearer {key}` for OpenAI-compat

Use `unittest.mock.patch("urllib.request.urlopen")` for all HTTP mocking.

- [ ] **Step 2: Run tests — verify they fail**

- [ ] **Step 3: Implement llm_client.py**

`LLMClient` class with `chat(messages, temperature)`. Two code paths: Ollama (`/api/chat`) and OpenAI-compat (`/v1/chat/completions`). Retry once on 429/503 with 5s backoff. 30s timeout. `LLMClientError` exception class.

- [ ] **Step 4: Run tests — verify they pass**

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(eval): LLM client for Ollama + OpenAI-compat"
```

---

### Task 5: LLM judge

**Files:**
- Create: `packages/studyctl/src/studyctl/eval/judge/llm.py`
- Create: `packages/studyctl/src/studyctl/eval/prompts/judge-rubric.md`
- Test: `packages/studyctl/tests/test_eval_llm_judge.py`

- [ ] **Step 1: Write failing tests**

Test cases:
- `test_builds_prompt_with_scenario_context`: verify rubric template is filled with scenario fields
- `test_parses_valid_json_scores`: mock LLM returns `{"clarity": 3, ...}` → parsed correctly
- `test_clamps_out_of_range_scores`: `{"clarity": 5}` → clamped to 4; `{"clarity": 0}` → clamped to 1
- `test_malformed_json_returns_zero_scores`: LLM returns garbage → `JudgeResult` with `heuristic_pass=True` but all dimensions score 1
- `test_heuristic_fail_skips_llm_call`: if heuristic fails, LLM `chat()` is never called

- [ ] **Step 2: Run tests — verify they fail**

- [ ] **Step 3: Create judge-rubric.md prompt template**

Copy from spec (the full template with `{{scenario_name}}`, `{{energy}}`, etc. placeholders).

- [ ] **Step 4: Implement llm.py**

`LLMJudge` class implementing `Judge` protocol. `score(scenario, response)`:
1. Run heuristic checks first
2. If heuristics fail → return zero-score `JudgeResult`
3. Build prompt from template + scenario context
4. Call `llm_client.chat()`
5. Parse JSON response, clamp scores to 1-4
6. Return `JudgeResult`

- [ ] **Step 5: Run tests — verify they pass**

- [ ] **Step 6: Commit**

```bash
git commit -m "feat(eval): LLM judge with rubric prompt and JSON score parsing"
```

---

## Chunk 3: Persona Target + Capture + Orchestrator

### Task 6: Response capture (tmux interaction)

**Files:**
- Create: `packages/studyctl/src/studyctl/eval/capture.py`
- Test: `packages/studyctl/tests/test_eval_capture.py`

- [ ] **Step 1: Write failing tests**

Test cases:
- `test_strip_ansi_codes`: input with `\x1b[32m` → stripped
- `test_extract_new_content`: baseline="Hello\n", full="Hello\nResponse\n" → "Response"
- `test_empty_response_returns_empty`: baseline == full → ""
- `test_capture_pane_plain_calls_tmux`: mock `subprocess.run` with `capture-pane` args

- [ ] **Step 2: Run tests — verify they fail**

- [ ] **Step 3: Implement capture.py**

`strip_ansi(text)`, `capture_pane_plain(session_name)`, `capture_response(session_name, prompt_text, timeout)` — all functions from the spec's capture strategy section.

- [ ] **Step 4: Run tests — verify they pass**

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(eval): tmux pane capture with ANSI stripping"
```

---

### Task 7: Persona eval target

**Files:**
- Create: `packages/studyctl/src/studyctl/eval/targets/__init__.py`
- Create: `packages/studyctl/src/studyctl/eval/targets/base.py`
- Create: `packages/studyctl/src/studyctl/eval/targets/persona.py`
- Test: `packages/studyctl/tests/test_eval_persona_target.py` (integration, marked `@pytest.mark.integration`)

- [ ] **Step 1: Implement base.py (EvalTarget Protocol)**

```python
from typing import Protocol
from studyctl.eval.models import Scenario

class EvalTarget(Protocol):
    name: str
    def setup(self, scenario: Scenario) -> None: ...
    def run(self, scenario: Scenario) -> str: ...
    def teardown(self) -> None: ...
```

- [ ] **Step 2: Implement persona.py**

`PersonaTarget` class:
- `setup(scenario)`: start session via subprocess (`studyctl study start {topic} --energy {energy} --agent {agent}`), poll `session-state.json`, inject `elapsed_minutes` via `write_session_state()`
- `run(scenario)`: send `setup_prompts` via `tmux send-keys` with delays, send `prompt`, call `capture_response()`, return response text
- `teardown()`: run `studyctl study --end`, verify session ended

- [ ] **Step 3: Write integration test (mock agent)**

Test with `STUDYCTL_TEST_AGENT_CMD` set to a script that echoes a fixed response when it receives input. Verify the target starts a session, sends a prompt, and captures the response.

Mark as `@pytest.mark.integration` (excluded from CI fast path).

- [ ] **Step 4: Commit**

```bash
git commit -m "feat(eval): persona eval target with tmux session management"
```

---

### Task 8: Test suite target (refactor existing)

**Files:**
- Create: `packages/studyctl/src/studyctl/eval/targets/test_suite.py`
- Modify: `scripts/test_iterate.py`

- [ ] **Step 1: Extract test runner logic into test_suite.py**

Move `run_tests()`, `parse_junit_xml()`, `build_iteration_result()` from `scripts/test_iterate.py` into `eval/targets/test_suite.py`. These become methods on a `TestSuiteTarget` class (though this target uses a different interface than `EvalTarget` — it runs pytest, not scenarios).

- [ ] **Step 2: Extract reporter logic**

Move `log_result()`, `generate_report()`, `show_progress()`, `_read_source_context()` into `eval/reporter.py` as a `TestSuiteReporter` class (separate from `TSVReporter` — different TSV schema).

- [ ] **Step 3: Slim down test_iterate.py**

Replace the monolithic script with thin wrappers calling the extracted modules. The script's CLI interface (`--max-iterations`, `--agent`, `--report`, `--progress`) remains identical.

- [ ] **Step 4: Verify existing behaviour preserved**

```bash
uv run python scripts/test_iterate.py --progress
# Should display existing results.tsv history unchanged
```

- [ ] **Step 5: Commit**

```bash
git commit -m "refactor(eval): extract test_iterate.py into eval/ modules"
```

---

### Task 9: Orchestrator

**Files:**
- Create: `packages/studyctl/src/studyctl/eval/orchestrator.py`
- Test: `packages/studyctl/tests/test_eval_orchestrator.py`

- [ ] **Step 1: Write failing tests**

Test cases (all use mock target + mock judge):
- `test_runs_all_scenarios_with_setup_teardown`: verify setup/teardown called per scenario
- `test_heuristic_failure_skips_llm`: scenario fails heuristic → judge.score still returns result but with heuristic_pass=False
- `test_timeout_recorded`: target.run raises EvalTimeout → recorded as timeout result
- `test_summary_contains_all_results`: 3 scenarios → summary has 3 results
- `test_reporter_called_with_summary`: verify reporter.record() called once

- [ ] **Step 2: Run tests — verify they fail**

- [ ] **Step 3: Implement orchestrator.py**

`run_evaluation(target, judge, scenarios, reporter, agent)` function matching the spec's orchestrator loop.

- [ ] **Step 4: Run tests — verify they pass**

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(eval): orchestrator loop with per-scenario isolation"
```

---

## Chunk 4: CLI, Config, Doctor Integration

### Task 10: Config schema

**Files:**
- Modify: `packages/studyctl/src/studyctl/settings.py`

- [ ] **Step 1: Add EvalConfig dataclass**

```python
@dataclass
class EvalJudgeConfig:
    provider: str = "ollama"
    base_url: str = "http://localhost:11434"
    model: str = "gemma4:26b"
    api_key_env: str = ""

@dataclass
class EvalConfig:
    judge: EvalJudgeConfig = field(default_factory=EvalJudgeConfig)
```

- [ ] **Step 2: Wire into Settings and config loading**

Add `eval: EvalConfig` to `Settings` dataclass. Load from `config.yaml` `eval:` section.

- [ ] **Step 3: Add to CONFIG_TEMPLATE**

Add commented-out `eval:` block to the config template string.

- [ ] **Step 4: Commit**

```bash
git commit -m "feat(eval): config schema for judge provider settings"
```

---

### Task 11: CLI commands

**Files:**
- Create: `packages/studyctl/src/studyctl/cli/_eval.py`
- Modify: `packages/studyctl/src/studyctl/cli/__init__.py`
- Test: `packages/studyctl/tests/test_eval_cli.py`

- [ ] **Step 1: Write failing tests**

```python
# test_eval_cli.py — CliRunner tests
# test_eval_setup_detects_no_ollama: mock HTTP failure → prints "Ollama not running"
# test_eval_setup_recommends_model: mock RAM detection → prints model recommendation
# test_eval_history_no_data: no TSV file → "No evaluation history"
# test_eval_run_missing_scenarios: bad --scenarios path → error
```

- [ ] **Step 2: Implement _eval.py**

`eval_group` Click group with three commands:
- `eval setup` — hardware detection, Ollama check, model recommendation, config YAML output
- `eval run --scenarios YAML [--agent NAME]` — load scenarios, create target + judge, call orchestrator
- `eval history` — read `eval-results.tsv`, display table

- [ ] **Step 3: Register in CLI LazyGroup**

Add `"eval": "studyctl.cli._eval:eval_group"` to the LazyGroup in `cli/__init__.py`.

- [ ] **Step 4: Run tests — verify they pass**

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(eval): CLI commands — eval run, eval history, eval setup"
```

---

### Task 12: Doctor integration

**Files:**
- Modify: `packages/studyctl/src/studyctl/doctor/models.py`
- Modify: `packages/studyctl/src/studyctl/doctor/config.py`

- [ ] **Step 1: Add "eval" to VALID_CATEGORIES**

- [ ] **Step 2: Add eval provider check**

Check if `eval.judge.provider == "ollama"` → verify Ollama is reachable. Check if configured model is available. Report as info/warn (not fail — eval is optional).

- [ ] **Step 3: Commit**

```bash
git commit -m "feat(eval): doctor integration for eval provider health"
```

---

### Task 13: Full integration test

- [ ] **Step 1: Run entire non-E2E test suite**

```bash
uv run pytest packages/studyctl/tests/ -x --ignore=packages/studyctl/tests/test_web_sidebar.py --ignore=packages/studyctl/tests/test_harness_matrix.py -m "not integration and not e2e" -q
```

Verify all tests pass including all new eval tests.

- [ ] **Step 2: Run CLI smoke test**

```bash
uv run studyctl eval setup
uv run studyctl eval history
```

- [ ] **Step 3: Commit all remaining changes**

```bash
git commit -m "test(eval): integration verification — all tests passing"
```
