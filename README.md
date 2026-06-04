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

Everything is on your machine. The app binds to `127.0.0.1` only, stores data in a
local SQLite file under `data/` (which is git-ignored), and the only network calls it
makes are to a **local** [Ollama](https://ollama.com) instance. Cloud LLM models are
explicitly blocked so your notes can never leave the device.

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
| **Reflect** | Free-flow chat → 2–3 generative follow-ups (skippable) → draft cards you edit → save. |
| **Recall** | Free recall (type it) → confidence → AI grade + one Socratic poke → rate (1–4). |
| **Schedule** | FSRS sets each card's next review to hit your target retention (default 90%). |

## Stack

- **Backend:** Python + FastAPI + SQLite. Ports the FSRS-4.5 engine.
- **Frontend:** plain HTML/CSS/ES-modules — no build step, runs offline.
- **AI:** local Ollama (`qwen2.5:7b` by default). Optional, with graceful fallback.

## Keyboard

Review is keyboard-first: `Space` reveal · `1`/`2`/`3`/`4` rate · `H` hint · `Z` undo.

## License

MIT — personal learning tool.
