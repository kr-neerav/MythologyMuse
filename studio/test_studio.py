#!/usr/bin/env python3
"""Studio offline tests: no key, no network, tmp dirs only."""

import json
import sys
import tempfile
from pathlib import Path

STUDIO = Path(__file__).resolve().parent
sys.path.insert(0, str(STUDIO))

import bundle as bundle_mod
import image_gen as image_gen_mod
import state as state_mod


def test_review_roundtrip():
    with tempfile.TemporaryDirectory() as t:
        out = Path(t)
        (out / "Ch1").mkdir()
        state_mod.set_slide(out, "Ch1", 2, "needs_redo", "reorder insight")
        state_mod.set_chapter(out, "Ch1", "approved", "looks good")
        data = state_mod.load_review(out, "Ch1")
        assert data["slides"]["2"]["decision"] == "needs_redo"
        assert data["chapter_decision"] == "approved"
        try:
            state_mod.set_slide(out, "Ch1", 1, "bogus")
            raise AssertionError("bad decision accepted")
        except ValueError:
            pass
    print("ok review roundtrip")


def test_bundle_assembly():
    with tempfile.TemporaryDirectory() as t:
        out = Path(t)
        d = out / "Ch9"
        d.mkdir()
        board = [{"slide": 1, "slide_label": "Slide01 - Dawn", "title": "Dawn",
                  "type": "scene", "on_slide_text": "text here",
                  "characters": ["Rama"], "location": "Ayodhya", "rationale": "why"}]
        (d / "comic_storyboard_Ch9.json").write_text(json.dumps(board))
        (d / "comic_muse_prompts_Ch9.json").write_text(json.dumps(
            [{"slide": 1, "muse_prompt": "paint Rama at dawn"}]))
        (d / "comic_storyboard_hindi_Ch9.json").write_text(json.dumps(
            [{"slide": 1, "on_slide_text": "hindi"}]))
        (d / "comic_eval_Ch9.json").write_text(json.dumps(
            {"verdict": "PASS", "dry_run": False}))
        (d / "comic_progress_Ch9.json").write_text(json.dumps({"eval": "PASS"}))
        (d / "comic_render_plan_Ch9.json").write_text(json.dumps(
            {"roster": [{"name": "Rama", "flow_ref": "Rama", "kind": "character",
                         "image_prompt": "tall archer"}],
             "slides": [{"slide": 1, "subjects": ["Rama"], "size": "1536x864"}]}))
        b = bundle_mod.chapter_bundle(out, "Ch9")
        assert b["counts"] == {"board": 1, "prompts": 1, "hindi": 1, "roster": 1}
        assert b["slides"][0]["muse_prompt"].startswith("paint Rama")
        assert b["slides"][0]["hindi_text"] == "hindi"
        assert "mock_panel" in b["slides"][0] and "mock_sheet" in b["roster"][0]
        assert bundle_mod.list_chapters(out) == ["Ch9"]
    print("ok bundle assembly")


def test_subject_ref_resolution():
    with tempfile.TemporaryDirectory() as t:
        out = Path(t)
        d = out / "Ch9"
        d.mkdir()
        (d / "comic_storyboard_Ch9.json").write_text(json.dumps(
            [{"slide": 1, "slide_label": "S1", "title": "T", "type": "scene",
              "on_slide_text": "x", "characters": ["Rama"], "location": "L",
              "rationale": "r"}]))
        (d / "comic_muse_prompts_Ch9.json").write_text(json.dumps(
            [{"slide": 1, "muse_prompt": "paint Rama"}]))
        (d / "comic_storyboard_hindi_Ch9.json").write_text(json.dumps([]))
        (d / "comic_eval_Ch9.json").write_text(json.dumps({"verdict": "PASS"}))
        (d / "comic_progress_Ch9.json").write_text(json.dumps({}))
        (d / "comic_render_plan_Ch9.json").write_text(json.dumps(
            {"roster": [{"name": "Rama", "flow_ref": "Rama", "kind": "character",
                         "image_prompt": "tall archer"}],
             "slides": [{"slide": 1, "subjects": [{"name": "Rama",
                         "kind": "character"}], "size": "1536x864"}]}))
        b = bundle_mod.chapter_bundle(out, "Ch9")
        assert b["slides"][0]["subjects"] == [
            {"name": "Rama", "kind": "character", "flow_ref": "Rama",
             "sheet_state": "missing", "sheet_final": "",
             "sheet_candidates": [], "generatable": True}]
        assert b["roster"][0]["sheet_state"] == "missing"
        imgs = out / "Ch9" / "studio_images"
        imgs.mkdir()
        (imgs / "sheet_Rama_candidate_1.jpg").write_bytes(b"fakejpeg")
        (imgs / "sheet_Rama_candidate_2.jpg").write_bytes(b"fakejpeg")
        refs = image_gen_mod.collect_refs(
            imgs, b["slides"][0]["subjects"])
        assert len(refs) == 0  # no final picked yet: panels use finals only
        b2 = bundle_mod.chapter_bundle(out, "Ch9")
        sub = b2["slides"][0]["subjects"][0]
        assert sub["sheet_state"] == "review"
        assert sub["sheet_candidates"] == ["sheet_Rama_candidate_1.jpg",
                                           "sheet_Rama_candidate_2.jpg"]
        final = image_gen_mod.select_candidate(
            out, "Ch9", "Rama", "sheet_Rama_candidate_2.jpg")
        assert final == "sheet_Rama_final.jpg"
        assert (imgs / "sheet_Rama_candidate_1.jpg").exists()  # kept
        b3 = bundle_mod.chapter_bundle(out, "Ch9")
        assert b3["slides"][0]["subjects"][0]["sheet_state"] == "ready"
        assert b3["roster"][0]["sheet_state"] == "ready"
        refs2 = image_gen_mod.collect_refs(
            imgs, b3["slides"][0]["subjects"])
        assert len(refs2) == 1 and refs2[0].name == "sheet_Rama_final.jpg"
    print("ok subject ref resolution feeds panel refs + readiness")



