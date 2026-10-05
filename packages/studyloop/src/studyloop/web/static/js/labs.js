/**
 * Labs -- the Web UI entry for installed modules' drills (module-contract v1, lane W).
 *
 * WHAT THIS FILE OWNS
 * -------------------
 * One generic sidebar entry, visible only while `modules.lock.json` lists a module
 * (C7: hidden otherwise, never an empty placeholder), and one view that lists the
 * installed modules' decks and tasks by id and prompt -- plus each task's success
 * criteria and the exact `studyloop drill` commands the learner runs in their own
 * terminal. Nothing from `hint`, `solution` or `mentorNotes` is ever rendered: the
 * server never sends them, and `scrubMentorOnlyFields` drops them again here so a
 * server regression cannot reach the DOM (proposal §5.6, web-ui spec scenario 3).
 *
 * STARTING A DRILL (proposal §7, Labs row)
 * ----------------------------------------
 * "Starting a drill uses the existing session start + terminal inside the one claimed
 * session." `startDrill` POSTs the drill identity to `/api/modules/labs/start`; the
 * server either starts the one session for it through the one session-start path
 * (201) or binds the drill to the session already live (200, `attached`). The browser
 * then goes to the Study Session view, whose console is the mentor pane. After a
 * fresh start that view re-adopts the live session on page load (`sessionTimer` reads
 * `/api/session/state`; the console reattaches) -- so a 201 is followed by a reload.
 * That reuses the tested re-attach path rather than reaching into another component's
 * state; the live drill survives the reload in `sessionStorage`. An attached start
 * needs no reload: the session was already the learner's.
 *
 * Nothing executes from here. The MVP's only execution surface is `studyloop drill`
 * (per-phase consent in the CLI, no `--yes`); browser-triggered checks are v1.1 (§8).
 * `cancelDrill` drops the drill (and a start still in flight) and leaves the session
 * exactly as it was.
 *
 * WHY FACTORIES WITH INJECTABLE DEPENDENCIES
 * ------------------------------------------
 * Same contract as every component under `js/components/`: Alpine evaluates
 * `x-data="labsView()"` in global scope, so the factory is assigned to `window`
 * below. `fetch`, `navigate`, `reload` and `storage` are injectable so
 * `tests/js/module-labs.test.js` drives the view with no browser and no server.
 */

export const MENTOR_ONLY_FIELDS = Object.freeze(['hint', 'solution', 'mentorNotes', 'mentor_notes']);

/** `sessionStorage` key for the drill the learner started from Labs. */
export const ACTIVE_DRILL_KEY = 'studyloop.labs.activeDrill';
/** `sessionStorage` key for the start's binding: `{ drill_nonce, study_session_id }`.
 *  Per tab (sessionStorage), on purpose: the binding is THIS view's handle on the live
 *  drill (W-review finding 7) -- another tab that never started it holds none. */
export const ACTIVE_BINDING_KEY = 'studyloop.labs.activeBinding';

const PHASES = Object.freeze(['setup', 'check', 'cleanup']);

const isObject = (value) => value !== null && typeof value === 'object' && !Array.isArray(value);

/** True when any object anywhere inside `value` carries a mentor-only key. */
export function containsMentorOnlyFields(value) {
  if (Array.isArray(value)) return value.some(containsMentorOnlyFields);
  if (!isObject(value)) return false;
  return Object.keys(value).some((key) => MENTOR_ONLY_FIELDS.includes(key))
    || Object.values(value).some(containsMentorOnlyFields);
}

/** A deep copy of `value` with every mentor-only key removed, at every depth. */
export function scrubMentorOnlyFields(value) {
  if (Array.isArray(value)) return value.map(scrubMentorOnlyFields);
  if (!isObject(value)) return value;
  const out = {};
  for (const [key, inner] of Object.entries(value)) {
    if (MENTOR_ONLY_FIELDS.includes(key)) continue;
    out[key] = scrubMentorOnlyFields(inner);
  }
  return out;
}

