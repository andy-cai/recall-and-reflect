# Improvement Proposal — Recall & Reflect

Goal of this review: maximize **retention** and **habit formation**, for two very different
kinds of material — (a) people, names, and stories, and (b) dense technical content
(equations, diagrams, derivations, procedures: Mohr's circle, TTT diagrams, FSRS-grade
math everywhere). Every proposal below is tied to a specific finding in the codebase and
to specific learning-science results, ordered by leverage.

---

## 0. What already works (keep it)

The core loop is built on the right science and the DESIGN.md shows real intent:

- Free recall before reveal (retrieval practice: Roediger & Karpicke 2006; free recall >
  cued recall > recognition: Karpicke & Blunt 2011).
- Generation-first capture (generation effect, elaborative interrogation — Dunlosky et al. 2013).
- FSRS scheduling, hint ladder as scaffolded desirable difficulty (Bjork), forgiving
  streak with one-day grace, local-first privacy, keyboard-first review.

The proposals below are about (1) correctness of the engine, (2) making the knowledge
representation match the material, and (3) moving the habit loop to where habits live.

---

## 1. Fix the engine first (correctness > features)

### 1.1 The FSRS port mixes algorithm versions — replace it with `py-fsrs`

`app/core/fsrs.py` advertises FSRS-4.5, but:

- `_retrievability()` and `_next_interval()` implement the **FSRS v4** forgetting curve
  `R = (1 + t/(9S))^-1`. FSRS-4.5's defining change was the curve
  `R = (1 + (19/81)·t/S)^-0.5`. Both are anchored so that `interval = S` at R = 0.90,
  but they diverge everywhere else — i.e., for any `desired_retention ≠ 0.90` (the app
  exposes 70–97% in Settings) and for every retrievability estimate used in the
  stability update at review time.
- The bundled `DEFAULT_WEIGHTS` do not match the published FSRS-4.5 defaults (they are
  closest to FSRS-5-family weights, truncated to 17). Weights are fitted *to a specific
  curve*; pairing one version's weights with another version's curve mis-schedules
  systematically.
- Learning/relearning steps are hardcoded (10 m / 30 m / 1 d). FSRS-5+ models short-term
  (same-day) memory natively.

**Proposal:** delete the hand port and depend on the maintained
[`py-fsrs`](https://github.com/open-spaced-repetition/py-fsrs) package (FSRS-6).
Then add the milestone the DESIGN.md already anticipates: once ~1,000 reviews exist,
run the FSRS optimizer on the user's own review log (the `reviews` table already stores
everything needed: rating, before/after state, elapsed time) and fit personal weights.
Personalized parameters are FSRS's main advantage over SM-2 — leaving them default
forfeits most of it.

Add a golden-vector test suite against the reference implementation so the scheduler can
never silently drift again (there are currently **zero tests** in the repo).

### 1.2 Use the metacognitive signals you already collect

The review flow collects `confidence` (1–3) and `ai_verdict` per review and stores them —
then never uses either for anything. This is the single cheapest retention win available:

