/** AuDHD-low-friction state machine for create/revise planning conversations. */

import {
  PLANNING_PRIVACY_NOTICE,
  createPlanningConversation,
} from './planning-conversation.js';

export const ARCHITECT_PHASES = Object.freeze({
  IDLE: 'idle',
  CAPTURE: 'capture',
  CAPACITY: 'capacity',
  CONVERSATION: 'conversation',
  PROPOSAL: 'proposal',
  APPLYING: 'applying',
  REJECTED: 'rejected',
  DETAIL: 'detail',
});

function freshCapacity() {
  return { current: 0, max: 3, available: 3, can_create: true };
}

function safeMessages(value) {
  if (!Array.isArray(value)) return [];
  const seen = new Set();
  return value
    .filter((item) => item && ['learner', 'assistant'].includes(item.role))
    .filter((item) => {
      const key = `${item.sequence}:${item.role}:${item.content}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    })
    .sort((a, b) => Number(a.sequence || 0) - Number(b.sequence || 0));
}

export async function waitForVisibleLayout(element, options = {}) {
  const attempts = Math.max(1, Number(options.attempts) || 10);
  const nextFrame = options.nextFrame || (() => new Promise((resolve) => {
    const schedule = globalThis.requestAnimationFrame || ((callback) => setTimeout(callback, 16));
    schedule(resolve);
  }));
  for (let index = 0; index < attempts; index += 1) {
    const visible = element?.getClientRects?.().length > 0;
    const rect = visible ? element.getBoundingClientRect?.() : null;
    if (visible && Number(rect?.width) > 0 && Number(rect?.height) > 0) return true;
    if (index < attempts - 1) await nextFrame();
  }
  return false;
}

export function createPlanArchitectPanel(options = {}) {
  return {
    api: options.api || createPlanningConversation(),
    phase: ARCHITECT_PHASES.IDLE,
    mode: 'create',
    planId: null,
    conversationId: '',
    brainDump: '',
    turnText: '',
    contextLabel: '',
    contextText: '',
    contextFile: null,
    attachedContext: null,
    privacyNotice: PLANNING_PRIVACY_NOTICE,
    capacity: freshCapacity(),
    messages: [],
    proposal: null,
    retiredProposalDigest: '',
    latestTurn: null,
    pendingTurn: null,
    lastSequence: 0,
    busy: false,
    error: '',
    decisionStatus: '',
    decisionFinal: false,
    pendingDecision: null,
    _disconnect: null,
    _onPlanApplied: options.onPlanApplied || (async () => {}),
    _onProposal: options.onProposal || (async () => {}),
    _onDetailVisible: options.onDetailVisible || (async () => {}),

    get atCapacity() {
      return !this.capacity.can_create;
    },

    get isCapture() {
      return this.phase === ARCHITECT_PHASES.CAPTURE;
    },

    get isConversation() {
      return this.phase === ARCHITECT_PHASES.CONVERSATION;
    },

    get isProposal() {
      return this.phase === ARCHITECT_PHASES.PROPOSAL;
    },

    async beginCreate() {
      this.reset();
      this.mode = 'create';
      this.capacity = await this.api.readCapacity();
      if (!this.capacity.can_create) {
        this.phase = ARCHITECT_PHASES.CAPACITY;
        this.error = `${this.capacity.current} of ${this.capacity.max} current plans are already in use. Complete, abandon, or pause one before creating another.`;
        return;
      }
      this.phase = ARCHITECT_PHASES.CAPTURE;
    },

    async beginRevise(planId) {
      this.reset();
      this.mode = 'revise';
      this.planId = String(planId || '');
      this.phase = ARCHITECT_PHASES.CAPTURE;
    },

    canStart() {
      return !this.busy && this.phase === ARCHITECT_PHASES.CAPTURE && !!this.brainDump.trim();
    },

    async startConversation() {
      if (this.mode === 'create' && this.phase === ARCHITECT_PHASES.CAPACITY) return;
      if (!this.canStart()) return;
      this.busy = true;
      this.error = '';
      try {
        const input = this.mode === 'revise'
          ? { mode: 'revise', plan_id: this.planId }
          : { mode: 'create' };
        const run = await this.api.create(input);
        if (run.privacy_notice?.text !== PLANNING_PRIVACY_NOTICE) {
          throw new Error('The server privacy disclosure does not match this release.');
        }
        this.conversationId = run.conversation_id;
        this.capacity = run.capacity || this.capacity;
        if (this.contextFile) {
          this.attachedContext = await this.api.attachTextFile(
            this.conversationId,
            this.contextFile
          );
        } else if (this.contextText.trim()) {
          this.attachedContext = await this.api.attachPastedContext(this.conversationId, {
            label: this.contextLabel.trim() || 'Pasted study context',
            content: this.contextText,
          });
        }
        this.latestTurn = await this.api.submitTurn(this.conversationId, this.brainDump.trim());
        this.phase = ARCHITECT_PHASES.CONVERSATION;
        this.connect();
      } catch (error) {
        this.error = error?.message || String(error);
        if (!this.conversationId) this.phase = ARCHITECT_PHASES.CAPTURE;
      } finally {
        this.busy = false;
      }
    },

    connect() {
      this._disconnect?.();
      this._disconnect = this.api.connect(
        this.conversationId,
        this.lastSequence,
        async (event) => {
          this.lastSequence = Math.max(this.lastSequence, Number(event.sequence) || 0);
          await this.refresh();
        }
      );
    },

    async refresh() {
      if (!this.conversationId) return;
      this.applySnapshot(await this.api.get(this.conversationId));
    },

    applySnapshot(value) {
      if (!value) return;
      if (this.decisionFinal) return;
      this.conversationId = value.conversation_id || this.conversationId;
      this.mode = value.mode || this.mode;
      this.planId = value.plan_id ?? this.planId;
      this.capacity = value.capacity || this.capacity;
      this.messages = safeMessages(value.messages);
      this.latestTurn = value.latest_turn || this.latestTurn;
      this.lastSequence = Math.max(
        this.lastSequence,
        ...this.messages.map((message) => Number(message.sequence) || 0)
      );
      if (this.pendingDecision) {
        this.phase = this.busy ? ARCHITECT_PHASES.APPLYING : ARCHITECT_PHASES.PROPOSAL;
        return;
      }
      if (
        value.proposal &&
        value.proposal.proposal_digest !== this.retiredProposalDigest
      ) {
        this.retiredProposalDigest = '';
        this.proposal = value.proposal;
        this.phase = ARCHITECT_PHASES.PROPOSAL;
        Promise.resolve(this._onProposal(value.proposal)).catch(() => {});
      } else if (
        !value.proposal || value.proposal.proposal_digest === this.retiredProposalDigest
      ) {
        this.phase = ARCHITECT_PHASES.CONVERSATION;
      }
    },

    canSendTurn() {
      return !this.busy && this.isConversation && !!this.turnText.trim();
    },

    async sendTurn() {
      if (!this.canSendTurn()) return;
      const text = this.turnText.trim();
      this.turnText = '';
      this.busy = true;
      this.error = '';
      if (!this.pendingTurn || this.pendingTurn.text !== text) {
        this.pendingTurn = {
          text,
          idempotencyKey: this.api.createIdempotencyKey?.() || '',
        };
      }
      try {
        this.latestTurn = await this.api.submitTurn(
          this.conversationId,
          text,
          this.pendingTurn.idempotencyKey
        );
        this.pendingTurn = null;
      } catch (error) {
        this.turnText = text;
        this.error = error?.message || String(error);
      } finally {
        this.busy = false;
      }
    },

    readContextFile(event) {
      const file = event?.target?.files?.[0] || null;
      if (!file) return;
      const name = String(file.name || '');
      const allowedName = /\.(txt|md|markdown)$/i.test(name);
      const allowedType = !file.type || /^text\/(plain|markdown)$/i.test(file.type);
      if (!allowedName || !allowedType) {
        this.contextFile = null;
        this.error = 'Choose a plain-text or Markdown file.';
        return;
      }
      if (Number(file.size) > 100_000) {
        this.contextFile = null;
        this.error = 'That context file is over the 100 KB browser limit.';
        return;
      }
      this.contextFile = file;
      this.contextLabel = this.contextLabel.trim() || name;
      this.contextText = '';
      this.error = '';
    },

    diagramSources() {
      const markdown = String(this.proposal?.markdown || '');
      const sources = [];
      const pattern = /```mermaid\s*\n([\s\S]*?)```/gi;
      let match;
      while ((match = pattern.exec(markdown)) !== null) {
        sources.push(match[1].trim());
      }
      return sources;
    },

    reviseProposal() {
      this.decisionFinal = false;
      this.retiredProposalDigest = String(this.proposal?.proposal_digest || '');
      this.proposal = null;
      this.phase = ARCHITECT_PHASES.CONVERSATION;
      this.turnText = 'I want to change this proposal: ';
    },

    async decide(outcome) {
      if (!this.proposal || !['approve', 'reject'].includes(outcome) || this.busy) return;
      const decisionIdentity = `${this.proposal.proposal_id}:${this.proposal.proposal_digest}:${outcome}`;
      if (this.pendingDecision && this.pendingDecision.identity !== decisionIdentity) {
        this.error = `Retry the pending ${this.pendingDecision.outcome} decision before choosing another outcome.`;
        return;
      }
      if (!this.pendingDecision) {
        this.pendingDecision = {
          identity: decisionIdentity,
          outcome,
          idempotencyKey: this.api.createIdempotencyKey?.() || '',
        };
      }
      this.busy = true;
      this.phase = ARCHITECT_PHASES.APPLYING;
      this.error = '';
      try {
        const exact = { ...this.proposal, conversation_id: this.conversationId };
        const result = await this.api.decide(
          exact,
          outcome,
          this.pendingDecision.idempotencyKey
        );
        this.pendingDecision = null;
        this.decisionFinal = true;
        this._disconnect?.();
        this._disconnect = null;
        this.decisionStatus = result.status || outcome;
        if (outcome === 'approve' && result.plan_id) {
          await this._onPlanApplied(result.plan_id);
          this.planId = result.plan_id;
          this.phase = ARCHITECT_PHASES.DETAIL;
          await this._onDetailVisible(result.plan_id);
        } else {
          this.phase = ARCHITECT_PHASES.REJECTED;
        }
      } catch (error) {
        this.decisionFinal = false;
        this.error = error?.message || String(error);
        this.phase = ARCHITECT_PHASES.PROPOSAL;
      } finally {
        this.busy = false;
      }
    },

    async retryTurn() {
      if (!this.latestTurn || this.busy) return;
      this.busy = true;
      try {
        this.latestTurn = await this.api.retry(this.conversationId, this.latestTurn);
      } catch (error) {
        this.error = error?.message || String(error);
      } finally {
        this.busy = false;
      }
    },

    async stopTurn() {
      if (!this.conversationId || this.busy) return;
      this.busy = true;
      try {
        await this.api.stop(this.conversationId);
        await this.refresh();
      } catch (error) {
        this.error = error?.message || String(error);
      } finally {
        this.busy = false;
      }
    },

    reset() {
      this._disconnect?.();
      this._disconnect = null;
      this.phase = ARCHITECT_PHASES.IDLE;
      this.planId = null;
      this.conversationId = '';
      this.brainDump = '';
      this.turnText = '';
      this.contextLabel = '';
      this.contextText = '';
      this.contextFile = null;
      this.attachedContext = null;
      this.messages = [];
      this.proposal = null;
      this.retiredProposalDigest = '';
      this.latestTurn = null;
      this.pendingTurn = null;
      this.lastSequence = 0;
      this.error = '';
      this.decisionStatus = '';
      this.decisionFinal = false;
      this.pendingDecision = null;
      this.busy = false;
    },
  };
}

/** Alpine-facing factory with plan-store and visible-proposal integration. */
export function planArchitectPanel() {
  let panel;
  panel = createPlanArchitectPanel({
    onPlanApplied: async (planId) => {
      const plans = panel.$store?.plans || globalThis.Alpine?.store?.('plans');
      if (plans) {
        await plans.load();
        await plans.select(planId);
      }
    },
    onProposal: async () => {
      if (typeof panel.$nextTick === 'function') {
        await panel.$nextTick();
        await panel.$nextTick();
      }
      panel.$refs?.proposalHeading?.focus?.();
      await panel.renderProposalDiagrams();
    },
    onDetailVisible: async () => {
      if (typeof panel.$nextTick === 'function') {
        await panel.$nextTick();
        await panel.$nextTick();
      }
      const documentElement = panel.$root?.querySelector?.('[data-testid="plan-markdown"]');
      if (!(await waitForVisibleLayout(documentElement))) return;
      if (typeof globalThis._mermaidInitForPalette === 'function') {
        globalThis._mermaidInitForPalette();
      }
      if (typeof globalThis._renderMermaidPlaceholders === 'function') {
        await globalThis._renderMermaidPlaceholders(documentElement);
      }
    },
  });

  panel.renderProposal = function renderProposal() {
    const markdown = this.proposal?.markdown || '';
    if (typeof globalThis.renderMarkdown === 'function') {
      return globalThis.renderMarkdown(markdown);
    }
    return markdown.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  };

  panel.renderMessage = function renderMessage(message) {
    if (message?.role === 'learner') return '';
    if (typeof globalThis.renderMarkdown === 'function') {
      return globalThis.renderMarkdown(message?.content || '');
    }
    return String(message?.content || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
  };

  panel.renderProposalDiagrams = async function renderProposalDiagrams() {
    if (this.phase !== ARCHITECT_PHASES.PROPOSAL) return;
    const root = this.$refs?.proposalDocument;
    if (!(await waitForVisibleLayout(root))) return;
    if (typeof globalThis._mermaidInitForPalette === 'function') {
      globalThis._mermaidInitForPalette();
    }
    if (typeof globalThis._renderMermaidPlaceholders === 'function') {
      await globalThis._renderMermaidPlaceholders(root);
    }
  };

  return panel;
}