def test_shared_sheet_final_visible_across_chapters():
    """Common entities must not need regeneration per chapter.

    A final picked in Ch1 must surface as ready in Ch2 (same mythology
    outputs dir): bundle state, panel ref attachment, and collect_refs.
    Writes stay per-chapter; local finals still win over shared ones.
    """
    with tempfile.TemporaryDirectory() as t:
        out = Path(t)
        roster = [{"name": "Rama", "flow_ref": "Rama", "kind": "character",
                   "image_prompt": "tall archer"}]
        subjects = [{"name": "Rama", "kind": "character"}]
        _write_ch9_plan(out, "Ch1", roster, subjects)
        _write_ch9_plan(out, "Ch2", roster, subjects)
        imgs1 = out / "Ch1" / "studio_images"
        imgs1.mkdir(parents=True)
        (imgs1 / "sheet_Rama_final.jpg").write_bytes(b"shared-bytes")
        # Ch2 has no local studio_images content: shared final still reads ready.
        b2 = bundle_mod.chapter_bundle(out, "Ch2")
        assert b2["roster"][0]["sheet_state"] == "ready", b2["roster"][0]
        assert b2["roster"][0]["sheet_final"] == "sheet_Rama_final.jpg"
        assert b2["slides"][0]["subjects"][0]["sheet_state"] == "ready"
        imgs2 = out / "Ch2" / "studio_images"
        refs = image_gen_mod.collect_refs(imgs2, ["Rama", "Nobody"])
        assert len(refs) == 1 and refs[0].name == "sheet_Rama_final.jpg"
        assert refs[0].read_bytes() == b"shared-bytes"
        import server as server_mod
        h = server_mod.Handler.__new__(server_mod.Handler)
        resolved = h._resolve_target(out, "Ch2", {"kind": "panel", "slide": 1})
        assert resolved["ref_names"] == ["Rama"], resolved
        # Local pick overrides the shared look (per-chapter override kept).
        imgs2.mkdir(parents=True, exist_ok=True)
        (imgs2 / "sheet_Rama_final.jpg").write_bytes(b"local-bytes")
        assert image_gen_mod.sheet_final(
            imgs2, "Rama").read_bytes() == b"local-bytes"
    print("ok shared sheet finals surface across chapters, local wins")


def _write_ch9_plan(out, chapter, roster, subjects, prompt="paint scene"):
    d = out / chapter
    d.mkdir(exist_ok=True)
    (d / f"comic_storyboard_{chapter}.json").write_text(json.dumps(
        [{"slide": 1, "slide_label": "S1", "title": "T", "type": "scene",
          "on_slide_text": "x", "characters": [], "location": "L",
          "rationale": "r"}]))
    (d / f"comic_muse_prompts_{chapter}.json").write_text(json.dumps(
        [{"slide": 1, "muse_prompt": prompt}]))
    (d / f"comic_storyboard_hindi_{chapter}.json").write_text(json.dumps([]))
    (d / f"comic_eval_{chapter}.json").write_text(json.dumps(
        {"verdict": "PASS"}))
    (d / f"comic_progress_{chapter}.json").write_text(json.dumps({}))
    (d / f"comic_render_plan_{chapter}.json").write_text(json.dumps(
        {"roster": roster,
         "slides": [{"slide": 1, "subjects": subjects,
                     "size": "1536x864"}]}))


def test_junk_subject_not_generatable():
    """Kavya-like junk (kind unknown, no flow_ref) must never offer Generate."""
    with tempfile.TemporaryDirectory() as t:
        out = Path(t)
        _write_ch9_plan(
            out, "Ch9",
            [{"name": "Rama", "flow_ref": "Rama", "kind": "character",
              "image_prompt": "tall archer"},
             {"name": "Kavya", "kind": "unknown", "flow_ref": None,
              "image_prompt": None}],
            [{"name": "Rama", "kind": "character"},
             {"name": "Kavya", "kind": "unknown"}])
        b = bundle_mod.chapter_bundle(out, "Ch9")
        subs = {s["name"]: s for s in b["slides"][0]["subjects"]}
        assert subs["Rama"]["flow_ref"] == "Rama"
        assert subs["Rama"]["generatable"] is True
        assert subs["Kavya"]["flow_ref"] == ""
        assert subs["Kavya"]["generatable"] is False
        assert b["slides"][0]["panel_candidates"] == []
    print("ok junk subjects are flagged, never offered for generation")


def test_panel_candidates_resurface():
    """Panel renders must survive a reload like sheet candidates do."""
    with tempfile.TemporaryDirectory() as t:
        out = Path(t)
        _write_ch9_plan(
            out, "Ch9",
            [{"name": "Rama", "flow_ref": "Rama", "kind": "character",
              "image_prompt": "tall archer"}],
            [{"name": "Rama", "kind": "character"}])
        imgs = out / "Ch9" / "studio_images"
        imgs.mkdir()
        (imgs / "slide_01_candidate_2.jpg").write_bytes(b"fakejpeg")
        (imgs / "slide_01_candidate_1.jpg").write_bytes(b"fakejpeg")
        (imgs / "slide_02_candidate_1.jpg").write_bytes(b"fakejpeg")
        b = bundle_mod.chapter_bundle(out, "Ch9")
        assert b["slides"][0]["panel_candidates"] == [
            "slide_01_candidate_1.jpg", "slide_01_candidate_2.jpg"]
    print("ok panel renders resurface after reload")


def test_sheet_resolve_errors():
    """Sheet resolution: exact ref, name fallback, and errors that name the ref."""
    import server as server_mod
    resolve = server_mod.Handler._resolve_target
    with tempfile.TemporaryDirectory() as t:
        out = Path(t)
        _write_ch9_plan(
            out, "Ch9",
            [{"name": "Rama", "flow_ref": "Rama", "kind": "character",
              "image_prompt": "tall archer"},
             {"name": "Sita", "flow_ref": "SitaRef", "kind": "character",
              "image_prompt": "princess"},
             {"name": "Kavya", "kind": "unknown", "flow_ref": None,
              "image_prompt": None}],
            [{"name": "Rama", "kind": "character"}])
        got = resolve(None, out, "Ch9", {"kind": "sheet", "ref": "Rama"})
        assert got["sheet_ref"] == "Rama" and got["prompt"] == "tall archer"
        got2 = resolve(None, out, "Ch9", {"kind": "sheet", "ref": "Sita"})
        assert got2["sheet_ref"] == "SitaRef", got2
        for bad, needle in [("Nope", "Nope"), ("", "roster ref"),
                            ("Kavya", "Kavya")]:
            try:
                resolve(None, out, "Ch9", {"kind": "sheet", "ref": bad})
            except ValueError as e:
                assert needle in str(e), str(e)
            else:
                raise AssertionError(f"no error for ref {bad!r}")
        try:
            resolve(None, out, "Ch9", {"kind": "sheet", "ref": "Kavya"})
        except ValueError as e:
            assert "image prompt" in str(e), str(e)
        else:
            raise AssertionError("junk subject generated no error")
    print("ok sheet resolution names bad refs, falls back to names")



