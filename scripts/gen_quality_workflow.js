export const meta = {
  name: 'studyloop-gen-quality',
  description: 'Autonomous generate+judge loop across 3 LLM providers, then Playwright-validate the panels and write a report',
  phases: [
    { title: 'Generate+Judge', detail: 'per-provider judge-loop-until-approved (max 4 rounds), Opus-4.8 judge' },
    { title: 'Validate', detail: 'Playwright walks Quiz + Flashcard panels for each generated deck' },
    { title: 'Report', detail: 'synthesise per-provider rounds, verdicts, Playwright results' },
  ],
}

// ---------------------------------------------------------------------------
// Config — providers proven live during STEP-2 recon (see handoff).
// IMPORTANT model-id correction: the spec named the Bedrock model
// `us.anthropic.claude-sonnet-4-6-20251101-v1:0`, but that raw foundation-model
// id is NOT directly invocable in this account/region (ValidationException:
// "provided model identifier is invalid"). The cross-region INFERENCE-PROFILE
// id `us.anthropic.claude-sonnet-4-6` works and was proven (5+5, 0 errors).
// ---------------------------------------------------------------------------
const REPO = '/path/to/StudyLoop' // set to your checkout before running
const PUBLISHER = 'CodeWithMosh'
const SOURCE_COURSE = 'Complete_SQL_Mastery'
const SECTIONS = 'study-notes/getting-started-0025,study-notes/data-types-0035'
const TARGET_COUNT = 5
const MAX_QUALITY_ROUNDS = 4
const MAX_GEN_ERROR_RETRIES = 2
const BUDGET_FLOOR = 100_000
const SERVER = 'http://127.0.0.1:8567'

const PROVIDERS = [
  {
    key: 'bedrock',
    label: 'AWS Bedrock — Claude Sonnet 4.6',
    backend: 'bedrock',
    provider: '',
    model: 'us.anthropic.claude-sonnet-4-6',
    outputCourse: 'Complete_SQL_Mastery__bedrock',
  },
  {
    key: 'minimax',
    label: 'MiniMax M2.7',
    backend: 'anthropic_compat',
    provider: 'minimax',
    model: 'MiniMax-M2.7',
    outputCourse: 'Complete_SQL_Mastery__minimax',
  },
  {
    key: 'ollama',
    label: 'Ollama — gemma4:latest',
    backend: 'ollama',
    provider: '',
    model: 'gemma4:latest',
    outputCourse: 'Complete_SQL_Mastery__ollama',
  },
]

// Schemas -------------------------------------------------------------------
const GEN_SCHEMA = {
  type: 'object',
  additionalProperties: true,
  required: ['written', 'failed', 'job_error', 'output_course', 'card_counts'],
  properties: {
    written: { type: 'integer' },
    failed: { type: 'integer' },
    job_error: { type: ['string', 'null'] },
    output_course: { type: 'string' },
    publisher: { type: 'string' },
    card_counts: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: true,
        properties: {
          path: { type: 'string' },
          kind: { type: 'string' },
          count: { type: 'integer' },
        },
      },
    },
    outcomes: { type: 'array', items: { type: 'object', additionalProperties: true } },
  },
}

const VERDICT_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: ['approved', 'flashcard_score', 'quiz_score', 'reasons'],
  properties: {
    approved: { type: 'boolean' },
    flashcard_score: { type: 'integer', description: '1-10 content-quality score' },
    quiz_score: { type: 'integer', description: '1-10 content-quality score' },
    reasons: {
      type: 'string',
      description: 'If approved: a one-line justification. If rejected: SPECIFIC, actionable improvements to feed back into the next generation prompt.',
    },
    strengths: { type: 'string' },
    weaknesses: { type: 'string' },
  },
}

const VALIDATE_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: ['provider_key', 'api_ok', 'rendered', 'flashcard_count', 'quiz_count', 'notes'],
  properties: {
    provider_key: { type: 'string' },
    api_ok: { type: 'boolean' },
    rendered: { type: 'boolean' },
    flashcard_count: { type: 'integer' },
    quiz_count: { type: 'integer' },
    sample_flashcard_front: { type: 'string' },
    sample_quiz_question: { type: 'string' },
    notes: { type: 'string' },
  },
}

