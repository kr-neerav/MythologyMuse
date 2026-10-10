#!/usr/bin/env python3
"""MythologyMuse — standalone Gemini TTS audio generator (NOT part of run_chapter).

Reads a chapter's `script_<chapter>.json` (list of {text (Hindi), text_en
(English)} segments) and synthesizes one WAV per segment per language, for
later video assembly. Trigger it explicitly; nothing in the text pipeline
calls this module.

Model (cost-efficient default):
    gemini-3.8-flash-lite-tts — Google's documented fast, cost-efficient
    single-speaker workhorse ("everyday single-speaker speech across major
    languages", incl. Hindi + English). Override with GEMINI_TTS_MODEL
    (e.g. gemini-3.8-flash-tts for max fidelity at ~1.5x audio price).

API: POST {GEMINI_BASE_URL}/interactions (REST, stdlib urllib only —
no new dependencies), key via GEMINI_API_KEY.

Gate: refuses (rc=2, no network, no writes) when any transcript still
carries a spoken structural label (प्रश्न:/Question: etc. — the same
literals podcast_stage bans): TTS reads every word, so synthesizing that
text would bake the distraction into the audio. Fix the script first.

Outputs (under <mythology>/outputs/<chapter>/):
    audio_en/chunk_001.wav ...   one WAV per script segment (English)
    audio_hi/chunk_001.wav ...   one WAV per script segment (Hindi)
    audio_manifest_<chapter>.json  chunk -> file map + durations + run config

Usage:
    python3 tools/generate_audio_gemini.py --chapter Book_1_Bala_Kanda_Chapter_1 --dry-run
    python3 tools/generate_audio_gemini.py --chapter Book_1_Bala_Kanda_Chapter_1 --lang en
    python3 tools/generate_audio_gemini.py --chapter Book_1_Bala_Kanda_Chapter_1 --lang both

Exit codes (match the stage contract):
    0  success (every requested chunk has a WAV)
    1  partial (best-effort files written, some chunks failed)
    2  bad invocation
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from muse_client import (  # noqa: E402
    assert_inside,
    resolve_mythology_root,
)
# Canonical spoken-label ban (same literals the podcast validator rejects).
from podcast_stage import (  # noqa: E402
    _FORBIDDEN_EN_LABELS,
    _FORBIDDEN_HI_LABELS,
)

# Cost-efficient default; override via GEMINI_TTS_MODEL.
DEFAULT_MODEL = os.getenv("GEMINI_TTS_MODEL", "gemini-3.8-flash-lite-tts")
BASE_URL = os.getenv("GEMINI_BASE_URL",
                     "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
DEFAULT_VOICE = os.getenv("GEMINI_TTS_VOICE", "Leda")
DEFAULT_STYLE = os.getenv(
    "GEMINI_TTS_STYLE", "calm, steady mythological storytelling narration")
TIMEOUT_S = int(os.getenv("GEMINI_TTS_TIMEOUT", "300"))
MAX_RETRIES = 3
# Tier 1 pacing/budget. Confirmed Tier 1 quota for gemini-3.8-flash-lite-tts
# (AI Studio rate-limit page): 10 RPM / 10k TPM / 100 RPD, per model.
# One 25-chunk chapter at --lang both = 50 requests, i.e. half the daily
# quota. Default pacing keeps >=7s between calls -> at most ~8.5 RPM even if
# synthesis returned instantly (10 RPM allows one call per 6s; the extra
# second is margin for rolling-window accounting). TPM needs no pacing: each
# input is a few hundred tokens, far below 10k/min at this request rate.
DEFAULT_DELAY_S = float(os.getenv("GEMINI_TTS_DELAY_S", "7.0"))
DEFAULT_DAILY_BUDGET = int(os.getenv("GEMINI_TTS_DAILY_BUDGET", "100"))

# 3.8 TTS treats input as a VERBATIM transcript, so pipeline emotion tags
# (<narrative>, <formal>, ...) must be stripped or they get spoken aloud.
_TAG_RE = re.compile(r"\s*<[A-Za-z][A-Za-z0-9_+-]*>\s*")


def clean_transcript(text: str) -> str:
    """Strip emotion/stage tags and normalize whitespace for verbatim TTS."""
    cleaned = _TAG_RE.sub(" ", text or "")
    return re.sub(r"\s+", " ", cleaned).strip()


def find_spoken_labels(segments: list) -> list[str]:
    """Chunks whose transcript would speak a structural label aloud.

    Same literals podcast_stage bans from reflections: labels are content
    to the TTS voice, so generating audio for them bakes in the
    distraction. Returns human-readable hits (empty = clear).
    """
    hits: list[str] = []
    for i, seg in enumerate(segments, 1):
        if not isinstance(seg, dict):
            continue
        for lang, key, labs in (("hi", "text", _FORBIDDEN_HI_LABELS),
                                ("en", "text_en", _FORBIDDEN_EN_LABELS)):
            heard = clean_transcript(str(seg.get(key, "")))
            for lab in labs:
                if lab in heard:
                    hits.append(
                        f"chunk {i} [{lang}]: spoken label {lab!r} "
                        f"in transcript (fix the script first)")
                    break
    return hits


def load_dotenv() -> None:
    """Load project-root .env so GEMINI_API_KEY need not be exported."""
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip())


def synth_request_body(model: str, voice: str, style: str,
                       transcript: str) -> dict:
    return {
        "model": model,
        "input": [{
            "type": "user_input",
            "content": [{
                "type": "text",
                "text": transcript,
                "annotations": [{
                    "type": "speech_metadata",
                    "style": style,
                }],
            }],
        }],
        "response_format": {"type": "audio"},
        "generation_config": {"speech_config": [{"voice": voice}]},
    }


def extract_audio(payload: dict) -> bytes:
    """Pull the last audio block (base64 .data) out of an interactions reply."""
    found: bytes | None = None
    for step in payload.get("steps", []) or []:
        for item in step.get("content", []) or []:
            if isinstance(item, dict) and item.get("type") == "audio" \
                    and item.get("data"):
                found = base64.b64decode(item["data"])
    if found is None:
        raise ValueError(f"no audio block in response: {str(payload)[:300]}")
    return found


def ensure_wav(raw: bytes) -> bytes:
    """Interactions returns WAV by default; wrap bare PCM (24kHz/16-bit/mono)."""
    if raw[:4] == b"RIFF":
        return raw
    import io
    import struct
    buf = io.BytesIO()
    n = len(raw) // 2
    buf.write(b"RIFF" + struct.pack("<I", 36 + len(raw)) + b"WAVEfmt "
              + struct.pack("<IHHIIHH", 16, 1, 1, 24000, 48000, 2, 16)
              + b"data" + struct.pack("<I", len(raw)) + raw)
    _ = n
    return buf.getvalue()


def wav_duration_s(path: Path) -> float:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / float(w.getframerate() or 24000)


def pace(seconds: float) -> None:
    """Inter-request delay (own function so tests can observe it)."""
    time.sleep(seconds)


def retry_after_s(exc: Exception, default: float) -> float:
    """Honor the server's Retry-After header on 429s (capped at 120s)."""
    headers = getattr(exc, "headers", None) or {}
    try:
        return min(120.0, max(0.0, float(headers.get("Retry-After", default))))
    except (TypeError, ValueError):
        return default


