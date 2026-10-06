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

## Rama exile dress — no crown during vanavasa
- Rule: during the vanavasa exile (after Rama's departure from Ayodhya,
  through the forest years up to the return/coronation) Rama is
  bare-headed with a matted jatabhara topknot — no crown of any kind.
  Crowned Rama is correct only outside exile (Ayodhya before departure,
  coronation/return).
- `panel_prompts.md`: new exile-dress rule — exile panels fold the
  jatabhara/bark-cloth look into the prose and omit every crown word;
  the roster sheet (Ayodhya prince with crown) never transfers its crown
  to an exile panel.
- `entity_designer.md`: Rama's sheet stays the crowned Ayodhya prince;
  exile is a per-panel override, never a second Rama entity.
- `.agents/skills/comic-art-critique/SKILL.md` §2: FAIL any
  exile-context render or prompt showing/naming a crown on Rama; fix in
  the panel prompt (both copies), then re-render.
- Existing Rama sheet + standing PASS unchanged (pre-exile prince).

## Look variants — per-slide subject sheet override (Ch1 exile retrofit)
- Mechanism: a render-plan subject may carry `"sheet": "<flow_ref>"` to
  attach a different picked final for that slide while the staged
  character name stays. Readiness, the panel gate, and ref attachment
  resolve against the variant (`studio/bundle.py`); unknown variants
  fail closed (missing) instead of rendering the base look;
  `tools/pretrim.py` preserves the key across trims. No `image_gen.py`
  change (anchors key generically by ref); UI needs none (reads
  `sheet_state`).
- Why: attached files win over prompt words by design, so crown-free
  words alone could not uncrown exile Rama while the crowned prince
  sheet attached (2 paid rounds proved it). Fix: `RamaExile` roster
  variant (bare jatabhara, bark cloth, same face) + override on the 13
  exile slides; Ayodhya/coronation slides keep the crowned sheet.
- Result: all 13 exile panels re-rendered and finalized crown-free.
  Slide 11 needed a third attempt: the attach shape drew a provider
  content-policy block twice (once before, once after a softened prompt
  rewrite), so the loop stopped per rule; a later unchanged re-roll
  passed the filter on luck and critiqued PASS.
- Guard: `test_subject_sheet_override_selects_variant` (studio suite).
- Caveat: a `--redo-comic` rebuild drops hand-added roster/subject keys
  (same as all hand corrections); the emitter does not set them yet.

## Principals-over-minors priority (slide 7 precedent)
- Rule: Rama, Sita, and Lakshmana are never dropped, merged, or
  backgrounded for minor figures. At the face cap, charioteers,
  attendants, and collectives yield first; lookalike principals are
  disambiguated, never fused (one feathered bowman is Guha, the
  clean-shaven sword-bearing youth is Lakshmana).
- Slide 7 redraw: the finalized Ganga panel had merged Lakshmana away
  (two Guha-like bowmen) while the Charioteer kept a prominent face.
  Prompt fix in both copies (Lakshmana foreground at Rama's side, Guha
  the lone feathered figure, Charioteer back at the chariot), one paid
  re-render, critiqued PASS, finalized.
- Recorded in `comic-art-critique/SKILL.md` §1, `panel_prompts.md`, and
  the `storyboard.md` STAGE-DRAW rubric.

## Blessings flow down, never up (slide 10 precedent)
- Rule: elders, sages, and gurus bless; juniors receive with joined
  palms or a bowed head. A younger prince never gives ashirwad (raised
  blessing palm) to a sage or elder.
- Slide 10 redraw: the finalized Vow panel showed Rama kneeling with a
  raised palm toward Agastya — reverence reversed, contradicting the
  on-slide text ("Agastya blesses him"). Prompt fix in both copies
  (Rama anjali + bowed head receiving; Agastya's blessing hands
  unchanged), one paid re-render, critiqued PASS, finalized.
- Recorded in `comic-art-critique/SKILL.md` §1 and `panel_prompts.md`.

## Goddesses travel with dignity (slide 13 precedent)
- Rule: Sita (and every goddess) is never clutched, gripped, or carried
  bodily by an antagonist; abductions stage her upright inside the
  vehicle with rails/seats/space between her and her captor, his hands
  elsewhere. Exactly one staged figure per staged name.
- Slide 13 redraw: the final showed Ravana bearing Sita aloft pressed to
  his chest. Round 1 fix (Pushpaka cabin + rail) duplicated Sita (one at
  the hut, one aboard) — FAIL; round 2 drew a provider block; round 3
  (minimal passing-shape rewrite) passed: one Sita standing in the
  cabin behind its rail, Ravana's hands on rail and weapons, Jatayu
  diving at the chariot. Critiqued PASS, finalized.
- Recorded in `comic-art-critique/SKILL.md` §1 and `panel_prompts.md`.

## Projectiles stay connected (slide 17 precedent)
- Rule: every arrow, spear, or thrown weapon must visibly join origin
  to target in one straight line (tail at string/hand, tip at target);
  bow arm extended at the target, string hand at cheek, gaze down the
  shaft. FAIL floating shafts and cross-eyed aim.