def test_panel_select_validation():
    """Panel finalize copies winner to slide final, keeps candidates."""
    with tempfile.TemporaryDirectory() as t:
        out = Path(t)
        d = out / "Ch9" / "studio_images"
        d.mkdir(parents=True)
        (d / "slide_01_candidate_1.jpg").write_bytes(b"fakejpeg")
        (d / "slide_01_candidate_2.jpg").write_bytes(b"fakejpeg")
        final = image_gen_mod.select_panel_candidate(
            out, "Ch9", 1, "slide_01_candidate_2.jpg")
        assert final == "slide_01_final.jpg"
        assert (d / "slide_01_candidate_1.jpg").exists()  # kept
        for bad in ["../evil.jpg", "slide_01_final.jpg",
                    "slide_02_candidate_1.jpg",
                    "sheet_Rama_candidate_1.jpg"]:
            try:
                image_gen_mod.select_panel_candidate(out, "Ch9", 1, bad)
            except ValueError:
                pass
            else:
                raise AssertionError(f"accepted {bad}")
        try:
            image_gen_mod.select_panel_candidate(
                out, "Ch9", 1, "slide_01_candidate_9.jpg")
        except ValueError as e:
            assert str(e) == "not found", str(e)
        else:
            raise AssertionError("missing file accepted")
        try:
            image_gen_mod.select_panel_candidate(
                out, "Ch9", "x", "slide_01_candidate_1.jpg")
        except ValueError:
            pass
        else:
            raise AssertionError("garbage slide accepted")
    print("ok panel finalize validates + copies (keeps candidates)")


def test_panel_final_resurfaces():
    """A picked panel final must resurface after reload."""
    with tempfile.TemporaryDirectory() as t:
        out = Path(t)
        _write_ch9_plan(
            out, "Ch9",
            [{"name": "Rama", "flow_ref": "Rama", "kind": "character",
              "image_prompt": "tall archer"}],
            [{"name": "Rama", "kind": "character"}])
        imgs = out / "Ch9" / "studio_images"
        imgs.mkdir()
        (imgs / "slide_01_candidate_1.jpg").write_bytes(b"fakejpeg")
        (imgs / "slide_01_final.jpg").write_bytes(b"fakejpeg")
        b = bundle_mod.chapter_bundle(out, "Ch9")
        assert b["slides"][0]["panel_final"] == "slide_01_final.jpg"
        assert b["slides"][0]["panel_candidates"] == [
            "slide_01_candidate_1.jpg"]
    print("ok picked panel final resurfaces after reload")


def test_panel_select_endpoint_routes():
    """POST /api/select kind=panel must reach the panel finalize."""
    import server as server_mod
    Harness = _fake_handler()
    seen = {}
    real = image_gen_mod.select_panel_candidate

    def stub(outputs, chapter, slide, fname):
        seen.update(chapter=chapter, slide=slide, fname=fname)
        return "slide_01_final.jpg"
    image_gen_mod.select_panel_candidate = stub
    try:
        h = Harness("POST", "/api/select",
                    {"mythology": "mythologies/ramayana_dutt",
                     "chapter": "Book_1_Bala_Kanda_Chapter_1",
                     "kind": "panel", "slide": 1,
                     "file": "slide_01_candidate_2.jpg"})
        h.do_POST()
        assert h._code == 200, h.wfile.getvalue()[:200]
        body = json.loads(h.wfile.getvalue().decode())
        assert body.get("final") == "slide_01_final.jpg", body
        assert (seen.get("chapter")
                == "Book_1_Bala_Kanda_Chapter_1"), seen
        assert seen.get("slide") == 1, seen
        assert seen.get("fname") == "slide_01_candidate_2.jpg", seen
    finally:
        image_gen_mod.select_panel_candidate = real
    print("ok panel select endpoint routes to panel finalize")



def test_ch1_hand_corrections_hold():
    """Hand-fixed Ch1 data must survive: hermitage slide 1, no person-Dharma
    slide 4. A pipeline re-run silently clobbers these files, so this test
    fails loudly if that happens. Skips when chapter outputs are absent."""
    root = Path(__file__).resolve().parent.parent
    out = root / "mythologies/ramayana_dutt/outputs/Book_1_Bala_Kanda_Chapter_1"
    if not out.is_dir():
        print("skip hand corrections (no chapter outputs)")
        return
    board = json.loads(
        (out / "comic_storyboard_Book_1_Bala_Kanda_Chapter_1.json").read_text(
            encoding="utf-8"))
    prompts = json.loads(
        (out / "comic_muse_prompts_Book_1_Bala_Kanda_Chapter_1.json").read_text(
            encoding="utf-8"))
    plan = json.loads(
        (out / "comic_render_plan_Book_1_Bala_Kanda_Chapter_1.json").read_text(
            encoding="utf-8"))
    p1 = next(x for x in prompts if x.get("slide") == 1)["muse_prompt"]
    assert "Ayodhya" not in p1 and "palace" not in p1, p1[:200]
    assert next(x for x in board if x.get("slide") == 1)["location"] == \
        "Valmiki's Forest Hermitage"
    p4 = next(x for x in prompts if x.get("slide") == 4)["muse_prompt"]
    assert "god of righteousness" not in p4, p4[:300]
    assert "dharma-wheel" in p4, "emblem must remain"
    subs4 = next(x for x in plan["slides"] if x.get("slide") == 4)["subjects"]
    assert all((x.get("name") if isinstance(x, dict) else x) != "Dharma"
               for x in subs4), subs4
    p7 = next(x for x in prompts if x.get("slide") == 7)["muse_prompt"]
    assert "Rohini" not in p7 and "Janaka" not in p7, p7[-400:]
    subs7 = next(x for x in plan["slides"] if x.get("slide") == 7)["subjects"]
    assert all((x.get("name") if isinstance(x, dict) else x)
               not in ("Rohini", "Janaka") for x in subs7), subs7
    print("ok ch1 hand corrections hold")


