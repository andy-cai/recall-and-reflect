// App shell + hash router.
import { state, el, clear, applyTheme } from './store.js';
import { api } from './api.js';

import * as today from './views/today.js';
import * as reflect from './views/reflect.js';
import * as recall from './views/recall.js';
import * as library from './views/library.js';
import * as stats from './views/stats.js';
import * as settings from './views/settings.js';

const ICONS = {
  today: '<path d="M3 10.5 12 4l9 6.5"/><path d="M5 9.5V20h14V9.5"/><path d="M9.5 20v-6h5v6"/>',
  reflect: '<path d="M4 5h16v10H8l-4 4V5Z"/><path d="M8 9h8M8 12h5"/>',
  recall: '<rect x="3" y="6" width="13" height="13" rx="2"/><path d="M8 3h11a2 2 0 0 1 2 2v11"/><path d="M7 12.5l2.5 2.5 5-5"/>',
  library: '<path d="M4 5h6v14H4zM14 5h6v14h-6z"/><path d="M7 9h0M17 9h0"/>',
  stats: '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',
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

  if (currentCleanup) { try { currentCleanup(); } catch {} currentCleanup = null; }
  clear(mainEl);
  mainEl.append(el('div', { class: 'view center', style: { paddingTop: '80px' } }, el('span', { class: 'spin' })));

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
      el('div', { class: 'icon' }, '⚠️'),
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

function buildShell() {
  const app = document.getElementById('app');
  clear(app);

  const nav = el('nav', { class: 'sidebar' });
  nav.append(el('div', { class: 'brand' },
    el('span', { class: 'mark', html:
      `<svg viewBox="0 0 32 32" width="28" height="28"><rect width="32" height="32" rx="8" fill="var(--accent)"/><path d="M9 22V10h6a4 4 0 0 1 0 8h-3l4 4M21 10v12" stroke="white" stroke-width="2.4" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>` }),
    el('div', {}, el('b', {}, 'Recall'), ' ', el('span', {}, '& Reflect'))));

  for (const key of NAV) {
    const r = ROUTES[key];
    const btn = el('button', { class: 'nav-item', onClick: () => navigate('#/' + key) }, svg(ICONS[r.icon]), r.label);
    if (key === 'recall') {
      dueBadgeEl = el('span', { class: 'badge', style: { display: 'none' } }, '0');
      btn.append(dueBadgeEl);
    }
    navButtons[key] = btn;
    nav.append(btn);
  }

  nav.append(el('div', { class: 'nav-spacer' }));
  navButtons.settings = el('button', { class: 'nav-item', onClick: () => navigate('#/settings') },
    svg(ICONS.settings), 'Settings');
  nav.append(navButtons.settings);
  llmDotEl = el('span', { class: 'dot' });
  nav.append(el('div', { class: 'nav-foot' }, llmDotEl, el('span', {}, 'checking…')));

  mainEl = el('main', { class: 'main', id: 'main-view' });
  app.append(nav, mainEl);
}

async function boot() {
  applyTheme(localStorage.getItem('rr-theme') || 'light');
  buildShell();
  try {
    const s = await api.getSettings();
    state.settings = s;
    state.llm = s.llm;
    localStorage.setItem('rr-theme', s.theme || 'light');
    applyTheme(s.theme || 'light');
  } catch {}
  window.addEventListener('hashchange', route);
  route();
}

boot();
