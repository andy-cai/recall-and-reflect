// Recall — effortful review. Free recall → confidence → reveal → AI grade + poke → rate.
import { el, clear, toast, state, infoTip } from '../store.js';
import { api } from '../api.js';
import { navigate, refreshBadge } from '../app.js';
import { renderMathIn } from '../math.js';

const CONF = { 1: 'Guessing', 2: 'Pretty sure', 3: 'Certain' };

function hintFor(c, level) {
  // Topic-recall cards hint with a rubric line — a real retrieval cue.
  if (c.ideas && c.ideas.length) {
    const i = Math.min(level, c.ideas.length) - 1;
    return `Idea ${i + 1} of ${c.ideas.length}: ${c.ideas[i].text}`;
  }
  const ans = c.answer || '';
  const words = ans.split(/\s+/).filter(Boolean);
  if (level <= 1) return `${words.length} word${words.length !== 1 ? 's' : ''} · starts with “${ans.trim()[0] || '?'}”`;
  if (level === 2) return `First word: “${words[0] || ''}”`;
  return `Starts: “${ans.slice(0, Math.ceil(ans.length / 2))}…”`;
}

export async function render({ params } = {}) {
  const llmOk = !!(state.llm && state.llm.available);
  const data = await api.queue({ tag: params?.tag || null, learning_id: params?.learning || null,
    subject: params?.subject, limit: params?.limit || null,
    focus: params?.focus || null, mode: params?.mode || null });
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
  let reviewedCount = 0, correctish = 0, lastRecall = '', suggested = null, rateGrid = null;
  let ideaResults = null;

  function total() { return cards.length; }  // grows if a confident miss is re-queued

  function updateProgress() {
    progLabel.textContent = `${Math.min(idx + 1, total())} / ${total()}`;
    progBar.firstChild.style.width = (idx / total() * 100) + '%';
  }

  function current() { return cards[idx]; }

  function showCard() {
    if (idx >= total()) return finish();
    revealed = false; confidence = null; hints = 0; verdict = null; suggested = null; rateGrid = null;
    ideaResults = null;
    cardStart = Date.now();
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
        el('div', { class: 'muted center', style: { fontSize: '12px' } }, 'How sure are you, before you peek?',
          infoTip('Committing to a confidence first makes recall more effortful — and being surprised by a confident miss helps the correction stick (the hypercorrection effect).')),
        confRow,
        hintBox,
        el('div', { class: 'row', style: { justifyContent: 'center', gap: '10px', marginTop: '4px' } }, hintBtn, revealBtn)));

    stage._recallInput = recallInput;
    stage._hintBox = hintBox;
    renderMathIn(qcard);
    setTimeout(() => recallInput.focus(), 30);

    function showHint() {
      const maxHints = c.ideas && c.ideas.length ? c.ideas.length : 3;
      hints = Math.min(maxHints, hints + 1);
      hintBox.hidden = false;
      hintBox.textContent = '💡 ' + hintFor(c, hints);
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

    // Topic recall with a rubric → checklist reveal; otherwise the classic answer box.
    const hasRubric = !!(c.ideas && c.ideas.length);
    let answerBox, ideaRows = null, ideaCount = null;
    if (hasRubric) {
      ideaRows = c.ideas.map(i => {
        const mark = el('span', { class: 'mark' }, '·');
        const node = el('div', { class: 'idea' }, mark, el('div', { class: 't' }, i.text));
        return { id: i.id, text: i.text, node, mark };
      });
      ideaCount = el('span', { class: 'muted', style: { fontSize: '12px' } },
        llmOk && recallText ? '' : 'self-check: which did you actually say?');
      answerBox = el('div', { class: 'card', style: { marginTop: '12px', padding: '16px' } },
        el('div', { class: 'row spread', style: { marginBottom: '10px' } },
          el('div', { class: 'eyebrow' }, 'Key ideas'), ideaCount),
        ...ideaRows.map(r => r.node));
    } else {
      answerBox = el('div', { class: 'a-reveal' },
        el('div', { class: 'lbl' }, 'Answer'),
        el('div', { class: 'a' }, c.answer));
    }
    stage.append(answerBox);

    const gradeSlot = el('div', {});
    stage.append(gradeSlot);
    renderMathIn(stage);

    rateGrid = buildRateGrid(c);
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
        // Paint the rubric checklist: ✓ hit / ◐ partial / ✕ miss per idea.
        if (g.ideas && ideaRows) {
          ideaResults = g.ideas.map(({ id, result }) => ({ id, result }));
          const marks = { hit: ['hit', '✓'], partial: ['part', '◐'], miss: ['miss', '✕'] };
          let hitN = 0;
          for (const r of g.ideas) {
            const row = ideaRows.find(x => x.id === r.id);
            if (!row) continue;
            const [cls, sym] = marks[r.result] || marks.miss;
            row.node.classList.add(cls);
            row.mark.textContent = sym;
            if (r.result === 'hit') hitN++;
          }
          if (ideaCount) ideaCount.textContent = `${hitN} of ${g.ideas.length}`;
        }
        const vbadge = el('div', { class: 'center', style: { marginTop: '14px' } },
          el('span', { class: 'verdict ' + verdict }, verdict === 'correct' ? '✓ Got it' : verdict === 'partial' ? '◐ Partial' : '✕ Missed it'));
        gradeSlot.append(vbadge);
        if (g.missing && verdict !== 'correct' && !hasRubric) {
          gradeSlot.append(el('div', { class: 'muted center', style: { fontSize: '13px', marginTop: '6px' } }, 'Missing: ' + g.missing));
        }
        if (g.drilled && g.drilled.length) {
          gradeSlot.append(el('div', { class: 'muted center', style: { fontSize: '12.5px', marginTop: '6px' } },
            '🛠 Added a drill card for an idea you keep missing.'));
        }
        // Confident miss → hypercorrection: call it out and re-queue for this session.
        if (confidence === 3 && verdict === 'wrong') {
          answerBox.classList.add('hypercorrect');
          gradeSlot.append(el('div', { class: 'hyper' }, '⚡',
            el('div', {}, 'You were ', el('b', {}, 'certain'), ' and missed it — these stick hardest once corrected. ',
              el('b', {}, 'It returns at the end of this session.'))));
          if (!c.requeued) cards.push({ ...c, requeued: true });
        }
        if (g.poke) {
          gradeSlot.append(el('div', { class: 'poke' },
            el('div', { class: 'lbl' }, 'Push yourself'),
            el('div', { class: 'q' }, g.poke)));
        }
        markSuggested(verdict);
      } catch {
        clear(gradeSlot);
      }
    } else if (!recallText) {
      gradeSlot.append(el('div', { class: 'muted center', style: { fontSize: '12.5px', marginTop: '12px' } },
        'Self-grade: how close were you?'));
    }
  }

  // Pre-highlight the rating consistent with the AI verdict (the honest default).
  // Easy is never auto-suggested; Enter takes the suggestion, 1–4 always work.
  function markSuggested(v) {
    suggested = v === 'wrong' ? 1 : v === 'partial' ? 2 : 3;
    if (!rateGrid) return;
    const btn = rateGrid.children[suggested - 1];
    btn.classList.add('suggested');
    btn.append(el('span', { class: 'sug' },
      `AI suggests · ${v === 'correct' ? '✓ got it' : v === 'partial' ? '◐ partial' : '✕ missed'} · Enter`));
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
      bury: !params?.learning,   // topic practice reviews siblings on purpose
      idea_results: ideaResults,
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
    progLabel.textContent = `${total()} / ${total()}`;
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
      else if (e.key === 'Enter' && suggested) { e.preventDefault(); rate(suggested); }
      else if (e.key.toLowerCase() === 'z') { e.preventDefault(); doUndo(); }
    }
  }
  document.addEventListener('keydown', onKey);
  view._cleanup = () => document.removeEventListener('keydown', onKey);

  showCard();
  return view;
}
