// The model guide shown in Settings: why each recommended model is on the
// list, with published benchmark scores where they exist.
//
// Honesty rules for this file: every number comes from the model's own
// published card or technical report (cited per entry); reasoning models are
// thinking-mode scores. Where a per-size score wasn't published (or we
// couldn't verify it), there is no bar — a range or a note, never a guess.
// Different harnesses ran these, so compare within a column, loosely.

export const BENCH_COLS = [
  { key: 'gpqa', label: 'GPQA-Diamond', hint: 'PhD-level science questions' },
  { key: 'aime', label: "AIME'25", hint: 'competition math, 2025 set' },
];

export const BENCH_NOTE =
  'Published scores only: Qwen3 blog and technical report (thinking mode), the '
  + 'Phi-4 technical report, and Google\'s Gemini 2.5 model cards. Each family ran '
  + 'its own harness, so compare within a column, loosely. Where a per-size score '
  + 'was never published, you see a range or a note instead of an invented number.';

export const MODEL_GUIDE = [
  {
    id: 'qwen3:14b', group: 'Local · main model', badge: 'default · 12–16 GB',
    why: 'The best all-round technical Q&A at this size. It can reason when generating '
      + 'cards and rubrics; the app switches reasoning off for grading so reviews stay quick.',
    range: { lo: 'qwen3:4b', hi: 'qwen3:30b-a3b' },
    note: 'Per-size scores live in the Qwen3 technical report; on every published table it lands between its 4B and 30B-A3B siblings shown here.',
  },
  {
    id: 'qwen3:30b-a3b', group: 'Local · main model', badge: '24 GB+',
    bench: { gpqa: 65.8, aime: 70.9 },
    why: 'Mixture-of-experts: 30B of knowledge with only ~3B active per token; the most '
      + 'quality per second you can run on a big GPU.',
    src: 'Qwen3 release table, thinking mode (AIME\'24: 80.4)',
  },
  {
    id: 'phi4:14b', group: 'Local · main model', badge: 'STEM alternative',
    bench: { gpqa: 56.1 },
    why: 'Microsoft\'s dense 14B trained hard on STEM; strong derivations and definitions '
      + 'with no reasoning tokens at all, so every call is fast.',
    src: 'Phi-4 technical report (MATH: 80.4, MMLU: 84.8); AIME not published',
  },
  {
    id: 'qwen3:8b / qwen2.5:7b', group: 'Local · main model', badge: '8 GB tier',
    why: 'The same ladders, one rung down: what to run when VRAM is tight. Expect competent '
      + 'cards and grading, less depth in follow-up questions.',
    note: 'Per-size scores in the Qwen3 / Qwen2.5 reports; both sit below the bars above.',
  },
  {
    id: 'qwen3:4b', group: 'Local · fast model', badge: 'grading · focus',
    bench: { aime: 65.6 },
    why: 'The recommended judge: grades your recall and files subjects at chat speed. The app '
      + 'turns its reasoning off for those calls; with it on, this 4B does competition math '
      + 'most 70B models can\'t.',
    src: 'Qwen3 release table, thinking mode (AIME\'24: 73.8); GPQA per-size not republished here',
  },
  {
    id: 'qwen2.5:3b', group: 'Local · fast model', badge: 'smallest judge',
    why: 'No reasoning to switch off, nothing to truncate: verdicts in a beat on any GPU. '
      + 'It only ever judges and files; it never writes your cards.',
    note: 'Too small for the reasoning benchmarks above; that\'s fine, grading is meaning-matching, not problem-solving.',
  },
  {
    id: 'nomic-embed-text', group: 'Local · embeddings', badge: 'connections',
    why: 'Embeddings only: related concepts, contrast-pair detection, semantic search, '
      + 'duplicate warnings. Nothing generative, nothing graded.',
  },
  {
    id: 'gemini-2.5-flash', group: 'Cloud · opt-in assist', badge: 'default',
    bench: { gpqa: 82.8, aime: 72.0 },
    why: 'The per-click assist default: near-Pro reasoning at free-tier-friendly speed for '
      + 'card rewrites and engineering-mode Reflect questions.',
    src: 'Gemini 2.5 Flash model card, thinking',
  },
  {
    id: 'gemini-2.5-pro', group: 'Cloud · opt-in assist', badge: 'deliberate',
    bench: { gpqa: 86.4, aime: 88.0 },
    why: 'For the rewrite that really matters. Slower and rate-limited harder on the free tier.',
    src: 'Gemini 2.5 Pro model card, thinking',
  },
  {
    id: 'gemini-2.5-flash-lite', group: 'Cloud · opt-in assist', badge: 'fastest',
    bench: { gpqa: 66.7, aime: 63.1 },
    why: 'Cheapest and fastest, and it shows on hard reasoning: fine for copy-editing a card, '
      + 'not for deriving one.',
    src: 'Gemini 2.5 Flash-Lite model card, thinking',
  },
];
