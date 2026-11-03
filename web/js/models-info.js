// The model guide shown in Settings: one entry per decision, short.
//
// Honesty rules for this file: a benchmark bar (`bench`) only for a score
// checked against the model's own published card or report, cited in `src`.
// Unverified figures don't go here at all. The footnote below only renders
// when some entry has a bar.

export const BENCH_COLS = [
  { key: 'gpqa', label: 'GPQA-Diamond', hint: 'PhD-level science questions' },
  { key: 'aime', label: 'AIME', hint: 'competition math' },
];

export const BENCH_NOTE =
  'Published scores only, from each model\'s own card. Vendors run their own harnesses, '
  + 'so compare loosely; these benchmarks measure problem-solving, not grading recall.';

export const MODEL_GUIDE = [
  {
    id: 'qwen3.5:9b', group: 'Local', badge: 'default · 8–12 GB',
    why: 'Writes cards and grades recall. About 6.6 GB, so it fits an 8 GB GPU entirely. '
      + 'Leave the fast model empty: one model stays loaded, so nothing reloads mid-review.',
    note: 'After a review, “ollama ps” should say 100% GPU.',
  },
  {
    id: 'qwen3.5:4b', group: 'Local', badge: 'under 8 GB',
    why: 'Use instead if the 9B spills onto the CPU (“ollama ps” shows a CPU/GPU split). '
      + 'Expect shallower cards and follow-up questions.',
  },
  {
    id: 'gemma4:26b', group: 'Local', badge: '16 GB+',
    why: 'For a bigger GPU: mixture-of-experts, ~4B active per token, so more depth at '
      + 'similar speed. On 24 GB+, qwen3.8:27b goes further. With either, a small fast '
      + 'model (qwen3.5:2b) can stay loaded alongside.',
  },
  {
    id: 'nomic-embed-text', group: 'Local', badge: 'connections',
    why: 'Embeddings only: related concepts, contrast pairs, semantic search, duplicate warnings.',
  },
  {
    id: 'gemini-3.5-flash', group: 'Cloud · opt-in', badge: 'default',
    why: 'Per-click card rewrites when cloud assist is on. The dropdown lists what Google '
      + 'offers your key right now, so retired models drop off. Free tier: Google may use '
      + 'what you send to improve its products.',
  },
];