- Slide 17, two rounds: first the shaft froze mid-air detached from the
  bow while both figures stared past it (odd); rewrite to the release
  instant (shaft spanning string to trunk) fixed the direction, and a
  second round's `--extra` restored Rama's bark cloth and Sugriva's
  crown+garland from their refs. Critiqued PASS, finalized.
- Slide 17 count follow-up (3 rounds, stopped on budget): the motion gap
  in the spanning shaft read as a second arrow against "one arrow" text.
  Lesson: never illustrate a counted feat with aftermath hole-counting —
  the model multiplies holes (riddled trunks twice) instead of one clean
  row. Keep the release instant with ONE unbroken shaft; no arrows in
  the air otherwise. A further round aimed the shaft at Sugriva standing
  in the row (bystander in the firing line); the fix is positional —
  keep all figures behind the bow arm, clear of the shaft's path. An
  unchanged re-roll then passed: shaft string-to-trunk with splinters,
  Sugriva clear, regalia intact. Finalized.
- Recorded in `comic-art-critique/SKILL.md` §3 and `panel_prompts.md`.

## Name the target (slide 18 precedent)
- Rule: a drawn weapon points AT its named victim (eye, weapon, target
  colinear). Phrase aim as geometry, never as wound-targeting — wound
  words trip the provider filter on the attach shape.
- Slide 18: the final aims past Vali while the text says the arrow fells
  him. "Aimed straight at Vali's chest" drew a provider block on the
  attach shape; softened to "shaft pointing toward Vali" and still
  blocked — stopping per loop rule. A later unchanged retry passed with
  refs: aim correct at Vali but TWO shafts embedded vs "single arrow"
  text, so not finalized. A "single nocked shaft, none embedded"
  rewrite blocked a third time (fallback came back crowned — discarded).
  A fourth attempt with the newest wording blocked identically.
- Resolution: reframed from aim to aftermath — Vali fallen still with
  mace slipped from hand (no wounds, no arrows), Sugriva triumphant
  overhead, Rama behind with bow lowered and nothing nocked. No
  aimed weapon or wound words anywhere, so the attach shape passed
  first try. Critiqued PASS, finalized. Lesson within the lesson: when
  the weapon itself keeps tripping the filter, illustrate the OUTCOME
  the caption asserts, not the strike.
- Recorded in `comic-art-critique/SKILL.md` §3 and `panel_prompts.md`.

## Clear the firing lane (slide 22 precedent)
- Rule: a drawn weapon threatens no staged figure but its target. Name
  the target AND clear the lane: geometry plus position — an open aim
  point (ground, water, sky) with every other figure behind the bow
  arm, below the shaft line, or otherwise visibly clear of the path.
