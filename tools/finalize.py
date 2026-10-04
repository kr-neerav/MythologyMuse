#!/usr/bin/env python3
"""MythologyMuse — finalize a passing candidate (free and reversible).

Copies <candidate> to the <final> slot. For sheets it also writes/refreshes
the book-wide ledger entry in sheet_verdicts.json (flow_ref + roster-prompt
sha256 + final-file sha256). For panels it only copies (no ledger).

Usage:
    python3 tools/finalize.py --chapter <id> --slide <N> [--candidate 1]
    python3 tools/finalize.py --chapter <id> --sheet <ref> [--candidate 1] [--note "..."]

Prints one JSON line. Exit: 0 finalized, 2 bad invocation / missing file.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import time
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(TOOLS.parent / "studio"))

from server import resolve_mythology  # noqa: E402


def candidate_name(kind: str, ref: str, n: int) -> str:
    if kind == "panel":
        return f"slide_{int(ref):02d}_candidate_{n}.jpg"
    return f"sheet_{ref}_candidate_{n}.jpg"


def final_name(kind: str, ref: str) -> str:
    if kind == "panel":
        return f"slide_{int(ref):02d}_final.jpg"
    return f"sheet_{ref}_final.jpg"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_sheet_entry(name: str, flow_ref: str, kind: str, prompt: str,
                      final_rel: str, final_sha: str, passed_on: str,
                      note: str = "") -> dict:
    return {
        "name": name,
        "flow_ref": flow_ref,
        "kind": kind,
        "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "prompt_source": "comic_render_plan roster",
        "final": final_rel,
        "final_sha256": final_sha,
        "verdict": "PASS",
        "decided_at": int(time.time()),
        "passed_on": passed_on,
        "note": note,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mythology", default="mythologies/ramayana_dutt")
    ap.add_argument("--chapter", required=True)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--slide", type=int, default=None)
    g.add_argument("--sheet", default=None)
    ap.add_argument("--candidate", type=int, default=1)
    ap.add_argument("--note", default="")
    args = ap.parse_args(argv)

    try:
        _, outputs = resolve_mythology(args.mythology)
    except ValueError as e:
        print(f"bad mythology: {e}")
        return 2
    imgdir = Path(outputs) / args.chapter / "studio_images"
    kind = "panel" if args.slide is not None else "sheet"
    ref = str(args.slide) if args.slide is not None else args.sheet
    src = imgdir / candidate_name(kind, ref, args.candidate)
    dst = imgdir / final_name(kind, ref)
    if not src.is_file():
        print(f"missing candidate: {src}")
        return 2
    shutil.copy(src, dst)
    rep = {"target": {kind: ref}, "final": str(dst), "ledger": None}

    if kind == "sheet":
        rp_path = Path(outputs) / args.chapter / \
            f"comic_render_plan_{args.chapter}.json"
        rp = json.loads(rp_path.read_text())
        rows = [r for r in rp["roster"] if r.get("flow_ref") == ref]
        if not rows:
            print(f"no roster entry for sheet ref: {ref}")
            return 2
        row = rows[0]
        led_path = Path(outputs) / "sheet_verdicts.json"
        led = json.loads(led_path.read_text()) if led_path.is_file() else {
            "scope": "book", "entities": {}}
        entry = build_sheet_entry(
            row["name"], ref, row.get("kind", "character"),
            row["image_prompt"], f"{args.chapter}/studio_images/{dst.name}",
            sha256_file(dst), passed_on=f"{args.chapter} {ref}",
            note=args.note)
        led.setdefault("entities", {})[ref] = entry
        led_path.write_text(json.dumps(led, ensure_ascii=False, indent=1))
        rep["ledger"] = {"flow_ref": ref, "verdict": "PASS"}
    print(json.dumps(rep))
    return 0


if __name__ == "__main__":
    sys.exit(main())
