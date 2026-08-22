/* ------------------------------------------------------------------
 * Session timer — the study-session start picker + live elapsed-time
 * timer with energy-adaptive break-nudge thresholds (from session.html).
 *
 * Alpine component factory. Drives the topic/vendor/course/lesson
 * start-picker, calls /api/session/start|end|state|options, then runs
 * a setInterval tick() that recomputes elapsed time and fires a
 * green→amber→red "phase" based on how long the session has run
 * relative to energy-adaptive thresholds.
 *
 * NOT self-contained: this factory references two identifiers defined
 * elsewhere in the original inline <script> block that were NOT moved
 * here (extraction scope excludes them by design):
 *   - `energyBand(energy)` — maps energy (0-10) to 'low' | 'medium' | 'high'.
 *     Already modularized at ../lib/chunk-text.js and exposed as
 *     `window.energyBand` by main.js.
 *   - `THRESHOLDS` — a module-level const (band -> {green, amber} minute
 *     thresholds) still living in the inline script at extraction time.
 * Both must be imported/wired by whatever assembles this module into
 * the page; this file only calls them by name.
 *
 * Non-obvious invariants noticed while reading:
 *   - `checkThresholds()` is a ratchet, not a level check: `_shownAmber`
 *     and `_shownRed` are set once and never cleared except by
 *     `resetTimer()`. Crossing the amber boundary a second time (e.g.
 *     after `togglePause()` un-pauses) will NOT re-fire the amber
 *     message.
 *   - `togglePause()` implements pause by shifting `startTime` forward
 *     by the paused duration on resume, rather than accumulating a
 *     separate paused-elapsed counter. `elapsed` is therefore always
 *     `now - startTime` while running, never a stored/incremented value.
 *   - `progress` and `timerPhase` both key off `th.amber` as the 100%
 *     mark — there is no upper bound beyond amber; `progress` clamps
 *     at 100 via `Math.min`, so time spent at/after the red phase reads
 *     as a flat 100% progress bar, not a display bug.
 *   - `resetTimer()` clears `_shownAmber`/`_shownRed` but `startSession()`
 *     never explicitly initializes them — they are relied upon to be
 *     `undefined` (falsy) on the object returned by the factory, since
 *     no property of that name is declared in the initial state block.
 *   - `sessionActive` means "a session exists AND THIS VIEW OWNS IT", not
 *     merely "a session exists". A live session whose `origin` is another
 *     surface's leaves it false and populates `conflictSession` instead, so
 *     the picker stays up with a recovery block rather than adopting a PTY
 *     another console is already attached to.
 * ------------------------------------------------------------------ */

/* This view's own origin. A live session whose origin differs is NOT ours to
   adopt: the guard exists so two consoles never attach to one PTY. */
const OWN_ORIGIN = 'study';

/* Origin -> the surface's human name, used verbatim in the picker's error text
   so the learner is told WHICH view holds the session rather than being left
   to guess (and to keep clicking a Start that can only 409). */
const CONFLICT_OWNER_LABELS = {
  study: 'Study Session',
  'body-double': 'Body Double',
};

/* Origin -> the nav route that shows that surface. */
const CONFLICT_OWNER_ROUTES = {
  study: 'study-session',
  'body-double': 'body-double',
};

