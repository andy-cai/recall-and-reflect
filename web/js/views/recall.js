// Recall — effortful review. Free recall → confidence → reveal → AI grade + poke → rate.
import { el, clear, toast, state, infoTip } from '../store.js';
import { api } from '../api.js';
import { navigate, refreshBadge } from '../app.js';
import { renderMathIn } from '../math.js';

const CONF = { 1: 'Guessing', 2: 'Pretty sure', 3: 'Certain' };

// People are yours to judge (no AI grading); sketch tasks are drawn on paper.
const isPerson = (c) => (c.subject || '').toLowerCase() === 'people';
const isSketch = (c) => /\bsketch\b/i.test(c.front || '');
const firstName = (c) => (c.title || '').trim().split(/\s+/)[0] || 'them';

function sketchNote() {
  return el('div', { class: 'sketch-note' },
    'Paper task: sketch it on nearby paper, then reveal and check feature by feature.');
}

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

  // Standalone teach-back from the Library (Teach it)
  if (params?.teach) {
    const lid = Number(params.teach);
    const detail = await api.getLearning(lid);
    const view = el('div', { class: 'view' });
    view.append(teachUI({
      learningId: lid,
      title: detail.learning.title,
      ideas: (detail.key_ideas || []).map(i => ({ id: i.id, text: i.idea })),
      onDone: () => navigate('#/library/' + lid),
    }));
    return view;
  }

  const data = await api.queue({ tag: params?.tag || null, learning_id: params?.learning || null,
    subject: params?.subject, limit: params?.limit || null,
    focus: params?.focus || null, mode: params?.mode || null });
  const cards = data.cards;

  // Scheduled teach swap-in: at most one solid topic per session teaches instead
  // of recalling (deterministic per day, ~1 in 3 of the eligible).
  if (llmOk) {
    const candidate = cards.find(c => c.teach_eligible && (c.id + new Date().getDate()) % 3 === 0);
    if (candidate) candidate._teach = true;
  }

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

    // Solid topic → teach it instead of recalling it (skippable)
    if (c._teach) {
      stage._teachActive = true;
      stage.append(teachUI({
        learningId: c.learning_id,
        title: c.title,
        ideas: c.ideas || [],
        onSkip: () => { c._teach = false; stage._teachActive = false; showCard(); },
        onDone: () => {
          stage._teachActive = false;
          reviewedCount += 1; correctish += 1;
          idx += 1; refreshBadge(); showCard();
        },
      }));
      return;
    }
    stage._teachActive = false;

    const qcard = el('div', { class: 'q-card' },
      el('div', { class: 'src' }, c.title ? `from · ${c.title}` : ''),
      el('div', { class: 'q' }, c.front),
      isSketch(c) ? sketchNote() : null);
    stage.append(qcard);

    // quiet per-card actions: fix a bad question, or punt without rating
    const editSlot = el('div', {});
    stage.append(el('div', { class: 'row', style: { justifyContent: 'flex-end', gap: '4px', marginTop: '6px' } },
      el('button', { class: 'btn-ghost card-act', onClick: () => toggleEditPanel(c, editSlot) }, '✎ Edit'),
      el('button', { class: 'btn-ghost card-act', title: 'Skip without rating, stays due (S)', onClick: skipCard }, 'Skip ›')));
    stage.append(editSlot);

    const recallInput = el('textarea', { class: 'input', rows: '3', placeholder:
      isPerson(c) ? 'Their name; typing it out is what makes it stick. Add whatever else comes back…'
      : isSketch(c) ? 'Optional: list the features you drew (axes, shape, landmarks) and the AI will check them…'
      : 'Try to recall it. Type what you remember…' });

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
          infoTip('Committing to a confidence first makes recall more effortful, and being surprised by a confident miss helps the correction stick (the hypercorrection effect).')),
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
      hintBox.textContent = 'Hint: ' + hintFor(c, hints);
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
      el('div', { class: 'q' }, c.front),
      isSketch(c) ? sketchNote() : null));
    const editSlot = el('div', {});
    stage.append(el('div', { class: 'row', style: { justifyContent: 'flex-end', gap: '4px', marginTop: '6px' } },
      el('button', { class: 'btn-ghost card-act', onClick: () => toggleEditPanel(c, editSlot) }, '✎ Edit'),
      el('button', { class: 'btn-ghost card-act', title: 'Skip without rating, stays due (S)', onClick: skipCard }, 'Skip ›')));
    stage.append(editSlot);

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
      el('span', { class: 'muted', style: { fontSize: '12px' } }, 'Rate honestly: ', el('span', { class: 'kbd' }, '1'), '–', el('span', { class: 'kbd' }, '4')),
      el('button', { class: 'btn-ghost', style: { fontSize: '12px', padding: '4px 8px' }, onClick: doUndo }, '↶ Undo (Z)')));

    // People are never AI-graded: the verdict that matters — did the name come
    // back — is yours. The reveal doubles as keeping the person current.
    if (isPerson(c)) {
      gradeSlot.append(el('div', { class: 'muted center', style: { fontSize: '12.5px', marginTop: '12px' } },
        'You’re the judge for people. Did the name come back?'));
      gradeSlot.append(personPanel(c, answerBox));
      return;
    }

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
            'Added a drill card for an idea you keep missing.'));
        }
        // Confident miss → hypercorrection: call it out and re-queue for this session.
        if (confidence === 3 && verdict === 'wrong') {
          answerBox.classList.add('hypercorrect');
          gradeSlot.append(el('div', { class: 'hyper' },
            el('div', {}, 'You were ', el('b', {}, 'certain'), ' and missed it; these stick hardest once corrected. ',
              el('b', {}, 'It returns at the end of this session.'))));
          if (!c.requeued) cards.push({ ...c, requeued: true });
        }
        if (g.poke) {
          gradeSlot.append(el('div', { class: 'poke' },
            el('div', { class: 'lbl' }, 'Push yourself'),
            el('div', { class: 'q' }, g.poke)));
        }
        markSuggested(verdict);
      } catch (e) {
        // never swallow the failure — say why and fall back to self-grading
        clear(gradeSlot);
        gradeSlot.append(el('div', { class: 'muted center', style: { fontSize: '12.5px', marginTop: '12px' } },
          `AI grade unavailable${e && e.message ? ` (${e.message})` : ''}. Self-grade below.`));
      }
    } else if (!recallText) {
      gradeSlot.append(el('div', { class: 'muted center', style: { fontSize: '12.5px', marginTop: '12px' } },
        isSketch(c) ? 'Check your sketch against the features above, one by one.'
                    : 'Self-grade: how close were you?'));
    }
  }

  // ---------- person reveal: keep the card alive ----------
  // A person changes; Hall-Petch doesn't. The reveal offers two quiet moves:
  // append a dated update (review as keeping up, not testing), and rework the
  // memory hook after a miss (a stronger self-made image is the fix).
  function personPanel(c, answerBox) {
    const first = firstName(c);
    const formSlot = el('div', {});
    const setShownAnswer = () => {
      const a = answerBox.querySelector && answerBox.querySelector('.a');
      if (a) a.textContent = c.answer;
    };
    function openForm(kind) {
      clear(formSlot);
      const isUpdate = kind === 'update';
      const input = el('input', { class: 'input', placeholder: isUpdate
        ? `One line: what’s new with ${first}, or what to pick up next time…`
        : 'A stronger image: what does the name sound like, tied to something about them?' });
      const saveBtn = el('button', { class: 'btn', style: { padding: '8px 14px', fontSize: '13px', flex: 'none' } },
        isUpdate ? 'Add, dated' : 'Replace hook');
      saveBtn.addEventListener('click', async () => {
        const text = input.value.trim();
        if (!text) return;
        saveBtn.disabled = true;
        try {
          if (isUpdate) {
            await api.personUpdate(c.learning_id, text);
            const stamp = new Date().toISOString().slice(0, 10);
            c.answer = c.answer.trimEnd() + '\n' + stamp + ': ' + text;
            toast(`Noted. ${first}’s card stays current.`);
          } else {
            await api.personAssociation(c.learning_id, text);
            const lines = c.answer.split('\n').filter(ln => !/^(🧷 )?your association:/i.test(ln.trim()));
            while (lines.length && !lines[lines.length - 1].trim()) lines.pop();
            c.answer = [...lines, 'Your association: ' + text].join('\n');
            toast('New hook saved. It shows at the next reveal.');
          }
          setShownAnswer();
          clear(formSlot);
        } catch (e) { toast('Save failed: ' + e.message); saveBtn.disabled = false; }
      });
      input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') { e.preventDefault(); saveBtn.click(); }
        e.stopPropagation();
      });
      formSlot.append(el('div', { class: 'row', style: { gap: '8px', marginTop: '10px' } }, input, saveBtn));
      input.focus();
    }
    return el('div', {},
      el('div', { class: 'person-acts' },
        el('button', { class: 'btn-ghost card-act', onClick: () => openForm('update') }, `+ What’s new with ${first}?`),
        el('button', { class: 'btn-ghost card-act', title: 'Didn’t come back? Invent a stronger association.',
          onClick: () => openForm('assoc') }, 'Rework the hook')),
      formSlot);
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

  function skipCard() {
    toast('Skipped. No rating recorded; it stays due.');
    idx += 1;
    showCard();
  }

  // ---------- edit / feedback panel (fix a bad question mid-review) ----------
  function toggleEditPanel(c, slot) {
    if (slot.firstChild) { clear(slot); return; }
    if (c.card_type === 'cloze') {
      slot.append(el('div', { class: 'muted', style: { fontSize: '12.5px', textAlign: 'right', padding: '6px 2px' } },
        'Cloze cards are edited from their source in the Library.'));
      return;
    }
    const cloudReady = !!(state.settings && state.settings.cloud && state.settings.cloud.ready)
      && !isPerson(c) && !c.private;   // People and private topics never leave this machine
    const qIn = el('textarea', { class: 'input', rows: '2' }); qIn.value = c.front;
    const aIn = el('textarea', { class: 'input', rows: '3' }); aIn.value = c.answer;
    const fbIn = el('input', { class: 'input', placeholder: 'What’s wrong with it? “Too vague”, “ask for the mechanism, not the formula”…' });
    const proposalSlot = el('div', {});

    async function applyValues(q, a) {
      try {
        await api.updateCard(c.id, { question: q, answer: a });
        c.front = q; c.answer = a;
        toast('Card updated');
        clear(slot);
        showCard();
      } catch (e) { toast('Save failed: ' + e.message); }
    }

    async function improve(useCloud, btn) {
      const orig = btn.textContent;
      btn.disabled = true; btn.textContent = 'Rewriting…';
      try {
        const r = await api.refineCard(c.id, { feedback: fbIn.value.trim(), use_cloud: useCloud });
        clear(proposalSlot);
        proposalSlot.append(el('div', { class: 'card', style: { marginTop: '10px', padding: '12px', borderColor: 'var(--easy)' } },
          el('div', { class: 'eyebrow', style: { marginBottom: '8px' } },
            r.source === 'cloud' ? 'Gemini’s rewrite' : 'Rewrite'),
          el('div', { style: { fontSize: '14px', fontWeight: '580' } }, r.question),
          el('div', { class: 'soft', style: { fontSize: '13.5px', marginTop: '6px' } }, r.answer),
          el('div', { class: 'row', style: { gap: '8px', marginTop: '10px', justifyContent: 'flex-end' } },
            el('button', { class: 'btn-ghost', style: { fontSize: '13px' }, onClick: () => clear(proposalSlot) }, 'Discard'),
            el('button', { class: 'btn btn-primary', style: { padding: '6px 12px', fontSize: '13px' },
              onClick: () => applyValues(r.question, r.answer) }, 'Apply'))));
        renderMathIn(proposalSlot);
      } catch (e) {
        toast((useCloud ? 'Cloud rewrite failed: ' : 'Rewrite failed: ') + e.message);
      }
      btn.disabled = false; btn.textContent = orig;
    }

    const localBtn = el('button', { class: 'btn', style: { padding: '6px 12px', fontSize: '13px' },
      onClick: (e) => improve(false, e.currentTarget) }, 'Improve');
    const cloudBtn = cloudReady ? el('button', { class: 'btn', style: { padding: '6px 12px', fontSize: '13px' },
      onClick: (e) => improve(true, e.currentTarget) }, 'Improve with Gemini') : null;

    slot.append(el('div', { class: 'card stack', style: { marginTop: '8px', padding: '14px', textAlign: 'left' } },
      el('div', { class: 'field' }, el('label', { class: 'lbl' }, 'Question'), qIn),
      el('div', { class: 'field' }, el('label', { class: 'lbl' }, 'Answer / reference'), aIn),
      el('div', { class: 'field' }, el('label', { class: 'lbl' }, 'Feedback for the AI rewrite (optional)'), fbIn),
      el('div', { class: 'row wrap', style: { gap: '8px', justifyContent: 'flex-end' } },
        localBtn, cloudBtn,
        el('button', { class: 'btn-ghost', style: { fontSize: '13px' }, title: 'Push it out a day without rating',
          onClick: async () => { await api.buryCard(c.id, 1); toast('Not today. Back tomorrow.'); clear(slot); skipCard(); } }, 'Not today'),
        el('button', { class: 'btn-ghost', style: { fontSize: '13px' },
          onClick: async () => { await api.suspendCard(c.id, true); toast('Suspended.'); refreshBadge(); clear(slot); skipCard(); } }, 'Suspend'),
        el('button', { class: 'btn btn-primary', style: { padding: '6px 12px', fontSize: '13px' },
          onClick: () => applyValues(qIn.value.trim(), aIn.value.trim()) }, 'Save')),
      proposalSlot));
    fbIn.focus();
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
      el('div', { class: 'icon' }, '✓'),
      el('h2', {}, 'Session complete'),
      el('p', { class: 'muted' }, `${reviewedCount} card${reviewedCount !== 1 ? 's' : ''} reviewed${reviewedCount ? ` · ~${acc}% recalled` : ''}.`),
      el('div', { class: 'row', style: { justifyContent: 'center', marginTop: '18px' } },
        el('button', { class: 'btn btn-primary', onClick: () => navigate('#/today') }, 'Back to Today'))));
  }

  // ---------- keyboard ----------
  function onKey(e) {
    if (stage._teachActive) return;  // the teach chat owns its own keys
    const editable = e.target.matches && e.target.matches('textarea:not([readonly]), input:not([readonly])');
    if (editable) {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); reveal(); }
      return;
    }
    if (e.key === 'Escape') { navigate('#/today'); return; }
    if (e.key.toLowerCase() === 's') { e.preventDefault(); skipCard(); return; }
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

