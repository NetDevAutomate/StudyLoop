/* ------------------------------------------------------------------
 * Study plans — shared Alpine store + content-column panel.
 *
 * WHY A STORE *AND* A COMPONENT
 * -----------------------------
 * The plan LIST lives in the left-pane `nav.sidebar`; the plan READER lives in
 * the content column. Two disjoint DOM subtrees cannot share one `x-data`, so
 * the state that both need (items, selection, progress) lives in
 * `Alpine.store('plans')` — the same pattern as `Alpine.store('nav')` and
 * `Alpine.store('explorer')`. `plansPanel()` is a thin facade over that store
 * for the content column: it owns only the concerns a store cannot reach,
 * namely `$nextTick`/`$root` and the second-pass mermaid render.
 *
 * WHY THE PANEL IS ALL GETTERS
 * ----------------------------
 * Every panel getter forwards to the store, so markup may bind either
 * `$store.plans.selected` or plain `selected` and get the same object. The
 * getters that back an `x-model` (`form`) return the store's own object, so
 * writes land on the store rather than shadowing it. Scalars that markup might
 * assign to (`creating`, `error`) carry setters for the same reason.
 *
 * WHY FACTORIES AND NOT CLASSES
 * -----------------------------
 * Alpine wraps the returned object in a reactive Proxy. Class methods live on
 * the prototype, not as own-properties, so both reactivity and `this` binding
 * break silently. `plansStore` is a plain object literal and `plansPanel` is a
 * factory returning one.
 *
 * FREE-VARIABLE DEPENDENCIES (components.js, a classic script)
 * -----------------------------------------------------------
 * `renderMarkdown`, `_renderMermaidPlaceholders` and `_mermaidInitForPalette`
 * are top-level functions in components.js, which makes them properties of the
 * global object by the time any module method runs. They are read here as FREE
 * identifiers behind `typeof` guards — deliberately, so there is exactly one
 * markdown renderer in the app and so this module still imports cleanly under
 * `node --test`, where none of them exist.
 *
 * SERVER CONTRACT (routes/plans.py — read, never changed here)
 *   GET    /api/plans                                {plans[], count, statuses[]}
 *   GET    /api/plans/interview                      {questions, seed}
 *   GET    /api/plans/{id}      {plan, markdown, mission, milestones,
 *                                learning_records, resources, checkpoints,
 *                                readiness}
 *   GET    /api/plans/{id}/evaluate?phase=…          {evaluation, markdown}
 *   POST   /api/plans/{id}/evaluate  201             {recorded, evaluation, …}
 *   POST   /api/plans                201             {created, plan, readiness}
 *   PATCH  /api/plans/{id}           422 on refusal  detail={message, blockers…}
 *   POST   /api/plans/{id}/milestones/{i}/toggle     {updated, index, done, plan}
 * ------------------------------------------------------------------ */

const API = '/api/plans';

/* ==================================================================
 * Pure helpers — no DOM, no fetch, no Alpine.
 * Unit-tested in tests/js/plans-panel.test.js.
 * ================================================================== */

/* Mirrors planning/markdown.py `_CONCEPTS_RE` exactly, including the optional
   backtick/paren wrappers a hand-edited document grows. Python's re.search and
   JS's RegExp.exec are both leftmost-first, so the two agree on which match
   wins when a line somehow contains "concepts:" twice. */
