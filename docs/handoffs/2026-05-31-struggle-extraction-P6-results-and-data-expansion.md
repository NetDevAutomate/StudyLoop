# Struggle-Extraction Pipeline — P6 Results & the Data-Expansion Path

**Created**: 2026-05-31 (afternoon) · **Supersedes the P4–P7 portion of** `2026-05-31-struggle-extraction-pipeline-handoff.md` · **Branch**: `feat/struggle-extraction-pipeline` (10 commits ahead of `main`, tree clean)

---

## TL;DR

P0–P6 are **built, tested, committed**. The pipeline, the hill-climber, the eval, and the safety rails all work end-to-end. The extractor improved ~3.5× on unseen data (held-out F1 0.095 → 0.333). **But it does NOT pass the quality gate** (held-out precision/recall 0.33/0.33 vs required 0.70/0.60), and the root cause is **data volume, not the prompt**: 5 training sessions is too few to learn struggle-detection that generalises. The loop overfits (train 0.667 → held-out 0.333). **Next real step is labelling ~15–20 more golden sessions**, then re-running P6. Do NOT tune the prompt further — it just overfits harder. P7 (production backfill) is blocked on clearing the gate.

---

## What is DONE (committed on the feature branch)

| Phase | Commit | What | Gate |
|---|---|---|---|
| P0 | `71e1cc4` | log_topic MCP tool + CodexExporter | 37/37 |
| P1 | `44784d5` | ExtractorResult interface + stub + pipeline + CLI | 11/11 |
| P2 | `c6968e8` | golden labels (8+5) + 5/3 split + topic_vocab | validation passes |
| P3 | `61126df` | Playwright e2e dropdown | 7/7 |
| P5 | `868d9e9` | extract-struggles wired into 4 harness session-ends | 4/4 |
| P4 | `68cfab6`,`fe5c03e`,`53238ae` | LLM extractor (Bedrock Converse) + eval harness + real-data live tests + per-session error isolation | 8 mocked + 4 live |
| P6 | `a564a22`,`573a0bb` | hill-climber + fuzzy scorer + recall floor | infra proven |

All non-e2e tests green (29 extractor-specific; 2279 full-suite with 4 pre-existing environmental failures unrelated to this work).

## Test layering (real-vs-mock discipline)
- **Mocks** (`test_extractor_llm.py`, 8): only for paths a real model can't be forced to emit (invalid enum, model-skips-tool). Always-on.
- **Real-data live tests** (`test_extractor_llm_live.py`, 4, marker `live_provider`): real Bedrock + real sessions. Opt in: `uv run --with boto3 pytest -m live_provider`. Skips cleanly without creds. These would have caught the nova-lite crash that mocks passed.
- **Fuzzy-matcher units** (`test_eval_fuzzy_match.py`, 10): pure-Python, lock in the scorer fix.

---

## The two key findings (read before touching anything)

### Finding 1 — the eval was measuring the wrong thing (FIXED)
First overnight run Goodharted: F1 rose only by SUPPRESSING output (precision 0.083→1.0, recall pinned at 0.111 every iteration). Root cause was **exact (topic, concept) string matching** in `score_session` — `graphrag/embedding` never matched the human label `graphrag/lightrag-embedding-pipeline`. The extractor was finding real struggles; the scorer couldn't see them.
**Fix (`573a0bb`)**: fuzzy concept matching (greedy bipartite, topic must agree, concept token Jaccard≥0.34 OR containment≥0.5, stopwords stripped) + a **recall floor** in keep/discard (reject any candidate dropping recall >0.02 below best, even if F1 rose). Same prompt re-baseline jumped recall 0.111→0.444 purely from the measurement fix.

### Finding 2 — the golden set is too small to generalise (NOT fixed — this is the next step)
After the fix, the loop climbed honestly to **train F1 0.667** (precision 0.583, recall 0.778). But on the **untouched held-out split** the same candidate scored **F1 0.333** (precision 0.333, recall 0.333). A 0.33 train→held-out gap is overfitting — the handoff's own tripwire was 0.10. With only 5 training sessions the loop memorises their phrasing; it can't learn transferable struggle-detection. Held-out `kiro_9c4b5d74` missed all 3 labelled struggles (tp=0, fn=3).
**fp_neg=0 held on every split and every iteration** — the false-positive gate is robust; pre_filter + the prompt never hallucinate struggles onto build sessions.

---

## The NEXT STEP — expand the golden set (the actual unblock)

The bottleneck is labelled data. To give the loop signal that generalises:

