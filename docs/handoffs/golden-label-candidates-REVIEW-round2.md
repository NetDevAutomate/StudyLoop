# Golden Label Candidates — Human Review Round 2

## WARNING: DRAFT LABELS — DO NOT MERGE WITHOUT HUMAN REVIEW

These labels were produced by an LLM pipeline (extractor + adversarial checker).
An LLM **must not** author the golden truth it will later be graded against — that
is a circularity that poisons the evaluation gate. A human must read every entry
below and make the accept/edit/reject decision independently.

**Branch:** `feat/struggle-extraction-pipeline`
**Produced:** 2026-05-31 — Round 2 (13 sessions from targeted corpus survey)

---

## Acceptance Steps

1. Read each section below.
2. For each entry, tick one checkbox in the checklist footer.
3. For accepted or edited entries, copy the JSON block (with any edits applied)
   into `packages/studyloop/tests/fixtures/eval_golden.json`, appending to the
   existing array.
4. After all accepted entries are added, rebuild the split file:
   ```bash
   uv run python -m studyloop.eval.split_golden
   ```
   (or whatever the current split-rebuild command is).
5. Do **not** modify `eval_golden.json` or `eval_split.json` in any other way —
   no automated backfill, no LLM writes.

---

## Sort Order

Entries are sorted **riskiest first**:
1. `reject-and-relabel` verdicts (adversarial checker disagrees with draft)
2. Low-confidence drafts
3. `accept-with-edits` verdicts (adversarial checker approves with caveats)
4. `accept-as-is` negatives
5. `accept-as-is` positives

---

## Session: kiro_321cca75-3534-464d-8ab2-c14f010ddb7d

**Drafter verdict:** `is_negative: true` — no topics drafted
**Adversarial verdict:** `reject-and-relabel` — drafter missed a genuine struggle

> The adversarial checker found a substantive struggle the drafter overlooked.
> The learner's terminal output shows three consecutive `gem pristine` failures
> across system Ruby 2.6, mise Ruby 3.4.8, and Homebrew ruby@3.4 — all pointing
> at the wrong Ruby installation. The learner then ran diagnostic commands
> (`which ruby`, `type ruby`, `grep -i ruby ~/.zshrc`) confirming they were
> actively troubleshooting a multi-Ruby PATH conflict, not just reporting an
> error. The adversarial checker proposes relabelling with the topic below.

**Drafter confidence:** high (for the original negative — but the negative is wrong)

**Drafter flags:** "The Ruby version-manager question could theoretically be labelled
as `ruby-version-manager-macos`, but the assistant never answers it and the learner
never pursues it." — The adversarial checker agrees the bare recommendation question
is too thin, but identifies the *actual* struggle as the repeated gem failures and
PATH diagnostics, not the question.

**Adversarial-checker proposed label:**

```json
{
  "session_id": "kiro_321cca75-3534-464d-8ab2-c14f010ddb7d",
  "is_negative": false,
  "expected_topics": [
    {
      "topic": "ruby",
      "concept": "gem-path-multi-ruby-confusion-macos",
      "confidence": "learning"
    }
  ],
  "notes": "The learner hit repeated gem pristine failures across three concurrent Ruby installations (system 2.6, mise 3.4.8, Homebrew ruby@3.4), then ran 'which ruby', 'type ruby', and 'grep -i ruby ~/.zshrc' to diagnose the PATH conflict. The zsh parse-error thread is a clean help-desk exchange with no struggle signal. The Ruby version-manager recommendation question ('rbenv / chruby / mise / asdf?') is too thin on its own, but the gem PATH confusion is evidenced by the learner's own repeated failed commands."
}
```

**Draft JSON (original — for reference):**

```json
{
  "session_id": "kiro_321cca75-3534-464d-8ab2-c14f010ddb7d",
  "is_negative": true,
  "expected_topics": [],
  "notes": "The session is dominated by ops/debugging work: resolving gem warnings, diagnosing a tangled Ruby PATH (system Ruby 2.6, mise Ruby 3.4.8, Homebrew ruby@3.4 all competing), and fixing unmatched-quote parse errors in a zsh dotfiles alias file. The Ruby version-manager question is a single passing question with no sustained learning thread; the assistant never substantively answers it and the learner never pursues it."
}
```

