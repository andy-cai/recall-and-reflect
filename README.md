# Recall & Reflect

A local-first spaced-repetition app built around two ideas from learning science:

- **Reflect** — capturing should make *you* think. Instead of a form, you talk to it.
  You dump what you learned and it asks a couple of sharp follow-ups
  (*why is that true? give me an example? how's it different from X?*) before turning
  the conversation into review cards. Generating your own explanations is what makes
  things stick (the *generation effect* + *elaborative interrogation*).
- **Recall** — reviewing should cost a little effort. You try to recall *before* you
  see the answer, rate your confidence, and a local AI gently grades you and pokes at
  the gaps. Effortful retrieval ("desirable difficulty") beats passive flip-and-rate —
  but there's always a hint ladder, and a miss is never punished.

Scheduling uses **FSRS** (the modern successor to SM-2), so reviews land right around
the edge of forgetting.

## Privacy

Everything runs on your machine by default. The app binds to `127.0.0.1` only, stores
data in a local SQLite file under `data/` (git-ignored), and routine operation talks
only to a **local** [Ollama](https://ollama.com) instance — Ollama cloud-proxy model
tags are blocked.

One explicit exception: **cloud assist** (off by default). If you set
`GEMINI_API_KEY` (free key at [aistudio.google.com](https://aistudio.google.com)) and
flip the toggle in Settings, an "Improve with Gemini" button appears on cards. It sends
only that single card's text, only when you click it. Reviews, capture chat, grading,
and embeddings never touch the cloud regardless.

## Local models

| VRAM | Main model | Fast model (grading) |
|------|------------|----------------------|
| 24 GB+ | `qwen3:30b-a3b` (MoE — fast and sharp) | `qwen3:4b` |
| 12–16 GB | `qwen3:14b` (default) or `phi4:14b` (strong STEM) | `qwen3:4b` |
| 8 GB | `qwen3:8b` or `qwen2.5:7b` | `qwen2.5:3b` |

Reasoning models work too — `<think>` blocks are stripped automatically (at some
latency cost). Pick models in Settings; the app falls back to whatever is installed.

## Quick start

```bat
:: 1. Install Ollama and pull the local model (one time)
ollama pull qwen2.5:7b

:: 2. Launch — first run creates a venv and installs deps
run.bat
```

Then it opens at <http://127.0.0.1:8765>. Without Ollama running the app still works —
you just write cards manually and self-grade reviews.

## How it works

| Stage | What happens |
|-------|--------------|
| **Reflect** | Free-flow chat → 2–3 generative follow-ups (skippable) → the AI distills editable **key ideas** (the rubric your recall is graded against) + optional detail questions → save. |
| **Recall** | Free recall (type it) → confidence → AI grades **per key idea** (✓/◐/✕ checklist) + one Socratic poke → rate (1–4, with the verdict-consistent rating pre-highlighted — `Enter` takes it). Confident misses return at the end of the session and a bit sooner next time (hypercorrection). An idea missed twice in a row earns its own drill card. |
| **Organize** | Each note gets a **Subject** (its home area). The Library's *Explore* view groups concepts by subject, and the local AI can suggest subjects for an uncategorized backlog (you approve). |
| **Focus** | Prioritize what matters now: star topics in the Library, focus a whole subject, or just tell Today *“vibrations final next week”* — the local model matches it to your real topics (you confirm). Focused topics jump every queue and claim the new-card budget first. |
| **Rhythm** | Come back after days away to a **welcome-back ramp** (spread the pile over N days, keep today's most-at-risk). Evenings offer a small **wind-down session** — today's misses and new captures, timed for sleep consolidation. |
| **Connect** | With a local embed model (`ollama pull nomic-embed-text`), topics link up: **related concepts** in the Library, one-click **contrast cards** for confusables (Tresca vs. von Mises), **connection chips** while you capture, semantic search, and duplicate warnings on bulk add. |
| **Teach** | Topics that are solid (stability ≥ 3 weeks) occasionally swap a review for a **teach-back**: explain it simply while the local AI plays a confused first-year. Also on-demand (🎓 in the Library). The transcript joins the topic's reflection; rating counts as a review. |
| **People** | A photo-free person card: the story is the cue ("battery bay, tin-whisker short — who?"), the reveal is the name plus the vivid association *you* invented. Capture takes ~20 seconds (Reflect → Person). |
| **Calibrate** | Stats shows whether your *Certain* actually means certain (confidence × AI-verdict accuracy), and names the subject where you're most overconfident. |
| **Schedule** | FSRS-4.5 sets each card's next review to hit your target retention (default 90%). The queue is shaped: most-at-risk first, one card per topic per session (remaining siblings are buried to tomorrow), new cards throttled by a per-day cap. |

## Starter curriculum

`seeds/` ships curated decks (mechanical engineering core, battery engineering,
internship topics — ~95 topics, ~185 cards with key-idea rubrics, task-style recall
prompts, and contrast cards for confusables). Import any time; re-runs skip what exists:

```bat
python tools\seed_curriculum.py
```

New topics ease into review at your new-per-day cap; focus a subject on Today to pull
its topics forward. Edit or add decks as JSON in `seeds/`.

## Math

Card text supports `$...$` / `$$...$$` TeX. To render it offline, vendor KaTeX once
(needs internet for the download; never a CDN at runtime):

```bat
python tools\get_katex.py
```

Without it, math falls back to readable styled source.

## Performance

Review grading is the latency-sensitive path. Two knobs:

- **Fast model** (Settings): pull a small model (`ollama pull qwen2.5:3b`) and select it
  as the fast model — it handles grading and focus-matching; capture quality stays on
  the main model.
- Every LLM call is token-capped (`num_predict`) so a rambling generation can't stall a
  review. The model is kept warm (`keep_alive 30m`) and warmed at startup.

## Desktop shortcut

```bat
powershell -ExecutionPolicy Bypass -File tools\make_shortcut.ps1
```

puts a "Recall & Reflect" icon on your Desktop that launches the app (server console
starts minimized). Alternatively, with the app open in Edge/Chrome use
*menu → Apps → Install Recall & Reflect* — you get a standalone window with the app
icon, no browser chrome. Icons are generated from one design by `tools/gen_icons.py`.

## Tests

```bat
python -m unittest discover tests
```

## Stack

- **Backend:** Python + FastAPI + SQLite. Ports the FSRS-4.5 engine.
- **Frontend:** plain HTML/CSS/ES-modules — no build step, runs offline.
- **AI:** local Ollama (`qwen2.5:7b` by default). Optional, with graceful fallback.

## Keyboard

Review is keyboard-first: `Space` reveal · `1`/`2`/`3`/`4` rate (`Enter` takes the AI
suggestion) · `H` hint · `S` skip without rating · `Z` undo. Every card has quiet
**✎ Edit / Skip** actions — fix a bad question inline, give feedback for an AI
rewrite, punt it to tomorrow, or suspend it, without leaving the session.

## License

MIT — personal learning tool.
