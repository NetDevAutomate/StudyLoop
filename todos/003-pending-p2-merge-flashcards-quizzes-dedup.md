---
status: pending
priority: p2
issue_id: "003"
tags: [code-review, architecture, alpine, deduplication]
dependencies: ["001"]
---

# Merge Flashcards + Quizzes Into Single reviewApp Instance

## Problem Statement

The flashcards view (index.html lines 115-352) and quizzes view (lines 357-536) share ~90% identical HTML. Both use the same `reviewApp()` component factory with different default modes. The courses grid, config panel, study view (card player), and summary view are all duplicated — ~300 lines of redundant HTML.

## Findings

- Both views call `x-data="reviewApp('flashcards')"` and `x-data="reviewApp('quiz')"` — same factory
- The only differences: quizzes tab shows Quiz button first in course cards, flashcards tab shows Flashcard button first
- Config, study, and summary subviews are character-for-character identical
- The JS logic is already DRY — only the HTML templates are duplicated

## Proposed Solutions

### Solution 1: Single reviewApp instance with nav-driven mode (RECOMMENDED)
- One `<div x-data="reviewApp($store.nav.current)">` visible for both flashcards and quizzes tabs
- Use `$watch` on `$store.nav.current` to switch mode when tab changes
- Keep both sidebar tabs as navigation shortcuts
- **Pros**: Eliminates ~300 lines, single source of truth, zero logic change
- **Cons**: Both tabs share one component instance (state resets on tab switch)
- **Effort**: Medium (1-2 hours)
- **Risk**: Low — no logic changes, purely structural

### Solution 2: HTML `<template>` reuse
- Extract shared subviews into `<template id="...">` elements, clone into both views
- **Pros**: Views stay independent
- **Cons**: Alpine directives don't work inside `x-html` injected content; fragile
- **Effort**: Medium
- **Risk**: Medium — Alpine compatibility concern

## Recommended Action

Solution 1. The quizzes "tab" becomes a nav shortcut that pre-selects quiz mode in the shared reviewApp.

## Technical Details

- **Affected files**: `packages/studyctl/src/studyctl/web/static/index.html`
- **Components**: reviewApp(), nav store
- **Lines removed**: ~300

## Acceptance Criteria

- [ ] Single reviewApp instance renders for both flashcards and quizzes tabs
- [ ] Switching to quizzes tab shows quiz-mode course cards
- [ ] Switching to flashcards tab shows flashcard-mode course cards
- [ ] All existing review/quiz functionality preserved
- [ ] index.html reduced by ~250-300 lines

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
| 2026-04-07 | Identified by architecture + Alpine research agents | Alpine doesn't have template includes; single-instance with mode switching is the idiomatic pattern |

## Resources

- Alpine sidebar plan: `docs/plans/2026-04-05-web-ui-alpine-sidebar-plan.md`
