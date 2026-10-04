#!/usr/bin/env python3
"""MythologyMuse — batch wrapper over studio_loop.py (loop primitive).

Runs one dry-run or live round per target, sequentially, printing one compact
JSON line per target. Same exit contract per target (0 ok, 1 pre-scan/generate
failure, 2 bad invocation); the batch exit is the worst seen.

Usage:
    python3 tools/loop_batch.py --chapter <id> --slides 1,2,3 [--live]
    python3 tools/loop_batch.py --chapter <id> --sheets Rama,Ayodhya [--live]
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import re
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))

import studio_loop as loop  # noqa: E402

CAND_RE = re.compile(r"(?:slide_\d+|sheet_.+?)_candidate_\d+\.jpg")


def parse_targets(slides: str | None, sheets: str | None) -> list:
    if bool(slides) == bool(sheets):
        raise ValueError("pass exactly one of --slides / --sheets")
    if slides:
        return [{"kind": "panel", "slide": int(x)} for x in slides.split(",") if x.strip()]
    return [{"kind": "sheet", "ref": x} for x in sheets.split(",") if x.strip()]


def run_one(chapter: str, mythology: str, target: dict, live: bool) -> dict:
    argv = ["--mythology", mythology, "--chapter", chapter]
    argv += ["--slide", str(target["slide"])] if "slide" in target \
        else ["--sheet", target["ref"]]
    if live:
        argv.append("--live")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        try:
            rc = loop.main(argv)
        except SystemExit as e:
            rc = e.code if isinstance(e.code, int) else 2
    out = buf.getvalue()
    cands = sorted(set(CAND_RE.findall(out)))
    return {"target": target, "rc": rc, "candidates": cands, "live": live}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mythology", default="mythologies/ramayana_dutt")
    ap.add_argument("--chapter", required=True)
    ap.add_argument("--slides", default=None)
    ap.add_argument("--sheets", default=None)
    ap.add_argument("--live", action="store_true")
    args = ap.parse_args(argv)
    try:
        targets = parse_targets(args.slides, args.sheets)
    except ValueError as e:
        print(f"bad invocation: {e}")
        return 2
    if not targets:
        print("bad invocation: empty target list")
        return 2
    worst = 0
    for t in targets:
        rep = run_one(args.chapter, args.mythology, t, args.live)
        worst = max(worst, rep["rc"])
        print(json.dumps(rep))
    return worst


if __name__ == "__main__":
    sys.exit(main())
