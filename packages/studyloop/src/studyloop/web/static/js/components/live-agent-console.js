/**
 * Live agent console — xterm.js terminal over the PTY transport, with an ACP chat
 * surface for agent-protocol sessions.
 *
 * ORIGIN SCOPING (read before changing the signature)
 * ---------------------------------------------------
 * `origin` says which view owns this console: 'study' or 'body-double'. TWO
 * instances live on the page at once, so every start AND stop event must be
 * filtered by origin — without the STOP guard, ending a study session tears down
 * the Body Double console and vice versa. See docs/adr/0002 and the
 * _ALLOWED_ORIGINS comment in web/routes/session/_start.py.
 *
 * The default value is load-bearing. The study console's markup calls
 * `liveAgentConsole()` with NO argument, and dozens of assertions across three
 * suites address that exact attribute string. Do not "tidy" the markup to
 * `liveAgentConsole('study')` — it means the same thing and breaks all of them.
 * ADR-0002 is still status Proposed; ratify it before rewriting those assertions.
 *
 * FREE-VARIABLE DEPENDENCIES
 * --------------------------
 * Calls `_escapeHtml()` and `renderMarkdown()` without importing them. Both are
 * top-level functions in components.js, which loads as a CLASSIC script and so
 * becomes global before this deferred module runs — and both are only called at
 * runtime, after Alpine init, so the ordering is safe either way. They are not
 * imported because components.js is not yet a module; when it is split, these
 * become real imports.
 *
 * KNOWN GAPS (see docs/handoffs/2026-08-22-frontend-modularisation-findings.md)
 * ---------------------------------------------------------------------------
 * The 3 TestLiveRefresh tests are red because this console has no LOAD-TIME
 * ADOPTION path: init() registers a study-session-start listener, but on a page
 * reload that event was dispatched before the page existed, so nothing ever mounts
 * a terminal. The fix is to read GET /api/session/state on init and, when a live
 * session's origin matches this console's, mount and connect. `origin` is already
 * echoed by that endpoint for exactly this purpose.
 *
 * Extracted verbatim from index.html lines 2652-3371.
 */
