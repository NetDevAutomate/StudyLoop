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
      Alpine.store('nav').go(this._viewFor(rec.action_type));
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
