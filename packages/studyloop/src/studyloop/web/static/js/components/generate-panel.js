/* ------------------------------------------------------------------
 * Generate panel — drives content generation jobs (U8).
 *
 * Extracted verbatim from index.html (was lines 2617-2927 of the inline
 * <script>); only `export` was added. Alpine component FACTORY, not a
 * class — Alpine wraps the returned object in a reactive Proxy, and
 * prototype methods are not own-properties, which breaks reactivity
 * and `this` binding.
 *
 * Job lifecycle:
 *   submit() → POST /api/content/generate
 *     → 202 { job_id, plan }   plan is an ESTIMATE (see invariant below)
 *     → 409                    another job is running; its detail goes to
 *                              `conflictBanner` (non-modal), NOT `formError`
 *     → other !ok / network    `formError`, job never starts
 *   on 202 → _openWS() opens WS /api/content/generate/ws?job_id=...
 *   WS frames handled:
 *     started         authoritative task_count (+ sources/kinds/…) —
 *                     reconciles the estimated 202 plan in place
 *     task_complete   appended to `tasks`; progressPct() = tasks/task_count
 *     all_done        SUCCESS terminal: summary set, running=false, ws.close()
 *     transport_error FAILURE terminal: error summary, running=false, ws.close()
 *   Frames that are not valid JSON are silently ignored (a malformed
 *   frame must not take the panel down mid-job).
 *   ws.onerror sets `formError`; ws.onclose sets running=false, so ANY
 *   close — expected or not — returns the UI to the form view.
 *
 * Invariants (non-obvious):
 *   - The form state is the source of truth; `running` flips the UI
 *     between form and progress views. 409 conflicts surface as a
 *     non-modal banner that includes the other job's id.
 *   - The 202 plan's task_count is an estimate; the server's `started`
 *     frame is authoritative and must win.
 *   - canSubmit() blocks while a keyed provider has no stored key
 *     (needsKey) or Bedrock has no AWS creds (needsBedrockCreds) —
 *     otherwise the job fails async on the backend instead of a clean
 *     disabled button. Bedrock is never keyed here (adapter==='bedrock'
 *     uses SigV4, not a typed key).
 *   - providerOptionLabel() builds the full <option> text because
 *     x-show/display:none does NOT work inside <option>.
 * ------------------------------------------------------------------ */
  export function generatePanel() {
    return {
      // Lookup data populated on init().
      publishers: [],
      courses: [],
      sections: [],
      strugglingTopics: [],
      providers: [],

      // Form state. Defaults match the plan: kinds=[flashcards],
      // count_per_source=10, on_existing=merge (least destructive).
      // `publisher` is the study-tree top level (ArjanCodes, CodeWithMosh…);
      // `course` the level below it; `section` an individual lesson file.
      form: {
        publisher: '',
        course: '',
        scope_kind: 'course',
        section: '',
        topic_slug: '',
        window_days: 14,
        kinds: ['flashcards'],
        count_per_source: 10,
        provider: '',
        model: '',
        on_existing: 'merge',
        backend: '',
      },
      formError: '',
      conflictBanner: '',

      // Inline API-key entry (shown when the chosen provider has no stored key).
      keyEntry: { value: '', saving: false, error: '', saved: false },

      // Job state. `running` gates the form vs progress UI.
      running: false,
      jobId: '',
      plan: null,
      tasks: [],
      finishedSummary: '',
      _ws: null,

      get modelsForProvider() {
        const p = this.providers.find((p) => p.slug === this.form.provider);
        return p ? p.models : [];
      },

      get selectedProvider() {
        return this.providers.find((p) => p.slug === this.form.provider) || null;
      },

      get needsKey() {
        // Show the key-entry form only for a chosen, keyed provider that is
        // not yet available. Bedrock uses AWS-SDK auth (adapter === 'bedrock')
        // and is never keyed here.
        const p = this.selectedProvider;
        return !!p && !p.available && p.adapter !== 'bedrock';
      },

      get needsBedrockCreds() {
        // Bedrock authenticates with AWS SigV4 credentials (IAM role /
        // AWS_PROFILE / access keys), not a typed API key. When it is chosen
        // but credentials don't resolve, show an AWS-specific hint instead of
        // the key-entry box.
        const p = this.selectedProvider;
        return !!p && !p.available && p.adapter === 'bedrock';
      },

      providerOptionLabel(p) {
        // Build the full <option> text here — x-show/display:none does NOT
        // work on elements nested inside <option> (browsers render the
        // flattened text content). Bedrock uses AWS creds, not a typed key.
        if (p.available) return p.label;
        const suffix = p.adapter === 'bedrock' ? ' — needs AWS credentials' : ' — needs API key';
        return p.label + suffix;
      },

      async init() {
        // The tree is 3-level: publisher → course → lesson file. Load the
        // publishers (study-tree top level) and the LLM providers up front;
        // courses load per-publisher, sections per-course.
        try {
          const [publishers, providers] = await Promise.all([
            fetch('/api/content/publishers').then((r) => r.ok ? r.json() : []),
            fetch('/api/content/providers').then((r) => r.ok ? r.json() : []),
          ]);
          this.publishers = publishers;
          this.providers = providers;
        } catch {
          /* lookups remain empty; the form still validates client-side */
        }
      },

      async onPublisherChange() {
        // Publisher changed → reset downstream selections and load its courses.
        this.form.course = '';
        this.form.section = '';
        this.courses = [];
        this.sections = [];
        if (!this.form.publisher) return;
        try {
          const r = await fetch(
            `/api/content/courses?publisher=${encodeURIComponent(this.form.publisher)}`
          );
          if (r.ok) this.courses = await r.json();
        } catch { /* leave empty */ }
      },

      async onCourseChange() {
        this.sections = [];
        this.strugglingTopics = [];
        this.form.section = '';
        if (!this.form.course) return;
        const pub = this.form.publisher
          ? `?publisher=${encodeURIComponent(this.form.publisher)}`
          : '';
        try {
          const r = await fetch(
            `/api/courses/${encodeURIComponent(this.form.course)}/sections${pub}`
          );
          if (r.ok) this.sections = await r.json();
        } catch { /* leave empty */ }
        try {
          const r = await fetch(`/api/history/struggling-topics?days=${this.form.window_days}`);
          if (r.ok) this.strugglingTopics = await r.json();
        } catch { /* leave empty */ }
      },

      onProviderChange() {
        // Reset model when provider changes; default-pick happens
        // server-side in get_generator() if blank.
        this.form.model = '';
        // Pick the matching backend automatically — the user shouldn't
        // care about the openai_compat / anthropic_compat distinction.
        const p = this.providers.find((x) => x.slug === this.form.provider);
        this.form.backend = p ? p.adapter : '';
        // Reset the key-entry form for the newly-selected provider.
        this.keyEntry = { value: '', saving: false, error: '', saved: false };
      },

      async refreshProviders() {
        // Re-fetch the provider list so `available` reflects a just-saved key.
        try {
          const r = await fetch('/api/content/providers');
          if (r.ok) this.providers = await r.json();
        } catch { /* keep the existing list */ }
      },

      async saveKey() {
        const value = this.keyEntry.value.trim();
        if (!value || this.keyEntry.saving) return;
        this.keyEntry.saving = true;
        this.keyEntry.error = '';
        this.keyEntry.saved = false;
        try {
          const r = await fetch('/api/content/secrets', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ provider: this.form.provider, key: value }),
          });
          if (r.ok) {
            // Tested + stored. Refresh providers so the option is enabled,
            // clear the raw key from memory, and confirm.
            this.keyEntry.value = '';
            this.keyEntry.saved = true;
            await this.refreshProviders();
          } else {
            // 400 = provider rejected the key; 422 = unknown/keyless provider.
            let detail = 'Could not verify the key.';
            try { detail = (await r.json()).detail || detail; } catch { /* keep default */ }
            this.keyEntry.error = detail;
          }
        } catch (e) {
          this.keyEntry.error = 'Network error testing the key. Is the server reachable?';
        } finally {
          this.keyEntry.saving = false;
        }
      },

      canSubmit() {
        if (this.running) return false;
        // A keyed provider with no key yet shows the inline key form; block
        // submission until the key is entered, else the job fails async on the
        // backend (CardGenerationError) instead of a clean disabled button.
        if (this.needsKey) return false;
        // Same reasoning for Bedrock: block until AWS credentials resolve,
        // else the job fails async with CardGenerationError.
        if (this.needsBedrockCreds) return false;
        if (!this.form.publisher) return false;
        if (!this.form.course) return false;
        if (this.form.kinds.length === 0) return false;
        if (this.form.scope_kind === 'section' && !this.form.section) return false;
        return true;
      },

      progressPct() {
        const total = this.plan?.task_count ?? 0;
        if (!total) return 0;
        return Math.min(100, Math.round((this.tasks.length / total) * 100));
      },

      async submit() {
        this.formError = '';
        this.conflictBanner = '';
        const body = {
          publisher: this.form.publisher,
          course: this.form.course,
          scope: {
            kind: this.form.scope_kind,
            publisher: this.form.publisher,
            course: this.form.course,
            section: this.form.section,
            topic_slug: this.form.topic_slug,
            window_days: this.form.window_days,
          },
          kinds: this.form.kinds,
          count_per_source: this.form.count_per_source,
          on_existing: this.form.on_existing,
        };
        if (this.form.backend) body.backend = this.form.backend;
        if (this.form.provider) body.provider = this.form.provider;
        if (this.form.model) body.model = this.form.model;

        let resp;
        try {
          resp = await fetch('/api/content/generate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
          });
        } catch (e) {
          this.formError = `Network error: ${e.message ?? e}`;
          return;
        }

        if (resp.status === 409) {
          const detail = (await resp.json()).detail ?? 'another job is already running';
          this.conflictBanner = detail;
          return;
        }
        if (!resp.ok) {
          const detail = (await resp.json().catch(() => ({}))).detail ?? `${resp.status} ${resp.statusText}`;
          this.formError = detail;
          return;
        }
        const data = await resp.json();
        this.jobId = data.job_id;
        this.plan = data.plan;
        this.tasks = [];
        this.finishedSummary = '';
        this.running = true;
        this._openWS();
      },

      _openWS() {
        const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const url = `${proto}//${window.location.host}/api/content/generate/ws?job_id=${encodeURIComponent(this.jobId)}`;
        const ws = new WebSocket(url);
        this._ws = ws;
        ws.onmessage = (ev) => {
          let frame;
          try {
            frame = JSON.parse(ev.data);
          } catch {
            return;
          }
          if (frame.type === 'started') {
            // Server's started frame has an authoritative task_count;
            // our 202 plan was an estimate. Reconcile.
            if (this.plan) {
              this.plan.task_count = frame.task_count;
              if (frame.sources) this.plan.sources = frame.sources;
              if (frame.kinds) this.plan.kinds = frame.kinds;
              if (frame.count_per_source) this.plan.count_per_source = frame.count_per_source;
              if (frame.backend) this.plan.backend = frame.backend;
              if (frame.provider) this.plan.provider = frame.provider;
              if (frame.model) this.plan.model = frame.model;
            }
          } else if (frame.type === 'task_complete') {
            this.tasks.push(frame);
          } else if (frame.type === 'all_done') {
            this.finishedSummary = `Done — ${frame.written} written, ${frame.failed} failed.`;
            this.running = false;
            ws.close();
          } else if (frame.type === 'transport_error') {
            this.finishedSummary = `Job error: ${frame.message}`;
            this.running = false;
            ws.close();
          }
        };
        ws.onerror = () => {
          this.formError = 'WebSocket connection lost.';
        };
        ws.onclose = () => {
          this.running = false;
        };
      },

      reset() {
        this.jobId = '';
        this.plan = null;
        this.tasks = [];
        this.finishedSummary = '';
        this.formError = '';
        this.conflictBanner = '';
        if (this._ws) {
          try { this._ws.close(); } catch {}
          this._ws = null;
        }
      },
    };
  }
