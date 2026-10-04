---
name: comic-art-critique
description: Evaluate a MythologyMuse sheet or panel render against the project's captured art feedback and return a verdict with source-layer fixes.
---

# Comic Art Critique

Review one newly rendered image at a time (character sheet, place sheet,
or comic panel) before it is finalized. Look at the image itself. Never
review from the prompt alone. This skill spends nothing: read the image
and the files, write the verdict, stop.

## Inputs

- The render (view it).
- The slide spec: staged cast, location, on-slide text.
- The exact prompt sent plus the attached ref list.
- For sheets: the roster entry. For panels: both prompt copies.

## Verdict

PASS, or FAIL with one line per finding: rule broken, what is seen, and
the exact source-layer fix. Generalize, do not enumerate: a new image
fails for the same reasons old ones did.

## Checks

### 1. Staging fidelity (panels)

- Faces only for the staged cast. Flag materialized similes (gods,
  ancestors, Dharma-figures drawn as people), lineage names, epithets
  split into extra people, invoked-but-absent gods, the dead as cloud
  apparitions, offstage beneficiaries, elsewhere-informants, and
  collectives drawn as individuals.
- Crowds stay undesigned with complete faces or no faces attempted: backs
  to the viewer, soft blur, small distant figures, cropped hands/lamps at
  the frame edge, or omitted entirely. NEVER "faceless" wording (it renders
  as blank smeared faces). FAIL any prompt or render with face-negation
  wording ("faceless", "without/no face", "no distinct faces", "no readable
  facial features", "featureless", "blank face", "only X has a visible
  face") or any background figure with a blank/smeared face zone.
  Corpses and weapons are props. Similes become emblems, motifs, or nothing.
- One moment per panel: the apex beat. Earlier beats at most background
  hints seen from behind, softly out of focus, or omitted.
- Fight beats stage the clash, not just its aftermath: the hostile force
  advances toward the hero with visible momentum while its defeat already
  reads at the edges (recoil, falter, dust, lowered weapons) — never an
  emptied field of pure flight with no fight happening, and never a fresh
  unbroken charge with no turn in the tide.
- The location is where the telling happens. Visions of absent figures
  read explicitly unreal (glow, edgeless inset), never physical.
- Directed actions aim at their recipient: whoever offers, hands,
  presents, blesses, or addresses someone faces that recipient — body,
  gaze, and offered object all point at the named receiver, never at
  another staged character or the crowd. FAIL offerings aimed away
  (slide 26 precedent: Bharata holding the crown aloft toward Hanuman
  while the text says he offers it to Rama). Fix in the panel prompt
  (both copies) by naming the recipient and the facing explicitly
  ("kneeling facing Rama, offering the crown up toward Rama"), then
  re-render.
- At most 5 named faces, prefer 4 or fewer.

### 2. Identity consistency (sheets and panels)

- Faces match the finalized sheets. An attached file beats stale prompt
  words every time.
- Twins share one build; faces, manes, and regalia stay distinct.
- Ravana: single head, two arms. This is project canon, not a mistake.
- Exile dress (Ramayana canon): during the vanavasa exile — after Rama's
  departure from Ayodhya, through the forest years up to the
  return/coronation — Rama wears NO crown of any kind (no
  kiritamukuta/mukuta/karanda/circlet): bare-headed, matted jatabhara
  topknot, bark/valkala or plain ascetic cloth with bow and quiver. The
  roster sheet shows the Ayodhya prince with crown; that crown never
  transfers to an exile panel. FAIL any exile-context render or prompt
  showing or naming a crown on Rama. Fix in the panel prompt (both
  copies) by describing the jatabhara topknot bare-headed and deleting
  every crown word, then re-render. Crowned Rama outside exile (Ayodhya
  before departure, coronation/return) still passes.
- No attribute bleed between staged figures: no extra limbs or heads on
  anyone, ever. Rama reads two-armed, one head.
- One tail per vanara: each monkey-figured staged cast member shows
  exactly one tail, visibly rooted at its own back — one tail per
  figure no matter how many share the frame. FAIL doubled, stray, or
  unrooted tails (slide 16 precedent: Hanuman rendered with two tails).
- Garments, crowns, marks, and attributes match the sheet.

### 3. Composition safety

- Weapons and gifts are never aimed at a protagonist. Gifts arrive
  hilt-first, raised in blessing, open hands.
- Defeat reads routed, faltering, or fleeing. No blood, wounds,
  corpse-focus, or slaughter counts.
- The fire ordeal is a trial the flames refuse: they curl around Sita
  without touching her while Agni attests. Never self-harm framing.
- Everything physical is supported: held, worn, planted, or rested —
  and the support must be plausible for that object. FAIL floating
  objects — bows, staffs, weapons, or vessels hovering with no hand,
  ground, or rest bearing them (slide 15 precedent: Rama's Kodanda
  hovering beside joined praying hands; Ch2 slide 5 precedent:
  Bharadwaja's kamandalu hanging unsupported at his hip while both
  hands hold the cloth). A long bow can never balance
  upright on its tip: never fix it with "planted upright / tip resting
  on the ground". When hands are occupied (joined palms, blessings,
  carrying), remove the weapon from the hands entirely — sling it
  across the back or lay it flat on the ground — and say the hands are
  empty. Fix in the panel prompt (both copies) with that explicit
  object-plausible support, then re-render. Before any PASS, sweep
  every physical prop named in the prompt — staff, vessel, mala,
  cloth, lamp, seat — and name its visible support in the image, one
  per object. Small dark vessels tucked against garments at hips and
  waists hide most often: zoom those zones. No PASS with an
  unaccounted object.