- Slide 22 redraw: the final aimed Rama's nocked arrow at a kneeling
  Hanuman at frame right. Prompt fix in both copies (shaft pointing at
  open water and at no person; Hanuman kneeling behind Rama's bow arm,
  clear of the arrow's path), one paid re-render, critiqued PASS,
  finalized. Same positional pattern as the slide 17 firing-line
  follow-up (figures behind the bow arm).
- Recorded in `comic-art-critique/SKILL.md` §3 and `panel_prompts.md`.

## Hanuman ears both alike (mixed-pair precedent)
- Rule: paired attributes are described once, identically, with "both
  alike" wording. Hanuman's canon is small round human-type ears, both
  alike — never pointed, tall, or vanara-type wording.
- Why it happened: the old prose ("tall pointed vanara ears") named an
  exotic mismatched type, and hair usually hides one ear, so the model
  sampled each visible ear near-independently and the pair diverged.
  Words plus the attached sheet jointly condition the render, so the
  fix went into every source layer: `entity_repository.json` Hanuman
  prompts (2x), both chapter rosters, all 12 Hanuman panel prompts
  (both copies each), the firing-lane wording on slide 22, and a
  regenerated Hanuman sheet — then all 12 panels re-rendered against
  the corrected sheet, each critiqued from the image with ear zooms,
  all PASS. Rakshasa pointed ears (Dushana/Maricha-type entries) are
  correct for those characters and were left untouched.
- Ch3 follow-through: slides 13/14/16 also needed the `RamaExile`
  sheet variant (crowned words fixed, crown still rendered until the
  variant attached — attached files win over words), and slides
  10/11/14/17/18 had string-serialized `subjects` (re-parsed to lists
  so refs attach). Slide 18 keeps the crowned sheet: coronation
  homecoming, exile over.
- Recorded in `comic-art-critique/SKILL.md` §2, `entity_designer.md`,
  and the Hanuman roster/panel wording itself.

## Ancient vehicles fly clean (slide 13 precedent)
- Rule: no engines in the age — no smoke, exhaust, fumes, or fire
  beneath chariots and vimanas. Divine vehicles fly by celestial power,
  trailing only pale dust and petals. Stage ONE cabin and one pavilion;
  extra pavilion/prow/trailing-cabin nouns grow a second occupied
  vehicle and duplicate a staged figure.
- Slide 13 rounds: the final showed gasoline-style exhaust wisps. Round
  1 (engine-less vimana + no-smoke clause) lost Ravana and duplicated
  Sita; round 2 restored both with one Sita but grew a small occupied
  upper pavilion; round 3 (ONE-cabin wording) rendered two full
  vehicles. Rounds exhausted per loop rule — slide 13 NOT finalized;
  old final stands. Next strategy (new layer): drop pavilion and
  swan-motif nouns entirely (they seed the extra cabin) and keep only
  the proven single-cabin shape plus the no-smoke clause.
- Same-location note: slides 12/13/14 share identical hermitage prose;
  the round-3 layout anchor (hut right, fence left, altar center)
  held the camera. Recorded in `comic-art-critique/SKILL.md` §1 and
  `panel_prompts.md`.

## Fire placement and Indian gods (slides 21/24 precedent)
- Rule: burning-tail fire lives ONLY on the tail-tip tuft — legs, feet,
  langot, and torso explicitly flame-free (slide 21: flame had read as
  burning legs; "single ribbon of fire from the tail-tip alone" fixed
  it first try, finalized).
- Rule: Vedic gods wear Indian markers — kirita-mukuta, tripundra/sandal
  tilak, yajnopavita, Indian-draped angavastram, seven-tongued halo,
  sruk + torch (slide 24: Agni's toga-like drape and wild flame beard
  read Greek; roster + repo + sheet reworked with tripundra and trimmed
  moustache, panel re-rendered, finalized).
- Recorded in `comic-art-critique/SKILL.md` §2 (Agni sheet),
  `entity_designer.md`, and the Agni roster/repo wording.

## One crown, one recipient (slide 26 precedent)
- Rule: a handoff stages a SINGLE crown in the giver's hands, giver
  body and gaze fixed only on the receiver; the receiver wears no crown
  at the same time. Pair every no-crown clause with positive hair —
  "bare-headed" alone renders BALD against a crowned sheet (round 1);
  "full hair in topknot, hair alone on his head, no crown" fixed it
  (round 2, finalized). Staged beat is the offering instant; the text's
  "crowned king" is its outcome.
- Recorded in `comic-art-critique/SKILL.md` §2 and
  `panel_prompts.md`.

## Slide 13, second loop (this turn)
- The drop-pavilion strategy worked: one chariot, no fumes, Ravana
  present, one cabin Sita. But the hut doorway grew a second Sita.
  Fix that worked: describe the door SHUT ("closed bamboo door, no
  opening, no one at it") rather than "empty doorway" — an opening
  invites a figure.
- Negated counts backfire: "one chariot only / no second cabin / no
  other vehicle" rendered TWO vehicles twice. Positive framing ("the
  lone craft in an otherwise empty sky holding only Ravana and Sita")
  rendered one. Lesson: never negate a count or an object in panel
  prose — describe only what exists.
- Round 3 also drew the provider attach-shape block (content policy on
  Ravana-menace + weapon + captive combo), so it rendered fallback
  text+style with no sheet refs. Sita leaned half over the rail
  (dignity FAIL). Rounds exhausted — still not finalized. Next: keep
  positive framing + shut door, add seated-inside physical constraint
  ("both feet on the cabin floor, hands on the rail from inside") and
  soften Ravana menace words to clear the attach filter.
- Recorded in `comic-art-critique/SKILL.md` §1 (shut-door/out-of-frame
  beats) and `panel_prompts.md` (positive counts, seated-inside).

## Slide 13, third loop (finalized)
- Soften + seat + clear-sky round: Ravana menace softened (attach
  filter cleared, refs attached), Sita seated, exactly two courtyard
  seats — but a second occupied chariot returned and dark smoke with
  fire glow ringed the craft.
- Spatial-dominance round: "golden cabin and great wheels filling the
  entire upper sky from edge to edge with Jatayu's wings filling the
  sky beside it" left no room for a second craft — ONE chariot,
  Sita seated inside with feet in and hands on the rail, no smoke or
  fire glow, shut hut door, courtyard matching slides 12/14.
  Critiqued PASS, finalized.
- Standing rules confirmed: fill the sky to suppress escort craft;
  clear blue sky must be named or smoke returns.

## Agni fully Indianized (slide 24, second loop)
- Research (web): Agni in Indian art is a red man with poita (sacred
  thread), fruit garland, black eyes and hair, seven tongues/rays, and
  almost always a ram vahana. Multi-head/limb textual forms stay out
  per project no-bleed canon (single head, two arms — same call as
  Ravana).
- Why he read Greek: bare oiled torso + himation-style shoulder drape
  + torch + wild flame beard/hair = Zeus/Prometheus signal. Fix in
  repo (both prompts) + Ch1 roster + regenerated sheet + slide 24
  panel (both copies): black topknot under mukuta, seven flame
  tongues, black moustache/beard, uttariya over left shoulder with
  hanging ends, marigold-and-fruit garland, white ram vahana. One
  round each, both critiqued PASS, finalized.
- Recorded in `entity_designer.md` (full Agni canon) and the Agni
  roster/repo wording.
