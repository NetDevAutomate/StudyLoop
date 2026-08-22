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
 * ------------------------------------------------------------------ */
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
          if (state.study_session_id && state.mode !== 'ended') {
            this.energy = state.energy || 5;
            this.topic = state.topic || 'Study Session';
            this.startTime = state.start_time
              ? new Date(state.start_time)
              : (state.started_at ? new Date(state.started_at) : new Date());
            this.sessionActive = true;
            this.tick();
            this.interval = setInterval(() => this.tick(), 1000);
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
            }),
          });
          /* Parse defensively: a 500 with an HTML/plain body must NOT masquerade
             as a network error. Read text, then try JSON — a non-JSON body on a
             failed response is a real server error, surfaced with its status. */
          const raw = await res.text();
          let data = {};
          try { data = raw ? JSON.parse(raw) : {}; } catch { data = {}; }
          if (!res.ok) {
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
        if (!this.sessionActive) return;
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
        if (!this.sessionActive) return;
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
