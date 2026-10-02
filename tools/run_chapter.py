#!/usr/bin/env python3
"""MythologyMuse — single-chapter driver (Phase 5).

Runs ONE chapter end to end, text only: PODCAST -> BRIDGE -> COMIC,
finishing the chapter completely. Resumable: stages whose outputs already
exist are skipped unless the corresponding --redo flag is given.

Per chapter:
  1. PODCAST -> podcast_stage.py --chapter <id>
       produces script_/narration_/discussion_<ch>.json
       SKIPPED if script_<ch>.json exists (unless --redo-podcast)
  2. BRIDGE  -> bridge_stage.py --chapter <id>
       produces english_narration_<ch>.txt + hindi_narration_<ch>.txt
       (deterministic; always re-run, it is free)
  3. COMIC   -> comic_stage.py --chapter <id>
       produces comic_storyboard[_hindi]/comic_muse_prompts/comic_eval
       (Flow/ingredient output removed; muse_prompt texts are the render inputs)
       SKIPPED if comic_eval_<ch>.json verdict == PASS (unless --redo-comic)

This driver deliberately handles ONE chapter per invocation. There is no
corpus-wide batch mode in v1 — the full 652-chapter corpus is never touched
by accident. Run chapters one at a time (or from your own loop).

Usage:
    python3 tools/run_chapter.py --chapter Book_1_Bala_Kanda_Chapter_1 --dry-run
    python3 tools/run_chapter.py --chapter Book_1_Bala_Kanda_Chapter_1   # live (needs .env key)

Exit: 0 = chapter complete (all stages PASS), 1 = a stage failed,
      2 = bad invocation.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from muse_client import (  # noqa: E402
    assert_inside,
    parse_chapter_id,
    resolve_mythology_root,
)

import podcast_stage as podcast  # noqa: E402
import bridge_stage as bridge  # noqa: E402
import comic_stage as comic  # noqa: E402


def podcast_done(myth_root: Path, chapter: str) -> bool:
    return (myth_root / "outputs" / chapter / f"script_{chapter}.json").exists()


def comic_done(myth_root: Path, chapter: str) -> bool:
    p = myth_root / "outputs" / chapter / f"comic_eval_{chapter}.json"
    if not p.exists():
        return False
    try:
        return comic.is_live_pass(json.loads(p.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, OSError):
        return False


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="MythologyMuse single-chapter driver")
    ap.add_argument("--mythology", default="mythologies/ramayana_dutt")
    ap.add_argument("--chapter", default="")
    ap.add_argument("--prompts-dir", default="")
    ap.add_argument("--max-qa-loops", type=int, default=2)
    ap.add_argument("--max-storyboard-retries", type=int, default=1)
    ap.add_argument("--max-loops", type=int, default=2)
    ap.add_argument("--max-calls", type=int, default=None)
    ap.add_argument("--redo-podcast", action="store_true")
    ap.add_argument("--redo-comic", action="store_true")
    ap.add_argument("--prev-recap", default="")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    if not args.chapter:
        print("nothing to do: give --chapter", file=sys.stderr)
        return 2
    try:
        myth_root = resolve_mythology_root(args.mythology)
        parse_chapter_id(args.chapter)
    except SystemExit as e:
        print(e.code, file=sys.stderr)
        return 2
    default_prompts = Path(__file__).resolve().parent.parent / "prompts"
    prompts_dir = Path(args.prompts_dir) if args.prompts_dir else default_prompts
    if not prompts_dir.is_dir():
        print(f"prompts dir not found: {prompts_dir}", file=sys.stderr)
        return 2
    chapter = args.chapter
    tag = "dry-run" if args.dry_run else "LIVE"
    print(f"=== CHAPTER {chapter} [{tag}] ===")

    # 1. PODCAST
    if podcast_done(myth_root, chapter) and not args.redo_podcast and not args.dry_run:
        print("-- podcast: script exists, skipping (use --redo-podcast)")
    else:
        try:
            rc = podcast.run_chapter(
                myth_root, prompts_dir, chapter,
                max_qa_loops=args.max_qa_loops, dry_run=args.dry_run,
                prev_recap=args.prev_recap)
        except (RuntimeError, OSError) as e:
            print(f"!! podcast stage hard error: {e}", file=sys.stderr)
            return 1
        if rc != 0:
            print(f"!! podcast stage failed rc={rc}", file=sys.stderr)
            return 1

    # 2. BRIDGE (deterministic; always re-run)
    rc = bridge.bridge(myth_root, chapter)
    if rc != 0:
        print(f"!! bridge stage failed rc={rc}", file=sys.stderr)
        return 1

    # 3. COMIC
    if comic_done(myth_root, chapter) and not args.redo_comic and not args.dry_run:
        print("-- comic: eval PASS exists, skipping (use --redo-comic)")
    else:
        try:
            rc = comic.run_chapter(
                myth_root, prompts_dir, chapter,
                max_storyboard_retries=args.max_storyboard_retries,
                max_loops=args.max_loops,
                dry_run=args.dry_run, redo_comic=args.redo_comic,
                max_calls=args.max_calls)
        except (RuntimeError, OSError) as e:
            print(f"!! comic stage hard error: {e}", file=sys.stderr)
            return 1
        if rc != 0:
            print(f"!! comic stage failed rc={rc}", file=sys.stderr)
            return 1

    chapter_dir = assert_inside(myth_root, Path("outputs") / chapter)
    produced = sorted(p.name for p in chapter_dir.iterdir() if p.is_file())
    print(f"=== CHAPTER COMPLETE: {chapter} ({len(produced)} files) ===")
    for name in produced:
        print(f"  {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