def test_ch1_staging_rubric_holds():
    """STAGE-DRAW restage must survive: capped necessary-only casts with
    board/hindi/plan agreement, plan scene == board location, prompt
    parity across both prompt copies, and no materialized similes,
    crowds, or ghosts in the prose. Skips when outputs are absent."""
    import re
    root = Path(__file__).resolve().parent.parent
    out = root / "mythologies/ramayana_dutt/outputs/Book_1_Bala_Kanda_Chapter_1"
    if not out.is_dir():
        print("skip staging rubric (no chapter outputs)")
        return
    board = json.loads(
        (out / "comic_storyboard_Book_1_Bala_Kanda_Chapter_1.json").read_text(
            encoding="utf-8"))
    hindi = json.loads(
        (out / "comic_storyboard_hindi_Book_1_Bala_Kanda_Chapter_1.json").read_text(
            encoding="utf-8"))
    prompts = json.loads(
        (out / "comic_muse_prompts_Book_1_Bala_Kanda_Chapter_1.json").read_text(
            encoding="utf-8"))
    plan = json.loads(
        (out / "comic_render_plan_Book_1_Bala_Kanda_Chapter_1.json").read_text(
            encoding="utf-8"))
    prom = {x["slide"]: x["muse_prompt"] for x in prompts}
    rsl = {x["slide"]: x for x in plan["slides"]}
    expect = {
        1: ["Valmiki", "Narada"], 2: ["Kavya"],
        3: ["Narada", "Rama"], 4: ["Rama"], 5: ["Kavya"],
        6: ["Dasharatha", "Rama", "Kaikeyi"],
        7: ["Rama", "Sita", "Lakshmana", "Guha", "Charioteer"],
        8: ["Bharata", "Rama"], 9: ["Kavya"],
        10: ["Rama", "Agastya"], 11: ["Rama", "Shurpanakha", "Khara"],
        12: ["Ravana", "Sita", "Jatayu"],
        13: ["Rama", "Lakshmana", "Hanuman", "Sugriva"],
        14: ["Rama", "Sugriva", "Vali"], 15: ["Kavya"],
        16: ["Hanuman", "Sita"], 17: ["Rama", "Hanuman", "Ocean"],
        18: ["Rama", "Sita", "Agni"],
        19: ["Rama", "Sita", "Bharata", "Hanuman"], 20: ["Kavya"],
    }
    banned = {"Ikshvaku", "Kausalya", "Prajapati", "Vishnu", "Kubera",
              "Dharma", "Rohini", "Janaka", "Citizens of Ayodhya",
              "Brahmanas", "Sages of Dandaka", "Rakshasas", "Monkeys",
              "Gods", "Indra", "Maricha", "Sharabhanga", "Sutikshna",
              "Agastya's Brother", "Viradha", "Trishira", "Dushana",
              "Tara", "Dundubhi", "Shabari", "Kabandha", "Sampati",
              "Indrajit", "Aksha", "Nala", "Vibhishana", "Vashishtha",
              "Bharadwaja"}
    for slide in board:
        n = slide["slide"]
        assert slide["characters"] == expect[n], (n, slide["characters"])
        h = next(x for x in hindi if x["slide"] == n)
        assert h["characters"] == expect[n], (n, "hindi drift")
        subs = rsl[n]["subjects"]
        chars = [s["name"] for s in subs if s["kind"] != "scene"]
        assert chars == expect[n], (n, chars)
        scenes = [s["name"] for s in subs if s["kind"] == "scene"]
        if slide["type"] == "insight":
            assert expect[n] == ["Kavya"] and slide["location"] is None, n
            assert scenes == [], (n, scenes)
        else:
            assert len(chars) <= 5, (n, chars)
            assert scenes == [slide["location"]], (
                n, scenes, slide["location"])
        assert not (set(chars) & banned), (n, chars)
        assert rsl[n]["muse_prompt"] == prom[n], f"prompt drift slide {n}"
    roster_names = {r.get("name") for r in plan["roster"]}
    for slide in board:
        n = slide["slide"]
        staged = list(slide["characters"])
        if slide["location"] is not None:
            staged.append(slide["location"])
        missing = [c for c in staged if c not in roster_names]
        assert not missing, (n, missing)
    for twin in ("Vali", "Sugriva"):
        rp = next(r for r in plan["roster"] if r.get("name") == twin)
        assert "powerfully athletic medium-tall twin build" in rp["image_prompt"], twin
    assert "twin build" in prom[14], prom[14][:200]
    rav = next(r for r in plan["roster"] if r.get("name") == "Ravana")
    assert "ten fierce heads" not in rav["image_prompt"], rav["image_prompt"][:200]
    assert "twenty powerful arms" not in rav["image_prompt"], rav["image_prompt"][:200]
    prose_ban = {
        3: ["Kausalya", "forebear"], 4: ["Prajapati", "Vishnu", "Kubera"],
        6: ["Bharata"], 7: ["Dasharatha", "Citizens"],
        8: ["Vashishtha", "Bharadwaja", "gazes down", "cloud"],
        10: ["Indra", "Viradha", "Sharabhanga", "Sutikshna", "vajra"],
        10: ["toward Rama", "pointed at", "aimed at"],
        11: ["Trishira", "Dushana"], 12: ["Maricha", "ten fierce heads", "twenty powerful arms"],
        13: ["Shabari", "Kabandha", "pyre"],
        14: ["Tara", "Dundubhi"],
        16: ["Sugriva", "Sampati", "Ravana", "Indrajit"],
        17: ["Sugriva", "Sita"], 18: ["Nala", "Ravana", "Vibhishana",
                                      "Devas"],
        19: ["Bharadwaja", "Sugriva", "Brahmanas"],
    }
    for n, words in prose_ban.items():
        for w in words:
            assert re.search(r"(?i)\b" + re.escape(w) + r"s?\b",
                             prom[n]) is None, (n, w)
    print("ok ch1 staging rubric holds")


def test_panel_cast_scene_first():
    """Panel attach leads with the place: scene subjects come before
    characters in the cast (first anchor/file priority), and scene sheets
    resolve landscape while character sheets stay portrait."""
    import server as server_mod
    with tempfile.TemporaryDirectory() as t:
        out = Path(t)
        _write_ch9_plan(
            out, "Ch9",
            [{"name": "Rama", "flow_ref": "Rama", "kind": "character",
              "image_prompt": "tall archer"},
             {"name": "Ayodhya", "flow_ref": "Ayodhya", "kind": "scene",
              "image_prompt": "palace Dawson"}],
            [{"name": "Rama", "kind": "character"},
             {"name": "Ayodhya", "kind": "scene"}])
        h = server_mod.Handler.__new__(server_mod.Handler)
        resolved = h._resolve_target(out, "Ch9", {"kind": "panel", "slide": 1})
        assert [c["name"] for c in resolved["cast"]] == [
            "Ayodhya", "Rama"], resolved["cast"]
        assert resolved["ref_names"] == [], resolved["ref_names"]
        sheet = h._resolve_target(out, "Ch9", {"kind": "sheet",
                                              "ref": "Ayodhya"})
        assert sheet["aspect"] == "16:9", sheet
        assert sheet["style_which"] == "comics", sheet
        charsheet = h._resolve_target(out, "Ch9", {"kind": "sheet",
                                                  "ref": "Rama"})
        assert charsheet["aspect"] == "2:3", charsheet
        assert charsheet["style_which"] == "characters", charsheet
        imgs = out / "Ch9" / "studio_images"
        imgs.mkdir(exist_ok=True)
        (imgs / "sheet_Ayodhya_final.jpg").write_bytes(b"x")
        (imgs / "sheet_Rama_final.jpg").write_bytes(b"x")
        resolved2 = h._resolve_target(out, "Ch9", {"kind": "panel", "slide": 1})
        assert resolved2["ref_names"] == ["Ayodhya", "Rama"], resolved2
    print("ok panel cast leads with the place; scene sheets go landscape")


def test_panel_aspect_always_169():
    """Comic slides always resolve 16:9 landscape, whatever the plan's
    legacy size fields say. Skips when chapter outputs are absent."""
    import server as server_mod
    root = Path(__file__).resolve().parent.parent
    chapter = "Book_1_Bala_Kanda_Chapter_1"
    cdir = root / "mythologies/ramayana_dutt/outputs" / chapter
    if not cdir.is_dir():
        print("skip panel aspect (no chapter outputs)")
        return
    out = root / "mythologies/ramayana_dutt/outputs"
    plan = json.loads(
        (cdir / "comic_render_plan_Book_1_Bala_Kanda_Chapter_1.json").read_text(
            encoding="utf-8"))
    assert len(plan["slides"]) == 20, len(plan["slides"])
    assert {s.get("size") for s in plan["slides"]} == {"1536x1024"},         {s.get("slide"): s.get("size") for s in plan["slides"]}
    h = server_mod.Handler.__new__(server_mod.Handler)
    for s in plan["slides"]:
        resolved = h._resolve_target(
            out, chapter, {"kind": "panel", "slide": s["slide"]})
        assert resolved["aspect"] == "16:9", (s["slide"], resolved["aspect"])
    print("ok comic slides always resolve 16:9")


