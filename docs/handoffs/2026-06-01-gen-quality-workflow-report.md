# Generation + Quality Workflow Run — 2026-06-01

**Course**: Complete SQL Mastery (CodeWithMosh)
**Sections covered**: `getting-started-0025`, `data-types-0035`
**Providers tested**: AWS Bedrock (Claude Sonnet 4.6), MiniMax M2.7, Ollama gemma4:latest

---

## Summary Table

| Provider | Status | Quality Rounds | Gen-Error Retries | Flashcard Score | Quiz Score | API OK | Rendered |
|---|---|---|---|---|---|---|---|
| AWS Bedrock — Claude Sonnet 4.6 | APPROVED | 1 | 0 | 9/10 | 9/10 | Yes | Yes |
| MiniMax M2.7 | **FAILED** | 3 (judge) + 2 gen errors = 4 total | 3 | 8/10 (last judge) | 4/10 (last judge) | Yes | Yes |
| Ollama — gemma4:latest | APPROVED | 4 | 0 | 8/10 | 7/10 | Yes | Yes |

---

## Provider Detail

### AWS Bedrock — Claude Sonnet 4.6

**Status**: APPROVED in 1 round (no retries required).

**Final verdict** (round 1):
> Both decks are accurate, non-trivial, and teach the real WHY behind each concept. Content is approved for use.

**Strengths**:
- Flashcards test genuine understanding (FK vs denormalisation trade-off, FLOAT IEEE 754 accumulation, `->` vs `->>` silent failure) rather than rote recall.
- Every answer is self-contained and correct.
- Quiz distractors are plausible — e.g. "FLOAT is slower than DECIMAL" is deliberately inverted from reality; "avoid JOINs" is the exact wrong reason engineers cite for denormalisation; "ENUM cannot be indexed" is correctly attributed to TEXT not ENUM (cross-card reinforcement).
- Rationales are educational, distinguishing mechanism from motivation. SQL examples are syntactically valid.
- The intentional-denormalisation exception card is a standout — it captures the nuance most intro courses skip.
- Getting-started deck covers both tool knowledge (Workbench execution model) and foundational principles (declarative vs procedural) without near-duplicates.

**Weaknesses**:
- The ENUM rebuild card/question does not mention that MySQL 8.0 supports `ALGORITHM=INSTANT` for appending new ENUM values at the end, avoiding a full table rebuild in many cases. This is a course-level abstraction and not a correctness error, but a senior engineer may notice the gap.
- The Workbench Execute-button flashcard is more tool-mechanics than SQL understanding — acceptable given it is a getting-started module, but the weakest card in the set.

**Round-by-round history**:

| Round | Kind | Approved | Flashcard Score | Quiz Score |
|---|---|---|---|---|
| 1 | judge | Yes | 9 | 9 |

**Output files**:
- `/Users/taylaand/Obsidian/Personal/Study/CodeWithMosh/Complete_SQL_Mastery__bedrock/flashcards/getting-started-0025-flashcards.json` (5 cards)
- `/Users/taylaand/Obsidian/Personal/Study/CodeWithMosh/Complete_SQL_Mastery__bedrock/quizzes/getting-started-0025-quiz.json` (5 questions)
- `/Users/taylaand/Obsidian/Personal/Study/CodeWithMosh/Complete_SQL_Mastery__bedrock/flashcards/data-types-0035-flashcards.json` (5 cards)
- `/Users/taylaand/Obsidian/Personal/Study/CodeWithMosh/Complete_SQL_Mastery__bedrock/quizzes/data-types-0035-quiz.json` (5 questions)

---

### MiniMax M2.7

> **ATTENTION: This provider hit the retry ceiling without achieving approval. Human decision required — see section below.**

**Status**: FAILED. Exhausted 3 gen-error retries and 3 judge rounds without approval. The final generation attempt (retry 3) produced an incomplete output — `data-types-0035-quiz.json` was never written because MiniMax returned XML-style tool-call markup instead of the expected `tool_use` block format.

**Final judge reasons** (round 3, last successful evaluation):
> Fix these specific defects before resubmitting:
> 1. Getting Started quiz Q1 (Elka/relational model): The correct answer option contains garbled non-English text ("看到她新地址") embedded in an otherwise English sentence.
> 2. Data Types quiz Q4 (JSON_SET path prefix): Marks "JSON_SET automatically normalizes bare paths by prepending $ internally" as CORRECT — this is factually wrong. MySQL's JSON_SET does NOT auto-prefix bare paths.
> 3. Data Types quiz Q1, distractor D rationale: States VARCHAR(2) and CHAR(2) store the same number of bytes — incorrect; CHAR(2) stores 2 bytes, VARCHAR(2) stores 3 bytes.

