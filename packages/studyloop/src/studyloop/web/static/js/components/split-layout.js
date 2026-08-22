/**
 * Alpine component factory for the resizable dashboard and terminal split pane.
 *
 * Invariant: create Split.js only after terminal availability and non-zero container
 * height are known; the retry loop covers events that fire before initialization
 * or while the tab is hidden.
 */
  export function splitLayout() {
    return {
      _split: null,
      _swapped: false,
      _termVisible: false,

      init() {
        const container = this.$el;
        const dash = container.querySelector('.split-dashboard');
        const term = container.querySelector('.split-terminal');
        if (!dash || !term) return;

        /* Terminal hidden until we know ttyd is available */
        term.style.display = 'none';

        /* Listen for terminal-ready from the terminalPanel() component */
        container.addEventListener('terminal-ready', (e) => {
          this._termVisible = e.detail.available;
          if (this._termVisible) {
            term.style.display = '';
            this._createSplit(dash, term);
          } else {
            this._destroySplit();
            term.style.display = 'none';
          }
        });

        /* Swap panel order (dashboard ↔ terminal) */
        container.addEventListener('swap-panels', () => {
          if (!this._termVisible) return;
          this._swapped = !this._swapped;
          this._destroySplit();
          container.style.flexDirection = this._swapped ? 'column-reverse' : 'column';
          this._createSplit(dash, term);
        });

        /* Re-init when tab becomes visible (handles hidden-tab zero-height) */
        Alpine.effect(() => {
          Alpine.store('nav')?.current;
          setTimeout(() => {
            if (container.offsetHeight && this._termVisible && !this._split) {
              term.style.display = '';
              this._createSplit(dash, term);
            }
          }, 200);
        });

        /* Poll until Split.js is actually created.
           Covers two races:
           1. terminal-ready fires before this listener is set up
           2. terminal-ready fires while container is still hidden
              (sessionActive not yet true) — _createSplit returns early
           Poll keeps retrying until _split exists. */
        const pollId = setInterval(() => {
          if (this._split) { clearInterval(pollId); return; }
          /* Detect terminal availability if event was missed */
          if (!this._termVisible) {
            const tp = term.querySelector('.terminal-panel');
            if (tp) {
              try {
                const data = Alpine.$data(tp);
                if (data && data.available) {
                  this._termVisible = true;
                  term.style.display = '';
                }
              } catch { /* Alpine not ready yet */ }
            }
          }
          /* Retry _createSplit if terminal is known but container was hidden */
          if (this._termVisible && !this._split) {
            this._createSplit(dash, term);
          }
        }, 500);
        setTimeout(() => clearInterval(pollId), 30000);
      },

      _createSplit(dash, term) {
        if (this._split) return;
        if (!this.$el.offsetHeight) return; /* hidden tab — skip */
        if (typeof Split === 'undefined') return; /* split.js not loaded — CSS fallback */
        this._split = Split([dash, term], {
          direction: 'vertical',
          sizes: [40, 60],
          minSize: [80, 80],
          gutterSize: 10,
          cursor: 'row-resize',
          onDragStart() {
            document.querySelectorAll('iframe')
              .forEach(f => f.style.pointerEvents = 'none');
          },
          onDragEnd() {
            document.querySelectorAll('iframe')
              .forEach(f => f.style.pointerEvents = '');
          },
        });
      },

      _destroySplit() {
        if (this._split) {
          this._split.destroy();
          this._split = null;
        }
      },
    };
  }