**Human decision:**
- [ ] Accept adversarial-checker label (use the `reject-and-relabel` JSON above)
- [ ] Accept original draft (negative, no topics)
- [ ] Edit and accept (modify concept slug, confidence, or notes before accepting)
- [ ] Reject both / skip

---

## Session: kiro_e9d60bd4-81f0-4f27-babb-bb99fdcd3d19

**Drafter verdict:** `is_negative: false` — one topic drafted
**Adversarial verdict:** `accept-as-is`
**Drafter confidence:** **low** — single unexplored question with no confirmation of understanding

> The drafter flagged this as low confidence because the session is very short (3
> user messages) and ends immediately after the learner's "without making changes,
> can you explain" request, with no learner reply confirming understanding. The
> adversarial checker disagrees: it treats the explicit "without making changes,
> can you explain" phrasing as the canonical struggle pattern (explanation sought,
> not a fix), overriding the length concern.

**Drafter flags:** "A human reviewer may reasonably classify this as a negative
(ops/diagnostic session) rather than a learning session, since a single unexplored
question with no confirmation of struggle or follow-up confusion is below the bar
set by existing golden examples."

**Proposed JSON:**

```json
{
  "session_id": "kiro_e9d60bd4-81f0-4f27-babb-bb99fdcd3d19",
  "is_negative": false,
  "expected_topics": [
    {
      "topic": "git",
      "concept": "src-refspec-does-not-match-push-error",
      "confidence": "learning"
    }
  ],
  "notes": "The learner encountered 'error: src refspec main does not match any' and explicitly asked for an explanation without making changes: 'without making changes, can you explain: error: src refspec main does not match any'. The explicit 'without making changes, can you explain' framing signals deliberate learning intent — they wanted to understand the error mechanism before acting. Session is very short (3 user messages) and ends after the assistant's explanation with no learner reply, so confidence is learning rather than struggling."
}
```

**Human decision:**
- [ ] Accept
- [ ] Edit and accept
- [ ] Reject (reclassify as negative — single unanswered question, no confirmation)

---

## Session: kiro_a58c2ec1-4df1-4f2b-a133-18f542a8aa04

**Drafter verdict:** `is_negative: false` — two topics drafted
**Adversarial verdict:** `accept-with-edits`
**Drafter confidence:** medium

> Both concepts have direct verbatim support. Concept 1: learner's first message
> pastes a draft refactoring with real errors and asks "Is the following correct?" —
> clear first-pass acquisition. Concept 2: learner explicitly singles out
> `field(init=False)` for deeper explanation. The adversarial checker notes the two
> concepts could reasonably be merged into one (`dataclass-defaults-and-field-options`)
> since the session is only 3 user messages. Human reviewer decides whether the split
> adds signal or noise.

**Drafter flags:** "Without assistant turns we cannot confirm whether the learner's
original code contained errors that would push the refactoring concept toward
'struggling'. The two concepts could reasonably be collapsed into one."

**Option A — keep split (as drafted):**

```json
{
  "session_id": "kiro_a58c2ec1-4df1-4f2b-a133-18f542a8aa04",
  "is_negative": false,
  "expected_topics": [
    {
      "topic": "python",
      "concept": "dataclass-refactoring-patterns",
      "confidence": "learning"
    },
    {
      "topic": "python",
      "concept": "dataclass-field-init-false",
      "confidence": "learning"
    }
  ],
  "notes": "The learner is converting hand-written __init__ classes to dataclasses and presents a candidate refactoring with 'Is the following correct?' — a first-pass acquisition check. Code includes field(default_factory=list[int]) and attempts a derived attribute (b: int = a + 3) inside the class body, indicating first exposure to @dataclass and field() mechanics. After the reply the learner explicitly asks for deeper explanation of 'field(init=False) — for attributes that shouldn't be constructor params', singling it out as new. Session ends with 'great, nice explanation - many thanks'. Neither concept reaches struggling threshold; both are first-pass learning."
}
```

**Option B — merge into single concept:**

```json
{
  "session_id": "kiro_a58c2ec1-4df1-4f2b-a133-18f542a8aa04",
  "is_negative": false,
  "expected_topics": [
    {
      "topic": "python",
      "concept": "dataclass-defaults-and-field-options",
      "confidence": "learning"
    }
  ],
  "notes": "The learner is converting hand-written __init__ classes to dataclasses. First message pastes a draft refactoring and asks 'Is the following correct?' — errors include incorrect field(default_factory=...) usage and a class-body derived attribute. Follow-up explicitly requests deeper explanation of field(init=False). Session ends with 'great, nice explanation - many thanks'. Short session (3 user messages); merged concept avoids over-splitting a thin transcript."
}
```