**Round-by-round history**:

| Round | Kind | Approved | Flashcard Score | Quiz Score | Detail |
|---|---|---|---|---|---|
| 1 | judge | No | 8 | 4 | Two critical defects: Q1 option text contained a question fragment not an answer; Q5 `isCorrect` flag on wrong option |
| 2 | gen_error | — | — | — | Generation failed: "1 task(s) failed" (retry 1) |
| 2 | judge | No | 8 | 6 | Three distractor errors: wrong topic in distractor C; TINYINT UNSIGNED as a 5M-row distractor; copy-paste rationale error in Q5 distractor D |
| 3 | judge | No | 8 | 4 | Garbled non-English characters in Q1 correct option; factually wrong correct answer in Q4; incorrect byte-count rationale in Q1 distractor D |
| 4 | gen_error | — | — | — | Generation failed: "1 task(s) failed" (retry 2) |
| 4 | gen_error | — | — | — | Generation failed: "1 task(s) failed" (retry 3 — ceiling reached) |

**Last generation partial output** (3 of 4 files written; 1 failed):
- `getting-started-0025-flashcards.json`: OK (12.1s)
- `getting-started-0025-quiz.json`: OK (60.1s)
- `data-types-0035-flashcards.json`: OK (36.6s)
- `data-types-0035-quiz.json`: **FAILED** — MiniMax returned XML-style `<minimax:tool_call>` markup instead of a `tool_use` block; the parser could not extract `emit_quiz_deck`.

**Root cause pattern**: MiniMax alternated between content quality failures (garbled text, incorrect `isCorrect` flags, factual errors) and tool-call format failures. The format failure (`<minimax:tool_call>` instead of JSON `tool_use`) is a protocol-level bug, not a content quality issue — it recurred on retries 2 and 3 and appears to be a reliability regression in the model's tool-use compliance.

**Output files** (incomplete — missing data-types quiz):
- `/Users/taylaand/Obsidian/Personal/Study/CodeWithMosh/Complete_SQL_Mastery__minimax/flashcards/getting-started-0025-flashcards.json` (5 cards)
- `/Users/taylaand/Obsidian/Personal/Study/CodeWithMosh/Complete_SQL_Mastery__minimax/quizzes/getting-started-0025-quiz.json` (5 questions)
- `/Users/taylaand/Obsidian/Personal/Study/CodeWithMosh/Complete_SQL_Mastery__minimax/flashcards/data-types-0035-flashcards.json` (5 cards)
- `data-types-0035-quiz.json` — **NOT WRITTEN**

**Note on API/render validation**: Despite the failed generation, the validation report shows `flashcard_count=10` and `quiz_count=10` for the minimax course. This is inconsistent with the generation record (only 3 of 4 files written). The validation agent may have encountered stale data from a prior run or the API is counting from a partially-consistent state. This discrepancy requires investigation.

---

### Ollama — gemma4:latest

**Status**: APPROVED in 4 rounds (no gen-error retries). This provider required the maximum number of judge iterations but ultimately met the approval bar.

**Final verdict** (round 4):
> Content is genuinely useful and accurate. Approve with these improvements for the next generation pass.

**Strengths**:
- Data Types 0035 flashcards are outstanding — all five test design reasoning (ENUM rebuild cost, IEEE 754 vs DECIMAL, Y2K38 TIMESTAMP limit, JSON sparse-table avoidance, BIGINT range) with correct SQL examples.
- Getting Started 0025 flashcards for FK/SSOT, junction tables, and Views are well-framed with concrete scenarios.
- Quiz distractors throughout are plausible real-world anti-patterns (comma-separated columns, nullable column explosion, SET type, VARCHAR PKs) rather than throwaway wrong answers.
- Rationales are educational and explain the why, not just the what.
- Data Types 0035 quiz Q3 (ENUM-to-lookup-table migration) is particularly strong — all four options are patterns engineers actually propose.

**Weaknesses (final round — deferred improvements, not blockers)**:
- Getting Started 0025 has one trivia flashcard (loopback IP / default port) that adds no SQL design value. Replacement suggested: View vs CTE trade-offs.
- Quiz Q5 tests MySQL Workbench UI mechanics rather than transferable SQL knowledge.
- Quiz Q4 distractor D has a logically unsound rationale — dismisses a trigger as a design flaw when a trigger is actually a valid implementation mechanism.
- Data Types 0035 quiz Q2 distractor B risks misleading learners: DECIMAL(19,4) is marked wrong for being "arbitrary" but it is the dominant industry convention for financial data; the rationale needs nuance.

**Round-by-round history**:

| Round | Kind | Approved | Flashcard Score | Quiz Score | Key issues |
|---|---|---|---|---|---|
| 1 | judge | No | 8 | 6 | Duplicate distractors in data-types Q5; imprecise correct answer in getting-started Q3; throwaway distractors; UI-trivia flashcard |
| 2 | judge | No | 7 | 6 | Two quiz questions test GUI/CLI knowledge not SQL; Q3 "correct" answer contestable; getting-started flashcard 4 is Workbench trivia |
| 3 | judge | No | 9 | 6 | Data Types Q5 JSON_EXTRACT rationale factually wrong in MySQL 8; Getting Started Q4 tests Workbench UI mechanics |
| 4 | judge | Yes | 8 | 7 | Approved with deferred improvements noted above |

**Output files**:
- `/Users/taylaand/Obsidian/Personal/Study/CodeWithMosh/Complete_SQL_Mastery__ollama/flashcards/getting-started-0025-flashcards.json` (5 cards)
- `/Users/taylaand/Obsidian/Personal/Study/CodeWithMosh/Complete_SQL_Mastery__ollama/quizzes/getting-started-0025-quiz.json` (5 questions)
- `/Users/taylaand/Obsidian/Personal/Study/CodeWithMosh/Complete_SQL_Mastery__ollama/flashcards/data-types-0035-flashcards.json` (5 cards)
- `/Users/taylaand/Obsidian/Personal/Study/CodeWithMosh/Complete_SQL_Mastery__ollama/quizzes/data-types-0035-quiz.json` (5 questions)

---

## Playwright / API Validation

### Complete_SQL_Mastery__bedrock

- **API**: `/api/courses` confirms course present with `flashcard_count=10`, `quiz_count=10`. Both `/api/cards` calls returned 10 items each.
- **Rendered**: Playwright navigated to `http://127.0.0.1:8567/#flashcards`; course card visible showing "10 flashcards 10 quiz questions" with Flashcards/Quiz buttons.
- **Console errors**: 5 non-blocking pre-existing errors; no new regressions.
- **Sample flashcard front**: "You need to store product prices in MySQL. A colleague suggests using FLOAT for efficiency. Why is this wrong, and what should you use instead?"
- **Sample quiz question**: "A financial application stores product prices. A developer defines the column as `price FLOAT`. What is the most serious consequence of this choice in production?"

### Complete_SQL_Mastery__minimax

- **API**: `/api/courses` reports `flashcard_count=10`, `quiz_count=10`. Both `/api/cards` calls returned 10 items each.
- **Rendered**: Playwright confirmed course card present with "10 flashcards 10 quiz questions".
- **Discrepancy**: The generation run recorded only 3 of 4 files successfully written (data-types quiz failed). The API and render counts of 10/10 are inconsistent with this. Either the API is serving stale data from a prior successful run, or there is a partial-write scenario that needs investigation.
- **Sample flashcard front**: "A colleague argues that MySQL's `JSON_SET` is smart enough to normalize bare paths like `'weight'` automatically. They write `JSON_SET(properties, 'weight', 20)` and expect it to work. Are they right? If not, what is the correct syntax?"
- **Sample quiz question**: "You need to store two-character US state abbreviations (always exactly 2 characters). Which storage comparison is correct?"

### Complete_SQL_Mastery__ollama

- **API**: `/api/courses` confirms course present with `flashcard_count=10`, `quiz_count=10`. Both `/api/cards` calls returned 10 items each.
- **Rendered**: Playwright confirmed course card renders at `#flashcards` with "10 flashcards 10 quiz questions" and Flashcards/Quiz buttons visible.
- **Sample flashcard front**: "When designing a schema, why is using a lookup table pattern (e.g., for 'size') superior to using an ENUM type?"
- **Sample quiz question**: "When designing a product catalog where products have highly variable attributes (e.g., a TV has a resolution, a shirt has a size), which pattern is best suited to store these optional, schema-per-row attributes while maintaining relational integrity?"

---

## What Needs Human Decision

### 1. MiniMax — FAILED provider: decide whether to retry or deprecate

MiniMax hit the 3-gen-error-retry ceiling and produced unapproved content across 3 judge rounds. The failures fall into two distinct categories:

- **Content quality**: Garbled non-English characters in output, incorrect `isCorrect` flags, factual SQL errors. These suggest the model does not reliably follow the judge's remediation instructions across multiple rounds.
- **Protocol failure**: MiniMax returned `<minimax:tool_call>` XML-style markup instead of the expected JSON `tool_use` block. This is a tool-call compliance bug that prevented the `data-types-0035-quiz.json` from being written at all on the final two retries.

**Decision needed**: Should MiniMax be retried with a different prompt strategy (e.g., stricter tool-call formatting instructions), or should it be removed from the provider rotation until the XML markup regression is investigated and fixed?