def test_partition_refs_attaches_all():
    """No ref is ever cut: the first anchorable final chains, EVERY other
    finalized ref file-attaches, whatever the cast size."""
    picked = [
        {"name": "Place", "file": "p.jpg", "anchor_id": "r1"},
        {"name": "Rama", "file": "rama.jpg", "anchor_id": ""},
        {"name": "Sita", "file": "sita.jpg", "anchor_id": "r2"},
        {"name": "Lakshmana", "file": "lak.jpg", "anchor_id": ""},
        {"name": "Guha", "file": "guha.jpg", "anchor_id": ""},
        {"name": "Charioteer", "file": "ch.jpg", "anchor_id": ""},
    ]
    prev_id, prev_ref, files = image_gen_mod.partition_refs(picked)
    assert (prev_id, prev_ref) == ("r1", "Place"), (prev_id, prev_ref)
    assert [n for n, _ in files] == [
        "Rama", "Sita", "Lakshmana", "Guha", "Charioteer"], files
    assert len(files) + 1 == len(picked), "every final is used"
    prev_id2, prev_ref2, files2 = image_gen_mod.partition_refs([])
    assert (prev_id2, prev_ref2, files2) == (None, "", []),         (prev_id2, prev_ref2, files2)
    print("ok every finalized ref attaches, none cut")


def test_single_candidate_round():
    """Loop mode spends one image: candidates=1 writes one file, chains
    the head to it, and never makes the second turn."""
    import os
    real_post = image_gen_mod._post_json
    prev_key = os.getenv("MUSEIMAGES_DIR")
    with tempfile.TemporaryDirectory() as td:
        try:
            (Path(td, ".env")).write_text("MIDJOURNEY_API_KEY=k\n")
            (Path(td, "settings.json")).write_text(json.dumps({}))
            os.environ["MUSEIMAGES_DIR"] = td
            imgs = Path(td, "outs")
            imgs.mkdir()
            calls = []
            def ok(url, payload, key):
                calls.append(payload)
                return _responses_canned(f"resp_{len(calls)}")
            image_gen_mod._post_json = ok
            res = image_gen_mod.generate_sync(
                prompt="a sage", aspect="2:3",
                file_prefix="sheet_Test_candidate", dest_dir=imgs,
                kind="sheet", sheet_ref="Test", candidates=1)
            assert len(res["candidates"]) == 1, res["candidates"]
            assert len(calls) == 1, len(calls)
            assert image_gen_mod.read_chain(imgs)["head"] == "resp_1"
        finally:
            image_gen_mod._post_json = real_post
            if prev_key is None:
                os.environ.pop("MUSEIMAGES_DIR", None)
            else:
                os.environ["MUSEIMAGES_DIR"] = prev_key
    print("ok single-candidate rounds spend one image")







def test_production_filenames_resurface():
    import server as server_mod
    with tempfile.TemporaryDirectory() as t:
        out = Path(t)
        d = out / "Ch9"
        (d / "studio_images").mkdir(parents=True)
        # exact names generate_sync writes for prefix sheet_Rama_candidate
        (d / "studio_images" / "sheet_Rama_candidate_1.jpg").write_bytes(b"j")
        st = image_gen_mod.sheet_status(d / "studio_images", "Rama")
        assert st["state"] == "review"
        assert st["candidates"] == ["sheet_Rama_candidate_1.jpg"]
        # legacy names from before the _candidate infix still resurface
        (d / "studio_images" / "sheet_Sita_1.jpg").write_bytes(b"j")
        st2 = image_gen_mod.sheet_status(d / "studio_images", "Sita")
        assert st2["state"] == "review"
        assert st2["candidates"] == ["sheet_Sita_1.jpg"]
        # full loop: resolve prefix -> written file -> lookup finds it
        (d / "comic_storyboard_Ch9.json").write_text(json.dumps([]))
        (d / "comic_muse_prompts_Ch9.json").write_text(json.dumps([]))
        (d / "comic_storyboard_hindi_Ch9.json").write_text(json.dumps([]))
        (d / "comic_eval_Ch9.json").write_text(json.dumps({}))
        (d / "comic_progress_Ch9.json").write_text(json.dumps({}))
        (d / "comic_render_plan_Ch9.json").write_text(json.dumps(
            {"roster": [{"name": "Rama", "flow_ref": "Rama",
                         "kind": "character", "image_prompt": "archer"}],
             "slides": []}))
        h = server_mod.Handler.__new__(server_mod.Handler)
        resolved = h._resolve_target(out, "Ch9", {"kind": "sheet",
                                                 "ref": "Rama"})
        (d / "studio_images" / f"{resolved['prefix']}_1.jpg").write_bytes(b"j")
        (d / "studio_images" / f"{resolved['prefix']}_2.jpg").write_bytes(b"j")
        st3 = image_gen_mod.sheet_status(d / "studio_images", "Rama")
        assert st3["state"] == "review", st3
        final = image_gen_mod.select_candidate(
            out, "Ch9", "Rama", f"{resolved['prefix']}_1.jpg")
        assert final == "sheet_Rama_final.jpg"
        assert image_gen_mod.sheet_status(
            d / "studio_images", "Rama")["state"] == "ready"
    print("ok production + legacy filenames resurface")


def test_select_validation():
    with tempfile.TemporaryDirectory() as t:
        out = Path(t)
        imgs = out / "Ch9" / "studio_images"
        imgs.mkdir(parents=True)
        (imgs / "sheet_Rama_candidate_1.jpg").write_bytes(b"j")
        for bad in ["", "../evil.jpg", "sheet_Sita_candidate_1.jpg",
                    "sheet_Rama_candidate_1.png", "sheet_Rama_final.jpg"]:
            try:
                image_gen_mod.select_candidate(out, "Ch9", "Rama", bad)
                raise AssertionError(f"accepted {bad!r}")
            except ValueError:
                pass
        try:
            image_gen_mod.select_candidate(out, "Ch9", "Rama",
                                           "sheet_Rama_candidate_9.jpg")
            raise AssertionError("accepted missing file")
        except ValueError:
            pass
        got = image_gen_mod.select_candidate(
            out, "Ch9", "Rama", "sheet_Rama_candidate_1.jpg")
        assert got == "sheet_Rama_final.jpg"
        assert (imgs / "sheet_Rama_final.jpg").read_bytes() == b"j"
    print("ok select validation (traversal + wrong-ref rejected)")


