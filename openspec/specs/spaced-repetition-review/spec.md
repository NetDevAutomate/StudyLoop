## Purpose

Track flashcard/quiz review outcomes with an SM-2-derived spaced-repetition
schedule, backed by SQLite, and surface due cards to the CLI, web review
list, and MCP tools from a single service layer.

## Requirements

### Requirement: Review state lives in a dedicated review database module
The system SHALL persist card review history and computed scheduling
(`ease_factor`, `interval_days`, `next_review`) via
`review_db.py` (`card_reviews`, `review_sessions` tables), accessed
through the shared `services/review.py` layer
(`get_cards`, `record_review`, `get_stats`, `get_due`, `get_wrong`,
`list_course_summaries`) so CLI, web, and MCP surfaces read one
implementation.

#### Scenario: MCP tool and web review list both read due counts
- **WHEN** `get_study_context` (MCP) and the web review list both query the
  same course
- **THEN** both go through `services/review.get_due()` / `get_stats()`
  and see identical due-card counts — there is no separate MCP-only or
  web-only review query path

### Requirement: SM-2 interval update is deterministic and bounded
On a correct review, `record_card_review()` (`review_db.py`) SHALL compute
`interval = min(max(1, int(interval * ease)), 365)` and increase `ease` by
`0.1` capped at `3.0`. On an incorrect review it SHALL reset
`interval = 1` and decrease `ease` by `0.2` floored at `MIN_EASE`.

#### Scenario: Card answered correctly at ease 2.5, interval 4
- **WHEN** a card with `ease_factor=2.5`, `interval_days=4` is reviewed
  correctly
- **THEN** the new interval is `min(max(1, int(4 * 2.5)), 365) = 10` days
  and the new ease is `2.6`

### Requirement: "Mastered" is a windowed query over the latest review per card
`get_course_stats()` SHALL compute `mastered` as the count of distinct
`card_hash` values whose most recent review (via a `ROW_NUMBER() OVER
(PARTITION BY card_hash ORDER BY reviewed_at DESC)` window, not a
correlated subquery) has `interval_days > 30`.

#### Scenario: Large review history for one course
- **WHEN** a course has thousands of accumulated review rows
- **THEN** `mastered` count computation runs in one windowed query pass
  rather than one correlated subquery per card (an explicit perf choice
  documented in the source to avoid `O(cards^2)` degradation)

### Requirement: Course discovery walks nested publisher/course layouts
`review_loader.discover_directories()` SHALL walk both the flat
`content.base_path/<course>/` layout and the nested
`content.base_path/<publisher>/<course>/` layout up to a fixed recursion
depth, stopping recursion at the first deck-bearing directory found on a
branch.

#### Scenario: Publisher-scoped course from web generation
- **WHEN** the web Generate panel wrote decks to
  `content.base_path/acme-press/python-basics/flashcards/`
- **THEN** `discover_directories()` finds `python-basics` as a course under
  publisher `acme-press` without additional configuration