const CONCEPTS_RE = /[`(]?\(?concepts:\s*([^)`]*)\)?[`)]?\s*$/i;
const BOLD_RE = /\*\*(.*?)\*\*/g;
/* A learner may paste real document lines back into the textarea, so accept
   (and honour) a leading task-list checkbox as well as a bare bullet. */
const CHECKBOX_RE = /^[-*+]\s+\[([ xX])\]\s*/;
const BULLET_RE = /^[-*+]\s+/;
/* Em dash, en dash and '--' all separate a milestone title from its notes:
   learners hand-edit these documents and keyboards produce all three. */
const NOTE_SEPARATORS = [' \u2014 ', ' \u2013 ', ' -- '];
const FRONTMATTER_RE = /^---\r?\n[\s\S]*?\r?\n---\r?\n?/;

/**
 * Drop a leading YAML frontmatter block.
 *
 * The server returns the plan's canonical document, which opens with
 * `---\ntitle: …\nreview_cadence_days: 3\n---`. Handed to `marked` raw, the
 * fences render as `<hr>` and the YAML keys leak into the page as paragraph
 * text — a test asserts the rendered text does NOT contain
 * `review_cadence_days:`. Frontmatter is metadata, not content.
 *
 * @param {string} text — raw markdown
 * @returns {string} — markdown with the opening block removed
 */
export function stripFrontmatter(text) {
  if (!text) return '';
  if (!text.startsWith('---\n') && !text.startsWith('---\r\n')) return text;
  const match = text.match(FRONTMATTER_RE);
  if (!match) return text; /* unclosed / malformed — leave it alone */
  return text.slice(match[0].length);
}

/**
 * Split a newline-separated textarea value into a clean list.
 *
 * `plan-field-success` / `-topics` / `-milestones` are textareas that receive
 * multi-line values; the API wants lists. Blank lines and an optional bullet
 * prefix are the two things learners reliably produce that JSON should not.
 *
 * @param {string} text
 * @returns {string[]}
 */
export function splitLines(text) {
  if (!text) return [];
  return String(text)
    .split(/\r?\n/)
    .map((line) => line.replace(BULLET_RE, '').trim())
    .filter((line) => line.length > 0);
}

/**
 * Parse one milestone line into the shape POST /api/plans accepts.
 *
 * `Understand Glue job anatomy (concepts: glue job, job bookmark)`
 *   → {title: 'Understand Glue job anatomy',
 *      concepts: ['glue job', 'job bookmark'], notes: '', done: false}
 *
 * The concepts tail is what joins a milestone to spaced-repetition evidence,
 * and it is what the server renders as inline `<code>` in the document — so
 * losing it here silently degrades the plan. Deliberately mirrors
 * planning/markdown.py `_parse_milestone_line` rather than inventing a second
 * grammar: the same line must round-trip through either side.
 *
 * @param {string} line
 * @returns {{title: string, concepts: string[], notes: string, done: boolean}}
 */
export function parseMilestoneLine(line) {
  let text = String(line == null ? '' : line).trim();

  /* Honour a pasted task-list checkbox, then strip a plain bullet. */
  let done = false;
  const box = text.match(CHECKBOX_RE);
  if (box) {
    done = box[1].toLowerCase() === 'x';
    text = text.slice(box[0].length).trim();
  } else {
    text = text.replace(BULLET_RE, '').trim();
  }

  let concepts = [];
  const match = CONCEPTS_RE.exec(text);
  if (match) {
    concepts = match[1]
      .split(',')
      .map((c) => c.trim())
      .filter((c) => c.length > 0);
    text = text.slice(0, match.index).trim();
  }
  /* A trailing backtick survives when the tail was written as `(concepts: …)`
     and the opening backtick fell inside the matched region. */
  text = text.replace(/`+$/, '').trim();

  let title = text;
  let notes = '';
  for (const sep of NOTE_SEPARATORS) {
    const at = text.indexOf(sep);
    if (at !== -1) {
      title = text.slice(0, at);
      notes = text.slice(at + sep.length);
      break;
    }
  }

  return {
    title: title.replace(BOLD_RE, '$1').trim(),
    concepts,
    notes: notes.trim(),
    done,
  };
}

/**
 * Parse a whole milestones textarea into API payload objects.
 *
 * @param {string} text — newline-separated milestone lines
 * @returns {Array<{title: string, concepts: string[], notes: string, done: boolean}>}
 */
export function parseMilestoneLines(text) {
  if (!text) return [];
  return String(text)
    .split(/\r?\n/)
    .filter((line) => line.trim().length > 0)
    .map((line) => parseMilestoneLine(line))
    .filter((m) => m.title.length > 0 || m.concepts.length > 0);
}

/**
 * Completion as a whole percentage.
 *
 * `pct` is the server's own `progress_pct`, which is authoritative and is
 * preferred whenever it is present: Python's `round()` is banker's rounding
 * and JS's `Math.round` is half-up, so 1/8 would render as 12% server-side and
 * 13% here. Recomputing only covers the optimistic window before a response
 * lands.
 *
 * @param {number} done
 * @param {number} total
 * @param {number} [pct] — server-supplied percentage, if known
 * @returns {number} 0-100
 */
export function progressPercent(done, total, pct) {
  const server = Number(pct);
  if (Number.isFinite(server)) return Math.max(0, Math.min(100, Math.round(server)));
  const d = Number(done);
  const t = Number(total);
  if (!Number.isFinite(d) || !Number.isFinite(t) || t <= 0) return 0;
  return Math.max(0, Math.min(100, Math.round((100 * d) / t)));
}

/**
 * Human progress readout: `1/3 · 33%`.
 *
 * One formatter for both the reader and the sidebar entry, so the two can
 * never disagree — the whole reason plan state lives in a store.
 *
 * @param {number} done
 * @param {number} total
 * @param {number} [pct] — server-supplied percentage, if known
 * @returns {string}
 */
export function formatProgress(done, total, pct) {
  const d = Number.isFinite(Number(done)) ? Math.max(0, Number(done)) : 0;
  const t = Number.isFinite(Number(total)) ? Math.max(0, Number(total)) : 0;
  return `${d}/${t} \u00b7 ${progressPercent(d, t, pct)}%`;
}

/* ==================================================================
 * Environment adapters — every one is optional at import time so this
 * module loads under `node --test` with no DOM and no Alpine.
 * ================================================================== */

