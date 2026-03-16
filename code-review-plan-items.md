# Implementation Plan Review -- Kieran

Reviewed against the actual codebase. Organised by severity.

---

## CRITICAL -- Must fix before or during implementation

### A5: get_due_cards() -- the SQL is wrong in a subtle way

The plan correctly identifies the bug (HAVING with non-deterministic GROUP BY), and proposes ROW_NUMBER(). Good call. However, there is a deeper issue in `review_db.py` that the plan should address while it is open:

**Connection leak on exceptions.** Every function in `review_db.py` follows this pattern:

```python
conn = sqlite3.connect(path)
# ... queries ...
conn.close()
```

If any query raises, `conn.close()` is never called. The existing `history.py` already uses `try/finally` consistently. The fix for A5 should adopt context managers:

```python
def get_due_cards(course: str, db_path: Path | None = None) -> list[CardProgress]:
    path = db_path or _get_db()
    if not path.exists():
        return []
    ensure_tables(path)
    with sqlite3.connect(path) as conn:
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        rows = conn.execute("""
            WITH latest AS (
                SELECT *, ROW_NUMBER() OVER (
                    PARTITION BY card_hash ORDER BY reviewed_at DESC
                ) AS rn,
                COUNT(*) OVER (PARTITION BY card_hash) AS review_count
                FROM card_reviews
                WHERE course = ?
            )
            SELECT card_hash, correct, ease_factor, interval_days,
                   next_review, review_count
            FROM latest
            WHERE rn = 1 AND next_review <= ?
            ORDER BY next_review ASC
        """, (course, today)).fetchall()
    # conn auto-closed by context manager
    return [CardProgress(...) for r in rows]
```

This also eliminates the redundant inner subquery that passes `course` twice.

**Verdict: FAIL as planned.** Refactor all `review_db.py` functions to use `with sqlite3.connect(...) as conn:` while you are in this file. Do not leave connection leaks behind.

---

### A6: Narrow suppress(Exception) -- correct direction, incomplete scope

The plan says replace `contextlib.suppress(Exception)` at lines 218 and 263 of `study_cards.py` with `try/except sqlite3.Error`. Confirmed in the codebase -- both call `record_card_review()` and `record_session()` from `review_db.py`.

However, `review_db` functions can also raise `OSError` (file permissions on the DB) and `ValueError` (if `_get_db()` config is malformed). The catch should be:

```python
try:
    record_card_review(...)
except (sqlite3.Error, OSError) as exc:
    logger.debug("Failed to record card review: %s", exc)
```

Do NOT catch `ValueError` -- that indicates a configuration bug and should propagate.

Also: the `_speak` method at the bottom of the file has `except Exception: pass` -- the plan does not mention this. It should be narrowed to `except ImportError` (kokoro not installed) at minimum. Flag it.

**Verdict: PASS with amendments.** Catch `(sqlite3.Error, OSError)`, not just `sqlite3.Error`. Address the `_speak` exception too.

---

## IMPORTANT -- Design concerns

### A1: Fix export progress bar

The diagnosis is correct: `batch_stats.added` is cumulative, but the progress description reads as per-source. The proposed fix (capture per-source values before accumulating) is sound.

However, `ExportStats` already has `__iadd__` defined in `exporters/base.py`. The fix should use it instead of the current `isinstance` branch:

```python
# Normalise source_stats to ExportStats
if source_stats and not isinstance(source_stats, ExportStats):
    source_stats = ExportStats(**source_stats)

if source_stats:
    source_added = source_stats.added  # capture BEFORE accumulation
    source_updated = source_stats.updated
    batch_stats += source_stats

if progress and task is not None:
    progress.update(
        task,
        description=f"{source.title()}: +{source_added} added, +{source_updated} updated",
    )
```

This also eliminates the duplicated `dict` vs `object` branching entirely. The `isinstance` check with `dict`/`getattr` is a code smell -- it means exporters are returning inconsistent types. If any exporter returns a plain `dict`, fix the exporter to return `ExportStats` instead. That is the real bug.

**Verdict: PASS with amendments.** Use `__iadd__`, enforce `ExportStats` return type from all exporters, add `+` prefix to make per-source semantics obvious.

---

### A2: list_concepts() -- NamedTuple vs dataclass

The plan proposes a 3-field NamedTuple `(name, domain, description)`. The `concepts` table schema (from migration v12) has columns: `id, name, domain, description, created_at, updated_at`.

Observations:

1. **NamedTuple is fine here** -- this is read-only query result data. No mutation needed. Lighter than a dataclass and works natively with tuple unpacking in DataTable row population.

2. **Missing type annotations in the plan.** The return must be typed:

```python
class ConceptSummary(NamedTuple):
    name: str
    domain: str
    description: str | None

def list_concepts() -> list[ConceptSummary]:
```

3. **Include `id` in the NamedTuple.** The caller in `_populate_concepts` does not need it today, but concept relations (A2 is a stepping stone for the concept graph) will need the ID to link through. Adding it now avoids a breaking change later:

```python
class ConceptSummary(NamedTuple):
    id: str
    name: str
    domain: str
    description: str | None
```

4. **Use `conn.row_factory = sqlite3.Row`** to avoid positional indexing. The existing `history.py` already does this via `_connect()`.

**Verdict: PASS with amendments.** Include `id`, type the return, follow existing `_connect()` pattern.

---

### A3: Course picker -- hardcoded courses[0]

Confirmed: `_launch_study()` has `name, path = courses[0]` with a `# TODO: add course picker` comment.

Design concerns:

1. **OptionList is appropriate** for Textual. But the plan says "multi-directory selection" -- flashcard/quiz sessions are single-course. This should be single-select, not multi-select. Clarify the requirement.

2. **Async flow matters.** Textual requires pushing a screen or showing a modal for selection, then calling back to `_launch_study` with the chosen course. The plan should specify whether this is a `Screen` push or an inline widget swap. Given the existing pattern of replacing container children (see `_launch_study` mounting `StudyCardsTab`), a `ModalScreen` with `OptionList` is the Pythonic Textual approach.

3. **Type the callback.** The course tuple `(str, Path)` should be a NamedTuple or at minimum documented:

```python
class CourseInfo(NamedTuple):
    name: str
    path: Path
```

Then `discover_directories` returns `list[CourseInfo]` instead of `list[tuple[str, Path]]`.

**Verdict: PASS with amendments.** Clarify single-select, use ModalScreen, type the tuple.

---

### A4: Review Wrong Answers

The plan says "in-memory wrong_hashes from `self._result.wrong_hashes`" with 2 states and `_is_retry` boolean, no SM-2 during retry.

Confirmed: `ReviewResult.wrong_hashes` is `list[str]` populated in `_record_answer`. `get_wrong_hashes()` in `review_db.py` also exists for DB-persisted wrong answers.

Concerns:

1. **Boolean `_is_retry` is a state-tracking smell.** If you have 2 states (normal study, retry), consider an enum:

```python
class StudyMode(StrEnum):
    NORMAL = "normal"
    RETRY = "retry"
```

This is explicit, extensible (you might add `REVIEW_DUE` later), and makes conditionals readable: `if self._mode is StudyMode.RETRY` vs `if self._is_retry`.

2. **"No SM-2 during retry" must be enforced at the call site.** The current `_record_answer` unconditionally calls `record_card_review()`. The plan must specify WHERE the SM-2 skip happens -- inside `_record_answer` (check mode), or by not calling it at all during retry. The former is cleaner:

```python
if self._study_mode is not StudyMode.RETRY:
    record_card_review(...)
```

3. **Filtering cards by hash.** If using in-memory `wrong_hashes`, use a `set` not a `list` for O(1) lookups. `ReviewResult.wrong_hashes` is currently `list[str]` -- either change it to `set[str]` or convert at the point of use.

**Verdict: PASS with amendments.** Use StrEnum over boolean, enforce SM-2 skip explicitly, use set for hash lookups.

---

## MINOR -- Polish items

### General: review_db.py connection pattern

Every function in `review_db.py` does `sqlite3.connect()` / `conn.close()` manually. Meanwhile `history.py` uses a `_connect()` helper with `row_factory = sqlite3.Row` and `try/finally`. The review_db module should adopt the same pattern or, better, use context managers throughout. This is not just about A5 -- `record_card_review`, `record_session`, `get_wrong_hashes`, `get_course_stats` all have the same leak.

### ExportStats: use forward reference syntax

In `base.py`, `__iadd__` uses `"ExportStats"` string annotation. Since the file already imports `from __future__ import annotations`... wait, it does NOT. Add `from __future__ import annotations` to `base.py` so the string quote is unnecessary, or keep the string -- but be consistent with the rest of the codebase which uses the `from __future__` import.

### review_loader.py: Flashcard.card_hash truncation

`hashlib.sha256(...).hexdigest()[:16]` gives 16 hex chars = 64 bits. For a study app this is fine, but document WHY the truncation exists (display friendliness? DB space?) so future maintainers do not "fix" it to full length and break existing spaced repetition data.

---

## Summary table

| Item | Verdict | Key amendments |
|------|---------|----------------|
| A1 | PASS | Use `__iadd__`, enforce ExportStats return type, prefix with `+` |
| A2 | PASS | Include `id`, type the return, use `_connect()` pattern |
| A3 | PASS | Single-select not multi, use ModalScreen, type the tuple |
| A4 | PASS | StrEnum over boolean, enforce SM-2 skip location, set not list |
| A5 | FAIL | Connection leaks throughout review_db.py; refactor all functions |
| A6 | PASS | Catch `(sqlite3.Error, OSError)`, also fix `_speak` exception |

No SQL injection risks found -- all queries use parameterised `?` placeholders correctly. No f-string interpolation in SQL anywhere in the codebase.