- **Hypercorrection rescheduling.** High-confidence errors are *more* correctable than
  low-confidence errors (Butterfield & Metcalfe 2001; Metcalfe 2017), but the correction
  decays — it needs a follow-up. Today the UI shows a one-line note ("You were certain —
  worth a closer look") and does nothing. Instead: confidence = Certain + verdict = wrong
  → re-queue the card *within the same session* (end of queue) and shorten the next
  interval (e.g., schedule against a temporarily higher target retention for that card).
- **Suggested rating.** Self-grading drifts and learners are systematically overconfident
  (Dunlosky & Rawson 2012 — overconfident self-judgments directly depress learning).
  When the AI verdict exists, pre-highlight the consistent rating
  (correct+Certain → Good/Easy; partial → Hard; wrong → Again) so the honest answer is
  the zero-keystroke default. Keep the override — but log disagreement.
- **Calibration feedback.** Add one Stats panel: "When you said *Certain*, you were right
  X% of the time" (confidence × verdict matrix). Improving metacognitive calibration is
  itself a learning intervention — miscalibrated learners under-study what they
  most need.

### 1.3 Interleave the queue and bury siblings

`get_due_questions()` orders strictly by `next_review_at` — cards created together come
due together, so reviews arrive **blocked by topic**, and sibling cards (e.g., the 4
detail questions of one topic, or cloze deletions from the same sentence) run
back-to-back, where the first card's answer primes the rest.

Interleaving related-but-different material improves discrimination and long-term
retention versus blocking, even though it *feels* worse (Rohrer & Taylor 2007;
Birnbaum et al. 2013) — and confusable engineering concepts (Tresca vs. von Mises,
CC vs. CV charging, Soderberg vs. Goodman) are exactly the case it helps most.

**Proposal:**
- Within the due set, order to maximize subject/learning alternation (simple greedy:
  never two cards from the same learning adjacently when avoidable).
- **Bury siblings:** after reviewing one card of a learning, push that learning's other
  due cards to tomorrow (Anki-style). This both de-primes and naturally interleaves.
- Later (see §3.6): use embeddings to interleave by *semantic* distance, and to build
  deliberate contrast cards for near-neighbor concepts.

### 1.4 Backlog policy — protect the habit from the pile

There is no daily cap, no new-card/day limit (outside bulk add's ease-in), and no
overdue triage. The failure mode is predictable: miss four days, return to 240 due,
feel defeated, churn. Lapse-recovery is where habit apps die; in habit-formation data,
missing single days doesn't hurt habit growth — *quitting after the miss does*
(Lally et al. 2010).

**Proposal:**
- Global `new_per_day` limit (the bulk-add `per_day` mechanism generalized to all
  card creation).
- Session cap = daily target; when due > cap, select by **relative overdueness**
  (elapsed/interval) so the most-at-risk memories go first, and *say so*:
  "82 due — here are today's 20 most at risk."
- **Welcome-back mode:** after ≥3 inactive days, offer an explicit ramp
  (auto-split the backlog over N days like bulk-add already does) instead of a wall.
  One screen, one button, no guilt.

---

## 2. Represent knowledge the way it's actually shaped

The user's corpus is equations, diagrams, processes, derivations — and people. Today the
only representations are plain-text Q/A, cloze, and whole-topic free recall. This is the
biggest gap between the app and its stated mission.

### 2.1 Math rendering (table stakes)

`σ = My/I`, `K_I = βσ√(πa)`, `R = (1+19/81·t/S)^-0.5` … the content is saturated with
notation, and the app renders raw text. Vendor **KaTeX** locally (no CDN — keeps the
local-only promise; no build step needed, it's a JS+CSS drop-in) and render `$...$` in
card fronts/backs, topic content, and the capture chat. Without this, technical cards
are strictly worse than a paper notebook.

### 2.2 Key-idea rubrics → make topic recall schedulable

The default "recall everything about: X" card is the app's best idea and its weakest
implementation: the *answer* is the entire content blob, the AI grades against the blob,
hints (`hintFor`) degenerate to "412 words, starts with 'T'", and FSRS gets one noisy
binary signal for a memory that is actually 8 separate ideas.

**Proposal — rubric-based topic recall (this is the flagship architecture change):**

1. At capture, the LLM (or the user) distills the topic into 3–8 **key ideas**
   (one-liners). Stored as rows, not a blob.
2. At review, free recall works as today, but grading returns a per-idea checklist:
   recalled / partial / missed. The reveal shows the rubric, not the wall of text.
3. Each key idea carries its own FSRS state. Consistently-missed ideas surface as their
   own drill cards; consistently-recalled ones stop inflating the reveal.
4. "Hint" becomes meaningful: reveal one rubric line as a cue.

This implements **successive relearning** (Rawson & Dunlosky 2011: spaced retrieval *to
criterion per idea* produced some of the largest classroom retention effects on record)
and turns the AI grade from a vibe into a measurement. Schema change: a `key_ideas`
table (learning_id, text, fsrs state columns), grading schema extended from
`verdict/missing/poke` to a per-idea list.

### 2.3 New card types (dual coding, drawing, discrimination)

Add `card_type` variants — the schema already has the column:

- **Image cards + image occlusion.** Store an image, draw occlusion rectangles, each
  occlusion = one card (Anki's most-loved add-on for exactly this kind of content:
  TTT diagrams, Mohr's circle, FCC/BCC cells, shear-moment diagrams). Dual coding —
  verbal + visual traces are additive (Paivio; Mayer's multimedia work). Local-first:
  images go in `data/media/`, served by FastAPI.
- **Sketch-to-recall.** For diagram cards, the recall box becomes a small canvas:
  *draw* the Mohr's circle / the TTT diagram before reveal, then visually compare.
  Drawing beats writing for memory even with seconds of drawing and zero skill
  (Wammes, Meade & Fernandes 2016 — the "drawing effect"). No AI grading needed;
  self-compare + rate is enough.
- **Derivation/procedure cards.** Ordered-steps type: prompt = "derive ε = αΔT case 3" /
  "walk the injection-molding defect diagnosis"; reveal steps one at a time
  ("what comes next?" — anticipation at each step is retrieval, not recognition).
- **Contrast cards.** Two confusables on one card: "Tresca vs. von Mises — when do they
  disagree, and which is conservative?" Generated deliberately for near-neighbors
  (see §3.6). Discrimination training is the interleaving effect, weaponized.

### 2.4 People cards (names, faces, stories)

Nothing in the app supports the conversational-memory goal. Add a lightweight **Person**
type — and note the foundational expanding-retrieval study (Landauer & Bjork 1978) was
literally face–name learning:

- Fields: name, optional photo, where met, story hook, **vivid association** (the
  user's own technique: visual link between name and a physical feature), details
  (partner, project, follow-ups).
- Capture flow prompts the *user* to invent the association ("What does *Marek* rhyme
  with? Tie it to the beard.") — imagery mnemonics work when self-generated
  (face–name mnemonic literature: McCarty 1980), and the generation must be the
  learner's (same generation-effect principle the app is built on).
- Review: photo or context shown → recall name + one fact. Scheduled by the same FSRS
  engine; "people" becomes a subject you can deliberately interleave into sessions.

### 2.5 Memory palace as an opt-in scaffold for ordered material

Don't build a 3D gimmick. Offer a **loci list**: a user-defined sequence of familiar
places (text, optionally a photo each), and the ability to pin an ordered set of items
(phases of steel; the 7 additive-manufacturing families; a derivation's steps) to a
palace. Review = walk the sequence, recall each station. The method of loci produces
durable, months-later gains in controlled trials (Wagner et al. 2021, *Science
Advances*; Maguire et al. 2003 on expert mnemonists). It's a table (`palaces`,
`loci`, `locus_assignments`) and one review mode — small build, real technique.

### 2.6 Feynman mode (teach it back)

Periodically (e.g., when a topic's stability passes a threshold, or on demand), replace
the standard review with **"Teach it"**: "Explain X so a first-year could follow.
I'll play the confused student." The local model asks naive why/how questions
(neuroplastic questioning — exactly the user's "how, why, ___" habit) and flags jargon
used without definition. Self-explanation and teaching-expectancy effects are
well-documented (Chi et al. 1994; Fiorella & Mayer 2013 — *expecting* to teach improves
learning even before any teaching happens). The transcript appends to the topic's
reflection; gaps the "student" exposed become rubric ideas (§2.2). This is the Reflect
chat's existing machinery pointed at review instead of capture — high value, low new code.

---

## 3. Habit architecture — meet the habit where it lives

### 3.1 The phone problem (deferred — decision June 2026: stay Windows-local for now)

The app is `127.0.0.1`-only with **Windows-only** toast reminders. Habits form around
stable contextual cues (Wood & Neal 2007), and the most available cue surface — the
phone, the bed, the bus — can't reach a localhost desktop app. A daily-review habit
that requires sitting at a particular desk is fragile by construction.

**Proposal (keeps local-first intact):**
1. Make the web app a **PWA**: manifest + service worker + responsive layout
   (the SPA is already framework-free; review and capture screens need a one-column
   mobile pass). Installable, offline-capable shell.
2. **Web Push** from the FastAPI server replaces/augments winotify — works on any OS
   and on mobile browsers, still entirely self-hosted.
3. Document the **Tailscale pattern** (or `--host` flag + auth token) so the phone
   reaches the home machine securely without any cloud. The LLM stays on the desktop;
   review works from anywhere on the tailnet.
4. Later, if ever needed: file-level sync of the SQLite DB is the escape hatch —
   the architecture (single file, single user) was chosen well for this.

This is the highest-impact habit change in the document. Everything in §3.2–3.6
multiplies off it.

### 3.2 Implementation intentions, not just reminders

Reminders fire by clock; habits anchor to events. At onboarding (and in Settings), ask
the user to complete one sentence: *"After I ___, I will do my review"* (after morning
coffee / after lunch / when I get on the train). Then phrase notifications against the
anchor and the planned time window. Implementation intentions show medium-to-large
effects on goal attainment across hundreds of studies (Gollwitzer & Sheeran 2006,
meta-analysis d ≈ 0.65). One text field, one sentence of copy — disproportionate payoff.

### 3.3 Micro-sessions: drop the activation energy to 3 cards

The Today screen offers one action sized "all due reviews." Add a permanent second
button: **"Just 3"** — three cards, most at-risk first, ~60 seconds. Tiny entry points
exploit the fact that starting is the expensive part; sessions frequently continue past
the minimum (goal-gradient behavior), and on bad days, 3 > 0 — which is what keeps the
consistency signal (and the habit) alive. The session-complete screen offers
"+3 more?" instead of only "Back to Today."

### 3.4 A bedtime session (sleep consolidation)

The user explicitly practices before-bed review; the science backs it: practicing close
to sleep, with sleep following, improves retention and halves later relearning effort
(Mazza et al. 2016; Gais, Lucas & Born 2006). Add an optional **evening wind-down
session**: user sets a bedtime window; the app schedules a small (5–10 card) session
biased toward (a) today's *misses* and (b) new material from today's Reflects;
notification copy is calm ("5 things worth sleeping on"). Dark theme already exists;
auto-switch for this session.

### 3.5 Make the invisible payoff visible

The deep problem with SRS motivation: the reward (not forgetting in 3 months) is
invisible today. Surface it:

- On rating, show the **retrievability save**: "This memory was at ~64% — review
  brought it back to ~100% and pushed the next dip 18 days out." One line, computed
  from FSRS state you already have.
- Session summary: "You rescued N fading memories; M are now stable past a month."
- Stats: per-subject retention and a **knowledge half-life** trend (median stability),
  which rises over weeks — a number that visibly grows is a retention curve the user
  can *feel*.
- Keep the consistency metric as the headline (it's the scientifically honest one);
  demote the streak to secondary. Add a weekly Monday recap ("fresh start effect" —
  temporal landmarks boost re-engagement: Dai, Milkman & Riis 2014).
- Count **Reflect sessions toward the day's activity** — `reviews_by_day` only counts
  reviews, so capturing five topics still shows a dead heatmap day. Reward showing up
  in either mode; the habit is "engage with memory," not "press 1–4."

### 3.6 Use the embeddings you already configured

`config.py` defines `EMBED_MODEL = "nomic-embed-text"` — never referenced anywhere else.
Embed every learning/card locally (Ollama embeddings endpoint, still on-device) and get,
cheaply:

- **Stretch connections** at capture: "This smells related to *Hall-Petch* and *Luder's
  bands* — how does it connect?" (the user's own technique; elaboration through
  connection is the self-explanation effect with a retrieval cue attached).
- **Near-duplicate detection** on save (bulk-add will create overlapping topics).
- **Semantic interleaving** (§1.3) and automatic **contrast-card candidates** (§2.3):
  nearest neighbors that are *not* duplicates are exactly the confusables worth a
  discrimination card.
- Library semantic search (current search is `LIKE %…%`).

One new table (`embeddings`), one service module, no privacy change.

---

## 4. Engineering hygiene (enables all of the above)

- **Tests, starting with the scheduler.** Golden vectors against reference FSRS, plus
  repository round-trips and grading fallbacks. The FSRS version mix (§1.1) is exactly
  the class of bug a 20-line vector test catches.
- **N+1 queries:** `_learning()` fetches tags per row; the review queue fetches each
  title individually; each `Database` op opens a fresh connection. Single-user SQLite
  forgives this, but the Library at 1,000 topics won't. Joins + one shared connection.
- **Migrations:** the additive `PRAGMA table_info` approach is fine now; §2.2's schema
  (key ideas, media, people, palaces, embeddings) justifies a tiny versioned-migration
  table before the schema grows.
- **Undo** pops the globally-last review — harmless single-user, but scope it to the
  session to avoid surprises.

---

## 5. Suggested order of attack

### Design decisions (June 2026, from `docs/mockups/prompt-ui.html`)

- Topic-recall reveal: **1A Checklist** — recall on top, vertical ✓/◐/✕ key-idea list.
- Rating: **2A Suggested glow** — 4-button grid kept; verdict-consistent button glows,
  `Enter` takes the suggestion, Easy is never auto-suggested.
- Capture: **3A Chat + live rubric** — Socratic chat with an editable key-ideas panel
  that fills as you talk (stretch-connection chips arrive with the embeddings layer).
- Today: **6B At-risk list** — named memories with retrievability gauges,
  "Rescue these 3 first" + a *Just 3* floor.
- People cards: face-forward first card, story-forward as the optional second.
- Mobile/PWA: deferred — Windows-local for now.


**Now (correctness + leverage, ~days each):**
1. `py-fsrs` swap + scheduler tests (§1.1)
2. KaTeX rendering (§2.1)
3. Queue interleaving + sibling burying (§1.3)
4. Confidence/verdict → suggested rating + hypercorrection requeue (§1.2)
5. "Just 3" micro-session + Reflect counts toward activity (§3.3, §3.5)

**Next (the retention architecture):**
6. Key-idea rubrics for topic recall — flagship (§2.2)
7. Backlog triage + welcome-back ramp + new/day limit (§1.4)
8. Image cards + image occlusion (§2.3)
9. People cards (§2.4)
10. Bedtime session + implementation-intention onboarding (§3.4, §3.2)

**Later (depth):**
12. Embedding layer: connections, contrast cards, semantic search (§3.6)
13. Feynman teach-back mode (§2.6)
14. Sketch-to-recall canvas, derivation cards (§2.3)
15. Memory palace lists (§2.5)
16. FSRS personal-weight optimizer at ~1k reviews; calibration panel (§1.1, §1.2)

### Key references

Roediger & Karpicke 2006 (testing effect) · Karpicke & Blunt 2011 (free recall) ·
Rawson & Dunlosky 2011 (successive relearning) · Rohrer & Taylor 2007, Birnbaum 2013
(interleaving) · Butterfield & Metcalfe 2001, Metcalfe 2017 (hypercorrection) ·
Dunlosky & Rawson 2012 (overconfidence harms learning) · Paivio (dual coding) ·
Wammes et al. 2016 (drawing effect) · Landauer & Bjork 1978 (expanding retrieval,
face–name) · Wagner et al. 2021 *Sci Adv*, Maguire et al. 2003 (method of loci) ·
Chi et al. 1994, Fiorella & Mayer 2013 (self-explanation, teaching expectancy) ·
Mazza et al. 2016, Gais et al. 2006 (sleep & relearning) · Lally et al. 2010 (habit
formation, missed days) · Gollwitzer & Sheeran 2006 (implementation intentions) ·
Dai, Milkman & Riis 2014 (fresh start) · Wood & Neal 2007 (context cues).