/**
 * Render a plan document to sanitised HTML using the app's ONE renderer.
 *
 * `renderMarkdown` (components.js) is `marked({gfm: true}) → DOMPurify →
 * anchor-harden → hljs`, with ```mermaid fences swapped for placeholder divs.
 * gfm is what turns the checkpoint pipe table into a real `<table>` and the
 * milestones into a task list, which is exactly what the phase-4 assertions
 * inspect. Frontmatter is stripped first so it cannot leak into the text.
 *
 * @param {string} raw
 * @returns {string} HTML for x-html
 */
function renderPlanDocument(raw) {
  const text = stripFrontmatter(raw || '');
  if (!text) return '';
  if (typeof renderMarkdown === 'function') return renderMarkdown(text);
  /* No components.js (unit tests): degrade to escaped text rather than
     injecting unsanitised markup. */
  return `<pre>${text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')}</pre>`;
}

/**
 * Let Alpine flush its reactive effects to the DOM.
 *
 * A store has no `$nextTick`, but `Alpine.nextTick` is the same queue. Two
 * ticks: the first drains the effect that reassigns `markdownHtml`, the second
 * waits for that effect's DOM mutation to be applied — the pattern
 * courseExplorer and notesPanel already use before querying rendered nodes.
 */
async function flushAlpine() {
  const alpine = globalThis.Alpine;
  if (alpine && typeof alpine.nextTick === 'function') {
    try {
      await alpine.nextTick();
      await alpine.nextTick();
      return;
    } catch {
      /* fall through to the timer */
    }
  }
  await new Promise((resolve) => setTimeout(resolve, 0));
}

/**
 * Read an error message out of a failed response without throwing.
 *
 * FastAPI's `detail` is a string for most refusals but an OBJECT for the
 * activation refusal (`{message, ready, blockers, nudges}`), and the blockers
 * in that object are the only place the real reason exists. Both shapes are
 * returned so callers can use whichever they need.
 *
 * @param {Response} resp
 * @param {string} fallback
 * @returns {Promise<{message: string, payload: object|null}>}
 */
async function readError(resp, fallback) {
  let detail;
  try {
    detail = (await resp.json()).detail;
  } catch {
    /* non-JSON body — fall back to the status line */
  }
  if (typeof detail === 'string' && detail.trim()) {
    return { message: detail.trim(), payload: null };
  }
  if (detail && typeof detail === 'object') {
    const message = String(detail.message || '').trim();
    return { message: message || fallback, payload: detail };
  }
  const status = `${resp.status} ${resp.statusText || ''}`.trim();
  return { message: status || fallback, payload: null };
}

/** A blank create form. One function so `startCreate()` cannot half-reset it. */
function blankForm() {
  return {
    /* The brain dump is the PRIMARY field: a blank five-field form asks the
       learner for the decomposition they do not yet have, which is the exact
       paralysis this tool exists to prevent. Carried through to the plan's
       notes on create so the reasoning survives the plan. */
    braindump: '',
    title: '',
    why: '',
    success: '',
    topics: '',
    milestones: '',
  };
}

/* ==================================================================
 * The shared store — Alpine.store('plans')
 * ================================================================== */

