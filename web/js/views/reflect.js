// Reflect — talk a TOPIC through. You describe it; the AI asks up to 2 generative
// follow-ups, then sets the topic up for review. Every topic gets a free-recall prompt
// by default ("recall it in your own words"); a few optional detail questions are tucked
// away. No flashcard authoring required.
import { el, clear, toast, state, infoTip } from '../store.js';
import { api } from '../api.js';
import { navigate, refreshBadge } from '../app.js';
import { renderMathIn } from '../math.js';

const MAX_Q = 2;
const GREETING = "What do you want to remember? Describe the topic in your own words — I'll ask a couple of sharp questions, then set it up so you can recall it later.";

function deriveTitle(text) {
  const first = (text || '').trim().split('\n')[0].replace(/^#+\s*/, '');
  return first.length > 70 ? first.slice(0, 70) + '…' : first;
}

const DRAFT_KEY = 'rr-reflect-draft';

export async function render() {
  const llmOk = !!(state.llm && state.llm.available);

  const convo = [];                 // {role, content}
  let asked = 0, phase = 'gathering';
  const editors = [];               // detail-question editors
  let addMsg = () => ({ node: null, setText() {}, typing() {} });
  let addStatus = (t) => addMsg('ai', t);   // quiet status line (not a margin note)
  let contentArea = null;
  let makeBtnRef = null;

  // Leaving mid-reflection must never destroy your thinking: every turn and
  // panel edit autosaves a draft; a banner offers Resume/Discard on return.
  function readDraft() {
    try { return JSON.parse(localStorage.getItem(DRAFT_KEY) || 'null'); } catch { return null; }
  }
  function saveDraft() {
    const data = {
      convo,
      title: titleInput.value, subject: subjectInput.value, tags: tagsInput.value,
      content: contentArea ? contentArea.value : '',
      ideas: ideaEditors.map(e => e.read()).filter(Boolean),
      details: editors.map(e => e.read()).filter(c => c.question || c.answer),
      ts: Date.now(),
    };
    const meaningful = data.convo.some(m => m.role === 'user') || data.content.trim()
      || data.ideas.length || data.details.length;
    if (meaningful) localStorage.setItem(DRAFT_KEY, JSON.stringify(data));
  }
  function clearDraft() { localStorage.removeItem(DRAFT_KEY); }
  function restoreDraft(d) {
    titleInput.value = d.title || '';
    subjectInput.value = d.subject || '';
    tagsInput.value = d.tags || '';
    if (d.ideas && d.ideas.length) renderIdeas(d.ideas);
    if (d.details && d.details.length) renderDetails(d.details);
    if (llmOk && d.convo && d.convo.length) {
      for (const m of d.convo) {
        renderMathIn(addMsg(m.role === 'user' ? 'user' : 'ai', m.content).node);
        convo.push(m);
      }
      asked = d.convo.filter(m => m.role === 'assistant').length;
      if (makeBtnRef) makeBtnRef.style.display = '';
    } else if (contentArea) {
      contentArea.value = d.content
        || (d.convo || []).filter(m => m.role === 'user').map(m => m.content).join('\n\n');
    }
  }

  const view = el('div', { class: 'view' });
  view.append(el('div', { class: 'page-head' },
    el('h1', {}, 'Reflect'),
    el('p', { class: 'sub' }, llmOk
      ? 'Talk a topic through — explaining it yourself is what makes it stick.'
      : 'AI is offline — jot the topic down; you can talk it through later.')));

  const chatWrap = el('div', {});

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
    onClick: () => toggleDetails() }, el('span', {}, 'Detail questions ', detailCount,
      infoTip('Optional. Your main review is recalling this topic in your own words — these just drill specific details. Edit or remove any.')), chev);
  const detailDisclosure = el('div', { style: { border: '1px solid var(--border)', borderRadius: '10px', padding: '4px', margin: '0 0 12px' } }, detailHeader, detailBody);

  function updateCount() { detailCount.textContent = editors.length ? `· ${editors.length}` : ''; }

  function makeEditor(card) {
    const node = el('div', { class: 'draft-card basic' });
    const ed = { node, read: null };
    const q = el('input', { class: 'input', placeholder: 'Question' }); q.value = card.question || '';
    const a = el('input', { class: 'input', placeholder: 'Answer' }); a.value = card.answer || '';
    q.addEventListener('input', saveDraft); a.addEventListener('input', saveDraft);
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
    '🧠 At review you’ll recall this topic in your own words first', llmOk ? ' — graded against the key ideas below.' : '. ');

  // ---------- key ideas (the rubric future recall is graded against) ----------
  const ideaEditors = [];
  const ideaList = el('div', { class: 'stack', style: { gap: '7px' } });
  function makeIdea(text = '') {
    const input = el('input', { class: 'input', placeholder: 'One key idea, one line', value: text,
      style: { fontSize: '13.5px', padding: '8px 11px' } });
    input.addEventListener('input', saveDraft);
    const ed = { read: () => input.value.trim() };
    const row = el('div', { class: 'row', style: { gap: '7px' } }, input,
      el('button', { class: 'btn-ghost', style: { padding: '2px 8px', fontSize: '12px', flex: 'none' },
        onClick: () => { row.remove(); const i = ideaEditors.indexOf(ed); if (i >= 0) ideaEditors.splice(i, 1); } }, '✕'));
    ideaEditors.push(ed);
    return row;
  }
  function renderIdeas(ideas) {
    clear(ideaList); ideaEditors.length = 0;
    for (const t of ideas) ideaList.append(makeIdea(t));
  }
  const ideasPanel = el('div', { style: { margin: '0 0 12px' } },
    el('div', { class: 'row spread', style: { marginBottom: '8px' } },
      el('span', { class: 'eyebrow' }, 'Key ideas',
        infoTip('What future-you is accountable for: your free recall of this topic is graded idea by idea. Trim ruthlessly — 3–8 one-liners.')),
      el('button', { class: 'btn-ghost', style: { padding: '2px 8px', fontSize: '12px' },
        onClick: () => ideaList.append(makeIdea()) }, '+ add')),
    ideaList);

  const topicPanel = el('div', { class: 'card draft-panel' },
    el('div', { class: 'eyebrow', style: { marginBottom: '12px' } }, 'Topic'),
    el('div', { class: 'field', style: { marginBottom: '10px' } }, el('label', { class: 'lbl' }, 'Subject'), subjectInput, subjectList),
    el('div', { class: 'field', style: { marginBottom: '10px' } }, el('label', { class: 'lbl' }, 'Title'), titleInput),
    el('div', { class: 'field', style: { marginBottom: '12px' } }, el('label', { class: 'lbl' }, 'Tags'), tagsInput),
    recallNote, ideasPanel, detailDisclosure, saveBtn);
  [titleInput, subjectInput, tagsInput].forEach(i => i.addEventListener('input', saveDraft));

  async function save() {
    const dump = convo.find(m => m.role === 'user');
    const content = ((dump && dump.content) || (contentArea && contentArea.value) || '').trim();
    const title = titleInput.value.trim() || deriveTitle(content);
    if (!content && !title) { toast('Describe the topic first.'); return; }
    const cards = editors.map(e => e.read()).filter(c => c.question && c.answer);
    const key_ideas = ideaEditors.map(e => e.read()).filter(Boolean);
    const reflection = convo.filter((_, i) => i > 0).map(m => `${m.role === 'user' ? 'Me' : 'Q'}: ${m.content}`).join('\n');
    const conversation = convo.length ? JSON.stringify(convo) : null;
    const tags = tagsInput.value.split(',').map(t => t.trim()).filter(Boolean);
    saveBtn.disabled = true; saveBtn.textContent = 'Saving…';
    try {
      const res = await api.createLearning({ title, content, reflection: reflection || null,
        subject: subjectInput.value.trim() || null, conversation, tags, cards, key_ideas });
      toast(`Saved “${res.title}”`);
      clearDraft();
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
    clear(ideaList); ideaEditors.length = 0;
    ideaList.append(el('div', { class: 'row' }, el('span', { class: 'spin' }), el('span', { class: 'muted', style: { fontSize: '12.5px' } }, ' distilling key ideas…')));
    const ideasJob = api.captureIdeas(transcript)
      .then(r => renderIdeas(r.ideas || []))
      .catch(() => { clear(ideaList); ideaEditors.length = 0; });
    try {
      const res = await api.captureCards(transcript, 4);
      renderDetails(res.cards);
      await ideasJob;
      saveDraft();
      addStatus('Set. I’ve distilled the key ideas your recall will be graded against — edit them in the panel, they’re what future-you is accountable for. Pick a subject and save.');
    } catch (e) {
      clear(detailList); editors.length = 0; updateCount(); toggleDetails(false);
      await ideasJob;
      addStatus('Got it — I’ll prompt you to recall this topic at review. Pick a subject and save.');
    }
  }

  // ---------- manuscript (Marginalia) vs manual ----------
  // No chatbot bubbles: your words form a continuous serif manuscript, and the
  // AI's questions live in the margin as numbered pencil-notes anchored to the
  // phrase that prompted them. Answering (writing the next paragraph) fades the
  // note with a ✓. Informal math is echoed back typeset ($...$) by the model.
  if (llmOk) {
    const doc = el('div', { class: 'ms-doc' });
    const marginCol = el('div', { class: 'ms-margin' });
    const cue = el('div', { class: 'ms-cue' }, GREETING);
    let noteCount = 0, openNote = null;

    const composer = el('textarea', { class: 'ms-compose', rows: '1', placeholder: 'Start writing…' });
    const sendBtn = el('button', { class: 'btn btn-primary', style: { padding: '7px 14px' }, onClick: onSend }, 'Add ↵');
    const makeBtn = el('button', { class: 'btn btn-ghost', style: { display: 'none' }, onClick: () => setupTopic() }, 'Set it up now →');
    makeBtnRef = makeBtn;
    const writeRow = el('div', { class: 'ms-write' }, composer,
      el('div', { class: 'row', style: { gap: '6px', justifyContent: 'flex-end', marginTop: '8px' } }, makeBtn, sendBtn));
    doc.append(cue, writeRow);
    addStatus = (t) => {
      doc.insertBefore(el('div', { class: 'ms-cue', style: { marginTop: '4px' } }, t), writeRow);
      scrollDown();
    };

    const scrollDown = () => requestAnimationFrame(() => window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' }));

    addMsg = (role, text = '') => {
      if (role === 'user') {
        cue.remove();
        const node = el('p', {}, text);
        doc.insertBefore(node, writeRow);
        if (openNote) {   // writing again counts the open margin note as engaged
          openNote.classList.remove('open');
          openNote.classList.add('done');
          openNote.append(el('span', { class: 'tick' }, ' ✓'));
          openNote = null;
        }
        scrollDown();
        return { node, setText(v) { node.textContent = v; renderMathIn(node); }, typing() {} };
      }
      // assistant → margin note, anchored to the latest paragraph
      noteCount += 1;
      const paras = doc.querySelectorAll('p');
      const lastP = paras[paras.length - 1];
      if (lastP) lastP.append(el('sup', { class: 'ms-ref' }, String(noteCount)));
      const body = el('span', { class: 'q' }, text);
      const note = el('div', { class: 'ms-note open' }, el('span', { class: 'n' }, noteCount + ' '), body);
      marginCol.append(note);
      openNote = note;
      composer.placeholder = 'Answer the margin — or keep writing…';
      scrollDown();
      let t = null;
      return {
        node: note,
        setText(v) { body.textContent = v; },
        typing(on) {
          if (on && !t) { t = el('span', { class: 'typing' }, el('span'), el('span'), el('span')); note.append(t); }
          else if (!on && t) { t.remove(); t = null; }
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
      renderMathIn(m.node);
      if (!text) { setupTopic(); return; }
      convo.push({ role: 'assistant', content: text });
      asked += 1;
      saveDraft();
      composer.focus();
    }

    // Stretch connections: after the first dump, surface the nearest topics the
    // learner already studied. Tapping a chip turns it into the next question —
    // elaboration anchored to something they provably know. Zero generation cost.
    async function showConnections(text) {
      try {
        const r = await api.captureConnections(text);
        if (!r.connections || !r.connections.length) return;
        const chips = el('div', { class: 'row wrap', style: { gap: '7px', margin: '2px 0 10px' } });
        for (const c of r.connections) {
          chips.append(el('button', { class: 'chip link', onClick: () => {
            chips.remove();
            const q = `You already know “${c.title}” — how does this connect (or where do they differ)?`;
            addMsg('ai', q);
            convo.push({ role: 'assistant', content: q });
            asked += 1;
            saveDraft();
            composer.focus();
          } }, `⚯ ${c.title}`));
        }
        doc.insertBefore(chips, writeRow);
      } catch {}
    }

    async function onSend() {
      const text = composer.value.trim();
      if (!text || phase === 'cards' || sendBtn.disabled) return;
      const isFirst = !convo.some(m => m.role === 'user');
      const para = addMsg('user', text);
      renderMathIn(para.node);
      convo.push({ role: 'user', content: text });
      const ci = convo.length - 1;
      saveDraft();
      // echo back with informal math typeset (and gently corrected) as TeX
      api.prettify(text).then(r => {
        const pretty = (r && r.text || '').trim();
        if (pretty && pretty !== text) {
          para.setText(pretty);
          convo[ci].content = pretty;
          saveDraft();
        }
      }).catch(() => {});
      composer.value = ''; composer.style.height = 'auto';
      makeBtn.style.display = '';
      if (isFirst) showConnections(text);   // fire-and-forget, never blocks writing
      if (asked < MAX_Q) await requestFollowup();
      else await setupTopic();
    }

    composer.addEventListener('input', () => { composer.style.height = 'auto'; composer.style.height = Math.min(200, composer.scrollHeight) + 'px'; });
    composer.addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); onSend(); } });

    chatWrap.append(el('div', { class: 'reflect-grid' },
      el('div', { class: 'card ms-frame' }, el('div', { class: 'ms' }, doc, marginCol)),
      topicPanel));
    setTimeout(() => composer.focus(), 50);
  } else {
    contentArea = el('textarea', { class: 'input', rows: '6', placeholder: 'What’s the topic? Describe it in your own words — context, examples, why it matters.' });
    chatWrap.append(el('div', { class: 'reflect-grid' },
      el('div', { class: 'stack' },
        el('div', { class: 'field' }, el('label', { class: 'lbl' }, 'The topic'), contentArea),
        el('p', { class: 'muted', style: { fontSize: '13px' } }, 'Tip: start Ollama (qwen2.5:7b) to talk it through and auto-prep questions.')),
      topicPanel));
  }

  // ---------- quick add (bulk) + person ----------
  const quickWrap = el('div', { style: { display: 'none' } });
  buildQuickAdd(quickWrap, subjectNames, llmOk);
  const personWrap = el('div', { style: { display: 'none' } });
  buildPersonAdd(personWrap);

  const chatBtn = el('button', { class: 'chip on', onClick: () => setMode('chat') }, llmOk ? 'Reflect' : 'Write');
  const quickBtn = el('button', { class: 'chip', onClick: () => setMode('quick') }, 'Quick add');
  const personBtn = el('button', { class: 'chip', onClick: () => setMode('person') }, 'Person');
  function setMode(m) {
    chatBtn.classList.toggle('on', m === 'chat');
    quickBtn.classList.toggle('on', m === 'quick');
    personBtn.classList.toggle('on', m === 'person');
    chatWrap.style.display = m === 'chat' ? '' : 'none';
    quickWrap.style.display = m === 'quick' ? '' : 'none';
    personWrap.style.display = m === 'person' ? '' : 'none';
  }
  view.append(el('div', { class: 'row', style: { gap: '7px', marginBottom: '16px' } }, chatBtn, quickBtn, personBtn));
  view.append(chatWrap, quickWrap, personWrap);
  if (contentArea) contentArea.addEventListener('input', saveDraft);

  // offer to resume a reflection that was abandoned mid-thought
  const draft = readDraft();
  if (draft && ((draft.convo || []).some(m => m.role === 'user') || (draft.content || '').trim()
      || (draft.ideas || []).length)) {
    const firstLine = ((draft.convo || []).find(m => m.role === 'user')?.content || draft.content || '').split('\n')[0];
    const snippet = firstLine.length > 70 ? firstLine.slice(0, 70) + '…' : firstLine;
    const banner = el('div', { class: 'card row spread', style: { marginBottom: '14px', borderColor: 'var(--accent)' } },
      el('div', { style: { minWidth: '0' } },
        el('div', { style: { fontWeight: '580' } }, '📝 Unfinished reflection'),
        el('div', { class: 'muted', style: { fontSize: '12.5px' } }, `“${snippet}” · ${agoLabel(draft.ts)}`)),
      el('div', { class: 'row', style: { gap: '8px', flex: 'none' } },
        el('button', { class: 'btn btn-ghost', onClick: () => { clearDraft(); banner.remove(); } }, 'Discard'),
        el('button', { class: 'btn btn-primary', onClick: () => { restoreDraft(draft); banner.remove(); } }, 'Resume')));
    view.insertBefore(banner, view.children[1]);
  }

  return view;
}

