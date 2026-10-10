#!/usr/bin/env python3
"""MythologyMuse — reorder existing comic boards story-first (one-shot migration).

Stable reorder per chapter: all `scene` slides first (relative order kept),
then all `insight` slides (relative order kept). Content moves to a new
slide number; every derived file follows the content:

  comic_storyboard_<ch>.json        renumber + relabel
  comic_storyboard_hindi_<ch>.json  same reorder (joined by old slide)
  comic_muse_prompts_<ch>.json      same reorder (joined by old slide)
  comic_render_plan_<ch>.json       slides renumbered (roster untouched)
  comic_eval_<ch>.json              storyboard_layer_a recomputed
  comic_progress_<ch>.json          layer_a recomputed
  av_mapping_<ch>.json              chunk slides/panels/images remapped
  video_manifest_<ch>.json          segment slide/image/title remapped
  studio_review_<ch>.json           slide keys remapped
  studio_images/panel_log.json      slide fields remapped
  studio_images/slide_NN_*          files renamed to the new number

No model calls, no pixels touched (renames only). Backs every rewritten
file up to <chapter>/_backup_reorder_<ts>/ plus a manifest with the
old->new map, so the move reverses exactly.

Usage:
    python3 tools/reorder_comic.py --chapter Book_1_Bala_Kanda_Chapter_1 --dry-run
    python3 tools/reorder_comic.py --all          # all chapters with boards
    python3 tools/reorder_comic.py --all --dry-run
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import time
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
from comic_stage import check_storyboard_layer_a  # noqa: E402
from muse_client import resolve_mythology_root  # noqa: E402


def is_grouped(board: list) -> bool:
    seen_insight = False
    for s in board:
        if not isinstance(s, dict):
            continue
        if s.get("type") == "insight":
            seen_insight = True
        elif s.get("type") == "scene" and seen_insight:
            return False
    return True


def plan_order(board: list) -> tuple[list[dict], dict[int, int]]:
    scenes = [s for s in board if isinstance(s, dict)
              and s.get("type") != "insight"]
    insights = [s for s in board if isinstance(s, dict)
                and s.get("type") == "insight"]
    others = [s for s in board if not isinstance(s, dict)]
    new_board = scenes + insights + others
    mapping: dict[int, int] = {}
    for new_n, s in enumerate(new_board, 1):
        old = s.get("slide")
        if isinstance(old, int) and old not in mapping:
            mapping[old] = new_n
    return new_board, mapping


def relabel(n: int, title: str) -> str:
    return f"Slide{n:02d} - {title}"


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


def backup_file(path: Path, backup_dir: Path) -> None:
    backup_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, backup_dir / path.name)


def reorder_chapter(myth_root: Path, chapter: str,
                    dry_run: bool) -> tuple[str, str]:
    """Returns (status, detail). status: SKIP|OK|FAIL."""
    chapter_dir = myth_root / "outputs" / chapter
    board_path = chapter_dir / f"comic_storyboard_{chapter}.json"
    if not board_path.is_file():
        return "SKIP", "no storyboard"
    try:
        board = load_json(board_path)
    except (json.JSONDecodeError, OSError) as e:
        return "FAIL", f"storyboard unreadable: {e}"
    if not isinstance(board, list) or not board:
        return "FAIL", "storyboard empty/not a list"
    if is_grouped(board):
        verdict = check_storyboard_layer_a(board)["verdict"]
        return "SKIP", f"already grouped (Layer A {verdict})"

    new_board, mapping = plan_order(board)
    for s in new_board:
        n = mapping[s["slide"]]
        s["slide"] = n
        if isinstance(s.get("title"), str) and s["title"].strip():
            s["slide_label"] = relabel(n, s["title"].strip())
    verdict = check_storyboard_layer_a(new_board)
    if verdict["verdict"] != "PASS":
        return "FAIL", f"reordered board fails Layer A: {verdict['issues'][:2]}"
    by_title = {s["title"]: s for s in new_board if isinstance(s, dict)}

    lines = [f"{len(board)} slides: "
             + ", ".join(f"{o}->{n}" for o, n in sorted(mapping.items()))]
    if dry_run:
        for s in new_board:
            lines.append(f"  new {s['slide']:2d} {s['type']:7s} {s['title']!r}")
        return "OK", "\n".join(lines)

    ts = time.strftime("%Y%m%d_%H%M%S", time.gmtime())
    backup_dir = chapter_dir / f"_backup_reorder_{ts}"
    write_json(backup_dir / "reorder_manifest.json",
               {"chapter": chapter, "at": ts,
                "old_to_new": {str(o): n
                               for o, n in sorted(mapping.items())}})

    def _rewrite(path: Path, obj) -> None:
        if path.is_file():
            backup_file(path, backup_dir)
        write_json(path, obj)

    _rewrite(board_path, new_board)

    # Hindi board: same reorder, joined by old slide number.
    hindi_path = chapter_dir / f"comic_storyboard_hindi_{chapter}.json"
    if hindi_path.is_file():
        hindi = load_json(hindi_path)
        by_old = {s["slide"]: s for s in hindi if isinstance(s, dict)}
        new_hindi = []
        for old in sorted(mapping, key=lambda o: mapping[o]):
            if old in by_old:
                c = by_old[old]
                c["slide"] = mapping[old]
                if c.get("title") in by_title:
                    c["slide_label"] = by_title[c["title"]]["slide_label"]
                new_hindi.append(c)
        new_hindi += [s for s in hindi
                      if isinstance(s, dict) and s["slide"] not in mapping]
        if len(new_hindi) != len(hindi):
            return "FAIL", "hindi board lost slides"
        _rewrite(hindi_path, new_hindi)
        lines.append(f"hindi: {len(new_hindi)} slides reordered")

    # Muse prompts pack: same reorder, joined by old slide number.
    prompts_path = chapter_dir / f"comic_muse_prompts_{chapter}.json"
    prom_by_new: dict[int, str] = {}
    if prompts_path.is_file():
        prompts = load_json(prompts_path)
        by_old = {p["slide"]: p for p in prompts if isinstance(p, dict)}
        new_prompts = []
        for old in sorted(mapping, key=lambda o: mapping[o]):
            if old in by_old:
                p = dict(by_old[old])
                p["slide"] = mapping[old]
                if p.get("slide_label") and by_old[old].get("slide_label"):
                    for s in new_board:
                        if s["slide"] == mapping[old]:
                            p["slide_label"] = s["slide_label"]
                new_prompts.append(p)
                prom_by_new[mapping[old]] = p.get("muse_prompt", "")
        if len(new_prompts) != len(prompts):
            return "FAIL", "prompts pack lost slides"
        _rewrite(prompts_path, new_prompts)
        lines.append(f"prompts: {len(new_prompts)} packs reordered")

    # Render plan: slides renumbered, roster untouched.
    plan_path = chapter_dir / f"comic_render_plan_{chapter}.json"
    if plan_path.is_file():
        plan = load_json(plan_path)
        for s in plan.get("slides", []):
            if isinstance(s, dict) and s.get("slide") in mapping:
                for b in new_board:
                    if mapping.get(s["slide"]) == b["slide"]:
                        s["slide"] = b["slide"]
                        s["slide_label"] = b["slide_label"]
                        break
        plan["slides"] = sorted(plan.get("slides", []),
                                key=lambda s: s.get("slide", 0)
                                if isinstance(s, dict) else 0)
        _rewrite(plan_path, plan)
        lines.append(f"render_plan: {len(plan.get('slides', []))} turns reordered")

    # Eval + progress: refresh the stored Layer A verdict.
    eval_path = chapter_dir / f"comic_eval_{chapter}.json"
    if eval_path.is_file():
        eval_rec = load_json(eval_path)
        if isinstance(eval_rec, dict):
            eval_rec["storyboard_layer_a"] = verdict
            _rewrite(eval_path, eval_rec)
            lines.append("eval: layer_a refreshed")
    prog_path = chapter_dir / f"comic_progress_{chapter}.json"
    if prog_path.is_file():
        prog = load_json(prog_path)
        if isinstance(prog, dict):
            prog["layer_a"] = verdict
            _rewrite(prog_path, prog)
            lines.append("progress: layer_a refreshed")

    # Studio review: slide keys follow the content.
    review_path = chapter_dir / f"studio_review_{chapter}.json"
    if review_path.is_file():
        review = load_json(review_path)
        slides = review.get("slides")
        if isinstance(slides, dict):
            fixed = {}
            for k, v in slides.items():
                try:
                    fixed[str(mapping[int(k)])] = v
                except (ValueError, KeyError):
                    fixed[k] = v
            review["slides"] = fixed
            _rewrite(review_path, review)
            lines.append(f"review: {len(fixed)} slide keys remapped")

    # Panel log: slide fields follow the content (chronological order kept).
    panel_log = chapter_dir / "studio_images" / "panel_log.json"
    if panel_log.is_file():
        log = load_json(panel_log)
        if isinstance(log, list):
            for e in log:
                if isinstance(e, dict) and e.get("slide") in mapping:
                    e["slide"] = mapping[e["slide"]]
            _rewrite(panel_log, log)
            lines.append(f"panel_log: {len(log)} entries remapped")

    # Panel image files: rename to the new number (two-phase, no clobber).
    imgdir = chapter_dir / "studio_images"
    if imgdir.is_dir():
        moves = []
        for p in imgdir.iterdir():
            name = p.name
            if not name.startswith("slide_") or not p.is_file():
                continue
            try:
                old = int(name.split("_")[1])
            except (IndexError, ValueError):
                continue
            if old in mapping and mapping[old] != old:
                rest = name.split("_", 2)[2]
                moves.append((p, f"slide_{mapping[old]:02d}_{rest}"))
        tmp_moves = []
        for src, dst_name in moves:
            tmp = src.with_name(src.name + ".reorder_tmp")
            backup_file(src, backup_dir / "studio_images")
            src.rename(tmp)
            tmp_moves.append((tmp, imgdir / dst_name))
        for tmp, dst in tmp_moves:
            if dst.exists():
                backup_file(dst, backup_dir / "studio_images")
                dst.unlink()
            tmp.rename(dst)
        lines.append(f"images: {len(moves)} files renamed")

    # AV mapping: chunk slides/panels/images follow the content.
    av_path = chapter_dir / f"av_mapping_{chapter}.json"
    if av_path.is_file():
        av = load_json(av_path)
        board_by_new = {s["slide"]: s for s in new_board
                        if isinstance(s, dict)}
        for c in av.get("chunks", []):
            if not isinstance(c, dict):
                continue
            new_slides = sorted({mapping[s] for s in (c.get("slides") or [])
                                 if s in mapping})
            c["slides"] = new_slides
            panels = []
            for n in new_slides:
                meta = board_by_new.get(n, {})
                panels.append({
                    "slide": n,
                    "image": f"studio_images/slide_{n:02d}_final.jpg",
                    "image_missing": not (
                        chapter_dir / "studio_images" /
                        f"slide_{n:02d}_final.jpg").is_file(),
                    "muse_prompt": prom_by_new.get(n),
                    "slide_label": meta.get("slide_label"),
                    "title": meta.get("title"),
                    "type": meta.get("type"),
                    "share": 1.0 / len(new_slides) if new_slides else 0.0,
                    "en": None, "hi": None,
                })
            # Keep probed cue timings when the panel count is unchanged.
            old_panels = [p for p in (c.get("panels") or [])
                          if isinstance(p, dict)]
            if len(old_panels) == len(panels):
                by_old_slide = {p.get("slide"): p for p in old_panels}
                inv = {n: o for o, n in mapping.items()}
                for p in panels:
                    src = by_old_slide.get(inv.get(p["slide"]))
                    if src is not None:
                        for k in ("share", "en", "hi"):
                            p[k] = src.get(k)
            c["panels"] = panels
            found = [s for s in
                     (f"studio_images/slide_{n:02d}_final.jpg"
                      for n in new_slides)
                     if (chapter_dir / s).is_file()]
            missing = [s for s in
                       (f"studio_images/slide_{n:02d}_final.jpg"
                        for n in new_slides)
                       if not (chapter_dir / s).is_file()]
            c["images"] = found
            c["images_missing"] = missing
        _rewrite(av_path, av)
        lines.append(f"av_mapping: {len(av.get('chunks', []))} chunks remapped")

    # Video manifest: segment identity follows the content (timings kept).
    man_path = chapter_dir / f"video_manifest_{chapter}.json"
    if man_path.is_file():
        man = load_json(man_path)
        board_by_new = {s["slide"]: s for s in new_board
                        if isinstance(s, dict)}
        n_seg = 0
        for v in (man.get("videos") or {}).values():
            if not isinstance(v, dict):
                continue
            for s in v.get("segments", []):
                if not isinstance(s, dict):
                    continue
                old = s.get("slide")
                if old not in mapping:
                    # Older manifests carry only the image name.
                    m = re.match(r"studio_images/slide_(\d+)_final\.jpg$",
                                 s.get("image") or "")
                    old = int(m.group(1)) if m else None
                    if old not in mapping:
                        continue
                n = mapping[old]
                meta = board_by_new.get(n, {})
                s["slide"] = n
                s["image"] = f"studio_images/slide_{n:02d}_final.jpg"
                if meta.get("title"):
                    s["title"] = meta["title"]
                if n in prom_by_new:
                    s["muse_prompt"] = prom_by_new[n]
                n_seg += 1
        _rewrite(man_path, man)
        lines.append(f"video_manifest: {n_seg} segments remapped")

    return "OK", "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Reorder comic boards story-first")
    ap.add_argument("--mythology", default="mythologies/ramayana_dutt")
    ap.add_argument("--chapter", default="")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    myth_root = resolve_mythology_root(args.mythology)
    outputs = myth_root / "outputs"
    if args.all:
        chapters = sorted(p.name for p in outputs.iterdir() if p.is_dir()
                          and (p / f"comic_storyboard_{p.name}.json").is_file())
    elif args.chapter:
        chapters = [args.chapter]
    else:
        print("nothing to do: give --chapter or --all", file=sys.stderr)
        return 2

    rc = 0
    for ch in chapters:
        status, detail = reorder_chapter(myth_root, ch, args.dry_run)
        print(f"[{status}] {ch}\n{detail}")
        if status == "FAIL":
            rc = 1
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
