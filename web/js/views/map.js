// Library › Map — the outline of areas you want to keep, with status computed
// from the topics linked to each item. Keyboard-first like an outliner:
//   ↑/↓ select · ←/→ fold · Enter edit · (editing) Enter new item below
//   Tab / Shift+Tab indent / outdent · Alt+↑/↓ move · Delete remove
import { el, clear, toast } from '../store.js';
import { api } from '../api.js';
import { navigate, refreshBadge } from '../app.js';
import { indexTree, dotEl, barEl, barText, pct, legendEl, atlasEl, branchPanel,
         untouchedLabel, STATE_LABEL } from '../knowledge.js';

const OPEN_KEY = 'rr-map-open';
const MODE_KEY = 'rr-map-mode';

function loadSet(key) {
  try { return new Set(JSON.parse(localStorage.getItem(key) || '[]')); } catch { return new Set(); }
}
function saveSet(key, set) {
  try { localStorage.setItem(key, JSON.stringify([...set])); } catch {}
}

export async function mapView({ focusId = null } = {}) {
  const root = el('div', { class: 'map-view' });
  let tree = null, idx = null;
  const open = loadSet(OPEN_KEY);
  let selected = focusId, editing = null, freshId = null;
  let source = '', query = '';
  let mode = 'outline';
  try { mode = localStorage.getItem(MODE_KEY) || 'outline'; } catch {}
  let atlasParent = null, atlasSel = null;
  let visible = [];
  let learnings = null;                       // lazy: [{id,title}] for the link picker
  let redrawing = false;                      // removing a focused input fires blur: ignore it

  // ---------- toolbar ----------
  const outlineBtn = el('button', { class: 'chip', onClick: () => setMode('outline') }, 'Outline');
  const atlasBtn = el('button', { class: 'chip', onClick: () => setMode('atlas') }, 'Atlas');
  const sourceRow = el('div', { class: 'row', style: { gap: '6px' } });
  const search = el('input', { class: 'input map-search', placeholder: 'Filter map…', 'aria-label': 'Filter map' });
  let searchTimer;
  search.addEventListener('input', () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => { query = search.value.trim().toLowerCase(); draw(); }, 160);
  });
  const panelSlot = el('div', {});
  const toolbar = el('div', { class: 'map-toolbar' },
    el('div', { class: 'row', style: { gap: '6px' } }, outlineBtn, atlasBtn),
    sourceRow,
    el('div', { class: 'row', style: { gap: '8px', marginLeft: 'auto' } },
      search,
      el('button', { class: 'btn', style: { padding: '6px 12px' }, onClick: showPlace }, 'Place topics'),
      el('button', { class: 'btn', style: { padding: '6px 12px' }, onClick: showImport }, 'Paste outline')));

  const main = el('div', { class: 'map-main' });
  const side = el('aside', { class: 'map-side' });
  root.append(toolbar, panelSlot, el('div', { class: 'map-body' }, main, side));

  function setMode(m) {
    mode = m;
    try { localStorage.setItem(MODE_KEY, m); } catch {}
    draw();
  }

  async function reload() {
    tree = await api.map();
    idx = indexTree(tree);
    if (focusId && idx.byId.has(focusId)) {        // deep link: unfold the path once
      let cur = idx.byId.get(focusId);
      while (cur && cur.parent_id) { open.add(cur.parent_id); cur = idx.byId.get(cur.parent_id); }
      saveSet(OPEN_KEY, open);
      mode = 'outline';
      focusId = null;
    }
    draw();
  }

  function draw() {
    redrawing = true;
    try { drawInner(); } finally { redrawing = false; }
  }

  function drawInner() {
    outlineBtn.classList.toggle('on', mode === 'outline');
    atlasBtn.classList.toggle('on', mode === 'atlas');
    clear(sourceRow);
    if (idx.sources.length) {
      sourceRow.append(el('button', { class: 'chip sm' + (source ? '' : ' on'), onClick: () => { source = ''; draw(); } }, 'All'));
      for (const s of idx.sources) sourceRow.append(el('button', { class: 'chip sm' + (source === s ? ' on' : ''),
        onClick: () => { source = source === s ? '' : s; draw(); } }, s));
    }
    clear(main);
    if (!idx.roots.length && !idx.inbox.length) { main.append(emptyState()); drawSide(); return; }
    if (mode === 'atlas') drawAtlas(); else drawOutline();
    drawSide();
  }

  // ---------- outline ----------
  function matches(n) {
    if (source && n.source !== source) return false;
    if (query && !n.text.toLowerCase().includes(query)) return false;
    return true;
  }

  function drawOutline() {
    const filtering = !!(query || source);
    let show = null;
    if (filtering) {                               // matches + their ancestors
      show = new Set();
      for (const n of idx.byId.values()) {
        if (n.kind !== 'item' || !matches(n)) continue;
        let cur = n;
        while (cur && !show.has(cur.id)) { show.add(cur.id); cur = idx.byId.get(cur.parent_id); }
      }
    }
    const list = el('div', { class: 'mtree', tabindex: '0', role: 'tree', 'aria-label': 'Knowledge map' });
    list.addEventListener('keydown', onTreeKey);
    visible = [];
    const walk = (nodes, depth) => {
      for (const n of nodes) {
        if (show && !show.has(n.id)) continue;
        visible.push(n.id);
        list.append(rowEl(n, depth));
        if (selected === n.id && editing !== n.id) list.append(detailEl(n));
        const kids = idx.childrenOf(n.id);
        if (kids.length && (open.has(n.id) || (filtering && query))) walk(kids, depth + 1);
      }
    };
    walk(idx.roots, 0);
    if (!visible.length) list.append(el('div', { class: 'muted', style: { padding: '18px' } }, 'Nothing matches.'));
    list.append(el('button', { class: 'mrow-add', onClick: () => addItem(null, idx.roots.at(-1)?.id ?? null, true) }, '+ Add area'));
    main.append(el('div', { class: 'card map-card' }, list,
      el('div', { class: 'map-keys muted' },
        'Enter edit · Tab / ⇧Tab indent · Alt+↑↓ move · ←→ fold · Del remove')));
    requestAnimationFrame(() => {
      if (editing) {
        const inp = list.querySelector('.mrow-edit');
        if (inp) { inp.focus(); inp.setSelectionRange(inp.value.length, inp.value.length); }
      } else if (selected) {
        const r = list.querySelector(`[data-id="${selected}"]`);
        if (r) r.scrollIntoView({ block: 'nearest' });
        if (!root.contains(document.activeElement) || document.activeElement === document.body) list.focus({ preventScroll: true });
      }
    });
  }

  function rowEl(n, depth) {
    const kids = idx.childrenOf(n.id);
    const isOpen = open.has(n.id);
    const heading = !n.state && kids.length;
    const chev = kids.length
      ? el('button', { class: 'mchev', 'aria-label': isOpen ? 'Collapse' : 'Expand',
          onClick: (e) => { e.stopPropagation(); toggle(n.id); } }, isOpen ? '▾' : '▸')
      : el('span', { class: 'mchev' });
    let label;
    if (editing === n.id) {
      label = el('input', { class: 'mrow-edit', value: n.text, 'aria-label': 'Item text' });
      label.addEventListener('keydown', (e) => onEditKey(e, n, label));
      label.addEventListener('blur', () => { if (!redrawing) commitEdit(n, label.value, { leave: true }); });
    } else {
      label = el('span', { class: 'mrow-text', onDblclick: (e) => { e.stopPropagation(); startEdit(n.id); } },
        n.text || el('span', { class: 'muted' }, 'untitled'));
    }
    let meta;
    if (heading) {
      meta = el('span', { class: 'mrow-meta' }, barEl(n.agg && n.agg.counts),
        el('span', { class: 'mrow-num' }, String((n.agg && n.agg.total) || 0)));
    } else if (n.state === 'none') {
      meta = el('span', { class: 'mrow-meta muted' }, 'no cards');
    } else if (n.state) {
      const lc = n.learning_ids.length;
      meta = el('span', { class: 'mrow-meta muted' },
        `${lc} topic${lc !== 1 ? 's' : ''} · ${n.r != null ? pct(n.r) : STATE_LABEL[n.state].toLowerCase()}`,
        n.due ? el('span', { class: 'mdue' }, ` · ${n.due} due`) : null);
    }
    return el('div', {
      class: 'mrow' + (selected === n.id ? ' sel' : '') + (depth === 0 ? ' root' : ''),
      'data-id': n.id, role: 'treeitem', 'aria-expanded': kids.length ? String(isOpen) : null,
      style: { paddingLeft: (8 + depth * 22) + 'px' },
      onClick: () => select(n.id),
    }, chev, heading ? null : dotEl(n.state, n.flag), label,
      n.flag ? el('span', { class: 'mflag', title: 'Flagged: lacking understanding' }, '!') : null,
      meta);
  }

  function detailEl(n) {
    const box = el('div', { class: 'mdetail' });
    const chips = el('div', { class: 'row wrap', style: { gap: '6px' } });
    for (const lid of n.learning_ids) {
      chips.append(el('span', { class: 'mtopic' },
        el('a', { href: '#/library/' + lid }, idx.titles[String(lid)] || `Topic ${lid}`),
        el('button', { class: 'mtopic-x', 'aria-label': 'Unlink topic', title: 'Unlink (the topic stays in your Library)',
          onClick: async (e) => { e.stopPropagation(); await api.mapUnlink(n.id, lid); reload(); } }, '×')));
    }
    const linkInput = el('input', { class: 'input mlink', placeholder: 'Link a topic…', list: 'map-topics',
      'aria-label': 'Link a topic by title' });
    const dl = el('datalist', { id: 'map-topics' });
    ensureLearnings().then(ls => { for (const l of ls) dl.append(el('option', { value: l.title })); });
    const tryLink = async () => {
      const v = linkInput.value.trim();
      if (!v) return;
      const ls = await ensureLearnings();
      const hit = ls.find(l => l.title === v) || ls.find(l => l.title.toLowerCase() === v.toLowerCase());
      if (!hit) { toast('No topic with that title'); return; }
      await api.mapLink(n.id, hit.id);
      toast(`Linked “${hit.title}”`);
      reload();
    };
    linkInput.addEventListener('change', tryLink);
    linkInput.addEventListener('keydown', (e) => { e.stopPropagation(); if (e.key === 'Enter') tryLink(); });
    linkInput.addEventListener('click', (e) => e.stopPropagation());
    if (n.learning_ids.length) box.append(chips);
    const agg = n.agg || {};
    box.append(el('div', { class: 'row wrap', style: { gap: '8px' } },
      linkInput, dl,
      el('button', { class: 'btn btn-primary sm', onClick: () => navigate('#/reflect?node=' + n.id) },
        n.learning_ids.length ? 'Add a topic in Reflect' : 'Cover in Reflect'),
      agg.due > 0 ? el('button', { class: 'btn sm', onClick: () => navigate('#/recall?node=' + n.id) }, `Review · ${agg.due} due`) : null,
      el('button', { class: 'btn sm', onClick: () => addItem(n.id, null, true) }, '+ Sub-item'),
      el('button', { class: 'btn sm' + (n.flag ? ' on-accent' : ''), title: 'Flag as lacking understanding',
        onClick: async () => { await api.mapUpdate(n.id, { flag: !n.flag }); reload(); } }, n.flag ? 'Flagged' : 'Flag'),
      el('button', { class: 'btn-danger sm', onClick: () => removeNode(n) }, 'Delete')));
    if (agg.total) box.append(el('div', { class: 'muted', style: { fontSize: '12.5px' } },
      `${barText(agg)} · ${untouchedLabel(agg.last)}`));
    box.addEventListener('click', (e) => e.stopPropagation());
    return box;
  }

  async function ensureLearnings() {
    if (!learnings) {
      const d = await api.listLearnings().catch(() => ({ learnings: [] }));
      learnings = d.learnings.map(l => ({ id: l.id, title: l.title }));
    }
    return learnings;
  }

  function toggle(id) {
    if (open.has(id)) open.delete(id); else open.add(id);
    saveSet(OPEN_KEY, open);
    draw();
  }
  function select(id) {
    if (editing) return;
    selected = selected === id ? null : id;
    draw();
  }
  function startEdit(id) { selected = id; editing = id; draw(); }

  async function addItem(parentId, afterId, edit) {
    const body = { text: '' };
    if (afterId != null) body.after_id = afterId; else if (parentId != null) body.parent_id = parentId;
    const r = await api.mapAdd(body);
    if (parentId != null) { open.add(parentId); saveSet(OPEN_KEY, open); }
    freshId = r.id;
    selected = r.id;
    editing = edit ? r.id : null;
    await reload();
  }

  let committing = false;
  async function commitEdit(n, value, { leave = false } = {}) {
    if (committing || editing !== n.id) return;
    committing = true;
    const text = value.trim();
    try {
      if (!text && freshId === n.id) {             // an empty new item: just drop it
        await api.mapDelete(n.id);
        selected = null;
      } else if (text && text !== n.text) {
        await api.mapUpdate(n.id, { text });
      }
      if (leave) { editing = null; freshId = null; await reload(); }
    } finally { committing = false; }
  }

  async function onEditKey(e, n, input) {
    e.stopPropagation();
    if (e.key === 'Escape') {
      e.preventDefault();
      await commitEdit(n, input.value, { leave: true });   // keeps what you typed
    } else if (e.key === 'Enter') {
      e.preventDefault();
      const text = input.value.trim();
      if (!text) return;
      await commitEdit(n, text);
      editing = null; freshId = null;
      await addItem(null, n.id, true);             // new sibling right below, ready to type
    } else if (e.key === 'Tab') {
      e.preventDefault();
      await commitEdit(n, input.value);
      const ok = (await api.mapShift(n.id, e.shiftKey ? 'outdent' : 'indent')).ok;
      if (ok && !e.shiftKey && n.parent_id !== undefined) {
        const sibs = idx.childrenOf(n.parent_id);
        const prev = sibs[sibs.findIndex(s => s.id === n.id) - 1];
        if (prev) { open.add(prev.id); saveSet(OPEN_KEY, open); }
      }
      await reload();
    } else if (e.key === 'Backspace' && !input.value) {
      e.preventDefault();
      const i = visible.indexOf(n.id);
      if (idx.childrenOf(n.id).length) return;
      await api.mapDelete(n.id);
      editing = null; freshId = null;
      selected = visible[i - 1] ?? null;
      if (selected) editing = selected;
      await reload();
    }
  }

  async function onTreeKey(e) {
    if (editing || e.target.closest('.mdetail')) return;
    const i = selected ? visible.indexOf(selected) : -1;
    const n = selected ? idx.byId.get(selected) : null;
    const k = e.key;
    if (k === 'ArrowDown' || k === 'ArrowUp') {
      e.preventDefault();
      if (e.altKey && n) { await api.mapShift(n.id, k === 'ArrowUp' ? 'up' : 'down'); await reload(); return; }
      const j = i < 0 ? 0 : Math.max(0, Math.min(visible.length - 1, i + (k === 'ArrowDown' ? 1 : -1)));
      selected = visible[j] ?? null; draw();
    } else if (!n) {
      return;
    } else if (k === 'ArrowRight') {
      e.preventDefault();
      if (idx.childrenOf(n.id).length && !open.has(n.id)) toggle(n.id);
    } else if (k === 'ArrowLeft') {
      e.preventDefault();
      if (open.has(n.id)) toggle(n.id);
      else if (n.parent_id) { selected = n.parent_id; draw(); }
    } else if (k === 'Enter') {
      e.preventDefault(); startEdit(n.id);
    } else if (k === 'Tab') {
      e.preventDefault();
      if ((await api.mapShift(n.id, e.shiftKey ? 'outdent' : 'indent')).ok) {
        if (!e.shiftKey) {
          const sibs = idx.childrenOf(n.parent_id);
          const prev = sibs[sibs.findIndex(s => s.id === n.id) - 1];
          if (prev) { open.add(prev.id); saveSet(OPEN_KEY, open); }
        }
        await reload();
      }
    } else if (k === 'Delete') {
      e.preventDefault(); removeNode(n);
    } else if (k === 'Escape') {
      selected = null; draw();
    }
  }

  async function removeNode(n) {
    const below = idx.descendants(n.id).length;
    if (below && !confirm(`Delete “${n.text}” and the ${below} item${below !== 1 ? 's' : ''} under it? Linked topics stay in your Library.`)) return;
    const i = visible.indexOf(n.id);
    await api.mapDelete(n.id);
    selected = visible[i - 1] ?? null;
    await reload();
  }

  // ---------- atlas ----------
  function drawAtlas() {
    const parent = atlasParent ? idx.byId.get(atlasParent) : null;
    if (atlasParent && !parent) atlasParent = null;
    const crumbs = el('div', { class: 'row', style: { gap: '6px', marginBottom: '10px', fontSize: '13.5px' } },
      el('button', { class: 'btn-ghost link-btn', onClick: () => { atlasParent = null; atlasSel = null; draw(); } }, 'All areas'),
      ...(parent ? idx.pathOf(parent.id).map((t, i, arr) => [el('span', { class: 'muted' }, '›'),
        i === arr.length - 1 ? el('b', {}, t) : el('span', { class: 'soft' }, t)]).flat() : []));
    const sel = atlasSel ? idx.byId.get(atlasSel) : null;
    const atlas = atlasEl(idx, { parentId: atlasParent, height: 340, selected: atlasSel,
      onSelect: (node) => { atlasSel = atlasSel === node.id ? null : node.id; draw(); } });
    const card = el('div', { class: 'card map-card', style: { padding: '16px' } }, crumbs, atlas, legendEl());
    if (sel) {
      const panel = branchPanel(idx, sel, {
        onReview: (node) => navigate('#/recall?node=' + node.id),
        onOpen: (node) => { selected = node.id; let cur = node;
          while (cur && cur.parent_id) { open.add(cur.parent_id); cur = idx.byId.get(cur.parent_id); }
          open.add(node.id); saveSet(OPEN_KEY, open); setMode('outline'); },
        onCover: (node) => navigate('#/reflect?node=' + node.id),
      });
      if (idx.childrenOf(sel.id).some(c => idx.childrenOf(c.id).length || c.agg)) {
        panel.firstChild.lastChild.prepend(el('button', { class: 'btn', style: { padding: '6px 12px' },
          onClick: () => { atlasParent = sel.id; atlasSel = null; draw(); } }, 'Zoom in'));
      }
      card.append(panel);
    }
    main.append(card);
  }

  // ---------- side: inbox + legend ----------
  function drawSide() {
    clear(side);
    const inbox = el('div', { class: 'card side-card' },
      el('div', { class: 'eyebrow', style: { marginBottom: '8px' } }, 'Inbox · not placed yet'));
    if (!idx.inbox.length) inbox.append(el('div', { class: 'muted', style: { fontSize: '13px', marginBottom: '8px' } },
      'Park gaps here: a class to revisit, a topic you know is missing.'));
    for (const it of idx.inbox) inbox.append(inboxRow(it));
    const park = el('input', { class: 'input', placeholder: 'Park an item… (Enter)', 'aria-label': 'Park an item in the inbox' });
    park.addEventListener('keydown', async (e) => {
      if (e.key !== 'Enter' || !park.value.trim()) return;
      await api.mapAdd({ text: park.value.trim(), kind: 'inbox' });
      park.value = '';
      reload();
    });
    inbox.append(park);
    side.append(inbox, el('div', { class: 'card side-card' },
      el('div', { class: 'eyebrow', style: { marginBottom: '8px' } }, 'Status · from your reviews'),
      legendEl(),
      el('div', { class: 'muted', style: { fontSize: '12.5px', marginTop: '8px' } },
        'Computed from the topics linked to each item. A flag (!) marks “lacking understanding” by hand.')));
  }

  function inboxRow(it) {
    const row = el('div', { class: 'inbox-row' });
    const place = el('button', { class: 'btn-ghost link-btn', onClick: () => {
      clear(row);
      const opts = [];
      for (const n of idx.byId.values()) if (n.kind === 'item') opts.push({ id: n.id, label: idx.pathOf(n.id).join(' › ') });
      const dl = el('datalist', { id: 'map-paths-' + it.id }, ...opts.map(o => el('option', { value: o.label })));
      const inp = el('input', { class: 'input', placeholder: 'Place under…', list: 'map-paths-' + it.id });
      const go = async () => {
        const hit = opts.find(o => o.label === inp.value);
        if (!hit) { toast('Pick an item from the list'); return; }
        await api.mapMove(it.id, hit.id);
        open.add(hit.id); saveSet(OPEN_KEY, open);
        toast(`Placed under ${hit.label.split(' › ').pop()}`);
        reload();
      };
      inp.addEventListener('change', go);
      inp.addEventListener('keydown', (e) => { if (e.key === 'Enter') go(); if (e.key === 'Escape') drawSide(); });
      row.append(el('div', { style: { fontSize: '13px', marginBottom: '4px' } }, it.text), inp, dl);
      inp.focus();
    } }, 'Place');
    row.append(el('span', { class: 'inbox-text' }, it.text), place,
      el('button', { class: 'mtopic-x', 'aria-label': 'Remove from inbox', onClick: async () => { await api.mapDelete(it.id); reload(); } }, '×'));
    return row;
  }

  // ---------- panels: paste outline / place topics ----------
  function showImport() {
    clear(panelSlot);
    const target = selected ? idx.byId.get(selected) : null;
    const ta = el('textarea', { class: 'input', rows: '9', placeholder:
      'Mechanics of Materials\n  Defining and calculating stresses\n    Mohr\'s circle\n    Buckling failure\n  ! TTT/CCT diagrams\n## MFE\nBattery\n  Cell capacity testing' });
    const starterRow = el('div', { class: 'row wrap', style: { gap: '6px', marginBottom: '8px' } });
    const where = el('select', { class: 'input', style: { maxWidth: '320px' } },
      el('option', { value: '' }, 'At the top level'),
      target ? el('option', { value: String(target.id), selected: '' }, `Under “${target.text}”`) : null);
    const go = el('button', { class: 'btn btn-primary', onClick: async () => {
      if (!ta.value.trim()) { toast('Paste an outline first'); return; }
      go.disabled = true;
      const r = await api.mapImport(ta.value, where.value ? Number(where.value) : null);
      if (where.value) { open.add(Number(where.value)); saveSet(OPEN_KEY, open); }
      toast(`Added ${r.added} item${r.added !== 1 ? 's' : ''}`);
      clear(panelSlot); reload();
    } }, 'Add to map');
    panelSlot.append(el('div', { class: 'card', style: { marginBottom: '14px', borderColor: 'var(--accent)' } },
      el('div', { class: 'eyebrow', style: { marginBottom: '6px' } }, 'Paste an outline'),
      el('div', { class: 'muted', style: { fontSize: '13px', marginBottom: '10px' } },
        'Indent with spaces or tabs; bullets (-, •, ○, ▪, □) are fine. Start or end a line with ! to flag it. A line “## MFE” labels what follows by source.'),
      starterRow,
      ta,
      el('div', { class: 'row spread', style: { marginTop: '10px' } }, where,
        el('div', { class: 'row', style: { gap: '8px' } },
          el('button', { class: 'btn btn-ghost', onClick: () => clear(panelSlot) }, 'Cancel'), go))));
    ta.focus();
    api.mapStarters().then(r => {
      for (const st of r.starters || []) starterRow.append(el('button', { class: 'chip', onClick: () => { ta.value = st.text; } },
        `Use “${st.name}” · ${st.items} items`));
    }).catch(() => {});
  }

  async function showPlace() {
    clear(panelSlot);
    const card = el('div', { class: 'card', style: { marginBottom: '14px', borderColor: 'var(--accent)' } },
      el('div', { class: 'muted' }, 'Matching topics to map items…'));
    panelSlot.append(card);
    let res;
    try { res = await api.mapSuggest(); } catch { clear(card); card.append('Matching failed.'); return; }
    clear(card);
    card.append(el('div', { class: 'eyebrow', style: { marginBottom: '6px' } },
      `${res.unplaced} topic${res.unplaced !== 1 ? 's' : ''} not in the map`));
    if (!res.suggestions.length) {
      card.append(el('div', { class: 'muted', style: { fontSize: '13.5px' } },
        res.unplaced ? 'No confident matches. Link them from an item (select it → Link a topic) or from the topic’s page.'
                     : 'Every topic has a place.'),
        el('div', { class: 'row', style: { justifyContent: 'flex-end', marginTop: '8px' } },
          el('button', { class: 'btn btn-ghost', onClick: () => clear(panelSlot) }, 'Close')));
      return;
    }
    card.append(el('div', { class: 'muted', style: { fontSize: '13px', marginBottom: '8px' } },
      `Suggested by ${res.embeddings ? 'meaning and wording' : 'wording (start an embed model for meaning matches)'}. Untick any that are wrong.`));
    const rows = res.suggestions.map(s => {
      const chk = el('input', { type: 'checkbox', checked: '', style: { width: '16px', height: '16px', accentColor: 'var(--accent)' } });
      return { s, chk, node: el('label', { class: 'place-row' }, chk,
        el('span', { class: 'soft' }, s.title), el('span', { class: 'muted' }, '→'),
        el('span', { class: 'place-path' }, s.path.join(' › '))) };
    });
    const apply = el('button', { class: 'btn btn-primary', onClick: async () => {
      const links = rows.filter(r => r.chk.checked).map(r => ({ node_id: r.s.node_id, learning_id: r.s.learning_id }));
      if (!links.length) { toast('Nothing selected'); return; }
      apply.disabled = true;
      const r = await api.mapPlace(links);
      toast(`Placed ${r.linked} topic${r.linked !== 1 ? 's' : ''}`);
      clear(panelSlot); refreshBadge(); reload();
    } }, `Place ${rows.length}`);
    card.append(el('div', { class: 'place-list' }, ...rows.map(r => r.node)),
      el('div', { class: 'row', style: { justifyContent: 'flex-end', gap: '8px', marginTop: '10px' } },
        el('button', { class: 'btn btn-ghost', onClick: () => clear(panelSlot) }, 'Cancel'), apply));
  }

  function emptyState() {
    return el('div', { class: 'card empty', style: { padding: '40px 24px' } },
      el('h2', {}, 'Map the areas you want to keep'),
      el('p', { class: 'muted', style: { maxWidth: '520px', margin: '0 auto' } },
        'An outline of your subjects, linked to your topics. Each item’s status comes from your reviews, so you can see what’s fading and what was never covered.'),
      el('div', { class: 'row', style: { justifyContent: 'center', gap: '8px', marginTop: '16px' } },
        el('button', { class: 'btn btn-primary', onClick: showImport }, 'Paste an outline'),
        el('button', { class: 'btn', onClick: () => addItem(null, null, true) }, 'Start from scratch')));
  }

  await reload();
  return root;
}
