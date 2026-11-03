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
  'No bars for this generation yet: the model cards could not be opened when this guide '
  + 'was updated (Nov 2026), so no score here is verified. Figures in the notes are the '
  + 'cards\' own numbers as quoted by secondary sources. Vendors run their own harnesses, '
  + 'and these benchmarks measure problem-solving, not grading recall.';

export const MODEL_GUIDE = [
  {
    id: 'qwen3.5:9b', group: 'Local · main model', badge: 'default · 8–12 GB',
    why: 'Qwen\'s newest small dense model (March 2026). About 6.6 GB, so it fits an 8 GB '
      + 'GPU entirely. On 8 GB leave the fast model empty: one model stays loaded and '
      + 'nothing reloads between writing cards and grading them.',
    note: 'Model card GPQA-Diamond 81.7 (quoted second-hand). Check ollama ps shows 100% GPU.',
  },
  {
    id: 'qwen3.5:4b', group: 'Local · main model', badge: '6–8 GB',
    why: 'About 3.4 GB. Use it when the 9B spills onto the CPU (ollama ps shows a CPU/GPU '
      + 'split), or pair it with a 0.8B fast model so both stay loaded.',
    note: 'Model card GPQA-Diamond 76.2 (quoted second-hand).',
  },
  {
    id: 'gemma4:26b', group: 'Local · main model', badge: '16 GB',
    why: 'Google\'s mixture-of-experts Gemma 4 (April 2026): ~26B of knowledge, ~4B active '
      + 'per token, so big-model depth at small-model speed. Reads images too.',
    note: 'Model card GPQA-Diamond 82.3 (quoted second-hand). Confirm the tag with ollama pull.',
  },
  {
    id: 'qwen3.8:27b', group: 'Local · main model', badge: '24 GB+',
    why: 'Qwen\'s strongest open model that fits one GPU (August 2026). Dense, about 17–18 GB '
      + 'at 4-bit, so it needs a 24 GB card with room for context.',
    note: 'Model card GPQA-Diamond 89.2 (quoted second-hand). Confirm the tag with ollama pull.',
  },
  {
    id: 'same as main (leave empty)', group: 'Local · fast model', badge: '8 GB GPUs',
    why: 'Ollama keeps two models loaded only if both fit in VRAM; otherwise every switch '
      + 'reloads one. On an 8 GB card a separate fast model makes reviews slower, not faster.',
    note: 'The app already turns reasoning off for grading, so the main model judges quickly.',
  },
  {
    id: 'qwen3.5:0.8b / qwen3.5:2b', group: 'Local · fast model', badge: 'grading · focus',
    why: 'A tiny judge that can stay loaded beside the main model: with a 4B main on 8 GB, '
      + 'or anything on 12 GB+. It only grades and files; it never writes your cards.',
    note: 'Grading is meaning-matching, not problem-solving; smaller models do it well enough.',
  },
  {
    id: 'nomic-embed-text', group: 'Local · embeddings', badge: 'connections',
    why: 'Embeddings only: related concepts, contrast-pair detection, semantic search, '
      + 'duplicate warnings. Nothing generative, nothing graded.',
    note: 'Keep it for now: switching embed models needs a re-embed the app does not yet do automatically.',
  },
  {
    id: 'gemini-3.5-flash', group: 'Cloud · opt-in assist', badge: 'default',
    why: 'The per-click assist default, and Google\'s named successor to 2.5 Flash. The '
      + 'dropdown lists whatever Google offers your key right now, so retired models drop off.',
    note: 'No bar: per-model scores weren\'t verifiable offline when this guide was updated. '
      + 'Free tier: Google may use what you send to improve its products.',
  },
  {
    id: 'gemini-3.5-flash-lite', group: 'Cloud · opt-in assist', badge: 'fastest',
    why: 'Cheapest and fastest: fine for copy-editing a card, weaker at deriving one.',
    note: 'Flash-Lite tiers trade reasoning depth for speed; pick Flash for derivations.',
  },
];
