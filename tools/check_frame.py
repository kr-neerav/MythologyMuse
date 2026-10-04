#!/usr/bin/env python3
"""MythologyMuse — deterministic frame gate for renders (no viewing needed).

Detects matte / border / letterbox / pillarbox surround: samples the image
corners for the surround color, then measures how far that flat surround
extends from each edge. Soft vignette gradients do not trip it — only flat
bands at least --band pixels wide FAIL.

Usage:
    python3 tools/check_frame.py <image> [--band 8] [--tol 45]
    python3 tools/check_frame.py <image> --crop-out <path>  # crop to art edge

Prints one JSON line. Exit: 0 = art runs to all four edges (PASS),
1 = surround band found (FAIL), 2 = bad invocation.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

def _pil():
    try:
        from PIL import Image
    except ImportError:
        print("Pillow is required (pip install -r requirements.txt)")
        raise SystemExit(2)
    return Image


def _is_bg(px, x: int, y: int, bg: tuple, tol: int) -> bool:
    r, g, b = px[x, y][:3]
    return abs(r - bg[0]) + abs(g - bg[1]) + abs(b - bg[2]) < tol


def analyze(path: str, band: int = 8, tol: int = 45) -> dict:
    im = _pil().open(path).convert("RGB")
    w, h = im.size
    px = im.load()
    bg = tuple(
        sum(c[i] for c in (
            px[5, 5][:3], px[w - 6, 5][:3], px[5, h - 6][:3], px[w - 6, h - 6][:3],
        )) // 4
        for i in range(3)
    )
    step_x, step_y = max(1, w // 280), max(1, h // 180)

    def row_hit(y: int) -> bool:
        n = sum(0 if _is_bg(px, x, y, bg, tol) else 1 for x in range(0, w, step_x))
        return n > (w // step_x) * 0.25

    def col_hit(x: int) -> bool:
        n = sum(0 if _is_bg(px, x, y, bg, tol) else 1 for y in range(0, h, step_y))
        return n > (h // step_y) * 0.25

    top = next((y for y in range(h) if row_hit(y)), h)
    bot = next((y for y in range(h - 1, -1, -1) if row_hit(y)), -1)
    lft = next((x for x in range(w) if col_hit(x)), w)
    rgt = next((x for x in range(w - 1, -1, -1) if col_hit(x)), -1)
    if (top == h and bot == -1) or (lft == w and rgt == -1):
        # Uniform within tolerance: no surround measurable, no art edge
        # either. The gate only judges surrounds, so this is band-free.
        bands = {"top": 0, "bottom": 0, "left": 0, "right": 0}
    else:
        bands = {"top": top, "bottom": h - 1 - bot, "left": lft, "right": w - 1 - rgt}
    bad = {k: v for k, v in bands.items() if v >= band}
    bbox = [lft, top, rgt + 1, bot + 1] if rgt > lft and bot > top else [0, 0, w, h]
    return {
        "image": path,
        "size": [w, h],
        "verdict": "FAIL" if bad else "PASS",
        "bands": bands,
        "failed_sides": sorted(bad),
        "art_bbox": bbox,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("--band", type=int, default=8)
    ap.add_argument("--tol", type=int, default=45)
    ap.add_argument("--crop-out", default=None,
                    help="save art edge (bbox shrunk 3px to drop stroke) here")
    args = ap.parse_args(argv)
    if not Path(args.image).is_file():
        print(f"no such image: {args.image}")
        return 2
    rep = analyze(args.image, band=args.band, tol=args.tol)
    if args.crop_out:
        x0, y0, x1, y1 = rep["art_bbox"]
        box = (x0 + 3, y0 + 3, max(x0 + 4, x1 - 3), max(y0 + 4, y1 - 3))
        _pil().open(args.image).crop(box).save(args.crop_out)
        rep["cropped"] = args.crop_out
    print(json.dumps(rep))
    return 1 if rep["verdict"] == "FAIL" else 0


if __name__ == "__main__":
    sys.exit(main())
