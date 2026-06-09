import { el, heatmapEl } from '../store.js';
import { api } from '../api.js';
import { navigate } from '../app.js';
import { renderMathIn } from '../math.js';

function greeting() {
  const h = new Date().getHours();
  return h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening';
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
  view.append(hero);

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
