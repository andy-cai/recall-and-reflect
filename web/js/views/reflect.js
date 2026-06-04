// Reflect — talk a TOPIC through. You describe it; the AI asks up to 2 generative
// follow-ups, then sets the topic up for review. Every topic gets a free-recall prompt
// by default ("recall it in your own words"); a few optional detail questions are tucked
// away. No flashcard authoring required.
import { el, clear, toast, state } from '../store.js';
import { api } from '../api.js';
import { navigate, refreshBadge } from '../app.js';

const MAX_Q = 2;
const GREETING = "What do you want to remember? Describe the topic in your own words — I'll ask a couple of sharp questions, then set it up so you can recall it later.";

function deriveTitle(text) {
  const first = (text || '').trim().split('\n')[0].replace(/^#+\s*/, '');
  return first.length > 70 ? first.slice(0, 70) + '…' : first;
}

export async function render() {
  const llmOk = !!(state.llm && state.llm.available);

  const convo = [];                 // {role, content}
  let asked = 0, phase = 'gathering';
  const editors = [];               // detail-question editors
  let addMsg = () => ({ setText() {}, typing() {} });
  let contentArea = null;

  const view = el('div', { class: 'view' });
  view.append(el('div', { class: 'page-head' },
    el('h1', {}, 'Reflect'),
    el('p', { class: 'sub' }, llmOk
      ? 'Talk a topic through — explaining it yourself is what makes it stick.'
      : 'AI is offline — jot the topic down; you can talk it through later.')));

  // ---------- topic panel ----------
  const titleInput = el('input', { class: 'input', placeholder: 'Topic (auto-filled)' });
  const tagsInput = el('input', { class: 'input', placeholder: 'tags, comma separated' });
  const subjectNames = (await api.subjects().catch(() => ({ names: [] }))).names || [];
  const subjectList = el('datalist', { id: 'subj-list' }, ...subjectNames.map(n => el('option', { value: n })));
  const subjectInput = el('input', { class: 'input', placeholder: 'e.g. Vibrations, Geopolitics…', list: 'subj-list' });
  const saveBtn = el('button', { class: 'btn btn-primary btn-block', onClick: save }, 'Save topic');

  // detail questions (optional, collapsed)
  const chev = el('span', { class: 'muted', style: { fontSize: '12px' } }, '▸');
  const detailCount = el('span', { class: 'muted' }, '');
  const detailList = el('div', {});
  let detailsOpen = false;
  function toggleDetails(open) {
    detailsOpen = open === undefined ? !detailsOpen : open;
    detailBody.style.display = detailsOpen ? '' : 'none';
    chev.textContent = detailsOpen ? '▾' : '▸';
  }
  const addQBtn = el('button', { class: 'btn', style: { padding: '6px 10px', fontSize: '13px', marginTop: '8px' },
    onClick: () => { toggleDetails(true); detailList.append(makeEditor({ type: 'basic' })); } }, '+ add a question');
  const detailBody = el('div', { style: { display: 'none', marginTop: '8px' } }, detailList, addQBtn);
  const detailHeader = el('button', { class: 'btn btn-ghost', style: { width: '100%', justifyContent: 'space-between', padding: '8px 10px' },
    onClick: () => toggleDetails() }, el('span', {}, 'Detail questions ', detailCount), chev);
  const detailDisclosure = el('div', { style: { border: '1px solid var(--border)', borderRadius: '10px', padding: '4px', margin: '0 0 12px' } }, detailHeader, detailBody);

  function updateCount() { detailCount.textContent = editors.length ? `· ${editors.length}` : ''; }

  function makeEditor(card) {
    const node = el('div', { class: 'draft-card basic' });
    const ed = { node, read: null };
    const q = el('input', { class: 'input', placeholder: 'Question' }); q.value = card.question || '';
    const a = el('input', { class: 'input', placeholder: 'Answer' }); a.value = card.answer || '';
    node.append(
      el('div', { class: 'row spread' },
        el('span', { class: 'ct' }, 'QUESTION'),
        el('button', { class: 'btn-ghost', style: { padding: '2px 8px', fontSize: '12px' },
          onClick: () => { node.remove(); const i = editors.indexOf(ed); if (i >= 0) editors.splice(i, 1); updateCount(); } }, 'remove')),
      q, a);
    ed.read = () => ({ type: 'basic', question: q.value.trim(), answer: a.value.trim() });
    editors.push(ed); updateCount();
    return node;
  }
  function renderDetails(cards) {
    clear(detailList); editors.length = 0;
    for (const c of cards) detailList.append(makeEditor(c));
    toggleDetails(true);
  }

  const recallNote = el('div', { style: { fontSize: '12.5px', color: 'var(--text-soft)', background: 'var(--surface-2)', borderRadius: '10px', padding: '11px 13px', margin: '2px 0 12px', lineHeight: '1.45' } },
    '🧠 At review you’ll recall this topic in your own words first', llmOk ? ', then your local AI probes the gaps with follow-up questions.' : '. ');

  const topicPanel = el('div', { class: 'card draft-panel' },
    el('div', { class: 'eyebrow', style: { marginBottom: '12px' } }, 'Topic'),
    el('div', { class: 'field', style: { marginBottom: '10px' } }, el('label', { class: 'lbl' }, 'Subject'), subjectInput, subjectList),
    el('div', { class: 'field', style: { marginBottom: '10px' } }, el('label', { class: 'lbl' }, 'Title'), titleInput),
    el('div', { class: 'field', style: { marginBottom: '12px' } }, el('label', { class: 'lbl' }, 'Tags'), tagsInput),
    recallNote, detailDisclosure, saveBtn);

  async function save() {
    const dump = convo.find(m => m.role === 'user');
    const content = ((dump && dump.content) || (contentArea && contentArea.value) || '').trim();
    const title = titleInput.value.trim() || deriveTitle(content);
    if (!content && !title) { toast('Describe the topic first.'); return; }
    const cards = editors.map(e => e.read()).filter(c => c.question && c.answer);
    const reflection = convo.filter((_, i) => i > 0).map(m => `${m.role === 'user' ? 'Me' : 'Q'}: ${m.content}`).join('\n');
    const conversation = convo.length ? JSON.stringify(convo) : null;
    const tags = tagsInput.value.split(',').map(t => t.trim()).filter(Boolean);
    saveBtn.disabled = true; saveBtn.textContent = 'Saving…';
    try {
      const res = await api.createLearning({ title, content, reflection: reflection || null,
        subject: subjectInput.value.trim() || null, conversation, tags, cards });
      toast(`Saved “${res.title}”`);
      refreshBadge();
      navigate('#/library/' + res.id);
    } catch (e) {
      toast('Save failed: ' + e.message);
      saveBtn.disabled = false; saveBtn.textContent = 'Save topic';
    }
  }

  async function setupTopic() {
    if (phase === 'cards') return;
    phase = 'cards';
    const dump = convo.find(m => m.role === 'user');
    if (dump && !titleInput.value) titleInput.value = deriveTitle(dump.content);
    const transcript = convo.map(m => (m.role === 'user' ? 'Learner' : 'Partner') + ': ' + m.content).join('\n\n');
    api.captureSubject(transcript).then(r => {
      if (r && r.subject && !subjectInput.value.trim()) subjectInput.value = r.subject;
    }).catch(() => {});
    toggleDetails(true);
    clear(detailList); editors.length = 0;
    const loading = el('div', { class: 'row', style: { padding: '8px 2px' } }, el('span', { class: 'spin' }), el('span', { class: 'muted' }, ' prepping a few questions…'));
    detailList.append(loading);
    try {
      const res = await api.captureCards(transcript, 4);
      renderDetails(res.cards);
      addMsg('ai').setText('Set. You’ll recall this in your own words at review — I’ve also prepped a few specific questions (see “Detail questions”). Pick a subject and save.');
    } catch (e) {
      clear(detailList); editors.length = 0; updateCount(); toggleDetails(false);
      addMsg('ai').setText('Got it — I’ll prompt you to recall this topic at review. Pick a subject and save.');
    }
  }

  // ---------- chat vs manual ----------
  if (llmOk) {
    const log = el('div', { class: 'chat-log' });
    const composer = el('textarea', { class: 'input', rows: '1', placeholder: 'Describe the topic…' });
    const sendBtn = el('button', { class: 'btn btn-primary', onClick: onSend }, 'Send');
    const makeBtn = el('button', { class: 'btn btn-ghost', style: { display: 'none' }, onClick: () => setupTopic() }, 'Set it up now →');

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
      } catch { m.typing(false); m.setText('Let’s set this topic up.'); sendBtn.disabled = false; setupTopic(); return; }
      m.typing(false); text = text.trim(); sendBtn.disabled = false;
      if (!text) { setupTopic(); return; }
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
      else await setupTopic();
    }

    composer.addEventListener('input', () => { composer.style.height = 'auto'; composer.style.height = Math.min(200, composer.scrollHeight) + 'px'; });
    composer.addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); onSend(); } });

    addMsg('ai', GREETING);
    view.append(el('div', { class: 'reflect-grid' },
      el('div', { class: 'chat' }, log,
        el('div', { class: 'composer' }, composer, el('div', { class: 'stack', style: { gap: '6px' } }, sendBtn, makeBtn))),
      topicPanel));
    setTimeout(() => composer.focus(), 50);
  } else {
    contentArea = el('textarea', { class: 'input', rows: '6', placeholder: 'What’s the topic? Describe it in your own words — context, examples, why it matters.' });
    view.append(el('div', { class: 'reflect-grid' },
      el('div', { class: 'stack' },
        el('div', { class: 'field' }, el('label', { class: 'lbl' }, 'The topic'), contentArea),
        el('p', { class: 'muted', style: { fontSize: '13px' } }, 'Tip: start Ollama (qwen2.5:7b) to talk it through and auto-prep questions.')),
      topicPanel));
  }

  return view;
}
