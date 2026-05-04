# D2 Provider Benchmark — Card Generation (3-way)

*Run: 2026-05-04 · Branch: `feat/d1-card-schemas` (to be renamed)*

Hardware / backends:
- **Local Ollama** on MacBook Pro M4 Max, 128 GB unified memory, localhost:11434
- **AWS Bedrock** via profile `bedrock-prod`, region `us-east-1`, inference profile `us.anthropic.claude-sonnet-4-6`

Source material: 3 AWS Data Engineering Bootcamp study-notes from the user's Obsidian vault (`Ultimate_AWS_Data_Engineering_Bootcamp_with_Real_World_Labs/study-notes/`). Same inputs for all three providers; same prompts; same pydantic schema constraint.

## Performance — cards/min and wall time

| Provider | Model | Note | Chars | Items | Wall time |
|---|---|---|---|---|---|
| Ollama | qwen2.5:7b | Section 2 flashcards | 52,122 | 12 cards | 53.6 s |
| Ollama | qwen2.5:7b | Section 2 quiz | — | 8 questions | 81.4 s |
| Ollama | qwen2.5:7b | Section 4 flashcards | 54,366 | 13 cards | 150.5 s |
| Ollama | qwen2.5:7b | Section 7 flashcards | 32,329 | 12 cards | 62.3 s |
| **Ollama qwen2.5:7b total (serial)** | | | 138,817 | **37 cards + 8 Q** | **~5.8 min** |
| Ollama | qwen2.5:14b | Section 2 flashcards | 52,122 | 12 cards | 132.3 s |
| Ollama | qwen2.5:14b | Section 2 quiz | — | 8 questions | 186.8 s |
| Ollama | qwen2.5:14b | Section 4 flashcards | 54,366 | 12 cards | 131.6 s |
| Ollama | qwen2.5:14b | Section 7 flashcards | 32,329 | 12 cards | 123.4 s |
| **Ollama qwen2.5:14b total (serial)** | | | 138,817 | **36 cards + 8 Q** | **~9.6 min** |
| Bedrock | Sonnet 4.6 | Section 2 flashcards | 52,122 | 12 cards | 62.6 s |
| Bedrock | Sonnet 4.6 | Section 2 quiz | — | 8 questions | 95.0 s |
| Bedrock | Sonnet 4.6 | Section 4 flashcards | 54,366 | 20 cards | 88.5 s |
| Bedrock | Sonnet 4.6 | Section 7 flashcards | 32,329 | 12 cards | 70.9 s |
| **Bedrock Sonnet 4.6 total (serial)** | | | 138,817 | **44 cards + 8 Q** | **~5.3 min** |
| **Bedrock Sonnet 4.6 total (concurrent, max_workers=4)** | | | 138,817 | **45 cards + 8 Q** | **~1.6 min** |

The concurrent run is **~3.3× faster** than serial — bounded by the slowest single task (the quiz at 96.5 s) since all 4 tasks overlap in time. All tasks succeeded first-try, zero retries, zero throttles, region fallback never fired.

## Concurrency + regional load balancing

Two independent mechanisms layered together:

1. **Thread-pool concurrency** via `content.generators.runner.generate_concurrently`. Any `CardGenerator` implementation works. `max_workers=4` by default — matches the Bedrock per-account concurrency sweet spot and is configurable via `card_generator.max_workers` in `config.yaml`.

2. **Cross-region fallback on throttle** inside `BedrockGenerator`. Primary `(region, model)` pair tries first; on `ThrottlingException` only, retries once on the secondary pair. Default: `us-east-1` / `us.anthropic.claude-sonnet-4-6` with fallback to `eu-west-1` / `eu.anthropic.claude-sonnet-4-6`. Configurable; set `fallback_region: ""` to disable.

Networking analogy: the thread pool is an **ECMP hash bucket** (each flow lands in one bucket and stays there to completion), and the region fallback is **per-flow active/standby** at the request layer. Composition gives you ECMP-of-active/standby — the right model for bursty per-file workloads with predictable completion.

## Resource + cost footprint

| Provider | Local GPU mem | Local CPU | Cost (this run) | Off-network? |
|---|---|---|---|---|
| Ollama qwen2.5:7b | 8.2 GB (Metal) | idle ~0% | $0.00 | yes |
| Ollama qwen2.5:14b | 17 GB (Metal) | idle ~0% | $0.00 | yes |
| Bedrock Sonnet 4.6 | — | idle ~0% | ~$0.30 (est.) | no |

Python driver peak RSS: 53–75 MB for all runs. The real memory is either GPU (Ollama) or remote (Bedrock).

## Reliability

| Provider | Runs | Successes | Retries fired | Errors |
|---|---|---|---|---|
| Ollama qwen2.5:7b | 4 | 4 | 0 | 0 |
| Ollama qwen2.5:14b | 4 | 4 | 0 | 0 |
| Bedrock Sonnet 4.6 | 4 | 4 | 0 | 0 |

