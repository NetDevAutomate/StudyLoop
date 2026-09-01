# Your First Week with StudyLoop

A minimal, repeatable path for getting value from StudyLoop without configuring every agent or LLM provider on day one. The core workflow is **live Socratic study**; flashcards, quizzes, and session export support that loop.

## What you need

- Python 3.12+, [uv](https://docs.astral.sh/uv/), and **tmux 3.1+** (for `studyloop study`)
- One supported AI coding agent on your PATH: Kiro CLI, Codex, Claude Code,
  OpenCode, or pi. Kiro is the documented first-session path.
- Optional: Obsidian vault for study notes; optional: Ollama or AWS Bedrock for local/cloud card generation

Install from source (see [Setup Guide](setup-guide.md)):

```bash
git clone https://github.com/NetDevAutomate/StudyLoop.git studyloop
cd studyloop
./scripts/install.sh
studyloop setup
studyloop doctor --fix
```

## Day 1 — Install and one live session

1. Run `studyloop doctor --fix` until core checks pass.
2. Start a short study session (pick one topic you care about):

   ```bash
   studyloop study "Python decorators" --energy 6
   ```

   Or use the web picker:

   ```bash
   studyloop web
   ```

   Open the **Study Session** tab, choose a topic and agent, and start.

3. At the end of the session, run `studyloop study --end` or end from the web UI.

4. Check context for next time:

   ```bash
   studyloop resume
   ```

## Day 2 — Let StudyLoop choose one next action

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
   session-query list --since last-7-days
   ```

   `--since` takes `YYYY-MM-DD`, `last-week`, `last-month`, or `last-N-days`.
   Shorthand like `7d` is rejected.

2. Surface progress (useful for AuDHD “nothing counts” moments):

   ```bash
   studyloop wins
   studyloop streaks
   studyloop review
   studyloop recap today
   ```

3. If you use Kiro and want struggle signals in progress tracking:

   ```bash
   studyloop extract-struggles --incremental --dry-run --model <bedrock-model-id>
   ```

   `--model` is required — it names the Bedrock model that reads your sessions.
   Set `STUDYLOOP_EXTRACTOR_MODEL` once and you can leave the flag off. This
   step needs AWS credentials; skip it if you have none configured.

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

3. Check that your chosen mentor runs `studyloop resume` and `studyloop review`
   at session start. Reinstall the shipped agent definitions with
   `studyloop install agents` if it does not.

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
- Skim [Web UI Guide](web-ui-guide.md) for LAN mode (`studyloop web --lan`) if
  you review from a tablet or another laptop on the same trusted network. Phone
  screens are not supported.

## What to defer

| Later | Why |
|-------|-----|
| Every LLM provider in Settings | One working backend is enough for generation |
| NotebookLM sync commands | Legacy optional path; not required for core study |
| `session-export --obsidian` | Opt-in vault mirror; enable when you want Dataview notes |
| All eight agent CLIs | Start with the one you already use daily |

## Where to go next

- [CLI Reference](cli-reference.md) — full command list
- [Architecture Overview](architecture.md) — how the Web UI, agents, files, and SQLite fit together
- [AuDHD Philosophy](audhd-learning-philosophy.md) — why energy checks and wins matter
