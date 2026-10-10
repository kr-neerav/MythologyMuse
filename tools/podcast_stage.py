#!/usr/bin/env python3
"""MythologyMuse — podcast stage driver (Phase 2).

Runs one chapter through Agents 1→2 (narration + QA) then 3→4 (flowing
reflection + QA), writing the same text artifacts the legacy pipeline
produced. All reads/writes stay inside the mythology folder (isolation gate
in muse_client).

Outputs (under <mythology>/outputs/<chapter_id>/):
    narration_<chapter>.json     Agent 1 segments
    narration_qa_<chapter>.md    Agent 2 review
    discussion_<chapter>.json    Agent 3 segments
    discussion_qa_<chapter>.md   Agent 4 review
    script_<chapter>.json        narration + discussion combined

Exit codes (match the legacy stage contract):
    0  success (both QAs APPROVED within budget)
    1  did not reach APPROVED within budget (best-effort files still written)
    2  bad invocation

Dry-run mode (--dry-run) uses schema-valid fixtures: no key, no network.
--dry-run-reject-first forces the first QA of each phase to REJECT once, so
the retry loop itself is exercised without a model.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from muse_client import (  # noqa: E402
    MODEL,
    assert_inside,
    call_muse,
    load_chapter_content,
    resolve_mythology_root,
)

EMOTION_TAGS = (
    "neutral",
    "narrative",
    "formal",
    "enthusiastic",
    "happy",
    "sad",
    "clear",
)
_EMOTION_RE = re.compile(r"<(%s)>\s*$" % "|".join(EMOTION_TAGS))

# Spoken-label ban: TTS reads every word of text/text_en aloud, so these
# structural literals must NEVER appear in reflection passages. Kept as
# tuples (not a set) for stable error messages; _HI_LABELS doubles as the
# legacy detector for pre-change artifacts (see av_map_stage.is_discussion).
_FORBIDDEN_HI_LABELS = ("प्रश्न:", "विवेचना:", "जीवन-सूत्र:")
_FORBIDDEN_EN_LABELS = ("Question:", "Reflection:", "Takeaway:")
_HI_LABELS = _FORBIDDEN_HI_LABELS
_EN_LABELS = _FORBIDDEN_EN_LABELS


def load_prompt(prompts_dir: Path, name: str) -> str:
    """Read a prompt file, stripping the `# header ... ---` metadata block."""
    text = (prompts_dir / name).read_text(encoding="utf-8")
    if "\n---\n" in text:
        text = text.split("\n---\n", 1)[1]
    return text.strip() + "\n"


def extract_json_array(raw: str | None) -> list | None:
    if not raw:
        return None
    text = raw.strip()
    m = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if m:
        text = m.group(1).strip()
    i, j = text.find("["), text.rfind("]")
    if i == -1 or j == -1 or j <= i:
        return None
    blob = re.sub(r",\s*([\]}])", r"\1", text[i:j + 1])
    try:
        data = json.loads(blob)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, list) else None


def validate_segments(segs: list | None, kind: str) -> list[str]:
    """Return a list of problems (empty = valid). kind: narration|reflection."""
    problems: list[str] = []
    if not segs:
        problems.append("no JSON array found in model output")
        return problems
    for n, s in enumerate(segs):
        where = f"segment {n}"
        if not isinstance(s, dict):
            problems.append(f"{where}: not an object")
            continue
        for key in ("character", "voice", "text", "text_en"):
            if not isinstance(s.get(key), str) or not s[key].strip():
                problems.append(f"{where}: missing/empty `{key}`")
        if s.get("character") != "Kavya":
            problems.append(f"{where}: character must be Kavya")
        if s.get("voice") != "Hindi (Female)":
            problems.append(f"{where}: voice must be 'Hindi (Female)'")
        for key in ("text", "text_en"):
            m = _EMOTION_RE.search(s.get(key) or "")
            if not m:
                problems.append(f"{where}: `{key}` lacks a trailing emotion tag")
                continue
            other = "text_en" if key == "text" else "text"
            m2 = _EMOTION_RE.search(s.get(other) or "")
            if m2 and m.group(1) != m2.group(1):
                problems.append(f"{where}: emotion tag mismatch hindi/en")
        if kind == "reflection" and not problems:
            for lab in _FORBIDDEN_HI_LABELS:
                if lab in (s["text"] or ""):
                    problems.append(
                        f"{where}: hindi text must NOT contain spoken label {lab!r} "
                        f"(TTS reads it aloud — keep the question-to-takeaway flow natural)"
                    )
                    break
            for lab in _FORBIDDEN_EN_LABELS:
                if lab in (s["text_en"] or ""):
                    problems.append(
                        f"{where}: text_en must NOT contain spoken label {lab!r} "
                        f"(TTS reads it aloud — keep the question-to-takeaway flow natural)"
                    )
                    break
            if "?" not in (s["text"] or ""):
                problems.append(
                    f"{where}: hindi text must open with a spoken question (no `?` found)"
                )
            if "?" not in (s["text_en"] or ""):
                problems.append(
                    f"{where}: text_en must open with a spoken question (no `?` found)"
                )
    return problems


def parse_verdict(review: str | None) -> str:
    if not review:
        return "REJECTED"
    lines = [ln.strip() for ln in review.strip().splitlines() if ln.strip()]
    if lines and lines[-1] in ("APPROVED", "REJECTED"):
        return lines[-1]
    return "REJECTED"


# --- Dry-run fixtures (schema-valid, no network) ------------------------------
def _fixture_narration() -> list[dict]:
    return [
        {
            "character": "Kavya",
            "voice": "Hindi (Female)",
            "text": "नमस्ते दोस्तों, आज हम बालकांड की पहली कथा सुनेंगे, जहाँ महर्षि वाल्मीकि नारद से राम के गुण पूछते हैं। <enthusiastic>",
            "text_en": "Hello friends, today we hear the first tale of the Balakanda, where Sage Valmiki asks Narada about Rama's virtues. <enthusiastic>",
        },
        {
            "character": "Kavya",
            "voice": "Hindi (Female)",
            "text": "नारद उत्तर देते हैं कि राम धर्म, करुणा और धैर्य के सागर हैं, और उन्हीं की कथा यह रामायण है। <narrative>",
            "text_en": "Narada answers that Rama is an ocean of duty, compassion, and patience — and this Ramayana is his story. <narrative>",
        },
    ]


def _fixture_reflection() -> list[dict]:
    return [
        {
            "character": "Kavya",
            "voice": "Hindi (Female)",
            "text": "वाल्मीकि ने कथा सुनने से पहले राम के गुण क्यों पूछे? क्योंकि वे जानते थे कि चरित्र ही कथा की आत्मा है — घटना भूल जाती है, गुण रह जाते हैं। किसी की कहानी सुनने से पहले उसका एक गुण पहचानें; आप कथा को गहराई से सुनेंगे। <formal>",
            "text_en": "Why did Valmiki ask about Rama's virtues before hearing the tale? Because he knew character is the soul of a story — events fade, virtues remain. Before hearing someone's story, name one of their virtues; you will listen more deeply. <formal>",
        },
    ]


def _fixture_qa(role: str, reject: bool) -> str:
    if reject:
        return (
            f"- Strengths: {role} draft covers the core beats.\n"
            "- Weaknesses: Pacing rushes the opening; one transition skipped.\n"
            "REJECTED"
        )
    return (
        f"- Strengths: {role} is complete, well-paced, and faithful.\n"
        "- Weaknesses: None material.\n"
        "APPROVED"
    )


# --- Phase runner --------------------------------------------------------------
# Per-stage token ceilings (xhigh effort everywhere; the ceiling bounds
# output+reasoning so a mechanical call cannot burn an hour-long trace).
GEN_TOKENS = 32768
QA_TOKENS = 8192

# Thinking split: creators run at the env default (xhigh, confirmed);
# reviewing a draft against a checklist is cheaper — QA runs at high.
GEN_THINKING = None
QA_THINKING = "high"

# Advisory word budgets (mirror the prompt guidance; the audit reports,
# QA judges — nothing truncates).
NARR_WORD_BUDGET = 90
REFL_WORD_BUDGET = 180


def run_phase(
    kind: str,
    gen_prompt: str,
    qa_prompt: str,
    user_context: str,
    max_qa_loops: int,
    dry_run: bool,
    reject_first: bool,
    gen_tokens: int = GEN_TOKENS,
    qa_tokens: int = QA_TOKENS,
    gen_thinking=None,
    qa_thinking: str = QA_THINKING,
) -> tuple[list[dict] | None, str, bool]:
    """Run one generate→QA loop. Returns (segments, qa_review, approved)."""
    phase = ("PHASE: NARRATION — apply Rubric A only.\n\n"
             if kind == "narration" else
             "PHASE: REFLECTION — apply Rubric B only.\n\n")
    critique = ""
    qa_review = ""
    attempt = 0
    while True:
        if dry_run:
            segs = _fixture_narration() if kind == "narration" else _fixture_reflection()
        else:
            raw = call_muse([
                {"role": "system", "content": gen_prompt},
                {"role": "user", "content": user_context + critique},
            ], max_tokens=gen_tokens, thinking=gen_thinking)
            segs = extract_json_array(raw)
        problems = validate_segments(segs, kind)
        if problems and attempt >= max_qa_loops:
            qa_review = "VALIDATION FAILED (no QA call):\n- " + "\n- ".join(problems)
            return segs, qa_review, False
        if problems:
            critique = "\n\nREVIEWER FEEDBACK (fix every point, keep the schema):\n- " + "\n- ".join(problems)
            attempt += 1
            continue
        if dry_run:
            qa_review = _fixture_qa(kind, reject_first and attempt == 0)
        else:
            qa_review = call_muse([
                {"role": "system", "content": qa_prompt},
                {"role": "user", "content": phase + user_context + "\n\nCANDIDATE:\n" + json.dumps(segs, ensure_ascii=False)},
            ], max_tokens=qa_tokens, thinking=qa_thinking) or ""
        if parse_verdict(qa_review) == "APPROVED":
            return segs, qa_review, True
        attempt += 1
        if attempt > max_qa_loops:
            return segs, qa_review, False
        critique = f"\n\nREVIEWER FEEDBACK (address it fully, keep the schema):\n{qa_review}"


def count_words(text: str) -> int:
    return len((text or "").split())


def audit_segments(segs: list | None, budget: int, label: str) -> None:
    """Advisory length audit: averages + outlier flags. Reports only."""
    if not segs:
        print(f"audit-{label}: no segments")
        return
    counts = [count_words(s.get("text", "")) for s in segs]
    avg = sum(counts) / len(counts)
    outliers = [n for n, c in enumerate(counts) if c > 2 * budget]
    print(f"audit-{label}: avg {avg:.0f}w/seg over {len(counts)} segs "
          f"(budget ~{budget}); outliers(>{2 * budget}w): "
          + (", ".join(f"#{n}" for n in outliers) or "none"))


def build_prev_recap(myth_root: Path, chapter_id: str, max_chars: int = 500) -> str:
    """Rolling continuity brief from the previous chapter's approved narration.

    Deterministic and free: first two narration segments of chapter N-1,
    emotion tags stripped, truncated. Empty when there is no previous chapter
    or its outputs do not exist yet (first-chapter behavior).
    """
    from muse_client import parse_chapter_id as _pci
    try:
        book_prefix, num = _pci(chapter_id)
    except SystemExit:
        return ""
    if num <= 1:
        return ""
    prev = f"{book_prefix}_Chapter_{num - 1}"
    narr_path = myth_root / "outputs" / prev / f"narration_{prev}.json"
    if not narr_path.exists():
        return ""
    try:
        segs = json.loads(narr_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return ""
    bits = []
    for s in segs[:2]:
        t = re.sub(r"\s+", " ", re.sub(r"<[^>\n]{1,40}>", " ", s.get("text", ""))).strip()
        if t:
            bits.append(t)
    brief = " ".join(bits)[:max_chars]
    return f"{prev}: {brief}" if brief else ""


def run_chapter(
    myth_root: Path,
    prompts_dir: Path,
    chapter_id: str,
    max_qa_loops: int = 2,
    dry_run: bool = False,
    reject_first: bool = False,
    prev_recap: str = "",
    auto_recap: bool = True,
) -> int:
    chapter = chapter_id  # canonical dir/file stem
    content = load_chapter_content(myth_root, chapter)
    out_dir = assert_inside(myth_root, Path("outputs") / chapter)
    out_dir.mkdir(parents=True, exist_ok=True)

    agent1 = load_prompt(prompts_dir, "agent1_narration.md")
    reviewer = load_prompt(prompts_dir, "reviewer.md")
    agent3 = load_prompt(prompts_dir, "agent3_reflection.md")

    if not prev_recap and auto_recap:
        prev_recap = build_prev_recap(myth_root, chapter)
    if prev_recap:
        print(f"recap: {len(prev_recap)} chars carried from previous chapter")
    else:
        print("recap: none (first chapter or previous outputs missing)")
    recap = f"PREVIOUS CHAPTER recap:\n{prev_recap}\n\n" if prev_recap else ""
    narration_ctx = f"{recap}MYTHOLOGY CHAPTER (source of truth — narrate ONLY this):\n{content}"

    narration, qa1, ok1 = run_phase(
        "narration", agent1, reviewer, narration_ctx,
        max_qa_loops, dry_run, reject_first,
    )
    (out_dir / f"narration_{chapter}.json").write_text(
        json.dumps(narration, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out_dir / f"narration_qa_{chapter}.md").write_text(qa1 + "\n", encoding="utf-8")

    discussion_ctx = (
        "ORIGINAL CHAPTER (for grounding):\n" + content
        + "\n\nNARRATION SCRIPT (reflect on THIS story):\n"
        + json.dumps(narration, ensure_ascii=False)
    )
    discussion, qa2, ok2 = run_phase(
        "reflection", agent3, reviewer, discussion_ctx,
        max_qa_loops, dry_run, reject_first,
    )
    (out_dir / f"discussion_{chapter}.json").write_text(
        json.dumps(discussion, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out_dir / f"discussion_qa_{chapter}.md").write_text(qa2 + "\n", encoding="utf-8")

    script = (narration or []) + (discussion or [])
    (out_dir / f"script_{chapter}.json").write_text(
        json.dumps(script, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"chapter : {chapter}")
    print(f"outputs : {out_dir}")
    print(f"narration: {len(narration or [])} segs QA={parse_verdict(qa1)}")
    audit_segments(narration, NARR_WORD_BUDGET, "narration")
    print(f"discussion: {len(discussion or [])} segs QA={parse_verdict(qa2)}")
    audit_segments(discussion, REFL_WORD_BUDGET, "discussion")
    print(f"script  : {len(script)} segs total")
    if ok1 and ok2:
        print("PODCAST STAGE PASS")
        return 0
    print("PODCAST STAGE did not reach APPROVED within budget", file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="MythologyMuse podcast stage")
    ap.add_argument("--mythology", default="mythologies/ramayana_dutt")
    ap.add_argument("--chapter", default="")
    ap.add_argument("--prompts-dir", default="")
    ap.add_argument("--max-qa-loops", type=int, default=2)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--dry-run-reject-first", action="store_true")
    ap.add_argument("--prev-recap", default="")
    ap.add_argument("--no-auto-recap", action="store_true")
    args = ap.parse_args(argv)

    if not args.chapter:
        print("nothing to do: give --chapter", file=sys.stderr)
        return 2
    from muse_client import parse_chapter_id as _pci
    try:
        myth_root = resolve_mythology_root(args.mythology)
        _pci(args.chapter)  # chapter-id sanity (also guards output naming)
    except SystemExit as e:
        # resolve/parse signal bad invocation: normalize to the stage
        # contract rc=2 (they exit 1 on their own).
        print(e.code, file=sys.stderr)
        return 2
    default_prompts = Path(__file__).resolve().parent.parent / "prompts"
    prompts_dir = Path(args.prompts_dir) if args.prompts_dir else default_prompts
    if not prompts_dir.is_dir():
        print(f"prompts dir not found: {prompts_dir}", file=sys.stderr)
        return 2
    return run_chapter(
        myth_root, prompts_dir, args.chapter,
        max_qa_loops=args.max_qa_loops,
        dry_run=args.dry_run,
        reject_first=args.dry_run_reject_first,
        prev_recap=args.prev_recap,
        auto_recap=not args.no_auto_recap,
    )


if __name__ == "__main__":
    raise SystemExit(main())