### 2. MiniMax API/render count discrepancy

The validation report shows `flashcard_count=10` and `quiz_count=10` for the minimax course, but the generation run only wrote 3 of 4 files. Someone needs to confirm whether the API is serving data from a previous (stale) run or whether there is genuinely a complete set of cards for this course that pre-dates this run. If the quiz counts are stale, the minimax course data should be treated as invalid for use.

### 3. Ollama — deferred improvements (approved but non-trivial feedback)

The Ollama content was approved but with four documented improvement items that the judge explicitly flagged for the "next generation pass". These are not blockers, but if content quality is a priority they should be addressed before the course is distributed to learners:

- Replace connectivity-trivia flashcard (127.0.0.1 / port 3306) with a View vs CTE trade-offs card.
- Fix quiz Q4 distractor D rationale (trigger dismissal is logically unsound).
- Replace quiz Q5 (Workbench highlight-to-execute) with transferable SQL knowledge question.
- Nuance the DECIMAL(19,4) distractor rationale in data-types quiz Q2.

**Decision needed**: Accept as-is for learner use, or queue a targeted regeneration pass for these four items?

### 4. Bedrock ENUM/ALGORITHM=INSTANT gap

The judge noted that the ENUM rebuild card does not mention `ALGORITHM=INSTANT` for MySQL 8.0 (appending ENUM values without a full table rebuild). This is a course-level abstraction and not a correctness error, but it is a meaningful omission for a senior engineer audience.

**Decision needed**: Accept the omission as appropriate course-level simplification, or add a follow-up card covering the MySQL 8.0 exception?

---

## STEP-3 ADDENDUM (post-workflow targeted fixes) — 2026-06-01

After the workflow completed, I root-caused MiniMax's FAILED status and fixed the
**code** defects it exposed, then re-ran MiniMax. Summary of what changed:

### MiniMax code bugs found & fixed (proven live)

1. **error 2013 → tool_result correction** (commit `2c26c2a`, fixed earlier in the
   night before the workflow): the schema-correction retry appended a plain-text
   user turn after an assistant `tool_use`; MiniMax's strict `/anthropic` shim
   rejects that. Now emits a protocol-valid `tool_result`.
2. **inline-XML tool calls** (commit `c4b2030`): MiniMax M2.7 intermittently emits
   the forced tool call as `<minimax:tool_call><invoke …><parameter …>` text
   markup instead of a native `tool_use` block (~half the time). Added
   `_parse_inline_tool_call` fallback **plus** a transient-retry in
   `call_with_correction` (a single bad emission no longer hard-fails). This is the
   exact protocol failure the workflow flagged as needing investigation.
3. **`--max-retries` knob** (commit `209d0e4`): flaky providers can be given a
   larger retry budget so consecutive bad emissions don't exhaust it.

**Proof**: MiniMax data-types quiz (previously failed reliably) now generates
4/4 clean consecutive runs (0 errors); a full clean two-section run wrote 4/4
files (5+5+5+5 = 20 cards).

### MiniMax content quality — STILL below bar (model limitation, NOT code)

After clean generation, an Opus-4.8 judge re-assessed the fresh MiniMax decks:

> **VERDICT: REJECTED — flashcard 9/10, quiz 6/10.** Getting-Started quiz Q4 has
> `isCorrect` on the wrong option for the scenario described (Workbench
> execution-scope confusion); the Data-Types quiz has two rationale-to-option
> copy-paste mismatches. Flashcards are excellent; quizzes carry subtle
> correctness defects.

This matches the workflow's 3 in-loop rejections. **Conclusion: MiniMax M2.7's
generation pipeline is now fully working (zero errors), but its quiz content
quality is a model limitation the strict judge keeps catching.** Its flashcards
(score 9) are genuinely strong.

### Final provider scorecard

| Provider | Generates cleanly? | Judge verdict | Notes |
|---|---|---|---|
| **Bedrock Sonnet 4.6** | ✅ | **APPROVED 9/9** (round 1) | Best — accurate, deep, plausible distractors |
| **Ollama gemma4** | ✅ | **APPROVED 8/7** (round 4) | Needed 4 judge rounds; approved with deferred nits |
| **MiniMax M2.7** | ✅ (after code fixes) | **REJECTED 9/6** | Flashcards strong; quiz quality is a model limit, not a bug |

### Decision for the user (MiniMax)

The code is fixed and committed — MiniMax no longer errors. The open question is
purely product: **keep MiniMax (it produces excellent flashcards) and accept
weaker quizzes, restrict MiniMax to flashcard-only generation, or drop it from
the rotation for quizzes.** No further code work is required for MiniMax to
*function*; the gap is content quality intrinsic to the model.
