# Prompt Changelog — comic stages (Phase 4)

Sources verified in mythology-texts: `skills/comic-entity-extractor/`,
`skills/comic-entity-prompt-designer/`,
`skills/english-script-to-comic-storyboard/`,
`skills/comic-slide-to-flow-prompt/`, `skills/comic-storyboard-eval/`,
`comic_generation/comic_pipeline_checks.py` (Layer A),
`comic_generation/comic_hindi_storyboard.py::TRANSLATE_PROMPT`, plus the
reference artifacts for `Book_1_Bala_Kanda_Chapter_1` (15 scene/insight
slides, flow records with `present_entities`, eval record shape, Hindi
storyboard shape).

Frozen downstream shapes (preserved exactly): storyboard slide keys
(`slide`, `slide_label`, `title`, `type`, `text_mode`, `speaker`,
`question`/`answer` on insight, `on_slide_text`, `characters`, `location`,
`rationale`); flow records (`slide`, `slide_label`, `flow_prompt`,
`present_entities[{name, flow_ref}]`); eval record (`verdict`, `gate`,
`model`, `structural_ok`, `corpus`, `counts`, `storyboard_layer_a`,
`flow_layer_a`); Hindi storyboard (same slides, translated text fields).

## entity_extractor.md — PORTED
- Same role (characters + scenes from English narration, canonical names,
  aliases, one-sentence descriptions, no inventions). JSON-only fences added
  so the driver parses deterministically.

## entity_designer.md — PORTED + dual output
- Keeps the model-sheet `image_prompt` discipline (plain grey backdrop,
  fixed identity details, no on-image text) and adds a `muse_prompt`:
  the same identity as flowing appearance prose with no @references.
- Flow refs are derived deterministically by the driver (CamelCase alnum),
  not the model — one less thing for the model to get wrong.

## storyboard.md — PORTED + slide discipline
- Slide plan made explicit (10–16 slides, ≥2/3 scene, ≥3 insight) matching
  the reference chapter's density (15 slides).
- Names constrained to the provided entity list verbatim; `slide_label`
  format pinned to `SlideNN - <title>` to satisfy Layer A.
- Muse adaptation: `<think>` wrappers dropped (xhigh thinking budget instead).

## flow_prompt.md — PORTED + dual output
- Keeps the Flow contract (single moment, @-referenced ingredients both
  directions, text-free negative clause) and adds `muse_prompt`: the same
  panel as self-contained descriptive prose with appearances folded in.
- Both prompts come from ONE call (one object, two fields) — no cost doubling.

## storyboard_eval.md — PORTED
- Same four checks (coverage, fidelity, ingredient discipline, panel text)
  with a machine-readable `{verdict, strengths, weaknesses}` contract.
  Deterministic Layer A gates stay in code, not in the prompt.

## hindi_storyboard.md — PORTED
- Same translator brief (meaningful modern Hindi, 20–50 Devanagari words,
  insight slides translate question+answer+caption, all other keys verbatim).

## hindi_storyboard.md — v2 slim fields-only
- Live Chapter 1 proved the whole-board echo does not fit: 19 slides
  (≈15.7KB in, full echo out) died 3x with `status=incomplete` empties at a
  8192-token ceiling (reasoning shares the output budget). The model now
  sees/returns only `{slide, fields}` items (`on_slide_text` always,
  `question`/`answer` when present — 8.9KB of the 15.7KB Chapter 1 board,
  with the reply shrinking the same way) in 5-slide chunks,
  and the driver merges translations back onto verbatim English slides, so
  structure cannot drift in translation. Ceiling raised to 32768 (English
  board parity). Tone/length brief unchanged (30–60 Devanagari words).

## Layer A gates — REUSED AS CODE
- `check_storyboard_layer_a` / `check_flow_layer_a` ported into
  `tools/comic_stage.py` (slide numbering/labels/titles/types, ingredient
  @-usage both directions, text-free clause advisory). Deterministic, no model.

## Observability + partial persistence (deterministic, no model)
- New `comic_debug_<ch>.jsonl`: one JSON record per failure point
  (extraction/design chunk/storyboard attempt/flow chunk/Hindi
  chunk/judge attempt/budget) with
  the exact stage input in full. Nothing recorded on success.
- The judge retries empty verdicts on its own (EVAL_ATTEMPTS, each miss
  recorded): a flaked verdict call costs another verdict call, never a
  full-pipeline redo (Chapter 1 burned ~30 calls re-running E/S/F/H for
  two flaked judge calls before this existed).
- Transport vs quality: when the judge never answers (`eval produced no
  usable verdict`), the driver stops (rc=1, manifest keeps all completed
  stages) instead of triggering the rebuild loop — the rerun resumes at
  the judge. Only an explicit verdict FAIL rebuilds the pipeline.
- Judge ceiling 4096 → 16384: the verdict is tiny but the judge thinks
  over ~28KB of narration + board at high effort first, and the ceiling
  bounds thinking AND output — at 4096 it died 5x mid-thought with
  status=incomplete empties. Caps are not spend: identical usage costs
  the same at any ceiling.
- Every completed step persists immediately: repo per designer chunk,
  storyboard after Layer A, muse pack per panel chunk, Hindi per
  translation chunk (`comic_hindi_partial_<ch>.json`, merged into the Hindi
  board on success). A later death keeps reviewable output (run 7's 19KB
  board died in memory — that class is gone).
- Per-stage resume via `comic_progress_<ch>.json` (live-stamped manifest of
  completed board/flow/Hindi slide counts + the Layer-A verdict): a rerun
  adopts finished stages and only runs what is pending. Dry runs stamp
  `live:false` so fixtures are never resumed from; `--redo-comic` forces a
  full run; a fresh board drops stale downstream files.

