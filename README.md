# Recall & Reflect

[![tests](https://github.com/andy-cai/recall-and-reflect/actions/workflows/tests.yml/badge.svg)](https://github.com/andy-cai/recall-and-reflect/actions/workflows/tests.yml)

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
the edge of forgetting. Runs on Windows, macOS and Linux — due-review toast reminders
are Windows-only, everything else is cross-platform.

## Quick start

Prerequisites: [Python](https://www.python.org) 3.9+. For the AI features, install
[Ollama](https://ollama.com) and pull a local model — `ollama pull qwen3:14b` for a
12 GB+ GPU, `ollama pull qwen3:8b` for 8 GB (see [Local models](#local-models); the
app uses whatever is installed).

**Windows** — first run creates a venv and installs deps:

```bat
run.bat
```

**macOS / Linux:**

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python run.py
```

The app opens at <http://127.0.0.1:8765>. Without Ollama running it still works — you
just write cards manually and self-grade reviews.

## What it feels like

Reflect is a conversation, not a form:

> **You:** learned why bolted joints barely feel the external load — the clamped
> members are a much stiffer spring than the bolt, so the bolt only sees a sliver of P
>
> **R&R:** What sets the size of that sliver physically — and what changes the
> moment the joint separates?
>
> **You:** C = kb/(kb+km), small because members ≫ bolt in stiffness. If it ever
> separates, the bolt takes the full alternating load → fatigue death
>
> **R&R:** Saved. Your rubric for future recall: bolt and members share load as
> springs in parallel — bolt sees only C·P while clamped — separation hands it
> everything — preload is the fatigue shield.

Days later, Recall flips it: you reproduce that from memory, the local AI checks your
recall against the rubric idea by idea (✓/◐/✕), pokes at what you missed, and FSRS
schedules the next encounter.

## Privacy

Everything runs on your machine by default. The app binds to `127.0.0.1` only, stores
data in a local SQLite file under `data/` (git-ignored), and routine operation talks
only to a **local** [Ollama](https://ollama.com) instance — Ollama cloud-proxy model
tags are blocked.

One explicit exception: **cloud assist** (off by default). Set `GEMINI_API_KEY` —
either in your shell environment or in a git-ignored `.env` file at the repo root
(copy `.env.example`; free key at [aistudio.google.com](https://aistudio.google.com)) —
and flip the toggle in Settings. You get an "Improve with Gemini" button on cards and a
per-session Private/Gemini switch in Reflect. Reviews, grading, and embeddings never
touch the cloud regardless.

Four guarantees around that exception:

- **People topics are refused** by every cloud path (server-side 403, no button).
- **Any topic can be marked Private** in the Library — same hard gate as People.
- **Saved People names are redacted** (`[name]`) from every outbound payload —
  best-effort, word-boundary; the hard gate above is the real wall.
- **Settings → "Sent to cloud"** lists every request that ever left the machine:
  when, what, which model, how many characters, how many names were redacted.

## Local models

| VRAM | Main model | Fast model (grading) |
|------|------------|----------------------|
| 24 GB+ | `qwen3:30b-a3b` (MoE — fast and sharp) | `qwen3:4b` |
| 12–16 GB | `qwen3:14b` (default) or `phi4:14b` (strong STEM) | `qwen3:4b` |
| 8 GB | `qwen3:8b` or `qwen2.5:7b` | `qwen2.5:3b` |

Reasoning models work well: thinking stays on for generation (cards, rubrics, drills)
and is switched off per-call for grading, focus-matching and filing, so reviews never
wait on a chain of thought. Pick models in Settings; the app falls back to whatever is
installed. Settings → "The models" explains each recommendation with published
benchmark scores, and "What the AI is asked" shows every system prompt verbatim.

## How it works

| Stage | What happens |
|-------|--------------|
| **Reflect** | Free-flow chat → 2–3 generative follow-ups (skippable) → the AI distills editable **key ideas** (the rubric your recall is graded against) + optional detail questions → save. |
| **Recall** | Free recall (type it) → confidence → AI grades **per key idea** (✓/◐/✕ checklist) + one Socratic poke → rate (1–4, with the verdict-consistent rating pre-highlighted — `Enter` takes it). Confident misses return at the end of the session and a bit sooner next time (hypercorrection). An idea missed twice in a row earns its own drill card. **Sketch tasks** ("Sketch the S-N curve…") are drawn on nearby paper; the reveal is a feature checklist (axes, shape, landmarks), and anything you type about your drawing gets the AI check. |
| **Organize** | Each note gets a **Subject** (its home area). The Library's *Explore* view groups concepts by subject, and the local AI can suggest subjects for an uncategorized backlog (you approve). |
| **Focus** | Prioritize what matters now: star topics in the Library, focus a whole subject, or just tell Today *"vibrations final next week"* — the local model matches it to your real topics (you confirm). Focused topics jump every queue and claim the new-card budget first. |
| **Rhythm** | Come back after days away to a **welcome-back ramp** (spread the pile over N days, keep today's most-at-risk). Evenings offer a small **wind-down session** — today's misses and new captures, timed for sleep consolidation. |
| **Connect** | With a local embed model (`ollama pull nomic-embed-text`), topics link up: **related concepts** in the Library, one-click **contrast cards** for confusables (Tresca vs. von Mises), **connection chips** while you capture, semantic search, and duplicate warnings on bulk add. |
| **Teach** | Topics that are solid (stability ≥ 3 weeks) occasionally swap a review for a **teach-back**: explain it simply while the local AI plays a confused first-year. Also on-demand (🎓 in the Library). The transcript joins the topic's reflection; rating counts as a review. |
| **People** | Photo-free person cards, two directions: the story cues the name ("battery bay, tin-whisker short. Who?") and the name cues where you left off — the before-the-meeting rehearsal. The reveal is the vivid association *you* invented. **No AI ever grades a person**: you judge whether the name came back. Reviews double as keeping up — add a dated "what's new" line, or rework the association after a miss. Never sent to any cloud. Capture takes ~20 seconds (Reflect → Person). |
| **Calibrate** | Stats shows whether your *Certain* actually means certain (confidence × AI-verdict accuracy), and names the subject where you're most overconfident. |
| **Schedule** | FSRS-4.5 sets each card's next review to hit your target retention (default 90%). The queue is shaped: most-at-risk first, one card per topic per session (remaining siblings are buried to tomorrow), new cards throttled by a per-day cap. |

## Starter curriculum

`seeds/` ships curated example decks (mechanical-engineering core plus battery & test
engineering — ~95 topics, ~185 cards with key-idea rubrics, task-style recall prompts,
sketch tasks, and contrast cards for confusables). Import any time; re-runs only add
what's new:

```bash
python tools/seed_curriculum.py            # --dry-run to preview
```

New topics ease into review at your new-per-day cap; focus a subject on Today to pull
its topics forward. Edit or add your own decks as JSON in `seeds/` — the format is
plain (see any existing file), and `tests/test_seeds.py` validates them.

## Math

Card text supports `$...$` / `$$...$$` TeX. To render it offline, vendor KaTeX once
(needs internet for the download; never a CDN at runtime):

```bash
python tools/get_katex.py
```

Without it, math falls back to readable styled source.

## Performance

Review grading is the latency-sensitive path. Two knobs:

- **Fast model** (Settings): pull a small model (`ollama pull qwen3:4b` or
  `qwen2.5:3b`) and select it as the fast model — it handles grading and
  focus-matching; capture quality stays on the main model.
- Grading and classification calls run with **model reasoning off** (`think: false`),
  so a reasoning model can't burn the whole token budget thinking and return nothing.
- Every LLM call is token-capped (`num_predict`) so a rambling generation can't stall a
  review; if a cap still truncates or empties a response, the call retries once
  uncapped. The model is kept warm (`keep_alive 30m`) and warmed at startup.

## Run it like an app

In Edge/Chrome use *menu → Apps → Install Recall & Reflect* — you get a standalone
window with the app icon, no browser chrome (any OS). On Windows there's also a
desktop shortcut that launches the server minimized and opens the app:

```bat
powershell -ExecutionPolicy Bypass -File tools\make_shortcut.ps1
```

Icons are generated from one design by `tools/gen_icons.py`.

## Tests

```bash
python -m unittest discover tests
```

CI runs the suite on Linux and Windows, Python 3.9 and 3.12.

## Stack

- **Backend:** Python + FastAPI + SQLite. Ports the FSRS-4.5 engine.
- **Frontend:** plain HTML/CSS/ES-modules — no build step, runs offline.
- **AI:** local Ollama — prefers `qwen3:14b`, falls back to any installed model.
  Optional, with graceful degradation.

## Keyboard

Review is keyboard-first: `Space` reveal · `1`/`2`/`3`/`4` rate (`Enter` takes the AI
suggestion) · `H` hint · `S` skip without rating · `Z` undo. Every card has quiet
**✎ Edit / Skip** actions — fix a bad question inline, give feedback for an AI
rewrite, punt it to tomorrow, or suspend it, without leaving the session.

## License

[MIT](LICENSE) — a personal learning tool, shared in case it's useful to you.
