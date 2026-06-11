import { el, clear, toast, applyTheme, state, infoTip } from '../store.js';
import { api } from '../api.js';
import { refreshBadge } from '../app.js';
import { ambientEnabled, setAmbientEnabled } from '../ambient.js';
import { BENCH_COLS, BENCH_NOTE, MODEL_GUIDE } from '../models-info.js';

export async function render() {
  const [s, promptInfo, logData] = await Promise.all([
    api.getSettings(),
    api.prompts().catch(() => null),
    api.cloudLog().catch(() => null),
  ]);
  const view = el('div', { class: 'view' });
  view.append(el('div', { class: 'page-head' }, el('h1', {}, 'Settings')));

  // daily target
  const targetInput = el('input', { class: 'input', type: 'number', min: '1', max: '500', value: String(s.daily_target), style: { maxWidth: '120px' } });

  // new cards per day
  const newPerDayInput = el('input', { class: 'input', type: 'number', min: '1', max: '100', value: String(s.new_per_day ?? 10), style: { maxWidth: '120px' } });

  // desired retention
  const retVal = Math.round((s.desired_retention || 0.9) * 100);
  const retLabel = el('b', {}, retVal + '%');
  const retNote = el('div', { class: 'muted', style: { fontSize: '12.5px' } });
  const retSlider = el('input', { class: 'slider', type: 'range', min: '70', max: '97', value: String(retVal) });
  function retText(v) { return v >= 92 ? 'Thorough: more frequent reviews.' : v <= 82 ? 'Light: fewer reviews, more forgetting.' : 'Balanced (90% is the sweet spot).'; }
  retNote.textContent = retText(retVal);
  retSlider.addEventListener('input', () => { retLabel.textContent = retSlider.value + '%'; retNote.textContent = retText(+retSlider.value); });

  // model
  const models = (s.llm && s.llm.models) || [];
  const modelSel = el('select', { class: 'input', style: { maxWidth: '260px' } },
    ...(models.length ? models : [s.model]).map(m => el('option', { value: m, selected: m === s.model ? '' : null }, m)));

  // fast model — a smaller model for latency-sensitive calls (grading, matching)
  const fastSel = el('select', { class: 'input', style: { maxWidth: '260px' } },
    el('option', { value: '', selected: !s.fast_model ? '' : null }, 'Same as main model'),
    ...models.map(m => el('option', { value: m, selected: m === s.fast_model ? '' : null }, m)));
  const llmStatus = s.llm && s.llm.available
    ? el('span', { class: 'verdict correct' }, '● ' + s.llm.model)
    : el('span', { class: 'verdict wrong' }, '● offline');

  // question style — appended to every generation prompt (cards, ideas, drills, rewrites)
  const styleArea = el('textarea', { class: 'input', rows: '3' });
  styleArea.value = s.gen_style || '';

  // cloud assist (strictly opt-in, per-click)
  const cloud = s.cloud || { enabled: false, models: [], key_present: false };
  let cloudOn = !!cloud.enabled;
  const cloudSw = el('div', { class: 'switch' + (cloudOn ? ' on' : ''), onClick: () => { cloudOn = !cloudOn; cloudSw.classList.toggle('on', cloudOn); } }, el('i'));
  const cloudModelSel = el('select', { class: 'input', style: { maxWidth: '220px' } },
    ...(cloud.models || []).map(m => el('option', { value: m, selected: m === cloud.model ? '' : null }, m)));
  const cloudStatus = cloud.key_present
    ? el('span', { class: 'verdict correct' }, '● key found')
    : el('span', { class: 'verdict wrong' }, '● set GEMINI_API_KEY');

  // theme
  const themeSel = el('select', { class: 'input', style: { maxWidth: '160px' } },
    ...['light', 'dark', 'system'].map(t => el('option', { value: t, selected: t === s.theme ? '' : null }, t[0].toUpperCase() + t.slice(1))));
  themeSel.addEventListener('change', () => { applyTheme(themeSel.value); localStorage.setItem('rr-theme', themeSel.value); });

  // notifications
  let notif = !!s.notifications;
  const sw = el('div', { class: 'switch' + (notif ? ' on' : ''), onClick: () => { notif = !notif; sw.classList.toggle('on', notif); } }, el('i'));

  // living backgrounds
  let amb = ambientEnabled();
  const ambSw = el('div', { class: 'switch' + (amb ? ' on' : ''), onClick: () => { amb = !amb; ambSw.classList.toggle('on', amb); } }, el('i'));

  function field(label, control, hint) {
    return el('div', { class: 'row spread', style: { padding: '14px 0', borderBottom: '1px solid var(--border)' } },
      el('div', {}, el('div', { style: { fontWeight: '560' } }, label), hint ? el('div', { class: 'muted', style: { fontSize: '12.5px', maxWidth: '420px' } }, hint) : null),
      control);
  }

  const saveBtn = el('button', { class: 'btn btn-primary', onClick: save }, 'Save settings');

  view.append(el('div', { class: 'card' },
    field('Daily review target', targetInput, 'A gentle goal for reviews per day.'),
    field('New topics per day', newPerDayInput, 'Caps how many brand-new cards enter review daily, so a big capture spree eases in instead of flooding tomorrow.'),
    el('div', { style: { padding: '14px 0', borderBottom: '1px solid var(--border)' } },
      el('div', { class: 'row spread' }, el('div', { style: { fontWeight: '560' } }, 'Target retention', infoTip('The chance you want of recalling a topic when it comes due. Higher = more frequent reviews. FSRS uses this to time each one; 90% is the sweet spot.')), retLabel),
      el('div', { style: { margin: '8px 0' } }, retSlider), retNote),
    field('AI model (local)', el('div', { class: 'row', style: { gap: '10px' } }, llmStatus, modelSel), 'Runs entirely on your machine via Ollama. Cloud models are blocked.'),
    field('Fast model (grading)', fastSel, 'Snappier reviews: a small model (qwen3:4b or qwen2.5:3b) grades recall and matches focus requests; the app turns reasoning off for these calls so verdicts land in a beat. Capture quality stays on the main model.'),
    el('div', { style: { padding: '14px 0', borderBottom: '1px solid var(--border)' } },
      el('div', { style: { fontWeight: '560' } }, 'Question style'),
      el('div', { class: 'muted', style: { fontSize: '12.5px', margin: '2px 0 8px' } },
        'Applied to every generated question, answer, rubric and rewrite. Edit to taste.'),
      styleArea),
    el('div', { style: { padding: '14px 0', borderBottom: '1px solid var(--border)' } },
      el('div', { class: 'row spread' },
        el('div', {},
          el('div', { style: { fontWeight: '560' } }, 'Cloud assist (Gemini)'),
          el('div', { class: 'muted', style: { fontSize: '12.5px', maxWidth: '420px' } },
            'Off by default. When on, an “Improve with Gemini” button appears on cards; only that card’s text is sent, only when you click. Free API key at aistudio.google.com. Reviews, capture and grading always stay local.')),
        cloudSw),
      el('div', { class: 'row', style: { gap: '10px', marginTop: '10px' } }, cloudStatus, cloudModelSel)),
    field('Theme', themeSel),
    field('Living backgrounds', ambSw, 'Slow ambient scenes behind each view (halo + fireflies while reflecting). Off = flat. Also respects your OS reduced-motion setting.'),
    field('Due reminders', sw, 'A gentle Windows notification when reviews pile up.'),
    el('div', { class: 'row', style: { justifyContent: 'flex-end', paddingTop: '16px' } }, saveBtn)));

  // ---------- the models: why these, with published scores ----------
  view.append(section('The models', 'Why each one is on the list, and how they score on published benchmarks.',
    buildModelGuide(), false));

  // ---------- prompt transparency: exactly what each model is asked ----------
  if (promptInfo && promptInfo.prompts) {
    view.append(section('What the AI is asked', 'Every system prompt, verbatim, with where it runs.',
      buildPromptPanel(promptInfo), false));
  }

  // ---------- sent-to-cloud audit log ----------
  view.append(section('Sent to cloud', 'Every request that ever went to Gemini from this app.',
    buildCloudLog(logData ? logData.entries || [] : null), false));

  view.append(el('div', { class: 'card', style: { marginTop: '16px', background: 'var(--surface-2)' } },
    el('div', { class: 'row', style: { gap: '10px' } },
      el('div', { class: 'muted', style: { fontSize: '13px' } },
        el('b', { style: { color: 'var(--text-soft)' } }, 'Your data stays on this machine. '),
        'Notes and reviews live in a local SQLite file, and routine operation talks only to a local Ollama. The single exception is the opt-in Gemini assist above: explicit per-click or per-session, refused for People and for topics you mark private, with saved People names replaced by [name] in every payload, and every request recorded in the log above.'))));

  async function save() {
    saveBtn.disabled = true; saveBtn.textContent = 'Saving…';
    try {
      await api.updateSettings({
        daily_target: +targetInput.value,
        new_per_day: +newPerDayInput.value,
        desired_retention: +retSlider.value / 100,
        notifications: notif,
        theme: themeSel.value,
        model: modelSel.value,
        fast_model: fastSel.value,
        gen_style: styleArea.value.trim(),
        cloud_enabled: cloudOn,
        cloud_model: cloudModelSel.value || undefined,
      });
      setAmbientEnabled(amb);
      localStorage.setItem('rr-theme', themeSel.value);
      applyTheme(themeSel.value);
      state.settings = await api.getSettings();
      state.llm = state.settings.llm;
      refreshBadge();
      toast('Settings saved');
    } catch (e) {
      toast('Save failed: ' + e.message);
    }
    saveBtn.disabled = false; saveBtn.textContent = 'Save settings';
  }

  return view;
}

