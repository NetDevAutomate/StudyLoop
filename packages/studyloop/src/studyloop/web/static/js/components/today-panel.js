/* ------------------------------------------------------------------
 * Today panel — "one next action" landing view (AuDHD-first).
 *
 * Fetches all of its sources in parallel and renders exactly ONE primary
 * recommendation (from the shared decision engine via /api/now), a
 * context-aware resume shortcut, parked-topic pickup chips, and at most one
 * Second Brain launcher action from prefetched /api/second-brain/launch-target
 * state (navigation happens ONLY inside openBrain(), on an explicit click).
 * Resume precedence: live session (rejoin) > last study session
 * (start-again-same-topic) > last review deck.
 *
 * Moved verbatim from the legacy components.js monolith so the factory
 * is importable under `node --test` (same seam as plans-panel.js).
 * `Alpine` and `window` are read as FREE identifiers inside methods only,
 * so constructing the object needs neither.
 * ------------------------------------------------------------------ */

export function todayPanel() {
  return {
    loading: true,
    plan: null,          // /api/now NowPlan
    parked: [],          // /api/backlog parking_lot
    resumeKind: null,    // 'rejoin' | 'session' | 'deck' | null
    resumeLabel: '',
    _resumePayload: null,
    showAlternates: false,
    launchTarget: null,  // /api/second-brain/launch-target (prefetched, never navigated)

    /* The Today surface renders AT MOST one launcher action: only for a
       selected provider, never for `none` and never before state arrives. */
    get hasBrainAction() {
      return !!this.launchTarget && this.launchTarget.provider !== 'none';
    },

    /* One explicit gesture → one navigation, from PREFETCHED state only: a
       synchronous window.open is what keeps the new tab out of popup-blocker
       territory, and `noopener,noreferrer` is what keeps it protected. */
    openBrain() {
      const target = this.launchTarget;
      if (!target || !target.enabled || !target.href) return;
      if (target.provider === 'xtiles') {
        window.open(target.href, '_blank', 'noopener,noreferrer');
      } else {
        /* A custom URI (obsidian://…) belongs to the CURRENT context: a new
           tab would stay behind as an empty window after the OS handoff. */
        window.location.assign(target.href);
      }
    },

    async init() {
      const get = (url) => fetch(url).then((r) => (r.ok ? r.json() : null)).catch(() => null);
      const [plan, backlog, state, last, history, launchTarget] = await Promise.all([
        get('/api/now'),
        get('/api/backlog'),
        get('/api/session/state'),
        get('/api/session/last'),
        get('/api/history'),
        get('/api/second-brain/launch-target'),
      ]);

      this.plan = plan;
      this.parked = (backlog && backlog.parking_lot) || [];
      this.launchTarget = launchTarget;

      if (state && state.study_session_id && state.mode !== 'ended') {
        this.resumeKind = 'rejoin';
        this.resumeLabel = state.topic_config_name || state.topic || 'active session';
      } else if (last && last.topic) {
        this.resumeKind = 'session';
        this.resumeLabel = last.topic;
        this._resumePayload = last;
      } else if (Array.isArray(history) && history.length > 0) {
        this.resumeKind = 'deck';
        this.resumeLabel = history[0].course;
      }

      this.loading = false;
    },

    resumeAction() {
      if (this.resumeKind === 'rejoin') {
        Alpine.store('nav').go('study-session');
      } else if (this.resumeKind === 'session') {
        // Hand the topic to the study-session picker (start-again-same-topic).
        // sessionTimer.init() already ran at page load, so this is an event.
        window.dispatchEvent(new CustomEvent('today-resume', {
          detail: {
            topic: this._resumePayload.topic,
            energy: this._resumePayload.energy_level || null,
          },
        }));
        Alpine.store('nav').go('study-session');
      } else if (this.resumeKind === 'deck') {
        Alpine.store('nav').go('flashcards');
      }
    },

    // Map the decision engine's action_type to the view that hosts it.
    _viewFor(actionType) {
      const map = {
        review: 'flashcards',
        recall: 'flashcards',
        quiz: 'quizzes',
        conversation: 'study-session',
        teach_back: 'study-session',
        generate: 'generate',
        'hands-on': 'study-session',
      };
      return map[actionType] || 'flashcards';
    },

    startPrimary() {
      if (this.plan && this.plan.primary) this.startAction(this.plan.primary);
    },

    startAction(rec) {
      const view = this.viewForAction(rec);
      if (view === 'body-double') {
        /* Carry the proposal's context to the Body Double view (council review
           7, F7): the same event-not-storage handoff `today-resume` uses, so
           the picker opens on the plan the engine named instead of blank. The
           view starts nothing on its own; the learner still presses start. */
        const detail = { activity: this.bodyDoubleActivity(rec), energy: this.plan && this.plan.energy };
        /* Issue #30: the engine's one passive first move rides along when there is
           one, so the picker opens on something to open — additive; a payload
           without it hands over exactly what it did before. Rubric 3c (d2): the
           lesson the move names, when the engine resolved one, rides beside it. */
        Object.assign(detail, this._firstMoveDetail(rec));
        window.dispatchEvent(new CustomEvent('body-double-request', { detail }));
      } else if (view === 'study-session') {
        /* Rubric 3c (e2): Start used to navigate and hand the Study picker
           NOTHING — not the (e1) warm-up, not even the concept — so the learner
           retyped the topic from memory and the sentence the card had just
           shown was thrown away. Same event the resume and parked paths use
           (`today-resume`, event-not-storage), so the picker opens on the
           action the engine named, with its move beside it when there is one.
           The view starts nothing on its own; the learner still presses Start. */
        const detail = { topic: rec.concept || '', energy: (this.plan && this.plan.energy) || null };
        Object.assign(detail, this._firstMoveDetail(rec));
        window.dispatchEvent(new CustomEvent('today-resume', { detail }));
      }
      Alpine.store('nav').go(view);
    },

    /* The first move's share of a hand-off: the sentence and, when the engine
       resolved a lesson, its id and title — additive, so a recommendation
       without a move hands over exactly what it did before. One definition for
       both session views. */
    _firstMoveDetail(rec) {
      const detail = {};
      const firstMove = this.firstMoveNote(rec);
      if (firstMove) detail.firstMove = firstMove;
      const lesson = this.firstMoveLesson(rec);
      if (lesson) {
        detail.firstMoveLessonId = lesson.id;
        detail.firstMoveLessonTitle = lesson.title;
      }
      return detail;
    },

    /* What a body-double proposal asks the learner to sit with: the named
       plan's title, or the proposal's own concept when the payload lists no
       plan for it. */
    bodyDoubleActivity(rec) {
      const planId = rec && rec.metadata && rec.metadata.plan_id;
      const plan = planId ? this._activePlan(planId) : null;
      return (plan && plan.title) || (rec && rec.concept) || '';
    },

    /* Issue #30: the engine's one tiny, passive first move, verbatim from
       `metadata.first_move`; '' for a payload that carries none. Nothing here
       re-derives it — the sentence is the engine's, so the CLI and the card
       agree. Rubric 3c (e1)/(e2): the engine puts a move on the body-double
       proposal AND, as a warm-up, on a plan-related active primary, so the card
       reads the field wherever the engine put it and never second-guesses the
       source (the body-double gate that used to sit here hid the warm-up). */
    firstMoveNote(rec) {
      const move = rec && rec.metadata && rec.metadata.first_move;
      return move ? String(move) : '';
    },

    /* Rubric 3c (d2): the indexed lesson the first move names, when the engine
       resolved one — `{ id, title }` from `metadata.first_move_lesson_id` and
       `_title`; null for a milestone-form move or no payload. The sentence has
       already stated the lesson's evidence (its course and the word the match
       rests on), so what this opens is what the learner judged. */
    firstMoveLesson(rec) {
      if (!rec || !rec.metadata) return null;
      const id = rec.metadata.first_move_lesson_id;
      if (!id) return null;
      return { id: String(id), title: String(rec.metadata.first_move_lesson_title || '') };
    },

    /* "Open X" actually opens X: asks the Course Explorer aside to open the
       lesson beside this view. No navigation — the learner stays on Today with
       the lesson open next to it. Nothing to open, nothing dispatched. */
    openFirstMoveLesson() {
      const lesson = this.firstMoveLesson(this.plan && this.plan.primary);
      if (!lesson) return;
      window.dispatchEvent(new CustomEvent('explorer-open-lesson', {
        detail: { lessonId: lesson.id, title: lesson.title },
      }));
    },

    /* The view an action starts in. A body-double proposal (design §5) is a
       session in the Body Double view, whatever its action_type says; every
       other action keeps the action_type mapping above. */
    viewForAction(rec) {
      if (rec && rec.source === 'body_double') return 'body-double';
      return this._viewFor(rec && rec.action_type);
    },

    /* ---- Plan relevance (issue #10) — rendering of what /api/now ranked. ----
       The engine attaches `plan_refs` to an action and lists `active_plans`,
       `energy_deferred` and `completion_actions` beside it, each key present
       only when non-empty. These helpers turn that into text; none of them
       changes which action is primary. A payload without the keys — the shape
       a learner with no active plan gets — yields empty strings and lists. */

    _activePlan(planId) {
      const plans = (this.plan && this.plan.active_plans) || [];
      return plans.find((p) => p.plan_id === planId) || null;
    },

    /* "SQL Windows · milestone 2: Frames; Other Plan" — every referenced plan,
       in the engine's order; the milestone is named when the ref points at
       the plan's next milestone. A ref to a plan the payload does not list
       falls back to its id rather than throwing mid-render. */
    planLabel(rec) {
      const refs = (rec && rec.plan_refs) || [];
      return refs
        .map((ref) => {
          const plan = this._activePlan(ref.plan_id);
          let label = plan ? plan.title : ref.plan_id;
          if (
            ref.milestone_index != null &&
            plan &&
            plan.next_milestone_index === ref.milestone_index &&
            plan.next_milestone
          ) {
            label += ` \u00b7 milestone ${ref.milestone_index + 1}: ${plan.next_milestone}`;
          }
          return label;
        })
        .join('; ');
    },

    deferredNotes() {
      const deferred = (this.plan && this.plan.energy_deferred) || [];
      const energy = (this.plan && this.plan.energy) || 'current';
      return deferred.map(
        (d) =>
          `${d.plan_title} \u2014 \u201c${d.title}\u201d waits for more energy `
          + `(needs ${d.energy_floor}/10, ${energy} energy carries ${d.energy_capability}/10)`,
      );
    },

    /* One line per struggle repair today's energy cannot carry (design §5,
       amendment 2): its own key, its own sentence — a repair has no milestone
       number. A repair unrelated to any plan names none. */
    deferredRepairNotes() {
      const repairs = (this.plan && this.plan.energy_deferred_repairs) || [];
      const energy = (this.plan && this.plan.energy) || 'current';
      return repairs.map((r) => {
        const head = r.plan_title
          ? `${r.plan_title} \u2014 repairing`
          : 'Repairing';
        return `${head} \u201c${r.concept}\u201d (${r.confidence}) waits for more energy `
          + `(asks for ${r.required_capability}/10, ${energy} energy carries ${r.energy_capability}/10)`;
      });
    },

    /* One block per finished plan (council review 6, F6): the closing review's
       sentence and ITS evidence lines, keyed by plan_id, in the engine's order.
       With two finished plans a flat list of lines lost the plan each belonged
       to; the card renders these blocks instead. A pre-D-G entry without
       `evidence` has none; a failed assessment (`proposal` null) carries none by
       construction; a partial one (F1) carries its `Not read:` lines. */
    completionReviews() {
      const actions = (this.plan && this.plan.completion_actions) || [];
      return actions.map((a) => ({
        planId: String(a.plan_id),
        sentence: a.action,
        evidence: (Array.isArray(a.evidence) ? a.evidence : []).map(String),
      }));
    },

    completionNotes() {
      return this.completionReviews().map((r) => r.sentence);
    },

    /* The closing review's evidence (D-G, item 4), flattened across every
       completion action in the engine's order — kept for callers that want
       the lines alone; the card itself renders completionReviews(). */
    completionEvidence() {
      return this.completionReviews().flatMap((r) => r.evidence);
    },

    /* The engine's warnings, verbatim: an active plan that is not ready (its
       blockers, "pause or repair"), a document that could not be read. Data
       the CLI and the JSON already show; the card shows it too. */
    warningNotes() {
      return ((this.plan && this.plan.warnings) || []).map((w) => String(w));
    },

    /* The notes block's label. "Your plans" once any note involves a plan; a
       learner with no plan whose live struggle was deferred (design §5
       decision 1) has no plan to be told about — the block is what today set
       aside (council review 7, grok). */
    planNotesLabel() {
      const plans = (this.plan && this.plan.active_plans) || [];
      const repairs = (this.plan && this.plan.energy_deferred_repairs) || [];
      const planInvolved = plans.length > 0
        || this.deferredNotes().length > 0
        || this.completionNotes().length > 0
        || repairs.some((r) => r.plan_id);
      return planInvolved ? 'Your plans' : 'Set aside today';
    },

    get hasPlanContext() {
      return (
        this.planLabel(this.plan && this.plan.primary) !== ''
        || this.deferredNotes().length > 0
        || this.deferredRepairNotes().length > 0
        || this.completionNotes().length > 0
        || this.warningNotes().length > 0
      );
    },

    pickUpParked(p) {
      window.dispatchEvent(new CustomEvent('today-resume', {
        detail: { topic: p.question, energy: null },
      }));
      Alpine.store('nav').go('study-session');
    },

    async dismissParked(p) {
      const idx = this.parked.indexOf(p);
      if (idx !== -1) this.parked.splice(idx, 1);
      try {
        const res = await fetch('/api/backlog/dismiss', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ id: p.id }),
        });
        if (!res.ok) {
          this.parked.splice(idx, 0, p);
          Alpine.store('toast').show('Could not dismiss — try again');
        }
      } catch {
        this.parked.splice(idx, 0, p);
        Alpine.store('toast').show('Could not dismiss — offline?');
      }
    },
  };
}
