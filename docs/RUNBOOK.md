# MythologyMuse Runbook

Text pipeline only — no audio, no image rendering. One chapter per command;
there is deliberately NO corpus-wide batch mode in v1.

## Setup (once)

```bash
cp .env.example .env   # then set MUSE_API_KEY (never commit .env)
pip install -r requirements.txt   # stdlib only today; pyyaml reserved
```

Model: Muse Spark 1.3 (contributor), thinking `xhigh` — all env-driven
(`MUSE_MODEL`, `MUSE_THINKING_BUDGET`). Creators run at the env default;
QA judges (podcast reviewer, comic eval) run one tier down at `high`.
`MUSE_MAX_RETRIES` (default 3) bounds transient-error retries per call.
Dry runs need no key and make no network calls.

Continuity is automatic: each chapter carries a rolling brief built from
the previous chapter's approved narration (first two segments, ~500 chars).
Disable per-run with `podcast_stage.py --no-auto-recap`, override with
`--prev-recap "<text>"`. The podcast summary prints an advisory length
audit (`audit-narration` / `audit-discussion`: avg words/segment vs the
~90/~180 budgets plus outlier flags) — report only, nothing truncates.

Self-test (no key, no network — run after any tools/prompts change):

```bash
python3 tools/selftest.py
```

## Run one chapter (dry-run first, always)

```bash
python3 tools/run_chapter.py --chapter Book_1_Bala_Kanda_Chapter_1 --dry-run
```

Stages, in order: `podcast_stage.py` (Agents 1→reviewer→3→reviewer) →
`bridge_stage.py` (deterministic) → `comic_stage.py` (E/P/S/F/V/H).
Re-run any stage alone:

```bash
python3 tools/podcast_stage.py --chapter <id> --dry-run [--dry-run-reject-first] [--no-auto-recap]
python3 tools/bridge_stage.py   --chapter <id>
python3 tools/comic_stage.py    --chapter <id> --dry-run [--redo-comic]
```

Live (spends API calls — one chapter to start):

```bash
python3 tools/run_chapter.py --chapter Book_1_Bala_Kanda_Chapter_1
```

Resume: finished podcast (`script_*.json` present) and live-PASSed comic
(`comic_eval_*.json` verdict PASS from a live run — dry-run fixture PASSes
never count) are skipped automatically; force with
`--redo-podcast` / `--redo-comic`. Comic also resumes *per stage*: a
live-stamped `comic_progress_<ch>.json` records which of board / flow packs /
Hindi board are done, and a rerun adopts finished stages (E/S skipped when
the board is saved, F/H pick up from saved packs / partial translations),
running only what is pending. A fresh board drops stale downstream files.
A judge call that comes back empty is retried on its own and, if all
attempts miss, stops the run without rebuilding — only an explicit
verdict FAIL retries the pipeline, since only that means the board itself
is bad.
Exit codes on every stage:
`0` done/PASS · `1` QA/eval budget exhausted (best-effort files kept) ·
`2` bad invocation · (bridge only) `3` broad `text_en` parity gap.

## Output catalog (`mythologies/<name>/outputs/<chapter>/`)

| File | Stage | Contents |
|---|---|---|
| `narration_<ch>.json` / `narration_qa_<ch>.md` | podcast | Kavya story segments / reviewer verdict (Rubric A) |
| `discussion_<ch>.json` / `discussion_qa_<ch>.md` | podcast | Q→A→takeaway reflection / reviewer verdict (Rubric B) |
| `script_<ch>.json` | podcast | narration + discussion combined |
| `english_narration_<ch>.txt` / `hindi_narration_<ch>.txt` | bridge | flat lines, emotion tags stripped |
| `comic_entities_preview_<ch>.json` | comic (dry-run) | what P would append (repo untouched) |
| `comic_storyboard_<ch>.json` | comic | ordered scene/insight slides |
| `comic_muse_prompts_<ch>.json` | comic | Muse-native prompt texts (render these separately; Flow output removed) |
| `comic_render_plan_<ch>.json` | comic | render handoff: roster (sheet prompts + response-id slots) + per-slide turns (`muse_prompt`, subjects, cookbook size) |
| `comic_progress_<ch>.json` | comic | resume manifest: live flag + completed board/flow/Hindi counts + Layer-A verdict |
| `comic_hindi_partial_<ch>.json` | comic | translated `{slide, fields}` items so far (removed once H completes) |

## Comic failure forensics (`comic_debug_<ch>.jsonl`)

Every comic stage records its exact failing input (full text) plus reply
evidence as one JSON line per failure — read this file first when a live run
dies. Nothing is recorded on success. Partial progress also persists as it
completes: repo entries per designer chunk, storyboard right after Layer A,
muse pack per panel chunk, Hindi translations per chunk — so a later death
never discards reviewable output again. Hindi translates `{slide, fields}`
items only (on-panel text: `on_slide_text` + `question`/`answer`), merged
back onto the English slides by the driver.

## Rendering images (separate step, Muse Image)

The pipeline emits text only. To render, per the [Muse Image anchoring
recipe](https://raw.githubusercontent.com/meta-models/meta-model-cookbook/main/05_muse_image/03_anchored_generation/README.md)
(model `muse-image-1.0`, Responses API):

1. Render one sheet per roster subject from its `image_prompt`; record each
   response id into that subject's `sheet_response_id`.
2. Render each panel chained from its subjects' ids (`previous_response_id`)
   with the slide `muse_prompt` as input, at the slide `size`.
| `comic_storyboard_hindi_<ch>.json` | comic | Hindi on-panel text, structure verbatim |
| `comic_eval_<ch>.json` | comic | verdict + Layer A verdicts + counts |

The per-mythology `entities/entity_repository.json` grows live chapter by
chapter (E dedups, P appends with `first_seen`). Dry runs never mutate it.

## Prompts (`prompts/`)

One reviewer template (`reviewer.md`, rubrics A+B) serves both QA phases —
`agent2_narration_qa.md` / `agent4_reflection_qa.md` were merged into it and
removed. Per-prompt history in `PROMPT_CHANGELOG.md` (+ `_COMIC` suffix file
for comic stages).

## Add a new mythology

1. `cp -r mythologies/ramayana_dutt mythologies/<new_name>/`
2. Replace `sources/` with the new corpus (`Book_*_narrative.json` shape +
   chapter ids `Book_N_..._Chapter_M`), edit `mythology.yaml`, reset
   `entities/entity_repository.json` to `{"corpus": "<new_name>",
   "characters": {}, "scenes": {}}`, clear `outputs/`.
3. `python3 tools/run_chapter.py --mythology mythologies/<new_name> --chapter <FirstChapter> --dry-run`

No shared-code changes; no cross-mythology reads/writes (enforced by the
isolation gate in `muse_client.assert_inside`).

## Troubleshooting

- Bridge rc=3 (parity gap): podcast dropped `text_en` — re-run podcast; the
  gap fraction is tunable via `BRIDGE_MAX_MISSING_FRAC` (default 0.34).
- Stage rc=1: read the `*_qa_*.md` / `comic_eval_*.json` weaknesses, adjust
  the prompt in `prompts/`, re-run with `--redo-*`.
- Live request-shape errors: only `call_muse()` in `tools/muse_client.py`
  touches the wire — fix there, stages are untouched.
- Slow/hung xhigh calls: per-stage token ceilings in each stage module bound
  output+reasoning; QA/eval run at `high` effort by default.