// ---------- collapsible card ----------
function section(title, sub, body, open = false) {
  const chev = el('span', { class: 'muted', style: { fontSize: '12px', flex: 'none' } }, open ? '▾' : '▸');
  const content = el('div', { style: { display: open ? '' : 'none', marginTop: '8px' } }, body);
  const head = el('div', { class: 'row spread subj-head', style: { padding: '2px' }, onClick: () => {
    open = !open;
    content.style.display = open ? '' : 'none';
    chev.textContent = open ? '▾' : '▸';
  } },
    el('div', {},
      el('div', { style: { fontWeight: '560' } }, title),
      sub ? el('div', { class: 'muted', style: { fontSize: '12.5px' } }, sub) : null),
    chev);
  return el('div', { class: 'card', style: { marginTop: '16px' } }, head, content);
}

// ---------- model guide: prose + published-benchmark bars ----------
function buildModelGuide() {
  const byId = Object.fromEntries(MODEL_GUIDE.map(m => [m.id, m]));

  function bars(m) {
    const rows = [];
    for (const col of BENCH_COLS) {
      let inner = null, val = '';
      if (m.bench && m.bench[col.key] != null) {
        inner = el('i', { style: { width: m.bench[col.key] + '%' } });
        val = m.bench[col.key].toFixed(1);
      } else if (m.range) {
        const lo = byId[m.range.lo]?.bench?.[col.key];
        const hi = byId[m.range.hi]?.bench?.[col.key];
        if (lo != null && hi != null) {
          inner = el('i', { class: 'range', style: { left: lo + '%', width: Math.max(2, hi - lo) + '%' } });
          val = '~';
        }
      }
      if (inner) {
        rows.push(el('div', { class: 'bench-row' },
          el('span', { class: 'lbl', title: col.hint }, col.label),
          el('div', { class: 'bench-bar' }, inner),
          el('span', { class: 'val' }, val)));
      }
    }
    return rows;
  }

  const wrap = el('div', {});
  let lastGroup = null;
  for (const m of MODEL_GUIDE) {
    if (m.group !== lastGroup) {
      lastGroup = m.group;
      wrap.append(el('div', { class: 'eyebrow', style: { margin: '16px 0 2px' } }, m.group));
    }
    wrap.append(el('div', { class: 'model-row' },
      el('div', { class: 'row', style: { gap: '10px', marginBottom: '4px' } },
        el('span', { class: 'name' }, m.id),
        m.badge ? el('span', { class: 'badge-soft' }, m.badge) : null),
      el('div', { class: 'soft', style: { fontSize: '13px', lineHeight: '1.5' } }, m.why),
      bars(m),
      (m.src || m.note) ? el('div', { class: 'muted', style: { fontSize: '11.5px', marginTop: '6px' } }, m.src || m.note) : null));
  }
  wrap.append(el('div', { class: 'muted', style: { fontSize: '12px', marginTop: '14px', lineHeight: '1.5' } }, BENCH_NOTE));
  return wrap;
}

