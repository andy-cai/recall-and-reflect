// Fetch client. All endpoints are local (same origin).

async function jfetch(method, url, body) {
  const opts = { method, headers: {} };
  if (body !== undefined) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(url, opts);
  const data = res.status === 204 ? null : await res.json().catch(() => null);
  if (!res.ok) {
    const err = new Error((data && data.error) || `HTTP ${res.status}`);
    err.status = res.status;
    err.data = data;
    throw err;
  }
  return data;
}

// Async generator yielding text chunks from a streaming endpoint.
export async function* streamText(url, body) {
  const res = await fetch(url, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = new Error('stream failed');
    err.status = res.status;
    throw err;
  }
  const reader = res.body.getReader();
  const dec = new TextDecoder();
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    const chunk = dec.decode(value, { stream: true });
    if (chunk) yield chunk;
  }
}

export const api = {
  // dashboards
  today: () => jfetch('GET', '/api/today'),
  stats: () => jfetch('GET', '/api/stats'),

  // settings + llm
  getSettings: () => jfetch('GET', '/api/settings'),
  updateSettings: (b) => jfetch('PUT', '/api/settings', b),
  llmStatus: () => jfetch('GET', '/api/llm/status'),

  // capture
  captureCards: (transcript, n = 4) => jfetch('POST', '/api/capture/cards', { transcript, n }),
  captureIdeas: (transcript) => jfetch('POST', '/api/capture/ideas', { transcript }),
  prettify: (text) => jfetch('POST', '/api/capture/prettify', { text }),
  captureSubject: (transcript) => jfetch('POST', '/api/capture/subject', { transcript }),
  followupStream: (messages) => streamText('/api/capture/followup', { messages }),

  // subjects
  subjects: () => jfetch('GET', '/api/subjects'),
  suggestSubjects: () => jfetch('POST', '/api/subjects/suggest'),
  assignSubjects: (assignments) => jfetch('POST', '/api/subjects/assign', { assignments }),

  // bulk add
  bulkTopics: (payload) => jfetch('POST', '/api/topics/bulk', payload),
  splitTopics: (text) => jfetch('POST', '/api/topics/split', { text }),
  generateMore: (id) => jfetch('POST', `/api/learnings/${id}/generate`),

  // learnings + cards
  listLearnings: (search = '', tag = null) => {
    const p = new URLSearchParams();
    if (search) p.set('search', search);
    if (tag) p.set('tag', tag);
    const qs = p.toString();
    return jfetch('GET', '/api/learnings' + (qs ? `?${qs}` : ''));
  },
  getLearning: (id) => jfetch('GET', `/api/learnings/${id}`),
  createLearning: (b) => jfetch('POST', '/api/learnings', b),
  updateLearning: (id, b) => jfetch('PUT', `/api/learnings/${id}`, b),
  deleteLearning: (id) => jfetch('DELETE', `/api/learnings/${id}`),
  addCard: (id, b) => jfetch('POST', `/api/learnings/${id}/cards`, b),
  updateCard: (id, b) => jfetch('PUT', `/api/cards/${id}`, b),
  deleteCard: (id) => jfetch('DELETE', `/api/cards/${id}`),
  suspendCard: (id, suspended) => jfetch('POST', `/api/cards/${id}/suspend`, { suspended }),
  refineCard: (id, b) => jfetch('POST', `/api/cards/${id}/refine`, b),
  buryCard: (id, days = 1) => jfetch('POST', `/api/cards/${id}/bury`, { days }),

  // review
  queue: ({ tag = null, learning_id = null, subject = null, limit = null, focus = null, mode = null } = {}) => {
    const p = new URLSearchParams();
    if (tag) p.set('tag', tag);
    if (learning_id) p.set('learning_id', learning_id);
    if (subject !== null && subject !== undefined) p.set('subject', subject);
    if (limit) p.set('limit', limit);
    if (focus) p.set('focus', '1');
    if (mode) p.set('mode', mode);
    const qs = p.toString();
    return jfetch('GET', '/api/review/queue' + (qs ? `?${qs}` : ''));
  },
  ramp: (days) => jfetch('POST', '/api/review/ramp', { days }),

  // embeddings: related concepts, contrast cards, connections, dupes
  related: (id) => jfetch('GET', `/api/learnings/${id}/related`),
  addContrast: (id, with_id) => jfetch('POST', `/api/learnings/${id}/contrast`, { with_id }),
  captureConnections: (text) => jfetch('POST', '/api/capture/connections', { text }),
  checkDupes: (titles) => jfetch('POST', '/api/topics/check_dupes', { titles }),

  // teach-back
  teachTurnStream: (learning_id, messages) => streamText('/api/teach/turn', { learning_id, messages }),
  teachFinish: (b) => jfetch('POST', '/api/teach/finish', b),

  // focus (priority topics)
  focusInterpret: (text) => jfetch('POST', '/api/focus/interpret', { text }),
  focusApply: (b) => jfetch('POST', '/api/focus/apply', b),
  focusClear: () => jfetch('POST', '/api/focus/clear'),
  setPriority: (id, priority) => jfetch('POST', `/api/learnings/${id}/priority`, { priority }),
  grade: (question_id, recall) => jfetch('POST', '/api/review/grade', { question_id, recall }),
  answer: (b) => jfetch('POST', '/api/review/answer', b),
  undo: () => jfetch('POST', '/api/review/undo'),
};
