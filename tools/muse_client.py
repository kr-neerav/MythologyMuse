#!/usr/bin/env python3
"""MythologyMuse — Meta Muse text adapter (Phase 1).

Stateless client for the Muse text model plus mythology-scoped chapter
reading. Shared read-only tooling: it never writes outside the mythology
folder it is pointed at (`--mythology`), and in dry-run mode it performs no
network calls at all (canned fixtures, no key needed).

Config (env, see ../../.env.example):
    MUSE_API_KEY            required for live calls only
    MUSE_BASE_URL           default https://api.meta.ai/v1
    MUSE_MODEL              default muse-spark-1.3-contributor
    MUSE_MODEL_TIER         default contributor (informational)
    MUSE_THINKING_BUDGET    off|low|medium|high|xhigh|dynamic (default xhigh)
    MUSE_LLM_TIMEOUT        seconds, default 1800
    MUSE_MAX_TOKENS         default 32768

Usage:
    python3 tools/muse_client.py --smoke
    python3 tools/muse_client.py --mythology mythologies/ramayana_dutt --list
    python3 tools/muse_client.py --mythology mythologies/ramayana_dutt \\
        --chapter Book_1_Bala_Kanda_Chapter_1 --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = TOOLS_DIR.parent

# --- .env loading (repo root; never committed) -------------------------------
def load_dotenv(path: Path | None = None) -> None:
    candidates = [path] if path else []
    candidates += [Path.cwd() / ".env", PROJECT_ROOT / ".env"]
    for p in candidates:
        if p and p.is_file():
            for line in p.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip().strip('"').strip("'")
                if k and k not in os.environ:
                    os.environ[k] = v
            return


load_dotenv()

# --- Config ------------------------------------------------------------------
BASE_URL = os.getenv("MUSE_BASE_URL", "https://api.meta.ai/v1")
MODEL = os.getenv("MUSE_MODEL", "muse-spark-1.3-contributor")
MODEL_TIER = os.getenv("MUSE_MODEL_TIER", "contributor")
THINKING_BUDGET = os.getenv("MUSE_THINKING_BUDGET", "xhigh")
LLM_TIMEOUT = int(os.getenv("MUSE_LLM_TIMEOUT", "1800"))
MAX_TOKENS = int(os.getenv("MUSE_MAX_TOKENS", "32768"))

# Thinking-budget map. Verified live against the Model API `/responses`
# endpoint: the wire field is `reasoning: {effort: <name>}` with at least
# low/high/xhigh accepted (an unknown `thinking_budget` field gets HTTP 400).
# `off`/`dynamic` have no wire equivalent: off floors to low, dynamic omits
# the key (service default, observed "high").
EFFORTS = ("low", "medium", "high", "xhigh")


def thinking_budget_value(name: str | int | None = None) -> int:
    """Legacy numeric scale (kept for introspection only)."""
    scale = {"off": 0, "low": 2048, "medium": 8192, "high": 24576,
             "xhigh": 32768, "dynamic": -1}
    key = str(name if name is not None else THINKING_BUDGET).lower().strip()
    if key in scale:
        return scale[key]
    try:
        return int(key)
    except ValueError:
        return scale["xhigh"]


def reasoning_effort(name: str | int | None = None) -> str | None:
    """Map a thinking-budget name to a wire `reasoning.effort` value."""
    key = str(name if name is not None else THINKING_BUDGET).lower().strip()
    if key in EFFORTS:
        return key
    if key == "dynamic":
        return None  # omit: service default
    if key == "off":
        return "low"  # no wire equivalent; floor to minimum
    return "xhigh"


def get_api_key() -> str:
    key = os.getenv("MUSE_API_KEY", "").strip()
    if not key or key == "your_muse_api_key_here":
        raise SystemExit(
            "MUSE_API_KEY is not set (see .env.example). "
            "Live calls need a key; use --dry-run without one."
        )
    return key


# --- Mythology-scoped chapter reading ----------------------------------------
_ID_RE = re.compile(r"^(Book_\d+_.+?)_Chapter_(\d+)$")


def resolve_mythology_root(mythology: str) -> Path:
    """Resolve `--mythology` to a directory. Relative values resolve from the
    project root so runs work from anywhere."""
    root = Path(mythology)
    if not root.is_absolute():
        root = PROJECT_ROOT / mythology
    root = root.resolve()
    if not root.is_dir():
        raise SystemExit(f"mythology folder not found: {root}")
    for required in ("sources", "outputs", "entities", "mythology.yaml"):
        if not (root / required).exists():
            raise SystemExit(f"mythology folder {root} is missing {required}")
    return root


def assert_inside(myth_root: Path, path: Path) -> Path:
    """Isolation gate: every read/write must stay inside the mythology folder
    (shared tools code itself is the only exception — it is read-only)."""
    myth_root = myth_root.resolve()
    resolved = (myth_root / path if not path.is_absolute() else path).resolve()
    if resolved != myth_root and myth_root not in resolved.parents:
        raise SystemExit(f"isolation violation: {resolved} is outside {myth_root}")
    return resolved


def parse_chapter_id(chapter_id: str) -> tuple[str, int]:
    name = Path(str(chapter_id)).name
    if name.endswith(".md"):
        name = name[:-3]
    m = _ID_RE.match(name)
    if not m:
        raise SystemExit(
            f"bad chapter id: {chapter_id!r} (expected Book_N_..._Chapter_M)"
        )
    return m.group(1), int(m.group(2))


def list_chapters(myth_root: Path, book_prefix: str | None = None) -> list[dict]:
    """Ordered chapters across the mythology's narrative JSONs (frozen inputs)."""
    sources = assert_inside(myth_root, Path("sources"))
    out: list[dict] = []
    files = sorted(
        sources.glob("Book_*_narrative.json"),
        key=lambda p: int(re.match(r"Book_(\d+)_", p.name).group(1)),
    )
    for nj in files:
        prefix = nj.name.replace("_narrative.json", "")
        if book_prefix and prefix != book_prefix:
            continue
        data = json.loads(nj.read_text(encoding="utf-8"))
        for ch in sorted(data, key=lambda c: c["index"]):
            num = ch["index"] + 1
            out.append({
                "chapter_name": f"{prefix}_Chapter_{num}",
                "book_prefix": prefix,
                "num": num,
                "title": ch.get("title_clean") or ch.get("title", "Untitled"),
            })
    return out


