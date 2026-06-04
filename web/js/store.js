// Tiny shared state + DOM helpers. No framework.

export const state = {
  settings: null,
  llm: { available: false, model: null, models: [] },
};

// el('div', {class:'x', onClick: fn}, child, child...) -> HTMLElement
export function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === 'class') node.className = v;
    else if (k === 'html') node.innerHTML = v;
    else if (k === 'text') node.textContent = v;
    else if (k === 'style' && typeof v === 'object') Object.assign(node.style, v);
    else if (k.startsWith('on') && typeof v === 'function') node.addEventListener(k.slice(2).toLowerCase(), v);
    else node.setAttribute(k, v === true ? '' : v);
  }
  add(node, children);
  return node;
}

export function add(node, children) {
  for (const c of children.flat(3)) {
    if (c === null || c === undefined || c === false) continue;
    node.append(c.nodeType ? c : document.createTextNode(String(c)));
  }
}

export function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); }

export function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, c =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

let toastTimer;
export function toast(msg) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.hidden = false;
  requestAnimationFrame(() => t.classList.add('show'));
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    t.classList.remove('show');
    setTimeout(() => (t.hidden = true), 220);
  }, 2400);
}

export function applyTheme(theme) {
  const resolved = theme === 'system'
    ? (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')
    : (theme || 'light');
  document.documentElement.setAttribute('data-theme', resolved);
}

export function relDate(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  const days = Math.round((d - new Date()) / 86400000);
  if (days <= 0) return 'now';
  if (days === 1) return 'tomorrow';
  if (days < 30) return `in ${days}d`;
  if (days < 365) return `in ${Math.round(days / 30)}mo`;
  return `in ${(days / 365).toFixed(1)}y`;
}

export function localKey(d) {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

export function heatmapEl(byDay, weeks = 18) {
  const days = weeks * 7;
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const start = new Date(today); start.setDate(start.getDate() - (days - 1));
  let max = 1;
  for (const v of Object.values(byDay || {})) if (v > max) max = v;
  const wrap = el('div', { class: 'heatmap' });
  const lead = start.getDay();
  for (let i = 0; i < lead; i++) wrap.append(el('div', { class: 'heat-cell', style: { visibility: 'hidden' } }));
  for (let i = 0; i < days; i++) {
    const d = new Date(start); d.setDate(start.getDate() + i);
    const v = (byDay && byDay[localKey(d)]) || 0;
    const lvl = v === 0 ? 0 : v >= max * 0.75 ? 4 : v >= max * 0.5 ? 3 : v >= max * 0.25 ? 2 : 1;
    wrap.append(el('div', {
      class: 'heat-cell' + (lvl ? ' l' + lvl : ''),
      title: `${localKey(d)}: ${v} review${v !== 1 ? 's' : ''}`,
    }));
  }
  return wrap;
}

export function agoDate(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  const days = Math.floor((new Date() - d) / 86400000);
  if (days <= 0) return 'today';
  if (days === 1) return 'yesterday';
  if (days < 30) return `${days}d ago`;
  if (days < 365) return `${Math.round(days / 30)}mo ago`;
  return `${Math.round(days / 365)}y ago`;
}
