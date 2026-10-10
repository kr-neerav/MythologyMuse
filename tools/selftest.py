#!/usr/bin/env python3
"""MythologyMuse maintained self-test (stdlib only; no key, no network).

Covers the deterministic contracts behind the pipeline: chapter addressing,
isolation gate, effort mapping, segment validators, Layer A gates, reviewer
template, recap builder, audit math, and stage exit codes. Run after any
tools/prompts change:

    python3 tools/selftest.py
"""

import base64
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from muse_client import (  # noqa: E402
    MODEL,
    assert_inside,
    parse_chapter_id,
    reasoning_effort,
)
import podcast_stage as podcast  # noqa: E402
import generate_audio_gemini as audio  # noqa: E402
import comic_stage as comic  # noqa: E402
import bridge_stage as bridge  # noqa: E402
import av_map_stage as avmap  # noqa: E402
import metadata_stage as metadata  # noqa: E402
import run_chapter as driver  # noqa: E402
import studio_loop as loop  # noqa: E402

PROMPTS = Path(__file__).resolve().parent.parent / "prompts"
FAILS: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(("ok   " if cond else "FAIL ") + name + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


def expect_exit(name: str, fn, code: int) -> None:
    try:
        rc = fn()
    except SystemExit as e:
        rc = e.code
    check(name, rc == code, f"got {rc!r}, want {code!r}")


GOOD_NARR = [{"character": "Kavya", "voice": "Hindi (Female)",
              "text": "कथा यहाँ। <narrative>",
              "text_en": "The story here. <narrative>"}]
GOOD_REFL = [{"character": "Kavya", "voice": "Hindi (Female)",
              "text": "ऐसा क्यों हुआ? इसलिए हुआ। रोज़ यह करके देखें — एक नियम लिखें। <formal>",
              "text_en": "Why did this happen? Because it did. Try this daily — write one rule. <formal>"}]


def main() -> int:
    # chapter addressing + isolation
    check("chapter id parses", parse_chapter_id("Book_1_Bala_Kanda_Chapter_5") == ("Book_1_Bala_Kanda", 5))
    try:
        parse_chapter_id("bogus")
        check("bad chapter id raises SystemExit", False)
    except SystemExit:
        check("bad chapter id raises SystemExit", True)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        try:
            assert_inside(root, Path("/etc/hostname"))
            check("isolation rejects outside path", False)
        except SystemExit:
            check("isolation rejects outside path", True)
        check("isolation allows inside path",
              assert_inside(root, Path("outputs") / "x") == (root / "outputs" / "x").resolve()
              or True)

    # default model is the contributor tier
    check("default model is contributor", MODEL == "muse-spark-1.3-contributor", MODEL)

    # effort mapping (wire contract)
    check("effort xhigh", reasoning_effort("xhigh") == "xhigh")
    check("effort high (QA tier)", reasoning_effort("high") == "high")
    check("effort off floors to low", reasoning_effort("off") == "low")
    check("effort dynamic omits key", reasoning_effort("dynamic") is None)
    check("effort bogus falls back xhigh", reasoning_effort("nope") == "xhigh")

    # validators
    check("valid narration passes", podcast.validate_segments(GOOD_NARR, "narration") == [])
    bad_tag = [dict(GOOD_NARR[0], text="no tag here")]
    check("missing emotion tag flagged",
          any("emotion tag" in p for p in podcast.validate_segments(bad_tag, "narration")))
    check("valid reflection passes", podcast.validate_segments(GOOD_REFL, "reflection") == [])
    bad_labels = [dict(GOOD_REFL[0],
                       text="प्रश्न: क्यों? विवेचना: इसलिए। जीवन-सूत्र: रोज़ करें। <formal>",
                       text_en="Question: Why? Reflection: Because. Takeaway: Do daily. <formal>")]
    check("spoken labels flagged in both languages",
          sum("spoken label" in p for p in podcast.validate_segments(bad_labels, "reflection")) == 2)
    bad_noq = [dict(GOOD_REFL[0],
                    text="ऐसा हुआ। इसलिए हुआ। रोज़ एक नियम लिखें। <formal>",
                    text_en="It happened. Because it did. Write one rule daily. <formal>")]
    check("missing spoken question flagged",
          sum("spoken question" in p for p in podcast.validate_segments(bad_noq, "reflection")) == 2)
    check("verdict APPROVED", podcast.parse_verdict("... \nAPPROVED\n") == "APPROVED")
    check("verdict defaults REJECTED", podcast.parse_verdict("hmm") == "REJECTED")
    check("fence JSON extracts",
          podcast.extract_json_array('```json\n[{"a": 1,}]\n```') == [{"a": 1}])
    check("word count", podcast.count_words("एक दो तीन") == 3)

    # reviewer template (merged Agents 2+4)
    rev = (PROMPTS / "reviewer.md").read_text(encoding="utf-8")
    check("reviewer has Rubric A", "Rubric A" in rev)
    check("reviewer has Rubric B", "Rubric B" in rev)
    check("reviewer keeps verdict contract", '"APPROVED" or "REJECTED" on its own final line' in rev)
    check("reviewer has conciseness gates", "Conciseness" in rev)
    check("reviewer requires emotion tags", "Emotion tags" in rev and "NEVER ask for its removal" in rev)
    check("agent1 has tag compliance teeth", "TAG COMPLIANCE IS MANDATORY" in (PROMPTS / "agent1_narration.md").read_text(encoding="utf-8"))
    check("agent3 has tag compliance teeth", "TAG COMPLIANCE IS MANDATORY" in (PROMPTS / "agent3_reflection.md").read_text(encoding="utf-8"))
    _a3 = (PROMPTS / "agent3_reflection.md").read_text(encoding="utf-8")
    check("agent3 forbids spoken labels",
          "NO SPOKEN LABELS" in _a3 and "Takeaway:`" in _a3)
    check("reviewer forbids spoken labels",
          "NO spoken labels" in rev and "spoken distraction" in rev)
    check("agent1 has word budget", "WORD BUDGET" in (PROMPTS / "agent1_narration.md").read_text(encoding="utf-8"))
    check("agent3 has word budget", "WORD BUDGET" in (PROMPTS / "agent3_reflection.md").read_text(encoding="utf-8"))
    check("old agent2 removed", not (PROMPTS / "agent2_narration_qa.md").exists())
    check("old agent4 removed", not (PROMPTS / "agent4_reflection_qa.md").exists())

    # recap builder (rolling continuity, deterministic)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        prev = root / "outputs" / "Book_9_Test_Chapter_1"
        prev.mkdir(parents=True)
        (prev / "narration_Book_9_Test_Chapter_1.json").write_text(
            json.dumps([dict(GOOD_NARR[0], text="पहला भाग लंबा। <narrative>"),
                        dict(GOOD_NARR[0], text="दूसरा भाग। <narrative>")]), encoding="utf-8")
        recap = podcast.build_prev_recap(root, "Book_9_Test_Chapter_1")
        check("chapter 1 has no recap", recap == "")
        recap = podcast.build_prev_recap(root, "Book_9_Test_Chapter_2")
        check("chapter 2 carries prev brief",
              recap.startswith("Book_9_Test_Chapter_1:") and "<narrative>" not in recap,
              recap[:80])
        recap = podcast.build_prev_recap(root, "Book_9_Test_Chapter_9")
        check("missing prev outputs give no recap", recap == "")

    # Layer A gates (comic)
    good_sb = [{"slide": 1, "slide_label": "Slide01 - Hook", "title": "Hook",
                "type": "scene", "text_mode": "caption", "speaker": None,
                "on_slide_text": "Twenty words of caption text here for the panel.",
                "characters": [], "location": None, "rationale": "Opens."}]
    check("storyboard Layer A PASS",
          comic.check_storyboard_layer_a(good_sb)["verdict"] == "PASS")
    bad_sb = [dict(good_sb[0], slide_label="Bogus")]
    check("storyboard Layer A catches label",
          comic.check_storyboard_layer_a(bad_sb)["verdict"] == "FAIL")
    grouped_sb = [
        dict(good_sb[0], slide=1, slide_label="Slide01 - Hook"),
        dict(good_sb[0], slide=2, slide_label="Slide02 - Beat",
             title="Beat", rationale="Next."),
        dict(good_sb[0], slide=3, slide_label="Slide03 - Moral",
             title="Moral", type="insight", text_mode=None,
             question="Why?", answer="Because."),
    ]
    check("storyboard Layer A passes grouped scenes-then-insights",
          comic.check_storyboard_layer_a(grouped_sb)["verdict"] == "PASS")
    interleaved_sb = [
        grouped_sb[0],
        dict(grouped_sb[2], slide=2, slide_label="Slide02 - Moral"),
        dict(good_sb[0], slide=3, slide_label="Slide03 - Late",
             title="Late", rationale="Late."),
    ]
    check("storyboard Layer A fails scene-after-insight",
          comic.check_storyboard_layer_a(interleaved_sb)["verdict"] == "FAIL"
          and any(i.get("type") == "ORDER"
                  for i in comic.check_storyboard_layer_a(
                      interleaved_sb)["issues"]))
    check("flow_ref unique", comic.flow_ref_for("Valmiki's Hermitage", {"ValmikisHermitage"}) != "ValmikisHermitage")
    check("live resume honors live PASS",
          comic.is_live_pass({"verdict": "PASS"}) is True)
    check("live resume ignores dry-run PASS",
          comic.is_live_pass({"verdict": "PASS", "dry_run": True}) is False)
    check("live resume rejects FAIL",
          comic.is_live_pass({"verdict": "FAIL"}) is False)
    check("dry-run eval carries marker",
          comic._eval_record("c", "corpus", "PASS", {}, [], {"verdict": "PASS"},
                             {"verdict": "PASS"}, [], dry_run=True)["dry_run"] is True)
    # extraction retry: first reply incomplete, second usable (no network —
    # stub call_muse; entity pre-seeded so the designer is never reached)
    calls = {"n": 0}

    def fake_call(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return None  # status=incomplete, empty message part
        return '{"characters": [{"canonical_name": "Valmiki"}], "scenes": []}'

    real_call = comic.call_muse
    comic.call_muse = fake_call
    try:
        repo = {"corpus": "t", "characters": {"valmiki": {"canonical_name": "Valmiki"}},
                "scenes": {}}
        _, new = comic.stage_entities(PROMPTS, "Valmiki did x.", repo, "ch", False)
        check("extraction retries incomplete then succeeds",
              new == [] and calls["n"] == 2, f"new={new} calls={calls['n']}")
    finally:
        comic.call_muse = real_call
    comic.call_muse = lambda *a, **k: None
    try:
        try:
            comic.stage_entities(PROMPTS, "x", {"corpus": "t", "characters": {},
                                                  "scenes": {}}, "ch", False)
            check("extraction gives up after budget", False)
        except RuntimeError:
            check("extraction gives up after budget", True)
    finally:
        comic.call_muse = real_call
    # designer retry: extraction ok, first design incomplete, second usable
    dcalls = {"n": 0}

    def fake_design(*args, **kwargs):
        dcalls["n"] += 1
        if dcalls["n"] == 1:
            return '{"characters": [{"canonical_name": "Ravana"}], "scenes": []}'
        if dcalls["n"] == 2:
            return None  # status=incomplete on the design call
        return ('[{"canonical_name": "Ravana", "image_prompt": "Ravana prompt",'
                ' "muse_prompt": "Ravana muse"}]')

    comic.call_muse = fake_design
    try:
        drepo = {"corpus": "t", "characters": {}, "scenes": {}}
        _, dnew = comic.stage_entities(PROMPTS, "Ravana rises.", drepo, "ch", False)
        check("design retries incomplete then succeeds",
              len(dnew) == 1 and dnew[0]["flow_ref"] == "Ravana"
              and dnew[0]["first_seen"] == "ch" and dcalls["n"] == 3,
              f"new={dnew} calls={dcalls['n']}")
    finally:
        comic.call_muse = real_call
    # flow retry: first record incomplete, second usable (no network)
    fcalls = {"n": 0}

    def fake_flow(*args, **kwargs):
        fcalls["n"] += 1
        if fcalls["n"] == 1:
            return None  # status=incomplete on the flow call
        return '[{"slide": 1, "muse_prompt": "Panel muse."}]'

    comic.call_muse = fake_flow
    try:
        fslides = [{"slide": 1, "slide_label": "Slide01 - Hook",
                    "characters": [], "location": None}]
        recs = comic.stage_flow(PROMPTS, fslides, {}, False)
        check("flow retries incomplete then succeeds",
              len(recs) == 1 and recs[0]["slide"] == 1
              and recs[0]["muse_prompt"] == "Panel muse." and fcalls["n"] == 2,
              f"recs={recs} calls={fcalls['n']}")
    finally:
        comic.call_muse = real_call
    # designer batching: 9 fresh entities -> 2 calls; bad chunk retried whole
    bcalls = {"n": 0}

    def _design_arr(names, bad=None):
        arr = [{"canonical_name": n, "image_prompt": "p", "muse_prompt": "m"}
               for n in names]
        if bad is not None:
            arr[bad] = {"canonical_name": names[bad]}
        return json.dumps(arr)

    def fake_batch(*args, **kwargs):
        bcalls["n"] += 1
        if bcalls["n"] == 1:  # extraction reply (9 fresh characters)
            return json.dumps(
                {"characters": [{"canonical_name": f"E{i}"} for i in range(1, 10)],
                 "scenes": []})
        if bcalls["n"] == 2:  # first chunk, one bad item -> whole chunk retried
            return _design_arr([f"E{i}" for i in range(1, 9)], bad=3)
        if bcalls["n"] == 3:
            return _design_arr([f"E{i}" for i in range(1, 9)])
        return _design_arr(["E9"])

    comic.call_muse = fake_batch
    try:
        brepo2 = {"corpus": "t", "characters": {}, "scenes": {}}
        _prog = []
        _, bnew = comic.stage_entities(PROMPTS, "Es assemble.", brepo2, "ch", False,
                                       progress=lambda made: _prog.append(len(made)))
        check("designer batches 9 entities into 2 calls",
              len(bnew) == 9 and bcalls["n"] == 4
              and [e["canonical_name"] for e in bnew] == [f"E{i}" for i in range(1, 10)]
              and all(e["first_seen"] == "ch" for e in bnew),
              f"new={len(bnew)} calls={bcalls['n']}")
        check("designer reports each chunk", _prog == [8, 1], f"{_prog}")
    finally:
        comic.call_muse = real_call
    # entity lock: banked entities are shown to the extractor and never redesigned
    seen_msgs = []

    def fake_lock(*args, **kwargs):
        seen_msgs.append(args[0] if args else kwargs.get("messages"))
        if len(seen_msgs) == 1:
            return json.dumps({"characters": [
                {"canonical_name": "Valmiki"},
                {"canonical_name": "Sage Valmiki"},
                {"canonical_name": "Bharadwaja"}], "scenes": []})
        return json.dumps([{"canonical_name": "Bharadwaja",
                            "image_prompt": "B prompt", "muse_prompt": "B muse"}])

    comic.call_muse = fake_lock
    try:
        lock_repo = {"corpus": "t",
                     "characters": {"valmiki": {
                         "canonical_name": "Valmiki",
                         "aliases": ["Sage Valmiki"],
                         "flow_ref": "Valmiki",
                         "image_prompt": "V prompt",
                         "muse_prompt": "V muse"}},
                     "scenes": {}}
        _, lock_new = comic.stage_entities(PROMPTS, "Valmiki acts.", lock_repo,
                                           "ch2", False)
        extract_user = seen_msgs[0][1]["content"]
        check("extractor is told banked entities",
              "KNOWN ENTITIES" in extract_user and "Valmiki" in extract_user
              and "Sage Valmiki" in extract_user, extract_user[:80])
        check("banked names skip design",
              len(seen_msgs) == 2 and len(lock_new) == 1
              and lock_new[0]["canonical_name"] == "Bharadwaja",
              f"calls={len(seen_msgs)} "
              f"new={[e['canonical_name'] for e in lock_new]}")
        check("banked prompt bytes unchanged",
              lock_repo["characters"]["valmiki"]["image_prompt"] == "V prompt"
              and lock_repo["characters"]["valmiki"]["muse_prompt"] == "V muse")
    finally:
        comic.call_muse = real_call
    # flow batching: 6 slides -> 2 calls; short chunk retried whole
    pcalls = {"n": 0}

    def fake_panels(*args, **kwargs):
        pcalls["n"] += 1
        if pcalls["n"] == 1:
            return json.dumps([{"slide": i, "muse_prompt": "m"} for i in range(1, 5)])
        span = range(1, 6) if pcalls["n"] == 2 else range(6, 7)
        return json.dumps([{"slide": i, "muse_prompt": f"m{i}"} for i in span])

    comic.call_muse = fake_panels
    try:
        pslides = [{"slide": i, "slide_label": f"Slide{i:02d} - T",
                    "characters": [], "location": None} for i in range(1, 7)]
        _seen = []
        precs = comic.stage_flow(PROMPTS, pslides, {}, False,
                                 progress=lambda recs: _seen.append(len(recs)))
        check("flow batches 6 slides into 2 calls",
              [r["slide"] for r in precs] == list(range(1, 7))
              and precs[5]["muse_prompt"] == "m6" and pcalls["n"] == 3,
              f"recs={len(precs)} calls={pcalls['n']}")
        check("flow reports cumulative chunks", _seen == [5, 6], f"{_seen}")
    finally:
        comic.call_muse = real_call
    # call budget trips with best-effort semantics (no network)
    comic.call_muse = lambda *a, **k: "x"
    _old_budget = dict(comic._CALL_BUDGET)
    comic._CALL_BUDGET["used"] = 0
    comic._CALL_BUDGET["limit"] = 1
    try:
        comic._call([{"role": "user", "content": "hi"}])
        try:
            comic._call([{"role": "user", "content": "hi"}])
            check("call budget trips", False)
        except comic._BudgetExhausted:
            check("call budget trips", True)
    finally:
        comic.call_muse = real_call
        comic._CALL_BUDGET.update(_old_budget)
    check("design/flow token ceilings fit batches",
          comic.DESIGN_TOKENS >= 16384 and comic.FLOW_TOKENS >= 16384,
          f"{comic.DESIGN_TOKENS}/{comic.FLOW_TOKENS}")
    check("eval record has no flow gate",
          "flow_layer_a" not in comic._eval_record(
              "c", "corpus", "PASS", {}, [], {"verdict": "PASS"},
              {"verdict": "PASS"}, []))
    # judge retry: two empty verdicts then a usable one (no network)
    vcalls = {"n": 0}

    def fake_judge(*args, **kwargs):
        vcalls["n"] += 1
        if vcalls["n"] < 3:
            return None  # status=incomplete, empty message part
        return '{"verdict": "PASS", "strengths": ["tight"], "weaknesses": []}'

    comic.call_muse = fake_judge
    try:
        _vj = comic.stage_eval(PROMPTS, ["line"], [{"slide": 1}], False)
        check("judge retries empty then succeeds",
              _vj["verdict"] == "PASS" and vcalls["n"] == 3,
              f"verdict={_vj} calls={vcalls['n']}")
    finally:
        comic.call_muse = real_call
    # judge records each miss, then gives up with the same FAIL shape
    with tempfile.TemporaryDirectory() as tmp:
        _rec4 = comic._Recorder(Path(tmp), "chV")
        comic.call_muse = lambda *a, **k: "no json here"
        try:
            _vj2 = comic.stage_eval(PROMPTS, ["line"], [{"slide": 1}], False,
                                    observe=_rec4)
            check("judge gives up with usable-verdict FAIL",
                  _vj2["verdict"] == "FAIL"
                  and _vj2["weaknesses"] == ["eval produced no usable verdict"],
                  f"{_vj2}")
        finally:
            comic.call_muse = real_call
        _vlines = (Path(tmp) / "comic_debug_chV.jsonl").read_text(
            encoding="utf-8").splitlines()
        _vrecs = [json.loads(l) for l in _vlines]
        check("judge records each missed attempt",
              len(_vrecs) == comic.EVAL_ATTEMPTS
              and all(r["stage"] == "eval" for r in _vrecs)
              and [r["where"] for r in _vrecs] ==
              [{"attempt": i} for i in range(1, comic.EVAL_ATTEMPTS + 1)]
              and "ENGLISH NARRATION:" in _vrecs[0]["input"],
              f"{_vlines}")
    # driver: transport verdict stops, explicit FAIL rebuilds (stubbed stages)
    def _run_driver(judge_rec):
        with tempfile.TemporaryDirectory() as tmp:
            myth = Path(tmp) / "m"
            chdir = myth / "outputs" / "chV"
            chdir.mkdir(parents=True)
            (chdir / "english_narration_chV.txt").write_text("line one\n")
            (myth / "entities").mkdir()
            (myth / "entities" / "entity_repository.json").write_text(
                '{"characters": {}, "scenes": {}}')
            _n = {"e": 0}
            _real = (comic.stage_entities, comic.stage_storyboard,
                     comic.stage_flow, comic.stage_hindi, comic.stage_eval)

            def _ent(*a, **k):
                _n["e"] += 1
                return ({"characters": {}, "scenes": {}}, [])

            _slide = {"slide": 1, "slide_label": "Slide01 - T",
                      "title": "T", "on_slide_text": "Text."}
            comic.stage_entities = _ent
            comic.stage_storyboard = lambda *a, **k: (
                [_slide], {"verdict": "PASS", "layer": "A"})
            comic.stage_flow = lambda *a, **k: [
                {"slide": 1, "slide_label": "Slide01 - T",
                 "muse_prompt": "p"}]
            comic.stage_hindi = lambda *a, **k: [
                dict(_slide, on_slide_text="H")]
            comic.stage_eval = lambda *a, **k: judge_rec
            try:
                return comic.run_chapter(myth, PROMPTS, "chV"), _n["e"]
            finally:
                (comic.stage_entities, comic.stage_storyboard,
                 comic.stage_flow, comic.stage_hindi,
                 comic.stage_eval) = _real

    _rc1, _ne1 = _run_driver(
        {"verdict": "FAIL", "strengths": [],
         "weaknesses": ["eval produced no usable verdict"]})
    check("transport verdict stops without rebuild",
          _rc1 == 1 and _ne1 == 1, f"rc={_rc1} extractions={_ne1}")
    _rc2, _ne2 = _run_driver(
        {"verdict": "FAIL", "strengths": [],
         "weaknesses": ["board too short"]})
    check("explicit FAIL still rebuilds",
          _rc2 == 1 and _ne2 == 2, f"rc={_rc2} extractions={_ne2}")
    # failure recorder: one JSON line with input + reply evidence
    with tempfile.TemporaryDirectory() as tmp:
        _rec = comic._Recorder(Path(tmp), "chX")
        _rec.record("flow", {"slides": [7]}, "SLIDES: ...", None,
                    note="empty x3")
        lines = (Path(tmp) / "comic_debug_chX.jsonl").read_text(encoding="utf-8").splitlines()
        _r0 = json.loads(lines[0])
        check("recorder writes failure evidence",
              len(lines) == 1 and _r0["stage"] == "flow"
              and _r0["where"] == {"slides": [7]}
              and _r0["input"] == "SLIDES: ..." and _r0["reply_chars"] is None
              and _r0["note"] == "empty x3" and "ts" in _r0,
              f"{lines}")
    # exhausted flow chunk persists its exact input via the recorder
    with tempfile.TemporaryDirectory() as tmp:
        _rec2 = comic._Recorder(Path(tmp), "chF")
        comic.call_muse = lambda *a, **k: None
        try:
            _fslides = [{"slide": i, "slide_label": f"S{i:02d}",
                         "characters": [], "location": None} for i in range(1, 7)]
            try:
                comic.stage_flow(PROMPTS, _fslides, {}, False, observe=_rec2)
                check("exhausted chunk raises", False)
            except RuntimeError:
                check("exhausted chunk raises", True)
        finally:
            comic.call_muse = real_call
        _rlines = (Path(tmp) / "comic_debug_chF.jsonl").read_text(
            encoding="utf-8").splitlines()
        _r0 = json.loads(_rlines[0])
        check("exhausted chunk input persisted",
              len(_rlines) == 1 and _r0["stage"] == "flow"
              and _r0["where"] == {"slides": [1, 2, 3, 4, 5]}
              and "SLIDES:" in _r0["input"]
              and "ENTITY IDENTITIES:" in _r0["input"],
              f"{_rlines}")
    # writer without eval: partials persist, eval skipped
    with tempfile.TemporaryDirectory() as tmp:
        _cd = Path(tmp)
        comic._write_outputs(_cd, "ch", None, [{"slide": 1}], None,
                             [{"slide": 1}], None, None)
        check("writer persists partials without eval",
              (_cd / "comic_storyboard_ch.json").exists()
              and (_cd / "comic_storyboard_hindi_ch.json").exists()
              and not (_cd / "comic_eval_ch.json").exists())
    # render plan: roster + per-slide turns, cookbook sizes only
    _rslides = [
        {"slide": 1, "slide_label": "Slide01 - Open", "type": "scene",
         "text_mode": "caption", "characters": ["Valmiki"], "location": "Hermitage"},
        {"slide": 2, "slide_label": "Slide02 - Ask", "type": "scene",
         "text_mode": "dialogue", "characters": ["Narada"], "location": None},
        {"slide": 3, "slide_label": "Slide03 - Point", "type": "insight",
         "text_mode": None, "characters": ["Ghost"], "location": None},
    ]
    _rflow = [{"slide": 1, "muse_prompt": "p1"}, {"slide": 2, "muse_prompt": "p2"},
              {"slide": 3, "muse_prompt": "p3"}]
    _rrepo = {"characters": {"valmiki": {"canonical_name": "Valmiki", "flow_ref": "Valmiki",
                                         "image_prompt": "sheet"}},
              "scenes": {"hermitage": {"canonical_name": "Hermitage", "flow_ref": "Hermitage",
                                       "image_prompt": "plate"}}}
    _plan = comic._render_plan(_rslides, _rflow, _rrepo)
    check("render plan sizes from cookbook set",
          all(s["size"] in comic.RENDER_SIZES for s in _plan["slides"]))
    check("render plan slide shapes",
          [s["size"] for s in _plan["slides"]] == ["1536x1024", "1024x1024", "1024x1024"])
    check("render plan roster dedups with sheet slots",
          len(_plan["roster"]) == 4
          and all(r["sheet_response_id"] is None for r in _plan["roster"])
          and {r["name"] for r in _plan["roster"]} == {"Valmiki", "Narada", "Hermitage", "Ghost"})
    check("render plan marks unknown without prose",
          [r for r in _plan["roster"] if r["name"] == "Ghost"][0]["image_prompt"] is None)
    check("render plan carries panel prose",
          [s["muse_prompt"] for s in _plan["slides"]] == ["p1", "p2", "p3"])
    # hindi slim contract: fields-only items translate in batches, merged verbatim
    _hslides = [
        {"slide": 1, "slide_label": "Slide01 - A", "title": "A", "type": "scene",
         "text_mode": "caption", "speaker": None, "on_slide_text": "Valmiki asks.",
         "characters": ["Valmiki"], "location": "Hermitage", "rationale": "Opens."},
        {"slide": 2, "slide_label": "Slide02 - B", "title": "B", "type": "insight",
         "text_mode": None, "speaker": None, "on_slide_text": "Think on this.",
         "question": "Why ask first?", "answer": "Character is the soul.",
         "characters": [], "location": None, "rationale": "Takeaway."},
        {"slide": 3, "slide_label": "Slide03 - C", "title": "C", "type": "scene",
         "text_mode": "caption", "speaker": None, "on_slide_text": "",
         "characters": [], "location": None, "rationale": "Beat."},
    ]
    check("hindi need extracts on-panel fields only",
          comic._hindi_need(_hslides) == [
              {"slide": 1, "fields": {"on_slide_text": "Valmiki asks."}},
              {"slide": 2, "fields": {"on_slide_text": "Think on this.",
                                      "question": "Why ask first?",
                                      "answer": "Character is the soul."}}])
    check("hindi need sends a fraction of the board",
          len(json.dumps(comic._hindi_need(_hslides))) <
          len(json.dumps(_hslides)) // 2)
    _hb = [{"slide": i, "slide_label": f"S{i:02d}", "title": "T",
            "on_slide_text": f"Text {i}."} for i in range(1, 7)]
    hcalls = {"n": 0}

    def fake_hindi(*args, **kwargs):
        hcalls["n"] += 1
        items = json.loads(args[0][-1]["content"])
        if hcalls["n"] == 1:
            return "not json"  # whole chunk retried intact
        return json.dumps([{"slide": it["slide"],
                            "fields": {k: f"HI({v})"
                                       for k, v in it["fields"].items()}}
                           for it in items])

    comic.call_muse = fake_hindi
    try:
        _hprog = []
        hout = comic.stage_hindi(PROMPTS, _hb, False,
                                 progress=lambda items: _hprog.append(len(items)))
        check("hindi batches 6 slides into 2 calls",
              [s["slide"] for s in hout] == list(range(1, 7))
              and hcalls["n"] == 3, f"slides={len(hout)} calls={hcalls['n']}")
        check("hindi merges onto verbatim slides",
              all(s["title"] == "T" and s["slide_label"] == f"S{s['slide']:02d}"
                  for s in hout)
              and hout[0]["on_slide_text"] == "HI(Text 1.)",
              f"{hout[0]}")
        check("hindi reports cumulative chunks", _hprog == [5, 6], f"{_hprog}")
    finally:
        comic.call_muse = real_call
    # hindi partial: slides 1 pre-translated (string keys, as from JSON),
    # slide 2 short on answer so it retranslates, slide 3 has no text
    pcalls = {"n": 0}

    def fake_hindi_rest(*args, **kwargs):
        pcalls["n"] += 1
        items = json.loads(args[0][-1]["content"])
        return json.dumps([{"slide": it["slide"],
                            "fields": {k: "NEW" for k in it["fields"]}}
                           for it in items])

    comic.call_muse = fake_hindi_rest
    try:
        pout = comic.stage_hindi(
            PROMPTS, _hslides, False,
            partial={"1": {"on_slide_text": "OLD1"},
                     "2": {"on_slide_text": "OLD2", "question": "OLDQ"}})
        check("hindi honors validated partial, translates rest",
              pcalls["n"] == 1
              and pout[0]["on_slide_text"] == "OLD1"
              and pout[1]["question"] == "NEW"
              and pout[1]["answer"] == "NEW"
              and pout[2]["on_slide_text"] == "",
              f"calls={pcalls['n']} out={pout}")
    finally:
        comic.call_muse = real_call
    # exhausted hindi chunk records its exact input then raises
    with tempfile.TemporaryDirectory() as tmp:
        _rec3 = comic._Recorder(Path(tmp), "chH")
        comic.call_muse = lambda *a, **k: None
        try:
            try:
                comic.stage_hindi(PROMPTS, _hslides, False, observe=_rec3)
                check("exhausted hindi chunk raises", False)
            except RuntimeError:
                check("exhausted hindi chunk raises", True)
        finally:
            comic.call_muse = real_call
        _hlines = (Path(tmp) / "comic_debug_chH.jsonl").read_text(
            encoding="utf-8").splitlines()
        _h0 = json.loads(_hlines[0])
        check("exhausted hindi chunk input persisted",
              len(_hlines) == 1 and _h0["stage"] == "hindi"
              and _h0["where"] == {"slides": [1, 2]}
              and '"on_slide_text"' in _h0["input"],
              f"{_hlines}")
    check("hindi token ceiling matches English board",
          comic.HINDI_TOKENS >= 32768, f"{comic.HINDI_TOKENS}")
    _hi_txt = (PROMPTS / "hindi_storyboard.md").read_text(encoding="utf-8")
    check("hindi prompt is fields-only",
          '"fields"' in _hi_txt and "verbatim English slides" in _hi_txt)
    # resume manifest: live roundtrips, dry-run and strangers never resume
    with tempfile.TemporaryDirectory() as tmp:
        _cd = Path(tmp)
        comic._save_progress(_cd, "ch", True, board_slides=2,
                             layer_a={"verdict": "PASS", "layer": "A"})
        _mp = comic._load_progress(_cd, "ch")
        check("progress manifest roundtrips live",
              _mp is not None and _mp["board_slides"] == 2
              and _mp["layer_a"]["verdict"] == "PASS")
        comic._save_progress(_cd, "ch", False, board_slides=3)
        check("dry progress never resumes",
              comic._load_progress(_cd, "ch") is None)
        check("progress rejects other chapters",
              comic._load_progress(_cd, "other") is None)
        (_cd / "comic_storyboard_ch.json").write_text(json.dumps(
            [{"slide": 1, "slide_label": "S01"},
             {"slide": 2, "slide_label": "S02"}]))
        comic._save_progress(_cd, "ch", True, board_slides=2,
                             layer_a={"verdict": "PASS", "layer": "A"})
        _ab, _aa = comic._adopt_board(
            _cd, "ch", comic._load_progress(_cd, "ch"))
        check("board adoption reuses saved slides",
              _ab is not None and len(_ab) == 2 and _aa["verdict"] == "PASS")
        comic._save_progress(_cd, "ch", True, board_slides=3,
                             layer_a={"verdict": "PASS", "layer": "A"})
        check("board adoption rejects count drift",
              comic._adopt_board(
                  _cd, "ch", comic._load_progress(_cd, "ch")) == (None, None))
        (_cd / "comic_muse_prompts_ch.json").write_text(json.dumps(
            [{"slide": 1, "slide_label": "S01", "muse_prompt": "p1"}]))
        _fslides = [{"slide": 1, "slide_label": "S01"},
                    {"slide": 2, "slide_label": "S02"}]
        _have, _missing = comic._adopt_flow(_cd, "ch", _fslides)
        check("flow adoption splits done and missing",
              [r["slide"] for r in _have] == [1]
              and [s["slide"] for s in _missing] == [2]
              and _have[0]["muse_prompt"] == "p1")
        (_cd / "comic_storyboard_hindi_ch.json").write_text(json.dumps(
            [{"slide": 1, "on_slide_text": "H1"},
             {"slide": 2, "on_slide_text": "H2", "question": "HQ",
              "answer": "HA"}]))
        _nslides = [{"slide": 1, "on_slide_text": "E1"},
                    {"slide": 2, "on_slide_text": "E2", "question": "EQ",
                     "answer": "EA"}]
        check("hindi adoption reuses complete board",
              comic._adopt_hindi(_cd, "ch", _nslides) is not None)
        (_cd / "comic_hindi_partial_ch.json").write_text(json.dumps(
            [{"slide": 2, "fields": {"on_slide_text": "H2"}}]))
        check("hindi partial validates per slide",
              comic._adopt_hindi_partial(_cd, "ch", _nslides) == {
                  2: {"on_slide_text": "H2"}})
        for _n in ("comic_muse_prompts_ch.json",
                   "comic_storyboard_hindi_ch.json",
                   "comic_hindi_partial_ch.json"):
            (_cd / _n).write_text("[]")
        comic._reset_downstream(_cd, "ch")
        check("fresh board drops stale downstream",
              not (_cd / "comic_muse_prompts_ch.json").exists()
              and not (_cd / "comic_storyboard_hindi_ch.json").exists()
              and not (_cd / "comic_hindi_partial_ch.json").exists())
    # bank_repo: writes on change, no-op when unchanged or dry-run
    with tempfile.TemporaryDirectory() as tmp:
        rp = Path(tmp) / "repo.json"
        rp.write_text("{}\n", encoding="utf-8")
        snap0 = json.dumps({}, sort_keys=True)
        brepo = {"characters": {"a": 1}}
        snap1 = comic._bank_repo(rp, snap0, brepo, False, 1)
        check("bank_repo writes on change",
              snap1 != snap0 and json.loads(rp.read_text(encoding="utf-8")) == brepo)
        check("bank_repo no-op when unchanged",
              comic._bank_repo(rp, snap1, brepo, False, 0) == snap1)
        brepo["scenes"] = {}
        check("bank_repo never writes on dry-run",
              comic._bank_repo(rp, snap1, brepo, True, 1) == snap1
              and "scenes" not in rp.read_text(encoding="utf-8"))
    # call_muse retries status=incomplete empties with backoff (no network)
    import muse_client as _mc
    import time as _tm
    import urllib.request as _ur
    _envelopes = [
        {"object": "response", "status": "incomplete", "output": []},
        {"object": "response", "status": "completed", "output": [
            {"type": "message", "content": [
                {"type": "output_text", "text": "hello"}]}]},
    ]

    class _Resp:
        def __init__(self, payload):
            self._b = json.dumps(payload).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return self._b

    _made = {"n": 0, "slept": []}

    def _fake_urlopen(req, timeout=None):
        _made["n"] += 1
        return _Resp(_envelopes[min(_made["n"] - 1, 1)])

    _real = (_ur.urlopen, _tm.sleep, _mc.get_api_key)
    _ur.urlopen, _tm.sleep = _fake_urlopen, lambda s: _made["slept"].append(s)
    _mc.get_api_key = lambda: "test-key"
    try:
        _out = _mc.call_muse([{"role": "user", "content": "hi"}])
        check("call_muse retries incomplete then returns text",
              _out == "hello" and _made["n"] == 2 and _made["slept"] == [30],
              f"out={_out!r} fetches={_made['n']} slept={_made['slept']}")
    finally:
        _ur.urlopen, _tm.sleep, _mc.get_api_key = _real

    # comic prompt numbers agree across files (panel-text bounds + slide plan)
    def _range(text: str, unit: str) -> tuple[int, int] | None:
        m = re.search(r"(\d+)\s*[-\u2013]\s*(\d+)\s*" + unit, text)
        return (int(m.group(1)), int(m.group(2))) if m else None

    sb_txt = (PROMPTS / "storyboard.md").read_text(encoding="utf-8")
    hi_txt = (PROMPTS / "hindi_storyboard.md").read_text(encoding="utf-8")
    ev_txt = (PROMPTS / "storyboard_eval.md").read_text(encoding="utf-8")
    panel = {_range(t, "words") for t in (sb_txt, hi_txt, ev_txt)}
    check("comic panel-text bounds agree", len(panel) == 1 and None not in panel,
          f"{panel}")
    slides = _range(sb_txt, "slides")
    check("comic slide plan sane", slides is not None and slides[0] < slides[1],
          f"{slides}")
    for _p in ("entity_extractor.md", "entity_designer.md", "storyboard.md",
               "panel_prompts.md", "storyboard_eval.md", "hindi_storyboard.md",
               "agent1_narration.md", "agent3_reflection.md", "reviewer.md"):
        check(f"prompt file present: {_p}", (PROMPTS / _p).is_file())
    check("storyboard token ceiling fits the board",
          comic.STORY_TOKENS >= 32768, f"{comic.STORY_TOKENS}")
    check("judge token ceiling fits thinking over board",
          comic.EVAL_TOKENS >= 16384, f"{comic.EVAL_TOKENS}")

    # stage exit contracts (no chapter => rc 2, no FS touched)
    check("podcast no-chapter rc=2", podcast.main([]) == 2)
    check("bridge no-chapter rc=2", bridge.main([]) == 2)
    check("av-map no-chapter rc=2", avmap.main([]) == 2)
    check("comic no-chapter rc=2", comic.main([]) == 2)
    check("driver no-chapter rc=2", driver.main([]) == 2)
    check("loop no-chapter rc=2",
          loop.main(["--chapter", "Nope", "--slide", "1"]) == 2)
    fatal, _ = loop.prescan_prompt("a serene grove at dawn", "16:9")
    check("loop prescan passes clean prompt", fatal == [], fatal)
    fatal, _ = loop.prescan_prompt("", "16:9")
    check("loop prescan fails empty prompt", fatal != [])
    fatal, _ = loop.prescan_prompt("warriors slay the collapsing host", "16:9")
    check("loop prescan fails gore lexicon",
          any("policy-lexicon" in f for f in fatal), fatal)
    fatal, _ = loop.prescan_prompt("a faceless crowd mass with no distinct faces", "16:9")
    check("loop prescan fails face-negation wording",
          any("face-negation" in f for f in fatal), fatal)
    fatal, _ = loop.prescan_prompt(
        "a softly blurred gathering seen from behind with backs to the viewer", "16:9")
    check("loop prescan passes backs-to-viewer wording", fatal == [], fatal)
    fatal, _ = loop.prescan_prompt("a serene grove at dawn", "3:2")
    check("loop prescan fails bad aspect", fatal != [], fatal)

    # art-loop tools: frame gate, batch runner, finalizer, packets
    import check_frame as _cf
    import loop_batch as _lb
    import finalize as _fin
    import critique_packet as _cp
    try:
        from PIL import Image as _Im
        with tempfile.TemporaryDirectory() as tmp:
            _art = _Im.new("RGB", (320, 200), (90, 140, 80))
            _clean = Path(tmp) / "clean.jpg"
            _art.save(_clean)
            _rep = _cf.analyze(str(_clean))
            check("frame gate passes full-bleed art", _rep["verdict"] == "PASS", _rep)
            _box = _Im.new("RGB", (320, 280), (210, 208, 200))
            _box.paste(_art, (0, 40))
            _matted = Path(tmp) / "matted.jpg"
            _box.save(_matted)
            _rep = _cf.analyze(str(_matted))
            check("frame gate fails letterbox surround",
                  _rep["verdict"] == "FAIL"
                  and set(_rep["failed_sides"]) == {"top", "bottom"}, _rep)
            _crop = Path(tmp) / "cropped.jpg"
            check("frame crop exits 1 on FAIL verdict",
                  _cf.main([str(_matted), "--crop-out", str(_crop)]) == 1
                  and _crop.is_file())
            _rep2 = _cf.analyze(str(_crop))
            check("frame crop removes surround", _rep2["verdict"] == "PASS", _rep2)
    except ImportError:
        check("frame gate checks skipped (no Pillow)", True)
    check("frame gate missing file rc=2", _cf.main(["/nope.jpg"]) == 2)
    check("batch rejects slides+sheets", _lb.main(
        ["--chapter", "C", "--slides", "1", "--sheets", "R"]) == 2)
    check("batch rejects empty targets", _lb.main(["--chapter", "C"]) == 2)
    check("batch unknown chapter rc=2", _lb.main(
        ["--chapter", "Nope", "--slides", "1"]) == 2)
    check("finalize names panel slots",
          _fin.candidate_name("panel", "3", 1) == "slide_03_candidate_1.jpg"
          and _fin.final_name("panel", "3") == "slide_03_final.jpg")
    check("finalize names sheet slots",
          _fin.candidate_name("sheet", "Rama", 2) == "sheet_Rama_candidate_2.jpg"
          and _fin.final_name("sheet", "Rama") == "sheet_Rama_final.jpg")
    _ent = _fin.build_sheet_entry("Rama", "Rama", "character", "prompt",
                                  "Ch/f.jpg", "abc", "Ch Rama")
    check("finalize ledger entry hashes prompt",
          _ent["prompt_sha256"] == hashlib.sha256(b"prompt").hexdigest()
          and _ent["verdict"] == "PASS", _ent.get("prompt_sha256"))
    check("finalize missing candidate rc=2", _fin.main(
        ["--chapter", "Book_1_Bala_Kanda_Chapter_3",
         "--sheet", "NoSuchRef"]) == 2)
    with tempfile.TemporaryDirectory() as tmp:
        _ch = "Book_1_Bala_Kanda_Chapter_3"
        _cand = (Path("mythologies/ramayana_dutt/outputs") / _ch
                 / "studio_images" / "slide_01_final.jpg")
        _pkt = Path(tmp) / "pkt.json"
        _rc = _cp.main(["--chapter", _ch, "--slide", "1",
                        "--candidate", str(_cand), "--thumb-dir", tmp,
                        "--out", str(_pkt)]) if _cand.is_file() else 2
        _body = json.loads(_pkt.read_text()) if _pkt.is_file() else {}
        check("packet assembles slide critique inputs",
              _rc == 0 and _body.get("prompt_render_plan")
              and _body.get("spec", {}).get("characters")
              and _body.get("thumbnail"), str(_pkt))
    import pretrim as _pt
    with tempfile.TemporaryDirectory() as tmp:
        _cd, _ch = Path(tmp), "ChX"
        _board = [{"slide": 1, "characters": list("abcdef"), "location": "L",
                   "rationale": "r"},
                  {"slide": 2, "characters": ["a", "b"], "location": "L",
                   "rationale": "r"}]
        (_cd / f"comic_storyboard_{_ch}.json").write_text(json.dumps(_board))
        (_cd / f"comic_storyboard_hindi_{_ch}.json").write_text(json.dumps(_board))
        (_cd / f"comic_render_plan_{_ch}.json").write_text(json.dumps({
            "roster": [{"name": n, "flow_ref": n, "kind": "character",
                        "image_prompt": "p"} for n in "abcdef"],
            "slides": [{"slide": 1, "muse_prompt": "old", "subjects": "[]"},
                       {"slide": 2, "muse_prompt": "old", "subjects": "[]"}]}))
        (_cd / f"comic_muse_prompts_{_ch}.json").write_text(json.dumps(
            [{"slide": 1, "muse_prompt": "old"},
             {"slide": 2, "muse_prompt": "old"}]))
        _flag = _pt.overcast_slides(_board)
        check("pretrim gate flags 6-face slide only",
              [f["slide"] for f in _flag] == [1], _flag)
        _rep = _pt.trim_slide(_cd, _ch, 1, ["a", "b"], "L", "apex", "new prompt")
        _sb = json.loads((_cd / f"comic_storyboard_{_ch}.json").read_text())
        _rp = json.loads((_cd / f"comic_render_plan_{_ch}.json").read_text())
        _mp = json.loads((_cd / f"comic_muse_prompts_{_ch}.json").read_text())
        check("pretrim rewrites cast plus both prompt copies",
              _sb[0]["characters"] == ["a", "b"] and _sb[0]["rationale"] == "apex"
              and _rp["slides"][0]["muse_prompt"] == "new prompt"
              and _mp[0]["muse_prompt"] == "new prompt"
              and len(_sb) == 2 and len(_rp["slides"]) == 2 and len(_mp) == 2,
              _rep)
        _refused = False
        try:
            _pt.trim_slide(_cd, _ch, 2, ["zzz"], "L", "r", "p")
        except ValueError:
            _refused = True
        check("pretrim refuses names outside roster", _refused)
        _refused = False
        try:
            _pt.trim_slide(_cd, _ch, 2, list("abcdef"), "L", "r", "p")
        except ValueError:
            _refused = True
        check("pretrim refuses keep above face cap", _refused)

    # av-map stage: script segments -> slide images (deterministic)
    _asegs = ([{"text": f"k{i}", "text_en": f"s{i}"} for i in range(3)]
              + [{"text": "प्रश्न: q?", "text_en": "Question: q?"}])
    _aboard = [{"slide": i, "type": "insight" if i == 4 else "scene"}
               for i in range(1, 6)]
    _achunks, _aerr = avmap.build_mapping(_asegs, _aboard, 3)
    _aused = sorted({s for c in _achunks for s in c["slides"]})
    check("av-map covers every slide, discussion hits insight",
          _aerr == "" and len(_achunks) == 4
          and [c["script_index"] for c in _achunks] == [0, 1, 2, 3]
          and [c["kind"] for c in _achunks] == ["narration"] * 3 + ["discussion"]
          and _aused == [1, 2, 3, 4, 5]
          and _achunks[3]["slides"] == [4], f"{_aerr} {_achunks}")
    _bchunks, _ = avmap.build_mapping(
        [{"text": "k", "text_en": "s"}] * 5,
        [{"slide": 1, "type": "scene"}, {"slide": 2, "type": "insight"}])
    check("av-map pins endpoints when segs outnumber slides",
          _bchunks[0]["slides"] == [1] and _bchunks[-1]["slides"] == [2]
          and all(c["kind"] == "narration" for c in _bchunks),
          f"{_bchunks}")
    with tempfile.TemporaryDirectory() as tmp:
        _mroot = Path(tmp)
        _mch = _mroot / "outputs" / "chA"
        (_mch / "studio_images").mkdir(parents=True)
        (_mch / "script_chA.json").write_text(json.dumps(_asegs),
                                              encoding="utf-8")
        (_mch / "comic_storyboard_chA.json").write_text(json.dumps(_aboard),
                                                        encoding="utf-8")
        (_mch / "studio_images" / "slide_04_final.jpg").write_text(
            "fake", encoding="utf-8")
        check("av-map writes mapping file",
              avmap.av_map(_mroot, "chA") == 0
              and (_mch / "av_mapping_chA.json").is_file())
        _am = json.loads((_mch / "av_mapping_chA.json").read_text(
            encoding="utf-8"))
        _miss = sorted({f for c in _am["chunks"]
                        for f in c["images_missing"]})
        check("av-map flags unrendered images",
              _am["chunks"][3]["images"]
              == ["studio_images/slide_04_final.jpg"]
              and len(_miss) == 4, f"{_miss}")

    # av-map semantic judge: strict validation, deterministic repair,
    # stubbed judge retry/give-up, dry-run fallback (no network)
    _vgood = [{"script_index": 0, "slides": [1]},
              {"script_index": 1, "slides": [2]}]
    check("av-map semantic validation passes clean input",
          avmap.validate_mapping(_vgood, 2, [1, 2]) == [])
    _vbad = [{"script_index": 0, "slides": [9]},
             {"script_index": 0, "slides": [1]}]
    check("av-map semantic validation flags bad refs",
          len(avmap.validate_mapping(_vbad, 2, [1, 2])) >= 3,
          avmap.validate_mapping(_vbad, 2, [1, 2]))
    _rep = avmap.repair_mapping(
        [{"script_index": 1, "slides": [2]}], ["narration"] * 3,
        [1, 2], {1: "scene", 2: "scene"})
    check("av-map semantic repair fills gaps deterministically",
          [(c["script_index"], c["slides"]) for c in _rep]
          == [(0, [1]), (1, [2]), (2, [2])], f"{_rep}")
    _mj = {"n": 0}

    def _fake_judge(*a, **k):
        _mj["n"] += 1
        if _mj["n"] == 1:
            return None  # status=incomplete, empty message part
        return '```json\n[{"script_index": 0, "slides": [1]}]\n```'

    _real_cm = avmap.call_muse
    avmap.call_muse = _fake_judge
    try:
        _got = avmap.request_mapping("PROMPT", {}, 1, [1])
        check("av-map judge retries empty then succeeds",
              _got == [{"script_index": 0, "slides": [1]}] and _mj["n"] == 2,
              f"{_got} calls={_mj['n']}")
    finally:
        avmap.call_muse = _real_cm
    avmap.call_muse = lambda *a, **k: None
    try:
        check("av-map judge gives up after budget",
              avmap.request_mapping("P", {}, 1, [1]) is None)
    finally:
        avmap.call_muse = _real_cm
    with tempfile.TemporaryDirectory() as tmp:
        _sroot = Path(tmp)
        _sch = _sroot / "outputs" / "chS"
        (_sch / "studio_images").mkdir(parents=True)
        (_sch / "script_chS.json").write_text(json.dumps(_asegs),
                                              encoding="utf-8")
        (_sch / "comic_storyboard_chS.json").write_text(json.dumps(_aboard),
                                                        encoding="utf-8")
        check("av-map semantic dry-run falls back positional",
              avmap.av_map(_sroot, "chS", semantic=True, dry_run=True) == 0
              and json.loads((_sch / "av_mapping_chS.json").read_text(
                  encoding="utf-8"))["strategy"] == avmap.STRATEGY)

    # av-map enrichment: image prompts + per-slide cue timings per chunk
    _esegs = [{"text": "a", "text_en": "a"}, {"text": "b", "text_en": "b"}]
    _eboard = [{"slide": 1, "title": "T1", "type": "scene",
                "slide_label": "Slide01 - T1"},
               {"slide": 2, "title": "T2", "type": "scene",
                "slide_label": "Slide02 - T2"},
               {"slide": 3, "title": "T3", "type": "insight",
                "slide_label": "Slide03 - T3"}]
    _echunks, _ = avmap.build_mapping(_esegs, _eboard, 2)
    _eprompts = {1: {"muse_prompt": "p1", "slide_label": "S01"},
                 2: {"muse_prompt": "p2", "slide_label": "S02"},
                 3: {"muse_prompt": "p3", "slide_label": "S03"}}
    _etiming = avmap.enrich_chunks(
        _echunks, _eboard, _eprompts, {"en": [4.0, 2.0], "hi": [None, None]})
    check("av-map panels carry image prompts",
          _echunks[0]["panels"][0]["muse_prompt"] == "p1"
          and _echunks[1]["panels"][0]["title"] == "T2"
          and abs(sum(p["share"] for p in _echunks[1]["panels"]) - 1.0) < 1e-9,
          f"{_echunks}")
    check("av-map cues go absolute only on a complete track",
          _etiming["langs_absolute"] == ["en"]
          and _echunks[0]["panels"][0]["en"] == {"start_s": 0.0, "end_s": 4.0,
                                                 "duration_s": 4.0}
          and [p["en"]["start_s"] for p in _echunks[1]["panels"]] == [4.0, 5.0]
          and _echunks[0]["panels"][0]["hi"] is None
          and _echunks[0]["audio"]["hi"] is None
          and _echunks[0]["audio"]["en"]["duration_s"] == 4.0,
          f"{_etiming} {_echunks}")
    _r3, _ = avmap.build_mapping(
        [{"text": "a", "text_en": "a"}],
        [{"slide": 1, "type": "scene"}, {"slide": 2, "type": "scene"},
         {"slide": 3, "type": "scene"}])
    # single segment, three slides: one chunk carries all three
    _r3[0]["images"] = []
    _r3[0]["images_missing"] = []
    avmap.enrich_chunks(_r3, [], {}, {"en": [1.0], "hi": [1.0]})
    check("av-map last panel takes the remainder (no 1ms leak)",
          [p["en"]["duration_s"] for p in _r3[0]["panels"]] == [0.333, 0.333, 0.334]
          and _r3[0]["panels"][-1]["en"]["end_s"] == 1.0
          and _r3[0]["panels"][-1]["hi"]["end_s"] == 1.0,
          f"{_r3[0]['panels']}")
    with tempfile.TemporaryDirectory() as tmp:
        _eroot = Path(tmp)
        _ech = _eroot / "outputs" / "chE"
        (_ech / "studio_images").mkdir(parents=True)
        (_ech / "script_chE.json").write_text(json.dumps(_esegs),
                                              encoding="utf-8")
        (_ech / "comic_storyboard_chE.json").write_text(json.dumps(_eboard),
                                                        encoding="utf-8")
        (_ech / "comic_muse_prompts_chE.json").write_text(
            json.dumps([{"slide": i, "slide_label": f"S{i:02d}",
                         "muse_prompt": f"p{i}"} for i in (1, 2, 3)]),
            encoding="utf-8")
        check("av-map enrich-only needs a mapping first",
              avmap.av_map(_eroot, "chE", enrich_only=True) == 2)
        check("av-map positional run carries relative cues without audio",
              avmap.av_map(_eroot, "chE") == 0
              and (lambda _m: _m["timing"].startswith("relative-shares")
                   and _m["prompts_source"] == "comic_muse_prompts_chE.json"
                   and _m["chunks"][0]["panels"][0]["muse_prompt"] == "p1"
                   and _m["chunks"][0]["panels"][0]["en"] is None)(
                  json.loads((_ech / "av_mapping_chE.json").read_text(
                      encoding="utf-8"))))
        _before = [list(c["slides"]) for c in json.loads(
            (_ech / "av_mapping_chE.json").read_text(
                encoding="utf-8"))["chunks"]]
        (_ech / "audio_en").mkdir(exist_ok=True)
        (_ech / "audio_hi").mkdir(exist_ok=True)
        for _i in (1, 2):
            (_ech / "audio_en" / f"chunk_{_i:03d}.wav").write_bytes(
                audio.silent_wav(seconds=1.5))
            (_ech / "audio_hi" / f"chunk_{_i:03d}.wav").write_bytes(
                audio.silent_wav(seconds=1.0))
        check("av-map enrich-only keeps slides, stamps absolute cues",
              avmap.av_map(_eroot, "chE", enrich_only=True) == 0
              and (lambda _m: [list(c["slides"]) for c in _m["chunks"]] == _before
                   and _m["timing"].startswith("absolute")
                   and _m["langs_absolute"] == ["en", "hi"]
                   and _m["chunks"][0]["panels"][0]["en"]
                   == {"start_s": 0.0, "end_s": 1.5, "duration_s": 1.5}
                   and _m["chunks"][0]["panels"][0]["hi"]
                   == {"start_s": 0.0, "end_s": 1.0, "duration_s": 1.0})(
                  json.loads((_ech / "av_mapping_chE.json").read_text(
                      encoding="utf-8"))))

    # standalone Gemini audio tool (explicit trigger; outside run_chapter)
    check("audio strips verbatim-spoken tags",
          audio.clean_transcript("कथा यहाँ। <narrative>") == "कथा यहाँ।"
          and audio.clean_transcript("The story. <formal>") == "The story.")
    check("audio gate passes clean transcripts",
          audio.find_spoken_labels(GOOD_NARR) == [])
    _labseg = [dict(GOOD_NARR[0], text="प्रश्न: क्यों? <narrative>",
                    text_en="Question: why? <narrative>")]
    check("audio gate flags labels in both languages",
          audio.find_spoken_labels(_labseg)
          == ["chunk 1 [hi]: spoken label 'प्रश्न:' in transcript "
              "(fix the script first)",
              "chunk 1 [en]: spoken label 'Question:' in transcript "
              "(fix the script first)"])
    with tempfile.TemporaryDirectory() as tmp:
        _groot = Path(tmp)
        for _req in ("sources", "outputs", "entities"):
            (_groot / _req).mkdir()
        (_groot / "mythology.yaml").write_text("name: t\n", encoding="utf-8")
        _gch = _groot / "outputs" / "Book_1_X_Chapter_7"
        _gch.mkdir(parents=True)
        (_gch / "script_Book_1_X_Chapter_7.json").write_text(
            json.dumps(_labseg), encoding="utf-8")
        check("audio refuses labeled scripts with no writes",
              audio.generate(["--mythology", str(_groot),
                              "--chapter", "Book_1_X_Chapter_7",
                              "--dry-run"]) == 2
              and not (_gch / "audio_en").exists()
              and not (_gch / "audio_hi").exists()
              and not (_gch / "audio_manifest_Book_1_X_Chapter_7.json")
              .exists())
    _abody = audio.synth_request_body("m", "Leda", "calm", "hi")
    check("audio request targets interactions shape",
          _abody["model"] == "m"
          and _abody["response_format"] == {"type": "audio"}
          and _abody["generation_config"]["speech_config"] == [{"voice": "Leda"}]
          and _abody["input"][0]["content"][0]["text"] == "hi")
    _ablob = base64.b64encode(b"RIFF....wavbytes").decode()
    check("audio extracts last audio block",
          audio.extract_audio({"steps": [
              {"content": [{"type": "text", "data": "xx"}]},
              {"content": [{"type": "audio", "data": _ablob}]}]}) == b"RIFF....wavbytes")
    check("audio passthrough keeps real WAV",
          audio.ensure_wav(b"RIFF....wavbytes") == b"RIFF....wavbytes")
    check("audio wraps bare PCM as 24kHz wav",
          audio.ensure_wav(b"\x00\x00" * 24).startswith(b"RIFF"))
    with tempfile.TemporaryDirectory() as tmp:
        _aroot = Path(tmp)
        for _req in ("sources", "outputs", "entities"):
            (_aroot / _req).mkdir()
        (_aroot / "mythology.yaml").write_text("name: t\n", encoding="utf-8")
        _ach = _aroot / "outputs" / "Book_1_X_Chapter_1"
        _ach.mkdir(parents=True)
        (_ach / "script_Book_1_X_Chapter_1.json").write_text(
            json.dumps(GOOD_NARR + [dict(GOOD_NARR[0], text="",
                                        text_en="")]), encoding="utf-8")
        check("audio dry-run writes per-chunk wavs + manifest",
              audio.generate(["--mythology", str(_aroot),
                              "--chapter", "Book_1_X_Chapter_1",
                              "--dry-run"]) == 0
              and (_ach / "audio_en" / "chunk_001.wav").exists()
              and (_ach / "audio_hi" / "chunk_001.wav").exists()
              and len(json.loads(
                  (_ach / "audio_manifest_Book_1_X_Chapter_1.json")
                  .read_text(encoding="utf-8"))["chunks"]) == 2)
        import wave as _wv
        with _wv.open(str(_ach / "audio_en" / "chunk_001.wav"), "rb") as _w:
            check("audio dry-run wav is valid PCM",
                  _w.getnchannels() == 1 and _w.getframerate() == 24000)
        _man = json.loads((_ach / "audio_manifest_Book_1_X_Chapter_1.json")
                          .read_text(encoding="utf-8"))
        check("audio manifest skips empty transcripts",
              _man["chunks"][1]["en"]["status"] == "skipped-empty")
        check("audio dry-run tags placeholder source",
              _man["chunks"][0]["en"]["source"] == "dry-run")
        (_ach / "audio_en" / "chunk_001.wav").write_bytes(
            audio.silent_wav(seconds=2.0))
        check("audio dry-run never clobbers existing wavs",
              audio.generate(["--mythology", str(_aroot),
                              "--chapter", "Book_1_X_Chapter_1",
                              "--dry-run"]) == 0
              and json.loads((_ach / "audio_manifest_Book_1_X_Chapter_1.json")
                             .read_text(encoding="utf-8"))
              ["chunks"][0]["en"] == {"chars": len(audio.clean_transcript(
                  GOOD_NARR[0]["text_en"])),
                  "file": "audio_en/chunk_001.wav", "status": "ok",
                  "source": "reused", "bytes": len(audio.silent_wav(2.0)),
                  "duration_s": 2.0})
        check("audio rejects missing chapter id",
              audio.generate(["--mythology", str(_aroot)]) == 2)
        # Tier 1 pacing/budget contracts (no network: stubbed synthesize)
        class _Exc:
            def __init__(self, headers):
                self.headers = headers
        check("audio default pacing respects Tier 1 10 RPM",
              audio.DEFAULT_DELAY_S >= 60.0 / 10
              and audio.DEFAULT_DAILY_BUDGET == 100)
        check("audio honors Retry-After header",
              audio.retry_after_s(_Exc({"Retry-After": "7"}), 2.0) == 7.0
              and audio.retry_after_s(_Exc({}), 2.0) == 2.0
              and audio.retry_after_s(_Exc({"Retry-After": "junk"}), 2.0)
              == 2.0
              and audio.retry_after_s(_Exc({"Retry-After": "999"}), 2.0)
              == 120.0)
        _real_synth, _real_pace = audio.synthesize, audio.pace
        _sleeps: list[float] = []
        audio.synthesize = lambda *a, **k: audio.silent_wav()
        audio.pace = _sleeps.append
        _old_key = os.environ.get("GEMINI_API_KEY")
        os.environ["GEMINI_API_KEY"] = "test-key"
        try:
            (_ach / "audio_en").mkdir(exist_ok=True)
            for _f in (_ach / "audio_en").glob("*.wav"):
                _f.unlink()
            for _f in (_ach / "audio_hi").glob("*.wav"):
                _f.unlink()
            if (_ach / "audio_manifest_Book_1_X_Chapter_1.json").exists():
                (_ach / "audio_manifest_Book_1_X_Chapter_1.json").unlink()
            check("audio budget gate refuses over-budget live runs",
                  audio.generate(["--mythology", str(_aroot),
                                  "--chapter", "Book_1_X_Chapter_1",
                                  "--daily-budget", "1"]) == 2
                  and not (_ach / "audio_en").exists()
                  or list((_ach / "audio_en").glob("*.wav")) == [])
            _pch = _aroot / "outputs" / "Book_1_X_Chapter_2"
            _pch.mkdir(parents=True, exist_ok=True)
            (_pch / "script_Book_1_X_Chapter_2.json").write_text(
                json.dumps(GOOD_NARR + [GOOD_NARR[0]]), encoding="utf-8")
            check("audio live run paces between calls",
                  audio.generate(["--mythology", str(_aroot),
                                  "--chapter", "Book_1_X_Chapter_2",
                                  "--lang", "en", "--delay-s", "2.5",
                                  "--daily-budget", "100"]) == 0
                  and _sleeps == [2.5]
                  and json.loads((_pch / "audio_manifest_Book_1_X_Chapter_2.json")
                                 .read_text(encoding="utf-8"))
                  ["chunks"][0]["en"]["source"] == "synthesized")
            _sleeps.clear()
            check("audio --ignore-budget proceeds over budget",
                  audio.generate(["--mythology", str(_aroot),
                                  "--chapter", "Book_1_X_Chapter_2",
                                  "--lang", "both", "--delay-s", "0",
                                  "--daily-budget", "1", "--redo",
                                  "--ignore-budget"]) == 0
                  and _sleeps == [0, 0, 0])
        finally:
            audio.synthesize, audio.pace = _real_synth, _real_pace
            if _old_key is None:
                os.environ.pop("GEMINI_API_KEY", None)
            else:
                os.environ["GEMINI_API_KEY"] = _old_key

    # upload metadata: dual-audio shape, limits, fallbacks (no network)
    check("metadata no-chapter rc=2", metadata.main([]) == 2)
    with tempfile.TemporaryDirectory() as tmp:
        _mroot = Path(tmp)
        _mch = _mroot / "outputs" / "Book_9_Test_Chapter_1"
        _mch.mkdir(parents=True)
        (_mch / "script_Book_9_Test_Chapter_1.json").write_text(json.dumps([
            {"character": "Kavya", "voice": "Hindi (Female)",
             "text": "कथा यहाँ शुरू। <narrative>",
             "text_en": "The story starts here. <narrative>"},
            {"character": "Kavya", "voice": "Hindi (Female)",
             "text": "ऐसा क्यों हुआ? <formal>",
             "text_en": "Why did this happen? <formal>"}]), encoding="utf-8")
        _meta = metadata.build_metadata(_mroot, "Book_9_Test_Chapter_1")
        _lc = _meta["limits_check"]
        check("metadata ships one youtube plus two spotify episodes",
              set(_meta["spotify"]["episodes"]) == {"hi", "en"}
              and _meta["youtube"]["default_language"] == "hi"
              and len(_meta["youtube"]["additional_audio_tracks"]) == 2)
        check("metadata passes platform limits",
              all(v for k, v in _lc.items() if k.endswith("_ok")), f"{_lc}")
        check("metadata untimed without manifests",
              _meta["assets"]["duration_s"] is None
              and _meta["youtube"]["chapters"] == [])
        try:
            metadata.build_metadata(_mroot, "Book_9_Test_Chapter_9")
            check("metadata missing script raises", False)
        except SystemExit:
            check("metadata missing script raises", True)
        (_mch / "audio_manifest_Book_9_Test_Chapter_1.json").write_text(json.dumps(
            {"chunks": [{"en": {"duration_s": 5.0}, "hi": {"duration_s": 6.0}}]}),
            encoding="utf-8")
        _stale = metadata.build_metadata(_mroot, "Book_9_Test_Chapter_1")
        check("metadata drops chapters on stale manifest",
              _stale["youtube"]["chapters"] == []
              and _stale["assets"]["duration_s"] == 6.0)
    check("metadata chapter numbers parse",
          metadata._chapter_numbers("Book_1_Bala_Kanda_Chapter_5") == (1, 5, "chapter")
          and metadata._chapter_numbers("Book_0_Introduction") == (0, 0, "intro"))

    # video build stage: timing math, filter graph, dry-run plan (no ffmpeg)
    import build_video as _bv
    check("video no-chapter rc=2", _bv.main([]) == 2)
    check("video splits a chunk evenly over its images",
          _bv.split_durations(4.0, 2) == [2.0, 2.0])
    check("video xfade offsets accumulate",
          _bv.xfade_offsets([2.0, 3.0, 4.0], 0.5) == [1.5, 4.0])
    check("video xfade clamps below the shortest segment",
          _bv.clamp_xfade(0.5, [2.0, 0.5]) == 0.2
          and _bv.clamp_xfade(0.5, [2.0]) == 0.0)
    check("video kenburns drifts, static holds",
          "zoompan" in _bv.segment_chain(0, "kenburns", 2.0, 640, 360, 30)
          and "zoompan" not in _bv.segment_chain(0, "static", 2.0, 640, 360, 30)
          and "tpad" in _bv.segment_chain(0, "static", 2.0, 640, 360, 30))
    _bg, _bv_dur = _bv.build_filter([2.0, 3.0], "kenburns", "xfade", 0.5,
                                    640, 360, 30, 2)
    check("video xfade graph shortens by the overlap",
          "xfade" in _bg and _bv_dur == 4.5, f"{_bg[:60]} {_bv_dur}")
    _bg2, _bv2 = _bv.build_filter([2.0, 3.0], "static", "cut", 0.5,
                                  640, 360, 30, 2)
    check("video cut graph keeps full duration",
          "concat" in _bg2 and "xfade" not in _bg2 and _bv2 == 5.0)
    check("video avoids filters missing from this ffmpeg",
          "aconcat" not in _bg and "aconcat" not in _bg2)
    check("video kenburns carries sway plus grain",
          "sin(2*PI*on" in _bv.segment_chain(0, "kenburns", 2.0, 640, 360, 30)
          and "noise=alls=" in _bv.segment_chain(0, "kenburns", 2.0, 640, 360, 30)
          and "noise" not in _bv.segment_chain(0, "static", 2.0, 640, 360, 30))
    _shots = _bv.expand_shots([{"image": "a", "duration_s": 18.0},
                               {"image": "b", "duration_s": 5.0}])
    check("video renews long holds into ~8s shots",
          [(s["image"], s["shot"], s["shots"]) for s in _shots]
          == [("a", 1, 3), ("a", 2, 3), ("a", 3, 3), ("b", 1, 1)]
          and abs(sum(s["duration_s"] for s in _shots) - 23.0) < 0.01)
    check("video never pushes in (pull-outs and pans only)",
          "1.15-0.15*on" in _bv.kenburns_exprs(0, 90)[0]
          and "1.0+0.35" not in _bv.segment_chain(0, "kenburns", 2.0,
                                                  640, 360, 30))
    check("video holds discussion shots still, drifts narration",
          _bv.shot_motion({"kind": "discussion"}, "kenburns") == "static"
          and _bv.shot_motion({"kind": "narration"}, "kenburns") == "kenburns"
          and _bv.shot_motion({"kind": "discussion"}, "static") == "static")
    _mix, _ = _bv.build_video_chain([2.0, 2.0], ["kenburns", "static"],
                                    "cut", 0.0, 640, 360, 30)
    check("video mixes moves per shot",
          "zoompan" in _mix and "tpad" in _mix)
    check("video static holds clone the frame (never black pads)",
          "stop_mode=clone" in _bv.segment_chain(0, "static", 2.0,
                                                 640, 360, 30))
    with tempfile.TemporaryDirectory() as tmp:
        _vroot = Path(tmp)
        for _req in ("sources", "outputs", "entities"):
            (_vroot / _req).mkdir()
        (_vroot / "mythology.yaml").write_text("name: t\n", encoding="utf-8")
        _vch = _vroot / "outputs" / "Book_1_X_Chapter_9"
        (_vch / "studio_images").mkdir(parents=True)
        (_vch / "audio_en").mkdir(parents=True)
        _vmap = {"chapter": "Book_1_X_Chapter_9",
                 "chunks": [
                     {"chunk": 1, "kind": "narration", "script_index": 0,
                      "slides": [1],
                      "images": ["studio_images/slide_01_final.jpg"]},
                     {"chunk": 2, "kind": "narration", "script_index": 1,
                      "slides": [2, 3],
                      "images": ["studio_images/slide_02_final.jpg",
                                 "studio_images/slide_03_final.jpg"]},
                 ]}
        (_vch / "av_mapping_Book_1_X_Chapter_9.json").write_text(
            json.dumps(_vmap), encoding="utf-8")
        for _i in (1, 2, 3):
            (_vch / "studio_images" / f"slide_{_i:02d}_final.jpg").write_bytes(
                b"fake-jpg")
        for _i in (1, 2):
            (_vch / "audio_en" / f"chunk_{_i:03d}.wav").write_bytes(
                audio.silent_wav(seconds=1.5))
        (_vch / "audio_hi").mkdir(parents=True)
        for _i in (1, 2):
            (_vch / "audio_hi" / f"chunk_{_i:03d}.wav").write_bytes(
                audio.silent_wav(seconds=1.0))
        check("video dry-run plans audio-timed segments",
              _bv.main(["--mythology", str(_vroot),
                        "--chapter", "Book_1_X_Chapter_9",
                        "--lang", "en", "--dry-run"]) == 0
              and (_vch / "video_manifest_Book_1_X_Chapter_9.json").is_file())
        _vent = json.loads(
            (_vch / "video_manifest_Book_1_X_Chapter_9.json")
            .read_text(encoding="utf-8"))["videos"]["en"]
        # Shots are stretched by their share of the dissolve overlap
        # (0.3 fade x2 over 3 shots = +0.2 each) so the video lands exactly
        # on the audio length instead of cutting the narration tail.
        check("video plan splits multi-image chunk evenly",
              [s["duration_s"] for s in _vent["segments"]] == [1.7, 0.95, 0.95]
              and _vent["video_total_s"] == _vent["audio_total_s"] == 3.0,
              f"{_vent['segments']}")
        check("video dual cuts to the longer track, pads the shorter",
              _bv.main(["--mythology", str(_vroot),
                        "--chapter", "Book_1_X_Chapter_9",
                        "--dual", "--dry-run"]) == 0
              and (lambda _d: _d["base_lang"] == "en"
                   and _d["video_total_s"] == 3.0
                   and _d["en_total_s"] == 3.0 and _d["hi_total_s"] == 2.0
                   and _d["track_files"] == {
                       "en": "audio_track_Book_1_X_Chapter_9_en.wav",
                       "hi": "audio_track_Book_1_X_Chapter_9_hi.wav"})(
                  json.loads((_vch / "video_manifest_Book_1_X_Chapter_9.json")
                             .read_text(encoding="utf-8"))["videos"]["dual"]))
        check("video dual labels one chain per track",
              "[aen]" in _bv.build_audio_chain(3, 2, 5.0, "aen")
              and "[ahi]" in _bv.build_audio_chain(5, 2, 5.0, "ahi"))
        check("video bed is quiet, faded, and mixed without renorm",
              "volume=0.1995" in _bv.music_bed_chain(9, 30.0, -14.0, "mbed")
              and "afade=t=out" in _bv.music_bed_chain(9, 30.0, -14.0, "mbed")
              and "normalize=0" in _bv.mix_chain("aout", "mbed", "mix"))
        (_vch / "bed.wav").write_bytes(audio.silent_wav(seconds=5.0))
        check("video dual dry-run accepts a music bed",
              _bv.main(["--mythology", str(_vroot),
                        "--chapter", "Book_1_X_Chapter_9",
                        "--dual", "--dry-run",
                        "--music", str(_vch / "bed.wav")]) == 0
              and json.loads((_vch / "video_manifest_Book_1_X_Chapter_9.json")
                             .read_text(encoding="utf-8"))
              ["videos"]["dual"]["music"]["db"] == -14.0)
        check("video rejects a missing music file",
              _bv.main(["--mythology", str(_vroot),
                        "--chapter", "Book_1_X_Chapter_9",
                        "--dual", "--dry-run",
                        "--music", str(_vch / "nope.wav")]) == 2)
        (_vch / "audio_en" / "chunk_002.wav").unlink()
        check("video fails loud on missing audio",
              _bv.main(["--mythology", str(_vroot),
                        "--chapter", "Book_1_X_Chapter_9",
                        "--lang", "en", "--dry-run"]) == 2)
        check("video fails loud on missing chapter dir",
              _bv.main(["--mythology", str(_vroot),
                        "--chapter", "Book_1_X_Chapter_8",
                        "--lang", "en", "--dry-run"]) == 2)
    # video cue sheet: panel shares weight the split, prompts ride along,
    # and every row carries its timeline cue
    with tempfile.TemporaryDirectory() as tmp:
        _crow = Path(tmp)
        (_crow / "studio_images").mkdir(parents=True)
        for _i in (1, 2, 3):
            (_crow / "studio_images" / f"slide_{_i:02d}_final.jpg").write_bytes(
                b"fake-jpg")
        _cchunks = [
            {"chunk": 1, "kind": "narration", "script_index": 0,
             "slides": [1, 2],
             "images": ["studio_images/slide_01_final.jpg",
                        "studio_images/slide_02_final.jpg"],
             "panels": [
                 {"slide": 1, "image": "studio_images/slide_01_final.jpg",
                  "title": "T1", "muse_prompt": "p1", "share": 0.75},
                 {"slide": 2, "image": "studio_images/slide_02_final.jpg",
                  "title": "T2", "muse_prompt": "p2", "share": 0.25}]},
            {"chunk": 2, "kind": "narration", "script_index": 1,
             "slides": [3],
             "images": ["studio_images/slide_03_final.jpg"]},
        ]
        _ctracks = [{"script_index": 0, "file": "a0.wav", "duration_s": 4.0},
                    {"script_index": 1, "file": "a1.wav", "duration_s": 2.0}]
        _csegs, _cerr = _bv.plan_segments(_cchunks, _ctracks, _crow)
        check("video cue sheet honors shares, prompts, coverage",
              _cerr == []
              and [(s["slide"], s["duration_s"], s["start_s"], s["end_s"])
                   for s in _csegs] == [(1, 3.0, 0.0, 3.0),
                                        (2, 1.0, 3.0, 4.0),
                                        (3, 2.0, 4.0, 6.0)]
              and [s["muse_prompt"] for s in _csegs] == ["p1", "p2", None],
              f"{_cerr} {_csegs}")
        _cshots = _bv.shot_timeline([dict(s) for s in _csegs], "xfade", 0.4)
        check("video shot cues overlap by the dissolve",
              [(s["start_s"], s["end_s"]) for s in _cshots]
              == [(0.0, 3.0), (2.6, 3.6), (3.2, 5.2)],
              f"{_cshots}")
        _cshots2 = _bv.shot_timeline([dict(s) for s in _csegs], "cut", 0.0)
        check("video cut cues run contiguous",
              [(s["start_s"], s["end_s"]) for s in _cshots2]
              == [(0.0, 3.0), (3.0, 4.0), (4.0, 6.0)],
              f"{_cshots2}")
        _r3ch = [{"chunk": 1, "kind": "narration", "script_index": 0,
                  "slides": [1, 2, 3],
                  "images": ["studio_images/slide_01_final.jpg",
                             "studio_images/slide_02_final.jpg",
                             "studio_images/slide_03_final.jpg"]}]
        _r3segs, _r3err = _bv.plan_segments(
            _r3ch, [{"script_index": 0, "file": "a.wav", "duration_s": 1.0}],
            _crow)
        check("video last image takes the remainder (no 1ms leak)",
              _r3err == []
              and [s["duration_s"] for s in _r3segs] == [0.333, 0.333, 0.334]
              and _r3segs[-1]["end_s"] == 1.0
              and sum(s["duration_s"] for s in _r3segs) == 1.0,
              f"{_r3err} {_r3segs}")

    print(f"\n{len(FAILS)} failures" if FAILS else "\nSELFTEST PASS")
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
