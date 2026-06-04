// Reflect — free-flow chat capture. You dump; it asks up to 2 generative follow-ups
// (skippable), then drafts editable recall cards.
import { el, clear, toast, state } from '../store.js';
import { api } from '../api.js';
import { navigate, refreshBadge } from '../app.js';

const MAX_Q = 2;
const GREETING = "What did you learn? Dump it here however it comes out — I'll ask a couple of sharp questions, then turn it into recall cards.";

function deriveTitle(text) {
  const first = (text || '').trim().split('\n')[0].replace(/^#+\s*/, '');
  return first.length > 64 ? first.slice(0, 64) + '…' : first;
}

export async function render() {
  const llmOk = !!(state.llm && state.llm.available);

  const convo = [];                 // {role, content} sent to the model (excludes greeting)
  let asked = 0, phase = 'gathering';
  const editors = [];               // draft-card editors
  let addMsg = () => ({ setText() {}, typing() {} });   // replaced in chat mode
  let contentArea = null;

  const view = el('div', { class: 'view' });
  view.append(el('div', { class: 'page-head' },
    el('h1', {}, 'Reflect'),
    el('p', { class: 'sub' }, llmOk
      ? 'Think it through out loud. Explaining it yourself is what makes it stick.'
      : 'AI is offline — jot it down and add cards manually.')));

  // ---------- draft panel ----------
  const draftList = el('div', {});
  const titleInput = el('input', { class: 'input', placeholder: 'Title (auto-filled)' });
  const tagsInput = el('input', { class: 'input', placeholder: 'tags, comma separated' });
  const saveBtn = el('button', { class: 'btn btn-primary btn-block', onClick: save }, 'Save learning');

  function placeholder() {
    clear(draftList); editors.length = 0;
    draftList.append(el('p', { class: 'muted', style: { fontSize: '13px', padding: '8px 2px' } },
      llmOk ? 'Cards appear here once we’ve talked it through.' : 'Add your first card below.'));
  }

  function makeEditor(card) {
    const type = (card.type || 'basic').toLowerCase();
    const node = el('div', { class: 'draft-card ' + type });
    const ed = { node, read: null };
    node.append(el('div', { class: 'row spread' },
      el('span', { class: 'ct' }, type === 'cloze' ? 'CLOZE' : 'BASIC'),
      el('button', { class: 'btn-ghost', style: { padding: '2px 8px', fontSize: '12px' },
        onClick: () => { node.remove(); const i = editors.indexOf(ed); if (i >= 0) editors.splice(i, 1); } }, 'remove')));
    if (type === 'cloze') {
      const src = el('textarea', { class: 'input', rows: '2', placeholder: 'Sentence with {{c1::blanked term}}' });
      src.value = card.source || '';
      node.append(src, el('div', { class: 'muted', style: { fontSize: '11px', marginTop: '4px' } }, 'Each {{c1::…}} marker becomes one card.'));
      ed.read = () => ({ type: 'cloze', source: src.value.trim() });
    } else {
      const q = el('input', { class: 'input', placeholder: 'Question' }); q.value = card.question || '';
      const a = el('input', { class: 'input', placeholder: 'Answer' }); a.value = card.answer || '';
      node.append(q, a);
      ed.read = () => ({ type: 'basic', question: q.value.trim(), answer: a.value.trim() });
    }
    editors.push(ed);
    return node;
  }

  function renderDraft(cards) { clear(draftList); editors.length = 0; for (const c of cards) draftList.append(makeEditor(c)); }

  const draftPanel = el('div', { class: 'card draft-panel' },
    el('div', { class: 'eyebrow', style: { marginBottom: '12px' } }, 'Draft cards'),
    draftList,
    el('div', { class: 'row', style: { gap: '8px', margin: '6px 0 14px' } },
      el('button', { class: 'btn', style: { flex: '1', padding: '7px' }, onClick: () => draftList.append(makeEditor({ type: 'basic' })) }, '+ Basic'),
      el('button', { class: 'btn', style: { flex: '1', padding: '7px' }, onClick: () => draftList.append(makeEditor({ type: 'cloze' })) }, '+ Cloze')),
    el('div', { class: 'field', style: { marginBottom: '10px' } }, el('label', { class: 'lbl' }, 'Title'), titleInput),
    el('div', { class: 'field', style: { marginBottom: '14px' } }, el('label', { class: 'lbl' }, 'Tags'), tagsInput),
    saveBtn);

  async function save() {
    const cards = editors.map(e => e.read()).filter(c =>
      (c.type === 'cloze' && c.source) || (c.type === 'basic' && c.question && c.answer));
    if (!cards.length) { toast('Add at least one complete card first.'); return; }
    const dump = convo.find(m => m.role === 'user');
    const content = (dump && dump.content) || (contentArea && contentArea.value) || '';
    const reflection = convo.filter((_, i) => i > 0).map(m => `${m.role === 'user' ? 'Me' : 'Q'}: ${m.content}`).join('\n');
    const title = titleInput.value.trim();
    const tags = tagsInput.value.split(',').map(t => t.trim()).filter(Boolean);
    if (!content.trim() && !title) { toast('Write what you learned first.'); return; }
    saveBtn.disabled = true; saveBtn.textContent = 'Saving…';
    try {
      const res = await api.createLearning({ title, content, reflection: reflection || null, tags, cards });
      toast(`Saved “${res.title}” · ${res.cards} card${res.cards !== 1 ? 's' : ''}`);
      refreshBadge();
      navigate('#/library/' + res.id);
    } catch (e) {
      toast('Save failed: ' + e.message);
      saveBtn.disabled = false; saveBtn.textContent = 'Save learning';
    }
  }

  async function generateCards() {
    if (phase === 'cards') return;
    phase = 'cards';
    const dump = convo.find(m => m.role === 'user');
    if (dump && !titleInput.value) titleInput.value = deriveTitle(dump.content);
    clear(draftList);
    draftList.append(el('div', { class: 'row', style: { padding: '10px 2px' } }, el('span', { class: 'spin' }), el('span', { class: 'muted' }, ' drafting cards…')));
    const transcript = convo.map(m => (m.role === 'user' ? 'Learner' : 'Partner') + ': ' + m.content).join('\n\n');
    try {
      const res = await api.captureCards(transcript, 4);
      renderDraft(res.cards);
      addMsg('ai').setText('Here’s a first set — edit anything, then save. Add your own with + Basic / + Cloze.');
    } catch (e) {
      renderDraft([{ type: 'basic' }]);
      addMsg('ai').setText('Couldn’t draft cards just now — add them manually on the right.');
    }
  }

  // ---------- chat vs manual ----------
  if (llmOk) {
    const log = el('div', { class: 'chat-log' });
    const composer = el('textarea', { class: 'input', rows: '1', placeholder: 'Type what you learned…' });
    const sendBtn = el('button', { class: 'btn btn-primary', onClick: onSend }, 'Send');
    const makeBtn = el('button', { class: 'btn btn-ghost', style: { display: 'none' }, onClick: () => generateCards() }, 'Make cards now →');

    const scrollDown = () => requestAnimationFrame(() => window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' }));

    addMsg = (role, text = '') => {
      const body = el('span', {}, text);
      const node = el('div', { class: 'msg ' + role }, body);
      log.append(node); scrollDown();
      let t = null;
      return {
        setText(v) { body.textContent = v; scrollDown(); },
        typing(on) {
          if (on && !t) { t = el('span', { class: 'typing' }, el('span'), el('span'), el('span')); node.append(t); }
          else if (!on && t) { t.remove(); t = null; }
          scrollDown();
        },
      };
    };

    async function requestFollowup() {
      sendBtn.disabled = true;
      const m = addMsg('ai'); m.typing(true);
      let text = '';
      try {
        for await (const chunk of api.followupStream(convo)) { m.typing(false); text += chunk; m.setText(text); }
      } catch { m.typing(false); m.setText('Let’s turn this into cards.'); sendBtn.disabled = false; generateCards(); return; }
      m.typing(false); text = text.trim(); sendBtn.disabled = false;
      if (!text) { generateCards(); return; }
      convo.push({ role: 'assistant', content: text });
      asked += 1;
      composer.focus();
    }

    async function onSend() {
      const text = composer.value.trim();
      if (!text || phase === 'cards' || sendBtn.disabled) return;
      addMsg('user', text);
      convo.push({ role: 'user', content: text });
      composer.value = ''; composer.style.height = 'auto';
      makeBtn.style.display = '';
      if (asked < MAX_Q) await requestFollowup();
      else await generateCards();
    }

    composer.addEventListener('input', () => { composer.style.height = 'auto'; composer.style.height = Math.min(200, composer.scrollHeight) + 'px'; });
    composer.addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); onSend(); } });

    addMsg('ai', GREETING);
    placeholder();
    view.append(el('div', { class: 'reflect-grid' },
      el('div', { class: 'chat' }, log,
        el('div', { class: 'composer' }, composer, el('div', { class: 'stack', style: { gap: '6px' } }, sendBtn, makeBtn))),
      draftPanel));
    setTimeout(() => composer.focus(), 50);
  } else {
    contentArea = el('textarea', { class: 'input', rows: '5', placeholder: 'What did you learn? Include context and examples.' });
    placeholder();
    view.append(el('div', { class: 'reflect-grid' },
      el('div', { class: 'stack' },
        el('div', { class: 'field' }, el('label', { class: 'lbl' }, 'What you learned'), contentArea),
        el('p', { class: 'muted', style: { fontSize: '13px' } }, 'Tip: start Ollama (qwen2.5:7b) for guided chat + auto-generated cards.')),
      draftPanel));
  }

  return view;
}
