<!-- verified_model: qwen3-coder -->
<!-- finish_reason: stop · 12.7s · usage: {"completion_tokens": 1107, "prompt_tokens": 24306, "total_tokens": 25413, "completion_tokens_details": {"reasoning_tokens": 0, "text_tokens": 1107}, "prompt_tokens_details": {"cached_tokens": 0, "text_tokens": 24306, "cache_write_tokens": 0, "cache_creation_tokens": 0}, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0} -->

## 1. Verdict

ACCEPT — the implementation correctly builds both the body-double and warm-up first moves as specified, with accurate lesson resolution and proper state carriage across views, satisfying all rubric requirements.

## 2. Findings

### 🔴 Defect: Incorrect no-lesson clause for non-milestone warm-ups
- **Location**: `packages/studyloop/src/studyloop/learning/decision.py:_first_move_sentence` lines 240-241
- **Issue**: The no-concept clause `"this milestone names no concept to look up yet"` is used for ALL warm-ups when `concepts` is empty, including repairs which aren't milestones
- **Impact**: Misleading message for repairs: `Open your "window function" material... — this milestone names no concept to look up yet.`
- **Fix**: Distinguish between milestone vs repair cases - use "this [material-type] names no concept..."
- **RED Test**: `test_the_warm_up_names_the_material_and_says_why_when_nothing_is_indexed` with repair having no concepts

### 🟡 Must-Fix: Recall exclusion by action type insufficient
- **Location**: `packages/studyloop/src/studyloop/learning/decision.py` lines 254, 304
- **Issue**: Excludes warm-ups only on action_type `recall` but retrieval tests can be any active type; should exclude by `_review_type_for` result
- **Impact**: Could suggest reading before active recall tasks that are actually retrieval tests
- **Fix**: Change condition to check if primary is a due review needing testing (`_review_type_for` returns non-empty)
- **RED Test**: Add test with `hands-on` action that's actually a scheduled retrieval test

### 🟡 Must-Fix: State lifetime inconsistency in Study view
- **Location**: `packages/studyloop/src/studyloop/web/static/js/components/session-timer.js` lines 298, 566
- **Issue**: `firstMove` fields cleared with `topicInput` on end but not on manual topic edit via `#topic-input`
- **Impact**: Stale first move can remain visible if learner retypes different topic
- **Fix**: Add `@input` handler on `#topic-input` to clear firstMove fields when topic changes
- **RED Test**: `test_today_resume_clears_stale_first_move_on_topic_change` (new)

### 🟡 Must-Fix: Planning launch missing firstMove clear
- **Location**: `packages/studyloop/src/studyloop/web/static/js/components/session-timer.js:startPlanning`
- **Issue**: `startPlanning()` clears topic/selected fields but not firstMove fields
- **Impact**: Architect interview could show stale first move from previous study action
- **Fix**: Add clearing of `this.firstMove*` fields in `startPlanning()`
- **RED Test**: `test_planning_launch_clears_first_move` (new)

### 🔵 Should-Fix: High-energy warm-up wording
- **Location**: `packages/studyloop/src/studyloop/learning/decision.py:_first_move_sentence`
- **Issue**: Warm-up says "then start the repair" even at high energy where learner likely doesn't need ramp
- **Impact**: May feel patronizing to capable learners seeing `10/10` energy with basic instruction
- **Fix**: Consider context-sensitive tail based on energy level or learner history
- **RED Test**: Not blocking - would require behavioral preference testing

### 🔵 Should-Fix: Potential markup shadowing
- **Location**: `packages/studyloop/src/studyloop/web/static/index.html` lines 2356-2366 and 2748-2759
- **Issue**: New `.study-first-move` and `.study-live-first-move` elements use global classes `.picker-hint`, `.bulk-btn`
- **Impact**: Risk of inheriting unwanted styles or breaking existing selectors relying on unique contexts
- **Fix**: Use scoped class names like `.study-first-move-hint` to avoid global collisions
- **RED Test**: Visual regression test covering all session picker states

### 💡 Note: Frozen clock leak acceptance
- **Issue**: Due collector reads wall clock instead of frozen time in tests (§0 facts)
- **Finding**: Acceptable as noted - recorded for separate fix in `history/progress.py` clock injection
- **Impact**: Test isolation issue - doesn't affect production behavior or correctness of this feature

## 3. Refutations

None - all claims in §0–§7 are consistent with code changes and test coverage shown.

## 4. Gate

1. **Fix incorrect no-lesson clause for non-milestone warm-ups**
   `test_the_warm_up_names_the_material_and_says_why_when_nothing_is_indexed`

2. **Improve recall exclusion to use _review_type_for check**
   Add new test: `test_recall_warmup_excluded_by_review_type`

3. **Clear firstMove state on Study topic input changes**
   `test_today_resume_clears_stale_first_move_on_topic_change`

4. **Clear firstMove state during planning launches**
   `test_planning_launch_clears_first_move`