function agoLabel(ts) {
  const mins = Math.max(1, Math.round((Date.now() - (ts || Date.now())) / 60000));
  if (mins < 60) return `${mins} min ago`;
  const hrs = Math.round(mins / 60);
  return hrs < 24 ? `${hrs} h ago` : `${Math.round(hrs / 24)} d ago`;
}

// People as topics, photo-free: the cue is the story, the reveal is the name +
// the association YOU invented (self-generated imagery is what makes it stick).
function buildPersonAdd(root) {
  const nameInput = el('input', { class: 'input', placeholder: 'Name' });
  const whereInput = el('input', { class: 'input', placeholder: 'Where / when — “MFE battery bay, May”' });
  const factsArea = el('textarea', { class: 'input', rows: '3',
    placeholder: 'What you know — role, the story you shared, details worth keeping…\nFirst line becomes the cue.' });
  const assocInput = el('input', { class: 'input', placeholder: 'e.g. “Priya = prying open the pack — crowbar at the HV bay”' });
  const saveBtn = el('button', { class: 'btn btn-primary' }, 'Save person · 1 card');

  saveBtn.addEventListener('click', async () => {
    const name = nameInput.value.trim();
    const facts = factsArea.value.trim();
    if (!name || !facts) { toast('Name and at least one fact.'); return; }
    const hook = facts.split('\n')[0];
    const where = whereInput.value.trim();
    const assoc = assocInput.value.trim();
    const question = `${where ? where + ' — ' : ''}${hook}. Who is this?`;
    const answer = `${name}\n${facts}${assoc ? `\n🧷 Your association: ${assoc}` : ''}`;
    saveBtn.disabled = true; saveBtn.textContent = 'Saving…';
    try {
      const res = await api.createLearning({
        title: name, content: `${where ? where + '\n' : ''}${facts}`,
        subject: 'People', notes: assoc || null, tags: [],
        recall_card: false, cards: [{ type: 'basic', question, answer }],
      });
      toast(`Saved ${name}`);
      refreshBadge();
      nameInput.value = whereInput.value = factsArea.value = assocInput.value = '';
    } catch (e) { toast('Save failed: ' + e.message); }
    saveBtn.disabled = false; saveBtn.textContent = 'Save person · 1 card';
  });

  root.append(el('div', { class: 'card stack', style: { maxWidth: '560px' } },
    el('div', { class: 'eyebrow' }, 'Remember a person'),
    el('p', { class: 'muted', style: { fontSize: '13px', marginTop: '-4px' } },
      'The story becomes the cue; at review you recall the name. ~20 seconds, no photos.'),
    el('div', { class: 'row', style: { gap: '10px' } },
      el('div', { class: 'field', style: { flex: '1' } }, el('label', { class: 'lbl' }, 'Name'), nameInput),
      el('div', { class: 'field', style: { flex: '1.4' } }, el('label', { class: 'lbl' }, 'Where / when'), whereInput)),
    el('div', { class: 'field' }, el('label', { class: 'lbl' }, 'What you know'), factsArea),
    el('div', { class: 'field' }, el('label', { class: 'lbl' }, 'Vivid association ',
      infoTip('What does the name sound like? Tie it to something you noticed about them. You invent it — self-generated images are what make name recall stick.')), assocInput),
    el('div', { class: 'row', style: { justifyContent: 'flex-end' } }, saveBtn)));
}

