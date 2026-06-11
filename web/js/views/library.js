// Library — browse / search / edit learnings and their cards.
import { el, clear, toast, agoDate, relDate, state } from '../store.js';
import { api } from '../api.js';
import { navigate, refreshBadge } from '../app.js';

function parseConversation(raw) {
  if (!raw) return [];
  try { const a = JSON.parse(raw); return Array.isArray(a) ? a.filter(m => m && m.content) : []; }
  catch { return []; }
}

export async function render({ rest } = {}) {
  if (rest && rest[0]) return detail(Number(rest[0]));
  return list();
}

async function list() {
  const view = el('div', { class: 'view' });
  view.append(el('div', { class: 'page-head' }, el('h1', {}, 'Library'),
    el('p', { class: 'sub' }, 'Browse what you’ve learned by subject area.')));

  let mode = 'explore', search = '', activeTag = null, timer = null;
  const llmOk = !!(state.llm && state.llm.available);

  const exploreBtn = el('button', { class: 'chip on', onClick: () => setMode('explore') }, 'Explore');
  const listBtn = el('button', { class: 'chip', onClick: () => setMode('list') }, 'List');
  const searchInput = el('input', { class: 'input', placeholder: 'Search…', style: { maxWidth: '280px' } });
  view.append(el('div', { class: 'row spread', style: { marginBottom: '14px' } },
    el('div', { class: 'row', style: { gap: '7px' } }, exploreBtn, listBtn), searchInput));

  const reviewSlot = el('div', {});
  const content = el('div', {});
  view.append(reviewSlot, content);

  function setMode(m) {
    mode = m;
    exploreBtn.classList.toggle('on', m === 'explore');
    listBtn.classList.toggle('on', m === 'list');
    clear(reviewSlot);
    render();
  }
  searchInput.addEventListener('input', () => {
    clearTimeout(timer);
    search = searchInput.value.trim();
    if (search && mode === 'explore') setMode('list');
    else timer = setTimeout(render, 220);
  });
  function render() { return mode === 'explore' ? renderExplore() : renderList(); }

  // ---------- Explore (grouped by subject) ----------
  async function renderExplore() {
    const data = await api.listLearnings();
    clear(content);
    if (!data.learnings.length) { content.append(emptyState()); return; }
    const bySubject = new Map();
    for (const l of data.learnings) {
      const key = l.subject || '';
      if (!bySubject.has(key)) bySubject.set(key, []);
      bySubject.get(key).push(l);
    }
    for (const s of data.subjects) content.append(subjectSection(s, bySubject.get(s.name) || []));
  }

  function subjectSection(summary, items) {
    const isUncat = summary.name === '';
    const allFocused = items.length > 0 && items.every(i => i.priority);
    const focusAreaBtn = isUncat ? null : el('button', {
      class: 'btn' + (allFocused ? ' on-accent' : ''), style: { padding: '6px 12px' },
      onClick: async (e) => {
        e.stopPropagation();
        const next = allFocused ? 0 : 1;
        e.currentTarget.disabled = true;
        await api.focusApply({ subjects: [summary.name], learning_ids: [], priority: next });
        toast(next ? `Focusing all of ${summary.name}` : `Unfocused ${summary.name}`);
        refreshBadge(); renderExplore();
      } }, allFocused ? '★ Focused' : '☆ Focus area');
    const actions = el('div', { class: 'row', style: { gap: '8px' } },
      focusAreaBtn,
      (isUncat && llmOk && items.length) ? el('button', { class: 'btn', style: { padding: '6px 12px' }, onClick: (e) => { e.stopPropagation(); suggest(e.currentTarget); } }, 'Suggest subjects') : null,
      summary.due > 0 ? el('button', { class: 'btn', style: { padding: '6px 12px' }, onClick: (e) => { e.stopPropagation(); navigate('#/recall?subject=' + encodeURIComponent(summary.name)); } }, 'Review area →') : null);

    // With a seeded curriculum the Library holds ~100 topics: sections collapse,
    // and only areas with due work start open.
    let open = summary.due > 0 || isUncat;
    const chev = el('span', { class: 'muted', style: { fontSize: '13px', width: '14px', flex: 'none' } }, open ? '▾' : '▸');
    const head = el('div', { class: 'row spread subj-head', style: { margin: '6px 2px 10px' },
      onClick: () => { open = !open; rows.style.display = open ? '' : 'none'; chev.textContent = open ? '▾' : '▸'; } },
      el('div', { class: 'row', style: { gap: '10px', minWidth: '0' } },
        chev,
        el('h3', { style: { fontSize: '16px' } }, isUncat ? 'Uncategorized' : summary.name),
        el('span', { class: 'muted', style: { fontSize: '12.5px' } },
          `${summary.learnings} concept${summary.learnings !== 1 ? 's' : ''} · ${summary.cards} card${summary.cards !== 1 ? 's' : ''}`),
        summary.due > 0 ? el('span', { class: 'pill-due' }, `${summary.due} due`) : null),
      actions);
    const rows = el('div', { class: 'stack', style: { gap: '8px', display: open ? '' : 'none' } });
    for (const l of items) rows.append(conceptRow(l));
    return el('div', { style: { marginBottom: '18px' } }, head, rows);
  }

  function starBtn(l) {
    const btn = el('button', { class: 'star' + (l.priority ? ' on' : ''), title: 'Focus: reviewed first',
      onClick: async (e) => {
        e.stopPropagation();
        l.priority = l.priority ? 0 : 1;
        btn.classList.toggle('on', !!l.priority);
        await api.setPriority(l.id, l.priority);
        toast(l.priority ? 'Focused. Goes first in sessions' : 'Unfocused');
      } }, '★');
    return btn;
  }

  function conceptRow(l) {
    return el('div', { class: 'list-row', onClick: () => navigate('#/library/' + l.id) },
      starBtn(l),
      el('div', { style: { flex: '1', minWidth: '0' } },
        el('div', { class: 'title' }, l.title),
        el('div', { class: 'meta' }, `${l.card_count} card${l.card_count !== 1 ? 's' : ''} · ${agoDate(l.created_at)}`, l.tags.length ? ' · ' + l.tags.join(', ') : '', l.private ? ' · private' : '')),
      l.due_count > 0 ? el('span', { class: 'pill-due' }, `${l.due_count} due`) : el('span', { class: 'pill-ok' }, 'scheduled'));
  }

  // ---------- AI backfill ----------
  async function suggest(btn) {
    const label = btn.textContent; btn.disabled = true; btn.textContent = 'Thinking…';
    try {
      const res = await api.suggestSubjects();
      btn.disabled = false; btn.textContent = label;
      if (!res.suggestions || !res.suggestions.length) { toast('Nothing to categorize'); return; }
      await renderReview(res.suggestions);
      window.scrollTo({ top: 0, behavior: 'smooth' });
    } catch (e) {
      btn.disabled = false; btn.textContent = label;
      toast(e.status === 503 ? 'Start Ollama to use AI suggestions' : 'Suggestion failed');
    }
  }

  async function renderReview(suggestions) {
    const names = (await api.subjects().catch(() => ({ names: [] }))).names || [];
    const dl = el('datalist', { id: 'subj-list-lib' }, ...names.map(n => el('option', { value: n })));
    const rows = suggestions.map(s => {
      const chk = el('input', { type: 'checkbox', checked: '', style: { width: '16px', height: '16px', accentColor: 'var(--accent)' } });
      const inp = el('input', { class: 'input', value: s.subject, list: 'subj-list-lib', style: { maxWidth: '220px' } });
      return { s, chk, inp, node: el('div', { class: 'row', style: { gap: '10px', padding: '7px 0' } },
        chk, el('div', { class: 'soft', style: { flex: '1', minWidth: '0' } }, s.title), el('span', { class: 'muted' }, '→'), inp) };
    });
    const applyBtn = el('button', { class: 'btn btn-primary' }, `Apply ${rows.length}`);
    applyBtn.addEventListener('click', async () => {
      const assignments = rows.filter(r => r.chk.checked && r.inp.value.trim()).map(r => ({ id: r.s.id, subject: r.inp.value.trim() }));
      if (!assignments.length) { toast('Nothing selected'); return; }
      applyBtn.disabled = true; applyBtn.textContent = 'Applying…';
      await api.assignSubjects(assignments);
      toast(`Categorized ${assignments.length} concept${assignments.length !== 1 ? 's' : ''}`);
      clear(reviewSlot); refreshBadge(); renderExplore();
    });
    clear(reviewSlot);
    reviewSlot.append(el('div', { class: 'card', style: { marginBottom: '18px', borderColor: 'var(--accent)' } },
      el('div', { class: 'eyebrow', style: { marginBottom: '10px' } }, 'Suggested subjects. Edit, then apply'),
      dl, ...rows.map(r => r.node),
      el('div', { class: 'row', style: { justifyContent: 'flex-end', gap: '8px', marginTop: '12px' } },
        el('button', { class: 'btn btn-ghost', onClick: () => clear(reviewSlot) }, 'Cancel'), applyBtn)));
  }

  // ---------- List (flat + search + tags) ----------
  async function renderList() {
    const data = await api.listLearnings(search, activeTag);
    clear(content);
    const chipRow = el('div', { class: 'row wrap', style: { gap: '7px', marginBottom: '14px' } });
    chipRow.append(el('button', { class: 'chip' + (activeTag ? '' : ' on'), onClick: () => { activeTag = null; renderList(); } }, 'All'));
    for (const t of data.tags) chipRow.append(el('button', { class: 'chip' + (activeTag === t.name ? ' on' : ''), onClick: () => { activeTag = t.name; renderList(); } }, `${t.name} · ${t.count}`));
    content.append(chipRow);
    if (!data.learnings.length) { content.append(emptyState()); return; }
    const rows = el('div', { class: 'stack' });
    for (const l of data.learnings) {
      rows.append(el('div', { class: 'list-row', onClick: () => navigate('#/library/' + l.id) },
        starBtn(l),
        el('div', { style: { flex: '1', minWidth: '0' } },
          el('div', { class: 'title' }, l.title),
          el('div', { class: 'meta' }, (l.subject ? l.subject + ' · ' : '') + `${l.card_count} card${l.card_count !== 1 ? 's' : ''} · ${agoDate(l.created_at)}` + (l.private ? ' · private' : ''))),
        l.due_count > 0 ? el('span', { class: 'pill-due' }, `${l.due_count} due`) : el('span', { class: 'pill-ok' }, 'scheduled')));
    }
    content.append(rows);
  }

  function emptyState() {
    return el('div', { class: 'empty' }, 
      el('h2', {}, search || activeTag ? 'Nothing matches' : 'Nothing captured yet'),
      el('p', { class: 'muted' }, 'Head to Reflect to add your first learning.'),
      el('div', { class: 'row', style: { justifyContent: 'center', marginTop: '16px' } },
        el('button', { class: 'btn btn-primary', onClick: () => navigate('#/reflect') }, 'Reflect →')));
  }

  await render();
  return view;
}

