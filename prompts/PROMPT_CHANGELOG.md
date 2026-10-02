# Prompt Changelog — podcast stage (Phase 2)

All sources verified in `mythology-texts/mythology podcast/podcast_pipeline.py`.
Downstream contract (frozen): JSON arrays of
`{character, voice, text, text_en}` + trailing emotion tags; `text_en` on
every segment. The bridge and comic stages read only these keys.

## agent1_narration.md — PORTED
- Kept: Kavya sole narrator, Hindi primary, continuity bridge, cover-all-plot-points, JSON schema, emotion tags, example.
- Strengthened: bilingual parity is now an explicit invalidation rule ("an object without `text_en` invalidates the whole output") — the old prompt asked for it; the new one makes missing `text_en` a hard failure so QA has teeth.
- Muse adaptation: dropped the `<think>...</think>` chain-of-thought wrapper (a local-Gemma convention). Reasoning now runs in the API thinking budget (`MUSE_THINKING_BUDGET=xhigh`); the prompt spends output tokens on story only and forbids prose outside the ```json fences.

## agent2_narration_qa.md — PORTED
- Kept: all six checks (completeness, pacing, engagement, accuracy, format, parity) and the APPROVED/REJECTED verdict contract.
- Muse adaptation: same `<think>` removal; verdict must stand on the final line for machine parsing.

## agent3_reflection.md — REWRITTEN (the content upgrade)
- Kept: single-voice Kavya, 4–6 segments, no re-narration, conversational-yet-scholarly, JSON schema, emotion tags, bilingual parity.
- New three-part structure inside each passage (both languages, fixed labels, fixed order):
  Hindi `प्रश्न:` → `विवेचना:` → `जीवन-सूत्र:`; English `Question:` → `Reflection:` → `Takeaway:`.
- New concreteness rule: every takeaway must be a usable action/decision/lens ("what should the listener DO, NOTICE, or DECIDE differently"), and the question must be chapter-specific, not generic philosophy.
- Why text-internal labels instead of new JSON keys: the bridge and comic stages consume `text`/`text_en` only, so the upgrade is backward-compatible — no downstream code changes.

## agent4_reflection_qa.md — PORTED + extended
- Kept: depth, insight, relevance, modern-connection, flow, format, parity checks.
- New gates 7–8: three-part structure (labels present, correctly ordered, in both languages) and takeaway concreteness (reject platitudes). These make Agent 3's upgrade enforceable rather than aspirational.

## Phase 7 — conciseness + reviewer merge + effort split (SUPERSEDES agent2/agent4)

- `reviewer.md` (NEW) replaces agent2_narration_qa.md + agent4_reflection_qa.md,
  which are DELETED. One template, two rubrics (A narration checks 1–7,
  B reflection checks 1–10); the driver prefixes the user message with
  `PHASE: NARRATION — apply Rubric A only.` (or REFLECTION/B), so no
  template-substitution logic is needed. Verdict contract unchanged
  (APPROVED/REJECTED on the final line). Saves no calls — halves drift.
- agent1: +WORD BUDGET (~60–90w Hindi/segment; full spend only on turning
  points) and ONE-IDEA-PER-SEGMENT anti-redundancy rule.
- agent3: +WORD BUDGET (~120–180w Hindi/passage, split across Q/R/T) and
  NO-REDUNDANCY rule (takeaway must CONVERT, never restate).
- reviewer rubrics gain conciseness reject-grounds (A.7, B.10) so QA trims
  bloat through the existing retry loops instead of a new agent.
- Thinking split (code, not prompts): creators at env default (xhigh);
  QA judges at high. Same verdicts expected at roughly half the QA cost.

## Phase 7 fix — emotion-tag rules restored to reviewer (live Ch.1 rc=1)

Live conciseness proof hit the lengths (narr 84w, refl 129w) but QA deadlocked:
reviewer.md never mentioned emotion tags, so the reflection judge invented an
anti-tag rule ("fourth element after Takeaway — delete all tags") while
`validate_segments` mandates tags: unsatisfiable loop. Narration died in the
validator loop (final segs untagged). Fix: reviewer gains A.8/B.11 (tags
REQUIRED on every text/text_en, explicitly delivery markup, never to be
removed); agent1/agent3 gain TAG-COMPLIANCE invalidation teeth incl. final
segments re-scan. No contract change (tags were always mandatory downstream).

## agent3 takeaway phrasing — do-or-notice lens (comic caption style)
- `agent3_reflection.md`: takeaway must be phrased as a do-or-notice lens
  ("write your three rules of life", "once a day, without a mirror,
  notice ...") so storyboard insight slides can compress it into Q&A panel
  captions. No contract change.
