// Library — browse / search / edit learnings and their cards.
import { el, clear, toast, agoDate, relDate, state } from '../store.js';
import { api } from '../api.js';
import { navigate, refreshBadge } from '../app.js';

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
    const actions = el('div', { class: 'row', style: { gap: '8px' } },
      (isUncat && llmOk && items.length) ? el('button', { class: 'btn', style: { padding: '6px 12px' }, onClick: (e) => suggest(e.currentTarget) }, '✨ Suggest subjects') : null,
      summary.due > 0 ? el('button', { class: 'btn', style: { padding: '6px 12px' }, onClick: () => navigate('#/recall?subject=' + encodeURIComponent(summary.name)) }, 'Review area →') : null);
    const head = el('div', { class: 'row spread', style: { margin: '6px 2px 10px' } },
      el('div', { class: 'row', style: { gap: '10px' } },
        el('h3', { style: { fontSize: '16px' } }, isUncat ? 'Uncategorized' : summary.name),
        el('span', { class: 'muted', style: { fontSize: '12.5px' } },
          `${summary.learnings} concept${summary.learnings !== 1 ? 's' : ''} · ${summary.cards} card${summary.cards !== 1 ? 's' : ''}`),
        summary.due > 0 ? el('span', { class: 'pill-due' }, `${summary.due} due`) : null),
      actions);
    const rows = el('div', { class: 'stack', style: { gap: '8px' } });
    for (const l of items) rows.append(conceptRow(l));
    return el('div', { style: { marginBottom: '26px' } }, head, rows);
  }

  function conceptRow(l) {
    return el('div', { class: 'list-row', onClick: () => navigate('#/library/' + l.id) },
      el('div', { style: { flex: '1', minWidth: '0' } },
        el('div', { class: 'title' }, l.title),
        el('div', { class: 'meta' }, `${l.card_count} card${l.card_count !== 1 ? 's' : ''} · ${agoDate(l.created_at)}`, l.tags.length ? ' · ' + l.tags.join(', ') : '')),
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
      el('div', { class: 'eyebrow', style: { marginBottom: '10px' } }, '✨ Suggested subjects — edit, then apply'),
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
        el('div', { style: { flex: '1', minWidth: '0' } },
          el('div', { class: 'title' }, l.title),
          el('div', { class: 'meta' }, (l.subject ? l.subject + ' · ' : '') + `${l.card_count} card${l.card_count !== 1 ? 's' : ''} · ${agoDate(l.created_at)}`)),
        l.due_count > 0 ? el('span', { class: 'pill-due' }, `${l.due_count} due`) : el('span', { class: 'pill-ok' }, 'scheduled')));
    }
    content.append(rows);
  }

  function emptyState() {
    return el('div', { class: 'empty' }, el('div', { class: 'icon' }, '📚'),
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

  view.append(el('div', { class: 'row spread', style: { marginBottom: '18px' } },
    el('button', { class: 'btn btn-ghost', onClick: () => navigate('#/library') }, '← Library'),
    el('div', { class: 'row', style: { gap: '8px' } },
      el('button', { class: 'btn', onClick: () => navigate('#/recall?learning=' + id) }, 'Review these →'),
      el('button', { class: 'btn btn-danger', onClick: del }, 'Delete'))));

  const subjectNames = (await api.subjects().catch(() => ({ names: [] }))).names || [];
  const titleInput = el('input', { class: 'input', value: L.title, style: { fontSize: '20px', fontWeight: '600' } });
  const contentArea = el('textarea', { class: 'input', rows: '4' }); contentArea.value = L.content || '';
  const reflectionArea = el('textarea', { class: 'input', rows: '3' }); reflectionArea.value = L.reflection || '';
  const tagsInput = el('input', { class: 'input', value: (L.tags || []).join(', ') });
  const subjectList = el('datalist', { id: 'subj-list-d' }, ...subjectNames.map(n => el('option', { value: n })));
  const subjectInput = el('input', { class: 'input', value: L.subject || '', placeholder: 'e.g. Machine Learning', list: 'subj-list-d' });

  view.append(el('div', { class: 'card stack' },
    el('div', { class: 'field' }, el('label', { class: 'lbl' }, 'Title'), titleInput),
    el('div', { class: 'field' }, el('label', { class: 'lbl' }, 'Subject / area'), subjectInput, subjectList),
    el('div', { class: 'field' }, el('label', { class: 'lbl' }, 'What you learned'), contentArea),
    el('div', { class: 'field' }, el('label', { class: 'lbl' }, 'Reflection notes'), reflectionArea),
    el('div', { class: 'field' }, el('label', { class: 'lbl' }, 'Tags'), tagsInput),
    el('div', { class: 'row', style: { justifyContent: 'flex-end' } },
      el('button', { class: 'btn btn-primary', onClick: saveMeta }, 'Save'))));

  // cards
  view.append(el('div', { class: 'row spread', style: { margin: '24px 0 12px' } },
    el('div', { class: 'eyebrow' }, `${data.cards.length} card${data.cards.length !== 1 ? 's' : ''}`),
    el('button', { class: 'btn', style: { padding: '6px 12px' }, onClick: addCard }, '+ Add card')));

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
        el('span', { class: 'tag' }, c.card_type === 'cloze' ? 'cloze' : 'basic'),
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
      reflection: reflectionArea.value.trim() || null,
      subject: subjectInput.value.trim() || null,
      tags: tagsInput.value.split(',').map(t => t.trim()).filter(Boolean),
    });
    toast('Saved');
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