def synthesize(api_key: str, model: str, voice: str, style: str,
               transcript: str) -> bytes:
    """One transcript -> WAV bytes, with retries on 429/5xx."""
    body = json.dumps(
        synth_request_body(model, voice, style, transcript)).encode("utf-8")
    last_err: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        req = urllib.request.Request(
            f"{BASE_URL}/interactions", data=body,
            headers={"Content-Type": "application/json",
                     "x-goog-api-key": api_key})
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
                return ensure_wav(extract_audio(json.loads(resp.read())))
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code not in (429, 500, 502, 503, 504) \
                    or attempt == MAX_RETRIES:
                raise
            pace(retry_after_s(e, 2 ** attempt) if e.code == 429
                 else 2 ** attempt)
        except (urllib.error.URLError, TimeoutError, ValueError) as e:
            last_err = e
            if attempt == MAX_RETRIES:
                raise
            pace(2 ** attempt)
    raise RuntimeError(f"TTS failed after retries: {last_err}")


def silent_wav(seconds: float = 1.0) -> bytes:
    """Minimal valid WAV for --dry-run placeholders (no key, no network)."""
    import io
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(b"\x00" * int(24000 * seconds) * 2)
    return buf.getvalue()


def generate(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--mythology", default="mythologies/ramayana_dutt")
    ap.add_argument("--chapter", default="")
    ap.add_argument("--lang", choices=("en", "hi", "both"), default="both",
                    help="English uses text_en, Hindi uses text, per chunk")
    ap.add_argument("--voice", default=DEFAULT_VOICE,
                    help="prebuilt voice (same voice both langs keeps "
                         "the video narrator consistent)")
    ap.add_argument("--style", default=DEFAULT_STYLE,
                    help="speech_metadata style annotation")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--redo", action="store_true",
                    help="re-synthesize even if the WAV already exists")
    ap.add_argument("--delay-s", type=float, default=DEFAULT_DELAY_S,
                    help="seconds between live synthesis calls (Tier 1 pacing)")
    ap.add_argument("--daily-budget", type=int, default=DEFAULT_DAILY_BUDGET,
                    help="max NEW live syntheses per run; aborts above it "
                         "(Tier 1 is 100 RPD per TTS model)")
    ap.add_argument("--ignore-budget", action="store_true",
                    help="run even if planned syntheses exceed --daily-budget")
    ap.add_argument("--dry-run", action="store_true",
                    help="no key, no network: silent WAVs + manifest only")
    args = ap.parse_args(argv)

    if not args.chapter:
        print("nothing to do: give --chapter", file=sys.stderr)
        return 2
    langs = ("en", "hi") if args.lang == "both" else (args.lang,)

    myth_root = resolve_mythology_root(args.mythology)
    ch_dir = assert_inside(myth_root, Path("outputs") / args.chapter)
    script_path = assert_inside(
        myth_root, Path("outputs") / args.chapter / f"script_{args.chapter}.json")
    if not script_path.exists():
        print(f"no script file: {script_path} (run podcast stage first)",
              file=sys.stderr)
        return 2
    segments = json.loads(script_path.read_text(encoding="utf-8"))
    if not isinstance(segments, list) or not segments:
        print(f"script file is empty or not a list: {script_path}",
              file=sys.stderr)
        return 2
    label_hits = find_spoken_labels(segments)
    if label_hits:
        print("refusing: spoken labels in script "
              "(TTS would read them aloud):", file=sys.stderr)
        for hit in label_hits:
            print(f"  {hit}", file=sys.stderr)
        print("remove the labels from the text, then re-run", file=sys.stderr)
        return 2

    load_dotenv()
    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key and not args.dry_run:
        print("missing GEMINI_API_KEY: add it to .env (never commit .env) "
              "or export it; --dry-run needs no key", file=sys.stderr)
        return 2

    manifest_path = assert_inside(
        myth_root, Path("outputs") / args.chapter
        / f"audio_manifest_{args.chapter}.json")
    prev: dict = {}
    if manifest_path.exists():
        try:
            prev = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            prev = {}
    # Resume (skip re-synthesis) only for chunks a previous LIVE run made
    # with the same model+voice: dry-run placeholders must always be
    # replaced, never mistaken for real audio.
    prev_live = (prev.get("dry_run") is False
                 and prev.get("model") == args.model
                 and prev.get("voice") == args.voice
                 and set(prev.get("langs", [])) >= set(langs))
    prev_slot = {(c.get("index"), lang): c.get(lang, {})
                 for c in prev.get("chunks", []) if isinstance(c, dict)
                 for lang in langs}

    out_dirs = {lang: assert_inside(
        myth_root, Path("outputs") / args.chapter / f"audio_{lang}")
        for lang in langs}
    for out_dir in out_dirs.values():
        out_dir.mkdir(parents=True, exist_ok=True)

    def reusable(i: int, lang: str, wav_path: Path) -> bool:
        if not wav_path.exists():
            return False
        if args.dry_run:
            return True  # measure only, never clobber real audio
        return (not args.redo and prev_live
                and prev_slot.get((i, lang), {}).get("status") == "ok")

    # Plan pass (no writes, no network): which slots need a live call?
    width = max(3, len(str(len(segments))))
    needs_call = sum(
        1 for i, seg in enumerate(segments, 1) for lang in langs
        if clean_transcript(str(seg.get("text_en" if lang == "en"
                                        else "text", "")))
        and not reusable(i, lang, out_dirs[lang]
                         / f"chunk_{i:0{width}d}.wav"))
    if not args.dry_run:
        print(f"audio_{args.lang}: plan {needs_call} new syntheses "
              f"(pacing {args.delay_s}s, daily budget {args.daily_budget})")
        if needs_call > args.daily_budget and not args.ignore_budget:
            print(f"refusing: {needs_call} planned syntheses exceed daily "
                  f"budget {args.daily_budget} (Tier 1 is 100 RPD per "
                  f"TTS model) — re-run with --ignore-budget, a smaller "
                  f"--lang, or after midnight Pacific",
                  file=sys.stderr)
            return 2

    manifest: dict = {"chapter": args.chapter, "model": args.model,
                      "voice": args.voice, "style": args.style,
                      "langs": list(langs), "dry_run": args.dry_run,
                      "delay_s": args.delay_s,
                      "daily_budget": args.daily_budget,
                      "chunks": []}
    failures = 0
    calls_made = 0
    for i, seg in enumerate(segments, 1):
        entry: dict = {"index": i}
        for lang in langs:
            key = "text_en" if lang == "en" else "text"
            transcript = clean_transcript(str(seg.get(key, "")))
            wav_path = out_dirs[lang] / f"chunk_{i:0{width}d}.wav"
            slot = {"chars": len(transcript),
                    "file": wav_path.relative_to(ch_dir).as_posix()}
            entry[lang] = slot
            if not transcript:
                slot.update(status="skipped-empty", duration_s=0.0)
                continue
            try:
                if reusable(i, lang, wav_path):
                    # Kept as-is (live resume, or dry-run measuring without
                    # clobbering); manifest top-level dry_run flag records
                    # this run's provenance.
                    source = "reused"
                else:
                    if args.dry_run:
                        wav_path.write_bytes(silent_wav())
                        source = "dry-run"
                    else:
                        if calls_made:
                            pace(args.delay_s)
                        wav_path.write_bytes(synthesize(
                            api_key, args.model, args.voice, args.style,
                            transcript))
                        calls_made += 1
                        source = "synthesized"
                slot.update(status="ok", source=source,
                            bytes=wav_path.stat().st_size,
                            duration_s=round(wav_duration_s(wav_path), 2))
            except Exception as e:  # best-effort per chunk; keep going
                failures += 1
                slot.update(status=f"error: {e}")
                print(f"chunk {i} [{lang}] failed: {e}", file=sys.stderr)
        manifest["chunks"].append(entry)

    manifest_path.write_text(json.dumps(manifest, indent=1,
                                        ensure_ascii=False), encoding="utf-8")
    total = len(segments) * len(langs)
    ok = sum(1 for c in manifest["chunks"] for lang in langs
             if c[lang].get("status") == "ok")
    print(f"audio_{args.lang}: {ok}/{total} chunks ok -> "
          f"{manifest_path.relative_to(myth_root)}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(generate())