**Human decision:**
- [ ] Accept Option A (split into two concepts)
- [ ] Accept Option B (merge into one concept)
- [ ] Edit and accept
- [ ] Reject

---

## Session: kiro_2e4d1ada-b2e3-4051-b80c-04138f90c18e

**Drafter verdict:** `is_negative: false` — two topics drafted
**Adversarial verdict:** `accept-with-edits` — drop `leader-key`, keep `vim-keybinding-notation`
**Drafter confidence:** medium

> The adversarial checker supports Topic 1 (`vim-keybinding-notation`) but rejects
> Topic 2 (`leader-key`). The user asked "what is the leader set to in this config?"
> framed as "a silly question" — the checker reads this as a pure config lookup, not
> a conceptual struggle about what a leader key is or how it works. The drafter's own
> flag acknowledges this ambiguity. Recommended: drop leader-key, keep vim-keybinding-notation.

**Drafter flags:** "The leader key question could be read as a pure config lookup
rather than a learning moment — reviewer may prefer to drop it if the bar is
'struggle only'."

**Option A — keep both topics (as drafted):**

```json
{
  "session_id": "kiro_2e4d1ada-b2e3-4051-b80c-04138f90c18e",
  "is_negative": false,
  "expected_topics": [
    {
      "topic": "neovim",
      "concept": "vim-keybinding-notation",
      "confidence": "learning"
    },
    {
      "topic": "neovim",
      "concept": "leader-key",
      "confidence": "learning"
    }
  ],
  "notes": "Two first-pass learning moments. (1) Vim keybinding notation: learner asked 'when you state <C-Space> is this literally capital C then Space?' — showing they had not encountered the <C-x> notation and misread it as uppercase C. Resolved in one exchange ('oh perfect - thank you'). (2) Leader key: learner asked 'a silly question, but in this config, what is the leader set to?' — self-deprecating framing signals awareness this is basic knowledge they feel they should know. No follow-up confusion on either concept."
}
```

**Option B — drop leader-key (adversarial checker recommendation):**

```json
{
  "session_id": "kiro_2e4d1ada-b2e3-4051-b80c-04138f90c18e",
  "is_negative": false,
  "expected_topics": [
    {
      "topic": "neovim",
      "concept": "vim-keybinding-notation",
      "confidence": "learning"
    }
  ],
  "notes": "The learner asked 'when you state <C-Space> is this literally capital C then Space?' — showing they had not previously encountered the <C-x> = Ctrl notation and misread it as uppercase C. Clarified in one exchange ('oh perfect - thank you'). Single real learning signal; leader-key question dropped as it reads as a config lookup rather than a conceptual gap."
}
```

**Human decision:**
- [ ] Accept Option A (keep both topics)
- [ ] Accept Option B (drop leader-key — adversarial checker recommendation)
- [ ] Edit and accept
- [ ] Reject

---

## Session: kiro_a1ef9045-6a85-44b2-a02d-4f7ac48a3fb9

**Drafter verdict:** `is_negative: false` — one topic drafted
**Adversarial verdict:** `accept-as-is`
**Drafter confidence:** medium — shallow engagement, borderline

> Verbatim quote "I've never tried this in a zsh file" directly supports a
> first-exposure signal. The adversarial checker accepts the label as-is: the
> `learning` confidence tier already encodes the shallow engagement, so no
> stronger label is warranted. The drafter's shallowness concern is valid as a
> caveat but does not justify rejecting the label.

**Drafter flags:** "A reviewer might reasonably call this a negative on the grounds
that the user did not actually work through the concept themselves. The 'learning'
label is defensible but borderline."

**Proposed JSON:**

