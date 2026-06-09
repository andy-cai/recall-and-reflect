import { el, clear, toast, heatmapEl } from '../store.js';
import { api } from '../api.js';
import { navigate, refreshBadge } from '../app.js';
import { renderMathIn } from '../math.js';

function greeting() {
  const h = new Date().getHours();
  return h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening';
}

// Focus: prioritize topics — focused ones jump the queue and claim the
// new-card budget first. Set it by telling the app what matters in plain words.
function buildFocus(t) {
  const wrap = el('div', { class: 'card', style: { marginTop: '16px' } });

  function showActive() {
    clear(wrap);
    wrap.append(el('div', { class: 'row spread' },
      el('div', {},
        el('div', { style: { fontWeight: '580' } }, `★ Focusing ${t.focus.topics} topic${t.focus.topics !== 1 ? 's' : ''}`),
        el('div', { class: 'muted', style: { fontSize: '13px' } },
          t.focus.due > 0 ? `${t.focus.due} due — they go first in every session.` : 'Nothing due in focus right now — focused topics still go first.')),
      el('div', { class: 'row', style: { gap: '8px' } },
        t.focus.due > 0 ? el('button', { class: 'btn btn-primary', onClick: () => navigate('#/recall?focus=1') }, 'Review focus →') : null,
        el('button', { class: 'btn btn-ghost', onClick: async () => { await api.focusClear(); t.focus = { topics: 0, due: 0 }; showInput(); toast('Focus cleared'); } }, 'Clear'))));
  }

  function showInput() {
    clear(wrap);
    const input = el('input', { class: 'input', placeholder: 'e.g. “vibrations final next week” or “battery + seals”…' });
    const setBtn = el('button', { class: 'btn', onClick: submit }, 'Set focus');
    input.addEventListener('keydown', (e) => { if (e.key === 'Enter') submit(); });
    wrap.append(
      el('div', { style: { fontWeight: '580', marginBottom: '4px' } }, 'Focus'),
      el('div', { class: 'muted', style: { fontSize: '13px', marginBottom: '10px' } },
        'Tell it what matters right now — matching topics jump to the front of every session.'),
      el('div', { class: 'row', style: { gap: '8px' } }, input, setBtn));

    async function submit() {
      const text = input.value.trim();
      if (!text) return;
      setBtn.disabled = true; setBtn.textContent = 'Matching…';
      try {
        const m = await api.focusInterpret(text);
        showConfirm(m);
      } catch { toast('Could not match — try naming a subject or topic.'); }
      setBtn.disabled = false; setBtn.textContent = 'Set focus';
    }
  }

  function showConfirm(m) {
    const subjects = m.subjects || [], learnings = m.learnings || [];
    if (!subjects.length && !learnings.length) { toast('No matching topics found.'); return; }
    clear(wrap);
    const checks = [];
    const rows = el('div', { class: 'stack', style: { gap: '6px', margin: '10px 0' } });
    const mkRow = (label, payload) => {
      const chk = el('input', { type: 'checkbox', checked: '', style: { width: '16px', height: '16px', accentColor: 'var(--accent)' } });
      checks.push({ chk, payload });
      rows.append(el('label', { class: 'row', style: { gap: '9px', cursor: 'pointer', fontSize: '13.5px' } }, chk, label));
    };
    for (const s of subjects) mkRow(`${s} (whole subject)`, { subject: s });
    for (const l of learnings) mkRow(l.title, { id: l.id });
    const applyBtn = el('button', { class: 'btn btn-primary', onClick: async () => {
      const sel = checks.filter(c => c.chk.checked).map(c => c.payload);
      const body = { subjects: sel.filter(p => p.subject).map(p => p.subject),
                     learning_ids: sel.filter(p => p.id).map(p => p.id), priority: 1 };
      if (!body.subjects.length && !body.learning_ids.length) { toast('Nothing selected'); return; }
      const r = await api.focusApply(body);
      t.focus = r.focus; refreshBadge(); showActive();
      toast(`Focusing ${r.focus.topics} topic${r.focus.topics !== 1 ? 's' : ''}`);
    } }, 'Focus these');
    wrap.append(
      el('div', { style: { fontWeight: '580' } }, 'Focus on:'),
      rows,
      el('div', { class: 'row', style: { gap: '8px', justifyContent: 'flex-end' } },
        el('button', { class: 'btn btn-ghost', onClick: showInput }, 'Cancel'), applyBtn));
  }

  if (t.focus && t.focus.topics > 0) showActive(); else showInput();
  return wrap;
}

