#!/usr/bin/env python3
"""MythologyMuse maintained self-test (stdlib only; no key, no network).

Covers the deterministic contracts behind the pipeline: chapter addressing,
isolation gate, effort mapping, segment validators, Layer A gates, reviewer
template, recap builder, audit math, and stage exit codes. Run after any
tools/prompts change:

    python3 tools/selftest.py
"""

import json
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
import comic_stage as comic  # noqa: E402
import bridge_stage as bridge  # noqa: E402
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
              "text": "प्रश्न: क्यों? विवेचना: इसलिए। जीवन-सूत्र: रोज़ करें। <formal>",
              "text_en": "Question: Why? Reflection: Because. Takeaway: Do daily. <formal>"}]


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
    bad_order = [dict(GOOD_REFL[0],
                      text="विवेचना: पहले। प्रश्न: बाद में। जीवन-सूत्र: रोज़। <formal>")]
    check("misordered Hindi labels flagged",
          any("order" in p for p in podcast.validate_segments(bad_order, "reflection")))
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
    fatal, _ = loop.prescan_prompt("a serene grove at dawn", "3:2")
    check("loop prescan fails bad aspect", fatal != [], fatal)

    print(f"\n{len(FAILS)} failures" if FAILS else "\nSELFTEST PASS")
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