```json
{
  "session_id": "kiro_a1ef9045-6a85-44b2-a02d-4f7ac48a3fb9",
  "is_negative": false,
  "expected_topics": [
    {
      "topic": "zsh",
      "concept": "zsh-command-completion",
      "confidence": "learning"
    }
  ],
  "notes": "Session is primarily a build/scripting task (creating kiro_cli_config.zsh), but contains one clear first-pass learning moment. After the assistant created the config file the user revealed no prior exposure: 'is it possible to add command completion? I've never tried this in a zsh file'. They then immediately requested a learning document on the topic ('could you add a short markdown document ... on how to add command completion to a zsh script ... This will be SUPER helpful for my learning?'). Shallow engagement — one question plus a doc request — but first-exposure is confirmed verbatim."
}
```

**Human decision:**
- [ ] Accept
- [ ] Edit and accept
- [ ] Reject (reclassify as negative — too shallow, no active exploration)

---

## Session: kiro_57a7983c-2cd6-4f96-b995-2b79ba09455e

**Drafter verdict:** `is_negative: true`
**Adversarial verdict:** `accept-as-is`
**Drafter confidence:** high

> Tooling/ops session. Self-resolved tab completion issue, one-and-done shell flag
> lookup (`exec $SHELL -L` vs `-l`), neovim clipboard config, CLI grep work. No
> repeated concepts, no confusion signals.

**Drafter flags:** "The `exec $SHELL -L or -l` question is a first-pass factual
lookup. If the golden set includes single-question first-pass acquisitions as
'learning', this could be labelled. Reviewer should check calibration."

**Proposed JSON:**

```json
{
  "session_id": "kiro_57a7983c-2cd6-4f96-b995-2b79ba09455e",
  "is_negative": true,
  "expected_topics": [],
  "notes": "Tooling/ops session. Typer/zsh tab completion issue was self-resolved by the user ('Not a big deal as the -- options complete'). 'exec $SHELL -L or -l?' is a one-shot factual lookup with immediate uptake ('cool, I'll create an alias') — below the bar for a learning label. Neovim clipboard config and CLI grep work are pure task execution. No repeated restating, no confirmation-seeking, no follow-up confusion."
}
```

**Human decision:**
- [ ] Accept (negative)
- [ ] Edit and accept as positive (`exec $SHELL` shell flag question = `shell-login-flag-semantics`)
- [ ] Reject

---

## Session: kiro_246e6c2c-267b-4389-96bb-c943e6b1eb06

**Drafter verdict:** `is_negative: true`
**Adversarial verdict:** `accept-as-is`
**Drafter confidence:** high

> Ansible/secrets ops session. Opening question about API key storage best practices
> has no visible assistant response and no learner follow-up; the user moved straight
> to implementation, demonstrating fluency with age, zsh autoload, and Ansible
> throughout. The assistant response body is entirely absent from the transcript.

**Drafter flags:** "The opening question alone — without the response or any
follow-up — may not meet the bar for a 'learning' label. Reviewer should decide
if a question with no visible answer and no follow-up qualifies."

**Proposed JSON:**

```json
{
  "session_id": "kiro_246e6c2c-267b-4389-96bb-c943e6b1eb06",
  "is_negative": true,
  "expected_topics": [],
  "notes": "Ansible playbook / age-encrypted secrets ops session. Opening question ('what is the general best practice for storing and exporting API Keys/Tokens') has no visible assistant response in the transcript (only tool stubs logged) and no learner follow-up — the user's immediate next message is 'fantastic, can you configure the playbook'. The user demonstrates fluency with age, zsh autoload, Ansible, and secrets management throughout the session, treating all concepts as known territory. Closest operational struggle (secrets-load returning nothing) is a bug the assistant debugged, not a conceptual struggle by the learner."
}
```

**Human decision:**
- [ ] Accept (negative)
- [ ] Edit and accept as positive (`api-key-storage-patterns`)
- [ ] Reject

---

## Session: kiro_4fdb3372-7821-42f6-aecf-9df2ff6c9162

**Drafter verdict:** `is_negative: true`
**Adversarial verdict:** `accept-as-is`
**Drafter confidence:** high

> Debugging session (NetworkX import missing, method-vs-property bug). One concept
> question (`--editable` flag for `uv tool install`) was asked but never answered —
> no explanatory assistant turn between the question and the next user message.

**Drafter flags:** "If the reviewer has reason to believe a response was truncated
or stored elsewhere, the `uv-tool-editable-install` concept could be revisited.
As-is, labelling it would be adding a topic with zero acquisition evidence."

**Proposed JSON:**