export const plansStore = {
  /* ---- contract keys, bound read-only by the markup ---- */
  items: [],
  selected: null,
  markdown: '',
  evaluation: null,
  loading: false,
  error: '',
  recordStatus: '',

  /* ---- derived / view state ---- */
  markdownHtml: '',
  creating: false,
  form: blankForm(),
  interview: { questions: [], seed: null },
  /* Set from the RESPONSE, never optimistically: markup that binds
     `plan-eval-phase` to this must never claim a phase whose verdict has not
     arrived. `pendingPhase` is the optimistic one, for button styling. */
  evalPhase: '',
  pendingPhase: '',

  /* ---- in-flight flags ---- */
  saving: false,
  evaluating: false,
  recording: false,
  activating: false,
  togglingIndex: -1,
  /* A REAL completion flag, not a proxy signal: `items: []` is already truthy
     before init runs and `loading` flips before the data is applied, so
     neither can be used to answer "is the store ready?". */
  initDone: false,

  /* Monotonic guard. Initialised to 0 — `undefined + 1` is NaN, and a NaN
     guard only ever "works" because NaN !== NaN. Bumped on every user action;
     re-checked after every await so a slow response cannot overwrite a newer
     selection. */
  _epoch: 0,
  _afterRender: [],
  _evalPromise: null,

  _bump() {
    this._epoch += 1;
    return this._epoch;
  },

  /**
   * Register a callback to run after the rendered document reaches the DOM.
   *
   * The store owns the HTML but has no `$root`, so the second-pass mermaid
   * render has to be driven by the component. Callers MUST register before
   * their first await (see `plansPanel().init`): a listener added after two
   * awaits loses every event dispatched in that window, permanently.
   *
   * @param {Function} fn
   */
  onRendered(fn) {
    if (typeof fn === 'function' && !this._afterRender.includes(fn)) {
      this._afterRender.push(fn);
    }
  },

  async init() {
    /* Alpine calls this for us at alpine:init (same as the nav store). Loading
       here — rather than on first paint of the panel — is what makes a full
       browser reload reconstruct the list from persistence. */
    await this.load();
  },

  /** Load the plan list. Safe to call repeatedly. */
  async load() {
    const epoch = this._bump();
    this.loading = true;
    try {
      const resp = await fetch(API);
      if (epoch !== this._epoch) return;
      if (!resp.ok) {
        const { message } = await readError(resp, 'could not load study plans');
        if (epoch === this._epoch) this.error = message;
        return;
      }
      const data = await resp.json();
      if (epoch !== this._epoch) return;
      this.items = Array.isArray(data.plans) ? data.plans : [];
      this.error = '';
    } catch (e) {
      if (epoch === this._epoch) this.error = `Network error: ${e.message ?? e}`;
    } finally {
      /* Only after the data is applied — a flag that flips early is a flag
         that produces intermittent failures. */
      if (epoch === this._epoch) {
        this.loading = false;
        this.initDone = true;
      }
    }
  },

  /** Alias so markup can read as intent rather than mechanism. */
  async refresh() {
    await this.load();
  },

  /**
   * Open a plan in the reader. Accepts an id or a summary object, because a
   * sidebar `x-for` naturally has the object in hand.
   *
   * @param {string|{plan_id: string}} planOrId
   */
  async select(planOrId) {
    const planId = typeof planOrId === 'string' ? planOrId : planOrId?.plan_id;
    if (!planId) return;
    const epoch = this._bump();
    this.loading = true;
    this.error = '';
    this.creating = false;
    /* A checkpoint belongs to the plan it was recorded against. */
    this.evaluation = null;
    this.evalPhase = '';
    this.pendingPhase = '';
    this.recordStatus = '';
    try {
      await this._fetchDetail(planId, epoch);
    } catch (e) {
      if (epoch === this._epoch) this.error = `Network error: ${e.message ?? e}`;
    } finally {
      if (epoch === this._epoch) this.loading = false;
    }
  },

  /** True when `planOrId` is the plan currently open in the reader. */
  isSelected(planOrId) {
    const planId = typeof planOrId === 'string' ? planOrId : planOrId?.plan_id;
    return !!planId && !!this.selected && this.selected.plan_id === planId;
  },

  /* ---------------- create ---------------- */

  /**
   * Open a blank create form.
   *
   * Clearing `selected` is load-bearing, not tidiness: without it the reader
   * keeps showing the PREVIOUS plan while the form is open, and a test that
   * waits for `plan-detail` after submitting would pass against stale content.
   */
  startCreate() {
    this.creating = true;
    this.form = blankForm();
    this.selected = null;
    this.markdown = '';
    this.markdownHtml = '';
    this.evaluation = null;
    this.evalPhase = '';
    this.pendingPhase = '';
    this.recordStatus = '';
    this.error = '';
    /* Seed suggestions are a nicety; the form must appear regardless, so this
       is intentionally not awaited. */
    this.loadInterview();
  },

  cancelCreate() {
    this.creating = false;
    this.form = blankForm();
    this.error = '';
  },

  /** Fetch interview questions + history-derived seed. Never blocks the form. */
  async loadInterview() {
    if (this.interview.questions.length) return;
    try {
      const resp = await fetch(`${API}/interview`);
      if (!resp.ok) return;
      const data = await resp.json();
      this.interview = {
        questions: Array.isArray(data.questions) ? data.questions : [],
        seed: data.seed ?? null,
      };
    } catch {
      /* the form works without suggestions */
    }
  },

  /** A title is the only field the API requires; everything else is honest gaps. */
  canSubmit() {
    return !this.saving && String(this.form.title || '').trim().length > 0;
  },

  /**
   * Create the plan, then open it.
   *
   * The structured fields are the API's input and the learner's editable
   * result; the brain dump rides along in `notes` so the reasoning behind the
   * decomposition is not thrown away once the plan exists.
   */
  async submitPlan() {
    if (!this.canSubmit()) return;
    const epoch = this._bump();
    this.saving = true;
    this.error = '';
    const body = {
      title: String(this.form.title || '').trim(),
      answers: {
        why: String(this.form.why || '').trim(),
        success: splitLines(this.form.success),
        topics: splitLines(this.form.topics),
        milestones: parseMilestoneLines(this.form.milestones),
        notes: String(this.form.braindump || '').trim(),
      },
    };
    try {
      const resp = await fetch(API, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (epoch !== this._epoch) return;
      if (!resp.ok) {
        const { message } = await readError(resp, 'could not create the plan');
        if (epoch === this._epoch) this.error = message;
        return;
      }
      const data = await resp.json();
      if (epoch !== this._epoch) return;
      const planId = data.plan?.plan_id;
      this.creating = false;
      this.form = blankForm();
      await this._reloadList(epoch);
      if (epoch !== this._epoch) return;
      if (planId) await this._fetchDetail(planId, epoch);
    } catch (e) {
      if (epoch === this._epoch) this.error = `Network error: ${e.message ?? e}`;
    } finally {
      if (epoch === this._epoch) this.saving = false;
    }
  },

  /** Name-compatible alias for markup that reads `createPlan()`. */
  async createPlan() {
    await this.submitPlan();
  },

  /* ---------------- milestones ---------------- */

  /**
   * Flip one milestone and re-read the document.
   *
   * Not optimistic: the POST returns the authoritative summary, and the plan
   * document has to be re-fetched so the rendered `- [x]` and the counts
   * cannot drift from each other. Persistence across a browser reload is the
   * point — the checkbox state must live on the server, never only here.
   *
   * @param {number} index
   */
  async toggleMilestone(index) {
    const planId = this.selected?.plan_id;
    const i = Number(index);
    if (!planId || !Number.isInteger(i) || i < 0) return;
    if (this.togglingIndex !== -1) return;
    const epoch = this._bump();
    this.togglingIndex = i;
    this.error = '';
    try {
      const resp = await fetch(
        `${API}/${encodeURIComponent(planId)}/milestones/${i}/toggle`,
        { method: 'POST' }
      );
      if (epoch !== this._epoch) return;
      if (!resp.ok) {
        const { message } = await readError(resp, 'could not update the milestone');
        if (epoch === this._epoch) this.error = message;
        return;
      }
      const data = await resp.json();
      if (epoch !== this._epoch) return;
      this._applySummary(data.plan);
      if (this.selected?.milestones?.[i]) {
        this.selected.milestones[i].done = !!data.done;
      }
      await this._fetchDetail(planId, epoch);
    } catch (e) {
      if (epoch === this._epoch) this.error = `Network error: ${e.message ?? e}`;
    } finally {
      if (epoch === this._epoch) this.togglingIndex = -1;
    }
  },

  /* ---------------- evaluation ---------------- */

  /**
   * Preview a checkpoint without recording it.
   *
   * The previous evaluation is left on screen while the new one is in flight:
   * blanking it would hide `plan-evaluation` mid-interaction, and hiding an
   * element another surface is about to read is how this panel's predecessors
   * broke.
   *
   * @param {'start'|'mid'|'end'} phase
   */
  async evaluate(phase) {
    const planId = this.selected?.plan_id;
    const want = String(phase || 'start').toLowerCase();
    if (!planId) return;
    /* Synchronous, so a record click that lands before the response still
       knows which phase the learner asked for. */
    this.pendingPhase = want;
    const epoch = this._bump();
    this.evaluating = true;
    this.error = '';
    const run = (async () => {
      try {
        const resp = await fetch(
          `${API}/${encodeURIComponent(planId)}/evaluate?phase=${encodeURIComponent(want)}`
        );
        if (epoch !== this._epoch) return;
        if (!resp.ok) {
          const { message } = await readError(resp, `could not evaluate the ${want} checkpoint`);
          if (epoch === this._epoch) this.error = message;
          return;
        }
        const data = await resp.json();
        if (epoch !== this._epoch) return;
        this._applyEvaluation(data.evaluation, want);
      } catch (e) {
        if (epoch === this._epoch) this.error = `Network error: ${e.message ?? e}`;
      } finally {
        if (epoch === this._epoch) this.evaluating = false;
      }
    })();
    this._evalPromise = run;
    await run;
    if (this._evalPromise === run) this._evalPromise = null;
  },

  /**
   * Record the current checkpoint, then re-read the document.
   *
   * `recordStatus` is set LAST, after the re-render has flushed. It is the
   * signal the rest of the app (and the journey test) waits on, so setting it
   * before the appended checkpoint row exists would advertise a document that
   * has not been written yet.
   */
  async recordCheckpoint() {
    const planId = this.selected?.plan_id;
    if (!planId || this.recording) return;
    /* Let an evaluation that is still in flight land first, so the recorded
       phase and the displayed verdict describe the same checkpoint. */
    if (this._evalPromise) {
      try {
        await this._evalPromise;
      } catch {
        /* its own handler already reported */
      }
    }
    const phase = String(
      this.pendingPhase || this.evaluation?.phase || this.evalPhase || 'start'
    ).toLowerCase();
    const epoch = this._bump();
    this.recording = true;
    this.error = '';
    this.recordStatus = '';
    try {
      const resp = await fetch(`${API}/${encodeURIComponent(planId)}/evaluate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ phase, append_to_plan: true }),
      });
      if (epoch !== this._epoch) return;
      if (!resp.ok) {
        const { message } = await readError(resp, 'could not record the checkpoint');
        if (epoch === this._epoch) this.error = message;
        return;
      }
      const data = await resp.json();
      if (epoch !== this._epoch) return;
      this._applyEvaluation(data.evaluation, phase);
      /* The server appended a row to the plan's checkpoint table. */
      await this._reloadList(epoch);
      if (epoch !== this._epoch) return;
      await this._fetchDetail(planId, epoch);
      if (epoch !== this._epoch) return;
      const verdict = this.evaluation?.verdict || '';
      this.recordStatus = verdict
        ? `Recorded ${phase} checkpoint \u2014 ${verdict}`
        : `Recorded ${phase} checkpoint`;
    } catch (e) {
      if (epoch === this._epoch) this.error = `Network error: ${e.message ?? e}`;
    } finally {
      if (epoch === this._epoch) this.recording = false;
    }
  },

  /* ---------------- activation ---------------- */

  /**
   * Ask the server to activate the plan.
   *
   * A refusal is surfaced, never swallowed, and the local status is NOT
   * changed on failure — a refusal that leaves the pill reading "active" has
   * not refused anything. The 422 body carries fresh readiness, so the
   * blockers list is updated from it too.
   *
   * @param {string} [status] — defaults to 'active'
   */
  async activate(status = 'active') {
    const planId = this.selected?.plan_id;
    if (!planId || this.activating) return;
    const want = String(status || 'active').toLowerCase();
    const epoch = this._bump();
    this.activating = true;
    this.error = '';
    try {
      const resp = await fetch(`${API}/${encodeURIComponent(planId)}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: want }),
      });
      if (epoch !== this._epoch) return;
      if (!resp.ok) {
        const { message, payload } = await readError(resp, 'plan is not ready to activate');
        if (epoch !== this._epoch) return;
        if (payload && this.selected) {
          this.selected.readiness = {
            plan_id: payload.plan_id ?? this.selected.plan_id,
            ready: !!payload.ready,
            blockers: Array.isArray(payload.blockers) ? payload.blockers : [],
            nudges: Array.isArray(payload.nudges) ? payload.nudges : [],
          };
        }
        const reasons = this.blockers;
        this.error = reasons.length
          ? `Cannot activate \u2014 ${reasons.join(' ')}`
          : `Cannot activate \u2014 ${message}`;
        return;
      }
      const data = await resp.json();
      if (epoch !== this._epoch) return;
      this._applySummary(data.plan);
      if (this.selected && data.readiness) this.selected.readiness = data.readiness;
      await this._fetchDetail(planId, epoch);
    } catch (e) {
      if (epoch === this._epoch) this.error = `Network error: ${e.message ?? e}`;
    } finally {
      if (epoch === this._epoch) this.activating = false;
    }
  },

  dismissError() {
    this.error = '';
  },

  /* ---------------- derived views ---------------- */

  /** `1/3 · 33%` for a summary item or the open plan. */
  progressLabel(planLike) {
    const plan = planLike || this.selected;
    if (!plan) return formatProgress(0, 0, 0);
    return formatProgress(plan.milestone_done, plan.milestone_total, plan.progress_pct);
  },

  get progressText() {
    return this.progressLabel(this.selected);
  },

  get milestones() {
    return this.selected?.milestones ?? [];
  },

  get blockers() {
    const list = this.selected?.readiness?.blockers;
    return Array.isArray(list) ? list : [];
  },

  get nudges() {
    const list = this.selected?.readiness?.nudges;
    return Array.isArray(list) ? list : [];
  },

  get ready() {
    return !!this.selected?.readiness?.ready;
  },

  get recommendations() {
    const list = this.evaluation?.recommendations;
    return Array.isArray(list) ? list : [];
  },

  get verdict() {
    return this.evaluation?.verdict ?? '';
  },

  get headline() {
    return this.evaluation?.headline ?? '';
  },

  get hasPlans() {
    return this.items.length > 0;
  },

  /* Deliberately NOT `!loading && !items.length`: the empty state is the first
     screen a brand-new learner sees, and gating it on a flag means a stuck
     flag renders a silent blank list instead. */
  get isEmpty() {
    return this.items.length === 0;
  },

  /* ---------------- internals ---------------- */

  /**
   * Fetch one plan's detail and install it as `selected` + rendered document.
   * Does NOT bump the epoch — callers own their epoch and pass it in.
   *
   * @param {string} planId
   * @param {number} epoch
   * @returns {Promise<boolean>} whether the write happened
   */
  async _fetchDetail(planId, epoch) {
    const resp = await fetch(`${API}/${encodeURIComponent(planId)}`);
    if (epoch !== this._epoch) return false;
    if (!resp.ok) {
      const { message } = await readError(resp, `could not load plan ${planId}`);
      if (epoch === this._epoch) this.error = message;
      return false;
    }
    const data = await resp.json();
    if (epoch !== this._epoch) return false;
    /* Flatten the payload: the summary's fields sit alongside the structured
       sections so markup binds `selected.title` and `selected.milestones`
       without knowing which half of the response each came from. */
    this.selected = {
      ...(data.plan || {}),
      plan_id: data.plan?.plan_id || planId,
      mission: data.mission || { why: '', success: [], constraints: [], out_of_scope: [] },
      milestones: Array.isArray(data.milestones) ? data.milestones : [],
      learning_records: Array.isArray(data.learning_records) ? data.learning_records : [],
      resources: Array.isArray(data.resources) ? data.resources : [],
      checkpoints: Array.isArray(data.checkpoints) ? data.checkpoints : [],
      readiness: data.readiness || { plan_id: planId, ready: false, blockers: [], nudges: [] },
    };
    this._applySummary(data.plan);
    await this._setMarkdown(data.markdown || '');
    return true;
  },

  /** Re-read the list without disturbing the caller's epoch semantics. */
  async _reloadList(epoch) {
    try {
      const resp = await fetch(API);
      if (epoch !== this._epoch || !resp.ok) return;
      const data = await resp.json();
      if (epoch !== this._epoch) return;
      this.items = Array.isArray(data.plans) ? data.plans : [];
    } catch {
      /* the existing list stays; the action itself already reported */
    }
  },

  /**
   * Merge a server summary into the list entry and the open plan.
   *
   * `splice` rather than in-place mutation, matching the codebase's
   * `_replaceItem`: it is the unambiguous signal to Alpine's array proxy and
   * it keeps the sidebar's progress in lockstep with the reader's.
   */
  _applySummary(summary) {
    if (!summary || !summary.plan_id) return;
    const idx = this.items.findIndex((p) => p.plan_id === summary.plan_id);
    if (idx !== -1) this.items.splice(idx, 1, { ...this.items[idx], ...summary });
    else this.items.push(summary);
    if (this.selected && this.selected.plan_id === summary.plan_id) {
      Object.assign(this.selected, summary);
    }
  },

  _applyEvaluation(evaluation, phase) {
    if (!evaluation) return;
    this.evaluation = evaluation;
    this.evalPhase = String(evaluation.phase || phase || '').toLowerCase();
    this.pendingPhase = this.evalPhase;
  },

  /**
   * Install the rendered document and let the DOM catch up.
   *
   * The clear-then-set guard is narrow on purpose. `renderPlanDocument` is
   * pure, so a re-render that produces a byte-identical string leaves
   * Alpine's `x-html` effect with nothing to do — it never rewrites the DOM,
   * the already-rendered mermaid placeholder keeps its old SVG and has lost
   * its `data-src`, and the second pass finds nothing. That only matters when
   * a diagram is actually present, so the flicker is paid only then.
   */
  async _setMarkdown(raw) {
    const html = renderPlanDocument(raw);
    if (html && html === this.markdownHtml && html.includes('mermaid-diagram')) {
      this.markdownHtml = '';
      await flushAlpine();
    }
    this.markdown = raw || '';
    this.markdownHtml = html;
    await this._notifyRendered();
  },

  /** Flush, then hand off to whoever owns a DOM root (the panel). */
  async _notifyRendered() {
    await flushAlpine();
    for (const hook of this._afterRender) {
      try {
        await hook();
      } catch (err) {
        console.warn('[plansPanel] after-render hook failed:', err);
      }
    }
  },
};

