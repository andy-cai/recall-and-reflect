// App shell + hash router.
import { state, el, clear, applyTheme } from './store.js';
import { api } from './api.js';
import { setAmbient } from './ambient.js';
import { loaderEl } from './loader.js';

import * as today from './views/today.js';
import * as reflect from './views/reflect.js';
import * as recall from './views/recall.js';
import * as library from './views/library.js';
import * as stats from './views/stats.js';
import * as settings from './views/settings.js';

// One family, in the Settings icon's dialect: sparse geometric strokes.
//   today   — sunrise on the horizon (the day arriving)
//   reflect — a quill (the manuscript you write)
//   recall  — an arc returning to where it started (retrieval)
//   library — book spines, one leaning
//   stats   — a sparkline ending in a point
const ICONS = {
  today: '<path d="M17 17.5a5 5 0 0 0-10 0"/><path d="M4 17.5h16"/><path d="M12 8.5v-3M6.9 10.9l-2-2M17.1 10.9l2-2"/>',
  reflect: '<path d="M19.5 4.5c-7 .4-11.6 4-13.2 11l-.8 3.5 3.4-.9c6.9-1.8 10.3-6.4 10.6-13.6Z"/><path d="M6.5 17.5C9.8 12.4 13.2 9.1 17 7"/>',
  recall: '<path d="M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/>',
  library: '<path d="m16 6 4 14"/><path d="M12 6v14"/><path d="M8 8v12"/><path d="M4 4v16"/>',
  stats: '<path d="M4 17.5l4.6-5.2 3.6 3 6.6-7.9"/><circle cx="19.5" cy="6.5" r="1.5" fill="currentColor" stroke="none"/>',
  settings: '<circle cx="12" cy="12" r="3.2"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M5 5l2 2M17 17l2 2M19 5l-2 2M7 17l-2 2"/>',
};

const ROUTES = {
  today: { mod: today, label: 'Today', icon: 'today' },
  reflect: { mod: reflect, label: 'Reflect', icon: 'reflect' },
  recall: { mod: recall, label: 'Recall', icon: 'recall' },
  library: { mod: library, label: 'Library', icon: 'library' },
  stats: { mod: stats, label: 'Stats', icon: 'stats' },
  settings: { mod: settings, label: 'Settings', icon: 'settings' },
};
const NAV = ['today', 'reflect', 'recall', 'library', 'stats'];

// living background per view: full effect while writing, quieter elsewhere
const AMBIENT = { reflect: 'reflect', today: 'today', recall: 'recall', library: 'library', stats: 'library', settings: '' };

function svg(paths) {
  return el('span', { class: 'ico', html:
    `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" width="18" height="18">${paths}</svg>` });
}

let mainEl, currentCleanup = null;
let routeSeq = 0;
const navButtons = {};
let dueBadgeEl = null, llmDotEl = null;

export function navigate(hash) {
  if (location.hash === hash) route();
  else location.hash = hash;
}