/**
 * The exact commands a task's declared phases need, in phase order. The server sends
 * them (`commands`); when it did not, derive them from `phases` so a stale cache
 * still shows the learner what to run.
 */
export function drillCommands(task) {
  if (!task) return [];
  if (Array.isArray(task.commands) && task.commands.length) return [...task.commands];
  const phases = Array.isArray(task.phases) ? task.phases.filter((p) => PHASES.includes(p)) : [];
  return phases.map((phase) => `studyloop drill ${phase} ${task.ref}`);
}

/**
 * Normalise the `labs` array of an options or `/api/modules/labs` payload: scrubbed,
 * with every module carrying `decks[]` and every deck `tasks[]`. Anything that is not
 * a list of modules is "no Labs".
 */
export function labsEntries(payload) {
  const labs = payload && Array.isArray(payload.labs) ? payload.labs : [];
  return labs.filter(isObject).map((module) => {
    const clean = scrubMentorOnlyFields(module);
    const decks = Array.isArray(clean.decks) ? clean.decks.filter(isObject) : [];
    return {
      ...clean,
      decks: decks.map((deck) => ({
        ...deck,
        tasks: Array.isArray(deck.tasks) ? deck.tasks.filter(isObject) : [],
      })),
    };
  });
}

/* ---- the store: `$store.labs` -- drives the sidebar entry and feeds the view ---- */

const defaultFetch = (...args) => globalThis.fetch(...args);

export function labsStore(deps = {}) {
  const fetchFn = deps.fetch || defaultFetch;
  return {
    /** The one visibility switch for the sidebar entry: true only with a module installed. */
    available: false,
    modules: [],
    agents: [],
    loaded: false,
    error: '',

    /* Alpine calls a store's init() itself, THROUGH its reactive proxy -- which is the
       only `this` whose writes the sidebar's x-show observes. Refreshing the raw object
       from registerLabsStore() mutated a target no effect was watching (found by the
       W2 browser smoke: the entry never appeared). */
    init() {
      return this.refresh();
    },

    async refresh() {
      let payload = null;
      try {
        const res = await fetchFn('/api/modules/labs', { cache: 'no-store' });
        if (res.ok) {
          payload = await res.json();
        } else {
          this.error = `Labs could not be loaded (HTTP ${res.status})`;
        }
      } catch {
        this.error = 'Labs could not be loaded (network error)';
      }
      /* A failed read hides Labs rather than showing a list that may no longer be
         true -- the entry is a claim that a module is installed. */
      this.modules = payload ? labsEntries(payload) : [];
      this.agents = payload && Array.isArray(payload.agents) ? payload.agents : [];
      this.available = this.modules.length > 0;
      if (payload) this.error = '';
      this.loaded = true;
    },
  };
}

export function registerLabsStore(Alpine) {
  /* Alpine wraps the object in its reactive proxy and calls init() on it; a refresh()
     on the raw object here would write to a target nothing observes. */
  Alpine.store('labs', labsStore());
}

/* ---- the view: list, start inside the one claimed session, cancel ------------- */

function browserStorage() {
  try {
    return typeof window !== 'undefined' && window.sessionStorage ? window.sessionStorage : null;
  } catch {
    return null;
  }
}

function alpineStore(name) {
  const Alpine = typeof window !== 'undefined' ? window.Alpine : null;
  return Alpine && typeof Alpine.store === 'function' ? Alpine.store(name) : null;
}

function describeRefusal(status, data, raw) {
  if (data && data.install_hint) return `${data.error} · ${data.install_hint}`;
  if (data && data.error) return data.error;
  const snippet = String(raw || '').trim().slice(0, 200);
  return `Server error (HTTP ${status})` + (snippet ? `: ${snippet}` : '');
}

