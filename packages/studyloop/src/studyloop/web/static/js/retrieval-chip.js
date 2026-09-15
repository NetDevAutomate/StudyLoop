/**
 * Encoder-warm status chip (lane A4, council D-8).
 *
 * The server pre-warms the query encoder at boot (lane A1). That load takes
 * seconds, and a search during it silently returns lexical-only results — so
 * the chip says which phase the warm is in, which model, and how long the load
 * that produced this state took.
 *
 * DELIBERATELY NOT A PROGRESS BAR. Nothing in a model load reports its own
 * completion fraction, so any percentage would be invented (E-A9). A contract
 * test asserts this file contains no percent sign at all.
 *
 * "last load" wording lives in the CLI reporter, not here: the browser is not
 * the process that loaded anything, so it reports the state it is told and the
 * elapsed time of that state — never an estimate of what comes next.
 *
 * Classic script, not a module, and registered from its own `alpine:init`
 * listener — the same pattern as nav-and-panel-stores.js, so `script-src
 * 'self'` stays a strict CSP with no inline exception.
 */
document.addEventListener('alpine:init', () => {
  /* Label + CSS class per state. `warm` is intentionally the quiet one: the
     chip exists to explain a wait or a failure, not to congratulate the
     server for working. */
  const PRESENTATION = {
    'cold': { label: 'semantic: cold', cls: 'bd-chip' },
    'warming': { label: 'semantic: loading', cls: 'bd-chip warn' },
    'warm': { label: 'semantic: ready', cls: 'bd-chip' },
    'failed': { label: 'semantic: failed', cls: 'bd-chip warn' },
    'disabled': { label: 'semantic: off', cls: 'bd-chip' },
  };

  Alpine.store('encoderWarm', {
    state: 'cold',
    model: null,
    elapsed: null,
    detail: '',

    get label() {
      const shown = PRESENTATION[this.state] || PRESENTATION.cold;
      if (this.state === 'warming') return shown.label;
      if (this.elapsed !== null && this.elapsed !== undefined) {
        return `${shown.label} (${this.elapsed.toFixed(1)}s)`;
      }
      return shown.label;
    },

    get cls() {
      return (PRESENTATION[this.state] || PRESENTATION.cold).cls;
    },

    get title() {
      const parts = [];
      if (this.model) parts.push(this.model);
      if (this.detail) parts.push(this.detail);
      return parts.length ? parts.join(' — ') : 'query encoder warm status';
    },

    /* Only shown while it says something a learner can act on. A permanently
       visible "ready" badge is noise; a silent failure is the bug. */
    get visible() {
      return this.state !== 'warm' && this.state !== 'cold';
    },

    async refresh() {
      try {
        const response = await fetch('/api/retrieval/health');
        if (!response.ok) return;
        const payload = await response.json();
        this.state = payload.state || 'cold';
        this.model = payload.model;
        this.elapsed = payload.elapsed;
        this.detail = payload.detail || '';
      } catch (err) {
        /* A status read failing is not worth a visible error: the chip's job
           is to explain the encoder, not the network. */
      }
    },

    init() {
      this.refresh();
      /* A warm either finishes or fails within seconds; stop polling once it
         has reached a terminal state so an idle page is not chatty. */
      const timer = setInterval(() => {
        if (this.state === 'warm' || this.state === 'failed' || this.state === 'disabled') {
          clearInterval(timer);
          return;
        }
        this.refresh();
      }, 1500);
    },
  });

  Alpine.store('encoderWarm').init();
});