```json
{
  "session_id": "kiro_4fdb3372-7821-42f6-aecf-9df2ff6c9162",
  "is_negative": true,
  "expected_topics": [],
  "notes": "Debugging session for lab-nuke CLI tool (NetworkX import issue, method-vs-property bug in Configuration class). One concept question — 'what does the --editable do with uv tool install?' at rowid 40062 — received no answer: the next user message (rowid 40063) is tool output and the assistant resumes debugging without addressing the question. Zero acquisition evidence for any topic. All other turns are tool calls, patches, and test runs."
}
```

**Human decision:**
- [ ] Accept (negative)
- [ ] Edit and accept as positive (`uv-tool-editable-install`) — only if you know the assistant did answer elsewhere
- [ ] Reject

---

## Session: kiro_688dba98-1987-47bf-9363-b73edcda61f9

**Drafter verdict:** `is_negative: true`
**Adversarial verdict:** `accept-as-is`
**Drafter confidence:** high

> Extremely thin session (5 DB rows). MCP connectivity check then one explain request
> ("please can you explain the Core network A policy and NFG configuration?") where
> the assistant response is truncated — the session ends before any explanation was
> delivered.

**Drafter flags:** "If there is a continuation session, that would be the right place
to look for struggle signals."

**Proposed JSON:**

```json
{
  "session_id": "kiro_688dba98-1987-47bf-9363-b73edcda61f9",
  "is_negative": true,
  "expected_topics": [],
  "notes": "5 DB rows total. User verified MCP server connectivity then asked 'please can you explain the Core network A policy and NFG configuration?' — the assistant response is truncated and the session ends before any explanation was delivered. No back-and-forth, no follow-up questions, no confusion signals. A single explain-request with a cut-off response is insufficient evidence of a learning struggle."
}
```

**Human decision:**
- [ ] Accept (negative)
- [ ] Edit and accept as positive (AWS CloudWAN policy / NFG)
- [ ] Reject

---

## Session: kiro_fcb01d07-748a-42ab-b1c6-f004648dfbff

**Drafter verdict:** `is_negative: true`
**Adversarial verdict:** `accept-as-is`
**Drafter confidence:** high

> 4-message session. Two assistant stubs that both end mid-flight. One follow-up
> user question received no reply at all. No completed exchange.

**Drafter flags:** "Possible the session was cut off mid-flight and more content
exists elsewhere."

**Proposed JSON:**

```json
{
  "session_id": "kiro_fcb01d07-748a-42ab-b1c6-f004648dfbff",
  "is_negative": true,
  "expected_topics": [],
  "notes": "4-message session. User requested explanation of Cloud WAN core network policy and NFGs via awslabs MCP; both assistant responses end mid-flight with no tool results or explanations delivered. Follow-up question ('what is the policy required to attach a vpc to a specific segment?') received no assistant reply. No completed exchange, no learner confusion or confusion signals — session was cut off before substantive content was produced."
}
```

**Human decision:**
- [ ] Accept (negative)
- [ ] Edit and accept as positive
- [ ] Reject

---

## Session: kiro_5e6f9479-98d1-4ec3-af1b-10b0fdcfb3b3

**Drafter verdict:** `is_negative: true`
**Adversarial verdict:** `accept-as-is`
**Drafter confidence:** high

> Pure task execution. Two terse imperatives directing a kiro agent to query AWS
> CloudWAN and produce markdown + Mermaid report artefacts. Four repeated tool
> errors not engaged with conceptually.

**Proposed JSON:**

```json
{
  "session_id": "kiro_5e6f9479-98d1-4ec3-af1b-10b0fdcfb3b3",
  "is_negative": true,
  "expected_topics": [],
  "notes": "Ops/tooling session. User issues two terse imperatives directing a kiro agent to query AWS CloudWAN and Transit Gateway and produce markdown/Mermaid reports. Four repeated get_cloudwan_routes tool errors (KeyError on 'Destinations') are not engaged with conceptually. No comprehension questions, no confirmation-seeking, no repeated restating. Pure task execution."
}
```

**Human decision:**
- [ ] Accept (negative)
- [ ] Edit and accept as positive
- [ ] Reject

---

## Session: kiro_34da9f1b-65d5-4421-be71-25038012e149

**Drafter verdict:** `is_negative: true`
**Adversarial verdict:** `accept-as-is`
**Drafter confidence:** high