export function labsView(deps = {}) {
  const fetchFn = deps.fetch || defaultFetch;
  const storage = deps.storage === undefined ? browserStorage() : deps.storage;
  const navigate = deps.navigate || ((view) => {
    const nav = alpineStore('nav');
    if (nav && typeof nav.go === 'function') nav.go(view);
  });
  const currentView = deps.currentView || (() => {
    const nav = alpineStore('nav');
    return nav && typeof nav.current === 'string' ? nav.current : '';
  });
  const reload = deps.reload || (() => window.location.reload());
  /* After an ATTACHED start (no reload) the console is already mounted: put focus in it
     (design.md §6 step 4; U1-review a4a). A fresh start reloads, and the console's own mount
     focuses the terminal as it opens. */
  const focusConsole = deps.focusConsole || (() => {
    if (typeof document === 'undefined') return;
    const focus = () => {
      const area = document.querySelector('.session-active-layout .xterm-helper-textarea');
      if (area && typeof area.focus === 'function') area.focus();
    };
    if (typeof requestAnimationFrame === 'function') requestAnimationFrame(focus); else focus();
  });
  const getStore = () => deps.store || alpineStore('labs');

  const readStored = () => {
    if (!storage) return null;
    try {
      const raw = storage.getItem(ACTIVE_DRILL_KEY);
      const parsed = raw ? JSON.parse(raw) : null;
      return isObject(parsed) && parsed.ref ? scrubMentorOnlyFields(parsed) : null;
    } catch {
      return null;
    }
  };
  const writeStored = (drill) => {
    if (!storage) return;
    try { storage.setItem(ACTIVE_DRILL_KEY, JSON.stringify(drill)); } catch { /* quota, private mode */ }
  };
  const clearStored = () => {
    if (!storage) return;
    try { storage.removeItem(ACTIVE_DRILL_KEY); storage.removeItem(ACTIVE_BINDING_KEY); } catch { /* nothing to clear */ }
  };
  const readBinding = () => {
    if (!storage) return null;
    try {
      const raw = storage.getItem(ACTIVE_BINDING_KEY);
      const parsed = raw ? JSON.parse(raw) : null;
      return isObject(parsed) && parsed.drill_nonce ? parsed : null;
    } catch {
      return null;
    }
  };
  const writeBinding = (binding) => {
    if (!storage) return;
    try { storage.setItem(ACTIVE_BINDING_KEY, JSON.stringify(binding)); } catch { /* quota */ }
  };

  return {
    agent: '',
    transport: 'pty',
    starting: false,
    startError: '',
    /** The drill the learner started from here, or null. Scrubbed; survives a reload. */
    activeDrill: null,
    /** The start's nonce for the live drill (this view's handle on it), or ''. */
    activeNonce: '',
    /** The session the live drill was bound to, or ''. */
    activeSessionId: '',
    /** `ref` of the drill whose start is in flight ('' otherwise) -- the button it belongs to shows it. */
    pendingRef: '',
    /* Monotonic: a cancel during an in-flight start bumps it, and the late response is
       dropped instead of adopting a session the learner just said no to. */
    _epoch: 0,

    async init() {
      this.activeDrill = readStored();
      const binding = readBinding();
      this.activeNonce = binding ? String(binding.drill_nonce) : '';
      this.activeSessionId = binding ? String(binding.study_session_id || '') : '';
      const store = getStore();
      if (store && !store.loaded) await store.refresh();
      this._pickAgent();
      /* `#labs` is a real hash view (finding 10), so a reload lands here -- but Labs exists
         only while a module is installed (C7). An empty Labs is not a view; go to Today. */
      if (store && store.loaded && !store.available && currentView() === 'labs') navigate('today');
    },

    modules() {
      const store = getStore();
      return store && Array.isArray(store.modules) ? store.modules : [];
    },

    agents() {
      const store = getStore();
      return store && Array.isArray(store.agents) ? store.agents : [];
    },

    error() {
      const store = getStore();
      return store ? store.error || '' : '';
    },

    /* Pre-select the first detected agent, exactly as the Study picker does, so the
       learner sees a choice rather than a silent default. */
    _pickAgent() {
      if (this.agent) return;
      const first = this.agents().find((a) => a && a.available);
      if (first) this.agent = first.value;
    },

    commandsFor(task) {
      return drillCommands(task);
    },

    isActive(task) {
      return !!(this.activeDrill && task && this.activeDrill.ref === task.ref);
    },

    isPending(task) {
      return this.starting && !!task && this.pendingRef === task.ref;
    },

    async startDrill(module, task) {
      if (!this.agent) {
        /* The Study picker's own hint; nothing is posted without an agent. */
        this.startError = 'Select an agent to continue.';
        return false;
      }
      const parts = String((task && task.ref) || '').split('/');
      if (parts.length !== 3) {
        this.startError = 'This drill has no usable reference.';
        return false;
      }
      const [moduleId, deckId, taskId] = parts;
      const epoch = ++this._epoch;
      this.starting = true;
      this.startError = '';
      this.pendingRef = task.ref;
      let res;
      let raw = '';
      try {
        /* Replacing a live drill: present this view's binding, or the server (rightly)
           refuses -- another view cannot swap the drill out from under the one that started it. */
        const binding = this.activeNonce
          ? { drill_nonce: this.activeNonce, study_session_id: this.activeSessionId }
          : {};
        res = await fetchFn('/api/modules/labs/start', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            module_id: (module && module.module_id) || moduleId,
            deck_id: deckId,
            task_id: taskId,
            agent: this.agent,
            transport: this.transport,
            ...binding,
          }),
        });
        raw = await res.text();
      } catch {
        if (epoch !== this._epoch) return false;
        this.starting = false;
        this.pendingRef = '';
        this.startError = 'Network error — could not reach the server';
        return false;
      }
      if (epoch !== this._epoch) return false; /* cancelled while in flight */
      let data = {};
      try { data = raw ? JSON.parse(raw) : {}; } catch { data = {}; }
      this.starting = false;
      this.pendingRef = '';
      if (!res.ok) {
        this.startError = describeRefusal(res.status, data, raw);
        return false;
      }
      const drill = scrubMentorOnlyFields(
        isObject(data.drill) ? data.drill : { ref: task.ref, module_id: moduleId, deck_id: deckId, task_id: taskId },
      );
      this.activeDrill = drill;
      this.activeNonce = typeof data.drill_nonce === 'string' ? data.drill_nonce : '';
      this.activeSessionId = data.study_session_id ? String(data.study_session_id) : '';
      writeStored(drill);
      if (this.activeNonce) {
        writeBinding({ drill_nonce: this.activeNonce, study_session_id: this.activeSessionId });
      }
      navigate('study-session');
      /* A fresh start: the Study Session view adopts the live session on page load
         (its console reattaches through /api/session/state). An attached start has
         nothing to adopt -- the session was already there; focus its console. */
      if (!data.attached) reload();
      else focusConsole();
      return true;
    },

    async cancelDrill() {
      this._epoch += 1;
      this.starting = false;
      this.pendingRef = '';
      /* A start still in flight has no binding yet; dropping it locally is the whole cancel. */
      if (!this.activeDrill) return;
      let refused = '';
      try {
        const res = await fetchFn('/api/modules/labs/cancel', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            drill_nonce: this.activeNonce,
            study_session_id: this.activeSessionId,
          }),
        });
        if (res && res.status === 403) {
          let data = {};
          try { data = JSON.parse(await res.text()); } catch { data = {}; }
          refused = data.error || 'This view did not start the live drill, so it cannot cancel it.';
        }
      } catch {
        /* Unreachable server: the learner's decision stands; the record is advisory. */
      }
      if (refused) {
        this.startError = refused;
        return;
      }
      this.activeDrill = null;
      this.activeNonce = '';
      this.activeSessionId = '';
      clearStored();
    },
  };
}

/* ---- browser registration (skipped under node) ------------------------------- */

if (typeof window !== 'undefined' && typeof document !== 'undefined') {
  window.labsView = labsView;
  document.addEventListener('alpine:init', () => registerLabsStore(window.Alpine));
}
