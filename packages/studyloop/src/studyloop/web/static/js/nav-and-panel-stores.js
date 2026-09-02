/**
 * Boot-time Alpine stores for sidebar navigation and the third-column
 * toggle panels (Course Explorer, Parking Lot, Notes).
 *
 * Moved out of an inline <script> in index.html (ttyd retirement stage 4,
 * R-13b) so `script-src 'self'` can be a strict Content-Security-Policy
 * with no `'unsafe-inline'` exception. Runs as a plain classic script at
 * the same position the inline block used to occupy, registered on
 * `alpine:init` exactly as before — see components.js's own header comment
 * for why this file, components.js, and plans-panel.js each register
 * stores from independent `alpine:init` listeners rather than one shared
 * bootstrap.
 */
document.addEventListener('alpine:init', () => {
  /* ----------------------------------------------------------------
   * Course Explorer store — drives the sidebar toggle button state.
   * The full courseExplorer() component (in components.js) reads and
   * writes this store so the sidebar button and the panel stay in sync.
   * ---------------------------------------------------------------- */
  Alpine.store('explorer', {
    open: false,
    // These stubs fire if the sidebar button is clicked before the
    // courseExplorer() component mounts (very brief window at boot).
    // The full implementation lives in courseExplorer().toggle()/close()
    // which also drive the .app-layout.explorer-open CSS class.
    toggle() {
      this.open = !this.open;
      const layout = document.querySelector('.app-layout');
      if (layout) layout.classList.toggle('explorer-open', this.open);
    },
    close() {
      this.open = false;
      const layout = document.querySelector('.app-layout');
      if (layout) layout.classList.remove('explorer-open');
    },
  });

  /* ----------------------------------------------------------------
   * Parking Lot + Notes stores — boot stubs for the sidebar toggle
   * buttons. The full behaviour (lazy-fetch + close siblings) is wired
   * onto these by parkingPanel()/notesPanel() in their init(), mirroring
   * the explorer store above. Only one 3rd-column panel is open at once.
   * ---------------------------------------------------------------- */
  Alpine.store('parking', {
    open: false,
    toggle() {
      this.open = !this.open;
      const layout = document.querySelector('.app-layout');
      if (layout) layout.classList.toggle('parking-open', this.open);
    },
    close() {
      this.open = false;
      const layout = document.querySelector('.app-layout');
      if (layout) layout.classList.remove('parking-open');
    },
  });

  Alpine.store('notes', {
    open: false,
    toggle() {
      this.open = !this.open;
      const layout = document.querySelector('.app-layout');
      if (layout) layout.classList.toggle('notes-open', this.open);
    },
    close() {
      this.open = false;
      const layout = document.querySelector('.app-layout');
      if (layout) layout.classList.remove('notes-open');
    },
  });

  /* ----------------------------------------------------------------
   * Alpine.store('plans') is registered by plansPanel()
   * (js/components/plans-panel.js) — it owns the plan data and the
   * left-pane list reads it, because the sidebar and the
   * content-column reader are sibling subtrees that cannot share one
   * x-data scope.  Deliberately NOT registered here: a second
   * registration would silently replace whichever half won the race.
   * The sidebar bindings use optional chaining so they render blank,
   * not broken, before that module has installed the store.
   * ---------------------------------------------------------------- */

  /* ----------------------------------------------------------------
   * Navigation store — drives sidebar + view switching
   * ---------------------------------------------------------------- */
  Alpine.store('nav', {
    current: 'today',

    init() {
      const hash = window.location.hash.slice(1);
      const valid = ['today', 'flashcards', 'quizzes', 'generate', 'mastery', 'body-double', 'study-session', 'study-plans', 'settings', 'course-reader'];
      if (hash && valid.includes(hash)) this.current = hash;
    },

    go(view) {
      this.current = view;
      window.location.hash = view;
    },

    is(view) {
      return this.current === view;
    }
  });
});
