// Recall — effortful review. Free recall → confidence → reveal → AI grade + poke → rate.
import { el, clear, toast, state } from '../store.js';
import { api } from '../api.js';
import { navigate, refreshBadge } from '../app.js';

const CONF = { 1: 'Guessing', 2: 'Pretty sure', 3: 'Certain' };

function hintFor(ans, level) {
  ans = ans || '';
  const words = ans.split(/\s+/).filter(Boolean);
  if (level <= 1) return `${words.length} word${words.length !== 1 ? 's' : ''} · starts with “${ans.trim()[0] || '?'}”`;
  if (level === 2) return `First word: “${words[0] || ''}”`;
  return `Starts: “${ans.slice(0, Math.ceil(ans.length / 2))}…”`;
}

export async function render({ params } = {}) {
  const llmOk = !!(state.llm && state.llm.available);
  const data = await api.queue({ tag: params?.tag || null, learning_id: params?.learning || null, subject: params?.subject });
  const cards = data.cards;

  const view = el('div', { class: 'view' });
  const wrap = el('div', { class: 'review-wrap', tabindex: '-1' });
  view.append(wrap);

  if (!cards.length) {
    wrap.append(el('div', { class: 'empty' },
      el('div', { class: 'icon' }, '✓'),
      el('h2', {}, 'Nothing due'),
      el('p', { class: 'muted' }, 'You’re caught up. Come back when reviews are ready, or capture something new.'),
      el('div', { class: 'row', style: { justifyContent: 'center', marginTop: '18px' } },
        el('button', { class: 'btn', onClick: () => navigate('#/today') }, 'Back to Today'),
        el('button', { class: 'btn btn-primary', onClick: () => navigate('#/reflect') }, 'Reflect →'))));
    return view;
  }

  // top progress
  const progLabel = el('div', { class: 'prog-label' });
  const progBar = el('div', { class: 'progress', style: { flex: '1' } }, el('i'));
  wrap.append(el('div', { class: 'review-top' },
    el('button', { class: 'btn btn-ghost', style: { padding: '6px 10px' }, onClick: () => navigate('#/today') }, '✕ Exit'),
    progBar, progLabel));

  const stage = el('div', {});           // rebuilt per card / phase
  wrap.append(stage);

  let idx = 0, revealed = false, confidence = null, hints = 0, cardStart = 0, verdict = null;
  let reviewedCount = 0, correctish = 0, lastRecall = '';

  const total = cards.length;

  function updateProgress() {
    progLabel.textContent = `${Math.min(idx + 1, total)} / ${total}`;
    progBar.firstChild.style.width = (idx / total * 100) + '%';
  }

  function current() { return cards[idx]; }

  function showCard() {
    if (idx >= total) return finish();
    revealed = false; confidence = null; hints = 0; verdict = null; cardStart = Date.now();
    updateProgress();
    clear(stage);
    const c = current();

    const qcard = el('div', { class: 'q-card' },
      el('div', { class: 'src' }, c.title ? `from · ${c.title}` : ''),
      el('div', { class: 'q' }, c.front));
    stage.append(qcard);

    const recallInput = el('textarea', { class: 'input', rows: '3', placeholder: 'Try to recall it — type what you remember…' });

    const confRow = el('div', { class: 'confidence' },
      ...[1, 2, 3].map(n => el('button', { class: 'conf-pill', onClick: (e) => {
        confidence = n;
        confRow.querySelectorAll('.conf-pill').forEach(p => p.classList.remove('on'));
        e.currentTarget.classList.add('on');
      } }, CONF[n])));

    const hintBox = el('div', { class: 'hint-box', hidden: true });
    const hintBtn = el('button', { class: 'btn btn-ghost', onClick: showHint }, 'Hint (H)');
    const revealBtn = el('button', { class: 'btn btn-primary btn-lg', onClick: reveal }, 'Reveal answer ·  Space');

    stage.append(
      el('div', { class: 'stack', style: { marginTop: '18px' } },
        recallInput,
        el('div', { class: 'muted center', style: { fontSize: '12px' } }, 'How sure are you, before you peek?'),
        confRow,
        hintBox,
        el('div', { class: 'row', style: { justifyContent: 'center', gap: '10px', marginTop: '4px' } }, hintBtn, revealBtn)));

    stage._recallInput = recallInput;
    stage._hintBox = hintBox;
    setTimeout(() => recallInput.focus(), 30);

    function showHint() {
      hints = Math.min(3, hints + 1);
      hintBox.hidden = false;
      hintBox.textContent = '💡 ' + hintFor(c.answer, hints);
    }
    stage._showHint = showHint;
  }

  async function reveal() {
    if (revealed) return;
    revealed = true;
    const c = current();
    const recallText = (stage._recallInput?.value || '').trim();
    lastRecall = recallText;
    if (stage._recallInput) { stage._recallInput.readOnly = true; stage._recallInput.blur(); }
    wrap.focus();

    // Build answer + rating UI
    clear(stage);
    stage.append(el('div', { class: 'q-card' },
      el('div', { class: 'src' }, c.title ? `from · ${c.title}` : ''),
      el('div', { class: 'q' }, c.front)));

    if (recallText) {
      stage.append(el('div', { class: 'card', style: { marginTop: '12px', textAlign: 'center' } },
        el('div', { class: 'eyebrow', style: { marginBottom: '6px' } }, 'Your recall'),
        el('div', { class: 'soft' }, recallText)));
    }

    const answerBox = el('div', { class: 'a-reveal' },
      el('div', { class: 'lbl' }, 'Answer'),
      el('div', { class: 'a' }, c.answer));
    stage.append(answerBox);

    const gradeSlot = el('div', {});
    stage.append(gradeSlot);

    const rateGrid = buildRateGrid(c);
    stage.append(rateGrid);
    stage.append(el('div', { class: 'row', style: { justifyContent: 'center', gap: '14px', marginTop: '12px' } },
      el('span', { class: 'muted', style: { fontSize: '12px' } }, 'Rate honestly — ', el('span', { class: 'kbd' }, '1'), '–', el('span', { class: 'kbd' }, '4')),
      el('button', { class: 'btn-ghost', style: { fontSize: '12px', padding: '4px 8px' }, onClick: doUndo }, '↶ Undo (Z)')));

    // AI grade only when the learner actually attempted in writing
    if (llmOk && recallText) {
      gradeSlot.append(el('div', { class: 'row', style: { justifyContent: 'center', padding: '12px' } },
        el('span', { class: 'spin' }), el('span', { class: 'muted' }, ' checking your recall…')));
      try {
        const g = await api.grade(c.id, recallText);
        verdict = g.verdict;
        clear(gradeSlot);
        const hyper = confidence === 3 && verdict === 'wrong';
        const vbadge = el('div', { class: 'center', style: { marginTop: '14px' } },
          el('span', { class: 'verdict ' + verdict }, verdict === 'correct' ? '✓ Got it' : verdict === 'partial' ? '◐ Partial' : '✕ Missed it'));
        if (hyper) {
          answerBox.classList.add('hypercorrect');
          vbadge.append(el('div', { class: 'muted', style: { fontSize: '12.5px', marginTop: '6px' } }, 'You were certain — worth a closer look.'));
        }
        gradeSlot.append(vbadge);
        if (g.missing && verdict !== 'correct') {
          gradeSlot.append(el('div', { class: 'muted center', style: { fontSize: '13px', marginTop: '6px' } }, 'Missing: ' + g.missing));
        }
        if (g.poke) {
          gradeSlot.append(el('div', { class: 'poke' },
            el('div', { class: 'lbl' }, 'Push yourself'),
            el('div', { class: 'q' }, g.poke)));
        }
      } catch {
        clear(gradeSlot);
      }
    } else if (!recallText) {
      gradeSlot.append(el('div', { class: 'muted center', style: { fontSize: '12.5px', marginTop: '12px' } },
        'Self-grade: how close were you?'));
    }
  }

  function buildRateGrid(c) {
    const grid = el('div', { class: 'rate-grid' });
    const defs = [
      ['again', 'Again', c.intervals.again, 1],
      ['hard', 'Hard', c.intervals.hard, 2],
      ['good', 'Good', c.intervals.good, 3],
      ['easy', 'Easy', c.intervals.easy, 4],
    ];
    for (const [cls, name, iv, r] of defs) {
      grid.append(el('button', { class: 'rate-btn ' + cls, onClick: () => rate(r) },
        el('span', { class: 'name ' + cls }, name),
        el('span', { class: 'iv' }, iv),
        el('span', { class: 'key' }, String(r))));
    }
    return grid;
  }

  async function rate(r) {
    if (!revealed) return;
    const c = current();
    const payload = {
      question_id: c.id, rating: r,
      recall: lastRecall, confidence, ai_verdict: verdict,
      elapsed_ms: Date.now() - cardStart,
    };
    revealed = false; // guard against double
    try { await api.answer(payload); } catch (e) { toast('Could not save: ' + e.message); }
    reviewedCount += 1;
    if (verdict === 'correct' || (verdict == null && r >= 3)) correctish += 1;
    idx += 1;
    refreshBadge();
    showCard();
  }

  async function doUndo() {
    const res = await api.undo();
    if (!res || !res.question_id) { toast('Nothing to undo'); return; }
    if (idx > 0) idx -= 1;
    reviewedCount = Math.max(0, reviewedCount - 1);
    refreshBadge();
    showCard();
    toast('Undid last review');
  }

  function finish() {
    clear(stage);
    progLabel.textContent = `${total} / ${total}`;
    progBar.firstChild.style.width = '100%';
    const acc = reviewedCount ? Math.round(correctish / reviewedCount * 100) : 0;
    stage.append(el('div', { class: 'empty' },
      el('div', { class: 'icon' }, '🎉'),
      el('h2', {}, 'Session complete'),
      el('p', { class: 'muted' }, `${reviewedCount} card${reviewedCount !== 1 ? 's' : ''} reviewed${reviewedCount ? ` · ~${acc}% recalled` : ''}.`),
      el('div', { class: 'row', style: { justifyContent: 'center', marginTop: '18px' } },
        el('button', { class: 'btn btn-primary', onClick: () => navigate('#/today') }, 'Back to Today'))));
  }

  // ---------- keyboard ----------
  function onKey(e) {
    const editable = e.target.matches && e.target.matches('textarea:not([readonly]), input:not([readonly])');
    if (editable) {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); reveal(); }
      return;
    }
    if (e.key === 'Escape') { navigate('#/today'); return; }
    if (!revealed) {
      if (e.key === ' ' || e.key === 'Enter') { e.preventDefault(); reveal(); }
      else if (e.key.toLowerCase() === 'h') { e.preventDefault(); stage._showHint && stage._showHint(); }
      else if (e.key.toLowerCase() === 'z') { e.preventDefault(); doUndo(); }
    } else {
      if (['1', '2', '3', '4'].includes(e.key)) { e.preventDefault(); rate(Number(e.key)); }
      else if (e.key.toLowerCase() === 'z') { e.preventDefault(); doUndo(); }
    }
  }
  document.addEventListener('keydown', onKey);
  view._cleanup = () => document.removeEventListener('keydown', onKey);

  showCard();
  return view;
}
