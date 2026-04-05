---
title: "feat: Persona Optimisation Tier 2 — Autonomous Evaluation Harness"
type: feat
status: designed
date: 2026-04-05
---

# Persona Optimisation Tier 2 — Autonomous Evaluation Harness

## Problem

The study persona (`agents/shared/personas/study.md`) is a static markdown file tuned by hand. Tier 1 added `persona_hash` tracking and win/struggle counts per session, but evaluation still requires a human running real study sessions.

We need an automated loop that:
1. Starts a study session with the current persona
2. Sends fixed student scenarios to the running agent
3. Captures and judges the agent's responses
4. Scores against a rubric weighted for AuDHD-critical behaviours
5. Tracks scores per persona version so improvements can be measured

## Design Decisions

### D1: Judge Architecture — External LLM ("Watcher Watching the Watcher")

The study agent cannot judge itself — self-evaluation is biased toward self-approval. A separate LLM evaluates responses against a rubric:

- **Ollama** — for local inference (free, private, works on LAN GPU boxes)
- **OpenAI-compatible API** — covers LM Studio, vLLM, Bedrock-via-proxy, Anthropic-via-proxy, and any remote provider

No separate Anthropic/Bedrock/OpenAI SDK integrations. The OpenAI-compatible spec is the universal adapter.

### D2: Scoring — Hybrid (Heuristic Gate + LLM Judge)

1. **Heuristic checks** — fast, deterministic, free. Catches structural failures.
2. **LLM judge** — runs only on heuristic-passing responses. Scores 7 dimensions on a 1-4 scale.

Responses that fail heuristics score 0 without burning a judge LLM call.

### D3: Session Isolation — One Session Per Scenario

Each scenario gets its own fresh session (start → prompt → capture → end). This prevents context contamination between scenarios. Trade-off: ~6 session startups per eval run (~2-3 minutes overhead). Accepted because evaluation is a background activity, and reproducibility is non-negotiable for a measurement tool.

### D4: No Automated Mutation in V1

V1 focuses on **evaluation only**. The user edits `study.md` manually, then runs `eval run` again. The system detects the persona changed via `persona_hash` and records it as a new baseline. This keeps the first delivery focused on the hard part (reliable scoring) and defers prompt generation (which needs its own design).

### D5: Git Strategy — Abort on Dirty Tree

If the working tree is dirty, `eval run` aborts with a clear error. No stash. Matches the existing `test_iterate.py` pattern. `--no-git-check` escape hatch for development.

### D6: Judge Prompt is Versioned and Autoresearch-Monitored

The judge prompt lives in a versioned file (`eval/prompts/judge-rubric.md`). The autoresearch iterate framework can monitor judge consistency by running the same scenario+response pair through the judge N times and measuring score variance. A good prompt produces low variance. This creates a positive cascade: better judge → more reliable scores → better persona iterations.

### D7: Win Recognition in Persona

The mentor persona should explicitly call out at least one specific, earned win per session. Not "great job!" (hollow), but "you spotted the over-engineering before I did — that's architectural thinking" (specific, evidenced). AuDHD brains detect hollow praise instantly; specific recognition builds genuine confidence. This is both a persona change recommendation and an evaluation scenario.

## Orchestrator Refactor

The current `scripts/test_iterate.py` is a monolithic ~300-line script. Refactor into a modular orchestrator where "what to evaluate" is a pluggable target:

```
packages/studyctl/src/studyctl/eval/
├── __init__.py
├── orchestrator.py          # The loop: load target → run → judge → record
├── targets/
│   ├── __init__.py
│   ├── base.py              # EvalTarget protocol
│   ├── test_suite.py        # Existing: run pytest, parse JUnit XML
│   └── persona.py           # New: run scenarios against live session
├── judge/
│   ├── __init__.py
│   ├── base.py              # Judge protocol
│   ├── heuristic.py         # Structural checks
│   └── llm.py               # Ollama/OpenAI-compat rubric scoring
├── llm_client.py            # Thin HTTP client for Ollama + OpenAI-compat
├── scenarios.py             # Load/validate YAML scenario definitions
├── capture.py               # tmux pane capture + ANSI stripping
├── reporter.py              # TSV logging, markdown report generation
├── git_ops.py               # git clean check, abort on dirty
└── prompts/
    └── judge-rubric.md      # Versioned judge prompt template
```

## Interfaces

### EvalTarget Protocol

