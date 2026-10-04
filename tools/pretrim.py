#!/usr/bin/env python3
"""MythologyMuse — pre-trim gate for the art loop (cost item 3).

Panels staging more than 5 named faces fail the comic-art-critique face cap
on R1 every time, burning a paid round plus a view cycle. This tool flags
those slides ($0 gate) and trims them to the apex beat BEFORE the first
render: storyboard characters + rationale, Hindi mirror, render-plan
subjects, and the panel prompt in BOTH copies (a trim without the prompt
rewrite would re-render the dropped cast).

Guards: slide counts must be unchanged after any write (a shrink is always
a bug); the 4 spec files are backed up to /tmp first; on-slide text
(English + Hindi) is immutable — there is no flag that touches it.

Usage (gate):
    python3 tools/pretrim.py --chapter <id>
      # exit 1 + JSON list when slides stage >5 faces, 0 when clean
Usage (trim one slide):
    python3 tools/pretrim.py --chapter <id> --slide <N> \\
        --keep Rama,Lakshmana,Jatayu [--location "Dandaka Forest"] \\
        --rationale "..." --apex-prompt "..."
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(TOOLS.parent / "studio"))

from server import resolve_mythology  # noqa: E402

FACE_CAP = 5
SPEC_FILES = ("comic_storyboard_{c}.json", "comic_storyboard_hindi_{c}.json",
              "comic_render_plan_{c}.json", "comic_muse_prompts_{c}.json")


def spec_paths(chdir: Path, chapter: str) -> dict:
    return {t: chdir / t.format(c=chapter) for t in SPEC_FILES}


def load_specs(chdir: Path, chapter: str) -> dict:
    paths = spec_paths(chdir, chapter)
    return {k: json.loads(p.read_text()) for k, p in paths.items()}


def overcast_slides(board: list) -> list:
    """Slides whose staged cast exceeds the face cap (entry count proxy)."""
    out = []
    for s in board:
        cast = s.get("characters") or []
        if len(cast) > FACE_CAP:
            out.append({"slide": s.get("slide"), "faces": len(cast),
                        "characters": cast})
    return out


def backup_specs(chdir: Path, chapter: str) -> str:
    dest = Path(f"/tmp/{chapter}_pretrim_{int(time.time())}")
    dest.mkdir(parents=True, exist_ok=True)
    for p in spec_paths(chdir, chapter).values():
        shutil.copy(p, dest / p.name)
    return str(dest)


def trim_slide(chdir: Path, chapter: str, slide: int, keep: list,
               location: str | None, rationale: str,
               apex_prompt: str) -> dict:
    """Trim one slide to the apex cast. Returns a report of what changed."""
    if len(keep) > FACE_CAP or not keep:
        raise ValueError(f"keep must name 1-{FACE_CAP} faces, got {keep}")
    specs = load_specs(chdir, chapter)
    before = {k: (len(v["slides"]) if isinstance(v, dict) else len(v))
              for k, v in specs.items()}
    sb, hi, rp, mp = (specs["comic_storyboard_{c}.json"],
                      specs["comic_storyboard_hindi_{c}.json"],
                      specs["comic_render_plan_{c}.json"],
                      specs["comic_muse_prompts_{c}.json"])
    rows = [s for s in sb if str(s.get("slide")) == str(slide)]
    if not rows:
        raise ValueError(f"no storyboard row for slide {slide}")
    kinds = {}
    for name in keep:
        hit = next((r for r in rp["roster"]
                    if r.get("flow_ref") == name or r.get("name") == name), None)
        if hit is None:
            raise ValueError(f"kept name not in roster: {name}")
        kinds[name] = hit.get("kind", "character")
    loc = location if location is not None else rows[0].get("location")
    if loc:
        kinds.setdefault(loc, "scene")
    subjects = str([{"name": n, "kind": kinds[n]} for n in keep]
                   + ([{"name": loc, "kind": "scene"}] if loc else []))

    backup = backup_specs(chdir, chapter)
    for s in sb:
        if str(s.get("slide")) == str(slide):
            s["characters"] = keep
            if loc:
                s["location"] = loc
            s["rationale"] = rationale
    for s in hi:
        if str(s.get("slide")) == str(slide):
            s["characters"] = keep
            if loc:
                s["location"] = loc
    for s in rp["slides"]:
        if str(s.get("slide")) == str(slide):
            s["muse_prompt"] = apex_prompt
            s["subjects"] = subjects
    for s in mp:
        if str(s.get("slide")) == str(slide):
            s["muse_prompt"] = apex_prompt
    paths = spec_paths(chdir, chapter)
    blobs = {"comic_storyboard_{c}.json": sb, "comic_storyboard_hindi_{c}.json": hi,
             "comic_render_plan_{c}.json": rp, "comic_muse_prompts_{c}.json": mp}
    for k, blob in blobs.items():
        paths[k].write_text(json.dumps(blob, ensure_ascii=False, indent=1))
    def _count(path: Path) -> int:
        blob = json.loads(path.read_text())
        return len(blob["slides"]) if isinstance(blob, dict) else len(blob)

    after = {k: _count(p) for k, p in paths.items()}
    if after != before:
        raise RuntimeError(f"slide count changed: {before} -> {after}")
    return {"slide": slide, "kept": keep, "location": loc,
            "backup": backup, "counts": after}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mythology", default="mythologies/ramayana_dutt")
    ap.add_argument("--chapter", required=True)
    ap.add_argument("--slide", type=int, default=None)
    ap.add_argument("--keep", default=None, help="comma-separated apex cast")
    ap.add_argument("--location", default=None)
    ap.add_argument("--rationale", default="")
    ap.add_argument("--apex-prompt", default=None)
    args = ap.parse_args(argv)
    try:
        _, outputs = resolve_mythology(args.mythology)
    except ValueError as e:
        print(f"bad mythology: {e}")
        return 2
    chdir = Path(outputs) / args.chapter
    if args.slide is None:
        board = json.loads((chdir / f"comic_storyboard_{args.chapter}.json").read_text())
        flagged = overcast_slides(board)
        print(json.dumps({"chapter": args.chapter, "face_cap": FACE_CAP,
                          "overcast": flagged}))
        return 1 if flagged else 0
    if not args.keep or not args.apex_prompt:
        print("trim needs --keep and --apex-prompt")
        return 2
    try:
        rep = trim_slide(chdir, args.chapter, args.slide,
                         [k.strip() for k in args.keep.split(",") if k.strip()],
                         args.location, args.rationale, args.apex_prompt)
    except (ValueError, RuntimeError) as e:
        print(f"trim refused: {e}")
        return 2
    print(json.dumps(rep, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