def load_chapter_content(myth_root: Path, chapter_id: str) -> str:
    """Title header + clean narrative for one chapter (read-only)."""
    book_prefix, num = parse_chapter_id(chapter_id)
    nj = assert_inside(myth_root, Path("sources") / f"{book_prefix}_narrative.json")
    if not nj.exists():
        raise SystemExit(f"narrative json not found: {nj}")
    data = json.loads(nj.read_text(encoding="utf-8"))
    ch = next((c for c in data if c["index"] == num - 1), None)
    if ch is None:
        raise SystemExit(f"chapter index {num - 1} not found in {nj.name}")
    title = ch.get("title_clean") or ch.get("title", "Untitled")
    text = (ch.get("narrative") or "").strip()
    header = f"# {book_prefix.replace('_', ' ')} - Chapter {num}: {title}"
    return f"{header}\n\n{text}\n"


# --- Muse text call -----------------------------------------------------------
def call_muse(
    messages: list[dict],
    model: str = MODEL,
    temperature: float = 0.7,
    thinking: str | int | None = None,
    max_tokens: int = MAX_TOKENS,
    dry_run: bool = False,
) -> str | None:
    """POST a chat-style request to the Muse Model API (Responses-style).

    The exact request shape is adapter-local by design: if the live API
    differs, only this function changes — no stage code is touched.
    With dry_run=True no network call is made (returns a canned fixture).
    """
    if dry_run:
        last = messages[-1].get("content", "") if messages else ""
        return (
            "[dry-run fixture: model=%s thinking=%s]\n"
            "Canned response standing in for the Muse text call. "
            "Prompt tail: %s" % (model, thinking or THINKING_BUDGET, str(last)[:200])
        )
    api_key = get_api_key()
    url = BASE_URL.rstrip("/") + "/responses"
    payload: dict = {
        "model": model,
        "input": [
            {"role": m.get("role", "user"), "content": m.get("content", "")}
            for m in messages
        ],
        "temperature": temperature,
        "max_output_tokens": max_tokens,
    }
    effort = reasoning_effort(thinking)
    if effort is not None:
        payload["reasoning"] = {"effort": effort}
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )
    max_retries = int(os.getenv("MUSE_MAX_RETRIES", "3"))
    for attempt in range(1, max_retries + 1):
        t0 = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=LLM_TIMEOUT) as resp:
                result = json.loads(resp.read().decode("utf-8"))
            dt = time.monotonic() - t0
            print(f"[muse] {model} effort={effort} {dt:.0f}s "
                  f"({len(json.dumps(result))} chars wire)",
                  file=sys.stderr, flush=True)
        except urllib.error.HTTPError as e:
            # Retry transient server/rate errors; a 4xx (other than 429) is
            # a contract problem — fail fast so the log shows the real cause.
            body = ""
            try:
                body = e.read()[:300].decode("utf-8", "replace")
            except Exception:  # noqa: BLE001
                pass
            retryable = e.code == 429 or 500 <= e.code < 600
            print(f"[muse] {model} attempt {attempt}/{max_retries} "
                  f"HTTP {e.code} {body}", file=sys.stderr, flush=True)
            if not retryable or attempt >= max_retries:
                return None
            result = None
        except Exception as e:  # noqa: BLE001 — timeouts etc. are transient
            print(f"[muse] {model} attempt {attempt}/{max_retries} FAILED: {e}",
                  file=sys.stderr, flush=True)
            if attempt >= max_retries:
                return None
            result = None
        else:
            text = _message_text(model, result)
            if text:
                return text
            # A 200 with status=incomplete and no message text is the API
            # stalling, not an answer — back off and retry like any transient
            # failure instead of handing one empty reply to the stages.
            # (Live comic runs died on these at extraction, design, and flow.)
            print(f"[muse] {model} attempt {attempt}/{max_retries} "
                  f"no message part (status="
                  f"{result.get('status') if isinstance(result, dict) else '?'})",
                  file=sys.stderr, flush=True)
            if attempt >= max_retries:
                return None
            result = None
        if attempt < max_retries:
            time.sleep(min(300, 30 * attempt))
    return None


