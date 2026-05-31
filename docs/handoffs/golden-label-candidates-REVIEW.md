# Golden Label Candidates — HUMAN REVIEW REQUIRED

> **WARNING: DRAFT LABELS PRODUCED BY AN LLM — DO NOT USE AS GOLDEN TRUTH WITHOUT REVIEW**
>
> These entries were drafted by an automated pipeline (drafter LLM + adversarial-check LLM) on
> branch `feat/struggle-extraction-pipeline`. They have NOT been accepted into the eval golden set.
>
> **Circularity risk**: An LLM must not author the golden truth it is later graded against.
> If these labels are accepted without human review, the eval gate becomes meaningless.
>
> **Acceptance steps** (human only):
> 1. Review each section below. Tick the checklist at the bottom.
> 2. For each session you accept, copy the JSON block into
>    `packages/studyloop/tests/fixtures/eval_golden.json` (maintain the existing array structure
>    and field ordering: `session_id`, `expected_topics`, `is_negative`, `notes`).
> 3. After editing `eval_golden.json`, regenerate the split file:
>    ```bash
>    uv run python -m studyloop.eval.split_golden
>    ```
>    or whatever the current rebuild command is — do NOT hand-edit
>    `packages/studyloop/tests/fixtures/eval_split.json`.
> 4. Re-run the eval suite to confirm the gate still passes at the target threshold.
>
> **Ordering**: highest-risk entries appear first (reject-and-relabel verdicts, then accept-with-edits,
> then medium-confidence accept-as-is, then clean high-confidence accepts).

---

## TIER 1 — Adversarial verdict: REJECT-AND-RELABEL (read carefully before accepting)

These sessions have a proposed label that the adversarial check recommends changing.
The JSON block below already incorporates the adversarial recommendation.
Verify the reasoning is sound before accepting.

---

### Session: kiro_1f396c36-61df-4e7f-a24a-db6c96627eee

**Adversarial verdict**: REJECT-AND-RELABEL — drafter marked negative; adversary found rich repeated struggle signal.

**Adversarial reasoning**: The transcript contains six distinct, sequential failure events on kiro-cli
agent configuration: (1) unknown `version` field in `agent.json`; (2) wrong type for `resources`
(sequence vs map); (3) wrong type for `mcpServers` (same error class); (4) MCP command field missing
(stdio transport with empty command); (5) agent not discovered (`no agent with name aws-network-agent found`)
repeated multiple times across directory structure attempts; (6) MCP tools not available inside agent
context. The session ends with the user falling back to global MCP config and requesting a written
summary — a classic consolidation move after a difficult learning session. Drafter incorrectly
classified this as ops/debugging with no learning content.

```json
{
  "session_id": "kiro_1f396c36-61df-4e7f-a24a-db6c96627eee",
  "expected_topics": [
    {
      "topic": "agentic-workflows",
      "concept": "kiro-agent-json-schema-validation",
      "confidence": "struggling"
    },
    {
      "topic": "agentic-workflows",
      "concept": "kiro-mcp-server-stdio-configuration",
      "confidence": "struggling"
    },
    {
      "topic": "agentic-workflows",
      "concept": "kiro-agent-discovery-mechanics",
      "confidence": "struggling"
    }
  ],
  "is_negative": false,
  "notes": "Kiro agent configuration session. Repeated failure across 6 distinct error categories: (1) unknown `version` field in agent.json; (2) `resources` expected map not sequence; (3) `mcpServers` expected map not sequence; (4) stdio transport with empty command field; (5) agent not discovered by kiro-cli despite multiple directory/naming attempts; (6) MCP tools unavailable inside agent context. Session ends with user falling back to global MCP config and requesting a written summary of lessons learned — consolidation signal after a difficult learning session."
}
```

**Drafter confidence**: high (in the wrong direction — drafter was confident it was negative)
**Review flags**: The three concept slugs above are the adversary's recommendation. Reviewer may prefer
to collapse to two entries (schema-validation + discovery-mechanics) if that better matches the spaced-rep
grain. Verify against the raw session transcript before accepting.

---

### Session: kiro_d7b6fb48-5410-4ee8-921f-bb682cbc51b6

**Adversarial verdict**: REJECT-AND-RELABEL — drafter marked negative; adversary found iterative-failure
struggle signal in carapace completion debugging and a secondary Ansible PATH struggle.

