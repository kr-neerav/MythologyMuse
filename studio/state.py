#!/usr/bin/env python3
"""Studio review state: per-chapter approve/redo flags beside pipeline outputs.

Copy-never-move: reads pipeline files, writes only
`studio_review_<chapter>.json` (atomic tmp+replace). Never touches the
entity repository or other pipeline outputs.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

DECISIONS = ("unreviewed", "approved", "needs_redo")


def review_path(outputs_dir: Path, chapter: str) -> Path:
    return outputs_dir / chapter / f"studio_review_{chapter}.json"


def load_review(outputs_dir: Path, chapter: str) -> dict:
    p = review_path(outputs_dir, chapter)
    if not p.exists():
        return {"chapter": chapter, "slides": {}, "chapter_decision": "unreviewed",
                "note": "", "updated_at": 0}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"chapter": chapter, "slides": {}, "chapter_decision": "unreviewed",
                "note": "", "updated_at": 0}


def save_review(outputs_dir: Path, chapter: str, data: dict) -> Path:
    p = review_path(outputs_dir, chapter)
    p.parent.mkdir(parents=True, exist_ok=True)
    data = dict(data)
    data["chapter"] = chapter
    data["updated_at"] = time.time()
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, p)
    return p


def set_slide(outputs_dir: Path, chapter: str, slide: int,
              decision: str, note: str = "") -> dict:
    if decision not in DECISIONS:
        raise ValueError(f"bad decision: {decision}")
    data = load_review(outputs_dir, chapter)
    slides = dict(data.get("slides", {}))
    slides[str(slide)] = {"decision": decision, "note": note,
                          "updated_at": time.time()}
    data["slides"] = slides
    save_review(outputs_dir, chapter, data)
    return data


def set_chapter(outputs_dir: Path, chapter: str, decision: str,
                note: str = "") -> dict:
    if decision not in DECISIONS:
        raise ValueError(f"bad decision: {decision}")
    data = load_review(outputs_dir, chapter)
    data["chapter_decision"] = decision
    data["note"] = note
    save_review(outputs_dir, chapter, data)
    return data