def _message_text(model: str, result) -> str | None:
    """Extract message text from a response envelope; None when empty.

    Verified shape: {"object": "response", "status": ..., "output": [
      {"type": "reasoning", ...}, {"type": "message",
       "content": [{"type": "output_text", "text": ...}]}, ...]}.
    Scan for message parts; stages validate semantics, not shape.
    """
    if isinstance(result, dict):
        for item in result.get("output", []) or []:
            if not isinstance(item, dict) or item.get("type") != "message":
                continue
            parts = []
            for part in item.get("content", []) or []:
                if isinstance(part, dict) and part.get("type") in (
                        "output_text", "text") and part.get("text"):
                    parts.append(part["text"])
            if parts:
                if result.get("status") not in (None, "completed"):
                    print(f"[muse] {model} status={result.get('status')} "
                          f"(partial text kept)", file=sys.stderr, flush=True)
                return "".join(parts)
    return None


# --- Self-test (no key needed) -----------------------------------------------
def smoke(mythology: str) -> int:
    """Dry self-test: chapter inventory + chapter load + isolation gate."""
    myth_root = resolve_mythology_root(mythology)
    chapters = list_chapters(myth_root)
    print(f"mythology : {myth_root}")
    print(f"chapters  : {len(chapters)}")
    if not chapters:
        print("SMOKE FAIL: no chapters found", file=sys.stderr)
        return 1
    first = chapters[0]["chapter_name"]
    content = load_chapter_content(myth_root, first)
    print(f"first     : {first} ({len(content)} chars)")
    if len(content) < 100:
        print("SMOKE FAIL: first chapter content too short", file=sys.stderr)
        return 1
    # Isolation gate: an absolute outside path must be rejected.
    try:
        assert_inside(myth_root, Path("/etc/hostname"))
    except SystemExit:
        print("isolation : OK (outside path rejected)")
    else:
        print("SMOKE FAIL: isolation gate did not reject", file=sys.stderr)
        return 1
    # Dry-run call path (no network, no key).
    probe = call_muse(
        [{"role": "user", "content": "smoke probe"}],
        dry_run=True,
    )
    if not probe or "dry-run fixture" not in probe:
        print("SMOKE FAIL: dry-run call path broken", file=sys.stderr)
        return 1
    print("dry-run   : OK (no network, no key)")
    print("SMOKE PASS")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="MythologyMuse Muse text adapter")
    ap.add_argument("--mythology", default="mythologies/ramayana_dutt")
    ap.add_argument("--chapter", default="")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--book", default="")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--prompt", default="Summarise this chapter in two sentences.")
    args = ap.parse_args(argv)

    if args.smoke:
        return smoke(args.mythology)

    myth_root = resolve_mythology_root(args.mythology)
    if args.list:
        for c in list_chapters(myth_root, book_prefix=args.book or None):
            print(f"{c['chapter_name']}\t{c['title']}")
        return 0

    if not args.chapter:
        print("nothing to do: give --chapter, --list, or --smoke", file=sys.stderr)
        return 2
    content = load_chapter_content(myth_root, args.chapter)
    print(content[:600] + ("..." if len(content) > 600 else ""))
    print(f"\n--- [{len(content)} chars loaded; live call needs MUSE_API_KEY] ---")
    if args.dry_run:
        out = call_muse(
            [
                {"role": "system", "content": "You are Kavya, a mythology scholar."},
                {"role": "user", "content": f"{args.prompt}\n\n{content[:2000]}"},
            ],
            dry_run=True,
        )
        print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