```python
class EvalTarget(Protocol):
    name: str

    def setup(self, scenario: Scenario) -> None:
        """Prepare for a single scenario (start session, set energy/time)."""

    def run(self, scenario: Scenario) -> str:
        """Send scenario prompt, capture and return the agent's response."""

    def teardown(self) -> None:
        """Clean up (end session, kill tmux)."""
```

Note: `setup/run/teardown` operate per-scenario (not per-eval-run) due to session isolation (D3). The orchestrator calls the cycle for each scenario independently.

### Judge Protocol

```python
class Judge(Protocol):
    def score(self, scenario: Scenario, response: str) -> JudgeResult:
        """Score a single response. Returns dimensions + pass/fail."""
```

### Orchestrator Loop (V1 — No Mutation)

```python
def run_evaluation(
    target: EvalTarget,
    judge: Judge,
    scenarios: list[Scenario],
    reporter: Reporter,
    agent: str,
) -> EvalSummary:
    results = []
    for scenario in scenarios:
        target.setup(scenario)
        try:
            response = target.run(scenario)
            score = judge.score(scenario, response)
        except EvalTimeout:
            score = JudgeResult.timeout(scenario)
        finally:
            target.teardown()
        results.append(score)

    summary = reporter.record(results, agent=agent)
    reporter.write_markdown(results)
    return summary
```

## Scenarios

Seven fixed scenarios stored in `eval/scenarios/study.yaml`:

| # | ID | Name | Priority | Tests |
|---|---|---|---|---|
| 1 | `confused-student` | Confused Student | Critical | Socratic response, no lecturing, RSD-safe language |
| 2 | `parking-lot` | Parking Lot Trigger | Critical | Detects tangent, suggests `studyctl park`, redirects |
| 3 | `hyperfocus` | Hyperfocus Intervention | Critical | References timer/break, gentle not jarring |
| 4 | `win-recognition` | Win Recognition | Critical | Calls out a specific, earned win (not hollow praise) |
| 5 | `wrong-answer` | Got It Wrong | High | Catches misconception, gentle correction |
| 6 | `low-energy` | Low Energy | High | Shorter chunks, micro-breaks, doesn't push |
| 7 | `deep-dive` | High Energy Deep Dive | Normal | Goes deep, doesn't over-scaffold |

### Scenario YAML Format

```yaml
scenarios:
  - id: confused-student
    name: Confused Student
    priority: critical
    topic: Python Decorators
    energy: 5
    elapsed_minutes: 10           # written to session-state.json
    prompt: |
      I've read the chapter on decorators three times and I still
      don't get it. I feel stupid.
    setup_prompts: []             # optional: conversation context before test prompt
    heuristic_checks:
      - contains_question         # response must ask a question
      - no_rsd_triggers           # no "it's easy", "just", "simply"
      - references_topic          # mentions decorators
    rubric_weights:
      emotional_safety: 2.0       # double-weighted for AuDHD scenarios

  - id: hyperfocus
    name: Hyperfocus Intervention
    priority: critical
    topic: Python Decorators
    energy: 3
    elapsed_minutes: 45           # harness writes fake start_time to IPC
    prompt: |
      OK so if I chain three decorators, the inner one executes first right?
      And what about decorators with arguments — how does the extra wrapper
      layer work? Actually, can you also explain descriptors while we're at it?
    setup_prompts:
      - "Let's study Python decorators"
      - "A decorator wraps a function, right?"
    heuristic_checks:
      - suggests_break
      - does_not_shame
    rubric_weights:
      emotional_safety: 2.0
      energy_adaptation: 2.0

  - id: win-recognition
    name: Win Recognition
    priority: critical
    topic: Python Decorators
    energy: 6
    elapsed_minutes: 20
    prompt: |
      Oh wait — so when I wrote that logging wrapper last week, that
      was actually a decorator pattern? I just didn't use the @ syntax!
    setup_prompts:
      - "Let's study Python decorators"
      - "I'm confused about what decorators actually do"
    heuristic_checks:
      - contains_positive_recognition   # must acknowledge the student's insight
      - recognition_is_specific         # must reference what the student did, not generic "good job"
    rubric_weights:
      emotional_safety: 2.0
      win_recognition: 2.0
```

### Energy and Elapsed Time Injection

Each scenario specifies `energy` and `elapsed_minutes`. Before sending the prompt, the harness writes directly to `session-state.json`:

```python
write_session_state({
    "energy": scenario.energy,
    "started_at": (datetime.now(UTC) - timedelta(minutes=scenario.elapsed_minutes)).isoformat(),
})
```

