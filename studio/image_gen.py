#!/usr/bin/env python3
"""UI-triggered Muse Image generation for the studio (spend-gated).

Key reuse: reads the API key + endpoint straight from the museimages
`.env` at call time (default sibling path, overridable with
MUSEIMAGES_DIR). The key is never copied, never persisted, never logged,
never returned by any API — only a configured/missing boolean leaves this
module.

Each UI click generates at most 2 candidates for ONE sheet or ONE slide
(no bulk mode in v1). Sheets render from roster `image_prompt`; panels
render from the slide `muse_prompt` plus approved sheet finals as
reference images (same consistency pattern as museimages).
"""

from __future__ import annotations

import base64
import json
import os
import re
import threading
import time
import urllib.request
from pathlib import Path

STUDIO_DIR = Path(__file__).resolve().parent
DEFAULT_MUSEIMAGES_DIR = Path("/Users/neerav/Documents/Projects/museimages")
DEFAULT_RESPONSES_URL = "https://api.meta.ai/v1/responses"
DEFAULT_MODEL = "muse-image-1.0"
MAX_CANDIDATES = 2
MAX_REFS = 2  # legacy collect_refs cap only; the panel path
# attaches EVERY finalized ref (see partition_refs)

# Attested tool sizes (Meta anchored-generation recipe): portrait sheets and
# landscape panels. Unknown sizes fail loudly at the API, never silently.
SIZE_BY_ASPECT = {"2:3": "1024x1536", "16:9": "1536x1024", "1:1": "1024x1024"}

BUILTIN_COMICS_STYLE = (
    "bold clean comic-book line art with thick black outlines, flat vivid "
    "colors, classical Indian mythological comic style, stylized faces")
BUILTIN_SHEET_STYLE = (
    BUILTIN_COMICS_STYLE + ", full-figure character model sheet")

_JOBS: dict = {}
_JOBS_LOCK = threading.Lock()


class KeyMissing(RuntimeError):
    pass


def museimages_dir() -> Path:
    override = os.getenv("MUSEIMAGES_DIR", "").strip()
    return Path(override) if override else DEFAULT_MUSEIMAGES_DIR


def load_dotenv_vars(env_file: Path) -> dict:
    vars_: dict = {}
    try:
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            vars_[k.strip()] = v.strip().strip("'\"")
    except OSError:
        pass
    return vars_


def muse_credentials() -> tuple:
    """Returns (api_key, api_base_endpoint). Raises KeyMissing when unusable."""
    env = load_dotenv_vars(museimages_dir() / ".env")
    for k in ("MUSE_IMAGE_API_KEY", "MUSE_API_KEY", "MIDJOURNEY_API_KEY"):
        if env.get(k):
            endpoint = (env.get("MIDJOURNEY_API_URL", "")
                        or DEFAULT_RESPONSES_URL)
            return env[k], endpoint
    raise KeyMissing("no API key in museimages .env")


def responses_url(api_endpoint: str) -> str:
    """Responses API URL: explicit MUSE_IMAGE_URL wins, else host + /v1/responses."""
    override = os.getenv("MUSE_IMAGE_URL", "").strip()
    if override:
        return override
    m = re.match(r"(https?://[^/]+)", api_endpoint or "")
    host = m.group(1) if m else "https://api.meta.ai"
    return host + "/v1/responses"


def key_status() -> dict:
    try:
        _, endpoint = muse_credentials()
        url = responses_url(endpoint)
        host = url.split("/")[2] if "://" in url else url
        return {"configured": True, "endpoint_host": host,
                "transport": "responses"}
    except KeyMissing:
        return {"configured": False, "endpoint_host": "",
                "transport": "responses"}