**Adversarial reasoning**: The carapace completion sequence produced four consecutive failure reports
from the user — "that doesn't seem to make any difference", "no change, no completion for awk or bat",
"no joy sadly", "sadly, no change" — while the assistant cycled through at least six hypotheses. This
is textbook iterative-failure struggle. The Ansible TPM task also failed a second time after an initial
fix, with the root cause (tmux via mise, not Homebrew) only surfacing in a follow-up message —
indicating the user did not know the tool's provenance and could not independently connect it to the
PATH problem. Drafter missed both signals by focusing on the confident surface-level framing.

```json
{
  "session_id": "kiro_d7b6fb48-5410-4ee8-921f-bb682cbc51b6",
  "expected_topics": [
    {
      "topic": "shell",
      "concept": "carapace-shell-completion-tooling",
      "confidence": "struggling"
    },
    {
      "topic": "shell",
      "concept": "mise-path-resolution-non-interactive-shell",
      "confidence": "learning"
    }
  ],
  "is_negative": false,
  "notes": "Dotfiles/Ansible ops session with two genuine struggle signals. (1) Carapace completion: four consecutive 'no change' failure reports while assistant cycles through six hypotheses (oh-my-zsh compinit ordering, fzf tab binding, mise shim interference, real binary path vs shim path, etc.) — textbook iterative-failure pattern. (2) Ansible tmux task: failed twice; root cause (tmux is mise-managed, not Homebrew) only surfaced in a user follow-up, indicating the user did not know the tool's provenance and could not connect it to the PATH problem independently."
}
```

**Drafter confidence**: high (in the wrong direction)
**Review flags**: The `shell` topic key is not currently in the golden set — `kiro_901e20c8` (if accepted
as negative, see below) would also have used it. Confirm topic key is acceptable or remap. Verify the
four consecutive failure messages appear verbatim in the transcript.

---

### Session: kiro_6c3eedd1-b13d-4190-9fd2-7559679b3f70

**Adversarial verdict**: REJECT-AND-RELABEL — proposed as positive (uv-run best practice); adversary
recommends negative (single one-line aside, no confusion signal, no follow-up).

**Adversarial reasoning**: The verbatim evidence is one sentence tacked onto a feature request:
"Is it best practice to call python <python file> or use uv run in a uv structured repo?" Answered
cleanly in one turn, user immediately moved to a completely unrelated topic. No confusion signal,
no follow-up, no error to recover from. Drafter's own flag correctly identified the borderline nature.
The session does not cross the threshold for an expected_topics entry.

```json
{
  "session_id": "kiro_6c3eedd1-b13d-4190-9fd2-7559679b3f70",
  "expected_topics": [],
  "is_negative": true,
  "notes": "Workshop automation repo scaffolding session (README, step scripts, Python Redshift helpers, pre-commit cleanup). One borderline best-practice question ('Is it best practice to call python <python file> or use uv run in a uv structured repo?') — one sentence, tacked onto a feature request, answered in one turn, user moved on with no follow-up. Adversarial check ruled this does not cross the struggle/acquisition threshold. Remainder of session is pure operational directives."
}
```

**Drafter confidence**: high (proposed positive); adversary ruled negative
**Review flags**: Reviewer may disagree — if the human considers a single first-pass best-practice
question sufficient for `confidence: learning`, restore `is_negative: false` with topic
`{topic: "python", concept: "uv-run-vs-python-invocation", confidence: "learning"}`. The
borderline call is close.

---

### Session: kiro_901e20c8-37b0-4178-ad4f-ce02514fd35f

**Adversarial verdict**: REJECT-AND-RELABEL — proposed as positive (shell brace expansion); adversary
recommends negative (bare question with no assistant reply captured, no follow-up evidence).

**Adversarial reasoning**: The `${VARIABLE}` vs `$VARIABLE` question appears as a one-line aside
appended to a message reporting a successful API call. There is no assistant reply captured in the
transcript, and no follow-up from the learner showing confusion or engagement. Without an assistant
reply or follow-up, there is nothing to label as a learning signal. Drafter's own flag acknowledged
this limitation. The session's other candidates (Obsidian 401 debugging = copy-paste typo, Click
ordering bug = operational, multi-agent orchestrator curiosity = one-shot question resolved cleanly)
do not meet the struggle bar.

