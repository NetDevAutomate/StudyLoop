/* ------------------------------------------------------------------
 * Settings panel — LLM Providers admin (add/change/delete/test keys)
 *
 * Alpine component factory. Manages the provider credential list
 * (API keys, the Bedrock bearer token, and the Ollama base URL): lets
 * the user type a value, POSTs it to /api/content/secrets (or the
 * Bedrock/Ollama-specific wrapper methods), and shows a per-slug
 * ok/error status message keyed by `slug`.
 *
 * Self-contained: every reference inside this factory is either
 * `this.*` (its own reactive state/methods) or the browser-global
 * `fetch`. It does NOT touch the `$store.settings` TTS engine tier
 * store (ttsEngineClass/Title/Label) that drives the TTS tier badge
 * elsewhere in the page — that store is defined outside this factory
 * and has no cross-reference here.
 *
 * Non-obvious invariant: `busy` is a single shared string (the slug
 * of whichever request is in flight), not a per-slug map — so only
 * one save/delete/test action can be in flight across the whole
 * panel at a time. saveKey/saveBearer/saveOllamaUrl/testOnly all
 * early-return if `this.busy` is already truthy.
 * ------------------------------------------------------------------ */
export function settingsPanel() {
    return {
      providers: [],
      inputs: {},          // { slug: string } live input values
      status: {},          // { slug: { ok: string, error: string } }
      busy: '',            // slug whose request is in flight

      async init() {
        await this.refreshProviders();
      },

      async refreshProviders() {
        try {
          const r = await fetch('/api/content/providers');
          if (r.ok) this.providers = await r.json();
        } catch { /* leave list as-is */ }
      },

      _ok(slug, msg) { this.status = { ...this.status, [slug]: { ok: msg, error: '' } }; },
      _err(slug, msg) { this.status = { ...this.status, [slug]: { ok: '', error: msg } }; },
      _clear(slug) { this.status = { ...this.status, [slug]: { ok: '', error: '' } }; },

      async _postSecret(storeName, value, uiSlug) {
        // Test + store via the secrets route; refresh on success.
        this._clear(uiSlug);
        try {
          const r = await fetch('/api/content/secrets', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ provider: storeName, key: value }),
          });
          if (r.ok) {
            this.inputs[uiSlug] = '';
            this._ok(uiSlug, 'Verified and saved.');
            await this.refreshProviders();
          } else {
            let detail = 'Could not verify the value.';
            try { detail = (await r.json()).detail || detail; } catch {}
            this._err(uiSlug, detail);
          }
        } catch { this._err(uiSlug, 'Network error.'); }
      },

      async _deleteSecret(storeName, uiSlug, okMsg) {
        this._clear(uiSlug);
        try {
          const r = await fetch(`/api/content/secrets/${storeName}`, { method: 'DELETE' });
          if (r.ok) { this._ok(uiSlug, okMsg); await this.refreshProviders(); }
          else { this._err(uiSlug, 'Delete failed.'); }
        } catch { this._err(uiSlug, 'Network error.'); }
      },

      async saveKey(slug) {
        const v = this.inputs[slug]?.trim();
        if (!v || this.busy) return;
        this.busy = slug;
        await this._postSecret(slug, v, slug);
        this.busy = '';
      },

      async deleteKey(slug) { await this._deleteSecret(slug, slug, 'Key deleted.'); },

      async saveBearer() {
        const v = this.inputs['bedrock']?.trim();
        if (!v || this.busy) return;
        this.busy = 'bedrock';
        await this._postSecret('bedrock_bearer_token', v, 'bedrock');
        this.busy = '';
      },

      async deleteBearer() {
        await this._deleteSecret('bedrock_bearer_token', 'bedrock', 'Bearer token deleted.');
      },

      async saveOllamaUrl() {
        const v = this.inputs['ollama']?.trim();
        if (!v || this.busy) return;
        this.busy = 'ollama';
        // ollama_base_url is a config value — stored without an auth-test.
        await this._postSecret('ollama_base_url', v, 'ollama');
        this.busy = '';
      },

      async testOnly(slug) {
        if (this.busy) return;
        this.busy = slug;
        this._clear(slug);
        try {
          const key = slug === 'bedrock' ? (this.inputs['bedrock']?.trim() || '') : '';
          const r = await fetch(`/api/content/providers/${slug}/test`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ key }),
          });
          const data = await r.json();
          if (data.ok) this._ok(slug, data.message || 'Credentials valid.');
          else this._err(slug, data.message || 'Test failed.');
        } catch { this._err(slug, 'Network error.'); }
        this.busy = '';
      },
    };
  }