// Helpers -------------------------------------------------------------------
function genCommand(p, round, guidanceFile) {
  // guidanceFile is a path whose contents (if any) are passed as --guidance.
  // We read it inline via $(cat ...) so judge feedback from the prior round
  // flows into the prompt. Empty file => empty guidance => first-round prompt.
  const guidanceArg = guidanceFile
    ? `--guidance "$(cat ${guidanceFile} 2>/dev/null)"`
    : '--guidance ""'
  return [
    `cd ${REPO} &&`,
    `uv run --project packages/studyloop python scripts/gen_for_workflow.py`,
    `--backend ${p.backend} --provider "${p.provider}" --model "${p.model}"`,
    `--publisher ${PUBLISHER} --course ${SOURCE_COURSE}`,
    `--output-course "${p.outputCourse}"`,
    `--sections "${SECTIONS}"`,
    `--target-count ${TARGET_COUNT} ${guidanceArg} --tag ${p.key}-r${round}`,
  ].join(' ')
}

// Per-provider judge loop ----------------------------------------------------
async function runProvider(p) {
  const guidanceFile = `/tmp/sl-guidance-${p.key}.txt`
  let qualityRound = 0
  let genErrorRetries = 0
  let lastVerdict = null
  let lastGen = null
  const history = []

  // Seed the guidance file empty (first round = base prompt).
  await agent(
    `Run EXACTLY this Bash command to reset the guidance file, then reply "ok": ` +
      `printf '' > ${guidanceFile}`,
    { label: `${p.key}:init`, phase: 'Generate+Judge' },
  )

  while (qualityRound < MAX_QUALITY_ROUNDS && budget.remaining() > BUDGET_FLOOR) {
    const round = qualityRound + 1

    // --- GENERATE (deterministic Python via a mechanical agent) ---
    const cmd = genCommand(p, round, guidanceFile)
    const gen = await agent(
      `You are a command runner. Run EXACTLY this command with the Bash tool, ` +
        `verbatim. CRITICAL: pass timeout=540000 to the Bash tool (generation is ` +
        `slow — up to 8 minutes for the local model). Wait for it to finish:\n\n` +
        `${cmd}\n\n` +
        `It prints one line beginning "WF_RESULT_JSON:". Parse the JSON object ` +
        `after that prefix and return it as your structured output. Do not modify ` +
        `the command, do not add flags, do not interpret the results — just run ` +
        `and return the parsed JSON. If the command produces no WF_RESULT_JSON line ` +
        `(e.g. it crashed), return an object with written=0, failed=1, ` +
        `job_error set to the stderr tail, output_course as in the command, and ` +
        `card_counts as an empty array.`,
      { label: `${p.key}:gen:r${round}`, phase: 'Generate+Judge', schema: GEN_SCHEMA },
    )
    lastGen = gen

    if (!gen || gen.job_error || gen.failed > 0) {
      // Generation ERROR (not a quality reject): retry up to MAX_GEN_ERROR_RETRIES.
      genErrorRetries++
      const errMsg = gen ? (gen.job_error || `${gen.failed} task(s) failed`) : 'agent returned null'
      history.push({ round, kind: 'gen_error', detail: errMsg, retry: genErrorRetries })
      log(`[${p.key}] generation error (retry ${genErrorRetries}/${MAX_GEN_ERROR_RETRIES}): ${errMsg}`)
      if (genErrorRetries > MAX_GEN_ERROR_RETRIES) {
        return {
          provider: p.key, label: p.label, status: 'FAILED',
          reason: `generation errored ${genErrorRetries}x: ${errMsg}`,
          rounds: qualityRound, genErrorRetries, history, lastGen,
          outputCourse: p.outputCourse,
        }
      }
      continue // retry generation without consuming a quality round
    }

    // --- JUDGE (Opus 4.8 reads the actual deck files) ---
    const paths = (gen.card_counts || []).map((c) => c.path)
    const verdict = await agent(
      `You are a strict educational-content quality judge. Read these generated ` +
        `study-deck JSON files (use the Read tool on each absolute path):\n` +
        paths.map((p2) => `- ${p2}`).join('\n') +
        `\n\nThey were generated from CodeWithMosh "Complete SQL Mastery" lesson ` +
        `notes by the provider "${p.label}". There are flashcard decks ` +
        `(front/back) and quiz decks (question/answerOptions with one isCorrect).\n\n` +
        `Schema-validity is the FLOOR, not the bar — they already parsed. Judge ` +
        `the actual CONTENT quality for a senior engineer learning SQL:\n` +
        `- Flashcards: do they test real understanding (why/when, trade-offs), ` +
        `are answers self-contained and correct, no trivia, no near-duplicates?\n` +
        `- Quizzes: is exactly one option correct, are distractors plausible (not ` +
        `throwaway), are rationales educational, is the SQL accurate?\n` +
        `- Each deck should have about ${TARGET_COUNT} items.\n\n` +
        `Score flashcards and quizzes 1-10. APPROVE only if BOTH are >= 7 and the ` +
        `content is genuinely useful and accurate. If you reject, "reasons" MUST be ` +
        `specific, actionable instructions that will be fed verbatim into the next ` +
        `generation prompt (e.g. "Quiz distractors for JOIN questions are obviously ` +
        `wrong — make them reflect common JOIN mistakes like confusing INNER vs LEFT").`,
      { label: `${p.key}:judge:r${round}`, phase: 'Generate+Judge', schema: VERDICT_SCHEMA, model: 'opus' },
    )
    lastVerdict = verdict
    history.push({
      round, kind: 'judge', approved: verdict?.approved,
      flashcard_score: verdict?.flashcard_score, quiz_score: verdict?.quiz_score,
      reasons: verdict?.reasons,
    })
    qualityRound++

    if (verdict && verdict.approved) {
      return {
        provider: p.key, label: p.label, status: 'APPROVED',
        rounds: qualityRound, genErrorRetries, verdict, history,
        outputCourse: p.outputCourse, cardCounts: gen.card_counts,
      }
    }

    // Feed the judge's reasons into the next round's prompt via the guidance file.
    const reasons = (verdict && verdict.reasons) || 'Improve overall depth, accuracy, and distractor quality.'
    await agent(
      `Run EXACTLY this Bash command to write the reviewer feedback to the guidance ` +
        `file, then reply "ok". Use a heredoc so quoting is safe:\n\n` +
        `cat > ${guidanceFile} <<'SLEOF'\n${reasons}\nSLEOF`,
      { label: `${p.key}:feedback:r${round}`, phase: 'Generate+Judge' },
    )
    log(`[${p.key}] round ${round} rejected (fc=${verdict?.flashcard_score} quiz=${verdict?.quiz_score}); regenerating with feedback`)
  }

  // Hit the ceiling (or budget) without approval.
  const reason = budget.remaining() <= BUDGET_FLOOR
    ? `budget floor reached after ${qualityRound} round(s)`
    : `not approved after ${MAX_QUALITY_ROUNDS} rounds`
  return {
    provider: p.key, label: p.label, status: 'FAILED',
    reason, rounds: qualityRound, genErrorRetries, lastVerdict, history,
    outputCourse: p.outputCourse, cardCounts: lastGen ? lastGen.card_counts : [],
  }
}