## Render plan emitter (deterministic, no model)
- New `comic_render_plan_<ch>.json`: roster (every subject once, with its
  sheet `image_prompt` and an empty `sheet_response_id` slot) + per-slide
  turns (`muse_prompt`, subjects, advisory cookbook size: opener wide,
  insight/dialogue square, other scenes portrait). Written alongside the
  muse pack on the main path only. Maps 1:1 onto the Muse Image anchoring
  recipe (render sheets → chain panels via `previous_response_id`).

## Flow removal + batching + call budget (live-unproven)
- **Flow/ingredient output removed** (user renders from Muse prompts only):
  `flow_prompt.md` renamed to `panel_prompts.md` and rewritten Muse-only
  (batched array in/out, `{slide, muse_prompt}` per slide, slide echo for
  joining). `present_entities` contract, `check_flow_layer_a`, the
  `flow_layer_a` eval key, and the `comic_flow_prompts_*.json` file are all
  deleted — the eval verdict now rests on the judge alone. Entity
  `image_prompt` model-sheets are KEPT (plain descriptive prompts, no
  @-references; still useful render inputs).
- **Batched designer** (`DESIGN_BATCH = 8`): one call designs a whole chunk;
  replies join on echoed `canonical_name`, a dropped/duplicated item fails
  the chunk for intact retry. 53 entities → ~7 calls.
- **Batched panels** (`FLOW_BATCH = 5`): one call prompts a whole chunk,
  joined on echoed `slide`. 12–20 slides → 3–4 calls.
- **Per-run call budget** (default 100, `--max-calls`): logical stage calls
  counted in one wrapper; overruns stop with best-effort files + eval FAIL
  ("call budget exhausted") and rc=1. `DESIGN/FLOW_TOKENS` raised to 16384
  for batched outputs (same lesson as the storyboard ceiling).

## Richness relaxation — panel-text + slide budget widened (live-unproven)
- Slide plan 10–16 → **12–20** (`storyboard.md`): richness through beats, no
  render risk; added one-beat-per-slide anti-compression rule.
- On-panel `on_slide_text` 20–50 → **30–60 words**, mirrored in lockstep in
  `storyboard.md` + `hindi_storyboard.md` (Devanagari) + `storyboard_eval.md`
  check 4. Cap stays because the text is rendered onto the art; the note now
  says so ("every word must earn its panel space").
- Depth moved to unbounded fields: insight `answer` gains a 3+ layers cue
  (eval check 4 mirrors it), `rationale` one sentence → one to two.
- No schema/contract change. `tools/selftest.py` gains a cross-file number
  agreement check so the three copies can never drift apart silently.

## Hand correction — Ch1 slide 1 location (pipeline smeared Ayodhya onto the hermitage)
- `comic_storyboard_Book_1_Bala_Kanda_Chapter_1.json` slide 1 `location`:
  "Ayodhya" → "Valmiki's Forest Hermitage". Per Dutt Sec I–II Valmiki
  questions Narada at his hermitage (disciples present); Ayodhya is the
  answer to his question, not the setting.
- `comic_muse_prompts_Book_1_Bala_Kanda_Chapter_1.json` slide 1 background
  clauses rewritten to forest hermitage (leaf-thatched huts, sacred fire,
  riverbank grove); both sages' descriptions byte-identical. No "Ayodhya" /
  palace / chhatri remains in the prompt.
- Hand edit, not a pipeline change: a Chapter 1 storyboard/prompts re-run
  will overwrite this. Both files re-validated as JSON; only slide 1 touched.

## Hand correction — Kavya promoted from junk entity to narrator character
- Pipeline extracted the word kavya (poetry) as a person with kind unknown,
  no flow ref, no image prompt. But the chapter consistently stages her: a
  young woman storyteller (teal saree, jasmine braid, jhumkas) hosting the
  five insight slides (2, 5, 9, 15, 20), with Female voice credit in Hindi
  narration. Minor wording drift across slides (saree vs kurta, medium-brown
  vs wheat-golden) is left as-is: the picked sheet final plus the per-subject
  file override unifies her look at render time.
- render_plan roster entry now: kind character, flow_ref Kavya, image_prompt
  model-sheet in Valmiki-prompt format. No code changes: generatable flag,
  sheet resolve, and panel attach pick it up automatically. Re-validated as
  JSON; a Chapter 1 design re-run will overwrite this.

## Hand correction — slide 4 Dharma depersonified (simile, not a person)
- On-slide text (and Dutt) says "true like Dharma": a simile, like "earth in
  forgiveness". The prompt illustrator materialized it into a standing god.
  Slide 4 prompt now stages a radiant golden dharma-wheel emblem turning
  above a Veda manuscript on a draped stand instead; Rama, Prajapati,
  Vishnu, Kubera untouched.
- Dharma removed from slide 4 subjects (render plan) and characters
  (storyboard) so no sheet is offered, no face attaches, and the panel gate
  never waits on him. Roster entry left in place (unreferenced). Same
  overwrite caveat on a Chapter 1 re-run.

## Hand correction — slide 7 Rohini + Janaka figures removed (similes again)
- On-slide text says "Janaka's Sita follows like Rohini follows moon": an
  epithet plus a classical simile, both correct as words. The prompt
  illustrator staged both as cloud figures blessing the farewell; neither
  belongs at Sringaverapura (Janaka is in Mithila; Rohini is the moon's
  consort, not a bystander). Cloud clause cut; prompt now closes on the
  farewell crowd in soft golden light. Rama, Sita, Lakshmana, Guha,
  Charioteer, Dasharatha, citizens untouched.
- Both dropped from slide 7 subjects/characters (no sheets, no refs, no
  gate). Roster entries left unreferenced. Text similes kept deliberately.