export async function render() {
  const t = await api.today();
  const view = el('div', { class: 'view' });

  const dateStr = new Date().toLocaleDateString(undefined, { weekday: 'long', month: 'long', day: 'numeric' });
  view.append(el('div', { class: 'page-head' },
    el('h1', {}, greeting()),
    el('p', { class: 'sub' }, dateStr)));

  // Hero — name what's at risk; the pull is "Mohr's circle is at 38%", not "18 due".
  let hero;
  const risk = t.at_risk || [];
  if (t.due > 0 && risk.length) {
    const rescueN = Math.min(3, t.due);
    hero = el('div', { class: 'card' },
      el('div', { class: 'row spread', style: { marginBottom: '12px' } },
        el('div', { class: 'eyebrow' }, 'About to slip'),
        el('span', { class: 'muted', style: { fontSize: '12px' } }, 'recall chance right now')),
      ...risk.map(r => el('div', { class: 'risk-item' },
        el('div', { class: 'gauge' }, el('i', { class: r.retrievability >= 0.55 ? 'warm' : '', style: { width: Math.round(r.retrievability * 100) + '%' } })),
        el('span', {}, r.label),
        el('span', { class: 'pct' }, '~' + Math.round(r.retrievability * 100) + '%'))),
      el('div', { class: 'row spread', style: { marginTop: '14px' } },
        el('span', { class: 'muted', style: { fontSize: '12.5px' } },
          t.due > risk.length ? `+${t.due - risk.length} more due today` : 'that’s everything due'),
        el('div', { class: 'row', style: { gap: '8px' } },
          el('button', { class: 'btn', onClick: () => navigate('#/recall') }, `Review all ${t.due}`),
          el('button', { class: 'btn btn-primary', onClick: () => navigate(`#/recall?limit=${rescueN}`) },
            `Rescue these ${rescueN} first →`))));
  } else if (t.due > 0) {
    // due cards but nothing scored yet (all new) — keep the classic hero
    hero = el('div', { class: 'hero' },
      el('div', { class: 'big', style: { color: 'var(--accent)' } }, String(t.due)),
      el('div', { class: 'lead' },
        el('h2', {}, `review${t.due !== 1 ? 's' : ''} ready to recall`),
        el('p', { class: 'muted' }, 'A few minutes of effortful recall is the whole game.')),
      el('div', { class: 'stack', style: { gap: '8px' } },
        el('button', { class: 'btn btn-primary btn-lg', onClick: () => navigate('#/recall') }, 'Start recall →'),
        el('button', { class: 'btn', onClick: () => navigate('#/recall?limit=3') }, 'Just 3 · ~60s')));
  } else {
    hero = el('div', { class: 'hero' },
      el('div', { class: 'big', style: { color: 'var(--good)' } }, '✓'),
      el('div', { class: 'lead' },
        el('h2', {}, 'All caught up'),
        el('p', { class: 'muted' }, 'Nothing due right now. Learn something new and reflect on it.')),
      el('button', { class: 'btn btn-primary btn-lg', onClick: () => navigate('#/reflect') }, 'Reflect →'));
  }
  renderMathIn(hero);

  // Welcome back — a wall of overdue cards kills the habit; offer a ramp instead.
  if (t.gap_days >= 3 && t.due > t.daily_target * 2) {
    const daysInput = el('input', { class: 'input', type: 'number', min: '2', max: '14', value: '5', style: { maxWidth: '70px' } });
    const rampBtn = el('button', { class: 'btn btn-primary', onClick: async () => {
      rampBtn.disabled = true;
      const r = await api.ramp(Math.max(2, +daysInput.value || 5));
      toast(`Spread ${r.moved} reviews over ${r.days} days — today stays focused.`);
      refreshBadge(); navigate('#/today');
    } }, 'Ease me back in');
    view.append(el('div', { class: 'card', style: { marginBottom: '16px', borderColor: 'var(--accent)' } },
      el('div', { style: { fontWeight: '580' } }, `Welcome back — ${t.due} reviews piled up while you were away.`),
      el('div', { class: 'muted', style: { fontSize: '13px', margin: '4px 0 12px' } },
        `Missing days doesn’t break the habit — quitting after them does. Keep today’s ${t.daily_target} most at-risk and spread the rest:`),
      el('div', { class: 'row', style: { gap: '10px' } }, rampBtn, el('span', { class: 'muted', style: { fontSize: '13px' } }, 'over'), daysInput, el('span', { class: 'muted', style: { fontSize: '13px' } }, 'days'))));
  }

  view.append(hero);

  // Focus — prioritize topics by telling it what matters right now
  view.append(buildFocus(t));

  // Evening wind-down — a small pass before sleep consolidates today's material
  if (new Date().getHours() >= 20) {
    view.append(el('div', { class: 'card row spread', style: { marginTop: '16px' } },
      el('div', {},
        el('div', { style: { fontWeight: '580' } }, '🌙 Wind-down'),
        el('div', { class: 'muted', style: { fontSize: '13.5px' } }, 'A few things worth sleeping on — today’s misses and new captures.')),
      el('button', { class: 'btn', onClick: () => navigate('#/recall?mode=evening') }, 'Sleep on it →')));
  }

  // Tiles
  const pct = t.daily_target ? Math.min(100, Math.round(t.reviews_today / t.daily_target * 100)) : 0;
  view.append(el('div', { class: 'tiles', style: { marginTop: '16px' } },
    el('div', { class: 'tile' },
      el('div', { class: 'n' }, `${t.reviews_today}`, el('span', { class: 'muted', style: { fontSize: '16px' } }, ` / ${t.daily_target}`)),
      el('div', { class: 'l' }, 'reviewed today'),
      el('div', { class: 'progress', style: { marginTop: '10px' } }, el('i', { style: { width: pct + '%' } }))),
    el('div', { class: 'tile' },
      el('div', { class: 'n' }, `${t.streak}`, t.streak > 0 ? el('span', { style: { fontSize: '20px' } }, ' 🔥') : ''),
      el('div', { class: 'l' }, t.streak === 1 ? 'day streak' : 'day streak')),
    el('div', { class: 'tile' },
      el('div', { class: 'n accent' }, `${t.consistency}%`),
      el('div', { class: 'l' }, 'consistency · 14d')),
    el('div', { class: 'tile' },
      el('div', { class: 'n' }, `${t.totals.cards}`),
      el('div', { class: 'l' }, `cards across ${t.totals.learnings} notes`))));

  // Reflect prompt
  view.append(el('div', { class: 'card row spread', style: { marginTop: '16px' } },
    el('div', {},
      el('div', { style: { fontWeight: '580' } }, 'Learn something today?'),
      el('div', { class: 'muted', style: { fontSize: '13.5px' } }, 'Talk it through and it becomes recall cards.')),
    el('button', { class: 'btn', onClick: () => navigate('#/reflect') }, 'Reflect on it')));

  // Heatmap
  const heat = el('div', { class: 'card', style: { marginTop: '16px' } },
    el('div', { class: 'row spread', style: { marginBottom: '14px' } },
      el('div', { class: 'eyebrow' }, 'Recent activity'),
      el('div', { class: 'heat-legend' }, 'less',
        ...[0, 1, 2, 3, 4].map(l => el('span', { class: 'heat-cell' + (l ? ' l' + l : '') })), 'more')),
    heatmapEl(t.heatmap, 18));
  view.append(heat);

  return view;
}