def test_mock_deterministic():
    a = bundle_mod.mock_svg("Rama", "2:3")
    assert bundle_mod.mock_svg("Rama", "2:3") == a
    assert "2:3 mock" in a and "16:9 mock" in bundle_mod.mock_svg("S", "16:9")
    print("ok mock deterministic")


def test_key_loading():
    import os
    with tempfile.TemporaryDirectory() as t:
        prev = os.getenv("MUSEIMAGES_DIR")
        try:
            os.environ["MUSEIMAGES_DIR"] = t
            assert image_gen_mod.key_status()["configured"] is False
            try:
                image_gen_mod.muse_credentials()
                raise AssertionError("missing key accepted")
            except image_gen_mod.KeyMissing:
                pass
            Path(t, ".env").write_text(
                "MIDJOURNEY_API_KEY=fake-key-for-test\n"
                "MIDJOURNEY_API_URL=https://api.meta.ai/v1/images/generations\n")
            st = image_gen_mod.key_status()
            assert st["configured"] is True
            assert st["endpoint_host"] == "api.meta.ai"
            assert "fake-key" not in json.dumps(st)
        finally:
            if prev is None:
                os.environ.pop("MUSEIMAGES_DIR", None)
            else:
                os.environ["MUSEIMAGES_DIR"] = prev
    print("ok key loading (never exposes secret)")


def test_prompt_building():
    p = image_gen_mod.build_effective_prompt(
        "Rama at dawn --ar 16:9 --v 6.1", extra="warmer light")
    assert "--ar" not in p and "--v" not in p
    assert "Rama at dawn" in p and "warmer light" in p
    assert image_gen_mod.SIZE_BY_ASPECT["2:3"] != \
        image_gen_mod.SIZE_BY_ASPECT["16:9"]
    print("ok prompt building (flags stripped, aspect sizes differ)")


def test_refs_and_jobs():
    with tempfile.TemporaryDirectory() as t:
        imgs = Path(t)
        (imgs / "sheet_Rama_final.jpg").write_bytes(b"fakejpeg")
        refs = image_gen_mod.collect_refs(imgs, ["Rama", "Nobody"])
        assert len(refs) == 1 and refs[0].name == "sheet_Rama_final.jpg"
        many = image_gen_mod.collect_refs(
            imgs, ["Rama"] * 5)
        assert len(many) <= image_gen_mod.MAX_REFS
    jid = image_gen_mod.start_job("test", "unit", lambda: [{"i": 1}])
    import time as _t
    for _ in range(100):
        st = image_gen_mod.job_status(jid)
        if st["status"] == "done":
            break
        _t.sleep(0.05)
    assert image_gen_mod.job_status(jid)["status"] == "done"
    assert image_gen_mod.job_status("nope") is None
    print("ok refs capped + job lifecycle")


def _responses_canned(rid):
    import base64
    return {"id": rid, "status": "completed",
            "output": [{"type": "image_generation_call",
                        "result": base64.b64encode(b"fakeimg").decode()}]}


def test_panel_lineage():
    import os
    bodies = []
    real_post = image_gen_mod._post_json
    prev_key = os.getenv("MUSEIMAGES_DIR")
    with tempfile.TemporaryDirectory() as t:
        try:
            (Path(t, ".env")).write_text("MIDJOURNEY_API_KEY=k\n")
            (Path(t, "settings.json")).write_text(json.dumps({}))
            os.environ["MUSEIMAGES_DIR"] = t
            out = Path(t) / "outs"
            imgs = out / "Ch9" / "studio_images"
            imgs.mkdir(parents=True)

            def ok(url, payload, key):
                assert url == "https://api.meta.ai/v1/responses", url
                bodies.append(payload)
                n = len([b for b in bodies])
                return _responses_canned(f"resp_{n}")
            image_gen_mod._post_json = ok

            res = image_gen_mod.generate_sync(
                prompt="Rama at dawn", aspect="2:3",
                file_prefix="sheet_Rama_candidate", dest_dir=imgs,
                kind="sheet", sheet_ref="Rama")
            assert len(res["candidates"]) == 2
            assert res["lineage"]["transport"] == "responses"
            assert res["lineage"]["response_ids"] == {
                "sheet_Rama_candidate_1.jpg": "resp_1",
                "sheet_Rama_candidate_2.jpg": "resp_2"}
            assert "comic-book" in res["lineage"]["prompt"]
            assert "photorealism" in res["lineage"]["prompt"]
            assert bodies[0]["tools"] == [{"type": "image_generation",
                                           "size": "1024x1536"}]
            assert "previous_response_id" not in bodies[0]
            assert bodies[1].get("previous_response_id") is None
            chain = image_gen_mod.read_chain(imgs)
            assert chain["head"] == "resp_2"

            got = image_gen_mod.select_candidate(
                out, "Ch9", "Rama", "sheet_Rama_candidate_1.jpg")
            assert got == "sheet_Rama_final.jpg"
            chain = image_gen_mod.read_chain(imgs)
            assert chain["anchors"]["Rama"]["response_id"] == "resp_1"
            assert chain["head"] == "resp_1"

            bodies.clear()
            res2 = image_gen_mod.generate_sync(
                prompt="Rama walks", aspect="16:9",
                file_prefix="slide_01_candidate", dest_dir=imgs,
                kind="panel",
                cast=[{"name": "Rama", "ref": "Rama"}],
                log={"dir": str(imgs), "slide": 1})
            lin = res2["lineage"]
            assert lin["prev_anchor"] == {"ref": "Rama",
                                          "response_id": "resp_1"}, lin
            assert lin["fallback"] is False
            assert lin["refs"] == ["Rama"]
            assert bodies[0]["previous_response_id"] == "resp_1"
            assert "single comic panel" in bodies[0]["input"]
            logged = json.loads((imgs / "panel_log.json").read_text())
            assert logged[-1]["slide"] == 1
            assert logged[-1]["prev_anchor"]["ref"] == "Rama"
        finally:
            image_gen_mod._post_json = real_post
            if prev_key is None:
                os.environ.pop("MUSEIMAGES_DIR", None)
            else:
                os.environ["MUSEIMAGES_DIR"] = prev_key
    print("ok panel lineage (chaining, style, anchor pick, log)")


