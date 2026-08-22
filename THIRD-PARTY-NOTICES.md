# Third-Party Notices

StudyLoop is MIT licensed (see `LICENSE`). This file records third-party work that
influenced or is included in it, and the terms that work carries.

---

## Matt Pocock — `skills`

**Source:** <https://github.com/mattpocock/skills>
**Licence:** MIT — Copyright (c) 2026 Matt Pocock

### What StudyLoop takes

The **study-plan document shape** is adapted from the `teach` skill
(<https://github.com/mattpocock/skills/tree/main/skills/productivity/teach>).
Three of its ideas shaped StudyLoop's `planning` package:

- **Mission first** — a plan opens with why the learner is doing this, and every
  milestone is justified against that mission rather than against a syllabus.
- **Learning records as ADRs** — what was learned is captured as a dated,
  append-only record with the reasoning attached, in the spirit of an
  architecture decision record, so a plan carries its own history.
- **Primary sources over recalled knowledge** — a plan cites the material it is
  built on and revisits it, rather than trusting what the agent remembers.

StudyLoop diverges deliberately: `teach` uses a multi-file workspace, whereas
StudyLoop collapses a plan into a single Markdown document so it renders as one
page in the web UI and stays diffable in git.

Inline credit also appears at the point of use, in
`agents/shared/study-plan-protocol.md`, `docs/study-plans.md`,
`packages/studyloop/src/studyloop/planning/__init__.py` and
`packages/studyloop/src/studyloop/planning/models.py`.

### What StudyLoop does not take

**No code and no text.** The borrowing above is conceptual — the ideas and the
document shape, independently implemented. This was verified rather than assumed:
an 8-word phrase comparison across 675 StudyLoop files against the `teach`,
`grilling`, `wait-what` and `loop-me` skills found no verbatim overlap in any of
them.

Because no copy or substantial portion of the original is present, MIT's notice
requirement is not triggered by the current state of this repository. This file
exists anyway, for two reasons: attribution for borrowed ideas is right whether or
not a licence compels it, and if any of that material is later adopted verbatim,
the notice it requires is already here rather than being remembered afterwards.

### Licence text

Reproduced so that the terms travel with this repository:

```
MIT License

Copyright (c) 2026 Matt Pocock

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

---

## Maintaining this file

Add an entry whenever third-party work is adopted, including when only an idea is
borrowed. If material is taken verbatim, reproduce its licence text as above and
say which files contain it — the point of this file is that someone can answer
"what is in here that isn't ours?" without reading the whole repository.