export function liveAgentConsole(origin = 'study') {
    return {
      /* ---- reactive state (bound to template) --------------------- */
      terminalMode: null,        /* 'xterm' | 'ttyd-iframe' | 'acp-chat' | null (idle) */
      transport: null,           /* 'pty' | 'acp' | 'ttyd' | null (idle) */
      connected: false,
      /* Monotonic guard so an in-flight _adoptLiveSession() fetch cannot mount
         over a newer real start/stop. Same pattern as reviewApp's
         _liveSessionEpoch; initialised to 0 deliberately, because an undefined
         counter makes the first bump NaN and the comparison then 'works' only
         by NaN !== NaN. */
      _adoptEpoch: 0,
      status: 'Waiting',
      statusDot: 'idle',         /* 'idle' | 'live' | 'error' */
      statusMessage: '',
      legacyTtydUrl: '',
      showJumpToBottom: false,
      acpInput: '',              /* bound to ACP input field */
      acpSending: false,         /* disables submit while a turn is in flight */

      /* ACP chat surface state (U2 — populated by U3+) */
      acpMessages: [],            /* {role: 'user'|'assistant'|'system', text, id?} */
      toolCallsById: new Map(),   /* keyed by toolCallId — U4 fills */
      streamingMessageId: null,   /* id of bubble currently being streamed — U3 */
      plan: null,                 /* {steps: [{title, status}]} | null — U5 */
      pendingPermission: null,    /* {toolCallId, options} | null — U6 */
      personaSetupInFlight: false, /* true during the invisible persona turn —
                                       drives the "Setting up your mentor…" status */

      /* ---- non-reactive internals (intentionally plain properties) */
      _term: null,
      _fitAddon: null,
      _webglAddon: null,
      _clipboardAddon: null,
      _ws: null,
      _resizeObserver: null,
      _scrollHandler: null,
      _suppressStreamingBubble: false,  /* true while the invisible persona-injection
                                            turn is in flight; cleared on first turn_end */

      init() {
        /* Listeners FIRST, before the await in _adoptLiveSession(). A handler
           must exist before the work that can emit its event. */
        window.addEventListener('study-session-start', (event) => {
          if (((event.detail && event.detail.origin) || 'study') !== origin) return;
          this._adoptEpoch += 1;   /* a real start supersedes any in-flight adopt */
          this.start(event.detail);
        });
        window.addEventListener('study-session-stop', (event) => {
          if (((event.detail && event.detail.origin) || 'study') !== origin) return;
          this._adoptEpoch += 1;
          this.stop();
        });
        /* LOAD-TIME ADOPTION. Everything above only reacts to an event, and after
           a page reload the study-session-start for a still-live session was
           dispatched before this page existed - so nothing mounted a terminal and
           the learner came back to an empty pane. Proven by a terminal-buffer
           artifact reading '<no buffer>' after reload: the terminal did not exist,
           rather than existing and being blank. sessionTimer() dispatches only on
           a FRESH start, never on restore, so this console has to adopt on its
           own rather than wait to be told. */
        this._adoptLiveSession();
      },

      /* Mount an already-live session this view owns. Deliberately silent when
         there is nothing to adopt: no session, a session owned by the other
         surface, or one already ended. */
      async _adoptLiveSession() {
        const epoch = this._adoptEpoch;
        let state;
        try {
          const res = await fetch('/api/session/state', { cache: 'no-store' });
          if (!res.ok) return;
          state = await res.json();
        } catch { return; }
        /* A real start/stop landed while the fetch was in flight - it is newer
           information than this response, so drop it rather than fighting it. */
        if (epoch !== this._adoptEpoch) return;
        if (this.connected) return;                       /* already mounted */
        if (!state || !state.study_session_id) return;    /* nothing live */
        if (state.mode === 'ended') return;
        /* Ownership: the endpoint echoes `origin` for exactly this decision, and
           defaults it to 'study', so an absent origin and 'study' must behave
           identically. Adopting another surface's session is what the origin
           guard exists to prevent - two consoles on one PTY. */
        if (((state.origin) || 'study') !== origin) return;
        this.start({
          topic: state.topic || '',
          origin,
          agent: state.agent || null,
          resolvedAgent: state.agent || null,
          studySessionId: state.study_session_id,
          transport: state.transport || 'pty',
          wsUrl: state.reattach_url || null,
          /* Distinguishes this from a fresh start, so the status line does not
             claim to be 'Starting' something that has been running for an hour. */
          reattached: true,
        });
      },

      start(detail) {
        this.stop();
        const transport = detail.transport || 'pty';
        this.transport = transport;
        if (transport === 'acp' && detail.wsUrl) {
          this._mountAcpChat(detail);
        } else if (transport === 'pty' && detail.wsUrl) {
          this._mountXterm(detail);
        } else {
          this._mountLegacyIframe(detail);
        }
      },

      stop() {
        try {
          if (this._ws && this._ws.readyState === WebSocket.OPEN) {
            this._ws.send(JSON.stringify({ type: 'stop' }));
          }
        } catch { /* ignore */ }
        if (this._ws) { try { this._ws.close(); } catch { /* ignore */ } this._ws = null; }
        if (this._resizeObserver) {
          try { this._resizeObserver.disconnect(); } catch { /* ignore */ }
          this._resizeObserver = null;
        }
        if (this._term) {
          if (this._scrollHandler) {
            try { this._term.onScroll && this._term.onScroll(null); } catch { /* ignore */ }
            this._scrollHandler = null;
          }
          try { this._term.dispose(); } catch { /* ignore */ }
          this._term = null;
          this._fitAddon = null;
          this._webglAddon = null;
          this._clipboardAddon = null;
        }
        this.connected = false;
        this.statusDot = 'idle';
        this.showJumpToBottom = false;
        this.transport = null;
        this.acpInput = '';
        this.acpSending = false;
        this.acpMessages = [];
        this.toolCallsById = new Map();
        this.streamingMessageId = null;
        this.plan = null;
        this.pendingPermission = null;
        this.terminalMode = null;
      },

      /* ------------------------------------------------------------
       * xterm.js path (PTY transport — plan §1.7)
       * ------------------------------------------------------------ */
      _mountXterm(detail) {
        this.terminalMode = 'xterm';
        /* A resumed session has been running for a while - calling that 'Starting'
           is a lie the learner has to decode, and a test forbids it. */
        this.status = `${detail.reattached ? 'Reattached' : 'Starting'} · `
          + `${detail.resolvedAgent || detail.agent || 'Agent'}`;
        this.statusDot = 'idle';
        this.$nextTick(() => {
          if (!this.$refs.xtermMount || !window.Terminal) {
            this.status = 'xterm.js not loaded';
            this.statusDot = 'error';
            return;
          }
          const isMac = /mac/i.test(navigator.platform);
          const term = new window.Terminal({
            fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace',
            fontSize: 13,
            cursorBlink: true,
            cursorStyle: 'bar',
            scrollback: 5000,
            macOptionIsMeta: isMac,                 /* plan §UX: Meta keys via Opt */
            rightClickSelectsWord: false,           /* let native context menu show */
            convertEol: false,                      /* agent emits CRLF already */
            allowProposedApi: true,                 /* webgl addon needs this */
            theme: this._computeTheme(),
          });

          const fit = new window.FitAddon.FitAddon();
          term.loadAddon(fit);

          /* Clipboard addon — OSC 52 read/write so agent "copy to
             clipboard" emits reach the host without user clicks. */
          if (window.ClipboardAddon) {
            try {
              const clip = new window.ClipboardAddon.ClipboardAddon();
              term.loadAddon(clip);
              this._clipboardAddon = clip;
            } catch { /* clipboard addon optional */ }
          }

          term.open(this.$refs.xtermMount);

          /* WebGL renderer with canvas fallback (plan §renderer choice). */
          if (window.WebglAddon) {
            try {
              const webgl = new window.WebglAddon.WebglAddon();
              webgl.onContextLoss(() => {
                try { webgl.dispose(); } catch { /* ignore */ }
                this._webglAddon = null;
              });
              term.loadAddon(webgl);
              this._webglAddon = webgl;
            } catch { /* some browsers reject WebGL; canvas is fine */ }
          }

          try { fit.fit(); } catch { /* container may be hidden; retry on show */ }
          term.writeln('\x1b[2mConnecting to agent...\x1b[0m');

          /* ResizeObserver → TIOCSWINSZ. `onResize` fires when fit()
             changes dims; the outbound resize frame is sent from there. */
          this._resizeObserver = new ResizeObserver(() => {
            try { fit.fit(); } catch { /* container hidden — no-op */ }
          });
          this._resizeObserver.observe(this.$refs.xtermMount);

          /* Jump-to-bottom pill — xterm fires onScroll with the top line. */
          term.onScroll(() => {
            const buf = term.buffer.active;
            const atBottom = buf.viewportY + term.rows >= buf.length - 1;
            this.showJumpToBottom = !atBottom;
          });

          /* Ctrl-\ escapes focus: let the native event propagate so
             the document can move focus to the sidebar. */
          term.attachCustomKeyEventHandler((ev) => {
            if (ev.type === 'keydown' && ev.ctrlKey && ev.key === '\\') {
              this.blurTerminal();
              return false;  /* don't feed to PTY */
            }
            return true;
          });

          this._term = term;
          /* Flush anything that arrived before this mount existed. */
          if (this._preMount && this._preMount.length) {
            for (const chunk of this._preMount) {
              try { term.write(chunk); } catch { /* ignore */ }
            }
            this._preMount = [];
          }
          this._fitAddon = fit;

          this._openWebSocket(detail);
        });
      },

      /* ------------------------------------------------------------
       * ACP chat surface path (U2 scaffolding — U3+ adds rendering)
       * ------------------------------------------------------------ */
      _mountAcpChat(detail) {
        this.terminalMode = 'acp-chat';
        /* A resumed session has been running for a while - calling that 'Starting'
           is a lie the learner has to decode, and a test forbids it. */
        this.status = `${detail.reattached ? 'Reattached' : 'Starting'} · `
          + `${detail.resolvedAgent || detail.agent || 'Agent'}`;
        this.statusDot = 'idle';
        /* Initialise chat-surface state. _openWebSocket runs after $nextTick
           so the panel is already mounted in the DOM by the time the WS opens. */
        this.acpMessages = [];
        this.toolCallsById = new Map();
        this.streamingMessageId = null;
        this.plan = null;
        this.pendingPermission = null;
        this.$nextTick(() => {
          this._openWebSocket(detail);
        });
      },

      _openWebSocket(detail) {
        const scheme = window.location.protocol === 'https:' ? 'wss' : 'ws';
        const wsUrl = `${scheme}://${window.location.host}${detail.wsUrl}`;
        const ws = new WebSocket(wsUrl);
        ws.binaryType = 'arraybuffer';
        this._ws = ws;

        ws.addEventListener('open', () => {
          this.connected = true;
          this.statusDot = 'live';
          this.status = `Connected · ${detail.resolvedAgent || detail.agent || 'Agent'}`;
          /* Send initial resize so the child sees the real terminal size. */
          if (this._term) {
            ws.send(JSON.stringify({
              type: 'resize',
              cols: this._term.cols,
              rows: this._term.rows,
            }));
          }
          /* ACP-only: ship the persona as the first invisible session/prompt
             so the agent has system context before the user speaks. We bypass
             _sendAcpInput on purpose — that helper pushes a user bubble into
             acpMessages, which would render the persona text as if the user
             typed it. Suppressing the streaming bubble for this turn (see
             _appendAgentChunk + _finaliseStreamingBubble) keeps the agent's
             ack response out of the visible chat too. */
          if (this.transport === 'acp' && detail.personaText) {
            this._suppressStreamingBubble = true;
            this.personaSetupInFlight = true;
            this.acpSending = true;
            ws.send(JSON.stringify({ type: 'input', data: detail.personaText }));
          }
        });

        ws.addEventListener('message', (event) => {
          if (event.data instanceof ArrayBuffer) {
            /* Raw PTY bytes → terminal.write(Uint8Array). */
            /* Buffer when the terminal is not mounted yet instead of dropping.
               A reload reattaches the socket before xterm has opened, so the
               first bytes of a resumed session - including the reattach
               marker - were silently discarded. Any early output was. */
            if (this._term) {
              this._term.write(new Uint8Array(event.data));
            } else {
              this._preMount = this._preMount || [];
              this._preMount.push(new Uint8Array(event.data));
            }
            return;
          }
          let frame;
          try { frame = JSON.parse(event.data); } catch { return; }
          if (frame.type === 'started') {
            this.statusDot = 'live';
            this.status = `Connected · ${frame.agent}`;
          } else if (frame.type === 'stopped') {
            this.connected = false;
            this.statusDot = 'idle';
            this.status = `Session ended (${frame.reason}, rc=${frame.returncode ?? 'n/a'})`;
            if (this._term) {
              this._term.writeln(`\r\n\x1b[2m[session ended: ${frame.reason}]\x1b[0m`);
            }
          } else if (frame.type === 'transport_error') {
            this.statusDot = 'error';
            this.status = `Error: ${frame.message}`;
            this.acpSending = false;
          } else if (frame.type === 'agent_message') {
            /* Phase 2 ACP events (plan §2.3 Amendment #12).
               - agent_chunk: assistant text chunks → streaming bubble (U3).
               - turn_end: finalise bubble (acp-chat path).
               - tool_call, tool_call_update, plan, request_permission:
                 handled by dedicated methods (U4–U6). */
            if (frame.kind === 'agent_chunk') {
              const text = _extractChunkText(frame.payload);
              if (this.terminalMode === 'acp-chat' && text) {
                this._appendAgentChunk(text);
              }
            } else if (frame.kind === 'turn_end') {
              const reason = (frame.payload && frame.payload.reason) || 'end_turn';
              if (this.terminalMode === 'acp-chat') {
                this._finaliseStreamingBubble(reason);
              }
              this.acpSending = false;
              this.$nextTick(() => {
                if (this.$refs.acpInputField) this.$refs.acpInputField.focus();
              });
            } else if (frame.kind === 'tool_call') {
              if (this.terminalMode === 'acp-chat' && !this._suppressStreamingBubble) {
                this._handleToolCall(frame.payload);
              }
            } else if (frame.kind === 'tool_call_update') {
              if (this.terminalMode === 'acp-chat' && !this._suppressStreamingBubble) {
                this._handleToolCallUpdate(frame.payload);
              }
            } else if (frame.kind === 'plan' || frame.kind === 'plan_update') {
              if (this.terminalMode === 'acp-chat' && !this._suppressStreamingBubble) {
                this._handlePlan(frame.payload);
              }
            } else if (frame.kind === 'request_permission') {
              if (this.terminalMode === 'acp-chat') {
                if (this._suppressStreamingBubble) {
                  /* Auto-allow during the persona-injection turn. The user
                     hasn't typed anything yet — surfacing a permission
                     prompt for tool calls the persona triggered would be
                     confusing UX. Pick allow_once if available, else the
                     first option. */
                  const opts = (frame.payload && frame.payload.options) || [];
                  const chosen =
                    opts.find((o) => o && o.kind === 'allow_once') ||
                    opts.find((o) => o && o.kind === 'allow_always') ||
                    opts[0];
                  const rid = frame.payload && frame.payload._request_id;
                  if (rid && chosen && this._ws) {
                    this._ws.send(JSON.stringify({
                      type: 'permission_response',
                      requestId: rid,
                      outcome: { outcome: 'selected', optionId: chosen.optionId },
                    }));
                  }
                } else {
                  this._handleRequestPermission(frame.payload);
                }
              }
            }
          }
        });

        ws.addEventListener('close', () => {
          this.connected = false;
          if (this.statusDot !== 'error') this.statusDot = 'idle';
          if (!/ended/i.test(this.status)) this.status = 'Disconnected';
        });
        ws.addEventListener('error', () => {
          this.statusDot = 'error';
          this.status = 'Connection error';
        });

        /* Bind terminal input only after the WS is wired, not inside
           _mountXterm — otherwise keystrokes typed during the connecting
           window land on a dead socket and silently drop.
           ACP is turn-based (each send_input → full session/prompt turn)
           so xterm.onData would fire one turn per keystroke. ACP uses
           the dedicated input row + _sendAcpInput() instead. */
        if (this._term) {
          if (this.transport === 'pty') {
            this._term.onData((data) => {
              if (ws.readyState !== WebSocket.OPEN) return;
              ws.send(JSON.stringify({ type: 'input', data }));
            });
          }
          this._term.onResize(({ cols, rows }) => {
            if (ws.readyState !== WebSocket.OPEN) return;
            ws.send(JSON.stringify({ type: 'resize', cols, rows }));
          });
        }
      },

      /* ACP turn-based input: push user message to acpMessages, send as one
         frame, lock field until turn_end arrives so users don't fire
         concurrent turns (which Kiro rejects mid-flight). */
      _sendAcpInput() {
        const text = (this.acpInput || '').trim();
        if (!text || !this._ws || this._ws.readyState !== WebSocket.OPEN) return;
        if (this.acpSending) return;
        this.acpMessages.push({
          id: (window.crypto && crypto.randomUUID) ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`,
          role: 'user',
          text,
          html: null,
          status: 'final',
        });
        this._ws.send(JSON.stringify({ type: 'input', data: text }));
        this.acpInput = '';
        this.acpSending = true;
      },

      /* ----------------------------------------------------------
       * ACP chat bubble helpers (U3)
       * ---------------------------------------------------------- */

      _appendAgentChunk(text) {
        if (!text) return;
        /* Persona-injection turn: drop the agent's ack chunks on the floor.
           Cleared in _finaliseStreamingBubble on the matching turn_end. */
        if (this._suppressStreamingBubble) return;
        if (this.streamingMessageId === null) {
          /* Start a new streaming bubble. */
          const id = (window.crypto && crypto.randomUUID) ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`;
          this.streamingMessageId = id;
          this.acpMessages.push({
            id,
            role: 'assistant',
            text,
            html: null,
            status: 'streaming',
          });
        } else {
          /* Append to the open bubble. Mutate in place so Alpine re-renders. */
          const msg = this.acpMessages.find((m) => m.id === this.streamingMessageId);
          if (msg) {
            msg.text = msg.text + text;
          }
        }
        this._scrollChatToBottom();
      },

      _finaliseStreamingBubble(reason) {
        /* Persona-injection turn: clear suppression and release the input
           lock. Nothing was ever pushed to acpMessages on this turn, so no
           bubble to finalise — just hand control back to the user. */
        if (this._suppressStreamingBubble) {
          this._suppressStreamingBubble = false;
          this.personaSetupInFlight = false;
          this.acpSending = false;
          this.streamingMessageId = null;
          return;
        }
        if (this.streamingMessageId === null) return;
        const msg = this.acpMessages.find((m) => m.id === this.streamingMessageId);
        if (msg) {
          msg.html = this._renderMarkdown(msg.text);
          msg.status = 'final';
        }
        this.streamingMessageId = null;
        /* `reason` is the turn_end reason — currently informational only.
           U5 may surface it inline; for now we just clear streaming state. */
      },

      /* Delegates to the top-level renderMarkdown() in components.js.
         Kept as a method so existing callers in this template
         (x-html="_renderMarkdown(…)" and _handleTurnEnd) are unchanged. */
      _renderMarkdown(text) { return renderMarkdown(text); },

      /* Delegates to the top-level _escapeHtml() in components.js. */
      _escapeHtml(s) { return _escapeHtml(s); },

      _scrollChatToBottom() {
        this.$nextTick(() => {
          if (this.$refs.acpChatLog) {
            this.$refs.acpChatLog.scrollTop = this.$refs.acpChatLog.scrollHeight;
          }
        });
      },

      /* ----------------------------------------------------------
       * Tool-call card helpers (U4)
       * ---------------------------------------------------------- */

      _isShellTool(name) {
        return /^(bash|shell|exec|run)/i.test(name || '');
      },

      /* U5: status icon for plan step (matches CSS class precedent). */
      _planStepIcon(status) {
        const icons = {
          completed: '✓',
          in_progress: '⟳',
          failed: '✗',
          pending: '○',
        };
        return icons[status] || '○';
      },

      _handleToolCall(payload) {
        /* Accept either 'arguments' or 'args' field name (spec + convenience). */
        const toolCallId = payload && (payload.toolCallId || payload.id);
        const name = (payload && payload.name) || '?';
        const args = (payload && (payload.arguments || payload.args)) || {};
        if (!toolCallId) return;

        if (this.toolCallsById.has(toolCallId)) {
          /* Out-of-order safety: tool_call_update arrived first — fill in missing fields.
             Splice a new copy so Alpine's reactivity picks up the change. */
          const existing = this.toolCallsById.get(toolCallId);
          if (existing.name === '?') existing.name = name;
          if (!existing.args || Object.keys(existing.args).length === 0) existing.args = args;
          const idx = this.acpMessages.indexOf(existing);
          if (idx !== -1) {
            const updated = { ...existing };
            this.toolCallsById.set(toolCallId, updated);
            this.acpMessages.splice(idx, 1, updated);
          }
          return;
        }

        const msg = {
          kind: 'tool_call',
          id: toolCallId,
          name,
          args,
          status: 'pending',
          output: '',
          expanded: false,
        };
        this.acpMessages.push(msg);
        this.toolCallsById.set(toolCallId, msg);
        this._scrollChatToBottom();
      },

      _handleToolCallUpdate(payload) {
        const toolCallId = payload && (payload.toolCallId || payload.id);
        if (!toolCallId) return;

        let msg = this.toolCallsById.get(toolCallId);
        let isNew = false;
        if (!msg) {
          /* Defensive: create a placeholder card when update arrives before tool_call. */
          console.warn(`[U4] tool_call_update for unknown toolCallId="${toolCallId}" — creating placeholder`);
          msg = {
            kind: 'tool_call',
            id: toolCallId,
            name: '?',
            args: {},
            status: 'pending',
            output: '',
            expanded: false,
          };
          isNew = true;
        }

        /* Build the updated object as a new reference for Alpine reactivity. */
        const newStatus = payload.status || msg.status;
        let newOutput = msg.output || '';
        if (payload.output !== undefined && payload.output !== null) {
          const chunk = typeof payload.output === 'string'
            ? payload.output
            : JSON.stringify(payload.output);
          newOutput = newOutput + chunk;
        }
        const newExpanded = (newStatus === 'failed') ? true : msg.expanded;

        const updated = {
          ...msg,
          status: newStatus,
          output: newOutput,
          expanded: newExpanded,
        };

        this.toolCallsById.set(toolCallId, updated);

        if (isNew) {
          /* First time we see this id — push the placeholder card. */
          this.acpMessages.push(updated);
        } else {
          /* Existing card — splice-replace to trigger Alpine reactivity. */
          const idx = this.acpMessages.findIndex((m) => m.id === toolCallId);
          if (idx !== -1) {
            this.acpMessages.splice(idx, 1, updated);
          }
        }

        this._scrollChatToBottom();
      },

      /* U5: plan / plan_update handler. Both events replace this.plan in
         place — no history. Defensively ensures steps is always an array
         so x-for never sees null. Status strings are used as CSS class
         suffixes; normalise to lowercase to be safe. */
      _handlePlan(payload) {
        if (!payload || typeof payload !== 'object') {
          /* Graceful: empty or missing payload → no-op (don't crash). */
          return;
        }
        const rawSteps = Array.isArray(payload.steps) ? payload.steps : [];
        const steps = rawSteps.map((s) => ({
          title: s.title || '',
          status: (s.status || 'pending').toLowerCase(),
        }));
        /* Defer the plan reactive write to the next tick so it runs in a
           separate Alpine flush from any concurrent acpMessages.push calls.
           This prevents the "null (reading 'type')" race where Alpine's Kn
           directive-sort comparator reads .type on an uninitialised x-if
           template node while the x-for list is still mid-flush. */
        this.$nextTick(() => { this.plan = { steps }; });
      },

      /* U6.5: request_permission handler. Stores on pendingPermission (not in
         acpMessages) to sidestep the Alpine 3.14.8 null.type race — same
         trick as U5 this.plan. Sets acpSending = true to lock the input row
         for the duration. Defensive: missing / empty options → no-op rather
         than crash.

         _request_id is the JSON-RPC request id from the inbound
         session/request_permission frame. The route needs it to send the
         correctly-correlated JSON-RPC response back to the agent. */
      _handleRequestPermission(payload) {
        if (!payload || typeof payload !== 'object') return;
        const options = Array.isArray(payload.options) ? payload.options : [];
        if (options.length === 0) return;
        /* Defer the pendingPermission write to the next tick — same pattern as
           _handlePlan — so it runs in a separate Alpine flush from concurrent
           acpMessages mutations, preventing the null.type race. */
        const perm = {
          toolCallId: payload.toolCallId || '',
          requestId: payload._request_id != null ? payload._request_id : '',
          options,
        };
        this.acpSending = true;
        this.$nextTick(() => {
          this.pendingPermission = perm;
          this._scrollChatToBottom();
        });
      },

      /* U6.5: User selected an option. Sends a permission_response WS frame
         with requestId + outcome {outcome:"selected", optionId}, clears the
         prompt, and releases acpSending so the input row restores. */
      _selectPermissionOption(optionId) {
        const perm = this.pendingPermission;
        if (!perm) return;
        if (this._ws && this._ws.readyState === WebSocket.OPEN) {
          this._ws.send(JSON.stringify({
            type: 'permission_response',
            requestId: perm.requestId,
            outcome: { outcome: 'selected', optionId },
          }));
        }
        this.pendingPermission = null;
        this.acpSending = false;
        this.$nextTick(() => {
          if (this.$refs.acpInputField) this.$refs.acpInputField.focus();
        });
      },

      /* U6.5: User cancelled (prompt turn cancelled). Sends outcome:cancelled.
         Not auto-wired to session/cancel; exposed for completeness. */
      _cancelPermission() {
        const perm = this.pendingPermission;
        if (!perm) return;
        if (this._ws && this._ws.readyState === WebSocket.OPEN) {
          this._ws.send(JSON.stringify({
            type: 'permission_response',
            requestId: perm.requestId,
            outcome: { outcome: 'cancelled' },
          }));
        }
        this.pendingPermission = null;
        this.acpSending = false;
        this.$nextTick(() => {
          if (this.$refs.acpInputField) this.$refs.acpInputField.focus();
        });
      },

      _toggleToolCall(msg) {
        /* failed cards are always expanded; toggling is a no-op so they stay visible. */
        if (msg.status === 'failed') return;
        msg.expanded = !msg.expanded;
        const idx = this.acpMessages.indexOf(msg);
        if (idx !== -1) {
          const updated = { ...msg };
          this.toolCallsById.set(updated.id, updated);
          this.acpMessages.splice(idx, 1, updated);
        }
      },

      /* Rough theme map — pulls from CSS vars so xterm blends in. */
      _computeTheme() {
        const css = getComputedStyle(document.documentElement);
        const get = (name, fallback) => (css.getPropertyValue(name).trim() || fallback);
        return {
          background: get('--bg', '#1a1b26'),
          foreground: get('--text', '#c0caf5'),
          cursor: get('--accent', '#7aa2f7'),
          selectionBackground: get('--accent', '#7aa2f7') + '66',
        };
      },

      /* ------------------------------------------------------------
       * Legacy ttyd iframe path (transport=ttyd emergency fallback)
       * ------------------------------------------------------------ */
      _mountLegacyIframe(detail) {
        this.terminalMode = 'ttyd-iframe';
        const key = detail.studySessionId || `${Date.now()}`;
        const params = new URLSearchParams({
          session: key,
          agent: detail.resolvedAgent || detail.agent || 'auto',
          t: `${Date.now()}`,
        });
        this.legacyTtydUrl = `/terminal/?${params.toString()}`;
        this.$nextTick(() => {
          this.connected = true;
          this.status = `Legacy terminal · ${detail.resolvedAgent || detail.agent || 'Agent'}`;
          this.statusDot = 'live';
        });
      },

      /* ------------------------------------------------------------
       * UX helpers
       * ------------------------------------------------------------ */
      scrollToBottom() {
        if (this._term) this._term.scrollToBottom();
        this.showJumpToBottom = false;
      },

      blurTerminal() {
        /* Move focus out of xterm so keyboard nav can reach the sidebar.
           xterm captures all keydowns while its textarea has focus. */
        if (this._term) this._term.blur();
        const nav = document.querySelector('.sidebar-nav .nav-btn');
        if (nav) nav.focus();
      },

      async copySelection() {
        if (!this._term) return;
        const text = this._term.getSelection();
        if (!text) return;
        try {
          await navigator.clipboard.writeText(text);
        } catch { /* clipboard permission denied; silent */ }
      },
    };
  }