```json
{
  "session_id": "kiro_901e20c8-37b0-4178-ad4f-ce02514fd35f",
  "expected_topics": [],
  "is_negative": true,
  "notes": "Build/config session (Obsidian REST API debugging, claude_mode shell function refactor, Python uv tool scaffolding). One borderline question ('when should ${VARIABLE} be used vs $VARIABLE?') tacked onto a success message — no assistant reply captured in transcript, no follow-up engagement. Adversarial check ruled this insufficient evidence for a learning label. Remaining signals (401 copy-paste typo, Click argument ordering, multi-agent orchestrator question) are all one-shot with clean resolution."
}
```

**Drafter confidence**: medium (proposed positive with caveats); adversary ruled negative
**Review flags**: If the human reviewer can access the full kiro session log (outside the DB) and
the assistant reply to the brace-expansion question is substantive, restore
`{topic: "shell", concept: "brace-expansion-vs-plain-variable", confidence: "learning"}`.

---

### Session: kiro_f922b25f-94a7-4ee3-8d3a-3ba7d5f19a23

**Adversarial verdict**: REJECT-AND-RELABEL — both proposed topics fail the evidence bar.

**Adversarial reasoning**:
- `bedrock-inference-profile-cli-discovery`: The learner's question ("how can I find that via the
  aws-cli?") is left unanswered in the transcript — the learner resolves their immediate need via the
  Claude Code UI `/model` command, not by learning the CLI pattern. The struggle is real but the
  learning outcome is zero.
- `jq-operator-precedence-in-select-filters`: Two identical `jq` errors back-to-back, but the learner
  never names the problem, asks about it, or shows metacognitive engagement. They reformulate the query
  structurally (adding null guard) and move on — possibly for entirely different reasons. Two silent
  errors do not constitute a struggle signal without engagement.
  The whole session is exploratory CLI trial-and-error with no resolution.

```json
{
  "session_id": "kiro_f922b25f-94a7-4ee3-8d3a-3ba7d5f19a23",
  "expected_topics": [],
  "is_negative": true,
  "notes": "Short AWS CLI exploration session: learner tries to locate Bedrock Sonnet 4.5 1M-context inference profile via CLI. Central question ('how can I find that via the aws-cli?') is left unanswered — learner resolves via Claude Code UI /model command, not by learning the CLI pattern. Two consecutive identical jq operator-precedence errors appear back-to-back but learner never names, asks about, or engages with the root cause. Session is exploratory CLI fumbling with no conceptual resolution. Adversarial check ruled both proposed topics (bedrock-inference-profile-cli-discovery, jq-operator-precedence-in-select-filters) fail the evidence bar."
}
```

**Drafter confidence**: medium (proposed positive with caveats); adversary ruled negative
**Review flags**: The jq operator-precedence gap is real and may surface again in future sessions
worth labelling. Note it for tracking even if this session is accepted as negative.

---

## TIER 2 — Adversarial verdict: ACCEPT-WITH-EDITS (minor changes incorporated)

---

### Session: kiro_93774693-5678-4f39-a8e8-d5af41512945

**Adversarial verdict**: ACCEPT-WITH-EDITS — add a second topic the drafter omitted.

**Adversarial reasoning**: The drafter decided NOT to label the ADD Framework question
("can you remind me what the Assess-Decide-Do feature does please"). The drafter assumed ADD had
been "fully described a few turns earlier," but the adversary found that the preceding turns were
entirely tool-narration with no conversational ADD explanation. ADD appeared only inside a 31KB
`CLAUDE.md` block the user pasted as context. The reminder question, asked immediately after nine
silent tool-action turns, is a genuine confusion signal, not a confirmatory check.

```json
{
  "session_id": "kiro_93774693-5678-4f39-a8e8-d5af41512945",
  "expected_topics": [
    {
      "topic": "agentic-workflows",
      "concept": "kiro-agents-vs-skills-authoring",
      "confidence": "learning"
    },
    {
      "topic": "agentic-workflows",
      "concept": "add-framework-realm-detection",
      "confidence": "learning"
    }
  ],
  "is_negative": false,
  "notes": "Config/ops session (Kiro steering files, Ansible playbook updates, MCP server scoping) with two learning signals. (1) User explicitly requests a document explaining how to write Kiro agents and skills and when to use which, stating 'so I can start writing my own' — first-pass acquisition of kiro-agents-vs-skills-authoring. (2) User asks 'can you remind me what the Assess-Decide-Do feature does please' immediately after nine silent tool-narration turns — ADD appeared only in a pasted CLAUDE.md block, not in any conversational explanation, making this a genuine confusion signal for add-framework-realm-detection."
}
```

