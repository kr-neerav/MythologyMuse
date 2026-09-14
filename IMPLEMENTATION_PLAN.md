# MythologyMuse — Implementation Plan (APPROVED)

## Goal

Build a clean **MythologyMuse** project (no space) that starts with the
Ramayana-Dutt but is structured from day one for many mythologies: **each
mythology lives in its own self-contained folder** with its own sources,
outputs, entity repo, and config, so adding a new source creates a new folder
and never touches the others. v1 populates only the Ramayana folder, driven
by the Meta Muse model — **text outputs only**: bilingual (Hindi + English)
podcast narration with real-world insight and Q&A-style reflection, bilingual
comic narration text, and the comic image-prompt text used for separate image
generation. Text model: **Muse Spark 1.3 (contributor tier)** with **xhigh
thinking**; API key placeholder until supplied.

## Success Criteria

- `MythologyMuse/` exists with: this plan, shared pipeline tooling,
  `.env.example` (Muse key placeholder), `requirements.txt`, and a
  `mythologies/ramayana_dutt/` folder that is fully self-contained (own
  sources, outputs, entity repo, config).
- One-chapter Ramayana smoke run reproduces the full legacy **text** artifact
  set inside its own folder only: `script_` / `narration_` / `discussion_`
  JSON (each segment with Hindi `text` + English `text_en`),
  `english_narration_` + `hindi_narration_` txt, `comic_storyboard_`
  (+ `_hindi_`) JSON, `comic_flow_prompts_` JSON plus a Muse-native prompt
  text pack, `comic_eval_` PASS.
- Isolation holds: a Ramayana run reads/writes nothing outside
  `mythologies/ramayana_dutt/` except shared read-only tooling; onboarding
  docs describe adding mythology #2 as "new folder, no edits to Ramayana."
- No image files are produced or expected in v1.
- No original files are destroyed (copy, not move); no real API key is
  committed; nothing calls the Muse API until the key is provided.

## Context And Current Facts

- **Source of truth** is the Dutt corpus: top-level
  `ramayana_dutt/Book_<N>_<Kanda>_narrative.json` (7 books, **652 chapters**
  total; Book 1 = 75), built by `mythology podcast/dutt_segment.py` from
  `ramayana_dutt/SOURCE/pg57265.txt / pg57826.txt / pg60188.txt / pg62496.txt`
  (Project Gutenberg Dutt). `mythology podcast/chapter_source.py` is the read
  contract (`Book_*_narrative.json`, chapter id `Book_N_..._Chapter_M`).
- **Current chain** (verified in mythology-texts): `podcast_pipeline.py`
  Agents 1–4 (Kavya bilingual narration `text`+`text_en` → QA → single-voice
  reflection → QA) → `bilingual_bridge.py` (`text_en` →
  `english_narration_*.txt`) → `comic_generation/comic_orchestrator.py`
  (entity extract → dedup into per-corpus `entity_repository.json` →
  storyboard → per-slide Flow prompts → eval, with deterministic Layer A
  gates) → `comic_hindi_storyboard.py`. `uber_pipeline_bilingual.py` is the
  batch driver; `generate_chapter_gemini.py` is the cloud-API analogue to copy
  for the Muse client. Skill prompts in `skills/` are the versioned operating
  prompts.
- Today's layout mixes corpora under one tree — this plan deliberately does
  not replicate that.

## Constraints And Non-goals

- **Copy, not move**: originals stay untouched.
- **Text outputs only**: image rendering, audio TTS, and image binaries are
  explicit non-goals.
- **Per-mythology isolation:** no shared mutable state between mythologies.
  Shared pipeline code is read-only tooling parameterized by `--mythology`.
- **Prompt review is in scope:** every AI prompt is reviewed and, where
  needed, rewritten for Muse.

## Key Decisions