// ---------- prompt transparency ----------
function buildPromptPanel(info) {
  const wrap = el('div', {});
  wrap.append(el('div', { class: 'muted', style: { fontSize: '12.5px', margin: '2px 0 8px', lineHeight: '1.5' } },
    'Verbatim: this is exactly what each model receives, plus your Question style where marked. ',
    'Grading and everything marked "fast" never leaves Ollama.'));
  for (const p of info.prompts) {
    const chips = [
      el('span', { class: 'chip-tag ' + p.runs },
        p.runs === 'fast' ? `fast · ${info.fast_model}` : `main · ${info.main_model}`),
      p.cloud ? el('span', { class: 'chip-tag cloud', title: 'Routes to Gemini when you explicitly choose cloud assist' },
        `+ ${info.cloud_model}`) : null,
      p.styled ? el('span', { class: 'chip-tag', title: 'Your Question style from above is appended' }, 'styled') : null,
      p.reasoning === 'off' ? el('span', { class: 'chip-tag', title: 'Model reasoning is switched off for speed on this call' }, 'no thinking') : null,
    ];
    wrap.append(el('details', { class: 'prompt-row' },
      el('summary', {},
        el('span', { class: 'chev' }, '▸'),
        el('span', { class: 'pname' }, p.name),
        el('span', { class: 'pwhat' }, p.what),
        ...chips),
      el('pre', { class: 'prompt-pre' }, p.system)));
  }
  return wrap;
}

