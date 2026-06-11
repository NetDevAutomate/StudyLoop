# Your First Week with StudyLoop

A minimal, repeatable path for getting value from StudyLoop without configuring every agent or LLM provider on day one. The core workflow is **live Socratic study**; flashcards, quizzes, and session export support that loop.

## What you need

- Python 3.12+, [uv](https://docs.astral.sh/uv/), and **tmux 3.1+** (for `studyloop study`)
- One AI coding agent on your PATH (Kiro, Claude Code, Codex, or Gemini are common choices)
- Optional: Obsidian vault for study notes; optional: Ollama or AWS Bedrock for local/cloud card generation

Install from source (see [Setup Guide](setup-guide.md)):

```bash
git clone https://github.com/Hookey-Street-Software/StudyLoop.git studyloop
cd studyloop
uv sync --all-packages
uv tool install './packages/studyloop[sessions,web,content]'
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

## Day 2 — Session memory and wins

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
   ```

3. If you use Kiro and want struggle signals in progress tracking:

   ```bash
   studyloop extract-struggles --incremental --dry-run
   ```

## Day 3 — Review support (optional)

If you have markdown notes or a course folder:

```bash
studyloop content discover
studyloop content generate-cards ~/path/to/course-notes --course my-course
studyloop web
```

Use **Flashcards** or **Quizzes** in the PWA. You do not need NotebookLM for this path.

For generation, configure **one** provider in the web **Settings → LLM Providers** panel (Ollama locally or Bedrock/OpenAI if you already have keys). See [Content Pipeline](content-pipeline.md).

## Day 4 — Agents and backlog

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

## Day 5 — Hardening habits

- Run `studyloop clean --dry-run` if tmux study sessions ever feel “stuck”.
- Set `studyloop backup` before big config experiments.
- Skim [Web UI Guide](web-ui-guide.md) for LAN mode (`studyloop web --lan`) if you review from a phone on the same network.

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