def test_panel_file_anchor_and_labeled_fallback():
    import os
    import urllib.error as _urlerror
    real_post = image_gen_mod._post_json
    prev_key = os.getenv("MUSEIMAGES_DIR")
    with tempfile.TemporaryDirectory() as t:
        try:
            (Path(t, ".env")).write_text("MIDJOURNEY_API_KEY=k\n")
            (Path(t, "settings.json")).write_text(json.dumps({}))
            os.environ["MUSEIMAGES_DIR"] = t
            out = Path(t) / "outs"
            imgs = out / "Ch9" / "studio_images"
            imgs.mkdir(parents=True)
            (imgs / "sheet_Sita_final.jpg").write_bytes(b"legacy-bytes")

            seen = []

            def reject_files(url, payload, key):
                seen.append(payload)
                inp = payload.get("input")
                has_image = isinstance(inp, list) and any(
                    part.get("type") == "input_image"
                    for msg in inp if isinstance(msg, dict)
                    for part in msg.get("content", []))
                if has_image:
                    raise _urlerror.HTTPError(url, 400, "bad", {}, None)
                return _responses_canned("resp_t")
            image_gen_mod._post_json = reject_files
            res = image_gen_mod.generate_sync(
                prompt="Sita waits", aspect="16:9",
                file_prefix="slide_03_candidate", dest_dir=imgs,
                kind="panel", cast=[{"name": "Sita", "ref": "Sita"}],
                log={"dir": str(imgs), "slide": 3})
            lin = res["lineage"]
            assert lin["file_attached"] == ["Sita"], lin
            assert lin["fallback"] is True
            assert "anchor rejected" in lin["fallback_reason"]
            first_input = seen[0]["input"]
            assert isinstance(first_input, list), first_input
            assert first_input[0]["role"] == "user"
            kinds = [p["type"] for p in first_input[0]["content"]]
            assert kinds == ["input_text", "input_image"]
        finally:
            image_gen_mod._post_json = real_post
            if prev_key is None:
                os.environ.pop("MUSEIMAGES_DIR", None)
            else:
                os.environ["MUSEIMAGES_DIR"] = prev_key
    print("ok file-attach for legacy finals, labeled fallback on 400")




def _sent_text(payload):
    inp = payload.get("input")
    if isinstance(inp, str):
        return inp
    for msg in inp if isinstance(inp, list) else []:
        if isinstance(msg, dict):
            for part in msg.get("content", []):
                if part.get("type") == "input_text":
                    return part.get("text", "")
    return ""


def test_panel_stale_description_override():
    """Picked finals must beat stale design-time words.

    Regression test for the Ch1 panel miss: the slide prompt still calls
    Narada a 'sage of sixty ... white beard' while the finalized imchat
    shows him young. The attached final plus an explicit override must go
    out on the turn; the text-only fallback retry must not reference
    attachments that are no longer attached.
    """
    import os
    import urllib.error as _urlerror
    real_post = image_gen_mod._post_json
    prev_key = os.getenv("MUSEIMAGES_DIR")
    STALE = ("slender sage of sixty with a shaven head "
             "and short trimmed white beard")
    with tempfile.TemporaryDirectory() as t:
        try:
            (Path(t, ".env")).write_text("MIDJOURNEY_API_KEY=k\n")
            (Path(t, "settings.json")).write_text(json.dumps({}))
            os.environ["MUSEIMAGES_DIR"] = t
            out = Path(t) / "outs"
            imgs = out / "Ch1" / "studio_images"
            imgs.mkdir(parents=True)
            (imgs / "sheet_Narada_final.jpg").write_bytes(b"legacy-bytes")
            seen = []

            def accept(url, payload, key):
                seen.append(payload)
                return _responses_canned(f"resp_{len(seen)}")
            image_gen_mod._post_json = accept
            res = image_gen_mod.generate_sync(
                prompt=f"Valmiki questions Narada, {STALE}", aspect="16:9",
                file_prefix="slide_01_candidate", dest_dir=imgs,
                kind="panel", cast=[{"name": "Narada", "ref": "Narada"}],
                log={"dir": str(imgs), "slide": 1})
            lin = res["lineage"]
            assert lin["file_attached"] == ["Narada"], lin
            assert lin["fallback"] is False
            text = _sent_text(seen[0])
            assert STALE in text
            assert "CHARACTER REFERENCE OVERRIDES" in text, text[-500:]
            tail = text.split("CHARACTER REFERENCE OVERRIDES", 1)[1]
            assert "Narada" in tail and "older draft" in tail, tail[:400]
            assert "Narada" in lin.get("file_override", ""), lin
            assert "CHARACTER REFERENCE OVERRIDES" in (
                lin.get("prompt") or ""), lin

            seen.clear()

            def reject_files(url, payload, key):
                seen.append(payload)
                inp = payload.get("input")
                has_image = isinstance(inp, list) and any(
                    part.get("type") == "input_image"
                    for msg in inp if isinstance(msg, dict)
                    for part in msg.get("content", []))
                if has_image:
                    raise _urlerror.HTTPError(url, 400, "bad", {}, None)
                return _responses_canned("resp_t")
            image_gen_mod._post_json = reject_files
            res2 = image_gen_mod.generate_sync(
                prompt=f"Valmiki questions Narada, {STALE}", aspect="16:9",
                file_prefix="slide_02_candidate", dest_dir=imgs,
                kind="panel", cast=[{"name": "Narada", "ref": "Narada"}],
                log={"dir": str(imgs), "slide": 2})
            assert res2["lineage"]["fallback"] is True
            retry_text = _sent_text(seen[-1])
            assert "CHARACTER REFERENCE OVERRIDES" not in retry_text
        finally:
            image_gen_mod._post_json = real_post
            if prev_key is None:
                os.environ.pop("MUSEIMAGES_DIR", None)
            else:
                os.environ["MUSEIMAGES_DIR"] = prev_key
    print("ok stale descriptions overridden by picked finals")


def _fake_handler():
    import io
    import server as server_mod

    class Harness(server_mod.Handler):
        def __init__(self, method, path, body):
            self.command = method
            self.path = path
            self.request_version = "HTTP/1.1"
            self.requestline = f"{method} {path} HTTP/1.1"
            raw = json.dumps(body).encode() if body is not None else b""
            self.headers = {"Content-Length": str(len(raw))}
            self.rfile = io.BytesIO(raw)
            self.wfile = io.BytesIO()
            self.sent_headers = {}
            self._code = None

        def send_response(self, code, message=None):
            self._code = code

        def send_header(self, key, value):
            self.sent_headers[key] = value

        def end_headers(self):
            pass

    return Harness


def test_generate_endpoint_no_500():
    import server as server_mod
    Harness = _fake_handler()
    seen = {}
    real_gen = image_gen_mod.generate_sync

    def stub_gen(**kwargs):
        seen.update(kwargs)
        return {"candidates": [{"candidate_index": 1}],
                "lineage": {"transport": "responses"}}
    image_gen_mod.generate_sync = stub_gen
    try:
        h = Harness("POST", "/api/generate",
                    {"mythology": "mythologies/ramayana_dutt",
                     "chapter": "Book_1_Bala_Kanda_Chapter_1",
                     "target": {"kind": "sheet", "ref": "Valmiki"}})
        h.do_POST()
        assert h._code == 200, h.wfile.getvalue()[:200]
        body = json.loads(h.wfile.getvalue().decode())
        assert body.get("job_id"), body
        assert seen.get("kind") == "sheet"
        assert seen.get("sheet_ref") == "Valmiki"

        h2 = Harness("POST", "/api/generate",
                     {"mythology": "mythologies/ramayana_dutt",
                      "chapter": "Book_1_Bala_Kanda_Chapter_1",
                      "target": {"kind": "panel", "slide": 1}})
        h2.do_POST()
        assert h2._code == 200, h2.wfile.getvalue()[:200]
        body2 = json.loads(h2.wfile.getvalue().decode())
        assert body2.get("job_id"), body2
        assert seen.get("kind") == "panel"
        assert isinstance(seen.get("cast"), list) and seen["cast"], seen
    finally:
        image_gen_mod.generate_sync = real_gen
    print("ok generate endpoint 200s with job ids (no 500)")


