#!/usr/bin/env python3
"""MythologyMuse Studio server (stdlib only, mock-only, no Muse calls).

Start:
    cd /Users/neerav/Documents/Projects/MythologyMuse/studio
    python3 server.py --port 8775
Then open http://localhost:8775 in a browser.
"""

from __future__ import annotations

import argparse
import json
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

STUDIO_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = STUDIO_DIR.parent

import bundle as bundle_mod
import state as state_mod
import image_gen as image_gen_mod


def resolve_mythology(name: str) -> tuple:
    root = (PROJECT_ROOT / name).resolve()
    if PROJECT_ROOT.resolve() not in root.parents and root != PROJECT_ROOT.resolve():
        raise ValueError("mythology escapes project root")
    outputs = root / "outputs"
    return root, outputs


class Handler(BaseHTTPRequestHandler):
    server_version = "MythologyMuseStudio/1.0"

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)
        try:
            return self._do_GET(parsed, qs)
        except BrokenPipeError:
            return
        except Exception:  # noqa: BLE001 — log for the terminal, JSON for UI
            import traceback
            traceback.print_exc()
            try:
                return self._json({"error": "server error"}, 500)
            except Exception:
                return

    def _do_GET(self, parsed, qs):
        try:
            if parsed.path == "/api/chapters":
                myth = qs.get("mythology", ["mythologies/ramayana_dutt"])[0]
                _, outputs = resolve_mythology(myth)
                return self._json({"mythology": myth,
                                   "chapters": bundle_mod.list_chapters(outputs)})
            if parsed.path == "/api/chapter":
                myth = qs.get("mythology", ["mythologies/ramayana_dutt"])[0]
                cid = qs.get("id", [""])[0]
                if not cid:
                    return self._json({"error": "missing id"}, 400)
                _, outputs = resolve_mythology(myth)
                if cid not in bundle_mod.list_chapters(outputs):
                    return self._json({"error": "unknown chapter"}, 404)
                return self._json(bundle_mod.chapter_bundle(outputs, cid))
            if parsed.path == "/api/key-status":
                return self._json(image_gen_mod.key_status())
            if parsed.path == "/api/job":
                job = image_gen_mod.job_status(qs.get("id", [""])[0])
                if job is None:
                    return self._json({"error": "unknown job"}, 404)
                return self._json(job)
            if parsed.path == "/api/studio-image":
                myth = qs.get("mythology", ["mythologies/ramayana_dutt"])[0]
                cid = qs.get("chapter", [""])[0]
                fname = qs.get("file", [""])[0]
                _, outputs = resolve_mythology(myth)
                base = (outputs / cid / "studio_images").resolve()
                target = (base / fname).resolve() if fname else base
                if base in target.parents and target.is_file():
                    pass
                else:
                    # Shared entity look: a sheet final picked in another
                    # chapter of the same mythology still serves here.
                    # Panels and candidates stay per-chapter (never shared).
                    shared = image_gen_mod.find_servable_image(base, fname)
                    if shared is None:
                        return self._json({"error": "not found"}, 404)
                    target = shared.resolve()
                    ok_roots = [base,
                                (outputs.resolve() if outputs.exists() else base)]
                    if not any(r in target.parents or r == target.parent
                               for r in ok_roots):
                        return self._json({"error": "not found"}, 404)
                    if not target.is_file():
                        return self._json({"error": "not found"}, 404)
                body = target.read_bytes()
                if body[:4] == b"RIFF" and body[8:12] == b"WEBP":
                    ctype = "image/webp"
                elif body[:2] == bytes([255, 216]):
                    ctype = "image/jpeg"
                elif body[:8] == bytes([137, 80, 78, 71, 13, 10, 26, 10]):
                    ctype = "image/png"
                else:
                    ctype = "application/octet-stream"
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
        except ValueError as e:
            return self._json({"error": str(e)}, 400)

        # static
        rel = parsed.path.lstrip("/") or "index.html"
        target = (STUDIO_DIR / "static" / rel).resolve()
        if STUDIO_DIR.joinpath("static").resolve() not in target.parents:
            self.send_response(403)
            self.end_headers()
            return
        if target.is_file():
            ctype = "text/plain"
            if target.suffix == ".html":
                ctype = "text/html; charset=utf-8"
            elif target.suffix == ".js":
                ctype = "text/javascript; charset=utf-8"
            elif target.suffix == ".css":
                ctype = "text/css; charset=utf-8"
            body = target.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.end_headers()

    def _resolve_target(self, outputs, chapter, target):
        """One sheet or one panel per request (no bulk)."""
        import re as _re
        b = bundle_mod.chapter_bundle(outputs, chapter)
        kind = (target or {}).get("kind", "")
        if kind == "sheet":
            ref = (target or {}).get("ref", "") or ""
            entry = next((r for r in b["roster"]
                          if r.get("flow_ref") == ref), None)
            if entry is None and ref:
                entry = next((r for r in b["roster"]
                              if r.get("name") == ref), None)
            if entry is None:
                raise ValueError(
                    f"unknown roster ref: {ref!r}" if ref
                    else "sheet target needs a roster ref (got empty)")
            if not entry.get("flow_ref") and not entry.get("image_prompt"):
                raise ValueError(
                    f"{entry.get('name') or ref!r} is not a character sheet "
                    "subject (no flow ref, no image prompt) — nothing to "
                    "generate")
            key = entry.get("flow_ref") or entry.get("name") or ref
            safe = image_gen_mod.sheet_safe(key)
            is_scene = (entry.get("kind", "") == "scene")
            return {"prompt": entry.get("image_prompt") or entry.get("name"),
                    "aspect": "16:9" if is_scene else "2:3",
                    "prefix": f"sheet_{safe}_candidate",
                    "kind": "sheet", "sheet_ref": key,
                    "style_which": "comics" if is_scene else "characters",
                    "label": entry.get("name", ref)}
        if kind == "panel":
            slide = int((target or {}).get("slide", -1))
            entry = next((s for s in b["slides"] if s["slide"] == slide), None)
            if entry is None or not entry["muse_prompt"]:
                raise ValueError("unknown slide or missing muse_prompt")
            imgs = image_gen_mod.images_dir(outputs, chapter)
            cast, picked_names = [], []
            subs = entry["subjects"] or []
            ordered = ([s for s in subs
                        if isinstance(s, dict) and s.get("kind", "") == "scene"]
                       + [s for s in subs
                          if not (isinstance(s, dict)
                                  and s.get("kind", "") == "scene")])
            for s in ordered:
                if isinstance(s, dict):
                    ref = s.get("flow_ref", "") or s.get("name", "")
                    cast.append({"name": s.get("name", ""), "ref": ref})
                    if image_gen_mod.sheet_final(imgs, ref) is not None:
                        picked_names.append(s.get("name", ""))
                elif s:
                    cast.append({"name": s, "ref": s})
                    if image_gen_mod.sheet_final(imgs, s) is not None:
                        picked_names.append(s)
            return {"prompt": entry["muse_prompt"], "aspect": "16:9",
                    "prefix": f"slide_{slide:02d}_candidate",
                    "kind": "panel", "cast": cast,
                    "ref_names": picked_names,
                    # attach-all: every picked final rides the turn, so
                    # nothing is omitted client-side (API-side fallback, if
                    # any, is recorded in the panel lineage instead).
                    "omitted": 0,
                    "slide": slide,
                    "label": entry["slide_label"]}
        raise ValueError("target must be sheet or panel")

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        try:
            return self._do_POST(parsed)
        except BrokenPipeError:
            return
        except Exception:  # noqa: BLE001 — log for the terminal, JSON for UI
            import traceback
            traceback.print_exc()
            try:
                return self._json({"error": "server error"}, 500)
            except Exception:
                return

    def _do_POST(self, parsed):
        if parsed.path not in ("/api/review", "/api/generate", "/api/select"):
            self.send_response(404)
            self.end_headers()
            return
        try:
            n = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(n) or b"{}")
            myth = payload.get("mythology", "mythologies/ramayana_dutt")
            cid = payload.get("chapter", "")
            _, outputs = resolve_mythology(myth)
            if cid not in bundle_mod.list_chapters(outputs):
                return self._json({"error": "unknown chapter"}, 404)
            if parsed.path == "/api/generate":
                try:
                    resolved = self._resolve_target(
                        outputs, cid, payload.get("target"))
                except ValueError as e:
                    return self._json({"error": str(e)}, 400)
                if not image_gen_mod.key_status()["configured"]:
                    return self._json({"error": "image key not configured"}, 409)
                dest = image_gen_mod.images_dir(outputs, cid)
                job_id = image_gen_mod.start_job(
                    "image", f"{cid} {resolved['label']}",
                    image_gen_mod.generate_sync,
                    prompt=resolved["prompt"], aspect=resolved["aspect"],
                    file_prefix=resolved["prefix"], dest_dir=dest,
                    extra=payload.get("extra_prompt", ""),
                    kind=resolved.get("kind", "panel"),
                    sheet_ref=resolved.get("sheet_ref"),
                    style_which=resolved.get("style_which", "characters"),
                    cast=resolved.get("cast", []),
                    log={"dir": str(dest), "slide": resolved.get("slide")})
                return self._json({"ok": True, "job_id": job_id,
                                   "refs_used": len(resolved.get("ref_names", [])),
                                   "ref_names": resolved.get("ref_names", []),
                                   "omitted": resolved.get("omitted", 0),
                                   "prefix": resolved["prefix"],
                                   "aspect": resolved["aspect"]})
            if parsed.path == "/api/select":
                try:
                    if payload.get("kind") == "panel":
                        final = image_gen_mod.select_panel_candidate(
                            outputs, cid, int(payload.get("slide", -1)),
                            str(payload.get("file", "")))
                    else:
                        final = image_gen_mod.select_candidate(
                            outputs, cid, str(payload.get("ref", "")),
                            str(payload.get("file", "")))
                except ValueError as e:
                    code = 404 if str(e) == "not found" else 400
                    return self._json({"error": str(e)}, code)
                return self._json({"ok": True, "final": final})
            slide = payload.get("slide")
            decision = payload.get("decision", "")
            note = payload.get("note", "")
            if slide is None:
                data = state_mod.set_chapter(outputs, cid, decision, note)
            else:
                data = state_mod.set_slide(outputs, cid, int(slide), decision, note)
            return self._json({"ok": True, "review": data})
        except (ValueError, json.JSONDecodeError) as e:
            return self._json({"error": str(e)}, 400)

    def log_message(self, *a):
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8775)
    args = ap.parse_args()
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"studio: http://localhost:{args.port} (Ctrl-C to stop)")
    srv.serve_forever()


if __name__ == "__main__":
    main()
