// Knowledge map — shared pieces: tree index, status marks, and the coverage atlas.
// Used by Library › Map (outline + atlas) and the Today atlas card.
import { el } from './store.js';

export const STATE_ORDER = ['shaky', 'fading', 'new', 'none', 'solid'];   // weakest first
export const STATE_LABEL = {
  solid: 'Solid', fading: 'Fading', shaky: 'Shaky', new: 'New', none: 'No cards yet',
};
export const STATE_HELP = {
  solid: 'recall chance ≥ 85%',
  fading: 'recall chance 60–85%',
  shaky: 'below 60%, an idea missed twice running, or flagged by you',
  new: 'cards written, not reviewed yet',
  none: 'nothing behind it yet: cover it',
};

// Flat node list -> lookup helpers. Inbox items live outside the tree.
export function indexTree(tree) {
  const byId = new Map(), kids = new Map(), inbox = [];
  for (const n of tree.nodes) byId.set(n.id, n);
  for (const n of tree.nodes) {
    if (n.kind === 'inbox') { inbox.push(n); continue; }
    const k = n.parent_id ?? 0;
    if (!kids.has(k)) kids.set(k, []);
    kids.get(k).push(n);
  }
  for (const list of kids.values()) list.sort((a, b) => a.position - b.position || a.id - b.id);
  inbox.sort((a, b) => a.position - b.position || a.id - b.id);
  const childrenOf = (id) => kids.get(id ?? 0) || [];
  function pathOf(id) {
    const out = []; let cur = byId.get(id), guard = 0;
    while (cur && guard++ < 64) { out.unshift(cur.text); cur = byId.get(cur.parent_id); }
    return out;
  }
  function descendants(id) {
    const out = [], stack = [...childrenOf(id)].reverse();
    while (stack.length) { const n = stack.pop(); out.push(n); stack.push(...[...childrenOf(n.id)].reverse()); }
    return out;
  }
  return { byId, roots: childrenOf(null), childrenOf, pathOf, descendants, inbox,
           titles: tree.titles || {}, sources: tree.sources || [] };
}

export const pct = (r) => (r == null ? '' : Math.round(r * 100) + '%');

export function daysSince(iso) {
  if (!iso) return null;
  return Math.floor((Date.now() - new Date(iso).getTime()) / 86400000);
}

export function untouchedLabel(iso, short = false) {
  const d = daysSince(iso);
  if (d == null) return short ? 'never' : 'never reviewed';
  if (d < 1) return short ? 'today' : 'touched today';
  if (d < 14) return short ? `${d}d ago` : `touched ${d}d ago`;
  if (d < 60) return short ? `${Math.round(d / 7)} wk ago` : `untouched ${Math.round(d / 7)} wk`;
  return short ? `${Math.round(d / 30)} mo ago` : `untouched ${Math.round(d / 30)} mo`;
}

export function dotEl(state, flag = false) {
  return el('span', { class: 'kdot k-' + (state || 'head') + (flag ? ' flagged' : ''),
    title: state ? `${STATE_LABEL[state]}: ${STATE_HELP[state]}` : '', 'aria-hidden': 'true' });
}

// Stacked status bar for a branch (segment widths = item counts).
export function barEl(counts, cls = '') {
  const bar = el('span', { class: 'kbar ' + cls, 'aria-hidden': 'true' });
  for (const s of ['solid', 'fading', 'shaky', 'new', 'none']) {
    if (counts && counts[s]) bar.append(el('i', { class: 'k-' + s, style: { flexGrow: String(counts[s]) } }));
  }
  return bar;
}

export function barText(agg) {
  if (!agg || !agg.total) return 'empty';
  const c = agg.counts, parts = [];
  if (c.solid) parts.push(`${c.solid} solid`);
  if (c.fading) parts.push(`${c.fading} fading`);
  if (c.shaky) parts.push(`${c.shaky} shaky`);
  if (c.new) parts.push(`${c.new} new`);
  if (c.none) parts.push(`${c.none} uncovered`);
  return parts.join(' · ');
}

// The branch's dominant condition, for tinting atlas blocks.
export function dominant(agg) {
  if (!agg || !agg.total) return 'none';
  const c = agg.counts;
  if (c.none / agg.total > 0.5) return 'none';
  let best = 'none', n = -1;
  for (const s of ['shaky', 'fading', 'new', 'solid']) if (c[s] > n) { best = s; n = c[s]; }
  return n > 0 ? best : 'none';
}

// Countable items under a branch, weakest first (shaky → fading → new → uncovered → solid).
export function weakest(idx, id, n = 6) {
  const items = idx.descendants(id).filter(x => x.state);
  const rank = (x) => STATE_ORDER.indexOf(x.state);
  items.sort((a, b) => (b.flag - a.flag) || rank(a) - rank(b) || ((a.r ?? 2) - (b.r ?? 2)));
  return items.slice(0, n);
}

