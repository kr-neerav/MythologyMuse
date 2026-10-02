#!/usr/bin/env python3
"""MythologyMuse — bridge stage (Phase 3).

Deterministic, model-free port of `bilingual_bridge.py` (mythology-texts):
reads the podcast stage's combined `script_<chapter>.json` (every segment
with Hindi `text` + English `text_en`) and writes the flat narration files
the comic stage consumes. All paths stay inside the mythology folder.

Writes (under <mythology>/outputs/<chapter_id>/):
    english_narration_<chapter>.txt   text_en per segment, emotion tags stripped
    hindi_narration_<chapter>.txt     text per segment, emotion tags stripped

Exit codes (match the legacy bridge contract):
    0  success
    2  usage / no input JSON found
    3  broad bilingual parity gap (too many segments missing text_en)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from muse_client import assert_inside, resolve_mythology_root  # noqa: E402

# Identical semantics to the legacy bridge: strip <...> tags <=40 chars.
_EMOTION_TAG_RE = re.compile(r"<[^>\n]{1,40}>")


def strip_emotion_tags(text: str) -> str:
    return re.sub(r"\s+", " ", _EMOTION_TAG_RE.sub(" ", text)).strip()


def load_segments(chapter_dir: Path, chapter: str) -> list | None:
    script_path = chapter_dir / f"script_{chapter}.json"
    if script_path.exists():
        return json.loads(script_path.read_text(encoding="utf-8"))
    segs: list = []
    for prefix in ("narration", "discussion"):
        p = chapter_dir / f"{prefix}_{chapter}.json"
        if p.exists():
            segs.extend(json.loads(p.read_text(encoding="utf-8")))
    return segs or None


def bridge(myth_root: Path, chapter: str) -> int:
    chapter_dir = assert_inside(myth_root, Path("outputs") / chapter)
    segments = load_segments(chapter_dir, chapter)
    if not segments:
        print(f"! bridge: no script_/narration_ JSON in {chapter_dir} "
              f"(run the podcast stage first)", file=sys.stderr)
        return 2

    en_lines, hi_lines, missing = [], [], 0
    for seg in segments:
        text_en = (seg.get("text_en") or "").strip()
        text_hi = (seg.get("text") or "").strip()
        if not text_en:
            missing += 1
            continue
        en_lines.append(strip_emotion_tags(text_en))
        if text_hi:
            hi_lines.append(strip_emotion_tags(text_hi))

    total = len(segments)
    try:
        max_frac = float(os.environ.get("BRIDGE_MAX_MISSING_FRAC", "0.34"))
    except ValueError:
        max_frac = 0.34
    frac = (missing / total) if total else 1.0
    if not en_lines:
        print(f"! bridge: no English lines for {chapter} "
              f"({missing}/{total} missing text_en)", file=sys.stderr)
        return 3
    if frac > max_frac:
        print(f"! bridge: {missing}/{total} segments missing `text_en` in {chapter} "
              f"(> {max_frac:.0%} parity gap) -- re-run podcast", file=sys.stderr)
        return 3
    if missing:
        print(f"  bridge: tolerated parity gap {missing}/{total} in {chapter}; "
              f"proceeding with {len(en_lines)} lines", file=sys.stderr)

    (chapter_dir / f"english_narration_{chapter}.txt").write_text(
        "\n".join(en_lines) + "\n", encoding="utf-8")
    (chapter_dir / f"hindi_narration_{chapter}.txt").write_text(
        "\n".join(hi_lines) + "\n", encoding="utf-8")
    print(f"bridge: {len(en_lines)} EN / {len(hi_lines)} HI lines -> {chapter_dir}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="MythologyMuse bridge stage")
    ap.add_argument("--mythology", default="mythologies/ramayana_dutt")
    ap.add_argument("--chapter", default="")
    args = ap.parse_args(argv)
    if not args.chapter:
        print("nothing to do: give --chapter", file=sys.stderr)
        return 2
    from muse_client import parse_chapter_id as _pci
    try:
        myth_root = resolve_mythology_root(args.mythology)
        _pci(args.chapter)
    except SystemExit as e:
        print(e.code, file=sys.stderr)
        return 2
    return bridge(myth_root, args.chapter)


if __name__ == "__main__":
    raise SystemExit(main())