def test_studio_image_content_type():
    import server as server_mod
    Harness = _fake_handler()
    h = Harness("GET", "/api/studio-image?mythology=mythologies/ramayana_dutt"
                "&chapter=Book_1_Bala_Kanda_Chapter_1&file=sheet_Valmiki_final.jpg",
                None)
    h.do_GET()
    assert h._code == 200, h._code
    assert h.sent_headers.get("Content-Type") == "image/webp", h.sent_headers
    print("ok studio images served with sniffed content type")



def test_data_url_sniffs_real_bytes():
    with tempfile.TemporaryDirectory() as t:
        webp = Path(t, "a.jpg")
        webp.write_bytes(b"RIFF" + b"\x00" * 4 + b"WEBP" + b"\x00" * 10)
        assert image_gen_mod._data_url(webp).startswith("data:image/webp;base64,")
        jpeg = Path(t, "b.jpg")
        jpeg.write_bytes(bytes([255, 216, 255, 0]))
        assert image_gen_mod._data_url(jpeg).startswith("data:image/jpeg;base64,")
    print("ok data URLs declare sniffed mediatype, not extension")


def test_fallback_reason_carries_api_body():
    import io
    import os
    import urllib.error as _urlerror
    real_post = image_gen_mod._post_json
    prev_key = os.getenv("MUSEIMAGES_DIR")
    with tempfile.TemporaryDirectory() as t:
        if True:
            (Path(t, ".env")).write_text("MIDJOURNEY_API_KEY=k\n")
            (Path(t, "settings.json")).write_text(json.dumps({}))
            os.environ["MUSEIMAGES_DIR"] = t
            out = Path(t) / "outs"
            imgs = out / "Ch9" / "studio_images"
            imgs.mkdir(parents=True)
            (imgs / "sheet_Sita_final.jpg").write_bytes(b"j")

            def reject(url, payload, key):
                raise _urlerror.HTTPError(
                    url, 400, "Bad Request", {},
                    io.BytesIO(b"{\"error\": \"unsupported image part\"}"))
            image_gen_mod._post_json = reject
            try:
                image_gen_mod.generate_sync(
                    prompt="Sita", aspect="16:9", file_prefix="slide_01",
                    dest_dir=imgs, kind="panel",
                    cast=[{"name": "Sita", "ref": "Sita"}],
                    log={"dir": str(imgs), "slide": 1})
                raise AssertionError("expected failure after fallback also fails")
            except Exception as e:
                assert "unsupported image part" in str(e), str(e)[:200]
        image_gen_mod._post_json = real_post
        if prev_key is None:
            os.environ.pop("MUSEIMAGES_DIR", None)
        else:
            os.environ["MUSEIMAGES_DIR"] = prev_key
    print("ok fallback path surfaces API body on total failure")



def test_turn_body_gate_rejects_before_spend():
    good_str = {"model": "muse-image-1.0", "input": "a sage at dawn",
                "tools": [{"type": "image_generation", "size": "1536x1024"}]}
    good_list = {"model": "muse-image-1.0",
                 "input": [{"role": "user", "content": [
                     {"type": "input_text", "text": "x"},
                     {"type": "input_image", "image_url": "data:,"}]}],
                 "tools": [{"type": "image_generation", "size": "1024x1536"}]}
    image_gen_mod._validate_turn_body(good_str)
    image_gen_mod._validate_turn_body(good_list)
    bad_bodies = [
        dict(good_str, input={"role": "user", "content": []}),
        dict(good_str, input=42),
        dict(good_str, tools=[{"type": "image_generation", "size": "999x999"}]),
        dict(good_str, tools=[]),
        dict(good_str, model=""),
    ]
    for bad in bad_bodies:
        try:
            image_gen_mod._validate_turn_body(bad)
            raise AssertionError(f"gate passed {bad!r}")
        except ValueError:
            pass

    real_post = image_gen_mod._post_json
    import base64
    canned = {"id": "resp_gate", "status": "completed",
              "output": [{"type": "image_generation_call",
                          "result": base64.b64encode(b"img").decode()}]}
    calls = []

    def ok_stub(url, payload, key):
        calls.append(payload)
        return canned
    image_gen_mod._post_json = ok_stub
    try:
        # legitimate traffic the gate must NOT block
        rid, _ = image_gen_mod._turn("k", "https://x", "a sage", "1536x1024",
                                     "resp_prev", [])
        assert rid == "resp_gate"
        assert calls[-1]["previous_response_id"] == "resp_prev"
        assert isinstance(calls[-1]["input"], str)
        with tempfile.TemporaryDirectory() as td:
            f = Path(td, "ref.jpg")
            f.write_bytes(bytes([255, 216, 255, 0]))
            rid2, _ = image_gen_mod._turn("k", "https://x", "a sage",
                                          "1024x1536", None,
                                          [("Sita", str(f))])
            assert rid2 == "resp_gate"
            assert isinstance(calls[-1]["input"], list)
    finally:
        image_gen_mod._post_json = real_post
    print("ok turn gate fails closed before any paid call")

if __name__ == "__main__":
    test_review_roundtrip()
    test_bundle_assembly()
    test_mock_deterministic()
    test_key_loading()
    test_prompt_building()
    test_refs_and_jobs()
    test_subject_ref_resolution()
    test_shared_sheet_final_visible_across_chapters()
    test_junk_subject_not_generatable()
    test_panel_candidates_resurface()
    test_sheet_resolve_errors()
    test_panel_select_validation()
    test_panel_final_resurfaces()
    test_panel_select_endpoint_routes()
    test_ch1_hand_corrections_hold()
    test_ch1_staging_rubric_holds()
    test_panel_cast_scene_first()
    test_panel_aspect_always_169()
    test_partition_refs_attaches_all()
    test_single_candidate_round()
    test_production_filenames_resurface()
    test_select_validation()
    test_panel_lineage()
    test_panel_file_anchor_and_labeled_fallback()
    test_panel_stale_description_override()
    test_generate_endpoint_no_500()
    test_studio_image_content_type()
    test_data_url_sniffs_real_bytes()
    test_fallback_reason_carries_api_body()
    test_turn_body_gate_rejects_before_spend()
    print("studio tests: 30/30 PASS")