export function sessionTimer() {
    return {
      // Timer state
      startTime: null,
      energy: 5,
      topic: 'Loading...',
      elapsed: 0,
      interval: null,
      message: '',
      messageTimeout: null,
      sessionActive: false,
      confirmingEnd: false,
      // Park-first friction modal (3-topic rule)
      confirmingParkFirst: false,
      parkFirstTopics: [],
      _parkFirstChecked: false,
      paused: false,
      pausedAt: 0,

      // Start-picker state
      topics: [],
      selectedTopic: '',
      selectedVendor: '',
      selectedCourse: '',
      selectedLesson: '',
      topicInput: '',
      selectedOption: null,
      sessionType: 'study',
      targetKind: 'topic',
      agent: '',
      transport: 'pty',
      studyOptions: { topics: [], vendors: [], courses: [], lessons: [] },
      starting: false,
      startError: '',

      /* Recovery state for a live session this view does not own — or for one
         that 409'd our own Start. `sessionActive` means "a session exists AND
         THIS VIEW OWNS IT"; a foreign session therefore leaves it false, the
         picker stays up, and these fields give that picker its levers:
           conflictSession    the blocking session (normalised, see
                              _conflictPayload) or null when there is none
           conflictOwnerLabel the owning surface's name ('Body Double')
           conflictIsOwn      true when the blocking session's origin is OURS,
                              i.e. the only case where reattach is offerable
         `confirmingEnd` (declared with the timer state above) doubles as the
         end-dialog flag for the recovery End, so there is one dialog, not two. */
      conflictSession: null,
      conflictOwnerLabel: '',
      conflictIsOwn: false,
      /* Monotonic, mirroring reviewApp's _liveSessionEpoch: bumped whenever the
         user acts on the conflict, so an /api/session/state response that was
         already in flight cannot overwrite the newer state. */
      _conflictEpoch: 0,

      energyBandLabel() {
        if (this.energy >= 7) return 'High energy';
        if (this.energy >= 4) return 'Medium energy';
        return 'Low energy';
      },

      async init() {
        // Today-panel resume handoff. init() runs ONCE at page load (x-init),
        // while the resume click happens LATER on the Today tab — so this is
        // an event, not a sessionStorage read at init time.
        window.addEventListener('today-resume', (e) => {
          this.topicInput = e.detail.topic || '';
          this.selectedTopic = '';
          if (e.detail.energy) {
            const bands = { low: 3, medium: 5, high: 8 };
            this.energy = bands[e.detail.energy] || 5;
          }
        });

        const optionsPromise = fetch('/api/session/options')
          .then((res) => res.ok ? res.json() : null)
          .catch(() => null);
        const statePromise = fetch('/api/session/state')
          .then((res) => res.ok ? res.json() : {})
          .catch(() => ({}));

        try {
          const options = await optionsPromise;
          if (options) {
            this.studyOptions = options;
            this.topics = options.topics || [];
            /* Same renderer descriptor the Body Double view reads. Hydrated here
               too so this picker's pty label names what will ACTUALLY paint —
               otherwise it names the stock renderer while a --dev engine is painting,
               which is the exact mislabelling --dev used to cause. */
            Alpine.store('terminalEngine').hydrate(options.terminal_engine);
          }
          // Pre-select the first detected-available agent so the user
          // sees an explicit choice rather than the previous "Auto"
          // default that silently fell back to Claude.
          if (!this.agent) {
            const firstAvailable = (this.studyOptions.agents || []).find((a) => a.available);
            if (firstAvailable) this.agent = firstAvailable.value;
          }
        } catch { /* enhanced picker unavailable — free-text still works */ }

        try {
          const state = await statePromise;
          const live = !!state.study_session_id && state.mode !== 'ended';
          /* An ABSENT origin means 'study': /api/session/state applies exactly
             that default server-side (setdefault), so the two must not diverge
             here or a legacy session would read as foreign to its own view. */
          const origin = (live && state.origin) || OWN_ORIGIN;
          if (live && origin === OWN_ORIGIN) {
            this.energy = state.energy || 5;
            this.topic = state.topic || 'Study Session';
            this.startTime = state.start_time
              ? new Date(state.start_time)
              : (state.started_at ? new Date(state.started_at) : new Date());
            this.sessionActive = true;
            this.tick();
            this.interval = setInterval(() => this.tick(), 1000);
          } else if (live) {
            /* Foreign origin — refuse to adopt (that guard is why two consoles
               never share a PTY) and do NOT set sessionActive, so the picker
               renders. But a picker in this state can ONLY 409, so name the
               owning surface and offer both levers up front rather than after
               the learner has been refused by a Start they had no reason to
               expect would fail. */
            this._setConflict(this._conflictPayload(state), origin);
            this.startError = this._foreignConflictMessage(this.conflictSession);
            this.topic = 'No active session';
          } else {
            this.topic = 'No active session';
          }
        } catch {
          this.topic = 'Could not load session';
        }
      },

      async startSession() {
        const topic = this.resolvedTopic().trim();
        if (!topic) return;

        // Park-first friction (AuDHD 3-topic rule): starting a NEW topic
        // while MAX_ACTIVE_TOPICS are already live requires parking one
        // first. In-page overlay — native dialogs are banned by spec.
        if (!this._parkFirstChecked) {
          try {
            const bl = await fetch('/api/backlog').then((r) => r.ok ? r.json() : null);
            if (bl && bl.active_count >= bl.max_active) {
              const isActive = (bl.active || []).some(
                (t) => (t.question || '').toLowerCase() === topic.toLowerCase());
              if (!isActive) {
                this.parkFirstTopics = bl.active;
                this.confirmingParkFirst = true;
                return;
              }
            }
          } catch { /* backlog unavailable — don't block starting */ }
        }
        this._parkFirstChecked = false;

        this.starting = true;
        this.startError = '';
        let startedSession = null;
        try {
          const res = await fetch('/api/session/start', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              topic,
              energy: this.energy,
              agent: this.agent,
              transport: this.transport,
              /* Stated, not inferred. The server defaults a missing origin to
                 'study', but the Body Double twin sends its own origin
                 explicitly and ownership is now load-bearing on both sides. */
              origin: OWN_ORIGIN,
            }),
          });
          /* Parse defensively: a 500 with an HTML/plain body must NOT masquerade
             as a network error. Read text, then try JSON — a non-JSON body on a
             failed response is a real server error, surfaced with its status. */
          const raw = await res.text();
          let data = {};
          try { data = raw ? JSON.parse(raw) : {}; } catch { data = {}; }
          if (!res.ok) {
            /* 409 — the slot is held. The body has carried the blocking
               session's id and reattach_url since the WS grace window landed;
               nothing ever consumed them, which is precisely what turned this
               refusal into a dead end. Consume them now. */
            if (res.status === 409 && data.study_session_id) {
              /* Origin resolution, in priority order:
                 1. a conflict we ALREADY hold for this same session id knows
                    the real origin (init() read it from /session/state);
                 2. otherwise assume it is ours — the 409 body carries no
                    origin, and a Start that races our own other tab is the
                    common case and the one reattach exists for;
                 3. then CONFIRM via /session/state, which does echo origin,
                    and downgrade to the foreign (no-reattach) form if it
                    disagrees. Skipping that confirmation would let this view
                    adopt another surface's PTY — the exact thing the origin
                    guard forbids. */
              const knownOrigin = (this.conflictSession
                && this.conflictSession.study_session_id === data.study_session_id
                && this.conflictSession.origin) || OWN_ORIGIN;
              this._setConflict(this._conflictPayload(data), knownOrigin);
              this.startError = this.conflictIsOwn
                ? (data.error
                  || 'A session is already active. Reattach to it, or end it first.')
                : this._foreignConflictMessage(this.conflictSession);
              this.starting = false;
              /* Deliberately not awaited: the error and both levers must paint
                 now, not one round-trip later. Staleness is handled by the
                 epoch guard inside, not by ordering. */
              if (this.conflictIsOwn) this._syncConflictOrigin(data.study_session_id);
              return;
            }
            /* §1.5b returns structured 503 with install_hint; surface it verbatim.
               For a non-JSON error body, fall back to the HTTP status + snippet. */
            if (data.install_hint) {
              this.startError = `${data.error} · ${data.install_hint}`;
            } else if (data.error) {
              this.startError = data.error;
            } else {
              const snippet = raw.trim().slice(0, 200);
              this.startError = `Server error (HTTP ${res.status})` + (snippet ? `: ${snippet}` : '');
            }
            this.starting = false;
            return;
          }
          startedSession = data;
        } catch {
          this.startError = 'Network error — could not reach the server';
          this.starting = false;
          return;
        }
        this.topic = topic;
        this.startTime = new Date();
        this.sessionActive = true;
        /* We own the slot now, so any conflict block from a previous refusal is
           stale — clearing it here keeps the two from ever being true at once. */
        this._clearConflict();
        this.starting = false;
        this.elapsed = 0;
        this.tick();
        this.interval = setInterval(() => this.tick(), 1000);
        this.$nextTick(() => {
          window.dispatchEvent(new CustomEvent('study-session-start', {
            detail: {
              topic,
              // Which view started this: the two origin-scoped consoles each
              // ignore the other's events (ADR-0002).
              origin: 'study',
              energy: this.energy,
              sessionType: this.sessionType,
              targetKind: this.targetKind,
              targetPath: this.selectedOption?.path || null,
              agent: this.agent || null,
              resolvedAgent: startedSession.agent || this.agent || null,
              studySessionId: startedSession.study_session_id || null,
              transport: startedSession.transport || this.transport,
              wsUrl: startedSession.ws_url || null,
              personaText: startedSession.persona_text || null,
            }
          }));
        });
      },

      endSession() {
        // In-page confirm, NOT native confirm(): Chrome can auto-dismiss
        // native dialogs while the embedded ttyd terminal iframe holds
        // focus, which made agent sessions impossible to end.
        //
        // A conflict counts as something to end even though we own no session:
        // that is the ONE state where the learner needs End and has no session
        // of their own to end it from.
        if (!this.sessionActive && !this.conflictSession) return;
        this.confirmingEnd = true;
      },

      // Park-first modal: demote the chosen active topic (re-parking the
      // same question is an INSERT OR IGNORE no-op that would NOT free the
      // slot — demote makes it the oldest pending row), then retry the start.
      async parkAndProceed(topicRow) {
        try {
          const res = await fetch('/api/backlog/demote', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ id: topicRow.id }),
          });
          if (!res.ok) {
            Alpine.store('toast').show('Could not park — try again');
            return;
          }
        } catch {
          Alpine.store('toast').show('Could not park — offline?');
          return;
        }
        Alpine.store('toast').show('Parked ✓ — starting session');
        this.confirmingParkFirst = false;
        this._parkFirstChecked = true; // skip the re-check on retry
        await this.startSession();
      },

      cancelParkFirst() {
        this.confirmingParkFirst = false;
        this.parkFirstTopics = [];
      },

      async confirmEndSession() {
        this.confirmingEnd = false;
        if (!this.sessionActive) {
          /* No session of our own, but one we do not own is blocking Start: the
             dialog was opened by the picker's recovery End, so honour the
             confirmation here too instead of dropping the click. */
          if (this.conflictSession) await this._releaseConflictSession();
          return;
        }
        try {
          await fetch('/api/session/end', { method: 'POST' });
        } catch { /* best effort */ }
        window.dispatchEvent(new CustomEvent('study-session-stop', { detail: { origin: 'study' } }));
        this.sessionActive = false;
        clearInterval(this.interval);
        this.topic = 'Session ended';
        this.topicInput = '';
        this.selectedTopic = '';
      },

      /* ---- recovery from a session this view does not own -------------- */

      /* Route to the surface that DOES own the live session. Sending the
         learner into a view that can only 409 them is the closed loop this
         whole block exists to break. */
      openConflictOwner() {
        const origin = (this.conflictSession && this.conflictSession.origin) || OWN_ORIGIN;
        const route = CONFLICT_OWNER_ROUTES[origin] || CONFLICT_OWNER_ROUTES[OWN_ORIGIN];
        const nav = window.Alpine && window.Alpine.store ? window.Alpine.store('nav') : null;
        if (nav && typeof nav.go === 'function') nav.go(route);
      },

      /* End the blocking session, releasing the slot so Start can succeed.
         TWO-PHASE on purpose: killing a live agent is not undoable, and the
         picker's End button and the confirm dialog's Yes may both be wired
         here, so the first call only raises the in-page dialog and the second —
         made with the dialog already up — performs the release. */
      async endConflictSession() {
        if (!this.conflictSession) return;
        if (!this.confirmingEnd) {
          this.confirmingEnd = true;
          return;
        }
        await this._releaseConflictSession();
      },

      /* Adopt the LIVE session instead of starting a new one. Only legal when
         the session is ours (`conflictIsOwn`) — the server holds a detached
         session through the grace window, so the id in reattach_url still
         resolves to a running PTY. */
      reattachConflictSession() {
        const session = this.conflictSession;
        if (!session || !this.conflictIsOwn) return;
        const sessionId = session.study_session_id;
        const wsUrl = this._conflictWsUrl(session);
        if (!sessionId || !wsUrl) return;
        /* Newer information than anything in flight: drop a late state read. */
        this._conflictEpoch += 1;
        this.topic = session.topic || 'Study Session';
        this.energy = session.energy || this.energy;
        this.startTime = session.start_time ? new Date(session.start_time) : new Date();
        this.sessionActive = true;
        this.starting = false;
        this._clearConflict();
        clearInterval(this.interval);
        this.tick();
        this.interval = setInterval(() => this.tick(), 1000);
        this.$nextTick(() => {
          window.dispatchEvent(new CustomEvent('study-session-start', {
            detail: {
              topic: this.topic,
              // Origin-scoped: the Body Double console ignores this (ADR-0002).
              origin: OWN_ORIGIN,
              energy: this.energy,
              sessionType: this.sessionType,
              targetKind: this.targetKind,
              targetPath: null,
              agent: session.agent || this.agent || null,
              resolvedAgent: session.agent || this.agent || null,
              studySessionId: sessionId,
              transport: session.transport || this.transport,
              wsUrl,
              personaText: null,
              /* Marks this as an ADOPTION, not a fresh start: consumers must
                 not replay a persona turn into a conversation already running. */
              reattached: true,
            },
          }));
        });
      },

      /* The actual release. Separate from endConflictSession() so the confirm
         dialog can call it directly without re-entering the two-phase gate. */
      async _releaseConflictSession() {
        this.confirmingEnd = false;
        const epoch = ++this._conflictEpoch;
        try {
          await fetch('/api/session/end', { method: 'POST' });
        } catch { /* best effort — a stuck conflict block is worse than a lost error */ }
        if (epoch !== this._conflictEpoch) return;
        this._clearConflict();
        this.starting = false;
        this.topic = 'No active session';
      },

      /* Normalise a conflicting session from either source — the 409 body or
         /api/session/state — down to the fields this block reads. The state
         body also carries the topics/parking panels; keeping them would drag
         two lists through Alpine's proxy on every conflict read for no reader. */
      _conflictPayload(source) {
        const src = source || {};
        return {
          study_session_id: src.study_session_id || null,
          topic: src.topic || null,
          agent: src.agent || null,
          energy: src.energy || null,
          start_time: src.start_time || src.started_at || null,
          transport: src.transport || null,
          detached: !!src.detached,
          reattach_url: src.reattach_url || null,
        };
      },

      /* Single writer for all three conflict fields, so the label and the
         is-own flag can never drift from the session they describe. An
         unrecognised origin falls back to ours, matching the server's own
         setdefault rather than inventing a third state. */
      _setConflict(session, origin) {
        const resolved = CONFLICT_OWNER_LABELS[origin] ? origin : OWN_ORIGIN;
        this.conflictSession = { ...session, origin: resolved };
        this.conflictIsOwn = resolved === OWN_ORIGIN;
        this.conflictOwnerLabel = CONFLICT_OWNER_LABELS[resolved];
      },

      _clearConflict() {
        this.conflictSession = null;
        this.conflictOwnerLabel = '';
        this.conflictIsOwn = false;
        this.startError = '';
      },

      /* Names the owning surface in the text itself. "A session is already
         active" without saying WHOSE is the difference between a clear refusal
         and a dead end. */
      _foreignConflictMessage(session) {
        const subject = session && session.topic ? ` on "${session.topic}"` : '';
        return `A ${this.conflictOwnerLabel} session is already active${subject}. `
          + `Open ${this.conflictOwnerLabel} to use it, or end it to start here.`;
      },

      _conflictWsUrl(session) {
        const id = session && session.study_session_id;
        if (!id) return null;
        /* Prefer the server's own reattach_url — both the 409 body and
           /session/state carry it, and it already contains the session id,
           which is what /api/session/ws keys the resumed PTY on. The fallback
           mirrors the server's exact format for the same reason; the id is
           server-issued and must reach the socket unescaped. */
        const url = session.reattach_url || `/api/session/ws?study_session_id=${id}`;
        return String(url).includes(String(id))
          ? url
          : `/api/session/ws?study_session_id=${id}`;
      },

      /* Confirm an ASSUMED-ours conflict against /api/session/state, the only
         source that echoes `origin`, and downgrade to the foreign form if it
         disagrees. Also upgrades the payload with the fields a 409 body lacks
         (start_time, energy, transport), so an adopted session's elapsed clock
         continues from its real start rather than restarting at zero. */
      async _syncConflictOrigin(sessionId) {
        const epoch = this._conflictEpoch;
        let state = null;
        try {
          state = await fetch('/api/session/state').then((res) => (res.ok ? res.json() : null));
        } catch { return; /* keep the optimistic reading — no worse than before */ }
        /* A reattach or an end since this went out is NEWER information than
           the response; letting it land would resurrect a cleared conflict. */
        if (epoch !== this._conflictEpoch) return;
        if (!state || !state.study_session_id || state.study_session_id !== sessionId) return;
        if (!this.conflictSession
          || this.conflictSession.study_session_id !== sessionId) return;
        const payload = this._conflictPayload(state);
        payload.reattach_url = payload.reattach_url || this.conflictSession.reattach_url;
        this._setConflict(payload, state.origin || OWN_ORIGIN);
        if (!this.conflictIsOwn) {
          this.startError = this._foreignConflictMessage(this.conflictSession);
        }
      },

      selectOption(kind, value) {
        const collection = this.studyOptions[`${kind}s`] || [];
        this.selectedOption = collection.find((item) => item.value === value) || null;
        if (this.selectedOption) this.topicInput = this.selectedOption.label;
      },

      agentOptions() {
        return this.studyOptions.agents || [];
      },

      selectedAgentSupportsAcp() {
        const selected = this.agentOptions().find((item) => item.value === this.agent);
        return !!(selected && selected.supports_acp && selected.available);
      },

      filteredCourses() {
        if (!this.selectedVendor) return [];
        return this.studyOptions.courses.filter((course) => course.parent === this.selectedVendor);
      },

      filteredLessons() {
        if (!this.selectedCourse) return [];
        return this.studyOptions.lessons.filter((lesson) => lesson.parent === this.selectedCourse);
      },

      resolvedTopic() {
        /* Return the joined vendor/course/lesson path (plan §1.8) so
           the agent's DB record + persona reflects the full cascade
           location. ``option.value`` is already constructed as a
           slash-joined path by the /session/options endpoint — see
           ``_course_options`` / ``_lesson_options`` in session.py.
           Falls back to the free-text topic input for the 'topic'
           target kind (no cascade). */
        if (this.targetKind === 'lesson' && this.selectedLesson) {
          return this.selectedLesson;
        }
        if (this.targetKind === 'lesson') {
          return '';
        }
        if (this.targetKind === 'course' && this.selectedCourse) {
          return this.selectedCourse;
        }
        if (this.targetKind === 'course') {
          return '';
        }
        if (this.targetKind === 'vendor') {
          if (this.selectedCourse) return this.selectedCourse;
          if (this.selectedVendor) return this.selectedVendor;
        }
        return this.topicInput;
      },

      togglePause() {
        if (!this.sessionActive) return;
        if (this.paused) {
          const pauseDuration = Date.now() - this.pausedAt;
          this.startTime = new Date(this.startTime.getTime() + pauseDuration);
          this.paused = false;
          this.interval = setInterval(() => this.tick(), 1000);
        } else {
          this.paused = true;
          this.pausedAt = Date.now();
          clearInterval(this.interval);
        }
      },

      resetTimer() {
        if (!this.sessionActive) return;
        this.startTime = new Date();
        this.elapsed = 0;
        this.paused = false;
        this._shownAmber = false;
        this._shownRed = false;
        this.message = '';
        clearInterval(this.interval);
        this.interval = setInterval(() => this.tick(), 1000);
      },

      tick() {
        if (!this.startTime || this.paused) return;
        this.elapsed = Math.floor((Date.now() - this.startTime.getTime()) / 1000);
        this.checkThresholds();
      },

      checkThresholds() {
        const mins = this.elapsed / 60;
        const band = energyBand(this.energy);
        const th = THRESHOLDS[band];
        if (mins >= th.amber && !this._shownRed) {
          this._shownRed = true;
          this.showMessage("Your brain's been at this for a while. Just flagging it.");
        } else if (mins >= th.green && !this._shownAmber) {
          this._shownAmber = true;
          if (this.energy < 7) {
            this.showMessage("Good stretch of focus. A micro-break soon?");
          }
        }
      },

      showMessage(msg) {
        this.message = msg;
        clearTimeout(this.messageTimeout);
        this.messageTimeout = setTimeout(() => { this.message = ''; }, 15000);
      },

      get display() {
        const m = Math.floor(this.elapsed / 60);
        const s = this.elapsed % 60;
        return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
      },

      get progress() {
        if (!this.sessionActive) return 0;
        const mins = this.elapsed / 60;
        const band = energyBand(this.energy);
        const th = THRESHOLDS[band];
        return Math.min(100, (mins / th.amber) * 100);
      },

      get timerPhase() {
        if (!this.sessionActive) return 'phase-idle';
        const mins = this.elapsed / 60;
        const band = energyBand(this.energy);
        const th = THRESHOLDS[band];
        if (mins >= th.amber) return 'phase-red';
        if (mins >= th.green) return 'phase-amber';
        return 'phase-green';
      },

      get timerIcon() {
        if (!this.sessionActive) return '\u23f1';
        const phase = this.timerPhase;
        if (phase === 'phase-red') return '\ud83d\udfe5';
        if (phase === 'phase-amber') return '\ud83d\udfe7';
        return '\ud83d\udfe9';
      },

      destroy() {
        clearInterval(this.interval);
        clearTimeout(this.messageTimeout);
      }
    };
  }
