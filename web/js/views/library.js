// Library — browse / search / edit learnings and their cards.
import { el, clear, toast, agoDate, relDate } from '../store.js';
import { api } from '../api.js';
import { navigate, refreshBadge } from '../app.js';

export async function render({ rest } = {}) {
  if (rest && rest[0]) return detail(Number(rest[0]));
  return list();
}

async function list() {
  const view = el('div', { class: 'view' });
  view.append(el('div', { class: 'page-head' }, el('h1', {}, 'Library'),
    el('p', { class: 'sub' }, 'Everything you’ve captured.')));

  let activeTag = null, search = '', timer = null;
  const searchInput = el('input', { class: 'input', placeholder: 'Search…', style: { maxWidth: '320px' } });
  const chipRow = el('div', { class: 'row wrap', style: { gap: '7px' } });
  const rows = el('div', { class: 'stack' });
  view.append(el('div', { class: 'row spread', style: { marginBottom: '12px' } }, searchInput));
  view.append(chipRow, el('div', { style: { height: '14px' } }), rows);

  async function load() {
    const data = await api.listLearnings(search, activeTag);
    // tag chips
    clear(chipRow);
    chipRow.append(el('button', { class: 'chip' + (activeTag ? '' : ' on'), onClick: () => { activeTag = null; load(); } }, 'All'));
    for (const t of data.tags) {
      chipRow.append(el('button', { class: 'chip' + (activeTag === t.name ? ' on' : ''), onClick: () => { activeTag = t.name; load(); } }, `${t.name} · ${t.count}`));
    }
    // rows
    clear(rows);
    if (!data.learnings.length) {
      rows.append(el('div', { class: 'empty' }, el('div', { class: 'icon' }, '📚'),
        el('h2', {}, search || activeTag ? 'Nothing matches' : 'Nothing captured yet'),
        el('p', { class: 'muted' }, 'Head to Reflect to add your first learning.'),
        el('div', { class: 'row', style: { justifyContent: 'center', marginTop: '16px' } },
          el('button', { class: 'btn btn-primary', onClick: () => navigate('#/reflect') }, 'Reflect →'))));
      return;
    }
    for (const l of data.learnings) {
      rows.append(el('div', { class: 'list-row', onClick: () => navigate('#/library/' + l.id) },
        el('div', { style: { flex: '1', minWidth: '0' } },
          el('div', { class: 'title' }, l.title),
          el('div', { class: 'meta' }, `${l.card_count} card${l.card_count !== 1 ? 's' : ''} · ${agoDate(l.created_at)}`, l.tags.length ? ' · ' + l.tags.join(', ') : '')),
        l.due_count > 0 ? el('span', { class: 'pill-due' }, `${l.due_count} due`) : el('span', { class: 'pill-ok' }, 'scheduled')));
    }
  }

  searchInput.addEventListener('input', () => { clearTimeout(timer); search = searchInput.value.trim(); timer = setTimeout(load, 220); });
  await load();
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

  const titleInput = el('input', { class: 'input', value: L.title, style: { fontSize: '20px', fontWeight: '600' } });
  const contentArea = el('textarea', { class: 'input', rows: '4' }); contentArea.value = L.content || '';
  const reflectionArea = el('textarea', { class: 'input', rows: '3' }); reflectionArea.value = L.reflection || '';
  const tagsInput = el('input', { class: 'input', value: (L.tags || []).join(', ') });

  view.append(el('div', { class: 'card stack' },
    el('div', { class: 'field' }, el('label', { class: 'lbl' }, 'Title'), titleInput),
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
