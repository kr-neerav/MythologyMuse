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

## STAGE-DRAW rubric — stage only the necessary (no bulk restage)
- Root cause: the extractor asked for everyone "appearing or discussed",
  so similes (Prajapati/Vishnu/Kubera/Dharma/Rohini), lineage (Ikshvaku),
  epithets (Janaka's Sita), the absent/dead (Indra's cloud blessing,
  Dasharatha's cloud ghost), offstage beneficiaries (Bharata at the boon),
  elsewhere-informants (Maricha, Sampati), and collectives (citizens,
  priests, sages, hordes, rejoicing gods) all got faces, sheets, and
  panel-gate waits — polluting panels the on-slide text never needed.
- Fix in prompts (text-only, no pipeline code change): entity_extractor.md
  now takes only the PHYSICALLY PRESENT actors and names the NEVER list;
  storyboard.md gains the STAGE-DRAW rubric (necessary + present, one
  moment per panel, max 5 named faces, telling-location rule, vision-only
  exception); panel_prompts.md draws ONLY listed characters and stages
  everything else as emblem/motif/crowd/prop, never as apparitions.
- Chapter 1 restaged by hand (no model re-run, zero spend): on-slide text
  byte-identical EN+HI (sha b4c8035a/55bf5f787); 14 slides trimmed, e.g.
  S3 Narada telling at the hermitage with Rama as vision (Ikshvaku,
  Kausalya out), S4 Rama alone with wheel emblem, S6 minus offstage
  Bharata, S8 Bharata+Rama only (cloud-Dasharatha, Vashishtha, Brahmanas,
  Bharadwaja out), S10 Rama+Agastya (bow as gift object, sages as
  undesigned silhouettes), S12 Ravana+Sita+Jatayu (brothers lured away),
  S13 fire-friendship four, S14 minus Tara with Dundubhi bones as prop,
  S16 Hanuman+Sita only, S17 Rama+Hanuman+Ocean, S18 Rama+Sita+Agni with
  causeway kept as object, S19 reunion four with crowd undesigned.
  Max scene cast now 5 (S7); insight slides Kavya-only.
- Drive-by fix: render-plan slide 1 still staged Ayodhya palace (hand
  correction had only fixed the prompts file) — synced to the hermitage
  prompt and hermitage scene subject. Prompt parity is now asserted.
- Guard: studio/test_studio.py::test_ch1_staging_rubric_holds (25/25).
  Backup: mythologies/ramayana_dutt/outputs/_backup_Ch1_20260923_044636/.

## Scene-first panel refs — place attaches every time, above characters
- Panel resolve (`server._resolve_target`) no longer skips `kind: scene`
  subjects: the cast is now [place, ...characters], so the location final
  takes first anchor/file priority and characters fill the remaining
  budget slots (1 anchor + MAX_REFS=2 files; extras recorded omitted).
- Scene sheets are now fit for purpose: landscape 16:9 with the comics
  style instead of portrait character-sheet shape (`style_which`
  threaded through `generate_sync`; character sheets unchanged).
- UI (`app.js`): a dashed "Place:" card leads each slide strip with the
  same Generate/Regenerate/pick flow; the panel gate and the missing-sheet
  button now include the place, so Generate panel unlocks only when the
  location final plus all character finals are picked. Insight slides
  (no scene subject) behave exactly as before.
- Guard: `test_panel_cast_scene_first` (26/26). Verified against live
  Ch1 data: slide 7 resolves
  [Sringaverapura Ganga Bank, Rama, Sita, Lakshmana, Guha, Charioteer].
- Needs a server restart (server.py changed): restart server.py, reload.

## Attach-all panel refs — every finalized look conditions the render
- You asked for all refs, not priority-within-budget: `partition_refs`
  (new, `studio/image_gen.py`) chains the first anchorable final via
  `previous_response_id` and file-attaches EVERY other finalized ref —
  place plus the whole staged cast, whatever its size. The MAX_REFS slice
  is gone from the panel path (the constant now governs only the legacy
  `collect_refs` helper). Nothing is silently dropped; `omitted` is 0 and
  the lineage lists exactly what rode the turn.
- Honest costs of attach-all: each attached image adds input tokens to a
  paid call (slide 7 sends 6 images x 2 turns), and more faces raise the
  chance the model blends identities (the per-subject override text pushes
  back). If the API ever rejects the shape, the existing fallback renders
  text+style-only and records the body — check the history line before
  re-spending.
- The panel spend-confirm now names the refs ("Generate 2 panel
  candidates for slide 7 with 6 refs (place, faces...)? Live spend").
- Guard: `test_partition_refs_attaches_all` (28/28). Needs a server
  restart (server.py + image_gen.py changed): restart server.py, reload.

## Ravana simplified to single-head, two-arm regal form (option A)
- The model cannot compose ten heads / twenty arms: the sheet candidate
  rendered one head and two arms despite the text. Decision: canonize the
  render instead of fighting the model. Roster sheet prompt and the slide
  12 panel prompt now stage a single fierce head (fiery copper-red eyes,
  fanged grimace, one conical mukuta) and two arms (khadga + shield/gada).
  Slide 18 stages no Ravana; no other slide does either.
- Guard: rubric test bans multi-head/arm phrasing in slide 12 prose and
  the Ravana roster prompt. Existing unfinalized sheet candidates already
  match the new design and can be picked as-is.

## Vali + Sugriva harmonized as twins (same build)
- They read as different species before: Sugriva lean-agile, Vali
  towering-massive. Both roster sheet prompts and the slide 13/14 panel
  clauses (the only panels staging either twin by name) now share one
  physique (powerfully athletic medium-tall twin build, same
  tawny-golden/cream fur); faces, manes, and regalia stay distinct (Vali
  fierce + crimson sun-regalia + mace; Sugriva kindly + orange-red + ruby
  crown + garland).
- Watch: Sugriva already has a picked final, so panels keep attaching the
  old lean look (file wins over words) until the sheet is regenerated.
  Vali has candidates only; the next generate uses the new build.
- Guard: twin-build phrasing asserted in both roster prompts + slide 14.

## Loop goes single-candidate; Narada roster text strengthened for age
- Loop rounds now spend 1 image, not 2 (`candidates` param on
  `generate_sync`, `--count` on the runner defaulting to 1, UI thumbnail
  strip tolerates the missing second file). UI clicks still render 2.
- Narada's sheet kept rendering young despite "sixty / shaven / white
  beard" in the roster text. Roster now front-loads unmistakable old age
  (visibly sixty, deeply lined face, grey brows, clean-shaven head bearing
  only the shikha). Character facts stay in the roster, not the skill.
- Guard: `test_single_candidate_round` proves one file, one turn, head
  chained (29/29).

## Narada canon corrected: youthful, beardless, rishi knot (reverses elderly edit)
- The approved final is the canon: young, smooth beardless face, long
  black hair in a high rishi topknot. The sixty/shaven/white-beard text
  (original pipeline plus my short-lived elderly strengthening) was the
  wrong source, not the image. Roster sheet prompt and the slide 1/3
  panel clauses now describe the approved face. Garments, tilak, veena,
  and kamandalu unchanged.
- Consequence: all three slide-one finals already match their texts.
  No regeneration needed unless a fresh look is wanted.

## Caption style — child-clear scenes + Q&A insights (Ch.1 retrofit pattern)
- `storyboard.md`: new CAPTION STYLE rule (short clear sentences, name-first,
  one concrete image per sentence; modern everyday words) with the Ch.1
  Slide01 caption as the scene exemplar; new INSIGHT SHAPE rule (Q&A fused
  question+answer+takeaway line opening with Why/How/What, landing on a
  do-or-notice lens) with the Ch.1 Slide02 caption as exemplar;
  `question`/`answer` keys must use the same child-clear Q&A voice.
- Slide plan widened 12–20 to 12–30: Ch.1 needed 27 under the standing
  one-beat-per-slide rule. Word band unchanged at 30–60 (measured Ch.1:
  scenes 24–43w, insights 41–48w — style, not length, was the fix).
- `hindi_storyboard.md`: Hindi mirrors keep the Q&A shape and simple
  register. `storyboard_eval.md` check 4 now rewards child-clear captions
  and Q&A insight lines. No contract change (keys, fences, HINDI_FIELDS,
  selftest bounds-agreement all preserved).
- Retrofit path per chapter: `comic_stage.py --chapter <name> --redo-comic`
  (text-only; studio finals untouched). Fresh chapters pick the style up
  directly.
