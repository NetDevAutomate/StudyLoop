# Hand-off prompt for in-flight worktrees (course-list rework landing on main)

Copy the block below into each active worktree agent (e.g. `course-explorer-panel`,
`browser-neural-tts`). It tells them what changed in the course-list rework that is
merging to `main`, so they rebase onto it instead of conflicting.

---

## PROMPT TO PASTE INTO EACH WORKTREE AGENT

> **Heads-up: a course-list rework is merging to `main` — rebase onto it before continuing, and adopt its new contract.**
>
> The branch `feat/settings-providers-panel` reworked the Flashcards/Quizzes review panels (commits `04266af`, `f576d53`, `373e6e6`) and is merging to `main`. It changed shared files you also touch. **Before you do more work: rebase/merge your worktree onto the latest `main` (post-merge), reinstall the tool, and update your code to the new contract below.** Do NOT keep building against the old course-card markup — it no longer exists.
>
> ### What changed (the contract you must build against)
>
> **1. API — `/api/courses` gained a `publisher` field.**
> `services/review.py::list_course_summaries` now returns, per course:
> `{name, publisher, flashcard_count, quiz_count, due_count, total_reviews, mastered}`.
> `publisher` = the course dir's parent folder name (e.g. `"CodeWithMosh"`). It is **display/grouping only** — `name` (the leaf dir) is STILL the identity key for `/api/cards/{course}`, `openConfig`, and the SM-2 review DB. Never key anything new on `publisher`.
>
> **2. Frontend — the old course-card grid is GONE.** In `web/static/index.html`, both the Flashcards and Quizzes `view==='courses'` blocks were replaced. These selectors **no longer exist** and any code/test using them will break:
> - `.courses` (the grid) — removed from the courses view
> - `.course-card` — removed
> - `.mode-buttons`, `.mode-btn`, `.mode-btn.flashcard`, `.mode-btn.quiz` — removed from the courses view
>
> The new markup per panel: a `.course-search-bar > .course-search-input`, then `x-for` over `groupedCourses` → `.course-group > .course-group-header` (collapsible) + `.course-group-body` → `x-for` over `group.courses` → `.course-row` containing one `.course-row-action.flashcard` OR `.course-row-action.quiz` (mode-specific), a `.course-row-name`, and a `.course-row-meta`.
>
> **Selector migration (apply to any of YOUR code/tests that touch these):**
> - `.course-card .mode-btn.flashcard` → `.course-row-action.flashcard`
> - `.course-card .mode-btn.quiz` → `.course-row-action.quiz`
> - `.course-card` (e.g. `has_text=` locators) → `.course-row`
>
> **3. Frontend — `reviewApp()` in `web/static/components.js` gained state + getters.** If you patched `reviewApp`, re-apply your changes on top of these (don't clobber them):
> - new state: `searchQuery: ''`, `collapsedGroups: new Set()`
> - new getters: `filteredCourses` (filters `courses` by the panel's `mode` then by `searchQuery`), `groupedCourses` (groups `filteredCourses` by `publisher` → `[{publisher, courses[]}]`)
> - new method: `toggleGroup(publisher)`
> - `goHome()` now also resets `searchQuery = ''`
> - **Behavioural change you must respect:** the Flashcards panel now shows ONLY decks with `flashcard_count > 0` and a single Flashcards action; the Quizzes panel shows ONLY `quiz_count > 0` decks with a Quiz action. The dual-button card is gone. If your feature assumed both buttons per card, update it.
>
> **4. CSS — `web/static/style.css`** gained `.course-search-bar/.course-search-input/.course-empty-search`, `.course-group*`, `.course-row*` rules (after the `.mode-btn` block). The old `.courses`/`.course-card`/`.mode-btn` rules still exist (used by config/study views) but are no longer used by the courses list — don't rely on them for the list.
>
> **5. Tests — geometry e2e exists.** `tests/test_web_course_list_scale_e2e.py` (port 18584) locks in mode-split + grouping + search + compact-row geometry. `tests/test_web_layout_regression.py` and `tests/test_web_review_flow.py` had their `.course-card`/`.mode-btn` selectors migrated. Pick **unique e2e ports** (sisters use 18570–18584) to avoid collisions.
>
> ### Operational rule (READ THIS — it caused real breakage)
> `uv tool install` installs ONE GLOBAL `studyloop` binary shared by every worktree and by the user's live server on **:8567**. When you run `uv tool install`, you OVERWRITE what :8567 serves and what other worktrees run. **Do not run `uv tool install` for the global tool.** For your own manual/e2e checks, install into YOUR worktree's editable venv only (`uv pip install -e packages/studyloop[web,...]` inside your worktree's `.venv`) and run on YOUR OWN port (NOT 8567 — the user owns that). If you must use the global tool, coordinate first.
>
> ### After rebasing
> 1. Resolve conflicts in `index.html`, `components.js`, `style.css`, `services/review.py` in favour of the new contract above, then re-apply your feature on top.
> 2. Run your tests AND `tests/test_web_course_list_scale_e2e.py` to confirm you didn't regress the list.
> 3. Confirm your feature still composes (e.g. a new nav panel coexists with the 6 existing nav items: flashcards, quizzes, generate, body-double, study-session, settings).

---

## Notes for the human (not part of the prompt)

- The course-list rework is on `feat/settings-providers-panel`, HEAD `373e6e6`, 3 commits: `04266af` (publisher field), `f576d53` (UI), `373e6e6` (tests).
- The `course-explorer-panel` worktree (a NEW "Courses" reading panel — separate feature) branched from `04266af` and has uncommitted WIP. After this merges to main it should rebase; its new `explorer.py` route + Courses nav item don't conflict with the review-list rework in intent, only in the shared `index.html`/`components.js`/`style.css` files.
- :8567 is currently locked to the review-list build (global tool reinstalled from the main checkout; competing worktree servers on :8601/:8771 stopped).
