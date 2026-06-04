# Recall & Reflect — Design & Rationale

This doc captures *why* the app is shaped the way it is. It's the spec the build
follows. Sources are summarized inline; the short version is that every non-obvious
decision traces back to cognitive-science or UX research.

## Principles

1. **Make the learner generate.** The biggest retention wins come from the user
   producing explanations, examples, and recall — not from reading AI-produced text.
   (Generation effect; elaborative interrogation; self-explanation — Dunlosky et al. 2013.)
2. **Effort is the point, within reach.** Effortful retrieval strengthens memory more
   than fluent restudy (testing effect; Bjork's *desirable difficulties*). But a
   difficulty is only *desirable* if the learner can execute it — so we scaffold with
   hints and never punish a miss. Target a ~20–40% miss rate, not 0% and not 90%.
3. **Act first, ask second.** Capture never blocks on questions; follow-ups are an
   optional refinement, always skippable. (Conversational-UX norm.)
4. **Reward showing up, not perfection.** A forgiving consistency signal, not a fragile
   streak that punishes a single missed day. (Streak-creep / goal-substitution research.)
5. **Calm, keyboard-first, local.** Neutral palette + one accent, generous whitespace,
   every action has a key. Data never leaves the machine.

## The two stages

### Reflect (capture)
- Opens to a cursor, not a form. User dumps freely.
- The model asks **at most 2–3** generative follow-ups, one at a time, drawn from
  archetypes: *why is this true* (elaborative interrogation), *how does it connect to
  what you knew* (self-explanation), *concrete example* (dual coding), *one-sentence
  gist*, *how is it different from <related>* (discrimination), *where would you use
  it / when would it fail* (transfer). Arbitrary facts skip elaboration → plain cloze.
- Cards (basic Q/A + cloze) draft live and are editable inline before saving.
- The conversation's elaboration is stored alongside the learning as context.

### Recall (review)
- **Free-recall first:** a blank box — "tell me what you remember." (Free recall >
  cued recall > recognition.) Typing is optional per card; you can self-grade mentally.
- **Confidence before reveal:** sure / think so / guessing. High-confidence misses get
  surfaced (the *hypercorrection effect*) and re-shown sooner.
- **AI grade + one poke:** local model compares recall to the reference answer
  (correct / partial / wrong), names the missing idea, and asks *one* Socratic
  follow-up. Reference-guided + semantically lenient to avoid harshness. Optional.
- **Hint ladder:** progressive hints on demand so a stuck user climbs down to an
  achievable retrieval instead of failing blankly.
- **Rate 1–4** (Again/Hard/Good/Easy) → FSRS schedules the next review. Keys printed
  on the buttons. Quiet progress (count + thin bar), small default batch.

## Scheduling
FSRS-4.5 with default weights (state of the art; ~20–30% fewer reviews than SM-2 for
equal retention). `desired_retention` default 0.90, user-adjustable. No optimizer until
there's a meaningful review history.

## Architecture

```
app/
  config.py            local-only config
  main.py              FastAPI app, static mount, lifespan (warm model, scheduler)
  core/  fsrs.py        ported FSRS-4.5 scheduler
         cloze.py       {{c1::...}} parsing/rendering
  db/    database.py    sqlite connection + schema
         models.py      dataclasses
         repository.py  all queries; apply_review() owns FSRS transitions
  services/ llm.py      Ollama: chat-stream, structured card gen, recall grading, poke
            notify.py   gentle Windows toast reminders (APScheduler)
  api/   capture.py review.py learnings.py stats.py settings.py
web/
  index.html  css/styles.css  js/{app,api,store}.js  js/views/*.js
```

### LLM usage (local only)
- `/api/chat` for multi-turn capture; stream tokens for perceived speed.
- Structured output via JSON schema (constrained decoding) + pydantic validation.
- Grading temp ~0.1 (deterministic); poke temp ~0.6 (varied). Card gen ~0.4.
- Warm the model at startup with `keep_alive`. Strip `<think>` if a reasoning model is
  ever selected. **Cloud model tags are refused.** Every LLM feature degrades
  gracefully: capture → manual cards; review → self-grade.

## Out of scope (for now)
Multi-user, sync, mobile, account system, encryption-at-rest (single-user local box).
