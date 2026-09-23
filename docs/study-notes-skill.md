# Lesson study notes

`studyloop-study-notes` creates one Markdown note per lesson and a linked section
overview. It preserves the seven-part structure of StudyLoop's comprehensive
study notes while keeping prerequisites, examples, and retrieval exercises
focused on one lesson. It supports Obsidian only, xTiles only, both destinations,
or portable Markdown.

The distributable package is `skills/studyloop-study-notes/`. It contains a
standard `SKILL.md`, two Markdown templates, and references for attribution,
updates, Obsidian, and xTiles presentation. It has no runtime dependency on StudyLoop.

## Use locally

From this repository:

```sh
npx skills add ./skills/studyloop-study-notes --list
npx skills add ./skills/studyloop-study-notes --agent codex
```

Then ask the agent, for example:

> Use studyloop-study-notes to turn these lesson transcripts into one note per
> lesson and a section overview. Save Markdown in my selected study-notes folder
> and create the corresponding pages in my existing xTiles study project.

The user supplies source paths and destinations. For a template-only request,
ask for a lesson template and section-overview template. For a pilot, name the
single lesson to generate. Other known lessons remain listed as not generated.

## Destination examples

- **Obsidian only:** "Use studyloop-study-notes with these transcripts and save
  lesson notes and an overview in this folder of my Obsidian vault."
- **xTiles only:** "Use studyloop-study-notes to create a lesson page and section
  overview in my existing xTiles study project. I do not use Obsidian."
- **Both:** "Use studyloop-study-notes to save full notes in my Obsidian vault and
  create linked xTiles pages for the same lessons."

Obsidian uses normal vault files with properties, native internal links where
appropriate, code fences, and Mermaid. xTiles uses pages/tiles with source IDs
and an adapted presentation. Both mode adds reciprocal links after the actual
paths and page IDs exist. A failed destination is reported separately so a
successful output is not lost or represented as complete in both apps.

## Boundaries

- An xTiles page containing a template layout is not automatically saved in
  **My Templates**. Gallery registration requires **Save as Template** in the
  page tab's three-dot menu; the current MCP toolset does not expose that action.
  Report prepared pages and saved gallery templates as separate delivery steps.
- Local installation and validation do not publish a skill to skills.sh. Once
  this package is in an accessible repository, the skills CLI can install it
  from that source. Public publication is a separate step.
- This package is installed through the skills CLI; it is not currently part
  of `studyloop install agents` or the agent asset manifest.
- This skill creates study material. The existing study-capture and wind-down
  workflows remain responsible for session records and review scheduling.
- Markdown retains code fences and Mermaid. The xTiles importer documents code
  formatting loss, so xTiles receives an adapted reading/retrieval page. When
  both destinations are selected, it links to the complete Obsidian note.
  xTiles-only output does not require a vault or invent a companion-note link.
  Local Obsidian links need the matching vault.
- Refreshing either output is an explicit agent action, not automatic two-way
  synchronisation. Learner annotations are preserved during updates.

See [the skill](https://github.com/NetDevAutomate/StudyLoop/blob/main/skills/studyloop-study-notes/SKILL.md)
for the workflow.