def image_style(which: str) -> str:
    """Comic style preamble, every prompt. museimages canon first, else builtin."""
    override = os.getenv("MUSE_IMAGE_STYLE", "").strip()
    if override:
        return override
    try:
        settings = json.loads(
            (museimages_dir() / "settings.json").read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        settings = {}
    key = "comics_meta_prompt" if which == "comics" else "characters_meta_prompt"
    base = (settings.get(key, "") if isinstance(settings, dict) else "").strip()
    if not base:
        base = BUILTIN_COMICS_STYLE if which == "comics" else BUILTIN_SHEET_STYLE
    if "photoreal" not in base.lower():
        base += ", no photorealism"
    return base


def build_effective_prompt(base: str, style: str = "", extra: str = "") -> str:
    parts = []
    if style and style.strip():
        parts.append(style.strip().rstrip("."))
    parts.append(base.strip())
    if extra and extra.strip():
        parts.append(f"[Modification: {extra.strip()}]")
    text = ". ".join(parts)
    text = re.sub(r"--[a-zA-Z0-9.\s]+(?::[0-9]+)?", "", text).strip()
    return re.sub(r"(?<!\d)::?[0-9]+(?:\.[0-9]+)?\b", "", text).strip()


def images_dir(outputs_dir: Path, chapter: str) -> Path:
    d = outputs_dir / chapter / "studio_images"
    d.mkdir(parents=True, exist_ok=True)
    return d


def sheet_safe(flow_ref: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", flow_ref).strip("_")


def _sibling_image_dirs(images: Path) -> list:
    """Sibling chapter studio_images dirs in the same mythology outputs dir.

    Derived from the conventional layout <outputs>/<chapter>/studio_images
    so existing (images, ref) call sites gain sharing without signature
    changes. Backup/hidden dirs (leading _ or .) are skipped. Returns [] for
    non-conventional paths (e.g. bare tmp dirs in unit tests).
    """
    try:
        images = Path(images)
    except Exception:
        return []
    if images.name != "studio_images":
        return []
    try:
        outputs = images.parent.parent
        if not outputs.is_dir():
            return []
        sibs = []
        for child in sorted(outputs.iterdir()):
            if child.name.startswith("_") or child.name.startswith("."):
                continue
            try:
                d = child / "studio_images"
                if d.is_dir() and d != images:
                    sibs.append(d)
            except OSError:
                continue
        return sibs
    except OSError:
        return []


def sheet_final(images: Path, flow_ref: str) -> Path | None:
    """Local final first, else the newest same-name final from a sibling
    chapter in the same mythology outputs dir.

    Entities are common across chapters and books, so a look finalized once
    (e.g. Rama in Chapter 1) reads as ready everywhere in that mythology.
    A local final always wins, preserving per-chapter overrides. Never
    crosses mythologies: the search stays inside the one outputs dir.
    """
    if not flow_ref:
        return None
    images = Path(images)
    safe = sheet_safe(flow_ref)
    if not safe:
        return None
    fname = f"sheet_{safe}_final.jpg"
    try:
        local = images / fname
        if local.is_file():
            return local
    except OSError:
        pass
    best = None
    best_mtime = -1.0
    for sib in _sibling_image_dirs(images):
        try:
            cand = sib / fname
            if not cand.is_file():
                continue
            mt = cand.stat().st_mtime
        except OSError:
            continue
        if best is None or mt > best_mtime:
            best, best_mtime = cand, mt
    return best


def find_servable_image(images: Path, fname: str) -> Path | None:
    """Local file first, else a sibling chapter's copy of a sheet final.

    Only sheet finals (sheet_*_final.jpg) are shared: panel renders and
    candidate iterations stay per-chapter, so a pick in one chapter can
    never leak another chapter's slide. Returns None for traversal garbage.
    """
    from pathlib import Path as _P
    if not fname or fname != _P(fname).name:
        return None
    images = _P(images)
    try:
        local = images / fname
        if local.is_file():
            return local
    except OSError:
        pass
    if not (fname.startswith("sheet_") and fname.endswith("_final.jpg")):
        return None
    best = None
    best_mtime = -1.0
    for sib in _sibling_image_dirs(images):
        try:
            cand = sib / fname
            if not cand.is_file():
                continue
            mt = cand.stat().st_mtime
        except OSError:
            continue
        if best is None or mt > best_mtime:
            best, best_mtime = cand, mt
    return best


def sheet_candidates(images: Path, flow_ref: str) -> list:
    """Existing candidate files (not finals), sorted. Legacy names included."""
    safe = sheet_safe(flow_ref)
    out = []
    for p in sorted(images.glob(f"sheet_{safe}_*.jpg")):
        if p.name == f"sheet_{safe}_final.jpg":
            continue
        out.append(p)
    return out


def sheet_status(images: Path, flow_ref: str) -> dict:
    """missing | review | ready — the cast-review state machine."""
    if not flow_ref:
        return {"state": "missing", "final": "", "candidates": []}
    final = sheet_final(images, flow_ref)
    cands = [p.name for p in sheet_candidates(images, flow_ref)]
    if final is not None:
        return {"state": "ready", "final": final.name, "candidates": cands}
    if cands:
        return {"state": "review", "final": "", "candidates": cands}
    return {"state": "missing", "final": "", "candidates": []}


def collect_refs(images: Path, subjects: list) -> list:
    refs = []
    for s in subjects or []:
        if isinstance(s, str):
            cands = [s]
        else:
            cands = [s.get("flow_ref", ""), s.get("name", "")]
        hit = None
        for cand in cands:
            if cand:
                hit = sheet_final(images, cand)
                if hit is not None:
                    break
        if hit is not None:
            refs.append(hit)
        if len(refs) >= MAX_REFS:
            break
    return refs


def partition_refs(picked: list) -> tuple:
    """Split picked finals into (prev_id, prev_ref, files) for a turn.

    The first anchorable ref chains via previous_response_id; EVERY other
    finalized ref file-attaches — no cap, so the whole staged cast
    (place first, then characters) conditions the render. Extras are never
    silently dropped; if the API rejects the shape, the caller degrades
    loudly with the body recorded.
    """
    prev_id, prev_ref = None, ""
    for p in picked:
        if p["anchor_id"]:
            prev_id, prev_ref = p["anchor_id"], p["name"]
            break
    files = [(p["name"], p["file"]) for p in picked
             if not prev_id or p["name"] != prev_ref]
    return prev_id, prev_ref, files


def _post_json(url: str, payload: dict, api_key: str, timeout: int = 300) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {api_key}",
                 "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def _post_responses(url: str, body: dict, api_key: str) -> dict:
    """One Responses call with a single retry on 5xx/timeout only.

    4xx errors raise immediately as body-carrying RuntimeErrors: a rejected
    anchor shape must fail loudly, never degrade into an unconditioned
    render, and the API's own message must survive in the error.
    """
    import time as _time
    import urllib.error as _urlerror

    def _convert(e):
        code = getattr(e, "code", None)
        try:
            raw = e.read().decode(errors="replace")[:300] if hasattr(e, "read") else ""
        except Exception:
            raw = ""
        msg = raw or getattr(e, "reason", "") or e
        err = RuntimeError(f"image API HTTP {code}: {msg}")
        err.status_code = code
        return err

    try:
        return _post_json(url, body, api_key)
    except _urlerror.HTTPError as e:
        if e.code is not None and 500 <= e.code < 600:
            _time.sleep(5)
            try:
                return _post_json(url, body, api_key)
            except Exception as e2:
                if isinstance(e2, _urlerror.HTTPError):
                    raise _convert(e2) from e2
                raise RuntimeError(f"image API unreachable ({e2})") from e2
        raise _convert(e) from e
    except (TimeoutError, _urlerror.URLError) as e:
        _time.sleep(5)
        try:
            return _post_json(url, body, api_key)
        except Exception as e2:
            if isinstance(e2, _urlerror.HTTPError):
                raise _convert(e2) from e2
            raise RuntimeError(f"image API unreachable ({e2})") from e2


def _chain_path(images: Path) -> Path:
    return images / "response_chain.json"


def read_chain(images: Path) -> dict:
    try:
        d = json.loads(_chain_path(images).read_text(encoding="utf-8"))
        if not isinstance(d, dict):
            d = {}
    except (json.JSONDecodeError, OSError):
        d = {}
    d.setdefault("head", None)
    if not isinstance(d.get("anchors"), dict):
        d["anchors"] = {}
    return d


def write_chain(images: Path, chain: dict):
    tmp = _chain_path(images).with_suffix(".tmp")
    tmp.write_text(json.dumps(chain, indent=1), encoding="utf-8")
    os.replace(tmp, _chain_path(images))


def sidecar_path(images: Path, safe: str) -> Path:
    return images / f"sheet_{safe}_responses.json"


def _extract_image(data: dict) -> str | None:
    for item in data.get("output", []) or []:
        if (isinstance(item, dict) and item.get("type") == "image_generation_call"
                and item.get("result")):
            return item["result"]
    return None


def log_panel(images: Path, slide: int, lineage: dict):
    """Append one panel render record. Read back by the bundle (never silent)."""
    log = images / "panel_log.json"
    try:
        entries = json.loads(log.read_text(encoding="utf-8"))
        if not isinstance(entries, list):
            entries = []
    except (json.JSONDecodeError, OSError):
        entries = []
    entries.append({"slide": slide, **lineage})
    tmp = log.with_suffix(".tmp")
    tmp.write_text(json.dumps(entries, indent=1), encoding="utf-8")
    os.replace(tmp, log)


def _data_url(path) -> str:
    """Base64 data URL with the mediatype sniffed from the actual bytes.

    Our files carry .jpg names but are usually WEBP bytes; declaring
    image/jpeg for WEBP bytes gets the turn rejected, so sniff first.
    """
    raw = Path(path).read_bytes()
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        mt = "image/webp"
    elif raw[:2] == bytes([255, 216]):
        mt = "image/jpeg"
    elif raw[:8] == bytes([137, 80, 78, 71, 13, 10, 26, 10]):
        mt = "image/png"
    else:
        mt = "application/octet-stream"
    return f"data:{mt};base64," + base64.b64encode(raw).decode()


def _http_body(e) -> str:
    try:
        return e.read().decode(errors="replace")[:300]
    except Exception:
        return ""


def _save_image_bytes(raw: bytes, dest: Path):
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(raw)


def _validate_turn_body(body: dict):
    """Local shape gate: reject malformed turns BEFORE any paid call.

    input must be a string or an ARRAY of message items (a bare object is
    rejected by the API); the image tool needs an attested size. A shape
    bug must cost $0 here, never a 400 out there.
    """
    problems = []
    inp = body.get("input")
    if not isinstance(inp, (str, list)):
        problems.append("input must be a string or an array of items")
    if isinstance(inp, list):
        for item in inp:
            if not isinstance(item, dict) or "role" not in item:
                problems.append("array input items must be message objects")
                break
    tools = body.get("tools", [])
    sizes = set(SIZE_BY_ASPECT.values())
    if not (isinstance(tools, list) and tools
            and tools[0].get("type") == "image_generation"
            and tools[0].get("size") in sizes):
        problems.append(f"tool must be image_generation with size in {sorted(sizes)}")
    if not body.get("model"):
        problems.append("model is required")
    if problems:
        raise ValueError("bad turn body: " + "; ".join(problems))


def _turn(api_key: str, url: str, text: str, size: str,
            prev_id: str | None, file_parts: list) -> tuple:
    """One Responses turn. Returns (response_id, b64_image)."""
    if file_parts:
        content: list = [{"type": "input_text", "text": text}]
        for _, path in file_parts:
            content.append({"type": "input_image",
                            "image_url": _data_url(path)})
        # Responses API takes a string or an ARRAY of items: a bare object
        # is rejected with "`input` did not match any supported type".
        body_input: object = [{"role": "user", "content": content}]
    else:
        body_input = text
    body: dict = {"model": DEFAULT_MODEL, "input": body_input,
                  "tools": [{"type": "image_generation", "size": size}]}
    if prev_id:
        body["previous_response_id"] = prev_id
    _validate_turn_body(body)
    data = _post_responses(url, body, api_key)
    b64 = _extract_image(data)
    if not b64:
        raise RuntimeError(
            f"image API returned no image (status {data.get('status')})")
    return data.get("id"), b64



def _file_override(names: list) -> str:
    """Per-subject override so attached finals beat stale prompt words.

    Panel prompts are written at design time from the original character
    drafts. When the user later finalizes a different look (e.g. a young
    Narada over a 'sage of sixty, white beard' description), the stale
    words would otherwise fight the picked reference on the turn. Naming
    each attached subject explicitly makes its file win.
    """
    if not names:
        return ""
    lines = [
        f"- {n}: depict this character EXACTLY as shown in the attached "
        f"'{n}' reference image — same face, same apparent age, same "
        f"garments and attributes. Ignore any conflicting age, beard, hair, "
        f"build, or clothing description of {n} elsewhere in this prompt; "
        "those words describe an older draft, not the final design."
        for n in names
    ]
    return (" CHARACTER REFERENCE OVERRIDES (highest priority — these win "
            "over every character description above):\n" + "\n".join(lines))


def generate_sync(*, prompt: str, aspect: str, file_prefix: str,
                  dest_dir: Path, extra: str = "",
                  kind: str = "panel", sheet_ref: str | None = None,
                  style_which: str = "characters",
                  cast: list | None = None, candidates: int = 2,
                  log: dict | None = None) -> dict:
    """One blocking generation of up to 2 candidates via the Responses API.

    Sheets chain from the chapter head and record per-file response ids;
    panels chain from the first picked anchor and file-attach picked finals
    that predate response ids. Attached finals carry a per-subject override
    so picked looks beat stale design-time words. Returns {"candidates":
    [...], "lineage": {...}}.
    A rejected anchor shape fails loudly (recorded); only the file-attach
    step degrades, and that degradation is recorded, never silent.
    """
    api_key, base_ep = muse_credentials()
    url = responses_url(base_ep)
    size = SIZE_BY_ASPECT.get(aspect, "1024x1024")
    images = Path(dest_dir)
    images.mkdir(parents=True, exist_ok=True)
    chain = read_chain(images)

    if kind == "sheet":
        style = image_style(style_which)
        text = build_effective_prompt(f"{prompt}, {style}, no text",
                                      extra=extra)
        prev = chain.get("head")
        ids: dict = {}
        saved = []
        for i in range(1, max(1, candidates) + 1):
            rid, b64 = _turn(api_key, url, text, size, prev, [])
            dest = images / f"{file_prefix}_{i}.jpg"
            _save_image_bytes(base64.b64decode(b64), dest)
            ids[dest.name] = rid
            saved.append({"candidate_index": i, "image_path": str(dest),
                          "aspect": aspect, "size": size,
                          "created_at": time.time()})
        if sheet_ref:
            sc = sidecar_path(images, sheet_safe(sheet_ref))
            sc.write_text(json.dumps(ids, indent=1), encoding="utf-8")
        if ids:
            chain["head"] = ids[f"{file_prefix}_{len(ids)}.jpg"]
            write_chain(images, chain)
        lineage = {"at": time.time(), "model": DEFAULT_MODEL, "size": size,
                   "transport": "responses", "chained_from": prev,
                   "response_ids": ids, "refs": [], "omitted_refs": 0,
                   "fallback": False, "fallback_reason": "", "prompt": text}
        return {"candidates": saved, "lineage": lineage}

    style = image_style("comics")
    text = build_effective_prompt(
        f"{prompt}, {style}, no speech bubbles, no text, single comic panel",
        extra=extra)
    picked = []
    for c in cast or []:
        name = c.get("name", "")
        ref = c.get("ref", "")
        fin = sheet_final(images, ref) if ref else None
        if fin is None:
            continue
        aid = (chain.get("anchors", {}).get(sheet_safe(ref), {}) or {}
               ).get("response_id")
        picked.append({"name": name, "file": fin, "anchor_id": aid})
    prev_id, prev_ref, files = partition_refs(picked)
    anchored = ([prev_ref] if prev_ref else []) + [n for n, _ in files]
    named = [p["name"] for p in picked]
    omitted = len(picked) - len(anchored)
    fallback, fb_reason = False, ""
    attempted_files = list(files)
    override = _file_override([n for n, _ in files])
    sent_text = text + override if files else text
    try:
        first_id, first_b64 = _turn(api_key, url, sent_text, size,
                                    prev_id, files)
    except Exception as e:  # noqa: BLE001 — attach rejected: degrade, record
        sc = getattr(e, "status_code", getattr(e, "code", None))
        if sc is not None and not 400 <= sc < 500:
            raise
        err_body = _http_body(e)
        fallback, fb_reason = True, (f"anchor rejected ({e}); text+style only"
                                     + (f" — {err_body}" if err_body else ""))
        prev_id, prev_ref, files = None, "", []
        sent_text = text
        try:
            first_id, first_b64 = _turn(api_key, url, sent_text, size,
                                        None, [])
        except Exception as e2:
            raise RuntimeError(
                f"panel render failed ({e2}); anchor attempt said: {fb_reason}"
            ) from e2
    turns = [(1, first_b64)]
    if max(1, candidates) > 1:
        second_id, second_b64 = _turn(api_key, url, sent_text, size,
                                      prev_id, files)
        turns.append((2, second_b64))
    saved = []
    for i, b64 in turns:
        dest = images / f"{file_prefix}_{i}.jpg"
        _save_image_bytes(base64.b64decode(b64), dest)
        saved.append({"candidate_index": i, "image_path": str(dest),
                      "aspect": aspect, "size": size,
                      "created_at": time.time()})
    lineage = {"at": time.time(), "model": DEFAULT_MODEL, "size": size,
               "transport": "responses",
               "prev_anchor": {"ref": prev_ref, "response_id": prev_id},
               "file_attached": [n for n, _ in attempted_files],
               "refs": named, "omitted_refs": omitted,
               "fallback": fallback, "fallback_reason": fb_reason,
               "prompt": sent_text,
               "file_override": override if not fallback else ""}
    if log is not None and log.get("slide") is not None:
        log_panel(images, int(log["slide"]), lineage)
    return {"candidates": saved, "lineage": lineage}


def select_candidate(outputs_dir, chapter: str, ref: str, fname: str) -> str:
    """Copy one candidate to the ref's final. Keeps candidates. Raises ValueError."""
    from pathlib import Path as _P
    safe = sheet_safe(ref)
    if not ref or not fname or fname != _P(fname).name:
        raise ValueError("bad selection")
    if not fname.startswith(f"sheet_{safe}_") or not fname.endswith(".jpg"):
        raise ValueError("bad selection")
    base = (_P(outputs_dir) / chapter / "studio_images").resolve()
    src = (base / fname).resolve()
    if base not in src.parents or not src.is_file():
        raise ValueError("not found")
    import shutil
    dest = base / f"sheet_{safe}_final.jpg"
    shutil.copy(src, dest)
    try:
        sidecar = json.loads(
            sidecar_path(base, safe).read_text(encoding="utf-8"))
        rid = sidecar.get(fname) if isinstance(sidecar, dict) else None
    except (json.JSONDecodeError, OSError):
        rid = None
    chain = read_chain(base)
    chain["anchors"][safe] = {"response_id": rid, "file": dest.name,
                              "at": time.time()}
    if rid:
        chain["head"] = rid
    write_chain(base, chain)
    return dest.name



def panel_final(images: Path, slide) -> Path | None:
    """The picked panel final for a slide, if one was finalized."""
    try:
        n = int(slide)
    except (TypeError, ValueError):
        return None
    dest = images / f"slide_{n:02d}_final.jpg"
    return dest if dest.exists() else None


def select_panel_candidate(outputs_dir, chapter, slide, fname: str) -> str:
    """Copy one panel candidate to the slide's final. Keeps candidates.

    Mirrors select_candidate: copy-never-move, traversal-proof, ValueError
    ("bad selection" / "not found") for the endpoint to map to 400/404.
    """
    from pathlib import Path as _P
    n = int(slide)  # ValueError on garbage → 400 upstream
    if not fname or fname != _P(fname).name:
        raise ValueError("bad selection")
    if (not fname.startswith(f"slide_{n:02d}_candidate_")
            or not fname.endswith(".jpg")):
        raise ValueError("bad selection")
    base = (_P(outputs_dir) / chapter / "studio_images").resolve()
    src = (base / fname).resolve()
    if base not in src.parents or not src.is_file():
        raise ValueError("not found")
    import shutil
    dest = base / f"slide_{n:02d}_final.jpg"
    shutil.copy(src, dest)
    return dest.name

def _run_job(job_id: str, fn, *args, **kwargs):
    with _JOBS_LOCK:
        _JOBS[job_id].update(status="running", updated_at=time.time())
    try:
        result = fn(*args, **kwargs)
        with _JOBS_LOCK:
            _JOBS[job_id].update(status="done", result=result,
                                 updated_at=time.time())
    except Exception as e:  # noqa: BLE001 — surfaced to the UI poll
        with _JOBS_LOCK:
            _JOBS[job_id].update(status="error", error=str(e),
                                 updated_at=time.time())


def start_job(job_kind: str, label: str, fn, *args, **kwargs) -> str:
    job_id = f"{job_kind}-{int(time.time() * 1000)}"
    with _JOBS_LOCK:
        _JOBS[job_id] = {"job_id": job_id, "kind": job_kind, "label": label,
                         "status": "queued", "result": None, "error": "",
                         "created_at": time.time(), "updated_at": time.time()}
    t = threading.Thread(target=_run_job, args=(job_id, fn) + args,
                         kwargs=kwargs, daemon=True)
    t.start()
    return job_id


def job_status(job_id: str) -> dict | None:
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        return dict(job) if job else None
