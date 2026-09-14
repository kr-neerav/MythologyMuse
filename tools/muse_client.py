#!/usr/bin/env python3
"""MythologyMuse — Meta Muse text adapter (Phase 1).

Stateless client for the Muse text model plus mythology-scoped chapter
reading. Shared read-only tooling: it never writes outside the mythology
folder it is pointed at (`--mythology`), and in dry-run mode it performs no
network calls at all (canned fixtures, no key needed).

Config (env, see ../../.env.example):
    MUSE_API_KEY            required for live calls only
    MUSE_BASE_URL           default https://api.meta.ai/v1
    MUSE_MODEL              default muse-spark-1.3
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
MODEL = os.getenv("MUSE_MODEL", "muse-spark-1.3")
MODEL_TIER = os.getenv("MUSE_MODEL_TIER", "contributor")
THINKING_BUDGET = os.getenv("MUSE_THINKING_BUDGET", "xhigh")
LLM_TIMEOUT = int(os.getenv("MUSE_LLM_TIMEOUT", "1800"))
MAX_TOKENS = int(os.getenv("MUSE_MAX_TOKENS", "32768"))

# Thinking-budget map. `xhigh` sits above the legacy `high` level; the exact
# numeric scale is adapter-local and tunable without touching callers.
THINKING_BUDGETS = {
    "off": 0,
    "low": 2048,
    "medium": 8192,
    "high": 24576,
    "xhigh": 32768,
    "dynamic": -1,
}


def thinking_budget_value(name: str | int | None = None) -> int:
    if isinstance(name, int):
        return name
    key = str(name or THINKING_BUDGET).lower().strip()
    if key in THINKING_BUDGETS:
        return THINKING_BUDGETS[key]
    try:
        return int(key)
    except ValueError:
        return THINKING_BUDGETS["xhigh"]


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
    payload = {
        "model": model,
        "input": [
            {"role": m.get("role", "user"), "content": m.get("content", "")}
            for m in messages
        ],
        "temperature": temperature,
        "max_output_tokens": max_tokens,
        "thinking_budget": thinking_budget_value(thinking),
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=LLM_TIMEOUT) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    except Exception as e:  # noqa: BLE001 — caller decides retry policy
        print(f"[muse] {model} FAILED: {e}", file=sys.stderr, flush=True)
        return None
    # Tolerate response-shape variants; stages validate semantics, not shape.
    if isinstance(result, dict):
        for key in ("output_text", "text", "content"):
            if isinstance(result.get(key), str) and result[key].strip():
                return result[key]
        try:
            return result["output"][0]["content"][0]["text"]
        except (KeyError, IndexError, TypeError):
            pass
    return json.dumps(result)[:4000]


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