> Obsidian plugin ops session. User debugging make.md plugin path misconfiguration,
> asking about plugin use cases, and asking about processes/API tokens. No learning
> struggle signals of any kind.

**Proposed JSON:**

```json
{
  "session_id": "kiro_34da9f1b-65d5-4421-be71-25038012e149",
  "is_negative": true,
  "expected_topics": [],
  "notes": "Pure ops/tooling session. User debugging a misconfigured make.md Obsidian plugin (root-level //People path instead of 3-Resources/People), asking for plugin use-case information to decide whether to remove it, and asking operational questions about processes and API tokens. No learning-struggle signals: no repeated restating, no 'Just to confirm...', no follow-up confusion. The 'can't see any option in the make.d plugin' quote is a UX investigation statement, not a conceptual struggle signal."
}
```

**Human decision:**
- [ ] Accept (negative)
- [ ] Edit and accept as positive
- [ ] Reject

---

## Session: kiro_69424a87-4736-4675-b9eb-f13185ae1efd

**Drafter verdict:** `is_negative: true`
**Adversarial verdict:** `accept-as-is`
**Drafter confidence:** high

> Build-and-iterate session (ePub-to-Obsidian UV tool). User acts as product owner
> throughout: spec requests, refinement instructions, test directives,
> product-quality feedback, pragmatic engineering suggestions. No learning struggle
> signals.

**Proposed JSON:**

```json
{
  "session_id": "kiro_69424a87-4736-4675-b9eb-f13185ae1efd",
  "is_negative": true,
  "expected_topics": [],
  "notes": "Build/iterate session. User specifies and iterates on an ePub-to-Obsidian study-note UV tool, acting as product owner throughout: viability question, module-separation instruction, EPUB test directive, note-quality feedback, LM Studio pivot. All failures (copyright refusal, token limits, API timeouts) are tool/environment issues, not learner comprehension issues. No conceptual confusion, no 'just to confirm', no repeated restating."
}
```

**Human decision:**
- [ ] Accept (negative)
- [ ] Edit and accept as positive
- [ ] Reject

---

## Summary Checklist

| # | session_id (short) | Drafter | Adversarial | Confidence | Decision |
|---|---|---|---|---|---|
| 1 | kiro_321cca75 | negative | **reject-and-relabel** | high (wrong) | [ ] accept relabel [ ] keep negative [ ] edit [ ] skip |
| 2 | kiro_e9d60bd4 | positive (git refspec) | accept-as-is | **low** | [ ] accept [ ] edit [ ] reject |
| 3 | kiro_a58c2ec1 | positive (2 topics) | accept-with-edits | medium | [ ] split [ ] merge [ ] edit [ ] reject |
| 4 | kiro_2e4d1ada | positive (2 topics) | accept-with-edits | medium | [ ] 2 topics [ ] 1 topic [ ] edit [ ] reject |
| 5 | kiro_a1ef9045 | positive (zsh-completion) | accept-as-is | medium | [ ] accept [ ] edit [ ] reject |
| 6 | kiro_57a7983c | negative | accept-as-is | high | [ ] accept [ ] add topic [ ] reject |
| 7 | kiro_246e6c2c | negative | accept-as-is | high | [ ] accept [ ] add topic [ ] reject |
| 8 | kiro_4fdb3372 | negative | accept-as-is | high | [ ] accept [ ] add topic [ ] reject |
| 9 | kiro_688dba98 | negative | accept-as-is | high | [ ] accept [ ] add topic [ ] reject |
| 10 | kiro_fcb01d07 | negative | accept-as-is | high | [ ] accept [ ] add topic [ ] reject |
| 11 | kiro_5e6f9479 | negative | accept-as-is | high | [ ] accept [ ] add topic [ ] reject |
| 12 | kiro_34da9f1b | negative | accept-as-is | high | [ ] accept [ ] add topic [ ] reject |
| 13 | kiro_69424a87 | negative | accept-as-is | high | [ ] accept [ ] add topic [ ] reject |

**Positives in this batch (if all accepted):** 5 (kiro_321cca75 relabelled, kiro_e9d60bd4, kiro_a58c2ec1, kiro_2e4d1ada, kiro_a1ef9045)
**Negatives in this batch (if all accepted):** 8

**Reminder:** After accepting entries, copy JSON into `eval_golden.json` and rebuild `eval_split.json`. Do not run `studyloop extract-struggles --commit`.
