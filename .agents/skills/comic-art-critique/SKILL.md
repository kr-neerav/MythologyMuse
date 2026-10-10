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
- No gratuitous animals or animal-skin props: FAIL any live animal, hide, skin, or ajina/deerskin mat the storyboard does not stage, the on-slide text does not name, and no staged entity identity requires as a functional attribute (Ch3 Slide05 precedent: deer skin beside Valmiki's kusha seat, unlisted, unnamed, unrequired — cut it from the panel prompt in both copies, then re-render). A staged animal beat (Maricha's golden deer) keeps its animal.
- One moment per panel: the apex beat. Earlier beats at most background
  hints seen from behind, softly out of focus, or omitted.
- Fight beats stage the clash, not just its aftermath: the hostile force
  advances toward the hero with visible momentum while its defeat already
  reads at the edges (recoil, falter, dust, lowered weapons) — never an
  emptied field of pure flight with no fight happening, and never a fresh
  unbroken charge with no turn in the tide. Pleading witnesses kneel at
  the frame edge recoiling away with raised hands — never centered under
  the clash with arms between combatants, which reads as the fight being
  over them (Ch3 slide 13 precedent: Tara centered beneath the duel;
  fixed to frame-edge recoiling).
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
- Goddesses travel with dignity: Sita (and every goddess) is never
  clutched, gripped, or carried bodily by an antagonist. Abductions
  stage her upright — standing or seated inside the vehicle with rails,
  seats, or space between her and her captor, his hands on reins, rails,
  or weapons, never on her (slide 13 precedent: Ravana bore Sita aloft
  pressed to his chest; fixed to Sita standing in the Pushpaka cabin
  behind its rail). One staged woman per panel — FAIL duplicates. Fix
  in the panel prompt (both copies), then re-render.
- Blessings flow down, never up: elders, sages, and gurus bless;
  juniors receive with joined palms or a bowed head. FAIL a younger
  prince giving ashirwad (raised blessing palm) to a sage or elder —
  Rama kneels in anjali before Agastya; Agastya's hands bless above him
  (slide 10 precedent). A rishi, sage, or elder never kneels before
  juniors to offer a gift — the elder stands upright and offers down
  while the junior kneels or bows to receive (Ch3 slide 10 Dandaka
  precedent: Agastya kneeling to offer the divine bow to a standing
  Rama). Fix in the panel prompt (both copies), then re-render.
