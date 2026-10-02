# MythologyMuse Studio — chapter review (text + images)

Local browser review for `MythologyMuse` text outputs plus mock image
previews. Mock-only in v1: no Muse calls, no spend, no network.

## Start

```bash
cd /Users/neerav/Documents/Projects/MythologyMuse/studio
python3 server.py --port 8775
```

Then open http://localhost:8775 in a browser.

## What it does

* Lists chapters under one `--mythology` root (default
  `mythologies/ramayana_dutt`). Per-mythology isolation: the server refuses
  paths outside that root.
* Shows the chapter bundle read-only from pipeline outputs: storyboard
  slides, `muse_prompt` per slide, Hindi board, eval verdict + manifest,
  render-plan roster/subjects/size.
* Chapter + per-slide review: `approved` / `needs_redo` + note. Redo only
  flags intent — actual regeneration stays on the CLI with your approval
  (`run_chapter.py --chapter <id> [--redo-comic]`). The server never calls
  Muse.
* Mock image previews: deterministic SVG placeholders per roster subject
  (sheet, 2:3) and per slide (panel, 16:9) so the text↔image mapping can be
  reviewed with zero spend. Real Muse Image wiring is an explicit later
  step, behind its own approval gate.

## State

Reviews live beside pipeline outputs, never in place of them:

```
mythologies/<name>/outputs/<chapter>/studio_review_<chapter>.json
```

Copy-never-move: the studio only reads pipeline files and writes that one
review file (atomic tmp+replace). It never moves, edits, or deletes
pipeline outputs or the entity repository.

## Image generation (live spend, UI-triggered only)

Each roster sheet and each slide has a **Generate** button: 2 candidates
for that one item, nothing bulk. A browser `confirm()` names the spend
before anything fires, and an optional tweak joins the prompt.

* Key: read at call time from the museimages `.env`
  (`MIDJOURNEY_API_KEY` + endpoint, your file already points at
  `api.meta.ai` with provider `metamuse`). Override the folder with
  `MUSEIMAGES_DIR=/path/to/museimages`. The key is never copied, logged,
  or returned — `/api/key-status` reports only ready/missing. Nothing is
  committed: `.env` is gitignored in both repos.
* Transport is Meta's Responses API (`POST /v1/responses`,
  `muse-image-1.0`), per the anchored-generation recipe — not the legacy
  images endpoint. Sheets chain into a per-chapter conversation and record
  per-file response ids; picking a candidate registers its id as the
  anchor. Panels chain from the first picked anchor (`previous_response_id`)
  and file-attach picked finals that predate response ids (max 2).
* Style words ride on every prompt (museimages canon + `no photorealism`),
  so sheets and panels render comic, not photographic. Panels additionally
  end with `no speech bubbles, no text, single comic panel`.
* Files land under `outputs/<chapter>/studio_images/` (per-mythology,
  beside — never inside — pipeline outputs). Without a key the buttons
  refuse with `image key not configured` and mocks remain.
* Panel lineage (panels can never silently ignore finals): every panel
  render appends endpoint (/edits vs fallback), refs actually sent by
  name, omitted-cast count, and the full effective prompt to
  `studio_images/panel_log.json`. The UI shows it under the panel and
  after each job; a fallback renders as an explicit warning, never a
  quiet success. Reference faces are declared authoritative over stale
  embedded descriptions in the prompt text.
* Per-slide cast review (no upfront bulk needed): each slide shows its
  characters underneath with one card per character —
  **missing** (placeholder + Generate), **review** (both candidates side
  by side with Use 1 / Use 2 + Regenerate), **ready** (your pick,
  resurfaced + Regenerate). Picking copies to `sheet_<ref>_final.jpg` and
  keeps both candidates; regenerating refreshes candidates only, never
  silently dropping your pick. Generate panel unlocks only when every
  required character has a pick, and panels attach picked finals (max 2)
  as reference images. Generate all character sheets stays as one
  top-level batch: one confirm, sequential, reloads at the end.
* Per-slide cast readiness: each slide lists its required characters as
  ready/missing chips. Generate panel stays disabled until every required
  character sheet exists (hover shows who is missing); scenes never gate.
  Generate missing characters builds exactly that slide's absent sheets,
  then reloads to unlock the panel.

## Tests

```bash
cd /Users/neerav/Documents/Projects/MythologyMuse/studio
python3 test_studio.py
python3 ../tools/selftest.py
```