async function detail(id) {
  const data = await api.getLearning(id);
  if (!data || data.error) { const v = el('div', { class: 'view' }); v.append(el('p', {}, 'Not found.')); return v; }
  const L = data.learning;
  const view = el('div', { class: 'view' });
  const llmOk = !!(state.llm && state.llm.available);

  let prio = L.priority || 0;
  const focusBtn = el('button', { class: 'btn' + (prio ? ' on-accent' : ''), onClick: async () => {
    prio = prio ? 0 : 1;
    await api.setPriority(id, prio);
    focusBtn.textContent = prio ? '★ Focused' : '☆ Focus';
    focusBtn.classList.toggle('on-accent', !!prio);
    toast(prio ? 'Focused. Goes first in sessions' : 'Unfocused');
  } }, prio ? '★ Focused' : '☆ Focus');

  // Private: this topic is refused by every cloud path, like People.
  // People topics are always private; the button becomes a fixed marker.
  const isPeople = (L.subject || '').trim().toLowerCase() === 'people';
  let priv = isPeople || !!L.private;
  const privBtn = el('button', {
    class: 'btn' + (priv ? ' on-accent' : ''),
    title: isPeople ? 'People topics never leave this machine.'
                    : 'Private topics are never sent to any cloud model, like People.',
    onClick: async () => {
      if (isPeople) { toast('People are always private.'); return; }
      priv = !priv;
      try {
        await api.setPrivate(id, priv);
        privBtn.textContent = priv ? 'Private' : 'Mark private';
        privBtn.classList.toggle('on-accent', priv);
        toast(priv ? 'Private. This topic never goes to the cloud.' : 'No longer marked private.');
      } catch (e) { priv = !priv; toast(e.message); }
    } }, priv ? 'Private' : 'Mark private');

  const solid = data.cards.some(c => c.card_type === 'recall' && c.stability >= 21);
  view.append(el('div', { class: 'row spread', style: { marginBottom: '18px' } },
    el('button', { class: 'btn btn-ghost', onClick: () => navigate('#/library') }, '← Library'),
    el('div', { class: 'row', style: { gap: '8px' } },
      privBtn,
      focusBtn,
      (llmOk && solid) ? el('button', { class: 'btn', title: 'Explain it simply; the AI plays a confused student',
        onClick: () => navigate('#/recall?teach=' + id) }, 'Teach it') : null,
      el('button', { class: 'btn', onClick: () => navigate('#/recall?learning=' + id) }, 'Review these →'),
      el('button', { class: 'btn btn-danger', onClick: del }, 'Delete'))));

  const subjectNames = (await api.subjects().catch(() => ({ names: [] }))).names || [];
  const titleInput = el('input', { class: 'input', value: L.title, style: { fontSize: '20px', fontWeight: '600' } });
  const contentArea = el('textarea', { class: 'input', rows: '4' }); contentArea.value = L.content || '';
  const notesArea = el('textarea', { class: 'input', rows: '3', placeholder: 'Add notes over time: corrections, links, fresh examples…' }); notesArea.value = L.notes || '';
  const tagsInput = el('input', { class: 'input', value: (L.tags || []).join(', ') });
  const subjectList = el('datalist', { id: 'subj-list-d' }, ...subjectNames.map(n => el('option', { value: n })));
  const subjectInput = el('input', { class: 'input', value: L.subject || '', placeholder: 'e.g. Machine Learning', list: 'subj-list-d' });

  view.append(el('div', { class: 'card stack' },
    el('div', { class: 'field' }, el('label', { class: 'lbl' }, 'Title'), titleInput),
    el('div', { class: 'field' }, el('label', { class: 'lbl' }, 'Subject / area'), subjectInput, subjectList),
    el('div', { class: 'field' }, el('label', { class: 'lbl' }, 'What you learned'), contentArea),
    el('div', { class: 'field' }, el('label', { class: 'lbl' }, 'My notes'), notesArea),
    el('div', { class: 'field' }, el('label', { class: 'lbl' }, 'Tags'), tagsInput),
    el('div', { class: 'row', style: { justifyContent: 'flex-end' } },
      el('button', { class: 'btn btn-primary', onClick: saveMeta }, 'Save'))));

  // capture conversation (read-only, collapsed)
  const convo = parseConversation(L.conversation);
  if (convo.length) {
    const chev = el('span', { class: 'muted', style: { fontSize: '12px' } }, '▸');
    const log = el('div', { class: 'chat-log', style: { marginTop: '12px' } });
    for (const m of convo) log.append(el('div', { class: 'msg ' + (m.role === 'user' ? 'user' : 'ai') }, m.content));
    const body = el('div', { style: { display: 'none' } }, log);
    let open = false;
    const toggle = el('button', { class: 'btn btn-ghost', style: { width: '100%', justifyContent: 'space-between', padding: '10px 12px' },
      onClick: () => { open = !open; body.style.display = open ? '' : 'none'; chev.textContent = open ? '▾' : '▸'; } },
      el('span', {}, `Capture conversation · ${convo.length} message${convo.length !== 1 ? 's' : ''}`), chev);
    view.append(el('div', { class: 'card', style: { marginTop: '16px', padding: '6px' } }, toggle, body));
  }

  // related concepts (local embeddings) — loads async, hidden when unavailable
  const relatedSlot = el('div', {});
  view.append(relatedSlot);
  api.related(id).then(r => {
    if (!r.embeddings || !r.related.length) return;
    const panel = el('div', { class: 'card', style: { marginTop: '16px' } },
      el('div', { class: 'eyebrow', style: { marginBottom: '10px' } }, 'Related concepts'));
    for (const rel of r.related) {
      panel.append(el('div', { class: 'row spread', style: { padding: '7px 0', borderBottom: '1px solid var(--border)', cursor: 'pointer' },
        onClick: () => navigate('#/library/' + rel.id) },
        el('span', { class: 'soft', style: { fontSize: '14px' } }, rel.title),
        el('span', { class: 'muted', style: { fontSize: '12px' } },
          rel.score >= 0.86 ? `very close · ${rel.score}` : rel.score >= 0.7 ? `close · ${rel.score}` : `related · ${rel.score}`)));
    }
    if (r.contrast) {
      const addBtn = el('button', { class: 'btn btn-primary', style: { padding: '6px 12px', fontSize: '13px' }, onClick: async () => {
        addBtn.disabled = true; addBtn.textContent = 'Writing…';
        try {
          const res = await api.addContrast(id, r.contrast.with_id);
          toast('Contrast card added'); refreshBadge(); box.remove(); reloadCards();
        } catch { toast('Could not generate. Is Ollama up?'); addBtn.disabled = false; addBtn.textContent = 'Add contrast card'; }
      } }, 'Add contrast card');
      const box = el('div', { style: { border: '1px dashed var(--hard)', borderRadius: '11px', padding: '12px 14px', marginTop: '12px', background: 'var(--hard-weak)' } },
        el('div', { style: { fontSize: '13.5px' } }, el('b', { style: { color: 'var(--hard)' } }, 'Easily confused? '),
          el('span', { class: 'soft' }, `“${L.title}” and “${r.contrast.with_title}” are very close; a contrast card drills the difference directly.`)),
        el('div', { class: 'row', style: { gap: '8px', marginTop: '10px' } }, addBtn,
          el('button', { class: 'btn-ghost', style: { fontSize: '13px' }, onClick: () => box.remove() }, 'Dismiss')));
      panel.append(box);
    }
    relatedSlot.append(panel);
  }).catch(() => {});

  // cards
  view.append(el('div', { class: 'row spread', style: { margin: '24px 0 12px' } },
    el('div', { class: 'eyebrow' }, `${data.cards.length} prompt${data.cards.length !== 1 ? 's' : ''}`),
    el('div', { class: 'row', style: { gap: '8px' } },
      llmOk ? el('button', { class: 'btn', style: { padding: '6px 12px' }, onClick: genMore }, 'Generate more') : null,
      el('button', { class: 'btn', style: { padding: '6px 12px' }, onClick: addCard }, '+ Add'))));

  const cardList = el('div', { class: 'stack' });
  view.append(cardList);
  for (const c of data.cards) cardList.append(cardEditor(c));

  function cardEditor(c) {
    const node = el('div', { class: 'card' });
    const q = el('input', { class: 'input', value: c.question });
    const a = el('input', { class: 'input', value: c.answer });
    const stateLabel = c.suspended ? 'suspended' : (c.next_review_at ? relDate(c.next_review_at) : 'new');
    node.append(
      el('div', { class: 'row spread', style: { marginBottom: '8px' } },
        el('span', { class: 'tag' }, c.card_type === 'cloze' ? 'cloze' : (c.card_type === 'recall' ? 'free recall' : 'question')),
        el('span', { class: 'muted', style: { fontSize: '12px' } }, `due ${stateLabel} · S=${c.stability}`)),
      el('div', { class: 'field', style: { marginBottom: '8px' } }, el('label', { class: 'lbl' }, 'Question'), q),
      el('div', { class: 'field', style: { marginBottom: '10px' } }, el('label', { class: 'lbl' }, 'Answer'), a),
      el('div', { class: 'row', style: { gap: '8px', justifyContent: 'flex-end' } },
        el('button', { class: 'btn-ghost', style: { fontSize: '13px' }, onClick: async () => { await api.suspendCard(c.id, !c.suspended); toast(c.suspended ? 'Unsuspended' : 'Suspended'); refreshBadge(); reloadCards(); } }, c.suspended ? 'Unsuspend' : 'Suspend'),
        el('button', { class: 'btn-danger', style: { fontSize: '13px' }, onClick: async () => { await api.deleteCard(c.id); node.remove(); refreshBadge(); toast('Card deleted'); } }, 'Delete'),
        el('button', { class: 'btn', style: { fontSize: '13px', padding: '6px 12px' }, onClick: async () => { await api.updateCard(c.id, { question: q.value, answer: a.value }); toast('Saved'); } }, 'Save')));
    return node;
  }

  async function saveMeta() {
    await api.updateLearning(id, {
      title: titleInput.value.trim(), content: contentArea.value.trim(),
      reflection: L.reflection || null,
      subject: subjectInput.value.trim() || null,
      notes: notesArea.value.trim() || null,
      tags: tagsInput.value.split(',').map(t => t.trim()).filter(Boolean),
    });
    toast('Saved');
  }
  async function genMore(e) {
    const btn = e.currentTarget, orig = btn.textContent;
    btn.disabled = true; btn.textContent = 'Thinking…';
    try {
      const r = await api.generateMore(id);
      toast(r.added ? `Added ${r.added} question${r.added !== 1 ? 's' : ''}` : 'No new questions');
      refreshBadge(); await reloadCards();
    } catch (err) { toast(err.status === 503 ? 'Start Ollama to generate' : 'Generation failed'); }
    btn.disabled = false; btn.textContent = orig;
  }
  async function addCard() {
    const res = await api.addCard(id, { type: 'basic', question: 'New question', answer: 'Answer' });
    if (res.added) { toast('Card added'); refreshBadge(); reloadCards(); }
  }
  async function reloadCards() {
    const fresh = await api.getLearning(id);
    clear(cardList);
    for (const c of fresh.cards) cardList.append(cardEditor(c));
  }
  async function del() {
    if (!confirm('Delete this learning and all its cards?')) return;
    await api.deleteLearning(id);
    refreshBadge();
    toast('Deleted');
    navigate('#/library');
  }

  return view;
}
