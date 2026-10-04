#!/usr/bin/env python3
"""MythologyMuse — one studio generation round from the CLI (loop primitive).

Resolves ONE sheet or panel target exactly like the studio server, runs the
deterministic pre-scan on the prompt, and — only with --live — spends one
generation round (loop default: 1 candidate). Default is dry-run: resolve + pre-scan, $0.

The agent drives the closed loop under the comic-art-critique skill: invoke
once per round, at most 3 rounds per image. Every round after the first must
cite the changed source (round 2 may re-roll unchanged sources once, for
pure composition luck, and must say so).

Usage:
    python3 tools/studio_loop.py --chapter <id> --slide <N>          # dry run
    python3 tools/studio_loop.py --chapter <id> --slide <N> --live   # 1 round
    python3 tools/studio_loop.py --chapter <id> --sheet <ref> --live

Exit: 0 = round complete (or dry-run clean), 1 = pre-scan/generate failure,
      2 = bad invocation.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(TOOLS.parent / "studio"))

import server as server_mod  # noqa: E402
import image_gen as image_gen_mod  # noqa: E402
from server import resolve_mythology  # noqa: E402

GORE = re.compile(
    r"(?i)\bblood\w*|\bslay\w*|slaughter|massacre|\bgore\w*|corpse|"
    r"severed|dismember\w*|decapitat\w*|entrails|mutilat\w*")
FACELESS = re.compile(
    r"(?i)faceless|featureless|blank fac\w*|without fac\w*|\bno fac\w*|"
    r"no distinct faces|no readable facial|only \w[^.]* visible face")


def prescan_prompt(prompt: str, aspect: str) -> tuple[list, list]:
    """Deterministic gate before any paid call. Returns (fatal, warnings)."""
    fatal, warnings = [], []
    if not isinstance(prompt, str) or not prompt.strip():
        fatal.append("empty prompt")
        return fatal, warnings
    if image_gen_mod.SIZE_BY_ASPECT.get(aspect) is None:
        fatal.append(f"unknown aspect {aspect!r}")
    m = GORE.search(prompt)
    if m:
        fatal.append(f"policy-lexicon hit: {m.group()!r} — rewrite, then render")
    m = FACELESS.search(prompt)
    if m:
        fatal.append(f"face-negation hit: {m.group()!r} — rewrite with backs-to-viewer/blur/distant/crop wording (never 'faceless'), then render")
    if "photoreal" in prompt.lower():
        warnings.append("prompt mentions photorealism; style strips it")
    return fatal, warnings


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mythology", default="mythologies/ramayana_dutt")
    ap.add_argument("--chapter", required=True)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--slide", type=int, default=None)
    g.add_argument("--sheet", default=None)
    ap.add_argument("--live", action="store_true",
                    help="spend one generation round (default: dry-run)")
    ap.add_argument("--count", type=int, default=1,
                    help="candidates per round (loop default 1 to save spend)")
    ap.add_argument("--extra", default="")
    args = ap.parse_args(argv)

    try:
        _, outputs = resolve_mythology(args.mythology)
    except ValueError as e:
        print(f"bad mythology: {e}")
        return 2
    h = server_mod.Handler.__new__(server_mod.Handler)
    target = {"kind": "panel", "slide": args.slide} if args.slide else \
        {"kind": "sheet", "ref": args.sheet}
    try:
        resolved = h._resolve_target(outputs, args.chapter, target)
    except (ValueError, KeyError) as e:
        print(f"unresolvable target: {e}")
        return 2

    fatal, warnings = prescan_prompt(resolved.get("prompt", ""),
                                     resolved.get("aspect", ""))
    print(json.dumps({"target": target, "label": resolved.get("label"),
                      "aspect": resolved.get("aspect"),
                      "ref_names": resolved.get("ref_names",
                                                [resolved.get("sheet_ref")]),
                      "omitted": resolved.get("omitted", 0),
                      "fatal": fatal, "warnings": warnings,
                      "live": args.live}, indent=1))
    if fatal:
        return 1
    if not args.live:
        print("dry-run clean ($0 spent)")
        return 0
    try:
        out = image_gen_mod.generate_sync(
            prompt=resolved["prompt"], aspect=resolved["aspect"],
            file_prefix=resolved["prefix"],
            dest_dir=image_gen_mod.images_dir(outputs, args.chapter),
            extra=args.extra, kind=resolved.get("kind", "panel"),
            sheet_ref=resolved.get("sheet_ref"),
            style_which=resolved.get("style_which", "characters"),
            cast=resolved.get("cast", []),
            candidates=args.count,
            log={"slide": resolved.get("slide")}
            if resolved.get("slide") else None)
    except Exception as e:  # noqa: BLE001 — paid attempt failed loudly
        print(f"round failed: {e}")
        return 1
    lin = out["lineage"]
    print(json.dumps({"candidates": [c["image_path"] for c in out["candidates"]],
                      "refs": lin.get("refs"), "omitted_refs": lin.get("omitted_refs"),
                      "fallback": lin.get("fallback"),
                      "fallback_reason": lin.get("fallback_reason", "")}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
