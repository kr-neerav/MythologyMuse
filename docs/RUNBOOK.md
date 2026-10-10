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
`bridge_stage.py` (deterministic) → `comic_stage.py` (E/P/S/F/V/H) →
`av_map_stage.py` (deterministic script→slide map for the video builder) →
`metadata_stage.py` (deterministic YouTube + Spotify copy).
Re-run any stage alone:

```bash
python3 tools/podcast_stage.py --chapter <id> --dry-run [--dry-run-reject-first] [--no-auto-recap]
python3 tools/bridge_stage.py   --chapter <id>
python3 tools/comic_stage.py    --chapter <id> --dry-run [--redo-comic]
python3 tools/av_map_stage.py   --chapter <id> [--semantic] [--enrich-only]
python3 tools/metadata_stage.py --chapter <id>
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
| `av_mapping_<ch>.json` | av-map | one chunk per script segment (audio order) with slide numbers + `studio_images/` paths; `images_missing` flags renders not yet on disk; each chunk also carries `panels` (per-slide image prompt, title, `share`, and `start_s`/`end_s` cues per language — absolute once every chunk has a WAV, else relative) plus per-language `audio` durations; default rule is positional, `--semantic` uses the Muse judge, `--enrich-only` re-cues an existing mapping without touching its slides |
| `comic_entities_preview_<ch>.json` | comic (dry-run) | what P would append (repo untouched) |
| `comic_storyboard_<ch>.json` | comic | ordered scene/insight slides |
| `comic_muse_prompts_<ch>.json` | comic | Muse-native prompt texts (render these separately; Flow output removed) |
| `comic_render_plan_<ch>.json` | comic | render handoff: roster (sheet prompts + response-id slots) + per-slide turns (`muse_prompt`, subjects, cookbook size) |
| `comic_progress_<ch>.json` | comic | resume manifest: live flag + completed board/flow/Hindi counts + Layer-A verdict |
| `comic_hindi_partial_<ch>.json` | comic | translated `{slide, fields}` items so far (removed once H completes) |
| `upload_metadata_<ch>.json` | metadata | copy-paste upload copy: one YouTube block (Hindi default + English localized, tags, timestamp chapters, dual-audio how-to) + two Spotify episodes (`hi`/`en`, same season/episode, `[Hindi]`/`[English]` suffixes); per-language durations feed timestamp chapters only when the audio manifest covers every script segment, else untimed |

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
| `video_<ch>_<lang>.mp4` | video | assembled video: Ken Burns stills cut to the TTS track |
| `video_manifest_<ch>.json` | video | per-lang segments, motion, durations, ffmpeg command; every segment/shot is a cue-sheet row (`slide`, `start_s`/`end_s`, `muse_prompt`, `title`) |

The per-mythology `entities/entity_repository.json` grows live chapter by
chapter (E dedups, P appends with `first_seen`). Dry runs never mutate it.

## Audio narration (separate step, Gemini TTS — explicit trigger only)

Not part of `run_chapter.py`. Synthesizes one WAV per script segment per
language from `script_<ch>.json` (`text_en` for English, `text` for Hindi),
for later video assembly:

```bash
python3 tools/generate_audio_gemini.py --chapter Book_1_Bala_Kanda_Chapter_1 --dry-run
python3 tools/generate_audio_gemini.py --chapter Book_1_Bala_Kanda_Chapter_1 --lang en   # English only
python3 tools/generate_audio_gemini.py --chapter Book_1_Bala_Kanda_Chapter_1 --lang both # default
```

Model: `gemini-3.8-flash-lite-tts` (Google's cost-efficient single-speaker
workhorse; override with `GEMINI_TTS_MODEL`, e.g. `gemini-3.8-flash-tts` for
max fidelity). Needs `GEMINI_API_KEY` in `.env` (live runs only; dry runs
write silent WAVs + manifest, no key, no network). Same voice both languages
(`--voice`, default `Leda`) keeps the video narrator consistent; outputs land
in `audio_en/` + `audio_hi/` with an `audio_manifest_<ch>.json` chunk map
(file, duration, source). Reruns resume: only chunks missing from a previous
*live* manifest are re-synthesized (dry-run placeholders never count).

Tier 1 pacing (confirmed quota: 10 RPM / 10k TPM / 100 RPD per TTS model):
calls go out sequentially with `--delay-s` (default 7s, `GEMINI_TTS_DELAY_S`)
between them — at most ~8.5 RPM even if synthesis returned instantly — and
429s honor the server's `Retry-After`. One 25-chunk chapter at `--lang both`
costs 50 requests, half the daily quota, so the tool prints its plan up front
and refuses to run past `--daily-budget` (default 100,
`GEMINI_TTS_DAILY_BUDGET`) unless given `--ignore-budget`.

## Video assembly (explicit trigger only, needs ffmpeg on PATH)

Not part of `run_chapter.py`. Cuts one MP4 per language from the AV mapping
plus the TTS WAVs — each audio chunk sets the hold duration, and a chunk
carrying several images splits its time by the mapping's panel shares
(even split in v1) so every mapped slide stays on screen. The manifest
records per-slide `start_s`/`end_s` cues plus each still's `muse_prompt`:

```bash
python3 tools/build_video.py --chapter Book_1_Bala_Kanda_Chapter_1 --dry-run   # plan only, no ffmpeg
python3 tools/build_video.py --chapter Book_1_Bala_Kanda_Chapter_1 --lang en    # one MP4
python3 tools/build_video.py --chapter Book_1_Bala_Kanda_Chapter_1 --lang both  # default: en + hi
```

Motion (calm by default — pull-outs and pans never crop the frame):
`--motion kenburns` (default) drifts narration scenes — alternating slow
pull-out (1.15→1.0, which reveals instead of cropping) and low pans with a
slow sway and light grain — via ffmpeg `zoompan` from a 4x plate; holds
longer than 8s are renewed into fresh shots (same still, new move,
dissolved). Text-heavy discussion shots hold still for readability even
under kenburns. `--motion static` holds everything. `--transition xfade`
(default) dissolves 0.5s between images (`--xfade-s` to change,
auto-clamped below the shortest segment); `--transition cut` is a hard
cut. Outputs land next to the audio
as `video_<ch>_<lang>.mp4` with a `video_manifest_<ch>.json` timing record
(segments, motion, durations, exact ffmpeg command). Missing audio or
unrendered images fail loud (rc=2, names listed); `--skip-missing` shows a
chunk's rendered images only instead of failing.

One video, two narrations: `build_video.py --chapter <id> --dual` cuts the
picture once — to the longer of the English/Hindi tracks — and muxes both
as labeled audio tracks (`eng` + `hin`) into `video_<ch>_dual.mp4`, the
shorter padded with trailing silence so both run exactly the video length.
It also writes both padded full-length WAVs (`audio_track_<ch>_en.wav`,
`audio_track_<ch>_hi.wav`) for direct upload as YouTube's additional audio
track.

Background music: `--music assets/music/meditation_impromptu_01.mp3`
(Kevin MacLeod, CC-BY 4.0 — credit required, see
`assets/music/CREDITS.md` for the description text) loops a quiet bed
(default `--music-db -14`) under the narration in every mode, faded in/out
at the ends — it carries the tail where the shorter narration has already
ended. Works with `--lang` singles and `--dual` alike.

## Chapter art loop (token-efficient; comic-art-critique skill governs verdicts)

The skill judges; this is the cheap execution shape. Parent never views
full-res renders — workers view thumbnails and return verdicts only.

0. Pre-trim gate ($0): `python3 tools/pretrim.py --chapter <id>`. Any flagged
   slide gets its apex-beat trim (storyboard + Hindi + subjects + prompt in
   both copies) before its first paid round. Entry count is a proxy: slides
   already resolved with background hints (backs/blur, no staged faces)
   need no trim.
1. Prescan batch ($0): `python3 tools/loop_batch.py --chapter <id> --slides 1,2,...`
   (or `--sheets Ref,...`). Any rc=1 is a prompt rewrite at the source, no spend.
2. Generate: same command with `--live`. One compact JSON line per target.
3. Frame gate without viewing: `python3 tools/check_frame.py <candidate>`
   (exit 1 = matte/border/letterbox). Crop fixes need no re-render:
   `check_frame.py <candidate> --crop-out <candidate_N+1>` then re-gate the crop.
4. Packets: `python3 tools/critique_packet.py --chapter <id> --slide <N>
   --candidate <path>` writes `/tmp/critique_<ch>_<target>.json` plus a 768px
   thumbnail. The packet holds spec, Hindi text, both prompt copies, staged
   roster rows, and ledger standing — everything a worker needs, nothing more.
5. Fan out viewing: one worker per slide (parallel, read-only checkout each),
   each viewing only its thumbnail + packet. Worker brief template:
   "Critique this one render under the comic-art-critique skill. Inputs are in
   <packet>. View the thumbnail for staging/frame/face checks; open the
   full-res candidate ONLY to zoom prop-support zones (hands, hips, ground
   contact). Return verdict PASS, or FAIL with one line per finding (rule
   broken, what is seen, exact source-layer fix). Do not re-render."
6. Parent applies the cited source fix, spends the next round via
   `studio_loop.py --live` (max 3 rounds x 1 candidate per image), finalizes
   passes with `python3 tools/finalize.py --chapter <id> --slide <N>`
   (sheets also refresh `sheet_verdicts.json`).

Text (English + Hindi) is immutable throughout.

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