This gives the agent accurate state to read, rather than relying on `setup_prompts` to describe state verbally (which tests prompt-following, not state-awareness — a weaker signal).

## Judge Rubric (7 Dimensions, 1-4 Scale)

| Dimension | 1 (Poor) | 2 (Below) | 3 (Good) | 4 (Excellent) |
|-----------|----------|-----------|----------|---------------|
| **Clarity** | Confusing or wall-of-text | Mostly clear, some jargon unexplained | Clear with concrete examples | Crystal clear, progressive disclosure |
| **Socratic Quality** | Lectures / gives answer | Asks question but answers it immediately | Genuine question that guides discovery | Question chain that builds understanding |
| **Emotional Safety** | "It's easy" / dismissive | Neutral, doesn't acknowledge struggle | Validates feelings, normalises difficulty | Validates + reframes as progress |
| **Energy Adaptation** | Ignores energy level | Mentions energy but doesn't adapt | Adapts chunk size and complexity | Adapts + proactively suggests breaks |
| **Tool Usage** | Never suggests studyctl commands | Mentions logging vaguely | Uses topic/park commands appropriately | Integrates tools naturally into flow |
| **Topic Focus** | Goes off on tangent | Stays on topic but doesn't redirect | Redirects gently when student wanders | Parks tangents + redirects + returns |
| **Win Recognition** | Never acknowledges progress | Generic praise ("good job") | Acknowledges specific achievement | Specific + connects to broader growth |

### Weighted Scoring

Default weight 1.0 per dimension. Scenarios override via `rubric_weights`. AuDHD-critical scenarios double-weight `emotional_safety`. The `win-recognition` scenario double-weights `win_recognition`.

**Score calculation:** `weighted_sum / max_possible_weighted_sum × 100`

**Pass threshold:** ≥ 70% weighted score AND all heuristic checks pass.

## Judge Prompt Template

Stored in `eval/prompts/judge-rubric.md`, versioned in git:

```markdown
You are an evaluation judge for an AI study mentor. Your task is to score
the mentor's response to a student scenario.

## Context
- **Scenario:** {{scenario_name}}
- **Student energy level:** {{energy}}/10
- **Session elapsed:** {{elapsed_minutes}} minutes
- **Topic:** {{topic}}

## Student said:
{{prompt}}

## Mentor responded:
{{response}}

## Rubric
Score each dimension from 1 (poor) to 4 (excellent). Use ONLY integers 1-4.
Be strict — a score of 3 means genuinely good, not "adequate". Default to 2
unless the response clearly earns higher. Do NOT be lenient.

{{rubric_table}}

## Critical notes
- This mentor serves AuDHD learners. Emotional safety is paramount.
- "It's easy" / "just" / "simply" language is a 1 on emotional_safety regardless
  of other qualities.
- Generic praise ("great job!") without specifics scores 1-2 on win_recognition.

Respond with ONLY this JSON, no other text:
{"clarity": N, "socratic_quality": N, "emotional_safety": N,
 "energy_adaptation": N, "tool_usage": N, "topic_focus": N,
 "win_recognition": N}
```

Temperature: 0.1 (deterministic scoring).

### Judge Consistency Monitoring (Autoresearch)

The judge prompt is itself a target for the autoresearch framework:
1. Run the same scenario+response pair through the judge 5 times
2. Measure score variance per dimension
3. Flag if any dimension has variance > 0.5 (on 1-4 scale)
4. When the judge prompt is edited, re-run consistency check

This is a future enhancement wired into the iterate runner as `--target judge-consistency`.

## Response Capture

### Capture Strategy

```python
import re

ANSI_RE = re.compile(r'\x1b\[[0-9;]*[a-zA-Z]')

def capture_response(session_name: str, prompt_text: str, timeout: int = 90) -> str:
    """Capture agent response from tmux pane.

    1. Record pane content before sending prompt (baseline)
    2. Send prompt via tmux send-keys
    3. Poll pane until output stabilises (5s of no change)
    4. Extract new content (diff from baseline)
    5. Strip ANSI escape codes
    """
    baseline = _capture_pane_plain(session_name)
    tmux_send_keys(session_name, prompt_text)

    prev = baseline
    stable_count = 0
    for _ in range(timeout):
        content = _capture_pane_plain(session_name)
        if content == prev:
            stable_count += 1
            if stable_count >= 5:
                break
        else:
            stable_count = 0
            prev = content
        time.sleep(1)

    new_content = content[len(baseline):]
    return ANSI_RE.sub('', new_content).strip()


def _capture_pane_plain(session_name: str) -> str:
    """tmux capture-pane in plaintext mode (no ANSI)."""
    result = subprocess.run(
        ["tmux", "capture-pane", "-t", session_name, "-p", "-S", "-"],
        capture_output=True, text=True,
    )
    return result.stdout
```

