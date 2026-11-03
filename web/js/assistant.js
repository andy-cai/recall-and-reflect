// "Ask R&R": a command-bar helper over the user's own study data.
//
// Opens with Ctrl/Cmd+K from anywhere (or the sidebar "Ask" button), Esc
// closes. The local model can only READ; anything that changes data comes
// back as a proposal the user must Confirm, which hits a separate endpoint.
// The conversation lives in memory for this page session only.
import { el, clear, toast } from './store.js';
import { api } from './api.js';
import { renderMathIn } from './math.js';

const EXAMPLES = [
  'What should I review today?',
  'Focus on vibrations this week',
  'What am I weakest at?',
  'Make a card from this: …',
];
const HISTORY_TURNS = 6;   // messages sent back as context

export const IS_MAC = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent || '');
export const SHORTCUT = IS_MAC ? '⌘K' : 'Ctrl K';

let overlay, panel, input, sendBtn, log;
let history = [];          // [{role, content}] — session-only
let busy = false, wrote = false, lastFocus = null;
let hooks = { navigate: (h) => { location.hash = h; }, refresh: () => {} };

export function isOpen() { return !!overlay && !overlay.hidden; }

export function openAssistant() {
  if (!overlay) build();
  if (isOpen()) { input.focus(); return; }
  lastFocus = document.activeElement;
  overlay.hidden = false;
  document.body.classList.add('ask-open');
  requestAnimationFrame(() => overlay.classList.add('show'));
  input.focus();
  input.select();
}