/* ==================================================================
 * The content-column component — Alpine.data via x-data="plansPanel()"
 * ================================================================== */

export function plansPanel() {
  return {
    _hooked: false,

    /**
     * Register the after-render hook BEFORE the first await.
     *
     * This ordering is the fix for a bug already paid for once in this app: a
     * listener registered after two awaits silently lost every event
     * dispatched in that window. The store may finish loading during this very
     * init, so the hook has to exist before anything yields.
     */
    async init() {
      const store = this._plans();
      if (store && !this._hooked) {
        store.onRendered(() => this.renderDiagrams());
        this._hooked = true;
      }
      if (store && !store.initDone && !store.loading) await store.load();
    },

    /**
     * The store, preferring Alpine's reactive proxy.
     *
     * Writing through `$store.plans` is what makes the sidebar re-render;
     * writes to the raw module object would not be observed. The raw object is
     * the fallback only for `node --test`, where no Alpine exists.
     */
    _plans() {
      if (this.$store && this.$store.plans) return this.$store.plans;
      const alpine = globalThis.Alpine;
      if (alpine && typeof alpine.store === 'function') {
        try {
          const store = alpine.store('plans');
          if (store) return store;
        } catch {
          /* not registered yet */
        }
      }
      return plansStore;
    },

    get plans() {
      return this._plans();
    },

    /* ---- state, forwarded ---- */
    get items() {
      return this._plans().items;
    },
    get selected() {
      return this._plans().selected;
    },
    get markdown() {
      return this._plans().markdown;
    },
    get markdownHtml() {
      return this._plans().markdownHtml;
    },
    get evaluation() {
      return this._plans().evaluation;
    },
    get loading() {
      return this._plans().loading;
    },
    get initDone() {
      return this._plans().initDone;
    },
    get recordStatus() {
      return this._plans().recordStatus;
    },
    get evalPhase() {
      return this._plans().evalPhase;
    },
    get pendingPhase() {
      return this._plans().pendingPhase;
    },
    get milestones() {
      return this._plans().milestones;
    },
    get blockers() {
      return this._plans().blockers;
    },
    get nudges() {
      return this._plans().nudges;
    },
    get ready() {
      return this._plans().ready;
    },
    get recommendations() {
      return this._plans().recommendations;
    },
    get verdict() {
      return this._plans().verdict;
    },
    get headline() {
      return this._plans().headline;
    },
    get progressText() {
      return this._plans().progressText;
    },
    get hasPlans() {
      return this._plans().hasPlans;
    },
    get isEmpty() {
      return this._plans().isEmpty;
    },
    get interview() {
      return this._plans().interview;
    },
    get saving() {
      return this._plans().saving;
    },
    get evaluating() {
      return this._plans().evaluating;
    },
    get recording() {
      return this._plans().recording;
    },
    get activating() {
      return this._plans().activating;
    },
    get togglingIndex() {
      return this._plans().togglingIndex;
    },

    /* `form` is the x-model target: the getter returns the store's OWN object,
       so `x-model="form.title"` writes land on the store rather than shadowing
       it with a component-local copy. */
    get form() {
      return this._plans().form;
    },

    /* Scalars markup may assign to need a setter as well as a getter — a
       getter-only property makes `creating = true` fail silently. */
    get creating() {
      return this._plans().creating;
    },
    set creating(value) {
      this._plans().creating = !!value;
    },
    get error() {
      return this._plans().error;
    },
    set error(value) {
      this._plans().error = value == null ? '' : String(value);
    },

    /* ---- actions, forwarded ---- */
    async load() {
      await this._plans().load();
    },
    async refresh() {
      await this._plans().refresh();
    },
    async select(planOrId) {
      await this._plans().select(planOrId);
    },
    isSelected(planOrId) {
      return this._plans().isSelected(planOrId);
    },
    startCreate() {
      this._plans().startCreate();
    },
    cancelCreate() {
      this._plans().cancelCreate();
    },
    canSubmit() {
      return this._plans().canSubmit();
    },
    async submitPlan() {
      await this._plans().submitPlan();
    },
    async createPlan() {
      await this._plans().submitPlan();
    },
    async toggleMilestone(index) {
      await this._plans().toggleMilestone(index);
    },
    async evaluate(phase) {
      await this._plans().evaluate(phase);
    },
    async recordCheckpoint() {
      await this._plans().recordCheckpoint();
    },
    async activate(status) {
      await this._plans().activate(status);
    },
    dismissError() {
      this._plans().dismissError();
    },
    progressLabel(planLike) {
      return this._plans().progressLabel(planLike);
    },

    /**
     * Second-pass mermaid render for the plan document.
     *
     * `$root`, NOT `$el`. Alpine resolves `$el` against the EVALUATION SCOPE,
     * and this runs from a store callback reached via a click handler — `$el`
     * would be whatever element invoked it, whose subtree holds no document
     * and therefore no placeholders. The pass would find nothing, return, and
     * leave every diagram unrendered with no throw and nothing in the console.
     * `$root` is the component root and is scope-stable; it is still guarded
     * because it can be undefined if this frame runs before mount.
     */
    async renderDiagrams() {
      if (typeof this.$nextTick === 'function') {
        await this.$nextTick();
        await this.$nextTick();
      }
      if (typeof _renderMermaidPlaceholders !== 'function') return;
      const root = this.$root || (typeof document !== 'undefined' ? document : null);
      if (!root) return;
      const reader = root.querySelector?.('[data-testid="plan-markdown"]');
      const visible = reader?.getClientRects?.().length > 0;
      const bounds = visible ? reader.getBoundingClientRect?.() : null;
      /* Do not consume data-src while x-show still hides the reader. The
         Architect approval path schedules a fresh pass after phase=detail. */
      if (!visible || Number(bounds?.width) <= 0 || Number(bounds?.height) <= 0) return;
      if (typeof _mermaidInitForPalette === 'function') {
        try {
          _mermaidInitForPalette();
        } catch {
          /* palette init is cosmetic; a failure must not stop the render */
        }
      }
      try {
        await _renderMermaidPlaceholders(reader);
      } catch (err) {
        console.warn('[plansPanel] mermaid pass failed:', err);
      }
    },
  };
}

/**
 * Register the store with Alpine. Call from an `alpine:init` listener.
 *
 * @param {object} alpine — the global Alpine instance
 */
export function registerPlansStore(alpine) {
  const target = alpine || globalThis.Alpine;
  if (!target || typeof target.store !== 'function') return null;
  target.store('plans', plansStore);
  return target.store('plans');
}
