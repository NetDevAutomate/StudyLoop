---
name: studyloop-xtiles-wind-down
description: At the end of a StudyLoop study session (wind-down phase), when `studyloop brain status --json` reports `provider: xtiles` and an `xtiles` MCP server is connected in this session, offer ONCE to write the session's learning record and the next review into the learner's xTiles project. Silent in every other case.
---

# StudyLoop → xTiles wind-down (opt-in)

Installed once into `~/.agents/skills/` and symlinked into each supported harness's
own skills directory by `studyloop install agents`. One body, so the offer rule
cannot drift between harnesses; see `references/harnesses.md` for what differs per
harness (invocation, install path) and why nothing else does.

Inert until both gates below are true. StudyLoop does not talk to xTiles itself:
the learner's assistant holds both connections, so this file is instructions for
you, not a feature of the CLI.

Use only during Phase 1 of `~/.agents/shared/wind-down-protocol.md`, after progress
has been recorded with `studyloop progress "<concept>" -t <topic> -c <confidence>`.

## Gate — both halves, checked every session

1. `studyloop brain status --json` reports `provider: xtiles`. Any other provider
   means this file does not apply: an Obsidian learner has already been offered the
   publish command in Phase 1, and a learner on `none` has chosen neither.
2. An MCP server named `xtiles` is connected in this session — its tools are
   visible to you. If it is not, do nothing and say nothing about xTiles. Do not
   suggest they connect one; an offer to set up a service they never asked for is
   the thing this gate exists to prevent.

If either half is false, continue the wind-down without mentioning xTiles at all.

## The offer

Offer once, in one line:

> Want me to add today's learning record and the next review to your xTiles project? Yes or no — I'll only ask once.

On **yes**, follow prompt P3 from the Second Brain guide: one learning-record page
under the plan's project, one dated planner task for the next review, then say what
you wrote. Ask before each write, and if xTiles refuses a write, report what it
said rather than retrying.

On **no**, continue the wind-down and do not raise it again this session.

## What this sends, and where

The summary, the plan title and the next review date go to the model service
backing this session and, through the connector, to xTiles' cloud. xTiles asks
permission per request, and your assistant reaches only what the learner's own
xTiles account can already see — nothing is shared with other users. StudyLoop
stores no xTiles credential and keeps no copy of what was written: the sign-in
lives in the assistant's own MCP configuration.

Creating a page or a task works on any xTiles plan, including Free. Editing an
existing project in place is a paid feature, so a refused write on a Free account
is the plan talking, not a bug — say so and stop.