function buildQuickAdd(root, subjectNames, llmOk) {
  const subjList = el('datalist', { id: 'subj-list-q' }, ...subjectNames.map(n => el('option', { value: n })));
  const subjectInput = el('input', { class: 'input', placeholder: 'Subject for all (optional)', list: 'subj-list-q' });
  const tagsInput = el('input', { class: 'input', placeholder: 'tags for all (optional)' });
  const perDay = el('input', { class: 'input', type: 'number', value: '8', style: { maxWidth: '84px' } });
  const text = el('textarea', { class: 'input', rows: '9',
    placeholder: 'One topic per line. Add a note after — or : if you like.\n\nQ-factor of SDOF systems — higher Q = sharper resonance, slower decay\nNyquist stability criterion\nPluralism in global power balances' });
  const countLbl = el('span', { class: 'muted' }, '');
  const addBtn = el('button', { class: 'btn btn-primary' }, 'Add topics');

  const lines = () => text.value.split('\n').map(l => l.trim()).filter(Boolean);
  const parseItems = () => lines().map(l => {
    const m = l.match(/^(.*?)\s+[—:-]\s+(.*)$/);
    return m ? { title: m[1].trim(), note: m[2].trim() } : { title: l, note: '' };
  });
  const updateCount = () => {
    const n = lines().length;
    countLbl.textContent = n ? `${n} topic${n !== 1 ? 's' : ''}` : '';
    addBtn.textContent = n ? `Add ${n} topic${n !== 1 ? 's' : ''}` : 'Add topics';
  };
  text.addEventListener('input', updateCount);
  addBtn.addEventListener('click', async () => {
    let items = parseItems();
    if (!items.length) { toast('Add at least one topic.'); return; }
    addBtn.disabled = true; addBtn.textContent = 'Checking…';
    // duplicate check (local embeddings) — don't double the queue silently
    try {
      const d = await api.checkDupes(items.map(i => i.title));
      if (d.dupes && d.dupes.length) {
        const lines = d.dupes.map(x => `• “${x.title}” ≈ existing “${x.match_title}”`).join('\n');
        if (confirm(`${d.dupes.length} look like topics you already have:\n\n${lines}\n\nSkip the duplicates? (Cancel adds everything anyway)`)) {
          const skip = new Set(d.dupes.map(x => x.title));
          items = items.filter(i => !skip.has(i.title));
          if (!items.length) { toast('All were duplicates — nothing added.'); addBtn.disabled = false; updateCount(); return; }
        }
      }
    } catch {}
    addBtn.textContent = 'Adding…';
    try {
      const res = await api.bulkTopics({ items, subject: subjectInput.value.trim() || null,
        tags: tagsInput.value.split(',').map(t => t.trim()).filter(Boolean),
        per_day: Math.max(1, parseInt(perDay.value, 10) || 8) });
      toast(`Added ${res.created} topic${res.created !== 1 ? 's' : ''} — easing in ${perDay.value}/day`);
      refreshBadge(); navigate('#/library');
    } catch (e) { toast('Add failed: ' + e.message); addBtn.disabled = false; updateCount(); }
  });

  root.append(el('div', { class: 'card stack' },
    el('div', { class: 'row spread' }, el('div', { class: 'eyebrow' }, 'Add topics in bulk'), countLbl),
    el('p', { class: 'muted', style: { fontSize: '13px', marginTop: '-4px' } },
      'One per line — each becomes a topic with a free-recall prompt. They ease into review a few per day.'),
    text,
    el('div', { class: 'row wrap', style: { gap: '12px' } },
      el('div', { class: 'field', style: { flex: '1', minWidth: '150px' } }, el('label', { class: 'lbl' }, 'Subject (all)'), subjectInput, subjList),
      el('div', { class: 'field', style: { flex: '1', minWidth: '150px' } }, el('label', { class: 'lbl' }, 'Tags (all)'), tagsInput),
      el('div', { class: 'field' }, el('label', { class: 'lbl' }, 'New / day', infoTip('How many of these topics become due each day, so a big batch eases into your routine gradually instead of all at once.')), perDay)),
    el('div', { class: 'row', style: { justifyContent: 'flex-end' } }, addBtn)));

  if (llmOk) {
    const splitText = el('textarea', { class: 'input', rows: '4', placeholder: 'Paste an outline or messy notes…' });
    const splitBtn = el('button', { class: 'btn' }, '✨ Split into topics');
    splitBtn.addEventListener('click', async () => {
      const t = splitText.value.trim();
      if (!t) { toast('Paste some text first.'); return; }
      splitBtn.disabled = true; splitBtn.textContent = 'Thinking…';
      try {
        const res = await api.splitTopics(t);
        const tops = res.topics || [];
        if (!tops.length) { toast('No topics found.'); }
        else {
          const add = tops.map(x => x.note ? `${x.title} — ${x.note}` : x.title).join('\n');
          text.value = (text.value.trim() ? text.value.trim() + '\n' : '') + add;
          updateCount();
          toast(`Pulled out ${tops.length} — review & save above`);
        }
      } catch (e) { toast(e.status === 503 ? 'Start Ollama to use AI split' : 'Split failed'); }
      splitBtn.disabled = false; splitBtn.textContent = '✨ Split into topics';
    });
    root.append(el('div', { class: 'card stack', style: { marginTop: '16px' } },
      el('div', { class: 'eyebrow' }, 'Or let AI split a paste'),
      el('p', { class: 'muted', style: { fontSize: '13px', marginTop: '-4px' } },
        'Paste an outline or notes; the local model pulls out a topic list into the box above.'),
      splitText,
      el('div', { class: 'row', style: { justifyContent: 'flex-end' } }, splitBtn)));
  }
  updateCount();
}
