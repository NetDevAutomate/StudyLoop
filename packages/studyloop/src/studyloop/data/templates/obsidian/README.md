# StudyLoop templates for Obsidian

Two note templates that mirror the sections StudyLoop's own study plans use, so a
plan you write by hand in your vault and a plan StudyLoop published look the same.

- **Study Plan.md** — mission, milestones, learning records, resources,
  checkpoints, notes. Exactly the sections a StudyLoop plan document has, in the
  same order.
- **Today.md** — next action, due reviews, active topics.
- **Due reviews (Dataview).md** — an optional query block. Needs the community
  Dataview plugin; skip it if you do not use Dataview.

## Two ways to use them

Copy this folder into your vault's own templates folder, or run:

```bash
studyloop brain template --install
```

That copies the templates into `<your templates folder>/StudyLoop/` and refuses
to overwrite anything already there.

## These templates are yours; StudyLoop's published notes are not

A note you create from a template belongs to you. StudyLoop never touches it.

Notes StudyLoop *publishes* — under `Study/` by default — carry a `studyloop:`
marker in their frontmatter, and StudyLoop regenerates those from your plan
document whenever you publish. If you edit one, your edit is replaced next time.
Keep your own thinking about a plan in the sibling file StudyLoop never writes:
`Study/Plans/<plan-id>.notes.md`. `studyloop brain pull <plan-id>` reads it back
to you when you ask.

The templates deliberately carry no `studyloop:` marker, which is what makes that
distinction mechanical rather than a convention someone has to remember.

## Other second brains

The xTiles template follows the same section shape. See the Second Brain guide
(`docs/second-brain.md`) for the whole picture, including exactly what leaves your
machine for each option.
