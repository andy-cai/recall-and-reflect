import { el, heatmapEl, localKey } from '../store.js';
import { api } from '../api.js';

function lastNDays(byDay, n) {
  const out = [];
  const today = new Date(); today.setHours(0, 0, 0, 0);
  for (let i = n - 1; i >= 0; i--) {
    const d = new Date(today); d.setDate(today.getDate() - i);
    out.push({ key: localKey(d), v: (byDay && byDay[localKey(d)]) || 0 });
  }
  return out;
}

function barChart(items, accessor, labeler) {
  const vals = items.map(accessor);
  const max = Math.max(1, ...vals);
  const bars = el('div', { class: 'bars' });
  items.forEach((it) => {
    const v = accessor(it);
    bars.append(el('div', { class: 'bar-col' },
      el('div', { class: 'bar' + (v === 0 ? ' soft' : ''), style: { height: (v / max * 100) + '%' }, title: labeler(it) })));
  });
  return bars;
}

export async function render() {
  const s = await api.stats();
  const view = el('div', { class: 'view' });
  view.append(el('div', { class: 'page-head' }, el('h1', {}, 'Stats'),
    el('p', { class: 'sub' }, 'How your memory is holding up.')));

  view.append(el('div', { class: 'tiles' },
    el('div', { class: 'tile' }, el('div', { class: 'n' }, String(s.totals.reviews)), el('div', { class: 'l' }, 'total reviews')),
    el('div', { class: 'tile' }, el('div', { class: 'n good' }, s.retention_30 == null ? '—' : s.retention_30 + '%'), el('div', { class: 'l' }, 'retention · 30d')),
    el('div', { class: 'tile' }, el('div', { class: 'n' }, String(s.streak), s.streak ? ' 🔥' : ''), el('div', { class: 'l' }, 'day streak')),
    el('div', { class: 'tile' }, el('div', { class: 'n accent' }, s.consistency + '%'), el('div', { class: 'l' }, 'consistency · 14d')),
    el('div', { class: 'tile' }, el('div', { class: 'n' }, String(s.totals.cards)), el('div', { class: 'l' }, 'cards')),
    el('div', { class: 'tile' }, el('div', { class: 'n' }, String(s.totals.learnings)), el('div', { class: 'l' }, 'learnings'))));

  // reviews per day (30d)
  const days = lastNDays(s.reviews_by_day, 30);
  view.append(el('div', { class: 'card', style: { marginTop: '16px' } },
    el('div', { class: 'eyebrow', style: { marginBottom: '14px' } }, 'Reviews · last 30 days'),
    barChart(days, d => d.v, d => `${d.key}: ${d.v}`)));

  // maturity
  const m = s.maturity;
  const tot = (m.new + m.learning + m.young + m.mature) || 1;
  const segs = [
    ['new', m.new, 'var(--accent-weak)', 'New'],
    ['learning', m.learning, 'var(--hard)', 'Learning'],
    ['young', m.young, 'var(--easy)', 'Young'],
    ['mature', m.mature, 'var(--good)', 'Mature'],
  ];
  view.append(el('div', { class: 'card', style: { marginTop: '16px' } },
    el('div', { class: 'eyebrow', style: { marginBottom: '14px' } }, 'Card maturity'),
    el('div', { class: 'segbar' }, ...segs.map(([k, n, c]) => el('span', { style: { width: (n / tot * 100) + '%', background: c }, title: `${k}: ${n}` }))),
    el('div', { class: 'row wrap', style: { gap: '14px', marginTop: '12px' } },
      ...segs.map(([k, n, c, label]) => el('div', { class: 'row', style: { gap: '6px' } },
        el('span', { class: 'dot', style: { background: c } }), el('span', { class: 'muted', style: { fontSize: '12.5px' } }, `${label} · ${n}`))))));

  // forecast
  const fmap = {};
  for (const f of s.forecast) fmap[f.date] = f.count;
  const next14 = [];
  const today = new Date(); today.setHours(0, 0, 0, 0);
  for (let i = 0; i < 14; i++) { const d = new Date(today); d.setDate(today.getDate() + i); next14.push({ key: localKey(d), v: fmap[localKey(d)] || 0 }); }
  view.append(el('div', { class: 'card', style: { marginTop: '16px' } },
    el('div', { class: 'eyebrow', style: { marginBottom: '14px' } }, 'Due in the next 14 days'),
    barChart(next14, d => d.v, d => `${d.key}: ${d.v} due`)));

  // calibration — does "Certain" actually mean certain?
  const cal = s.calibration;
  if (cal && Object.values(cal.levels).some(l => l.n >= 5)) {
    const names = { 3: 'Certain', 2: 'Pretty sure', 1: 'Guessing' };
    const colors = { 3: 'var(--good)', 2: 'var(--hard)', 1: 'var(--again)' };
    const panel = el('div', { class: 'card', style: { marginTop: '16px' } },
      el('div', { class: 'eyebrow', style: { marginBottom: '14px' } }, 'Confidence calibration · 90d'));
    for (const c of [3, 2, 1]) {
      const lv = cal.levels[String(c)];
      if (!lv || !lv.n) continue;
      const pct = lv.accuracy == null ? 0 : Math.round(lv.accuracy * 100);
      panel.append(
        el('div', { class: 'row spread', style: { marginBottom: '4px' } },
          el('span', { class: 'soft', style: { fontSize: '13.5px' } }, `When you said `, el('b', {}, names[c]), ` (n=${lv.n})`),
          el('span', { style: { fontSize: '13px', color: colors[c] } }, `right ${pct}%`)),
        el('div', { class: 'cal-bar', style: { marginBottom: '12px' } },
          el('i', { style: { width: pct + '%', background: colors[c] } })));
    }
    const hot = cal.overconfident_subject;
    if (hot && hot.accuracy < 0.7) {
      panel.append(el('div', { class: 'soft', style: { fontSize: '13px', background: 'var(--surface-2)', borderRadius: '10px', padding: '10px 13px' } },
        `💡 Your mid/high confidence is least reliable on `, el('b', {}, hot.subject),
        ` (right ${Math.round(hot.accuracy * 100)}% of ${hot.n}) — slow down before revealing there.`));
    }
    view.append(panel);
  }

  // heatmap (full year)
  view.append(el('div', { class: 'card', style: { marginTop: '16px' } },
    el('div', { class: 'eyebrow', style: { marginBottom: '14px' } }, 'Activity · last year'),
    el('div', { style: { overflowX: 'auto' } }, heatmapEl(s.heatmap, 52))));

  return view;
}
