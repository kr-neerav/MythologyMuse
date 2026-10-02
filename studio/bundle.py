#!/usr/bin/env python3
"""Chapter bundle assembly (read-only) + deterministic mock image placeholders.

Reads pipeline outputs for one chapter and returns a single JSON-able
bundle for the review UI. Never writes. Mock images are inline SVG strings
(no deps, no network, no spend) keyed by label so text<->image mapping can
be reviewed before any real Muse Image wiring.
"""

from __future__ import annotations

import html
import json
from pathlib import Path

import image_gen as image_gen_mod


def _load_json(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def mock_svg(label: str, aspect: str, sub: str = "") -> str:
    w, h = (320, 180) if aspect == "16:9" else (180, 270)
    safe = html.escape(label[:42])
    sub = html.escape(sub[:60])
    return (
        f"<svg xmlns='http://www.w3.org/2000/svg' width='{w}' height='{h}' "
        f"viewBox='0 0 {w} {h}'><rect width='{w}' height='{h}' fill='#1d1a14'/>"
        f"<rect x='8' y='8' width='{w-16}' height='{h-16}' fill='none' "
        f"stroke='#b98a2f' stroke-width='2'/>"
        f"<text x='{w//2}' y='{h//2-8}' fill='#e8d9b0' font-size='13' "
        f"text-anchor='middle' font-family='Georgia,serif'>{safe}</text>"
        f"<text x='{w//2}' y='{h//2+12}' fill='#9c8a63' font-size='10' "
        f"text-anchor='middle' font-family='Georgia,serif'>{sub} {aspect} mock</text>"
        "</svg>"
    )


def list_chapters(outputs_dir: Path) -> list:
    if not outputs_dir.is_dir():
        return []
    return sorted(p.name for p in outputs_dir.iterdir() if p.is_dir())


def chapter_bundle(outputs_dir: Path, chapter: str) -> dict:
    d = outputs_dir / chapter
    board = _load_json(d / f"comic_storyboard_{chapter}.json", [])
    prompts = _load_json(d / f"comic_muse_prompts_{chapter}.json", [])
    hindi = _load_json(d / f"comic_storyboard_hindi_{chapter}.json", [])
    ev = _load_json(d / f"comic_eval_{chapter}.json", {})
    prog = _load_json(d / f"comic_progress_{chapter}.json", {})
    plan = _load_json(d / f"comic_render_plan_{chapter}.json", {})
    review = _load_json(d / f"studio_review_{chapter}.json", {})

    panel_log = _load_json(d / "studio_images" / "panel_log.json", [])
    panel_hist = {}
    if isinstance(panel_log, list):
        for e in panel_log:
            if isinstance(e, dict) and e.get("slide") is not None:
                panel_hist[int(e["slide"])] = e
    prompt_by_slide = {p.get("slide"): p for p in prompts if isinstance(p, dict)}
    hindi_by_slide = {h.get("slide"): h for h in hindi if isinstance(h, dict)}
    plan_slides = {s.get("slide"): s for s in plan.get("slides", [])
                   if isinstance(s, dict)} if isinstance(plan, dict) else {}
    roster_list = plan.get("roster", []) if isinstance(plan, dict) else []
    ref_by_name = {}
    for r in roster_list:
        if isinstance(r, dict):
            if r.get("flow_ref"):
                ref_by_name[str(r.get("name", "")).lower()] = r["flow_ref"]
                ref_by_name[str(r.get("flow_ref", "")).lower()] = r["flow_ref"]

    imgs = outputs_dir / chapter / "studio_images"  # read-only: no mkdir here
    def _subjects_with_refs(raw):
        out = []
        for s in raw or []:
            if isinstance(s, str):
                name, kind = s, ""
            else:
                name, kind = s.get("name", ""), s.get("kind", "")
            ref = ref_by_name.get(str(name).lower(), "")
            st = image_gen_mod.sheet_status(imgs, ref)
            out.append({"name": name, "kind": kind, "flow_ref": ref,
                        "sheet_state": st["state"],
                        "sheet_final": st["final"],
                        "sheet_candidates": st["candidates"],
                        # Junk entities (kind unknown, no flow_ref, e.g.
                        # "Kavya") can never resolve: no Generate button,
                        # excluded from missing counts and the panel gate.
                        "generatable": bool(ref)})
        return out

    slides = []
    for s in board:
        n = s.get("slide")
        pp = prompt_by_slide.get(n, {})
        hh = hindi_by_slide.get(n, {})
        ps = plan_slides.get(n, {})
        # Panel renders are stable files (slide_NN_candidate_*.jpg), so a
        # reload or a slide approval must resurface them like sheets.
        try:
            panel_cands = sorted(
                q.name for q in imgs.glob(f"slide_{int(n):02d}_candidate_*.jpg")
                if q.is_file())
        except (TypeError, ValueError):
            panel_cands = []
        _pf = image_gen_mod.panel_final(imgs, n)
        panel_final_name = _pf.name if _pf is not None else ""
        slides.append({
            "slide": n,
            "slide_label": s.get("slide_label", ""),
            "title": s.get("title", ""),
            "type": s.get("type", ""),
            "on_slide_text": s.get("on_slide_text", ""),
            "characters": s.get("characters", []),
            "location": s.get("location", ""),
            "rationale": s.get("rationale", ""),
            "muse_prompt": pp.get("muse_prompt", ""),
            "subjects": _subjects_with_refs(ps.get("subjects", [])),
            "panel_candidates": panel_cands,
            "panel_final": panel_final_name,
            "size": ps.get("size", ""),
            "panel_history": panel_hist.get(n),
            "hindi_text": hh.get("on_slide_text", ""),
            "mock_panel": mock_svg(s.get("slide_label", f"Slide {n}"), "16:9",
                                   s.get("title", "")),
        })

    roster = []
    for r in roster_list:
        if not isinstance(r, dict):
            continue
        ref = r.get("flow_ref", "")
        st = image_gen_mod.sheet_status(imgs, ref)
        roster.append({
            "name": r.get("name", ""),
            "flow_ref": ref,
            "kind": r.get("kind", ""),
            "image_prompt": r.get("image_prompt", ""),
            "sheet_state": st["state"],
            "sheet_final": st["final"],
            "sheet_candidates": st["candidates"],
            "mock_sheet": mock_svg(r.get("name", "?"), "2:3", r.get("kind", "")),
        })

    return {
        "chapter": chapter,
        "counts": {"board": len(board), "prompts": len(prompts),
                   "hindi": len(hindi), "roster": len(roster)},
        "eval_verdict": ev.get("verdict"),
        "eval_dry_run": ev.get("dry_run"),
        "manifest": prog,
        "roster": roster,
        "slides": slides,
        "review": review,
    }