**Edge cases:**
- **Agent streams with spinners**: The `-p` flag to `capture-pane` captures the final rendered state, not intermediate frames. The 5-second stability check handles streaming.
- **Agent doesn't respond (timeout)**: After 90 seconds, return whatever was captured. The heuristic checks will fail it.
- **Empty pane**: Return empty string. Heuristics fail it (no question, no topic reference).
- **Agent asks clarifying question before answering**: The capture includes the clarifying question. The judge evaluates the full response including the question.

## LLM Client

### Configuration (`~/.config/studyctl/config.yaml`)

```yaml
eval:
  judge:
    provider: ollama              # "ollama" or "openai-compat"
    base_url: http://localhost:11434
    model: gemma4:26b             # MoE: 4B active params, frontier-quality JSON output
    # For remote Ollama on LAN (e.g. a GPU box):
    # base_url: http://192.168.1.100:11434
    #
    # For OpenAI-compatible providers (LM Studio, vLLM, Bedrock-via-proxy):
    # provider: openai-compat
    # base_url: https://api.example.com/v1
    # model: gpt-4o-mini
    # api_key_env: EVAL_API_KEY   # env var name, not the key itself
```

### Model Selection — Why Gemma 4 26B MoE

The judge needs two things: reliable JSON output and strong reasoning about pedagogy.

**Gemma 4 26B-A4B** (MoE, 4B active / 26B total) is the recommended default:
- **Native JSON**: Generates structured `{"clarity": 3, ...}` without grammar constraints
- **Frontier reasoning**: 1441 Arena score, MMLU Pro 82.6% — near GPT-4 class
- **Fast inference**: Only 4B parameters active per forward pass (MoE architecture)
- **Moderate RAM**: ~18GB to load — fits on machines with 32GB+ RAM
- **Available on Ollama**: `ollama pull gemma4:26b`

This single model covers the majority of hardware tiers because the MoE architecture gives 30B+ quality at 4B speed.

### Hardware Tiers and Model Recommendations

| Hardware | RAM | Model | Quality | Speed | Notes |
|----------|-----|-------|---------|-------|-------|
| Apple Silicon + ≥32GB | 32-128GB | `gemma4:26b` | Excellent | Fast (~5s) | Ideal setup |
| CPU-only + ≥32GB | 32-64GB | `gemma4:26b` | Excellent | Moderate (~15s) | MoE keeps inference fast even on CPU |
| 16-32GB | 16-32GB | `gemma4:26b` (tight) | Excellent | Moderate | Fits in ~18GB; may need to close other apps |
| 8-16GB | 8-16GB | `nemotron-3-nano:4b` | Good | Fast | Fallback when Gemma MoE doesn't fit |
| <8GB (e.g. Pi 5) | <8GB | N/A — use OpenAI-compat | Varies | Network-bound | Point at a LAN machine running Ollama |

**LAN offloading**: Users with a low-end dev machine can point `base_url` at a more powerful machine on their network running Ollama. The eval harness just needs HTTP access — no local GPU required.

### `studyctl eval setup`

Read-only diagnostics — does NOT write to config. Prints copy-pasteable YAML.

1. Check if Ollama is running (`GET /api/tags`)
   - Not running → print instructions to start it
2. Detect available RAM (`sysctl hw.memsize` on macOS, `/proc/meminfo` on Linux)
3. Detect Apple Silicon / GPU presence
4. Recommend model based on hardware tier table above
5. Check if recommended model is downloaded (`ollama list`)
   - Missing → print `ollama pull {model}` command with download size warning
6. Test a minimal chat request (send "Respond with only: OK" and verify)
7. Print recommended config YAML block as copy-pasteable output

### API Shape

```python
class LLMClient:
    """Thin client for Ollama + OpenAI-compatible endpoints."""

    def __init__(self, base_url: str, model: str, api_key: str = ""):
        ...

    def chat(self, messages: list[dict], temperature: float = 0.1) -> str:
        """Send chat completion. Returns assistant message content.

        Raises LLMClientError on HTTP errors, timeouts (30s), malformed responses.
        Retries once on 429/503 with 5s backoff.
        """
```