// === Phase 1: Generate + Judge (providers run independently) ===============
phase('Generate+Judge')
log(`Starting gen+judge for ${PROVIDERS.length} providers (max ${MAX_QUALITY_ROUNDS} rounds each)`)
// parallel() so one slow/stuck provider never blocks the others; each thunk
// runs its own full judge-loop and resolves to a verdict (or null on throw).
const genResults = (
  await parallel(PROVIDERS.map((p) => () => runProvider(p)))
).map((r, i) => r || {
  provider: PROVIDERS[i].key, label: PROVIDERS[i].label,
  status: 'FAILED', reason: 'provider thunk threw / returned null',
  rounds: 0, history: [], outputCourse: PROVIDERS[i].outputCourse,
})

// === Phase 2: Validate via Playwright + API ================================
phase('Validate')
const validateResults = await parallel(
  PROVIDERS.map((p) => () => {
    const r = genResults.find((g) => g.provider === p.key)
    // Only validate providers that produced decks (APPROVED or FAILED-on-quality
    // still wrote files; FAILED-on-gen-error may have none).
    return agent(
      `Validate that the StudyLoop Quiz and Flashcard panels render the decks for ` +
        `course "${p.outputCourse}". The web server is already running at ${SERVER}.\n\n` +
        `Step 1 (API assertion, hard): run with Bash:\n` +
        `  curl -s "${SERVER}/api/courses"\n` +
        `Confirm an entry with name "${p.outputCourse}" exists and note its ` +
        `flashcard_count and quiz_count.\n` +
        `Then run:\n` +
        `  curl -s "${SERVER}/api/cards/${p.outputCourse}?mode=flashcards"\n` +
        `  curl -s "${SERVER}/api/cards/${p.outputCourse}?mode=quiz"\n` +
        `Count the items in each array and capture one sample front + one sample question.\n\n` +
        `Step 2 (render check): use the Playwright MCP browser tools to navigate to ` +
        `${SERVER}/#flashcards, snapshot the page, and confirm the course ` +
        `"${p.outputCourse}" appears in the course list with its flashcard/quiz counts. ` +
        `If Playwright tools are unavailable, set rendered=false and say so in notes — ` +
        `the API assertion is the authoritative one.\n\n` +
        `Return the structured result. api_ok=true only if the course is in ` +
        `/api/courses AND both /api/cards calls returned non-empty arrays.`,
      { label: `validate:${p.key}`, phase: 'Validate', schema: VALIDATE_SCHEMA },
    ).then((v) => v || {
      provider_key: p.key, api_ok: false, rendered: false,
      flashcard_count: 0, quiz_count: 0, notes: 'validate agent returned null',
    })
  }),
)

