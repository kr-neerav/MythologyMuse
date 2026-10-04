#!/usr/bin/env python3
"""MythologyMuse — build a self-contained critique packet for a worker.

A worker (subagent) needs everything to judge one image without holding the
whole chapter in context: the candidate, a cheap thumbnail for staging/frame
checks, the slide spec, both prompt copies, the staged roster rows, and
ledger standing. This script assembles that packet (read-only, except for
thumbnails it writes).

Usage:
    python3 tools/critique_packet.py --chapter <id> --slide <N> --candidate <path>
    python3 tools/critique_packet.py --chapter <id> --sheet <ref> --candidate <path>

Options: --thumb-dir DIR (default /tmp/<chapter>_thumbs, 768px max side),
--out PATH (default /tmp/critique_<chapter>_<target>.json).

Prints the packet path. Exit: 0 ok, 2 bad invocation / missing input.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(TOOLS.parent / "studio"))

from server import resolve_mythology  # noqa: E402

THUMB_MAX = 768


def load_json(path: Path, default):
    return json.loads(path.read_text()) if path.is_file() else default


def make_thumb(candidate: Path, thumb_dir: Path) -> str | None:
    try:
        from PIL import Image
    except ImportError:
        return None
    thumb_dir.mkdir(parents=True, exist_ok=True)
    out = thumb_dir / (candidate.stem + "_thumb.jpg")
    im = Image.open(candidate).convert("RGB")
    im.thumbnail((THUMB_MAX, THUMB_MAX))
    im.save(out)
    return str(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mythology", default="mythologies/ramayana_dutt")
    ap.add_argument("--chapter", required=True)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--slide", type=int, default=None)
    g.add_argument("--sheet", default=None)
    ap.add_argument("--candidate", required=True)
    ap.add_argument("--thumb-dir", default=None)
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)

    cand = Path(args.candidate)
    if not cand.is_file():
        print(f"missing candidate: {cand}")
        return 2
    try:
        _, outputs = resolve_mythology(args.mythology)
    except ValueError as e:
        print(f"bad mythology: {e}")
        return 2
    chdir = Path(outputs) / args.chapter
    thumb_dir = Path(args.thumb_dir) if args.thumb_dir \
        else Path(f"/tmp/{args.chapter}_thumbs")

    led = load_json(Path(outputs) / "sheet_verdicts.json", {"entities": {}})
    standing = {k: v.get("verdict") for k, v in led.get("entities", {}).items()}

    if args.slide is not None:
        tag = f"slide_{args.slide}"
        sb = load_json(chdir / f"comic_storyboard_{args.chapter}.json", [])
        hi = load_json(chdir / f"comic_storyboard_hindi_{args.chapter}.json", [])
        rp = load_json(chdir / f"comic_render_plan_{args.chapter}.json", {"roster": [], "slides": []})
        mp = load_json(chdir / f"comic_muse_prompts_{args.chapter}.json", [])
        spec = next((s for s in sb if str(s.get("slide")) == str(args.slide)), None)
        hindi = next((s for s in hi if str(s.get("slide")) == str(args.slide)), None)
        plan = next((s for s in rp.get("slides", []) if str(s.get("slide")) == str(args.slide)), None)
        muse = next((s for s in mp if str(s.get("slide")) == str(args.slide)), None)
        if spec is None or plan is None:
            print(f"no spec for slide {args.slide}")
            return 2
        staged = (spec.get("characters") or []) + ([spec.get("location")] if spec.get("location") else [])
        roster = [r for r in rp.get("roster", [])
                  if r.get("flow_ref") in staged or r.get("name") in staged]
        body = {"spec": spec, "hindi": hindi,
                "prompt_render_plan": (plan or {}).get("muse_prompt"),
                "prompt_muse_copy": (muse or {}).get("muse_prompt"),
                "subjects": (plan or {}).get("subjects"),
                "staged_roster": roster}
    else:
        tag = f"sheet_{args.sheet}"
        rp = load_json(chdir / f"comic_render_plan_{args.chapter}.json", {"roster": []})
        rows = [r for r in rp.get("roster", []) if r.get("flow_ref") == args.sheet]
        if not rows:
            print(f"no roster entry for sheet: {args.sheet}")
            return 2
        body = {"roster": rows[0]}

    packet = {"chapter": args.chapter, "target": tag,
              "candidate": str(cand),
              "thumbnail": make_thumb(cand, thumb_dir),
              "ledger_standing": standing,
              **body}
    out = Path(args.out) if args.out \
        else Path(f"/tmp/critique_{args.chapter}_{tag}.json")
    out.write_text(json.dumps(packet, ensure_ascii=False, indent=1))
    print(str(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