1. **Location/name:** sibling `Projects/MythologyMuse` (no space).
2. **Self-contained per-mythology layout:**
   `MythologyMuse/mythologies/<mythology>/` owns `sources/`, `outputs/`,
   `entities/entity_repository.json`, and `mythology.yaml`; shared stateless
   tooling at `MythologyMuse/tools/`, versioned prompts at
   `MythologyMuse/prompts/`. v1 creates only `mythologies/ramayana_dutt/`.
   *Rejected:* one flat tree with `--corpus` over mixed folders (leaks state
   across mythologies; onboarding #2 becomes a refactor, not a folder copy).
3. **Reuse, not rewrite:** generalize `chapter_source`, `bilingual_bridge`,
   Layer A checks, and schemas from hardcoded `ramayana_dutt` paths to a
   `--mythology` root parameter; replace only the LLM client layer.
   *Rejected:* from-scratch rewrite (breaks diff-compatibility, no benefit).
4. **Full prompt audit and update** (Agent 1, 2, 3 — main upgrade, 4,
   storyboard, entity-prompt-designer, slide-to-flow, Hindi translate, evals).
   Keep JSON-only contracts, emotion tags, and `text`/`text_en` parity
   byte-identical; retune voice, thinking budget, and temperatures for Muse.
   Layer A gates and the bridge are reused as-is (not LLM prompts).
5. **Single-voice structured Q&A:** Kavya stays the sole voice; each
   reflection segment gets `question` → `answer` → `real_world_takeaway`.
   *Rejected:* two-speaker dialogue (breaks Agent 4 gate + comic contract).
6. **Muse integration:** one `tools/muse_client.py` text adapter, Meta Model
   API base `https://api.meta.ai/v1`, model Muse Spark 1.3 (contributor),
   thinking `xhigh` — all env-driven (`MUSE_MODEL`,
   `MUSE_THINKING_BUDGET=xhigh`). No image API calls in v1.
7. **Secrets:** root `.env.example` only; per-mythology folders hold no
   secrets; real key never enters git.

## Recommended Approach

Thin-adapter port with a prompt-quality pass, text-only, on the isolated
layout: seed `mythologies/ramayana_dutt/sources/` with the 7 narrative JSONs
(+ `SOURCE/` + mapping/index docs) as frozen inputs; add `tools/muse_client.py`
(Muse Spark 1.3, xhigh thinking) + a per-mythology driver (`--mythology
ramayana_dutt --chapter Book_1_Bala_Kanda_Chapter_1`) modeled on
`generate_chapter_gemini.py` (podcast → bridge → comic-text → Hindi
storyboard); audit prompts into `prompts/` — verbatim port except Agent 3
(structured question/answer/takeaway), storyboard (tighter slide schema +
on-slide text discipline), flow/entity prompts (legacy Flow shape + Muse-native
prompt-text variant, both text files), eval rubrics (same verdict contracts,
Muse-tuned wording). Validate by diffing against the intact
`gemini/Book_1_Bala_Kanda_Chapter_1` text reference: eval PASS + Layer A gates,
plus an isolation check and a mythology-#2 skeleton dry-run.

## Work Plan

- **Phase 0 — Scaffold:** `MythologyMuse/` tree, Ramayana source copy,
  `IMPLEMENTATION_PLAN.md`, `.env.example`, `requirements.txt`, git repo.
- **Phase 1 — `tools/muse_client.py`:** env-keyed Muse text client (xhigh
  thinking, timeouts/retries, dry-run fixtures needing no key).
- **Phase 2 — Podcast prompts + stage:** audit Agents 1–4 into `prompts/`;
  rewrite Agent 3 to structured Q&A; keep `text`/`text_en` parity + QA loops.
- **Phase 3 — Bridge (reuse):** path-parameterized bridge → narration txts.
- **Phase 4 — Comic text prompts + stages:** per-mythology entity repo; flow
  prompts + Muse-native prompt text pack + Hindi storyboard. No binaries.
- **Phase 5 — Driver + smoke:** `--mythology ramayana_dutt --chapter
  Book_1_Bala_Kanda_Chapter_1 --dry-run`, then live on key; eval PASS;
  isolation + skeleton-#2 checks.
- **Phase 6 — Docs:** README, "add a new mythology" procedure,
  prompt-changelog.

## Validation Plan

- Dry-run (no key): full text file set under
  `mythologies/ramayana_dutt/outputs/`; Layer A checks pass; `text_en` parity
  passes; isolation check (zero reads/writes outside the mythology folder);
  skeleton second-mythology folder validates with no code changes.
- Live (on key): `comic_eval` PASS under Muse Spark 1.3 + xhigh; shapes
  diff-clean vs the `gemini/...Chapter_1` text reference; prompt pack present.
- Hygiene: secrets-clean; `*.env` ignored. Highest-risk step: first live Muse
  call — quarantined behind dry-run + single-chapter probe.

## Risks / Rollback

- Muse request shape is conditional on secondary sources (model ID, tier, and
  thinking confirmed by owner — only env values change if details differ).
- Cost/rate limits → sequential driver, resumable outputs, per-mythology repo
  backup/restore.
- Rollback: delete the new folder (or one `mythologies/<name>/` for scoped
  rollback); originals untouched (copy semantics).

## Open Questions

None — resolved: (1) Muse Spark 1.3 contributor + xhigh thinking, (2)
copy-not-move, (3) single-voice structured Q&A, (4) self-contained
per-mythology folders.

## Sources

- [Meta model cookbook — Muse Image via Responses API](https://github.com/meta-models/meta-model-cookbook/blob/main/05_muse_image/README.md)
- [muse-image-mcp — endpoints `/images/generations`, `/images/edits`, `/responses`; default model `muse-image-1.0` at `https://api.meta.ai/v1`](https://kevintsai1202.github.io/muse-image-mcp/)