// === Phase 3: Report =======================================================
phase('Report')
const reportPayload = JSON.stringify({ genResults, validateResults }, null, 2)
await agent(
  `Write a markdown report to ${REPO}/reviews/gen-quality/2026-06-01-gen-quality-workflow-report.md ` +
    `summarising this autonomous generation+quality run. Use the Write tool.\n\n` +
    `Here is the structured data (per-provider judge results and Playwright/API ` +
    `validation):\n\n\`\`\`json\n${reportPayload}\n\`\`\`\n\n` +
    `The report MUST include:\n` +
    `1. A summary table: provider | status (APPROVED/FAILED) | quality rounds | ` +
    `gen-error retries | flashcard score | quiz score | API ok | rendered.\n` +
    `2. For each provider: the judge's final reasons, strengths, weaknesses, and ` +
    `the round-by-round history.\n` +
    `3. Any provider that hit the ceiling (4 rounds) or budget floor WITHOUT ` +
    `approval — call these out prominently as needing attention.\n` +
    `4. Playwright/API validation results per provider (counts + sample content).\n` +
    `5. A short "what needs human decision" section.\n` +
    `Be precise and factual; do not invent data not present in the JSON. ` +
    `Reply with the absolute path you wrote.`,
  { label: 'report:write', phase: 'Report' },
)

// Return the structured data so the orchestrator (STEP 3) can act on it.
const approved = genResults.filter((r) => r.status === 'APPROVED').map((r) => r.provider)
const failed = genResults.filter((r) => r.status !== 'APPROVED').map((r) => r.provider)
return {
  approved,
  failed,
  allApproved: failed.length === 0,
  genResults,
  validateResults,
  reportPath: `${REPO}/reviews/gen-quality/2026-06-01-gen-quality-workflow-report.md`,
}