All 12 generations across all three providers succeeded first-try. The retry-on-parse-failure path in both `OllamaGenerator` and `BedrockGenerator` exists as insurance but was never exercised in the acceptance run. Ollama's `format`-param structured output and Bedrock's forced tool-use are both solid on this workload.

## Quality — side-by-side sample (Section 2, "RPU in Redshift Serverless")

Same source, same prompt, same schema. Compare the back of the "RPU" flashcard from each model:

**Ollama qwen2.5:7b**:
> An **RPU (Redshift Processing Unit)** is the capacity unit for Redshift Serverless, providing 16 GB of RAM. It's used to allocate compute resources dynamically based on workload needs.

**Ollama qwen2.5:14b**:
> An RPU (Redshift Processing Unit) is the capacity unit for Redshift Serverless, providing 16 GB of RAM. It's used to allocate compute resources dynamically based on workload needs.

**Bedrock Sonnet 4.6**:
> **RPU (Redshift Processing Unit)**: the capacity unit for Redshift Serverless. 1 RPU = 16 GB RAM. The minimum allocation is 8 RPUs (128 GB RAM total).
>
> **Billing**: you are charged only for the **seconds of compute used during active query execution** (RPU-seconds). When no queries are running, the workgroup is idle and you are not billed for compute.
>
> **Why cost-effective for a lab**: a provisioned Redshift cluster bills per-hour for every node whether idle or not. A course lab runs queries sporadically — maybe a few minutes per session. Serverless means you pay only for those few minutes rather than for 24 hours of idle cluster time.

The qwen2.5 answers are correct but terse — defining the term without explaining why it matters. Sonnet 4.6 answers the same question as a mentor would: definition + billing mechanics + "why you'd pick this over the alternative". This pattern holds across the decks.

## Quality — quiz distractor depth

The "Section 2" quiz question about TCP connection refused to Redshift is the cleanest comparison because all three models picked roughly the same question concept. Comparing the distractors:

- **qwen2.5:7b** — 3 options (ignored the "4 options" prompt). Distractors are plausible but short, one-line rationales.
- **qwen2.5:14b** — 3 or 4 options depending on question. The 14b model produced one **factually wrong** answer on a different Section 2 question: flagged "namespace-sharing" as the "primary advantage of Redshift Serverless" when the source material clearly identifies auto-scaling / per-second billing as the primary benefit. This is a **correctness issue**, not a quality gap.
- **Sonnet 4.6** — 4 options consistently. Each distractor is a *specific common mistake a learner would make* (wrong IAM role, wrong conn_id, wrong service boundary) with a one-paragraph rationale explaining exactly why it's wrong. This is the quiz quality the prompt was asking for.

## Flashcard volume — Section 4 anomaly

Sonnet 4.6 produced **20 cards** for Section 4 (Step Functions + Glue + Redshift) vs 12–13 for the Ollama models. Section 4 is the densest source note (54K chars, 1161 lines). The Sonnet output covers more concepts without either redundancy or fabrication — the prompt says "6–12 cards per source chunk, more is acceptable if the source covers that many distinct ideas." Sonnet exercised that flexibility; the Ollama models did not. Neither is wrong by the prompt, but for dense source material Sonnet's output is more thorough.

## Recommendations

| Use case | Recommendation |
|---|---|
| Daily card generation, privacy-sensitive or offline | **Ollama qwen2.5:7b** — fast, zero cost, 8 GB GPU. Cards are correct and useful. |
| Card generation where card quality matters (study material, published decks) | **Bedrock Sonnet 4.6** — materially better rationales, scenario-based fronts, ~$0.07 per deck. |
| Ollama qwen2.5:14b | **Skip.** 2× slower than 7b, 2× the memory, and produced one factual hallucination in the quiz. No measurable quality advantage over 7b in this benchmark. |

**Default for studyctl D2: `ollama` with model `qwen2.5:7b`** — matches the autonomous-by-default design principle. Users who want higher-quality cards flip one config line to `backend: bedrock`. Both paths produce schema-validated JSON into the same filesystem layout.

## Known qualitative issues

- **Quiz option count** — qwen2.5 models produce 3 or 4 options inconsistently. Sonnet produces 4 consistently. Prompt says "4 options"; schema accepts ≥ 2. Future iteration could tighten this via more aggressive retry on count mismatch.
- **qwen2.5:14b factual drift** — one false-positive distractor marked correct in the Section 2 quiz. Not seen in 7b or Sonnet. Possibly noise (N=1), but still a credibility hit.
- **Sonnet verbosity** — some backs are ~400 words with code + rationale + "when to use this". Great for study; might be too much for quick review. Configurable via prompt if ever needed.

## Cost note

Bedrock Sonnet 4.6 used ~35K input tokens (prompt + source markdown × 4 calls) and ~8K output tokens for the full 3-note run. At Sonnet's rates that's roughly $0.11–$0.30 depending on exact tokenisation. Ollama is free (hardware amortised). For a full course of 16 chapters × 4 decks = 64 generations at Sonnet cost, estimate $2–$6 per course.