**Drafter confidence**: medium
**Review flags**: The `kiro-agents-vs-skills-authoring` slug sits at the intersection of
`agentic-workflows` and `devops`; reviewer may prefer `topic: "devops"`. The ADD Framework label is
the adversary's addition — if reviewer believes seeing ADD in CLAUDE.md context is sufficient prior
exposure to disqualify the label, drop the second topic.

---

### Session: kiro_3cf73360-94b3-48a6-86ae-3d5cd8c1b3a9

**Adversarial verdict**: ACCEPT-WITH-EDITS — label supported but confidence should be downgraded
to reflect delegation-without-resolution pattern.

**Adversarial reasoning**: The verbatim confusion signal is genuine: "I've looked through
https://www.nushell.sh/cookbook/foreign_shell_scripts.html but can't work out what this means
for the zsh files/functions in scope" — the user attempted self-service, hit a comprehension wall,
and explicitly reported failure. However, after the assistant delivers the deep-dive document, the
user immediately pivots to an SSH question and never engages with the nushell content again. The
subsequent nushell mention is pure execution delegation ("create the nushell functions"), not
concept acquisition. The gap is real; the resolution is unconfirmed.

The existing confidence options are `"learning"` and `"struggling"` — the adversary's suggested
"stuck" or "weak-positive" tier does not exist in the current schema. Reviewer must decide:
keep `"learning"` (the gap is real even if resolution is unconfirmed) or downgrade to note the
delegation-without-resolution pattern in `notes` only.

```json
{
  "session_id": "kiro_3cf73360-94b3-48a6-86ae-3d5cd8c1b3a9",
  "expected_topics": [
    {
      "topic": "nushell",
      "concept": "zsh-to-nushell-function-migration",
      "confidence": "learning"
    }
  ],
  "is_negative": false,
  "notes": "Ansible home-lab ops/refactor session with one genuine learning signal: user explicitly reports failure to understand the nushell cookbook ('I've looked through https://www.nushell.sh/cookbook/foreign_shell_scripts.html but can't work out what this means for the zsh files/functions in scope') — self-service attempted, comprehension wall hit, assistance requested. Note: after receiving the deep-dive document, user immediately pivots to an SSH question and never engages with nushell content again; subsequent nushell mention is pure execution delegation. The gap is real but resolution is unconfirmed (delegation-without-verification pattern)."
}
```

**Drafter confidence**: medium
**Review flags**: The `nushell` topic key is not in the current golden set — this would be its first
appearance. Confirm acceptable or remap to `shell`. Adversary flagged that confidence should
potentially reflect the delegation-without-resolution pattern; no sub-`learning` tier exists in the
current schema, so the distinction lives in `notes` only.

---

## TIER 3 — Adversarial verdict: ACCEPT-AS-IS, medium drafter confidence

---

### Session: kiro_889cad39-d3b5-41ad-833f-fb7e7b2a4235

**Adversarial verdict**: ACCEPT-AS-IS

**Adversarial reasoning**: The hedge "I believe an AND takes precedence?" is verbatim in the
transcript — a real uncertainty marker. Topic, concept, and `learning` confidence are all justified.
No stored assistant turns contradict the label. `is_negative: false` is correct.

```json
{
  "session_id": "kiro_889cad39-d3b5-41ad-833f-fb7e7b2a4235",
  "expected_topics": [
    {
      "topic": "sql",
      "concept": "and-or-operator-precedence",
      "confidence": "learning"
    }
  ],
  "is_negative": false,
  "notes": "DataCamp SQL study session (learner opened with 'study buddy/body double' framing). Single concept: AND/OR operator precedence. Learner self-answers with uncertainty marker: 'I believe an AND takes precedence? The second set of parantheses are not required, but make easier for people to read and understand the implied logic' — hedged first-pass answer, confirming the rule rather than stating it from knowledge. All 5 stored messages are user-only (no assistant turns captured), limiting confidence."
}
```

**Drafter confidence**: medium
**Review flags**: All 5 stored messages are user-only — no assistant turns were captured in the DB.
If the full kiro session log is available externally, check whether any follow-up confusion turns
exist. If so, upgrade to `"struggling"`. The concept slug `and-or-operator-precedence` is
SQL-domain-specific; reviewer may prefer `operator-precedence` for cross-topic applicability.