### 4. Policy pre-scan (before any spend)

Fail the prompt without rendering when it contains gore lexicon
(blood*, slay*, slaughter, massacre, gore, corpse, severed, dismember*,
decapitat*, entrails, mutilat*), death tallies phrased as killing, or
self-harm framing. Rewrite at the source, then render. Fail the prompt
without rendering when any prop noun lacks a support verb: every
staff, vessel, weapon, lamp, and seat must read held, worn, planted,
rested, slung, or set down somewhere explicit. Vague standees
("beside his kamandalu", "with his staff nearby") fail at $0 — name
the support, then render. Fail the prompt without rendering when it
contains face-negation wording ("faceless", "without face(s)",
"no face(s)", "no distinct faces", "no readable facial features",
"featureless", "blank face", "only X has a visible face"): rewrite with
camera language (backs to viewer, soft blur, small distant figures, crop)
or omit the crowd, then render.
A provider-side block (image API content_policy_violation on a prompt
that passed this pre-scan) is not a stop: rewrite the panel prompt in
both copies to clear the filter while staying consistent with the
immutable on-slide text, then retry inside the remaining round budget.
Stop only when the block repeats after a prompt rewrite or rounds
exhaust.

### 5. Frame and finish

- Panels 16:9 landscape. Character sheets 2:3 portrait. Place sheets
  16:9 landscape.
- Comic line art holds. No on-image text, no speech bubbles, no
  photorealism drift.
- Artwork fills the frame edge to edge. FAIL any matte, border,
  letterbox, pillarbox, or inset margin in any color — the panel must
  run to all four edges (slide 12 precedent: grey matte baked around
  the panel). A clean inner panel is fixed by cropping the matte, no
  re-render; anything else re-renders.
- Every panel carries its place ref first, then all finalized cast refs.

### 6. On-screen text consistency (panels)

- Read the English and Hindi on-slide text alongside the image. FAIL when the image contradicts or confuses the text: wrong actor, action, place, moment, or count.
- Fix at the image source layers only. Text is immutable.

## Fix layers (close the loop at the source)

- Wrong person present or absent: storyboard characters/location plus
  render-plan subjects plus the Hindi mirror. All three, always.
- Wrong look (build, anatomy, garments): the roster image prompt, then
  regenerate the sheet. Existing finals keep winning until replaced.
- Wrong gesture, facing/direction, gore, or policy hit: the panel prompt in both copies.
- Matte or border framing: crop to the panel edge, save as a new
  candidate, select as final. No re-render when the inner panel is
  otherwise clean.
- Place ref missing: the roster scene entry must exist; finalize the
  place sheet before the panel.
- On-slide text (English and Hindi) is immutable. Never fix staging by
  changing words.
- Image contradicts on-screen text: fix the image side via the matching
  layer above, never the words.

## Automated loop (agent-driven, at most 3 rounds)

Start only on an explicit per-image instruction ("refine slide 7"). That
instruction authorizes up to 3 paid rounds of 1 candidate each, nothing
more. Never loop a whole chapter unasked.

- Round 0 is the existing render. Each round: run the critique, cite one
  source change, spend exactly one single-candidate round via
  `tools/studio_loop.py --chapter <id> --slide <N> --live` (dry-run
  first when the prompt changed), view the candidate, critique again.
  Critique from the 768px thumbnail (`tools/critique_packet.py`); open
  full-res only to zoom prop-support zones. Thumbnails never replace the
  zoom: no PASS with an unaccounted object.
- Before round 1, run the pre-trim gate (`tools/pretrim.py --chapter
  <id>`): storyboard slides staging more than 5 named faces fail the
  face cap on arrival, so trim them to the apex beat first (same three
  files as any wrong-person fix, plus the panel prompt in both copies).
  Entry count is a proxy — a slide resolved with background hints
  (backs/blur, no staged faces) needs no storyboard trim.
- Entities once only: evaluate each entity sheet the first time it
  appears; a PASS stands book-wide for that exact final (same roster
  image prompt, same final file) and is never re-critiqued while the
  final is unchanged. A regenerated or replaced final, or a changed
  roster prompt, resets standing and is critiqued as new. Track
  standing passes in the book-wide ledger
  `mythologies/<corpus>/outputs/sheet_verdicts.json`, keyed by flow_ref
  with roster-prompt sha256 and final-file sha256: before critiquing a
  sheet, look it up, and a matching prompt hash plus final hash means a
  standing PASS, so skip re-critique; on a new PASS, write or refresh
  its entry. On later slides evaluate only entities without a standing
  PASS, then the panel, and report standing passes used with verdicts.
- Preflight before round 1: the panel gate is green (all finals picked).
  The runner's pre-scan fails the round at $0 on gore lexicon, empty
  prompt, or bad aspect. Never pay for a prompt that fails text checks.
- Round 2 may re-roll unchanged sources exactly once, for pure
  composition luck, and must say so. Every other round cites its source
  change or the loop stops.
- Stop at PASS (the passing candidate may be finalized: free and
  reversible), at 3 rounds, on a repeated finding (wrong layer, change
  strategy, do not re-roll), or on a provider policy block that repeats
  after a prompt rewrite (a first-time provider block mandates a
  both-copies prompt rewrite plus a retry — see §4). Report best
  candidate, remaining findings, and paid rounds used.