// ---------- Feynman teach-back ----------
// The model plays a confused first-year; you explain. Wrapping up self-checks
// against the rubric and counts as a review of the topic's recall card.
function teachUI({ learningId, title, ideas = [], onDone, onSkip }) {
  const messages = [];
  const wrap = el('div', {});

  wrap.append(el('div', { class: 'q-card', style: { borderColor: 'var(--easy)' } },
    el('div', { class: 'src' }, `teach it · ${title}`),
    el('div', { class: 'q' }, 'This one’s solid, so teach it. ',
      el('span', { style: { color: 'var(--easy)' } }, `Explain “${title}” to a first-year.`)),
    el('div', { class: 'muted', style: { fontSize: '13px', marginTop: '8px' } },
      'I’ll play the student; I don’t know this topic yet.')));

  const log = el('div', { class: 'chat-log', style: { marginTop: '14px' } });
  const composer = el('textarea', { class: 'input', rows: '2', placeholder: 'Start wherever feels natural…' });
  const sendBtn = el('button', { class: 'btn btn-primary', onClick: send }, 'Send');
  const wrapBtn = el('button', { class: 'btn', onClick: wrapUp, disabled: true }, 'Wrap up & rate');
  const skipBtn = onSkip ? el('button', { class: 'btn btn-ghost', onClick: onSkip }, 'Normal recall instead') : null;
  const footer = el('div', { class: 'row', style: { gap: '8px', marginTop: '10px', justifyContent: 'flex-end' } },
    skipBtn, wrapBtn, sendBtn);
  wrap.append(el('div', { class: 'chat', style: { marginTop: '14px' } }, log, composer, footer));

  function addBubble(role, text = '') {
    const node = el('div', { class: 'msg ' + (role === 'user' ? 'user' : 'ai') }, text);
    log.append(node);
    node.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    return node;
  }
  addBubble('ai', 'Ready when you are.');

  composer.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
    e.stopPropagation();
  });

  async function send() {
    const text = composer.value.trim();
    if (!text || sendBtn.disabled) return;
    renderMathIn(addBubble('user', text));
    messages.push({ role: 'user', content: text });
    composer.value = '';
    wrapBtn.disabled = false;
    sendBtn.disabled = true;
    const bubble = addBubble('ai', '…');
    let reply = '';
    try {
      for await (const chunk of api.teachTurnStream(learningId, messages)) {
        reply += chunk;
        bubble.textContent = reply;
      }
      reply = reply.trim();
      if (reply) messages.push({ role: 'assistant', content: reply });
      else bubble.remove();
      renderMathIn(bubble);
    } catch {
      bubble.textContent = 'The student lost connection. Wrap up when ready.';
    }
    sendBtn.disabled = false;
    composer.focus();
  }

  function wrapUp() {
    composer.disabled = true; sendBtn.disabled = true; wrapBtn.disabled = true;
    const panel = el('div', { class: 'card', style: { marginTop: '14px', padding: '16px' } });
    if (ideas.length) {
      panel.append(el('div', { class: 'eyebrow', style: { marginBottom: '10px' } }, 'Self-check: did your explanation cover these?'));
      for (const i of ideas) {
        panel.append(el('div', { class: 'idea neutral' }, el('span', { class: 'mark' }, '·'), el('div', { class: 't' }, i.text)));
      }
      renderMathIn(panel);
    }
    const rates = [['again', 'Struggled', 1], ['hard', 'Shaky', 2], ['good', 'Taught it', 3], ['easy', 'Crystal', 4]];
    const grid = el('div', { class: 'rate-grid' },
      ...rates.map(([cls, label, r]) => el('button', { class: 'rate-btn ' + cls, onClick: () => finishWith(r) },
        el('span', { class: 'name ' + cls }, label))));
    panel.append(el('div', { class: 'muted center', style: { fontSize: '12.5px', margin: '12px 0 4px' } },
      'How did teaching it feel? This schedules the topic like a normal review.'), grid);
    wrap.append(panel);
    panel.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }

  async function finishWith(rating) {
    try {
      await api.teachFinish({ learning_id: learningId, messages, rating });
      toast('Teach-back saved to the topic’s reflection.');
    } catch (e) { toast('Could not save: ' + e.message); }
    onDone();
  }

  return wrap;
}