1. **Label ~15–20 more kiro_cli study sessions** (target ~25 total, split ~18 train / ~7 held-out — the handoff noted held-out should reach ≥6 for a stable F1 estimate).
   - Find candidates: `sqlite3 ~/.config/studyloop/sessions.db "SELECT session_id, COUNT(*) n FROM messages WHERE role='user' AND length(content)>100 AND session_id LIKE 'kiro_%' GROUP BY session_id ORDER BY n DESC LIMIT 40"`
   - A prestaging subagent can draft candidate labels with verbatim quotes (read-only) exactly as done for the first 8 — see the first handoff's P2-prestage. Human reviews/accepts (labels must NOT be LLM-authoritative — circularity).
   - Append to `packages/studyloop/tests/fixtures/eval_golden.json` (same schema) and rebuild `eval_split.json`.
2. **Re-run P6**: `AWS_PROFILE=arraafat+prod-taylaand uv run --with boto3 python -m studyloop.extractors.improve_extractor --budget-usd 2.0 --max-iterations 20`
3. **Check held-out** (the honest gate) with the snippet in "How to re-check the gate" below. Only ship to P7 when held-out precision≥0.70 AND recall≥0.60 AND fp_neg==0.

### Cheaper iteration once data is bigger
Model comparison was deferred (user: sonnet-first to a working solution). When revisiting: nova-pro works via Converse forced-tool and is ~4× cheaper than sonnet (nova-lite CRASHES on real transcripts — `ModelErrorException: invalid sequence in ToolUse` — do not use it as extractor; the eval now survives it via per-session error isolation but it scores zero). **Before any cost-driven model choice, fix the model-blind cost meter**: `eval_runner._PRICE_IN/_PRICE_OUT` are hardcoded sonnet rates — make them a per-model price table. (Harmless while sonnet-only.)

---

## How to re-check the gate (held-out eval of the current candidate)

```bash
AWS_PROFILE=arraafat+prod-taylaand uv run --with boto3 python -c "
import importlib.util, json
from pathlib import Path
from studyloop.extractors import eval_runner as ev
import boto3
spec = importlib.util.spec_from_file_location('c','packages/studyloop/src/studyloop/extractors/extractor_candidate.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
client = boto3.Session(profile_name='arraafat+prod-taylaand').client('bedrock-runtime','us-east-1')
metrics,_,_ = ev.run_eval('held_out', db_path=Path.home()/'.config/studyloop/sessions.db', prompt_template=m.EXTRACTOR_PROMPT, client=client)
print(json.dumps(metrics))
"
```

## P7 (blocked until the gate passes)
Once held-out clears the bar: promote `extractor_candidate.py`'s prompt into `llm.py` as the default (or load it), then:
`studyloop extract-struggles --full --dry-run --limit 10` → human eyeballs output → `--full --commit` backfills `study_progress`. This is the ONLY step that writes the live DB; it needs human sign-off. The dropdown reads via the existing `/api/history/struggling-topics` route — no UI change.

---

## Config / environment facts (corrected from the original handoff)
- **Transport**: AWS Bedrock **Converse API + forced tool-use** (mirrors `content/generators/bedrock.py`). NOT LiteLLM/httpx (original handoff was wrong).
- **Model**: `us.anthropic.claude-sonnet-4-6`, region `us-east-1`, profile **`arraafat+prod-taylaand`** (the bedrock-prod/bedrock-local profiles in `bedrock.py` defaults are EXPIRED on this machine).
- **CLI**: click + LazyGroup (NOT typer). Tests use `click.testing.CliRunner`.
- **`source`** lives on the `sessions` table, not `messages`. pre_filter takes it as a param.
- **boto3** is behind the `[bedrock]` extra — eval/live runs use `uv run --with boto3`.
- **Generated artifacts (gitignored)**: `extractor_candidate.py`, `results.tsv`.

## Spend this session
~$4.85 total: first (Goodharted) loop $2.02 + scorer re-baselines ~$0.30 + second loop $2.01 + held-out $0.07 + probes/baselines ~$0.45. Still under the original $5 envelope. The first $2 bought the Goodhart diagnosis that made the second run worthwhile.

## results.tsv (local, gitignored) — key rows
- baseline exact-match: F1 0.083, recall 0.111 (the Goodhart floor)
- baseline fuzzy: F1 0.348, recall 0.444 (measurement fix, same prompt)
- best train candidate: F1 0.667, prec 0.583, recall 0.778
- **held-out-final: F1 0.333, prec 0.333, recall 0.333, fp_neg 0 ← the honest number; gate NOT met**
