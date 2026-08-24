/**
 * Closed browser adapter for the StudyLoop planning-conversation API.
 *
 * It deliberately knows nothing about ACP, terminals, providers, or capability
 * schemas. UI components receive one small object whose methods exactly mirror
 * the release-one browser contract.
 */

const PLANNING_API = '/api/planning';

export const PLANNING_PRIVACY_NOTICE =
  'Planning text and proposals are stored locally for recovery and may remain ' +
  'after rejection or replacement. StudyLoop sends the bounded planning context ' +
  'to your configured model. This release provides no automatic expiry.';

function defaultId() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  return `browser-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function csrfFromCookie() {
  const cookie = globalThis.document?.cookie || '';
  for (const item of cookie.split(';')) {
    const [name, ...rest] = item.trim().split('=');
    if (name === 'studyloop_csrf') return decodeURIComponent(rest.join('='));
  }
  return '';
}

async function responseError(response, fallback) {
  try {
    const body = await response.json();
    const detail = body?.detail;
    if (typeof detail === 'string' && detail.trim()) return detail.trim();
    if (detail && typeof detail.message === 'string') return detail.message;
  } catch {
    // The status remains the only safe public detail for non-JSON failures.
  }
  return `${fallback} (${response.status})`;
}

function normalizeCapacity(raw) {
  const value = raw?.capacity || raw || {};
  const current = Number(value.current ?? value.current_count ?? 0);
  const max = Number(value.max ?? value.max_current ?? 3);
  const available = Number(value.available ?? value.slots_free ?? Math.max(0, max - current));
  return {
    current: Number.isFinite(current) ? current : 0,
    max: Number.isFinite(max) ? max : 3,
    available: Number.isFinite(available) ? available : 0,
    can_create: value.can_create ?? value.at_capacity !== true,
  };
}

function websocketUrl(origin, conversationId, afterSeq, csrfToken) {
  const base = String(origin || globalThis.location?.origin || 'http://127.0.0.1');
  const wsOrigin = base.replace(/^http:/, 'ws:').replace(/^https:/, 'wss:');
  const id = encodeURIComponent(conversationId);
  const token = encodeURIComponent(String(csrfToken || ''));
  return `${wsOrigin}${PLANNING_API}/conversations/${id}/events?after_seq=${afterSeq}&csrf_token=${token}`;
}

export function createPlanningConversation(options = {}) {
  const fetchImpl = options.fetchImpl || ((...args) => globalThis.fetch(...args));
  const socketFactory =
    options.websocketFactory || ((url) => new globalThis.WebSocket(url));
  const origin = String(options.origin || globalThis.location?.origin || 'http://127.0.0.1');
  const idFactory = options.idFactory || defaultId;
  let csrfToken = csrfFromCookie();

  const headers = (withJson = true) => {
    const result = {
      Origin: origin,
      'Sec-Fetch-Site': 'same-origin',
    };
    if (withJson) result['Content-Type'] = 'application/json';
    if (csrfToken) result['X-CSRF-Token'] = csrfToken;
    return result;
  };

  const requestJson = async (url, init, fallback) => {
    const response = await fetchImpl(url, init);
    if (!response.ok) throw new Error(await responseError(response, fallback));
    return response.json();
  };

  return {
    createIdempotencyKey() {
      return idFactory();
    },

    async readCapacity() {
      const body = await requestJson('/api/plans', { headers: headers(false) }, 'Could not load plans');
      return normalizeCapacity(body);
    },

    async create(input) {
      const body = await requestJson(
        `${PLANNING_API}/conversations`,
        {
          method: 'POST',
          headers: headers(),
          body: JSON.stringify(input),
        },
        'Could not start the planning conversation'
      );
      csrfToken = String(body.csrf_token || csrfFromCookie());
      return { ...body, capacity: normalizeCapacity(body.capacity) };
    },

    async get(conversationId) {
      const id = encodeURIComponent(conversationId);
      return requestJson(
        `${PLANNING_API}/conversations/${id}`,
        { headers: headers(false) },
        'Could not refresh the planning conversation'
      );
    },

    async attachPastedContext(conversationId, context) {
      const id = encodeURIComponent(conversationId);
      return requestJson(
        `${PLANNING_API}/conversations/${id}/context`,
        {
          method: 'POST',
          headers: headers(),
          body: JSON.stringify({
            kind: 'pasted',
            label: String(context.label || '').trim(),
            content: String(context.content || ''),
          }),
        },
        'Could not attach the planning context'
      );
    },

    async attachTextFile(conversationId, file) {
      const id = encodeURIComponent(conversationId);
      const form = new FormData();
      form.append('label', String(file?.name || 'Study context'));
      form.append('file', file, String(file?.name || 'context.txt'));
      return requestJson(
        `${PLANNING_API}/conversations/${id}/context`,
        {
          method: 'POST',
          headers: headers(false),
          body: form,
        },
        'Could not attach the planning context file'
      );
    },

    async submitTurn(conversationId, text, idempotencyKey = '') {
      const id = encodeURIComponent(conversationId);
      const operationKey = String(idempotencyKey || idFactory());
      return requestJson(
        `${PLANNING_API}/conversations/${id}/turns`,
        {
          method: 'POST',
          headers: headers(),
          body: JSON.stringify({ text: String(text), idempotency_key: operationKey }),
        },
        'Could not send the planning turn'
      );
    },

    async retry(conversationId, turn) {
      const id = encodeURIComponent(conversationId);
      return requestJson(
        `${PLANNING_API}/conversations/${id}/retry`,
        {
          method: 'POST',
          headers: headers(),
          body: JSON.stringify({
            turn_id: turn.turn_id,
            expected_turn_version: turn.turn_version,
          }),
        },
        'Could not retry the interrupted turn'
      );
    },

    async stop(conversationId) {
      const id = encodeURIComponent(conversationId);
      return requestJson(
        `${PLANNING_API}/conversations/${id}/stop`,
        { method: 'POST', headers: headers(), body: '{}' },
        'Could not stop the planning turn'
      );
    },

    async decide(proposal, outcome, idempotencyKey = '') {
      const proposalId = encodeURIComponent(proposal.proposal_id);
      const operationKey = String(idempotencyKey || idFactory());
      return requestJson(
        `${PLANNING_API}/proposals/${proposalId}/decision`,
        {
          method: 'POST',
          headers: headers(),
          body: JSON.stringify({
            conversation_id: proposal.conversation_id,
            proposal_digest: proposal.proposal_digest,
            outcome,
            idempotency_key: operationKey,
            base: proposal.base,
          }),
        },
        'Could not apply the proposal decision'
      );
    },

    connect(conversationId, afterSeq, onEvent, onDisconnect) {
      let cursor = Math.max(0, Number(afterSeq) || 0);
      const socket = socketFactory(websocketUrl(origin, conversationId, cursor, csrfToken));
      socket.onmessage = (message) => {
        let event;
        try {
          event = JSON.parse(message.data);
        } catch {
          return;
        }
        const sequence = Number(event?.sequence);
        if (!Number.isInteger(sequence) || sequence <= cursor) return;
        cursor = sequence;
        onEvent?.(event);
      };
      socket.onclose = () => onDisconnect?.(cursor);
      socket.onerror = () => onDisconnect?.(cursor);
      return () => socket.close();
    },
  };
}

export { normalizeCapacity };