// ---------- squarified treemap (Bruls, Huizing & van Wijk 2000) ----------
function squarify(items, W, H) {
  const total = items.reduce((a, b) => a + b.v, 0) || 1;
  const scale = (W * H) / total;
  const rest = items.map(it => ({ ...it, a: it.v * scale }));
  const out = [];
  let x = 0, y = 0, w = W, h = H, row = [];
  const worst = (r, side) => {
    const s = r.reduce((a, b) => a + b.a, 0);
    let m = 0;
    for (const it of r) m = Math.max(m, (side * side * it.a) / (s * s), (s * s) / (side * side * it.a));
    return m;
  };
  const place = (r) => {
    const s = r.reduce((a, b) => a + b.a, 0);
    if (w >= h) {
      const cw = s / h; let cy = y;
      for (const it of r) { const rh = it.a / cw; out.push({ ...it, x, y: cy, w: cw, h: rh }); cy += rh; }
      x += cw; w -= cw;
    } else {
      const rh = s / w; let cx = x;
      for (const it of r) { const rw = it.a / rh; out.push({ ...it, x: cx, y, w: rw, h: rh }); cx += rw; }
      y += rh; h -= rh;
    }
  };
  while (rest.length) {
    const side = Math.min(w, h);
    if (!row.length || worst([...row, rest[0]], side) <= worst(row, side)) row.push(rest.shift());
    else { place(row); row = []; }
  }
  if (row.length) place(row);
  return out;
}

// atlasEl(idx, { parentId, height, selected, onSelect })
// Blocks are the children of parentId (roots by default), sized by item count.
// The layout follows the box's real aspect ratio and re-flows on resize.
export function atlasEl(idx, { parentId = null, height = 280, selected = null, onSelect } = {}) {
  const wrap = el('div', { class: 'atlas', style: { height: height + 'px' }, role: 'list' });
  const items = idx.childrenOf(parentId)
    .map(n => ({ n, v: Math.max(1, (n.agg && n.agg.total) || 1) }))
    .sort((a, b) => b.v - a.v);
  if (!items.length) return wrap;
  const blocks = items.map(({ n }) => {
    const agg = n.agg || { counts: {}, total: 0 };
    const label = `${n.text}: ${agg.total} item${agg.total !== 1 ? 's' : ''}, ${barText(agg)}, ${untouchedLabel(agg.last)}`;
    return el('button', {
      class: `atlas-block k-tint-${dominant(agg)}` + (selected === n.id ? ' sel' : ''),
      role: 'listitem', title: label, 'aria-label': label,
      onClick: () => onSelect && onSelect(n),
    },
      el('span', { class: 'atlas-name' }, n.text),
      el('span', { class: 'atlas-meta' }, `${agg.total} · ${untouchedLabel(agg.last, true)}`),
      barEl(agg.counts, 'atlas-bar'));
  });
  wrap.append(...blocks);
  let lastW = 0;
  const layout = () => {
    const w = wrap.clientWidth || 800;
    if (w === lastW) return;
    lastW = w;
    const W = w, H = height;
    const rects = squarify(items.map((it, i) => ({ ...it, i })), W, H);
    for (const r of rects) {
      const b = blocks[r.i];
      Object.assign(b.style, { left: (r.x / W * 100) + '%', top: (r.y / H * 100) + '%',
        width: (r.w / W * 100) + '%', height: (r.h / H * 100) + '%' });
      b.classList.toggle('tiny', r.w < 64 || r.h < 40);
      b.classList.toggle('small', !(r.w < 64 || r.h < 40) && (r.w < 120 || r.h < 76));
    }
  };
  layout();
  if (typeof ResizeObserver !== 'undefined') {
    const ro = new ResizeObserver(() => { if (!wrap.isConnected) { ro.disconnect(); return; } layout(); });
    ro.observe(wrap);
  }
  return wrap;
}

// The detail for one selected branch: where it stands + its weakest items.
export function branchPanel(idx, node, { onReview, onOpen, onCover } = {}) {
  const agg = node.agg || { counts: {}, total: 0, due: 0 };
  const weak = weakest(idx, node.id, 6);
  const panel = el('div', { class: 'branch-panel' },
    el('div', { class: 'row spread', style: { gap: '10px', alignItems: 'baseline' } },
      el('div', { style: { minWidth: '0' } },
        el('div', { class: 'branch-title' }, node.text),
        el('div', { class: 'muted', style: { fontSize: '12.5px' } },
          `${barText(agg)} · ${untouchedLabel(agg.last)}`)),
      el('div', { class: 'row', style: { gap: '8px', flex: 'none' } },
        onOpen ? el('button', { class: 'btn', style: { padding: '6px 12px' }, onClick: () => onOpen(node) }, 'Open in map') : null,
        onReview && agg.due > 0 ? el('button', { class: 'btn btn-primary', style: { padding: '6px 12px' },
          onClick: () => onReview(node) }, `Review branch · ${agg.due}`) : null)));
  if (weak.length) {
    const list = el('div', { class: 'weak-list' });
    for (const w of weak) {
      const path = idx.pathOf(w.id);
      const crumb = path.slice(path.indexOf(node.text) + 1, -1).join(' › ');
      list.append(el('div', { class: 'weak-row' },
        dotEl(w.state, w.flag),
        el('span', { class: 'weak-text' }, w.text, crumb ? el('span', { class: 'muted' }, '  ' + crumb) : null),
        w.state === 'none' && onCover
          ? el('button', { class: 'btn-ghost link-btn', onClick: () => onCover(w) }, 'Cover')
          : el('span', { class: 'muted', style: { fontSize: '12px' } }, w.r != null ? pct(w.r) : STATE_LABEL[w.state].toLowerCase())));
    }
    panel.append(list);
  }
  return panel;
}

export function legendEl() {
  return el('div', { class: 'klegend' },
    ...['solid', 'fading', 'shaky', 'new', 'none'].map(s =>
      el('span', { title: STATE_HELP[s] }, dotEl(s), STATE_LABEL[s])));
}