function parseHash() {
  const raw = (location.hash || '#/today').replace(/^#\//, '');
  const [path, qs] = raw.split('?');
  const parts = path.split('/').filter(Boolean);
  const params = Object.fromEntries(new URLSearchParams(qs || ''));
  return { name: parts[0] || 'today', rest: parts.slice(1), params };
}

async function route() {
  const seq = ++routeSeq;
  const { name, rest, params } = parseHash();
  const entry = ROUTES[name] || ROUTES.today;

  for (const [k, b] of Object.entries(navButtons)) b.classList.toggle('active', k === name);
  setAmbient(AMBIENT[name] ?? '');

  if (currentCleanup) { try { currentCleanup(); } catch {} currentCleanup = null; }
  clear(mainEl);
  mainEl.append(el('div', { class: 'view center', style: { paddingTop: '64px' } }, loaderEl()));

  try {
    const node = await entry.mod.render({ rest, params });
    if (seq !== routeSeq) return;  // a newer navigation superseded this one
    clear(mainEl);
    mainEl.append(node);
    if (node._cleanup) currentCleanup = node._cleanup;
    mainEl.scrollTop = 0;
  } catch (e) {
    if (seq !== routeSeq) return;
    clear(mainEl);
    mainEl.append(el('div', { class: 'view empty' },
      el('div', { class: 'icon' }, '!'),
      el('h2', {}, 'Something went wrong'),
      el('p', { class: 'muted' }, String(e.message || e))));
  }
  if (seq === routeSeq) refreshBadge();
}

export async function refreshBadge() {
  try {
    const t = await api.today();
    if (dueBadgeEl) {
      dueBadgeEl.textContent = t.due;
      dueBadgeEl.style.display = t.due > 0 ? '' : 'none';
    }
    if (llmDotEl) {
      llmDotEl.className = 'dot ' + (t.llm.available ? 'on' : 'off');
      llmDotEl.parentElement.lastChild.textContent =
        t.llm.available ? `AI ready · ${t.llm.model}` : 'AI offline';
    }
    state.llm = t.llm;
  } catch {}
}

// Quiet fireflies inside a nav item on hover: a few accent motes drift up and
// fade. Skipped entirely under prefers-reduced-motion.
function sprinkle(btn) {
  if (matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  if (btn.querySelectorAll('.mote').length > 5) return;
  for (let i = 0; i < 3; i++) {
    const m = el('span', { class: 'mote' });
    m.style.left = (12 + Math.random() * 72) + '%';
    m.style.animationDelay = (i * 90 + Math.random() * 130) + 'ms';
    m.style.setProperty('--drift', (Math.random() * 16 - 8).toFixed(1) + 'px');
    m.addEventListener('animationend', () => m.remove());
    btn.append(m);
  }
}

function buildShell() {
  const app = document.getElementById('app');
  clear(app);

  const nav = el('nav', { class: 'sidebar' });
  const MARK_SVG = `<svg viewBox="0 0 64 64" width="28" height="28"><rect width="64" height="64" rx="14" fill="#131d16"/><circle cx="32" cy="32" r="18.5" fill="none" stroke="#d59a52" stroke-width="8" stroke-linecap="round" stroke-dasharray="91.7 116.3" transform="rotate(-7 32 32)"/><circle cx="45.1" cy="18.9" r="5.4" fill="#ece3d1"/></svg>`;
  nav.append(el('div', { class: 'brand' },
    el('span', { class: 'mark', html: MARK_SVG }),
    el('div', {}, el('b', {}, 'Recall'), ' ', el('span', {}, '& Reflect'))));

  for (const key of NAV) {
    const r = ROUTES[key];
    const btn = el('button', { class: 'nav-item', onClick: () => navigate('#/' + key),
      onMouseenter: (e) => sprinkle(e.currentTarget) }, svg(ICONS[r.icon]), r.label);
    if (key === 'recall') {
      dueBadgeEl = el('span', { class: 'badge', style: { display: 'none' } }, '0');
      btn.append(dueBadgeEl);
    }
    navButtons[key] = btn;
    nav.append(btn);
  }

  nav.append(el('div', { class: 'nav-spacer' }));
  navButtons.settings = el('button', { class: 'nav-item', onClick: () => navigate('#/settings'),
    onMouseenter: (e) => sprinkle(e.currentTarget) }, svg(ICONS.settings), 'Settings');
  nav.append(navButtons.settings);
  llmDotEl = el('span', { class: 'dot' });
  nav.append(el('div', { class: 'nav-foot' }, llmDotEl, el('span', {}, 'checking…')));

  mainEl = el('main', { class: 'main', id: 'main-view' });
  app.append(nav, mainEl);
}

async function boot() {
  applyTheme(localStorage.getItem('rr-theme') || 'dark');
  buildShell();
  try {
    const s = await api.getSettings();
    state.settings = s;
    state.llm = s.llm;
    localStorage.setItem('rr-theme', s.theme || 'dark');
    applyTheme(s.theme || 'dark');
  } catch {}
  window.addEventListener('hashchange', route);
  route();
}

boot();