export function closeAssistant({ restoreFocus = true } = {}) {
  if (!isOpen()) return;
  overlay.classList.remove('show');
  overlay.hidden = true;
  document.body.classList.remove('ask-open');
  if (wrote) {
    wrote = false;
    hooks.refresh();
    // re-render the current view so it shows the change (not mid-review)
    if (!/^#\/recall/.test(location.hash)) hooks.navigate(location.hash || '#/today');
  }
  if (restoreFocus && lastFocus && document.contains(lastFocus)) { try { lastFocus.focus(); } catch {} }
  lastFocus = null;
}

function toggle() { isOpen() ? closeAssistant() : openAssistant(); }

// ---------- building ----------
function build() {
  input = el('input', {
    class: 'ask-input', type: 'text', maxlength: '1000', autocomplete: 'off', spellcheck: 'false',
    placeholder: 'Ask, or tell me what to set up…', 'aria-label': 'Ask Recall & Reflect',
  });
  sendBtn = el('button', { class: 'btn btn-primary ask-send', onClick: () => send() }, 'Ask');
  log = el('div', { class: 'ask-log', 'aria-live': 'polite' });

  panel = el('div', { class: 'ask-panel', role: 'dialog', 'aria-modal': 'true', 'aria-label': 'Ask R&R' },
    el('div', { class: 'ask-bar' },
      el('span', { class: 'ask-glyph', 'aria-hidden': 'true', html: SPARK }),
      input, sendBtn),
    log,
    el('div', { class: 'ask-foot' },
      el('span', {}, el('span', { class: 'kbd' }, 'Enter'), ' send'),
      el('span', {}, el('span', { class: 'kbd' }, 'Esc'), ' close'),
      el('span', { class: 'ask-foot-note' }, 'Local model · reads your data, changes nothing without your OK')));

  overlay = el('div', { class: 'ask-overlay', hidden: true,
    onMousedown: (e) => { if (e.target === overlay) closeAssistant(); } }, panel);

  // Keys typed inside the panel stay inside the panel: stopping them at the
  // overlay keeps document-level handlers (Recall's Space/1-4/H/S/Z/Enter/Esc)
  // from ever seeing them.
  overlay.addEventListener('keydown', (e) => {
    e.stopPropagation();
    if (e.key === 'Escape') { e.preventDefault(); closeAssistant(); return; }
    if (e.key === 'Enter' && e.target === input && !e.isComposing) { e.preventDefault(); send(); return; }
    if (e.key === 'Tab') trapTab(e);
  });

  document.body.append(overlay);
  renderEmpty();
}

function renderEmpty() {
  clear(log);
  log.append(el('div', { class: 'ask-empty' },
    el('div', { class: 'eyebrow' }, 'Try'),
    el('div', { class: 'ask-chips' }, EXAMPLES.map(t => el('button', { class: 'chip', onClick: () => pickExample(t) }, t)))));
}

function pickExample(text) {
  if (text.endsWith('…')) {        // a template: let the user finish it
    input.value = text.slice(0, -1);
    input.focus();
    input.setSelectionRange(input.value.length, input.value.length);
    return;
  }
  input.value = text;
  send();
}

function trapTab(e) {
  const f = [...panel.querySelectorAll('button:not(:disabled), input:not(:disabled), [tabindex]:not([tabindex="-1"])')]
    .filter(n => n.offsetParent !== null);
  if (!f.length) return;
  const first = f[0], last = f[f.length - 1];
  if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
  else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
}

// ---------- conversation ----------
function setBusy(b) {
  busy = b;
  sendBtn.disabled = b;
  input.setAttribute('aria-busy', b ? 'true' : 'false');
}

function scrollDown() { log.scrollTop = log.scrollHeight; }

async function send() {
  const text = input.value.trim();
  if (!text || busy) return;
  if (!history.length) clear(log);
  input.value = '';

  log.append(el('div', { class: 'msg user ask-msg' }, text));
  const thinking = el('div', { class: 'msg ai ask-msg ask-thinking' },
    el('span', { class: 'typing' }, el('span'), el('span'), el('span')), ' Thinking…');
  log.append(thinking);
  scrollDown();
  setBusy(true);

  const sent = history.slice(-HISTORY_TURNS);
  history.push({ role: 'user', content: text });
  let res;
  try {
    res = await api.assistantAsk(text, sent);
  } catch (e) {
    res = { reply: `Couldn’t reach the helper: ${e.message || e}`, actions: [], available: false, _error: true };
  }
  thinking.remove();
  setBusy(false);

  const reply = String(res?.reply || '').trim() || '(no answer)';
  if (!res?._error) history.push({ role: 'assistant', content: reply });
  log.append(replyEl(reply, res?.available !== false ? (res?.actions || []) : [], res?.available === false));
  scrollDown();
  input.focus();
}

function replyEl(text, actions, offline) {
  const body = el('div', { class: 'ask-text' }, text);
  renderMathIn(body);
  const node = el('div', { class: 'msg ai ask-msg' + (offline ? ' ask-offline' : '') }, body);
  if (actions.length) {
    node.append(el('div', { class: 'ask-actions' }, actions.slice(0, 4).map(actionEl)));
  }
  return node;
}

function actionEl(a) {
  if (a.kind === 'navigate') {
    return el('button', {
      class: 'btn ask-act', onClick: () => {
        if (!a.href || !a.href.startsWith('#/')) return;
        closeAssistant({ restoreFocus: false });
        hooks.navigate(a.href);
      },
    }, a.label || 'Open', el('span', { 'aria-hidden': 'true' }, ' →'));
  }
  if (a.kind === 'write') {
    const wrap = el('div', { class: 'ask-write' });
    const btn = el('button', { class: 'btn btn-primary ask-act' }, `Confirm: ${a.label || a.tool}`);
    btn.addEventListener('click', async () => {
      if (btn.disabled) return;
      btn.disabled = true;
      btn.textContent = 'Working…';
      try {
        const r = await api.assistantConfirm(a.tool, a.args || {});
        wrote = true;
        btn.textContent = '✓ ' + (a.label || 'Done');
        btn.classList.add('done');
        const msg = r?.message || 'Done.';
        toast(msg);
        wrap.append(el('div', { class: 'ask-result good' }, msg,
          r?.href && r.href.startsWith('#/')
            ? el('button', { class: 'btn btn-ghost ask-go', onClick: () => { closeAssistant({ restoreFocus: false }); hooks.navigate(r.href); } }, 'Go →')
            : null));
      } catch (e) {
        btn.disabled = false;
        btn.textContent = `Confirm: ${a.label || a.tool}`;
        wrap.append(el('div', { class: 'ask-result bad' }, e.message || String(e)));
      }
      scrollDown();
    });
    wrap.prepend(btn);
    return wrap;
  }
  return null;
}

// ---------- mount ----------
// navigate/refresh come from app.js (avoids a circular import).
export function mountAssistant({ navigate, refresh } = {}) {
  if (navigate) hooks.navigate = navigate;
  if (refresh) hooks.refresh = refresh;
  // Capture phase on window: runs before any view's document listener, and
  // works even while typing in an input.
  window.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && !e.altKey && !e.shiftKey && (e.key === 'k' || e.key === 'K')) {
      e.preventDefault();
      e.stopPropagation();
      toggle();
      return;
    }
    // While open, a key aimed outside the panel (focus lost to <body>) must not
    // reach the page underneath: pull focus back into the panel instead.
    if (isOpen() && !overlay.contains(e.target)) {
      e.stopPropagation();
      if (e.key === 'Escape') { e.preventDefault(); closeAssistant(); return; }
      input.focus();
    }
  }, true);
}

const SPARK = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" width="18" height="18"><path d="M12 3.5l1.9 5.1 5.1 1.9-5.1 1.9L12 17.5l-1.9-5.1L5 10.5l5.1-1.9z"/><path d="M18.5 16.5l.7 1.8 1.8.7-1.8.7-.7 1.8-.7-1.8-1.8-.7 1.8-.7z"/></svg>';
export const ASK_ICON = '<path d="M12 3.5l1.9 5.1 5.1 1.9-5.1 1.9L12 17.5l-1.9-5.1L5 10.5l5.1-1.9z"/><path d="M18.5 16.5l.7 1.8 1.8.7-1.8.7-.7 1.8-.7-1.8-1.8-.7 1.8-.7z"/>';