---

## TIER 4 — Adversarial verdict: ACCEPT-AS-IS, high drafter confidence (clean negatives and positives)

---

### Session: kiro_bbe0b048-5c6f-4787-9525-bd24d114470a

**Adversarial verdict**: ACCEPT-AS-IS

```json
{
  "session_id": "kiro_bbe0b048-5c6f-4787-9525-bd24d114470a",
  "expected_topics": [],
  "is_negative": true,
  "notes": "Pure build/ops session: iterating through LLM providers (LM Studio GLM-4.7 Flash, Ollama qwen2.5:32b, MiniMax M2.5, AWS Bedrock Sonnet 4.6) to solve timeout and performance problems in the book2notes tool. All user messages are operational directives or pragmatic choices. No explanation requests, no confusion signals, no teaching interactions. Session concludes with cleanup and documentation work."
}
```

**Drafter confidence**: high | **Review flags**: none

---

### Session: kiro_ea2ed876-6736-4ae1-b020-03fc83568798

**Adversarial verdict**: ACCEPT-AS-IS

```json
{
  "session_id": "kiro_ea2ed876-6736-4ae1-b020-03fc83568798",
  "expected_topics": [],
  "is_negative": true,
  "notes": "Long tool-building session: user directs construction of skillctl (skill manager), studyctl/study-mentor (NotebookLM sync, mermaid-to-PDF rendering, session DB wiring, scheduler management), and a Kiro agent registration. User confidently directing throughout — no concept confusion, no requests for explanation of Python/data-engineering/SQL principles. Minor friction is environmental/tooling (killed session, model crash, mermaid raw-text rendering, CLI path bug, Kiro agent not appearing until new session), each resolved quickly. Zero extractable learning struggles."
}
```

**Drafter confidence**: high | **Review flags**: none

---

### Session: kiro_d00994a0-f414-486c-84b7-1f213b3a1f0a

**Adversarial verdict**: ACCEPT-AS-IS

```json
{
  "session_id": "kiro_d00994a0-f414-486c-84b7-1f213b3a1f0a",
  "expected_topics": [],
  "is_negative": true,
  "notes": "Build/ops session: user directs feature additions to AWS lab-nuke resource cleanup CLI. User messages are: existing code provision, git commit + explore output analysis request, brief praise, factual AWS Resource Explorer CSV API lookup, docs/codemap request, sign-off. User demonstrates confident domain familiarity (Isengard-protected resources, Resource Explorer stale entries, future service targets). CSV question resolved in one turn with no follow-up. Zero learning struggle signals."
}
```

**Drafter confidence**: high | **Review flags**: none

---

### Session: kiro_522f64fb-2261-4e5b-bc57-605dd8ebe15d

**Adversarial verdict**: ACCEPT-AS-IS

```json
{
  "session_id": "kiro_522f64fb-2261-4e5b-bc57-605dd8ebe15d",
  "expected_topics": [],
  "is_negative": true,
  "notes": "Short zsh debugging/config session: user pastes a function with a variable assignment syntax error, attempts own fix (still produces [1m] with empty prefix), asks assistant to patch file, assistant fix also fails to apply correctly, session ends with exit and a typo. Pure task/config debugging, no conceptual confusion, no learning signals."
}
```

**Drafter confidence**: high | **Review flags**: none

---

### Session: kiro_d5add552-7a86-467e-8204-a699acbfdc22

**Adversarial verdict**: ACCEPT-AS-IS

```json
{
  "session_id": "kiro_d5add552-7a86-467e-8204-a699acbfdc22",
  "expected_topics": [],
  "is_negative": true,
  "notes": "Obsidian vault cleanup session: fixing frontmatter, removing duplicates, restructuring folders. All learner messages are task-direction or preference statements, not confusion signals. User actively proposes solutions ('I would suggest they go under Development, not Software-Development'), applies confident taxonomy reasoning, and identifies an unexpected Tags folder as a one-off factual question. No repeated restating, no concept confusion loops."
}
```

**Drafter confidence**: high | **Review flags**: none

---

### Session: kiro_a3751672-57ff-4eee-b8fb-dd7b81ec3c1e

**Adversarial verdict**: ACCEPT-AS-IS

