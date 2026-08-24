# Your First Week with StudyLoop

A minimal, repeatable path for getting value from StudyLoop without configuring every agent or LLM provider on day one. The core workflow is **one focused plan followed by live Socratic study**; flashcards, quizzes, and session export support that loop.

## What you need

- Python 3.12+, [uv](https://docs.astral.sh/uv/), and **tmux 3.1+** (for `studyloop study`)
- One reachable OpenAI-compatible planning model. `studyloop setup` auto-detects supported local LiteLLM addresses, or accepts an explicit gateway URL and model name.
- One AI coding agent on your PATH (Kiro, Claude Code, Codex, or Gemini are common choices)
- Optional: a Markdown/plain-text notes folder (including an Obsidian vault); optional: Ollama or AWS Bedrock for local/cloud card generation

Install from source (see [Setup Guide](setup-guide.md)):

```bash
git clone https://github.com/NetDevAutomate/StudyLoop.git studyloop
cd studyloop
./scripts/install.sh
studyloop setup
studyloop doctor --fix
```

## Day 1 — Turn the brain dump into one plan

1. Run `studyloop doctor --fix` until core checks pass.
2. Check the planning result printed by `studyloop setup`. If it reported no live
   planning model, configure the gateway you intend to use:

   ```bash
   studyloop setup --planning-base-url URL --planning-model MODEL
   ```

   The scripted preflight checks StudyLoop's protocol, but it is not a substitute
   for the live model required by the browser Architect.

3. Launch the browser:

   ```bash
   studyloop web
   ```

   Open **Study Plans → Create with Architect**. Type or dictate one brain dump:
   where you are, what you want to be able to do, and anything that is getting in
   the way. Answer the focused follow-up questions, inspect the Markdown proposal
   and learning-map diagram, then **Approve**, **Revise**, or **Reject** it.

   A course outline or Markdown/plain-text note is optional context. It can shape
   the plan, but it does not count as study completed. StudyLoop keeps at most
   three current plans so the first week does not become a new backlog.

4. Start a short study session from the approved plan (or pick its first topic):

   ```bash
   studyloop study "Python decorators" --energy 6
   ```

   Or stay in the browser: open **Study Session**, choose a topic and agent, and start.

5. At the end of the session, run `studyloop study --end` or end from the web UI.

6. Check context for next time:

   ```bash
   studyloop resume
   ```

## Day 2 — Let StudyLoop choose one next action

`studyloop now` currently ranks recorded learning evidence; it does not yet
prioritise the new plan's milestones. Use the plan's visible next action when
the two disagree. This limitation is tracked in the [Study Plans guide](study-plans.md#how-a-plan-drives-today-not-implemented).

1. Ask for one useful next action instead of picking from the whole vault:

   ```bash
   studyloop now --energy medium --time 20
   ```

2. Open the source note it points at, or pick one note from your current course:

   ```bash
   studyloop chat-note ~/Obsidian/Personal/Study/Python/decorators.md --mode recall
   ```

3. End with a small evidence record. Use the command printed by `studyloop now`
   or `chat-note`, usually `studyloop progress` or `studyloop teachback`.

## Day 3 — Session memory and wins

1. Export recent agent sessions into the shared database (from any tool you already use):

   ```bash
   session-export
   session-query list --since 7d
   ```

2. Surface progress (useful for AuDHD “nothing counts” moments):

   ```bash
   studyloop wins
   studyloop streaks
   studyloop review
   studyloop recap today
   ```

3. If you use Kiro and want struggle signals in progress tracking:

   ```bash
   studyloop extract-struggles --incremental --dry-run
   ```

## Day 4 — Review support and source notes

If you have markdown notes or a course folder:

```bash
studyloop content discover
studyloop content generate-cards ~/path/to/course-notes --course my-course
studyloop content generate-practice ~/path/to/course-notes --course my-course
studyloop web
```

Use **Flashcards** or **Quizzes** in the web app. In the **Course Explorer**, open a lesson and use **Discuss** to copy a Socratic prompt from the current note; use **Struggling?** when the lesson should feed future repair work. You do not need NotebookLM for this path.

> **Practice tasks stay in the terminal.** The web app has no exercises panel
> yet, so review the JSON that `generate-practice` wrote with
> `studyloop practice verify TASKS.json --task 1 --notes "what passed"`.

For generation, configure **one** provider in the web **Settings → LLM Providers** panel (Ollama locally or Bedrock/OpenAI if you already have keys). See [Content Pipeline](content-pipeline.md).

## Day 5 — Agents and backlog

1. Install agent definitions for your tool:

   ```bash
   studyloop install agents
   ```

2. Park tangents instead of rabbit-holing:

   ```bash
   studyloop park "How does asyncio compare to threads?" -t python
   studyloop backlog list
   ```

3. Re-read [Session Protocol](session-protocol.md) so your agent runs `studyloop resume` and `studyloop review` at session start.

## Day 6 — Visualise weak links

Use the mastery commands once you have a few progress records:

```bash
studyloop mastery graph --topic python
studyloop mastery weak-links --topic python
studyloop review --interleave adaptive --energy low
```

The graph is Mermaid by default, so it can be pasted into Obsidian.

## Day 7 — Hardening habits

- Run `studyloop clean --dry-run` if tmux study sessions ever feel “stuck”.
- Set `studyloop backup` before big config experiments.
- Skim [Web UI Guide](web-ui-guide.md) for LAN mode (`studyloop web --lan`) if you use a tablet or computer on the same network. Phone-sized screens are out of scope for this release.

## What to defer

| Later | Why |
|-------|-----|
| Every LLM provider in Settings | One working backend is enough for generation |
| NotebookLM sync commands | Legacy optional path; not required for core study |
| `session-export --obsidian` | Opt-in vault mirror; enable when you want Dataview notes |
| All eight agent CLIs | Start with the one you already use daily |

## Where to go next

- [CLI Reference](cli-reference.md) — full command list
- [Architecture (current)](architecture/current.md) — how web, tmux, ACP, and SQLite fit together
- [AuDHD Philosophy](audhd-learning-philosophy.md) — why energy checks and wins matter
