/*
 * Alpine.js terminal-panel factory: tracks the terminal proxy's availability,
 * embeds it or opens it in a pop-out window. The polling interval set by init()
 * must be cleared by destroy() so a torn-down component stops probing the API.
 */
  export function terminalPanel() {
    return {
      available: false,      /* panel exists (ttyd_port in state) */
      connected: false,      /* ttyd is actually reachable */
      embedded: true,
      poppedOut: false,
      _popoutWindow: null,
      _healthInterval: null,
      unavailableMessage: '',
      activeTtydUrl: '',

      get ttydUrl() { return window.__studyLoopTerminalUrl || '/terminal/'; },

      async init() {
        await this._checkAvailability();
        /* Re-check quickly during startup, then keep watching for session end. */
        this._healthInterval = setInterval(() => this._checkAvailability(), 1000);
      },

      async _checkAvailability() {
        try {
          const stateRes = await fetch('/api/session/state');
          const state = await stateRes.json();
          if (!state.ttyd_port) {
            this.available = false;
            this.connected = false;
            this.$dispatch('terminal-ready', { available: false });
            return;
          }
          /* Panel is available (state has ttyd_port) */
          if (!this.available) {
            this.available = true;
            this.$dispatch('terminal-ready', { available: true });
          }
          /* Probe the proxy to verify ttyd is actually reachable */
          const probe = await fetch('/terminal/', { method: 'HEAD' });
          if (probe.ok || probe.status === 401) {
            this.connected = true;
            this.unavailableMessage = '';
            if (this.activeTtydUrl !== this.ttydUrl) this.activeTtydUrl = this.ttydUrl;
          } else {
            this.connected = false;
            this.unavailableMessage = probe.status === 502 ? 'Starting terminal...' : 'Terminal session ended';
          }
        } catch {
          this.connected = false;
          this.unavailableMessage = 'Terminal unavailable';
        }
      },

      destroy() {
        if (this._healthInterval) clearInterval(this._healthInterval);
      },

      toggleEmbed() {
        if (!this.embedded && this._popoutWindow) {
          try { this._popoutWindow.close(); } catch {}
          this._popoutWindow = null;
        }
        this.embedded = !this.embedded;
        this.poppedOut = false;
      },

      popOut() {
        this._popoutWindow = window.open('/terminal/', 'studyloop-terminal',
          'width=900,height=600,menubar=no,toolbar=no');
        this.embedded = false;
        this.poppedOut = true;
      }
    };
  }