// ---------- sent-to-cloud log ----------
function buildCloudLog(entries) {
  const wrap = el('div', {});
  if (entries === null) {
    wrap.append(el('div', { class: 'muted', style: { fontSize: '13px' } }, 'Could not load the log.'));
    return wrap;
  }
  function renderEntries(list) {
    clear(wrap);
    if (!list.length) {
      wrap.append(el('div', { class: 'muted', style: { fontSize: '13px', padding: '6px 2px' } },
        'No cloud requests on record. Anything that leaves this machine from now on is listed here.'));
      return;
    }
    for (const e of list) {
      const when = new Date(e.ts).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
      wrap.append(el('div', { class: 'cloud-log-row' },
        el('span', { class: 'when' }, when),
        el('span', { class: 'what' }, e.action,
          e.redacted ? el('span', { class: 'muted' }, ` · ${e.redacted} name${e.redacted !== 1 ? 's' : ''} redacted`) : null),
        el('span', { class: 'meta' }, `${e.model} · ${e.chars} chars`),
        e.ok ? null : el('span', { class: 'err', title: e.detail || '' }, 'failed')));
    }
    wrap.append(el('div', { class: 'row', style: { justifyContent: 'flex-end', marginTop: '10px' } },
      el('button', { class: 'btn-ghost', style: { fontSize: '12.5px' }, onClick: async () => {
        await api.clearCloudLog();
        toast('Log cleared');
        renderEntries([]);
      } }, 'Clear log')));
  }
  renderEntries(entries);
  return wrap;
}