Ollama: `POST /api/chat` with `{"model": ..., "messages": [...], "stream": false}`.
OpenAI-compat: `POST /v1/chat/completions` with standard schema.

## Reporter

### TSV Format — Separate File (`eval-results.tsv`)

```
iteration  timestamp  agent  scenario_id  heuristic_pass  avg_score  clarity  socratic  emotional  energy_adapt  tools  focus  win_recog  commit  persona_hash
1  2026-04-05T18:00:00  claude  confused-student  true  81.2  3  4  4  3  2  3  0  abc1234  fa3e9b2c
```

One row per scenario per run. Separate from the existing `results.tsv` (test suite target) — no schema conflict.

### Markdown Report

Per-run breakdown:
- Agent name and persona hash
- Per-scenario: name, heuristic pass/fail, per-dimension scores, weighted total
- Delta from previous run (if exists)
- Overall pass/fail and average score

## CLI Integration

```bash
# Evaluate current persona (7 scenarios, one session each)
studyctl eval run --scenarios study [--agent claude]

# Show evaluation score history
studyctl eval history

# Hardware detection + model recommendation (read-only)
studyctl eval setup

# Verify judge consistency (autoresearch)
studyctl eval check-judge --scenarios study --repeats 5
```

`--agent` defaults to the first detected agent. Agent name is recorded in every TSV row for reproducibility.

## Doctor Integration

Add `"eval"` to `VALID_CATEGORIES` in `doctor/models.py`. New checks:
- Ollama reachable (if `eval.judge.provider == "ollama"`)
- Configured model available
- Judge prompt file exists

## Implementation Phases

| Phase | Scope | Effort |
|-------|-------|--------|
| **Phase 1: Orchestrator refactor** | Extract `test_iterate.py` into `eval/` modules. `EvalTarget` protocol, `test_suite` target (preserves existing behaviour), `reporter`, `git_ops`. | Small |
| **Phase 2: LLM client + judge** | `llm_client.py` (Ollama + OpenAI-compat), `heuristic.py`, `llm.py` judge, judge prompt template, `eval setup` command with hardware detection. | Medium |
| **Phase 3: Persona eval target + capture** | `persona.py` target, scenario YAML loader, `capture.py` (tmux interaction, ANSI stripping, response extraction), IPC state injection. | Medium |
| **Phase 4: CLI + integration** | Wire `studyctl eval run/history/setup` commands, config schema, doctor checks, end-to-end test with mock agent. | Small |

## Testing Strategy

- **LLM client**: mock HTTP responses for Ollama and OpenAI-compat schemas, test retry on 429/503
- **Heuristic judge**: pure functions, unit testable with fixed response strings
- **LLM judge**: mock `llm_client.chat()`, verify prompt construction and JSON score parsing, test malformed/out-of-range score handling (clamp to 1-4)
- **Orchestrator**: mock target + judge, verify per-scenario loop with setup/teardown cycle
- **Capture**: mock `tmux capture-pane`, test ANSI stripping, baseline diff, timeout handling
- **Persona target**: integration test with `STUDYCTL_TEST_AGENT_CMD` mock agent (extend `matrix_agent` to echo a fixed response when it receives a prompt)
- **Scenarios**: validate YAML loading, required fields, weight calculation, energy/elapsed injection
- **Reporter**: verify TSV row format, markdown generation, delta calculation

## Acceptance Criteria

- [ ] `studyctl eval setup` detects Ollama, recommends model, prints config YAML
- [ ] `studyctl eval run --scenarios study` runs 7 scenarios (one session each), produces scores
- [ ] Heuristic checks gate LLM judge calls (fail-fast on structural issues)
- [ ] LLM judge scores 7 dimensions on 1-4 scale with weighted aggregation
- [ ] Results logged to `eval-results.tsv` with agent name, persona hash, git commit
- [ ] Markdown report generated per run with per-scenario breakdown
- [ ] `studyctl eval history` shows score progression across runs
- [ ] Existing `scripts/test_iterate.py` behaviour preserved via `test_suite` target
- [ ] Config schema documented in `config.yaml` template
- [ ] Judge prompt versioned in `eval/prompts/judge-rubric.md`
- [ ] `studyctl doctor` reports eval provider health
- [ ] Win-recognition scenario validates specific (not hollow) praise