- At most 5 named faces, prefer 4 or fewer.
- Ancient-tech realism: vehicles of the age have no engines, so no
  smoke, exhaust, fumes, or fire beneath them — divine chariots and
  vimanas fly by celestial power, trailing only pale dust and petals
  (slide 13 precedent: Pushpaka rendered with gasoline-style exhaust
  wisps; fixed with "engine-less, divine power, no smoke no exhaust no
  fumes"). Name ONE cabin and one pavilion only — extra pavilion,
  swan-prow, or trailing-cabin nouns grow a second occupied vehicle
  and a duplicate figure (slide 13 rounds 2-3 precedent).
- Same-location continuity: consecutive slides in one place share
  identical place prose PLUS one explicit layout anchor (hut at the
  right, fence at the left, altar center foreground) — prose alone
  drifts the camera (slides 12-14 precedent: same hermitage).
  Identical wording still leaves minor per-render differences (no seed
  or composite support): same ref, same words, same anchor is the
  ceiling — never promise pixel-identical backgrounds.
- Shut doors, don't empty them: an "empty doorway/opening" grows a
  duplicate figure; a SHUT door ("closed bamboo door, no opening, no
  one at it") stays shut (slide 13 precedent: doorway Sita twice).
- Positive counts only: negated quantities ("no second cabin", "no
  other vehicle") render the negated thing — state what exists ("the
  lone craft in an otherwise empty sky"). Seat staged figures
  physically: "both feet on the cabin floor, hands on the rail from
  inside" keeps Sita in the cabin (slide 13 precedent: she leaned half
  over the rail).
- Principals over minors: Rama, Sita, and Lakshmana are never dropped,
  merged, or backgrounded for minor figures (charioteers, attendants,
  citizens). When a panel crowds toward the face cap, minor figures yield
  first — trim them, push them to backs/blur/distance, or omit them —
  and Lakshmana stays a distinct foreground face with his bow and sword
  (slide 7 precedent: Lakshmana merged away while the Charioteer kept a
  prominent face). Lookalike principals get disambiguated, never fused:
  one feathered bowman is Guha, the clean-shaven sword-bearing youth is
  Lakshmana. Staged vanara read fully simian (muzzle, fur, tail), never
  blended with human-prince features (Ch3 slide 13 precedent: Sugriva
  rendered as a Lakshmana-like human prince; fixed with fully-simian
  wording distinct from any human prince).

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
  every crown word, then re-render. When the crown persists across
  rounds, the attached crowned sheet is forcing it (attached files win
  over words by design): attach the exile variant sheet on that slide's
  Rama subject (`"sheet": "RamaExile"` in the render plan) instead of
  re-rolling. Tag the variant at chapter-build time for every
  exile-context panel — Ch3 precedent: slides 13/14/16 shipped with
  crowned Rama because the variant was never tagged there, and two
  paid rounds on corrected words alone still rendered the crown.
  Crowned Rama outside exile (Ayodhya before departure,
  coronation/return) still passes.
- Uncrowned never means hairless: "bare-headed / no crown" without an
  explicit full-head-of-hair clause renders a BALD head when the
  attached sheet wears a crown (slide 26 precedent). Always pair the
  negation with positive hair: "full jet-black hair tied in a topknot,
  hair alone on his head, no crown".
- One crown, one recipient: a handoff stages a SINGLE crown in the
  giver's hands with giver body and gaze fixed only on the receiver —
  never a crown on the receiver's head at the same time (slide 26
  precedent: crowned Rama plus Bharata offering a second crown toward
  Hanuman; fixed to uncrowned topknot Rama, Bharata kneeling with back
  to Hanuman, crown raised toward Rama alone).
- No attribute bleed between staged figures: no extra limbs or heads on
  anyone, ever. Rama reads two-armed, one head.
- One tail per vanara: each monkey-figured staged cast member shows
  exactly one tail, visibly rooted at its own back — one tail per
  figure no matter how many share the frame. FAIL doubled, stray, or
  unrooted tails (slide 16 precedent: Hanuman rendered with two tails).
- Paired attributes match, both alike: ears, eyes, limbs, and ornaments
  are described once, identically, with "both alike" wording — never
  two different types on one figure. FAIL mixed pairs (Hanuman
  precedent: "tall pointed vanara ears" rendered as two different ear
  types, sometimes pointed one side and round the other; fixed to
  "small round human-type ears, both alike" in the repository, both
  rosters, and all panel prompts, plus the corrected sheet). Zoom ears
  on every vanara critique: hair hides one side, which is where the
  mismatch breeds.
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
  on the ground". Heavy-headed weapons (gada, mace, axe) can never
  balance on end: "planted upright" is not a support for them — FAIL
  a freestanding vertical weapon as floating. When hands are occupied (joined palms, blessings,
  carrying), remove the weapon from the hands entirely — sling it
  across the back or lay it flat on the ground — and say the hands are
  empty. Fix in the panel prompt (both copies) with that explicit
  object-plausible support, then re-render. Before any PASS, sweep
  every physical prop named in the prompt — staff, vessel, mala,
  cloth, lamp, seat — and name its visible support in the image, one
  per object. Small dark vessels tucked against garments at hips and
  waists hide most often: zoom those zones. No PASS with an
  unaccounted object.
- Seated sages carry no staff: a danda/staff appears ONLY when its bearer is walking or traveling. A seated, meditating, or yoga-pose figure shows NO staff at all — omit it entirely, never "planted beside", "resting nearby", or freestanding (Ch3 slide 2 precedent: Valmiki's staff standing alone beside his seated yoga pose, physically impossible). A staff can never stand on its own. When hands are in dhyana/anjali or otherwise occupied, state the hands empty and the staff absent.
- Projectiles stay connected: every arrow, spear, or thrown weapon must
  visibly join its origin to its target in one straight line — tail at
  the string or hand, tip at or biting into the target. FAIL floating
  shafts that touch neither (slide 17 precedent: an arrow frozen
  mid-air with both ends free) and cross-eyed aim (archer's gaze not on
  the target). The release instant reads best: bow arm extended at the
  target, string hand at the cheek, gaze fixed down the shaft, motion
  told by splinters, dust, or strain — never by a detached object. Fix
  in the panel prompt (both copies), then re-render.
- Name the target: a drawn weapon points AT its intended victim — eye,
  weapon, and target colinear — never at empty space or off-frame when
  the text names who falls (slide 18 precedent: Rama's arrow aimed past
  Vali while the text says it fells him). Phrase aim as geometry
  ("shaft pointing toward Vali, gaze fixed on Vali"), never as
  wound-targeting ("aimed at his chest") — the latter trips the
  provider content filter on the attach shape.
- Clear the firing lane: a drawn weapon threatens no staged figure but
  its target. FAIL any protagonist or bystander standing in the shaft's
  path (slide 22 precedent: Rama's nocked arrow pointing at a kneeling
  Hanuman). Fix in the panel prompt (both copies) with geometry plus
  position — name open ground or water as the aim point AND place every
  other figure behind the bow arm, below the shaft line, or otherwise
  visibly clear of it — then re-render.

### 4. Policy pre-scan (before any spend)

Fail the prompt without rendering when it contains gore lexicon
(blood*, slay*, slaughter, massacre, gore, corpse, severed, dismember*,
decapitat*, entrails, mutilat*), death tallies phrased as killing, or
self-harm framing. Rewrite at the source, then render. Fail the prompt
without rendering when any prop noun lacks a support verb: every
staff, vessel, weapon, lamp, and seat must read held, worn, planted,
rested, slung, or set down somewhere explicit. Vague standees
("beside his kamandalu", "with his staff nearby") fail at $0 — name
the support, then render. Exception: a seated/meditating figure must not name a staff at all — omit the noun entirely (never "planted beside his hand"); a staff named for a seated figure fails at $0. Fail the prompt without rendering when it
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
- Token hygiene: never print full file contents — diffs, counts, and
  hashes only; read in windows and never re-read an unchanged file in
  one session; critique from the 768px thumbnail, full-res only for
  disputed zooms, never re-view after PASS; batch discovery into
  single calls and run gates once per workstream, not per edit.
