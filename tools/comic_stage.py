#!/usr/bin/env python3
"""MythologyMuse — comic text stages (Phase 4).

Turns ONE chapter's `english_narration_<chapter>.txt` (bridge output) into a
comic storyboard, Muse-native panel-prompt texts, and a Hindi storyboard —
text only, no image rendering (Flow/ingredient output was removed; the
`muse_prompt` texts are the render inputs). Per-mythology entity repository
grows chapter by chapter (fresh LLM interpretation; never seeded).

Stages (E/P/S/F/V/H), mirroring the legacy comic orchestrator:
    E  extract   entity_extractor.md        EN narration -> characters + scenes
       dedup     (deterministic, no model)  drop entities already in the repo
    P  design    entity_designer.md         NEW entities in batches ->
                                             image_prompt + muse_prompt ->
                                             appended to this mythology's
                                             entity_repository.json
    S  storyboard storyboard.md             EN narration -> ordered slides
       layerA    (deterministic, ported)    storyboard shape gate; retry on FAIL
    F  panels    panel_prompts.md           slides in batches -> muse_prompt
                                             per slide (no Flow output)
    V  eval      storyboard_eval.md         coverage/fidelity/ingredient judge
    H  hindi     hindi_storyboard.md        full storyboard -> Hindi text fields

A per-run call budget (default 100, `--max-calls`) stops spirals with
best-effort files and rc=1 instead of burning calls without bound.

Outputs (under <mythology>/outputs/<chapter_id>/):
    comic_entities_<chapter>.json        extraction result (E)
    comic_entities_preview_<chapter>.json (dry-run only: what P would append)
    comic_storyboard_<chapter>.json     ordered slides (S)
    comic_muse_prompts_<chapter>.json   per-slide Muse-native prompt texts (F)
    comic_render_plan_<chapter>.json    roster + per-slide render turns (F)
    comic_storyboard_hindi_<chapter>.json (H)
    comic_eval_<chapter>.json           verdict + storyboard Layer A (V)

Repo (read-modify-write, sequential runs assumed):
    <mythology>/entities/entity_repository.json
    Dry-run NEVER mutates the repo (writes the preview file instead).

Exit: 0 = eval PASS (or already-PASS skip), 1 = did not PASS within budget,
      2 = bad invocation / missing input.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from muse_client import (  # noqa: E402
    MODEL,
    assert_inside,
    call_muse,
    resolve_mythology_root,
)

# --- Layer A ports ------------------------------------------------------------
# Ported from mythology-texts
# `mythology podcast/comic_generation/comic_pipeline_checks.py`
# (deterministic gates; no model). Constants reconstructed to match the
# documented contract: `SlideNN - <title>` labels, scene|insight types,
# caption|dialogue modes, @flow_ref ingredient usage both directions.
_LABEL_RE = re.compile(r"^Slide(\d+)\s*-\s*.+")
_GENERIC_TITLE_RE = re.compile(r"(?i)^\s*(scene|slide|panel|untitled|chapter)\s*\d*\s*$")
_SCENE_TEXT_MODES = ("caption", "dialogue")
_AT_TOKEN_RE = re.compile(r"@([A-Za-z][A-Za-z0-9_]*)")


def _nonempty_str(v) -> bool:
    return isinstance(v, str) and v.strip() != ""


def check_storyboard_layer_a(slides) -> dict:
    issues: list[dict] = []
    if not isinstance(slides, list) or len(slides) == 0:
        return {"layer": "A", "target": "storyboard", "verdict": "FAIL",
                "issues": [{"slide": None, "type": "SHAPE",
                            "problem": "Storyboard is not a non-empty JSON array."}],
                "counts": {"slides": 0}}
    for idx, slide in enumerate(slides, start=1):
        if not isinstance(slide, dict):
            issues.append({"slide": idx, "type": "SHAPE",
                           "problem": "Slide is not an object."})
            continue
        num = slide.get("slide")
        if num != idx:
            issues.append({"slide": idx, "type": "SLIDE_NUMBER",
                           "problem": f"slide={num!r} but expected {idx}."})
        label = slide.get("slide_label", "")
        m = _LABEL_RE.match(label) if isinstance(label, str) else None
        if not m or int(m.group(1)) != (num if isinstance(num, int) else -1):
            issues.append({"slide": idx, "type": "LABEL_FORMAT",
                           "problem": f"slide_label {label!r} != 'SlideNN - <title>'."})
        title = slide.get("title", "")
        if not _nonempty_str(title) or _GENERIC_TITLE_RE.match(title):
            issues.append({"slide": idx, "type": "TITLE",
                           "problem": f"Missing/generic title {title!r}."})
        stype = slide.get("type")
        if stype == "scene":
            if slide.get("text_mode") not in _SCENE_TEXT_MODES:
                issues.append({"slide": idx, "type": "SCENE_TEXT",
                               "problem": f"text_mode {slide.get('text_mode')!r} not caption|dialogue."})
            if not _nonempty_str(slide.get("on_slide_text")):
                issues.append({"slide": idx, "type": "SCENE_TEXT",
                               "problem": "scene on_slide_text empty."})
            if slide.get("text_mode") == "dialogue" and not _nonempty_str(slide.get("speaker")):
                issues.append({"slide": idx, "type": "SCENE_TEXT",
                               "problem": "dialogue slide missing speaker."})
        elif stype == "insight":
            if not _nonempty_str(slide.get("question")):
                issues.append({"slide": idx, "type": "INSIGHT_QA",
                               "problem": "insight slide missing question."})
            if not _nonempty_str(slide.get("answer")):
                issues.append({"slide": idx, "type": "INSIGHT_QA",
                               "problem": "insight slide missing answer."})
        else:
            issues.append({"slide": idx, "type": "TYPE",
                           "problem": f"type {stype!r} not in scene|insight."})
    verdict = "PASS" if not issues else "FAIL"
    return {"layer": "A", "target": "storyboard", "verdict": verdict,
            "issues": issues, "counts": {"slides": len(slides) if isinstance(slides, list) else 0}}


# Per-stage token ceilings (xhigh effort everywhere; the ceiling bounds
# output+reasoning so mechanical calls cannot burn hour-long traces).
EXTRACT_TOKENS = 16384
# Attempt budgets: one `status=incomplete` empty reply must not kill the
# whole stage (live Chapter 1 died on extraction once with zero artifacts,
# then on Ravana's design after 20+ good calls — same signature, same fix).
EXTRACT_ATTEMPTS = 3
DESIGN_ATTEMPTS = 3
FLOW_ATTEMPTS = 3
HINDI_ATTEMPTS = 3
EVAL_ATTEMPTS = 3
# Transport-failure marker: the judge never answered (as opposed to judging
# the board bad). The driver uses it to stop instead of rebuilding.
_NO_VERDICT = "eval produced no usable verdict"
# Batch sizes: entities and slides are independent items — one call per item
# burned ~53 designer calls on Chapter 1. Same prompt, same model, same
# thinking; the per-item validation below is unchanged.
DESIGN_BATCH = 8
FLOW_BATCH = 5
HINDI_BATCH = 5
# Per-run call budget: a run that exceeds this stops with best-effort files
# and rc=1 instead of spiraling (live runs hit 70–88 calls). Transport-level
# retries inside call_muse are the client's business and don't count here.
COMIC_CALL_BUDGET = 100


class _BudgetExhausted(RuntimeError):
    """Raised when a comic run exceeds its logical-call budget."""


_CALL_BUDGET = {"limit": COMIC_CALL_BUDGET, "used": 0}


def _call(messages, **kwargs):
    """Budgeted model call: counts one logical call, then delegates.

    Keeps delegating to the module-global `call_muse` so tests can stub it.
    """
    if _CALL_BUDGET["used"] >= _CALL_BUDGET["limit"]:
        raise _BudgetExhausted(
            f"comic call budget exhausted "
            f"({_CALL_BUDGET['used']}/{_CALL_BUDGET['limit']})")
    _CALL_BUDGET["used"] += 1
    return call_muse(messages, **kwargs)
# Storyboard ceiling: the board is the longest single output (12–20 slides
# of JSON). At 16384 the 12–20-slide board came back truncated (~800-char
# stubs, Layer-A SHAPE fail twice) while podcast creators pass the same
# shape of load at 32768 — reasoning shares the output budget, so the
# ceiling must leave room for thinking AND the full board.
DESIGN_TOKENS = 16384
STORY_TOKENS = 32768
FLOW_TOKENS = 16384
# Judge parity: the verdict object is tiny, but the judge must think over
# ~28KB of narration + board at high effort first — and the ceiling bounds
# thinking AND output. At 4096 the Chapter 1 judge died 5x with
# status=incomplete empties before writing a word. Ceilings are caps, not
# spend: an 8K thought costs 8K at any ceiling.
EVAL_TOKENS = 16384
# Hindi parity: the 19-slide Chapter 1 board (≈15.7KB in, whole-board echo
# out) died 3x with status=incomplete empties at 8192 — reasoning plus the
# full-board echo did not fit. The fields-only contract below shrinks both
# sides, and the ceiling matches the English board so a large chapter never
# asphyxiates mid-reasoning again.
HINDI_TOKENS = 32768


# --- Shared helpers ------------------------------------------------------------
def load_prompt(prompts_dir: Path, name: str) -> str:
    text = (prompts_dir / name).read_text(encoding="utf-8")
    if "\n---\n" in text:
        text = text.split("\n---\n", 1)[1]
    return text.strip() + "\n"


def extract_json(raw: str | None, expect: str):
    """Parse a JSON object ('object') or array ('array') from model output."""
    if not raw:
        return None
    text = raw.strip()
    m = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if m:
        text = m.group(1).strip()
    if expect == "array":
        i, j = text.find("["), text.rfind("]")
    else:
        i, j = text.find("{"), text.rfind("}")
    if i == -1 or j == -1 or j <= i:
        return None
    blob = re.sub(r",\s*([\]}])", r"\1", text[i:j + 1])
    try:
        data = json.loads(blob)
    except json.JSONDecodeError:
        return None
    if expect == "array" and not isinstance(data, list):
        return None
    if expect == "object" and not isinstance(data, dict):
        return None
    return data


def norm_key(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def flow_ref_for(name: str, taken: set[str]) -> str:
    """Deterministic CamelCase flow_ref, unique within the repo."""
    base = "".join(w[:1].upper() + w[1:] for w in re.findall(r"[A-Za-z0-9]+", name))
    base = base or "Entity"
    ref, n = base, 2
    while ref in taken:
        ref = f"{base}{n}"
        n += 1
    taken.add(ref)
    return ref


# --- Entity repo ---------------------------------------------------------------
def load_repo(myth_root: Path) -> tuple[dict, Path]:
    repo_path = assert_inside(myth_root, Path("entities") / "entity_repository.json")
    repo = json.loads(repo_path.read_text(encoding="utf-8"))
    repo.setdefault("characters", {})
    repo.setdefault("scenes", {})
    return repo, repo_path


class _Recorder:
    """Failure observability: append one JSON record per failure point.

    Records the exact stage input that failed (full text — stage inputs are
    small) plus the reply evidence, so the next post-mortem reads a file
    instead of reconstructing from memory. Nothing is recorded on success.
    """

    def __init__(self, chapter_dir: Path, chapter: str) -> None:
        self.path = chapter_dir / f"comic_debug_{chapter}.jsonl"

    def record(self, stage: str, where: dict, input_text: str | None = None,
               reply_text: str | None = None, note: str | None = None) -> None:
        rec: dict = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
                     "stage": stage, "where": where}
        rec["input_chars"] = len(input_text) if input_text is not None else None
        if input_text is not None:
            rec["input"] = input_text
        rec["reply_chars"] = len(reply_text) if reply_text is not None else None
        if reply_text is not None:
            rec["reply"] = reply_text
        if note is not None:
            rec["note"] = note
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _bank_repo(repo_path: Path, snapshot: str, repo: dict,
               dry_run: bool, new_count: int) -> str:
    """Persist the repo when it changed; return the new snapshot.

    Dry runs never mutate the repo. Returns `snapshot` unchanged when
    nothing was written, so repeat calls are cheap no-ops.
    """
    current = json.dumps(repo, sort_keys=True)
    if dry_run or current == snapshot:
        return snapshot
    repo_path.write_text(json.dumps(repo, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8")
    print(f"comic: repo +{new_count} entities")
    return current


def repo_index(repo: dict) -> tuple[dict[str, tuple[str, str]], set[str]]:
    """Map norm_key -> (section, key); plus the set of taken flow_refs."""
    index: dict[str, tuple[str, str]] = {}
    taken: set[str] = set()
    for section in ("characters", "scenes"):
        for key, ent in (repo.get(section) or {}).items():
            if not isinstance(ent, dict):
                continue
            index[norm_key(ent.get("canonical_name", key))] = (section, key)
            for alias in ent.get("aliases", []) or []:
                index.setdefault(norm_key(alias), (section, key))
            if ent.get("flow_ref"):
                taken.add(ent["flow_ref"])
    return index, taken


# --- Dry-run fixtures (schema-valid, no network) -------------------------------
def _fixture_extraction() -> dict:
    return {
        "characters": [
            {"canonical_name": "Valmiki", "aliases": ["Sage Valmiki"],
             "description": "The ascetic sage who seeks the ideal man and becomes the Ramayana's author."},
            {"canonical_name": "Narada", "aliases": ["Devarshi Narada"],
             "description": "The divine traveling sage who answers Valmiki's question."},
        ],
        "scenes": [
            {"canonical_name": "Valmiki's Hermitage", "aliases": [],
             "description": "A tranquil forest-hermitage courtyard where the question is asked."},
        ],
    }


def _fixture_design(name: str, etype: str) -> dict:
    return {
        "canonical_name": name,
        "description": f"Fixture {etype} design for {name}.",
        "image_prompt": (
            f"A full-figure character model-sheet of {name}, classical Indian "
            f"mythological art style, plain seamless neutral-grey studio backdrop, "
            f"soft even lighting, no on-image text."
        ),
        "muse_prompt": f"{name}, as described in this chapter's narration, in classical Indian mythological style.",
    }


def _fixture_storyboard() -> list[dict]:
    return [
        {
            "slide": 1,
            "slide_label": "Slide01 - The Sage's Question",
            "title": "The Sage's Question",
            "type": "scene",
            "text_mode": "caption",
            "speaker": None,
            "on_slide_text": "In a tranquil forest hermitage, the ascetic Valmiki asked the divine traveler Narada whether any mortal alive embodied every ideal virtue at once.",
            "characters": ["Valmiki", "Narada"],
            "location": "Valmiki's Hermitage",
            "rationale": "Opening hook: the question that launches the epic.",
        },
        {
            "slide": 2,
            "slide_label": "Slide02 - Narada Answers",
            "title": "Narada Answers",
            "type": "scene",
            "text_mode": "dialogue",
            "speaker": "Narada",
            "on_slide_text": "Narada smiled and named the prince of Ayodhya, Rama, an ocean of duty, compassion, and patience whose story this will be.",
            "characters": ["Valmiki", "Narada"],
            "location": "Valmiki's Hermitage",
            "rationale": "The answer that names the hero.",
        },
        {
            "slide": 3,
            "slide_label": "Slide03 - Character Is the Story",
            "title": "Character Is the Story",
            "type": "insight",
            "text_mode": None,
            "speaker": None,
            "question": "Why ask about virtues before hearing the tale?",
            "answer": "Because character is the soul of a story — events fade, virtues remain.",
            "on_slide_text": "Why ask about virtues before the tale? Because character is the soul of a story: events fade, but virtues remain.",
            "characters": ["Valmiki", "Kavya"],
            "location": None,
            "rationale": "Reflection takeaway as the closing beat.",
        },
    ]


def _fixture_panel(slide: dict) -> dict:
    scene = f" at {slide['location']}" if slide.get("location") else ""
    return {
        "slide": slide["slide"],
        "slide_label": slide["slide_label"],
        "muse_prompt": (
            f"{slide['title']}{scene}: {slide.get('on_slide_text', '')} "
            "Classical Indian mythological comic art, rich saturated colors, "
            "dramatic cinematic lighting."
        ),
    }


def _fixture_hindi(slides: list[dict]) -> list[dict]:
    hi_text = {
        1: "एक शांत वन-आश्रम में, तपस्वी वाल्मीकि ने देवर्षि नारद से पूछा कि क्या धरती पर कोई ऐसा मनुष्य है जिसमें सभी आदर्श गुण एक साथ हों।",
        2: "नारद मुस्कुराए और अयोध्या के राजकुमार राम का नाम लिया — धर्म, करुणा और धैर्य के सागर, जिनकी कथा यह होने वाली है।",
        3: "कथा से पहले गुण क्यों पूछे? क्योंकि चरित्र ही कथा की आत्मा है — घटनाएँ मिट जाती हैं, गुण रह जाते हैं।",
    }
    out = []
    for s in slides:
        c = dict(s)
        c["on_slide_text"] = hi_text.get(s["slide"], s.get("on_slide_text"))
        if s.get("type") == "insight":
            c["question"] = "कथा से पहले गुण क्यों पूछे?"
            c["answer"] = "क्योंकि चरित्र ही कथा की आत्मा है — घटनाएँ मिट जाती हैं, गुण रह जाते हैं।"
        out.append(c)
    return out


def _find_entity(repo: dict, name: str):
    """Return (section, entity) for a canonical name or alias, else None."""
    nk = norm_key(name or "")
    for section in ("characters", "scenes"):
        for key, ent in (repo.get(section) or {}).items():
            if not isinstance(ent, dict):
                continue
            names = [ent.get("canonical_name", key)] + (ent.get("aliases", []) or [])
            if any(norm_key(n) == nk for n in names if n):
                return section, ent
    return None


# --- Stage implementations -------------------------------------------------------
def stage_entities(prompts_dir: Path, narration: str, repo: dict,
                   chapter: str, dry_run: bool, observe=None,
                   progress=None) -> tuple[dict, list[dict]]:
    """E+P: extract, dedup (deterministic), design new. Returns (repo, new).

    `progress` (called with each chunk's new entries) lets the driver bank
    completed chunks immediately; `observe` records the exact failing input.
    """
    if dry_run:
        extracted = _fixture_extraction()
    else:
        user = "ENGLISH NARRATION:\n" + narration
        extracted = None
        last_raw: str | None = None
        for _ in range(EXTRACT_ATTEMPTS):
            raw = _call([
                {"role": "system", "content": load_prompt(prompts_dir, "entity_extractor.md")},
                {"role": "user", "content": user},
            ], max_tokens=EXTRACT_TOKENS)
            last_raw = raw
            extracted = extract_json(raw, "object")
            if extracted and isinstance(extracted.get("characters"), list) \
                    and isinstance(extracted.get("scenes"), list):
                break
        if not extracted or not isinstance(extracted.get("characters"), list) \
                or not isinstance(extracted.get("scenes"), list):
            if observe is not None:
                observe.record("extract", {"what": "extraction"}, user, last_raw)
            raise RuntimeError("entity extraction produced no usable JSON object")
    index, taken = repo_index(repo)
    # Pre-seed taken refs from the repo so flow_ref_for stays unique.
    new: list[dict] = []
    designer = None if dry_run else load_prompt(prompts_dir, "entity_designer.md")
    # Collect-then-chunk: entities are independent items, so one call designs
    # a whole batch (DESIGN_BATCH) instead of one call per entity.
    pending: list[tuple[str, dict, str]] = []
    for section, items in (("characters", extracted.get("characters", [])),
                           ("scenes", extracted.get("scenes", []))):
        for item in items:
            if not isinstance(item, dict) or not _nonempty_str(item.get("canonical_name")):
                continue
            name = item["canonical_name"].strip()
            if norm_key(name) in index:
                continue  # already in the repo (canonical or alias)
            pending.append((section, item, name))
    for i in range(0, len(pending), DESIGN_BATCH):
        chunk = pending[i:i + DESIGN_BATCH]
        if dry_run:
            designs = {norm_key(name): _fixture_design(
                name, "character" if section == "characters" else "scene")
                for section, _, name in chunk}
        else:
            user = "ENTITIES:\n" + json.dumps(
                [{"entity_type": section[:-1], "canonical_name": name,
                  "chapter_role": item.get("description", "")}
                 for section, item, name in chunk], ensure_ascii=False)
            designs = None
            last_draw: str | None = None
            for _ in range(DESIGN_ATTEMPTS):
                draw = _call([
                    {"role": "system", "content": designer},
                    {"role": "user", "content": user},
                ], max_tokens=DESIGN_TOKENS)
                last_draw = draw
                designs = _match_designs(draw, chunk)
                if designs is not None:
                    break
            if designs is None:
                names = ", ".join(repr(n) for _, _, n in chunk)
                if observe is not None:
                    observe.record("design", {"chunk": [n for _, _, n in chunk]},
                                   user, last_draw)
                raise RuntimeError(f"entity design failed for chunk [{names}]")
        made: list[dict] = []
        for section, item, name in chunk:
            design = designs[norm_key(name)]
            key = norm_key(name)
            repo[section][key] = {
                "type": section[:-1],
                "canonical_name": name,
                "aliases": item.get("aliases", []) or [],
                "description": design.get("description") or item.get("description", ""),
                "flow_ref": flow_ref_for(name, taken),
                "image_prompt": design["image_prompt"],
                "muse_prompt": design["muse_prompt"],
                "first_seen": chapter,
            }
            index[norm_key(name)] = (section, key)
            made.append(repo[section][key])
        new.extend(made)
        if progress is not None:
            progress(made)
    extracted["_new_count"] = len(new)
    return repo, new


def _match_designs(raw: str | None,
                   chunk: list[tuple[str, dict, str]]) -> dict[str, dict] | None:
    """Join a batch design reply to its chunk; None when unusable.

    Requires an array of the same length with every chunk name echoed back
    carrying both prompt texts — a dropped/duplicated item fails the whole
    chunk so the caller retries it intact.
    """
    arr = extract_json(raw, "array")
    if not isinstance(arr, list) or len(arr) != len(chunk):
        return None
    by_key: dict[str, dict] = {}
    for entry in arr:
        if not isinstance(entry, dict) or not _nonempty_str(entry.get("canonical_name")):
            return None
        by_key[norm_key(entry["canonical_name"])] = entry
    got: dict[str, dict] = {}
    for _, _, name in chunk:
        design = by_key.get(norm_key(name))
        if not design or not _nonempty_str(design.get("image_prompt")) \
                or not _nonempty_str(design.get("muse_prompt")):
            return None
        got[norm_key(name)] = design
    return got


def stage_storyboard(prompts_dir: Path, narration_lines: list[str], repo: dict,
                     chapter: str, max_retries: int,
                     dry_run: bool, observe=None) -> tuple[list[dict], dict]:
    """S: storyboard with Layer A retry. Returns (slides, layer_a_verdict)."""
    entity_list = (
        "CHARACTERS: " + ", ".join(
            e.get("canonical_name", k) for k, e in repo.get("characters", {}).items()) +
        "\nSCENES: " + ", ".join(
            e.get("canonical_name", k) for k, e in repo.get("scenes", {}).items()))
    board_prompt = None if dry_run else load_prompt(prompts_dir, "storyboard.md")
    context = entity_list + "\n\nENGLISH NARRATION:\n" + "\n".join(narration_lines)
    critique = ""
    attempts = 0
    while True:
        if dry_run:
            slides = _fixture_storyboard()
            raw = None
        else:
            raw = _call([
                {"role": "system", "content": board_prompt},
                {"role": "user", "content": context + critique},
            ], max_tokens=STORY_TOKENS)
            slides = extract_json(raw, "array")
        verdict = check_storyboard_layer_a(slides)
        if verdict["verdict"] != "PASS":
            # Evidence, not verbosity: the last two live runs died here with
            # ~800-char stubs and no record of what the model returned.
            head = (raw or "")[:600].replace("\n", " ")
            print(f"[comic] storyboard Layer A FAIL "
                  f"(raw {len(raw or '')} chars): {head}", file=sys.stderr)
            if observe is not None and not dry_run:
                observe.record("storyboard", {"attempt": attempts + 1},
                               context + critique, raw,
                               note=json.dumps(verdict.get("issues", []),
                                               ensure_ascii=False)[:2000])
        if verdict["verdict"] == "PASS" or attempts >= max_retries:
            return slides, verdict
        critique = "\n\nLAYER-A FAILURES (fix every one, keep the schema):\n" + json.dumps(
            verdict["issues"], ensure_ascii=False)
        attempts += 1


def stage_flow(prompts_dir: Path, slides: list[dict], repo: dict,
               dry_run: bool, observe=None, progress=None) -> list[dict]:
    """F: Muse-native panel prompt per slide, in chunks. Returns records.

    Flow/ingredient output was removed (Muse image prompts only): each record
    is {slide, slide_label, muse_prompt}. Slides are independent items, so one
    call prompts a whole batch (FLOW_BATCH) instead of one call per slide.
    `progress` (called with the cumulative records after each chunk) lets the
    driver persist completed chunks immediately.
    """
    panel_prompt = None if dry_run else load_prompt(prompts_dir, "panel_prompts.md")
    records: list[dict] = []
    for i in range(0, len(slides), FLOW_BATCH):
        chunk = slides[i:i + FLOW_BATCH]
        if dry_run:
            for slide in chunk:
                records.append(_fixture_panel(slide))
            if progress is not None:
                progress(records)
            continue
        seen: list[str] = []
        for slide in chunk:
            for name in (slide.get("characters") or []) + ([slide.get("location")] if slide.get("location") else []):
                if name not in seen:
                    seen.append(name)
        ent_ctx = []
        for name in seen:
            hit = _find_entity(repo, name)
            if hit:
                _, ent = hit
                ent_ctx.append(
                    f"- {ent.get('canonical_name')}: {ent.get('muse_prompt', '')}")
        user = ("SLIDES:\n" + json.dumps(chunk, ensure_ascii=False) +
                "\n\nENTITY IDENTITIES:\n" + "\n".join(ent_ctx))
        recs = None
        last_raw: str | None = None
        for _ in range(FLOW_ATTEMPTS):
            raw = _call([
                {"role": "system", "content": panel_prompt},
                {"role": "user", "content": user},
            ], max_tokens=FLOW_TOKENS)
            last_raw = raw
            recs = _match_panels(raw, chunk)
            if recs is not None:
                break
        if recs is None:
            nos = ", ".join(str(s.get("slide")) for s in chunk)
            if observe is not None:
                observe.record("flow", {"slides": [s.get("slide") for s in chunk]},
                               user, last_raw)
            raise RuntimeError(f"panel prompts failed for slides [{nos}]")
        for slide in chunk:
            records.append({"slide": slide["slide"],
                            "slide_label": slide["slide_label"],
                            "muse_prompt": recs[slide["slide"]]})
        if progress is not None:
            progress(records)
    return records


def _match_panels(raw: str | None, chunk: list[dict]) -> dict[int, str] | None:
    """Join a batch panel reply to its chunk; None when unusable.

    Requires an array of the same length with every chunk slide number echoed
    back carrying a non-empty muse_prompt — a dropped/duplicated slide fails
    the whole chunk so the caller retries it intact.
    """
    arr = extract_json(raw, "array")
    if not isinstance(arr, list) or len(arr) != len(chunk):
        return None
    want = {s.get("slide") for s in chunk}
    got: dict[int, str] = {}
    for entry in arr:
        if not isinstance(entry, dict) or entry.get("slide") not in want:
            return None
        text = entry.get("muse_prompt")
        if not _nonempty_str(text):
            return None
        got[entry["slide"]] = text
    return got if len(got) == len(chunk) else None


def stage_eval(prompts_dir: Path, narration_lines: list[str], slides: list[dict],
               dry_run: bool, thinking: str = "high", observe=None) -> dict:
    """V: judge verdict object {verdict, strengths, weaknesses}.

    Reviewing against a checklist is cheaper than creating — the judge runs
    at high effort while creators stay at the env default (xhigh). A judge
    call that comes back empty is retried on its own (EVAL_ATTEMPTS) with
    each miss recorded — it must never cost a full-pipeline redo (Chapter
    1 burned ~30 calls re-running E/S/F/H for two flaked verdict calls).
    """
    if dry_run:
        return {"verdict": "PASS", "strengths": ["dry-run fixture"], "weaknesses": []}
    user = ("ENGLISH NARRATION:\n" + "\n".join(narration_lines) +
            "\n\nSTORYBOARD:\n" + json.dumps(slides, ensure_ascii=False))
    for attempt in range(1, EVAL_ATTEMPTS + 1):
        raw = _call([
            {"role": "system", "content": load_prompt(prompts_dir, "storyboard_eval.md")},
            {"role": "user", "content": user},
        ], max_tokens=EVAL_TOKENS, thinking=thinking)
        verdict = extract_json(raw, "object")
        if verdict and verdict.get("verdict") in ("PASS", "FAIL"):
            return verdict
        if observe is not None:
            observe.record("eval", {"attempt": attempt}, user, raw)
    return {"verdict": "FAIL", "strengths": [],
            "weaknesses": [_NO_VERDICT]}


HINDI_FIELDS = ("on_slide_text", "question", "answer")


def _hindi_need(slides: list[dict]) -> list[dict]:
    """Fields-only translation items: slide + on-panel text, nothing else.

    Scene slides translate `on_slide_text`; insight slides add `question`
    and `answer` (whichever are non-empty). Slides with no on-panel text
    are skipped — they merge through verbatim. This keeps the Hindi
    round-trip to a fraction of the whole-board echo that died on Chapter 1.
    """
    need = []
    for slide in slides:
        fields = {k: slide[k] for k in HINDI_FIELDS
                  if _nonempty_str(slide.get(k))}
        if fields:
            need.append({"slide": slide["slide"], "fields": fields})
    return need


def _match_hindi(raw: str | None, chunk: list[dict]) -> dict[int, dict] | None:
    """Join a batch translation reply to its chunk; None when unusable.

    Requires an array of the same length with every chunk slide echoed back
    carrying a non-empty translation for each requested field — a
    dropped/duplicated slide or field fails the whole chunk so the caller
    retries it intact.
    """
    arr = extract_json(raw, "array")
    if not isinstance(arr, list) or len(arr) != len(chunk):
        return None
    want = {item["slide"]: item["fields"] for item in chunk}
    got: dict[int, dict] = {}
    for entry in arr:
        if not isinstance(entry, dict) or entry.get("slide") not in want:
            return None
        fields = entry.get("fields")
        if not isinstance(fields, dict):
            return None
        for key in want[entry["slide"]]:
            if not _nonempty_str(fields.get(key)):
                return None
        got[entry["slide"]] = {k: fields[k] for k in want[entry["slide"]]}
    return got if len(got) == len(chunk) else None


def stage_hindi(prompts_dir: Path, slides: list[dict], dry_run: bool,
                observe=None, partial: dict | None = None,
                progress=None) -> list[dict]:
    """H: translate on-panel text fields only, merge programmatically.

    The model sees and returns just {slide, fields} items in HINDI_BATCH
    chunks — never the whole board — and the driver merges translations
    back onto verbatim English slides, so structure cannot drift in
    translation. `partial` maps slide numbers to already-translated field
    dicts (an earlier chunk or run) and is honored after validation;
    `progress` receives the cumulative translated-items list after each
    chunk so the driver can persist it.
    """
    need = _hindi_need(slides)
    done: dict[int, dict] = {}
    if partial:
        want = {item["slide"]: set(item["fields"]) for item in need}
        for num, fields in partial.items():
            try:
                num = int(num)
            except (TypeError, ValueError):
                continue
            if num in want and isinstance(fields, dict) \
                    and all(_nonempty_str(fields.get(k)) for k in want[num]):
                done[num] = {k: fields[k] for k in want[num]}
    todo = [item for item in need if item["slide"] not in done]
    translator = None if dry_run else load_prompt(prompts_dir,
                                                  "hindi_storyboard.md")
    fix: dict[int, dict] = {}
    if dry_run:
        fix = {s["slide"]: s for s in _fixture_hindi(slides)}
    for i in range(0, len(todo), HINDI_BATCH):
        chunk = todo[i:i + HINDI_BATCH]
        if dry_run:
            got = {item["slide"]:
                   {k: fix[item["slide"]].get(k, item["fields"][k])
                    for k in item["fields"]}
                   for item in chunk}
        else:
            user = json.dumps(chunk, ensure_ascii=False)
            got = None
            last_raw: str | None = None
            for _ in range(HINDI_ATTEMPTS):
                raw = _call([
                    {"role": "system", "content": translator},
                    {"role": "user", "content": user},
                ], max_tokens=HINDI_TOKENS)
                last_raw = raw
                got = _match_hindi(raw, chunk)
                if got is not None:
                    break
            if got is None:
                nos = [item["slide"] for item in chunk]
                if observe is not None:
                    observe.record("hindi", {"slides": nos}, user, last_raw)
                raise RuntimeError(
                    f"hindi translation failed for slides {nos}")
        done.update(got)
        if progress is not None:
            progress([{"slide": item["slide"], "fields": done[item["slide"]]}
                      for item in need if item["slide"] in done])
    hindi = []
    for slide in slides:
        c = dict(slide)
        if slide["slide"] in done:
            c.update(done[slide["slide"]])
        hindi.append(c)
    return hindi


def run_chapter(myth_root: Path, prompts_dir: Path, chapter: str,
                max_storyboard_retries: int = 1, max_loops: int = 2,
                dry_run: bool = False, redo_comic: bool = False,
                max_calls: int | None = None) -> int:
    chapter_dir = assert_inside(myth_root, Path("outputs") / chapter)
    en_path = chapter_dir / f"english_narration_{chapter}.txt"
    if not en_path.exists():
        print(f"! comic: no {en_path.name} (run podcast + bridge first)",
              file=sys.stderr)
        return 2
    eval_path = chapter_dir / f"comic_eval_{chapter}.json"
    if eval_path.exists() and not redo_comic and not dry_run:
        try:
            if is_live_pass(json.loads(eval_path.read_text(encoding="utf-8"))):
                print(f"comic: {chapter} already PASS (use --redo-comic to rerun)")
                return 0
        except (json.JSONDecodeError, OSError):
            pass

    narration = en_path.read_text(encoding="utf-8")
    narration_lines = [ln for ln in narration.splitlines() if ln.strip()]
    corpus = myth_root.name

    repo, repo_path = load_repo(myth_root)
    repo_before = json.dumps(repo, sort_keys=True)
    _CALL_BUDGET["used"] = 0
    _CALL_BUDGET["limit"] = max_calls or COMIC_CALL_BUDGET
    new_entities: list[dict] = []
    observe = _Recorder(chapter_dir, chapter)
    snap = [repo_before]
    banked_total = [0]

    def _save_repo(made: list) -> None:
        banked_total[0] += len(made)
        snap[0] = _bank_repo(repo_path, snap[0], repo, dry_run, banked_total[0])

    def _save_pack(records: list) -> None:
        _write_outputs(chapter_dir, chapter, None, None, list(records),
                       None, None, None)

    def _save_hindi_partial(items: list) -> None:
        (chapter_dir / f"comic_hindi_partial_{chapter}.json").write_text(
            json.dumps(items, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")

    # Per-stage resume: a persisted live board/flow/Hindi board is adopted
    # instead of re-run — only what is pending costs calls. Dry runs never
    # resume (fixtures must not poison live files) and --redo-comic forces
    # a full run.
    live = not dry_run
    may_resume = live and not redo_comic
    resume = _load_progress(chapter_dir, chapter) if may_resume else None
    adopted: tuple[list | None, dict | None] = \
        _adopt_board(chapter_dir, chapter, resume) if resume else (None, None)

    try:
        for loop in range(1, max_loops + 1):
            if adopted[0] is not None and loop == 1:
                slides, sb_a = adopted
                new_entities = []
                print(f"comic: {chapter} resuming from saved board "
                      f"({len(slides)} slides, E/S skipped)")
            else:
                repo, new_entities = stage_entities(
                    prompts_dir, narration, repo, chapter, dry_run,
                    observe=observe, progress=_save_repo)
                # Bank E+P progress now: a later stage failing must not
                # discard the designer calls — the next loop then dedups to
                # zero new entities instead of redesigning everything (run 6
                # burned ~25 designs twice).
                repo_before = _bank_repo(repo_path, snap[0], repo, dry_run,
                                         len(new_entities))
                snap[0] = repo_before
                slides, sb_a = stage_storyboard(
                    prompts_dir, narration_lines, repo, chapter,
                    max_storyboard_retries, dry_run, observe=observe)
                if sb_a["verdict"] != "PASS":
                    eval_rec = _eval_record(chapter, corpus, "FAIL", repo,
                                            slides, sb_a, {"verdict": "FAIL"},
                                            new_entities, dry_run=dry_run)
                    _write_outputs(chapter_dir, chapter, None, slides, None,
                                   None, None, eval_rec)
                    _save_progress(chapter_dir, chapter, live, eval="FAIL")
                    print(f"comic: storyboard Layer A FAIL (loop {loop})",
                          file=sys.stderr)
                    if loop >= max_loops:
                        return 1
                    continue
                # Persist the board now: a later stage failing must not
                # discard reviewable output (run 7's 19KB board died in
                # memory). A fresh board invalidates downstream artifacts.
                _write_outputs(chapter_dir, chapter, None, slides, None,
                               None, None, None)
                _reset_downstream(chapter_dir, chapter)
                _save_progress(chapter_dir, chapter, live,
                               board_slides=len(slides), layer_a=sb_a,
                               flow_slides=0, hindi_slides=0, eval=None)
            if may_resume:
                have, missing = _adopt_flow(chapter_dir, chapter, slides)
            else:
                have, missing = [], slides
            if not missing:
                flow_records = have
                print(f"comic: {chapter} reusing saved flow "
                      f"({len(have)} packs, F skipped)")
            elif have:
                print(f"comic: {chapter} resuming flow "
                      f"({len(have)}/{len(slides)} packs saved)")
                def _save_rest(recs: list, _have=have) -> None:
                    _save_pack(sorted(_have + recs,
                                      key=lambda r: r["slide"]))
                flow_records = sorted(
                    have + stage_flow(prompts_dir, missing, repo, dry_run,
                                      observe=observe, progress=_save_rest),
                    key=lambda r: r["slide"])
            else:
                flow_records = stage_flow(prompts_dir, slides, repo, dry_run,
                                          observe=observe, progress=_save_pack)
            _save_progress(chapter_dir, chapter, live,
                           flow_slides=len(slides))
            hindi_slides = _adopt_hindi(chapter_dir, chapter, slides) \
                if may_resume else None
            if hindi_slides is None:
                part = _adopt_hindi_partial(chapter_dir, chapter, slides) \
                    if may_resume else {}
                if part:
                    print(f"comic: {chapter} resuming Hindi "
                          f"({len(part)} slides translated)")
                hindi_slides = stage_hindi(prompts_dir, slides, dry_run,
                                           observe=observe, partial=part,
                                           progress=_save_hindi_partial)
            else:
                print(f"comic: {chapter} reusing saved Hindi board "
                      f"(H skipped)")
            # Persist the Hindi board too: eval/budget failing later must not
            # discard it either.
            _write_outputs(chapter_dir, chapter, None, None, None,
                           hindi_slides, None, None)
            try:
                (chapter_dir / f"comic_hindi_partial_{chapter}.json").unlink()
            except OSError:
                pass
            _save_progress(chapter_dir, chapter, live,
                           hindi_slides=len(slides))
            judge = stage_eval(prompts_dir, narration_lines, slides, dry_run,
                               observe=observe)
            eval_rec = _eval_record(chapter, corpus,
                                    "PASS" if judge.get("verdict") == "PASS" else "FAIL",
                                    repo, slides, sb_a, judge, new_entities,
                                    dry_run=dry_run)
            _write_outputs(chapter_dir, chapter, {"new_entities": len(new_entities)},
                           slides, flow_records, hindi_slides,
                           None, eval_rec, new_entities=new_entities if dry_run else None,
                           repo=repo)
            _save_progress(chapter_dir, chapter, live,
                           eval=eval_rec["verdict"])
            if eval_rec["verdict"] == "PASS":
                repo_before = _bank_repo(repo_path, repo_before, repo, dry_run,
                                         len(new_entities))
                print(f"comic: {chapter} PASS "
                      f"({len(slides)} slides, +{len(new_entities)} entities)")
                return 0
            if judge.get("weaknesses") == [_NO_VERDICT]:
                # Transport failure, not a quality judgment: the judge never
                # answered, so there is nothing to rebuild. Stop here — the
                # manifest keeps every completed stage and the next run goes
                # straight back to the judge. Only an explicit verdict FAIL
                # retries the pipeline.
                print(f"comic: eval produced no usable verdict (loop {loop}); "
                      f"not rebuilding — rerun resumes at the judge",
                      file=sys.stderr)
                return 1
            print(f"comic: eval FAIL (loop {loop}): "
                  f"{judge.get('weaknesses', [])}", file=sys.stderr)
    except _BudgetExhausted as e:
        print(f"comic: {e}", file=sys.stderr)
        observe.record("budget", {"limit": _CALL_BUDGET["limit"]},
                       note=str(e))
        eval_rec = _eval_record(
            chapter, corpus, "FAIL", repo, None,
            {"verdict": "FAIL", "issues": [{"problem": str(e)}]},
            {"verdict": "FAIL", "strengths": [],
             "weaknesses": ["call budget exhausted"]},
            new_entities, dry_run=dry_run)
        _write_outputs(chapter_dir, chapter, None, None, None, None,
                       None, eval_rec)
        _save_progress(chapter_dir, chapter, live, eval="FAIL")
        _bank_repo(repo_path, repo_before, repo, dry_run, len(new_entities))
        return 1
    return 1


def is_live_pass(eval_rec: dict | None) -> bool:
    """Live resume predicate: a dry-run fixture PASS must NOT count as done.

    Dry runs write a verdict-PASS eval of fixture content; the live resume
    gate must ignore it or live work is silently skipped (hit on Chapter 1).
    Records written before this marker carry no `dry_run` key and keep the
    old meaning (a bare PASS counts as done).
    """
    return bool(isinstance(eval_rec, dict)
                and eval_rec.get("verdict") == "PASS"
                and not eval_rec.get("dry_run"))


def _progress_path(chapter_dir: Path, chapter: str) -> Path:
    return chapter_dir / f"comic_progress_{chapter}.json"


def _load_progress(chapter_dir: Path, chapter: str) -> dict | None:
    """Live stage-completion manifest, or None when unusable.

    Only a manifest stamped live by a live run counts — dry runs stamp
    their own fixture files live:false so fixture output is never resumed
    from (a dry-run board for the same chapter would otherwise look done).
    """
    try:
        d = json.loads(_progress_path(chapter_dir, chapter).read_text(
            encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(d, dict) or d.get("chapter") != chapter \
            or d.get("live") is not True:
        return None
    return d


def _save_progress(chapter_dir: Path, chapter: str, live: bool,
                   **fields) -> dict:
    """Read-modify-write the manifest; returns it.

    Live and dry runs both stamp it so `live` always describes the files
    currently on disk.
    """
    path = _progress_path(chapter_dir, chapter)
    d: dict = {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict) and raw.get("chapter") == chapter:
            d = raw
    except (OSError, json.JSONDecodeError):
        pass
    d["chapter"] = chapter
    d["live"] = bool(live)
    d.update(fields)
    path.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    return d


def _read_json_list(path: Path) -> list | None:
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return d if isinstance(d, list) else None


def _adopt_board(chapter_dir: Path, chapter: str,
                 resume: dict | None) -> tuple[list | None, dict | None]:
    """Adopt a persisted live board, else (None, None) for a fresh E/S run.

    A board counts as done only when the manifest records a live Layer-A
    PASS for exactly this many slides and the file on disk matches.
    """
    if not resume or not resume.get("board_slides"):
        return None, None
    layer_a = resume.get("layer_a")
    if not isinstance(layer_a, dict) or layer_a.get("verdict") != "PASS":
        return None, None
    board = _read_json_list(chapter_dir / f"comic_storyboard_{chapter}.json")
    if board is None or len(board) != resume["board_slides"] \
            or any(not isinstance(s, dict) or s.get("slide") is None
                   for s in board):
        return None, None
    return board, layer_a


def _adopt_flow(chapter_dir: Path, chapter: str,
                slides: list[dict]) -> tuple[list, list]:
    """Split persisted muse packs into (done records, slides still missing).

    Done records reuse the on-disk projection, which is exactly the
    {slide, slide_label, muse_prompt} shape stage_flow returns, so the
    remainder runs on the missing slides only and merges back in order.
    """
    packs = _read_json_list(
        chapter_dir / f"comic_muse_prompts_{chapter}.json") or []
    by_slide = {}
    for p in packs:
        if isinstance(p, dict) and p.get("slide") is not None \
                and _nonempty_str(p.get("muse_prompt")):
            by_slide.setdefault(p["slide"], p)
    done = [{"slide": s["slide"],
             "slide_label": by_slide[s["slide"]].get("slide_label")
             or s["slide_label"],
             "muse_prompt": by_slide[s["slide"]].get("muse_prompt", "")}
            for s in slides if s["slide"] in by_slide]
    missing = [s for s in slides if s["slide"] not in by_slide]
    return done, missing


def _adopt_hindi(chapter_dir: Path, chapter: str,
                 slides: list[dict]) -> list | None:
    """Adopt a complete persisted Hindi board, else None.

    Trusts the file only when its slide set matches the board and every
    slide needing translation carries non-empty translated fields.
    """
    hindi = _read_json_list(
        chapter_dir / f"comic_storyboard_hindi_{chapter}.json")
    if hindi is None or len(hindi) != len(slides):
        return None
    if {s.get("slide") for s in hindi if isinstance(s, dict)} != \
            {s["slide"] for s in slides}:
        return None
    need = {item["slide"]: set(item["fields"]) for item in _hindi_need(slides)}
    by_slide = {s["slide"]: s for s in hindi if isinstance(s, dict)}
    for num, keys in need.items():
        entry = by_slide.get(num)
        if not isinstance(entry, dict) \
                or any(not _nonempty_str(entry.get(k)) for k in keys):
            return None
    return hindi


def _adopt_hindi_partial(chapter_dir: Path, chapter: str,
                         slides: list[dict]) -> dict:
    """Validated slide->fields translations from an unfinished H run.

    stage_hindi revalidates field completeness per slide, so anything
    stale or short is simply retranslated.
    """
    items = _read_json_list(
        chapter_dir / f"comic_hindi_partial_{chapter}.json") or []
    want = {s["slide"] for s in slides}
    part = {}
    for it in items:
        if isinstance(it, dict) and it.get("slide") in want \
                and isinstance(it.get("fields"), dict):
            part[it["slide"]] = it["fields"]
    return part


def _reset_downstream(chapter_dir: Path, chapter: str) -> None:
    """Drop flow/Hindi artifacts when a fresh board replaces the old one."""
    dropped = []
    for name in (f"comic_muse_prompts_{chapter}.json",
                 f"comic_storyboard_hindi_{chapter}.json",
                 f"comic_hindi_partial_{chapter}.json"):
        try:
            (chapter_dir / name).unlink()
            dropped.append(name)
        except OSError:
            pass
    if dropped:
        print(f"comic: new board, dropped stale {', '.join(dropped)}")


def _eval_record(chapter: str, corpus: str, verdict: str, repo: dict,
                 slides: list | None, sb_a: dict, judge: dict,
                 new_entities: list, dry_run: bool = False) -> dict:
    return {
        "verdict": verdict,
        "gate": "structural",
        "dry_run": dry_run,
        "model": MODEL,
        "structural_ok": verdict == "PASS",
        "corpus": corpus,
        "counts": {
            "slides": len(slides or []),
            "extracted_characters": len(repo.get("characters", {})),
            "extracted_scenes": len(repo.get("scenes", {})),
        },
        "storyboard_layer_a": sb_a,
        "judge": judge,
    }


RENDER_SIZES = ("1024x1024", "1024x1536", "1536x1024")


def _render_plan(slides: list[dict], flow_records: list[dict], repo: dict) -> dict:
    """Build the image-render handoff: roster + per-slide panel turns.

    Deterministic, no model. Per the Muse Image anchoring recipe: render one
    sheet per roster subject (from its `image_prompt`), keep the returned
    response id, then chain each panel turn from its subjects'
    `previous_response_id`s with the slide `muse_prompt` as input.
    Sizes are advisory defaults from the cookbook's three panel shapes.
    """
    prose = {r["slide"]: r.get("muse_prompt", "") for r in flow_records
             if isinstance(r, dict)}
    roster: dict[str, dict] = {}

    def _subject(name: str) -> dict:
        if name not in roster:
            ent, section = None, None
            for sec in ("characters", "scenes"):
                hit = (repo.get(sec, {}) or {}).get(norm_key(name or ""))
                if hit is not None:
                    ent, section = hit, sec
                    name = ent.get("canonical_name", name)
                    break
            if ent is None:
                for sec in ("characters", "scenes"):
                    for key, cand in (repo.get(sec, {}) or {}).items():
                        names = [cand.get("canonical_name", key)] + (cand.get("aliases", []) or [])
                        if any(norm_key(n) == norm_key(name) for n in names if n):
                            ent, section, name = cand, sec, cand.get("canonical_name", key)
                            break
                    if ent is not None:
                        break
            roster[name] = {
                "name": name,
                "kind": section[:-1] if section else "unknown",
                "flow_ref": ent.get("flow_ref") if ent else None,
                "image_prompt": ent.get("image_prompt") if ent else None,
                "sheet_response_id": None,  # fill in when the sheet is rendered
            }
        return {"name": name, "kind": roster[name]["kind"]}

    plan_slides = []
    for slide in slides:
        names: list[str] = []
        for n in (slide.get("characters") or []) + ([slide.get("location")] if slide.get("location") else []):
            if n not in names:
                names.append(n)
        if slide.get("slide") == 1:
            size = "1536x1024"  # establishing opener, wide
        elif slide.get("type") == "insight" or slide.get("text_mode") == "dialogue":
            size = "1024x1024"  # two-shots and insight cards, square
        else:
            size = "1024x1536"  # captioned story beats, portrait
        plan_slides.append({
            "slide": slide.get("slide"),
            "slide_label": slide.get("slide_label"),
            "muse_prompt": prose.get(slide.get("slide"), ""),
            "subjects": [_subject(n) for n in names],
            "size": size,
        })
    return {"roster": [roster[k] for k in sorted(roster)],
            "slides": plan_slides}


def _write_outputs(chapter_dir: Path, chapter: str, extraction: dict | None,
                   slides: list | None, flow_records: list | None,
                   hindi_slides: list | None, muse_pack: list | None,
                   eval_rec: dict | None, new_entities: list | None = None,
                   repo: dict | None = None) -> None:
    def _w(name: str, obj) -> None:
        (chapter_dir / name).write_text(
            json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if slides is not None:
        _w(f"comic_storyboard_{chapter}.json", slides)
    if flow_records is not None:
        _w(f"comic_muse_prompts_{chapter}.json",
           [{"slide": r["slide"], "slide_label": r["slide_label"],
             "muse_prompt": r.get("muse_prompt", "")} for r in flow_records])
        if repo is not None:
            _w(f"comic_render_plan_{chapter}.json",
               _render_plan(slides or [], flow_records, repo))
    if hindi_slides is not None:
        _w(f"comic_storyboard_hindi_{chapter}.json", hindi_slides)
    if new_entities is not None:  # dry-run preview only; repo untouched
        _w(f"comic_entities_preview_{chapter}.json", new_entities)
    if eval_rec is not None:
        _w(f"comic_eval_{chapter}.json", eval_rec)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="MythologyMuse comic stages")
    ap.add_argument("--mythology", default="mythologies/ramayana_dutt")
    ap.add_argument("--chapter", default="")
    ap.add_argument("--prompts-dir", default="")
    ap.add_argument("--max-storyboard-retries", type=int, default=1)
    ap.add_argument("--max-loops", type=int, default=2)
    ap.add_argument("--max-calls", type=int, default=None)
    ap.add_argument("--redo-comic", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    if not args.chapter:
        print("nothing to do: give --chapter", file=sys.stderr)
        return 2
    from muse_client import parse_chapter_id as _pci
    try:
        myth_root = resolve_mythology_root(args.mythology)
        _pci(args.chapter)
    except SystemExit as e:
        print(e.code, file=sys.stderr)
        return 2
    default_prompts = Path(__file__).resolve().parent.parent / "prompts"
    prompts_dir = Path(args.prompts_dir) if args.prompts_dir else default_prompts
    if not prompts_dir.is_dir():
        print(f"prompts dir not found: {prompts_dir}", file=sys.stderr)
        return 2
    try:
        return run_chapter(myth_root, prompts_dir, args.chapter,
                           max_storyboard_retries=args.max_storyboard_retries,
                           max_loops=args.max_loops,
                           dry_run=args.dry_run, redo_comic=args.redo_comic,
                           max_calls=args.max_calls)
    except (RuntimeError, OSError) as e:
        print(f"comic hard error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