```json
{
  "session_id": "kiro_a3751672-57ff-4eee-b8fb-dd7b81ec3c1e",
  "expected_topics": [],
  "is_negative": true,
  "notes": "Short AWS architecture diagram session (11 messages). User iteratively refines a diagram aesthetically, corrects missing architectural detail (demonstrating expert AWS knowledge: dual TGWs, TGW peerings, inspection VPCs, Cloud WAN core networks), then asks two forward-looking meta-prompting questions ('how would I ask to get this type of diagram?'). Meta-prompting questions resolved in a single exchange with immediate satisfaction ('that's super hepful!'). No distress pattern, no repetition, no correction loop."
}
```

**Drafter confidence**: high | **Review flags**: none

---

### Session: kiro_99c67256-4e1d-42b2-b866-ed1534575236

**Adversarial verdict**: ACCEPT-AS-IS

```json
{
  "session_id": "kiro_99c67256-4e1d-42b2-b866-ed1534575236",
  "expected_topics": [],
  "is_negative": true,
  "notes": "Collaborative debugging session for a broken zsh function (broadcast_download). Learner delegates most investigation to the assistant. The 'how do I best force source to use the new function definition?' question is one procedural line with no follow-up confusion. FUNCNEST error is pasted as output, user immediately self-recovers by trying unset SOURCED_AWS_FUNCTIONS and direct sourcing — no question about what FUNCNEST means. Session ends with 'awesome!!!' and 'fantastic!!!' — clear resolution signals. No repeated restating or confusion loop."
}
```

**Drafter confidence**: high | **Review flags**: none

---

### Session: kiro_4ba5f4fb-7fd3-4089-b199-cab52503f624

**Adversarial verdict**: ACCEPT-AS-IS

```json
{
  "session_id": "kiro_4ba5f4fb-7fd3-4089-b199-cab52503f624",
  "expected_topics": [],
  "is_negative": true,
  "notes": "Pure tool-fixing loop: user pastes successive tracebacks from a Teachable/ZTM course downloader script (ModuleNotFoundError, ElementClickInterceptedException, TimeoutException, ImportError, InvalidCookieDomainException) and assistant patches the code each time. Learner-initiated messages are only operational (pasting errors, suggesting cookie-based auth, asking assistant to run the tool). No conceptual questions, no 'why does this work', no confusion signals about Python or Selenium."
}
```

**Drafter confidence**: high | **Review flags**: none

---

## Human Review Checklist

Tick one column per session after review. Then copy accepted JSON into `eval_golden.json`.

| Session ID | Accept as-is | Edit then accept | Reject | Notes |
|---|---|---|---|---|
| `kiro_1f396c36` (TIER 1 — relabel to positive) | | | | |
| `kiro_d7b6fb48` (TIER 1 — relabel to positive) | | | | |
| `kiro_6c3eedd1` (TIER 1 — relabel to negative) | | | | |
| `kiro_901e20c8` (TIER 1 — relabel to negative) | | | | |
| `kiro_f922b25f` (TIER 1 — relabel to negative) | | | | |
| `kiro_93774693` (TIER 2 — add second topic) | | | | |
| `kiro_3cf73360` (TIER 2 — confidence note) | | | | |
| `kiro_889cad39` (TIER 3 — medium confidence) | | | | |
| `kiro_bbe0b048` (TIER 4 — clean negative) | | | | |
| `kiro_ea2ed876` (TIER 4 — clean negative) | | | | |
| `kiro_d00994a0` (TIER 4 — clean negative) | | | | |
| `kiro_522f64fb` (TIER 4 — clean negative) | | | | |
| `kiro_d5add552` (TIER 4 — clean negative) | | | | |
| `kiro_a3751672` (TIER 4 — clean negative) | | | | |
| `kiro_99c67256` (TIER 4 — clean negative) | | | | |
| `kiro_4ba5f4fb` (TIER 4 — clean negative) | | | | |

**Total entries drafted**: 16
**Positive labels (is_negative: false) in draft**: 5 (`kiro_1f396c36`, `kiro_d7b6fb48`, `kiro_93774693`, `kiro_3cf73360`, `kiro_889cad39`)
**Negative labels (is_negative: true) in draft**: 11
**Reject-and-relabel sessions**: 5 (Tier 1)
**Accept-with-edits sessions**: 2 (Tier 2)
**Accept-as-is sessions**: 9 (Tier 3 + 4)
