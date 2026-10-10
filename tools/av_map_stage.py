#!/usr/bin/env python3
"""MythologyMuse — AV mapping stage.

Deterministic, model-free: maps each ``script_<chapter>.json`` segment (one
TTS audio unit) to storyboard slide image(s), so a video builder knows which
image(s) to hold on screen while each audio chunk plays.

Rule (documented, no guessing): narration segments -> scene slides,
discussion (Q&A) segments -> insight slides, distributed evenly in chapter
order. Every slide in a group is used exactly once when slides outnumber
segments (a chunk may then carry several images); when segments outnumber
slides, slides repeat by nearest-neighbor with endpoints pinned. A group
with zero segments folds its slides into the other group.

Reads (under <mythology>/outputs/<chapter>/):
    script_<chapter>.json  (else narration_ + discussion_ fallback, bridge order)
    comic_storyboard_<chapter>.json
    comic_muse_prompts_<chapter>.json  (image prompts, optional but expected)
    audio_<lang>/chunk_*.wav  (durations only; absent audio still maps)
Writes:
    av_mapping_<chapter>.json

With ``--semantic`` a Muse judge (high effort, ``prompts/av_semantic_map.md``)
pairs segments to slides by meaning instead of position; deterministic
repair still guarantees full coverage, and judge failure falls back to the
positional rule with a warning. ``--dry-run`` forces the positional rule
(no network). With ``--enrich-only`` the slide assignment of an existing
mapping is kept and only images, prompts, and timings are refreshed —
use it after audio lands, or to keep a semantic pairing while re-cueing.

Chunk shape (one per script segment, audio order):
    {"chunk": 1, "kind": "narration", "script_index": 0,
     "slides": [1, 2], "images": ["studio_images/slide_01_final.jpg", ...],
     "images_missing": [],
     "audio": {"en": {"file": "audio_en/chunk_001.wav", "duration_s": 4.2},
               "hi": {... or None}},
     "panels": [{"slide": 1, "image": "studio_images/slide_01_final.jpg",
                 "image_missing": False, "muse_prompt": "Render Rama ...",
                 "slide_label": "Slide01 - ...", "title": "...", "type": "scene",
                 "share": 0.5,
                 "en": {"start_s": 0.0, "end_s": 2.1, "duration_s": 2.1},
                 "hi": None}]}

``images`` paths are relative to the chapter dir. ``images_missing`` lists
expected renders not yet on disk (e.g. chapter not yet rendered) — the
builder should treat those as gaps, not as done. ``panels`` carries the
same slides in order with the image prompt behind each render (so a reader
knows what is in the image without reopening the comic files) plus the
cue timing: absolute ``start_s``/``end_s`` seconds on each language's
audio timeline when every chunk has a WAV for that language, else None
with ``share`` (fraction of the chunk, even split in v1) so the builder
can still cue each slide in order.

Exit codes (match the bridge contract):
    0  success
    2  usage / missing inputs (no script or no storyboard slides)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from muse_client import assert_inside, call_muse, resolve_mythology_root  # noqa: E402
from bridge_stage import strip_emotion_tags  # noqa: E402
from podcast_stage import extract_json_array  # noqa: E402

STRATEGY = ("narration->scene, discussion->insight; "
            "even contiguous distribution v1")
STRATEGY_SEMANTIC = ("llm-semantic-v1 (Muse judge pairs by meaning; "
                      "deterministic repair fills gaps)")
MAP_TOKENS = 16384
MAP_ATTEMPTS = 3
_SLIDE_IMG_RE = re.compile(r"slide_(\d+)_final\.jpg$")


def is_discussion(seg: dict) -> bool:
    """Legacy labeled Q&A segments open with the question word.

    Kept for pre-change artifacts whose reflections carry spoken labels
    (प्रश्न:/Question: ...). New label-free reflections carry no marker, so
    split_script prefers the positional split via narr_count (always known
    when narration_<chapter>.json sits next to the script); this fallback
    only classifies scripts whose narration file is missing.
    """
    text = (seg.get("text") or "").lstrip()
    text_en = (seg.get("text_en") or "").lstrip()
    return text.startswith("प्रश्न:") or text_en.startswith("Question:")


def split_script(script: list, narr_count: int | None = None
                 ) -> tuple[list[int], list[int]]:
    """Split script into (narration indices, discussion indices).

    Positional split (script is narration ++ discussion) wins when the
    narration file tells us the boundary; otherwise per-segment markers.
    """
    if narr_count is not None and 0 <= narr_count <= len(script):
        return list(range(narr_count)), list(range(narr_count, len(script)))
    narr = [i for i, s in enumerate(script) if not is_discussion(s)]
    disc = [i for i, s in enumerate(script) if is_discussion(s)]
    return narr, disc


def distribute(n_seg: int, slides: list[int]) -> list[list[int]]:
    """Assign slide numbers to each of n_seg segments (order preserved).

    Slides outnumber segments: contiguous partition, every slide used
    exactly once. Segments outnumber slides: nearest-neighbor repeat with
    endpoints pinned (first segment -> first slide, last -> last).
    """
    if n_seg <= 0:
        return []
    if not slides:
        return [[] for _ in range(n_seg)]
    n_slides = len(slides)
    if n_slides >= n_seg:
        return [slides[(i * n_slides) // n_seg:((i + 1) * n_slides) // n_seg]
                for i in range(n_seg)]
    if n_seg == 1:
        return [list(slides)]
    last = n_slides - 1
    # round(i * last / (n_seg - 1)) in integer math; endpoints exact.
    return [[slides[(2 * i * last + (n_seg - 1)) // (2 * (n_seg - 1))]]
            for i in range(n_seg)]


def resolve_images(chapter_dir: Path, slide_nums: list[int]
                   ) -> tuple[list[str], list[str]]:
    """Map slide numbers to studio_images finals on disk."""
    known: dict[int, str] = {}
    img_dir = chapter_dir / "studio_images"
    if img_dir.is_dir():
        for p in img_dir.glob("slide_*_final.jpg"):
            m = _SLIDE_IMG_RE.search(p.name)
            if m:
                known[int(m.group(1))] = f"studio_images/{p.name}"
    found, missing = [], []
    for n in slide_nums:
        name = known.get(n, f"studio_images/slide_{n:02d}_final.jpg")
        if (chapter_dir / name).is_file():
            found.append(name)
        else:
            missing.append(name)
    return found, missing


def load_slide_prompts(chapter_dir: Path, chapter: str
                       ) -> tuple[dict[int, dict], str | None]:
    """Slide -> {muse_prompt, slide_label} from the comic muse pack.

    Returns ({}, source_or_None): a missing/unreadable pack is not fatal —
    panels then carry muse_prompt None and the mapping names its source.
    """
    path = chapter_dir / f"comic_muse_prompts_{chapter}.json"
    if not path.is_file():
        return {}, None
    try:
        recs = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}, None
    out: dict[int, dict] = {}
    if isinstance(recs, list):
        for r in recs:
            if isinstance(r, dict) and isinstance(r.get("slide"), int):
                out[r["slide"]] = {"muse_prompt": r.get("muse_prompt"),
                                   "slide_label": r.get("slide_label")}
    return out, path.name


def probe_audio_durations(chapter_dir: Path, n_seg: int) -> dict[str, list]:
    """Per-language WAV durations in script order (None per missing chunk).

    Probes the files (ground truth); width matches generate_audio_gemini
    and build_video so chunk_N lines up with script_index N - 1.
    """
    import wave as _wave

    width = max(3, len(str(n_seg)))
    out: dict[str, list] = {}
    for lang in ("en", "hi"):
        durs: list = []
        for s in range(n_seg):
            p = chapter_dir / f"audio_{lang}/chunk_{s + 1:0{width}d}.wav"
            if not p.is_file():
                durs.append(None)
                continue
            try:
                with _wave.open(str(p), "rb") as w:
                    rate = w.getframerate() or 24000
                    durs.append(round(w.getnframes() / float(rate), 3))
            except Exception:
                durs.append(None)
        out[lang] = durs
    return out


def enrich_chunks(chunks: list[dict], board: list,
                  prompts: dict[int, dict],
                  audio_durs: dict[str, list] | None) -> dict:
    """Attach image prompts + cue timings to mapping chunks (in place).

    ``board`` supplies title/type context (may be empty); ``prompts`` maps
    slide -> {muse_prompt, slide_label}; ``audio_durs`` maps lang ->
    per-script-index durations (None where that chunk has no WAV).
    A language gets absolute cues only when EVERY chunk has audio for it —
    otherwise its cues are None and ``share`` (even split of the chunk in
    v1) orders the slides. Returns the top-level timing summary.
    """
    meta = {s.get("slide"): s for s in (board or [])
            if isinstance(s, dict)}
    audio_durs = audio_durs or {}
    order = sorted(range(len(chunks)),
                   key=lambda k: chunks[k].get("script_index", k))
    valid = {lang: bool(durs) and all(d is not None for d in durs)
             for lang, durs in audio_durs.items()}
    cursor = {lang: 0.0 for lang, ok in valid.items() if ok}
    for k in order:
        c = chunks[k]
        slides = list(c.get("slides") or [])
        pos = c.get("script_index", k)
        audio: dict = {}
        for lang in ("en", "hi"):
            durs = audio_durs.get(lang) or []
            d = durs[pos] if 0 <= pos < len(durs) else None
            width = max(3, len(str(len(chunks))))
            audio[lang] = ({"file": f"audio_{lang}/chunk_{pos + 1:0{width}d}.wav",
                            "duration_s": d} if d is not None else None)
        c["audio"] = audio
        panels = []
        n = len(slides)
        for j, num in enumerate(slides):
            expected = f"studio_images/slide_{num:02d}_final.jpg"
            m = meta.get(num, {})
            p = prompts.get(num, {})
            panel: dict = {
                "slide": num, "image": expected,
                "image_missing": expected in (c.get("images_missing") or []),
                "muse_prompt": p.get("muse_prompt"),
                "slide_label": p.get("slide_label") or m.get("slide_label"),
                "title": m.get("title"), "type": m.get("type"),
                "share": (1.0 / n) if n else 0.0,
            }
            for lang in ("en", "hi"):
                if not valid.get(lang):
                    panel[lang] = None
                    continue
                total = audio[lang]["duration_s"]
                each = round(total / n, 3) if n else 0.0
                start = round(cursor[lang] + j * each, 3)
                if j == n - 1:  # last panel takes the remainder: no 1ms leak
                    end = round(cursor[lang] + total, 3)
                else:
                    end = round(start + each, 3)
                panel[lang] = {"start_s": start, "end_s": end,
                               "duration_s": round(end - start, 3)}
            panels.append(panel)
        c["panels"] = panels
        for lang, ok in valid.items():
            if ok and audio[lang] is not None:
                cursor[lang] = round(cursor[lang] + audio[lang]["duration_s"], 3)
    langs_absolute = sorted(lang for lang, ok in valid.items() if ok)
    return {"timing": ("absolute-s (audio probed)" if langs_absolute else
                       "relative-shares (no complete audio track)"),
            "langs_absolute": langs_absolute}


def load_inputs(chapter_dir: Path, chapter: str
                ) -> tuple[list | None, list | None, int | None]:
    script: list | None = None
    narr_count: int | None = None
    script_path = chapter_dir / f"script_{chapter}.json"
    if script_path.is_file():
        try:
            script = json.loads(script_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            script = None
    else:
        parts = []
        for prefix in ("narration", "discussion"):
            p = chapter_dir / f"{prefix}_{chapter}.json"
            if p.is_file():
                try:
                    segs = json.loads(p.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    return None, None, None
                if prefix == "narration":
                    narr_count = len(segs)
                parts.extend(segs)
        script = parts or None
    if script is not None:
        narr_path = chapter_dir / f"narration_{chapter}.json"
        if narr_path.is_file():
            try:
                narr_count = len(json.loads(narr_path.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, OSError):
                pass
    board: list | None = None
    board_path = chapter_dir / f"comic_storyboard_{chapter}.json"
    if board_path.is_file():
        try:
            board = json.loads(board_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            board = None
    return script, board, narr_count


def build_mapping(script: list, board: list, narr_count: int | None = None
                  ) -> tuple[list[dict] | None, str]:
    """Pure mapping: returns (chunks, error). chunks is None on failure."""
    if not script:
        return None, "no script segments"
    if not board:
        return None, "no storyboard slides"
    narr_idx, disc_idx = split_script(script, narr_count)
    scene = [s["slide"] for s in board if s.get("type") != "insight"]
    insight = [s["slide"] for s in board if s.get("type") == "insight"]
    if not narr_idx and disc_idx:
        # Degenerate: no narration — everything maps as one narration group.
        narr_idx, disc_idx = disc_idx, []
        scene, insight = scene + insight, []
    elif narr_idx and not disc_idx and insight:
        scene = scene + insight
        insight = []
    chunks: list[dict] = []
    for idx_list, slides, kind in ((narr_idx, scene, "narration"),
                                   (disc_idx, insight, "discussion")):
        assignment = distribute(len(idx_list), slides)
        for local, pos in enumerate(idx_list):
            chunks.append({"chunk": 0, "kind": kind,
                           "script_index": pos,
                           "slides": assignment[local]})
    chunks.sort(key=lambda c: c["script_index"])
    for n, c in enumerate(chunks, 1):
        c["chunk"] = n
    return chunks, ""


def load_judge_prompt(prompts_dir: Path | None) -> str:
    """Load the semantic-map judge prompt (repo convention: body after ---)."""
    if prompts_dir is None:
        prompts_dir = Path(__file__).resolve().parent.parent / "prompts"
    text = (Path(prompts_dir) / "av_semantic_map.md").read_text(encoding="utf-8")
    if "\n---\n" in text:
        text = text.split("\n---\n", 1)[1]
    return text.strip() + "\n"


def judge_payload(script: list, board: list,
                  narr_idx: list[int], disc_idx: list[int]) -> dict:
    """Compact judge input: stripped bilingual segments + on-panel slides."""
    kinds = {i: "narration" for i in narr_idx}
    for i in disc_idx:
        kinds[i] = "discussion"
    return {
        "segments": [
            {"script_index": i, "kind": kinds.get(i, "narration"),
             "text": strip_emotion_tags(script[i].get("text") or ""),
             "text_en": strip_emotion_tags(script[i].get("text_en") or "")}
            for i in range(len(script))],
        "slides": [
            {"slide": s.get("slide"), "type": s.get("type"),
             "title": s.get("title"), "on_slide_text": s.get("on_slide_text"),
             "question": s.get("question"), "answer": s.get("answer")}
            for s in board],
    }


def mapping_usable(mapping, n_seg: int, slide_nums: list[int]) -> bool:
    """Structural gate for a judge reply: right shape, known references."""
    if not isinstance(mapping, list) or not mapping:
        return False
    want = set(slide_nums)
    seen_any = False
    for item in mapping:
        if not isinstance(item, dict):
            return False
        idx = item.get("script_index")
        slides = item.get("slides")
        if not isinstance(idx, int) or not (0 <= idx < n_seg):
            return False
        if not isinstance(slides, list):
            return False
        if any(n in want for n in slides):
            seen_any = True
    return seen_any


def validate_mapping(mapping, n_seg: int, slide_nums: list[int]) -> list[str]:
    """Strict report on a judge reply: bad refs, dupes, coverage gaps."""
    problems = []
    if not isinstance(mapping, list):
        return ["mapping is not a JSON array"]
    seen: set[int] = set()
    for item in mapping:
        if not isinstance(item, dict):
            problems.append(f"item is not an object: {str(item)[:60]!r}")
            continue
        idx = item.get("script_index")
        slides = item.get("slides")
        if not isinstance(idx, int) or not (0 <= idx < n_seg):
            problems.append(f"bad script_index: {idx!r}")
            continue
        if idx in seen:
            problems.append(f"duplicate script_index: {idx}")
            continue
        seen.add(idx)
        if not isinstance(slides, list) or not slides:
            problems.append(f"segment {idx} has no slides")
            continue
        for n in slides:
            if n not in slide_nums:
                problems.append(f"segment {idx} names unknown slide: {n!r}")
    for i in range(n_seg):
        if i not in seen:
            problems.append(f"segment {i} unmapped")
    used = {n for item in mapping if isinstance(item, dict)
            for n in (item.get("slides") or []) if n in slide_nums}
    for n in slide_nums:
        if n not in used:
            problems.append(f"slide {n} unused")
    return problems


def repair_mapping(mapping: list, kinds: list[str], slide_nums: list[int],
                   slide_kinds: dict) -> list[dict]:
    """Normalize a judge reply to full coverage. Pure + deterministic.

    Unknown slides are dropped; unmapped segments are filled with the
    positional rule; unused slides join the nearest chunk of matching
    kind (scene->narration, insight->discussion).
    """
    n_seg = len(kinds)
    norm: dict[int, list[int]] = {}
    for item in mapping or []:
        if not isinstance(item, dict):
            continue
        idx = item.get("script_index")
        if not isinstance(idx, int) or not (0 <= idx < n_seg) or idx in norm:
            continue
        norm[idx] = list(dict.fromkeys(
            n for n in (item.get("slides") or []) if n in slide_kinds))
    for kind, want_type in (("narration", "scene"), ("discussion", "insight")):
        idxs = [i for i, k in enumerate(kinds) if k == kind]
        pool = [n for n in slide_nums if slide_kinds.get(n) == want_type]
        if not pool:
            pool = list(slide_nums)
        assign = distribute(len(idxs), pool)
        for local, pos in enumerate(idxs):
            if not norm.get(pos):
                norm[pos] = list(assign[local])
    used = {n for v in norm.values() for n in v}
    order = {n: p for p, n in enumerate(slide_nums)}
    for n in slide_nums:
        if n in used:
            continue
        want = ("narration" if slide_kinds.get(n) == "scene" else "discussion")
        cands = [i for i, k in enumerate(kinds) if k == want] or list(range(n_seg))
        if n_seg > 1 and len(slide_nums) > 1:
            proj = round(order[n] * (n_seg - 1) / (len(slide_nums) - 1))
        else:
            proj = 0
        best = min(cands, key=lambda i: (abs(i - proj), i))
        if n not in norm[best]:
            norm[best].append(n)
    return [{"chunk": 0, "kind": kinds[i], "script_index": i,
             "slides": norm.get(i, [])} for i in range(n_seg)]


def request_mapping(prompt_text: str, payload: dict,
                    n_seg: int, slide_nums: list[int]) -> list | None:
    """One judge call with retries. Returns a usable array or None."""
    body = (prompt_text + "\nSCRIPT SEGMENTS + SLIDES (JSON):\n"
            + json.dumps(payload, ensure_ascii=False))
    messages = [{"role": "user", "content": body}]
    for _ in range(MAP_ATTEMPTS):
        try:
            raw = call_muse(messages, thinking="high", max_tokens=MAP_TOKENS)
        except Exception:
            raw = None
        arr = extract_json_array(raw) if raw else None
        if mapping_usable(arr, n_seg, slide_nums):
            return arr
    return None


def semantic_map(script: list, board: list, narr_count: int | None,
                 prompts_dir: Path | None
                 ) -> tuple[list[dict] | None, str, str]:
    """LLM pairing with deterministic repair. Returns (chunks, strategy, err)."""
    narr_idx, disc_idx = split_script(script, narr_count)
    kinds = ["narration"] * len(script)
    for i in disc_idx:
        kinds[i] = "discussion"
    slide_nums = [s["slide"] for s in board]
    slide_kinds = {s["slide"]: ("insight" if s.get("type") == "insight" else "scene")
                   for s in board}
    try:
        prompt_text = load_judge_prompt(prompts_dir)
    except OSError as e:
        return None, "", f"judge prompt missing: {e}"
    payload = judge_payload(script, board, narr_idx, disc_idx)
    arr = request_mapping(prompt_text, payload, len(script), slide_nums)
    if arr is None:
        print(f"!! av-map: judge unusable after {MAP_ATTEMPTS} tries, "
              f"positional fallback", file=sys.stderr)
        chunks, err = build_mapping(script, board, narr_count)
        if chunks is None:
            return None, "", err
        return chunks, STRATEGY + "; llm judge failed, positional fallback", ""
    problems = validate_mapping(arr, len(script), slide_nums)
    chunks = repair_mapping(arr, kinds, slide_nums, slide_kinds)
    chunks.sort(key=lambda c: c["script_index"])
    for n, c in enumerate(chunks, 1):
        c["chunk"] = n
    note = "clean" if not problems else f"repaired {len(problems)}"
    return chunks, f"{STRATEGY_SEMANTIC} ({note})", ""


def av_map(myth_root: Path, chapter: str, semantic: bool = False,
           prompts_dir: Path | None = None, dry_run: bool = False,
           enrich_only: bool = False) -> int:
    chapter_dir = assert_inside(myth_root, Path("outputs") / chapter)
    if not chapter_dir.is_dir():
        print(f"! av-map: no chapter dir {chapter_dir}", file=sys.stderr)
        return 2
    if enrich_only:
        map_path = chapter_dir / f"av_mapping_{chapter}.json"
        if not map_path.is_file():
            print(f"! av-map: no existing mapping {map_path} "
                  f"(run av-map first, without --enrich-only)", file=sys.stderr)
            return 2
        try:
            body = json.loads(map_path.read_text(encoding="utf-8"))
            chunks = body.get("chunks")
        except (json.JSONDecodeError, OSError) as e:
            print(f"! av-map: existing mapping unreadable: {e}", file=sys.stderr)
            return 2
        if not chunks:
            print(f"! av-map: existing mapping has no chunks: {map_path}",
                  file=sys.stderr)
            return 2
        board: list = []
        try:
            board = json.loads(
                (chapter_dir / f"comic_storyboard_{chapter}.json")
                .read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            board = []
        script = [{"script_index": c.get("script_index", k)}
                  for k, c in enumerate(chunks)]
        strategy = ((body.get("strategy") or STRATEGY)
                    + "; enriched (slides kept)")
        print(f"-- av-map: enrich-only, keeping {len(chunks)} slide "
              f"assignments from {map_path.name}", file=sys.stderr)
        for c in chunks:
            found, missing = resolve_images(chapter_dir, c.get("slides") or [])
            c["images"] = found
            c["images_missing"] = missing
        prompts, prompt_source = load_slide_prompts(chapter_dir, chapter)
        if prompt_source is None:
            print(f"-- av-map: no comic_muse_prompts_{chapter}.json; "
                  f"panels carry muse_prompt null", file=sys.stderr)
        timing = enrich_chunks(chunks, board, prompts,
                               probe_audio_durations(chapter_dir, len(chunks)))
        out = {"chapter": chapter, "strategy": strategy,
               "script_segments": body.get("script_segments", len(chunks)),
               "slides": body.get("slides", len(board)),
               "prompts_source": prompt_source, **timing,
               "chunks": chunks}
        (chapter_dir / f"av_mapping_{chapter}.json").write_text(
            json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        n_missing = sum(len(c["images_missing"]) for c in chunks)
        print(f"av-map: {chapter}: {len(chunks)} chunks re-cued "
              f"({timing['timing']})"
              + (f" ({n_missing} images not yet rendered)" if n_missing else ""))
        return 0
    script, board, narr_count = load_inputs(chapter_dir, chapter)
    if not script:
        print(f"! av-map: no script_/narration_ JSON in {chapter_dir}",
              file=sys.stderr)
        return 2
    if not board:
        print(f"! av-map: no comic_storyboard_{chapter}.json in {chapter_dir} "
              f"(run the comic stage first)", file=sys.stderr)
        return 2
    if semantic and not dry_run:
        chunks, strategy, err = semantic_map(
            script, board, narr_count, prompts_dir)
    else:
        if semantic and dry_run:
            print("-- av-map: dry-run, positional rule "
                  "(semantic needs a key)", file=sys.stderr)
        chunks, err = build_mapping(script, board, narr_count)
        strategy = STRATEGY
    if chunks is None:
        print(f"! av-map: {err} for {chapter}", file=sys.stderr)
        return 2
    for c in chunks:
        found, missing = resolve_images(chapter_dir, c["slides"])
        c["images"] = found
        c["images_missing"] = missing
    prompts, prompt_source = load_slide_prompts(chapter_dir, chapter)
    if prompt_source is None:
        print(f"-- av-map: no comic_muse_prompts_{chapter}.json; "
              f"panels carry muse_prompt null", file=sys.stderr)
    timing = enrich_chunks(chunks, board or [], prompts,
                           probe_audio_durations(chapter_dir, len(chunks)))
    out = {"chapter": chapter, "strategy": strategy,
           "script_segments": len(script), "slides": len(board),
           "prompts_source": prompt_source, **timing,
           "chunks": chunks}
    (chapter_dir / f"av_mapping_{chapter}.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    n_missing = sum(len(c["images_missing"]) for c in chunks)
    print(f"av-map: {chapter}: {len(chunks)} chunks over {len(board)} slides"
          + (f" ({n_missing} images not yet rendered)" if n_missing else ""))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="MythologyMuse AV mapping stage")
    ap.add_argument("--mythology", default="mythologies/ramayana_dutt")
    ap.add_argument("--chapter", default="")
    ap.add_argument("--semantic", action="store_true",
                    help="Muse judge pairs by meaning (needs key); "
                         "default is the positional rule")
    ap.add_argument("--dry-run", action="store_true",
                    help="no network; forces the positional rule")
    ap.add_argument("--enrich-only", action="store_true",
                    help="keep the existing mapping's slide assignment; "
                         "refresh images, prompts, and timings only")
    args = ap.parse_args(argv)
    if not args.chapter:
        print("nothing to do: give --chapter", file=sys.stderr)
        return 2
    # NOTE: no parse_chapter_id gate — mapping only needs the chapter dir,
    # so Book_0_Introduction and other non-Chapter_M ids work too.
    try:
        myth_root = resolve_mythology_root(args.mythology)
    except SystemExit as e:
        print(e.code, file=sys.stderr)
        return 2
    return av_map(myth_root, args.chapter, semantic=args.semantic,
                    dry_run=args.dry_run, enrich_only=args.enrich_only)


if __name__ == "__main__":
    raise SystemExit(main())
