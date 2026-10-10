#!/usr/bin/env python3
"""MythologyMuse — upload-metadata stage (deterministic; no API calls).

Builds one copy-paste-ready metadata file per introduction/chapter:
``upload_metadata_<chapter>.json``. It holds everything needed to publish
the finished assets without re-reading the pipeline:

  youtube  — ONE upload per chapter (``video_<ch>_dual.mp4`` with its muxed
             eng+hin tracks). Default-language block plus a localized block
             for the second language, tags, category, playlist, audience,
             timestamp chapters, and the padded full-length WAVs that feed
             Studio's additional-audio-track step.
  spotify  — TWO monolingual episodes per chapter in a single show
             (Spotify has no second-audio-track concept: one file = one
             language). Same season/episode numbers, ``[Hindi]`` /
             ``[English]`` title suffixes, each pointing at its padded WAV.

Dual-audio rule: YouTube localizes metadata on a single video (no split
views); Spotify duplicates the episode per language (no other option).
Both languages' copy is therefore always generated.

Reads (under <mythology>/outputs/<chapter>/, all optional except script):
    script_<chapter>.json                  (required: segment texts)
    audio_manifest_<chapter>.json          (optional: per-chunk durations)
    video_manifest_<chapter>.json          (optional: confirms dual build)
Writes:
    upload_metadata_<chapter>.json

Usage:
    python3 tools/metadata_stage.py --chapter Book_0_Introduction
    python3 tools/metadata_stage.py --chapter Book_1_Bala_Kanda_Chapter_1

Exit: 0 wrote file (limits valid), 2 bad invocation / missing script.
Limits (YouTube upload page; Spotify for Creators Details page):
    youtube title <= 100 chars, description <= 5000 chars,
    tags joined <= 500 chars.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from muse_client import assert_inside, resolve_mythology_root  # noqa: E402

YT_TITLE_MAX = 100
YT_DESC_MAX = 5000
YT_TAGS_MAX = 500

SERIES_EN = "Mythic Tales and Today's Truth"
SERIES_HI = "पौराणिक कथाएँ और आज का सच"
NARRATOR = "Kavya"
CATEGORY = "Education"
PLAYLIST_EN = "Ramayana — Mythic Tales and Today's Truth (Hindi + English)"
PLAYLIST_HI = "रामायण — पौराणिक कथाएँ और आज का सच (हिंदी + English)"
MUSIC_CREDIT = (
    'Background music: "Meditation Impromptu 01" by Kevin MacLeod '
    "(incompetech.com) — Licensed under CC-BY 4.0: "
    "https://creativecommons.org/licenses/by/4.0/"
)
SOURCE_CREDIT_EN = (
    "Based on Manmatha Nath Dutt's prose Ramayana "
    "(Valmiki text via Project Gutenberg); structure, order and "
    "completeness kept, language simplified."
)
SOURCE_CREDIT_HI = (
    "आधार: मनमथा नाथ दत्त का गद्य-रामायण "
    "(प्रोजेक्ट गुटेनबर्ग के वाल्मीकि-पाठ पर); मूल संरचना, क्रम और "
    "पूर्णता ज्यों की त्यों, भाषा सरल-आधुनिक।"
)
FORMAT_EN = (
    "Each episode has two parts: Kavya narrates the tale, then pauses "
    "for reflective questions that connect it to today's decisions and "
    "relationships. Told in simple Hindi with a full English rendering."
)
FORMAT_HI = (
    "हर कड़ी दो भागों में: पहले काव्या कथा सुनाती हैं, फिर ठहरकर "
    "चिंतन-प्रश्नों पर विचार होता है जो कथा को आज के निर्णयों और "
    "संबंधों से जोड़ते हैं। सरल-आधुनिक हिंदी में, हर पंक्ति के सहज "
    "अंग्रेज़ी रूप के साथ।"
)

# Hand-locked per-chapter topics. Unknown future chapters fall back to a
# templated topic derived from the book/chapter numbers (see _fallback_info).
CHAPTER_INFO: dict[str, dict[str, str]] = {
    "Book_0_Introduction": {
        "topic_en": "Intro — Beginning the Ramayana Journey",
        "topic_hi": "परिचय — रामायण यात्रा का शुभारंभ",
        "blurb_en": (
            "Kavya opens the journey: what the Ramayana is, why Dutt's "
            "translation grounds every episode, how each tale pairs story "
            "with reflection, and how first-time listeners should begin."
        ),
        "blurb_hi": (
            "काव्या यात्रा का शुभारंभ करती हैं: रामायण क्या है, हर कड़ी "
            "दत्त के अनुवाद पर क्यों टिकी है, हर कथा के साथ चिंतन-प्रश्न "
            "क्यों हैं, और पहली बार सुनने वाला श्रोता शुरुआत कैसे करे।"
        ),
    },
    "Book_1_Bala_Kanda_Chapter_1": {
        "topic_en": "Who Is the Complete Man? Valmiki Questions Narada",
        "topic_hi": "पूर्ण पुरुष कौन है? वाल्मीकि का नारद से प्रश्न",
        "blurb_en": (
            "Valmiki asks Narada who in this age is full of dharma, truth "
            "and compassion; Narada answers with Rama's brief tale, the "
            "epic's executive summary."
        ),
        "blurb_hi": (
            "वाल्मीकि नारद से पूछते हैं — इस युग में धर्म, सत्य और करुणा "
            "से भरा पूर्ण पुरुष कौन है; नारद राम की संक्षिप्त कथा सुनाते "
            "हैं, महाकाव्य का कार्यकारी सारांश।"
        ),
    },
    "Book_1_Bala_Kanda_Chapter_2": {
        "topic_en": "The Curse That Became Compassion — Birth of the Shloka",
        "topic_hi": "शाप से करुणा तक — श्लोक का जन्म",
        "blurb_en": (
            "Grief over the slain krauncha bursts from Valmiki as the first "
            "shloka; Brahma turns the wound into work and orders the Rama "
            "tale sung."
        ),
        "blurb_hi": (
            "क्रौंच-वध के शोक से वाल्मीकि के मुख से पहला श्लोक फूटता है; "
            "ब्रह्मा घाव को कार्य में बदलकर राम-कथा गाने का आदेश देते हैं।"
        ),
    },
    "Book_1_Bala_Kanda_Chapter_3": {
        "topic_en": "Seeing the Tale in Yoga — Facing East",
        "topic_hi": "योग में कथा-दर्शन — पूर्वाभिमुख ध्यान",
        "blurb_en": (
            "What Narada told, Valmiki now beholds: seated facing east, he "
            "sees the whole tale in yoga — and honestly keeps even Sita's "
            "renunciation after victory."
        ),
        "blurb_hi": (
            "नारद ने जो सुनाया, वाल्मीकि उसे योग में देखते हैं — पूर्व "
            "दिशा में बैठकर संपूर्ण कथा का दर्शन; विजय के बाद सीता-त्याग "
            "सहित सत्य ज्यों का त्यों।"
        ),
    },
    "Book_1_Bala_Kanda_Chapter_4": {
        "topic_en": "Kush and Lav Learn the Vedas, Then Sing Rama",
        "topic_hi": "कुश-लव: पहले वेद-बोध, फिर राम-कथा का गान",
        "blurb_en": (
            "Valmiki first wakes Kush and Lav to the meaning of the Vedas, "
            "then gives them the sweet Rama tale they will sing in Rama's "
            "own court."
        ),
        "blurb_hi": (
            "वाल्मीकि पहले कुश-लव को वेदों के अर्थ से जगाते हैं, फिर मधुर "
            "राम-कथा सौंपते हैं जिसे वे राम के ही दरबार में गाएँगे।"
        ),
    },
    "Book_1_Bala_Kanda_Chapter_5": {
        "topic_en": "Kings Before Rama — Lineage as Restraint",
        "topic_hi": "राम से पहले राजा — संयम ही सभ्यता",
        "blurb_en": (
            "Before Rama is born, the tale sings bygone kings — Prajapati, "
            "Ikshvaku, Sagara: lineage as measure, where might that spares "
            "the hidden and the fleeing defines civilization."
        ),
        "blurb_hi": (
            "राम के जन्म से पहले बीते राजाओं का गान — प्रजापति, इक्ष्वाकु, "
            "सगर: वंशावली ही मापदंड, जहाँ छिपे और भागते पर वार न करने वाला "
            "संयम सभ्यता को परिभाषित करता है।"
        ),
    },
    "Book_1_Bala_Kanda_Chapter_6": {
        "topic_en": "The City Before the Hero — Ayodhya Described",
        "topic_hi": "नायक से पहले नगरी — अयोध्या का वर्णन",
        "blurb_en": (
            "Before Rama himself, Valmiki describes Ayodhya in full — the "
            "city of dharma whose adornment and order prefigure its king."
        ),
        "blurb_hi": (
            "राम से पहले वाल्मीकि अयोध्या का पूर्ण वर्णन करते हैं — धर्म "
            "की नगरी, जिसकी शोभा और व्यवस्था अपने राजा का पूर्वाभास देती है।"
        ),
    },
}

BASE_TAGS = [
    "ramayana", "ramayan", "ramayan katha", "ramayana hindi",
    "ramayana english", "bala kanda", "valmiki ramayana",
    "manmatha nath dutt", "kavya narration", "hindu mythology",
    "indian mythology podcast", "dharma", "ram katha hindi",
    "mythic tales and todays truth",
]


def _chapter_numbers(chapter: str) -> tuple[int, int, str]:
    """Return (season, episode, kind) without the strict Chapter_M parser.

    kind is 'intro' for Book_N_Introduction, else 'chapter'.
    """
    m = re.fullmatch(r"(Book_\d+_.+?)(?:_Chapter_(\d+))?", chapter)
    if not m:
        raise SystemExit(f"bad chapter id: {chapter!r}")
    book = m.group(1)
    season_m = re.match(r"Book_(\d+)_", book)
    season = int(season_m.group(1)) if season_m else 0
    if m.group(2) is not None:
        return season, int(m.group(2)), "chapter"
    return season, 0, "intro"


def _fallback_info(chapter: str) -> dict[str, str]:
    season, episode, kind = _chapter_numbers(chapter)
    label = f"S{season}E{episode}" if kind == "chapter" else "Introduction"
    return {
        "topic_en": f"{label} — Ramayana narration with reflection",
        "topic_hi": f"{label} — चिंतन सहित रामायण कथा",
        "blurb_en": (
            f"Kavya narrates {chapter} in simple Hindi with a full English "
            "rendering, then reflects on its choices for today's life."
        ),
        "blurb_hi": (
            f"काव्या {chapter} सरल हिंदी में सुनाती हैं, हर पंक्ति के सहज "
            "अंग्रेज़ी रूप के साथ, फिर उसके निर्णयों पर चिंतन होता है।"
        ),
    }


def _mmss(seconds: float) -> str:
    total = max(0, int(round(seconds)))
    return f"{total // 60:02d}:{total % 60:02d}"


def _segment_chapters(script: list[dict], durations: list[float] | None,
                      info: dict[str, str]) -> list[dict]:
    """YouTube timestamp chapters: one per script segment when timed."""
    if not durations or len(durations) != len(script):
        return []
    rows: list[dict] = []
    t = 0.0
    for i, seg in enumerate(script):
        en = re.sub(r"\s*<[^>]+>\s*", "", seg.get("text_en", "")).strip()
        hi = re.sub(r"\s*<[^>]+>\s*", "", seg.get("text", "")).strip()
        en_words = en.split()
        hi_words = hi.split()
        en_short = " ".join(en_words[:7]) + ("…" if len(en_words) > 7 else "")
        hi_short = " ".join(hi_words[:7]) + ("…" if len(hi_words) > 7 else "")
        rows.append({"start": _mmss(t),
                     "title_en": en_short or f"Part {i + 1}",
                     "title_hi": hi_short or f"भाग {i + 1}"})
        t += durations[i]
    return rows


def _check_limits(yt_title: str, yt_desc: str, tags: list[str]) -> dict:
    return {
        "youtube_title_chars": len(yt_title),
        "youtube_title_ok": len(yt_title) <= YT_TITLE_MAX,
        "youtube_description_chars": len(yt_desc),
        "youtube_description_ok": len(yt_desc) <= YT_DESC_MAX,
        "youtube_tags_chars": len(",".join(tags)),
        "youtube_tags_ok": len(",".join(tags)) <= YT_TAGS_MAX,
    }


def build_metadata(myth_root: Path, chapter: str) -> dict:
    chapter_dir = assert_inside(myth_root, Path("outputs") / chapter)
    script_path = chapter_dir / f"script_{chapter}.json"
    if not script_path.is_file():
        raise SystemExit(f"missing script (run podcast stage first): {script_path}")
    script = json.loads(script_path.read_text(encoding="utf-8"))
    info = CHAPTER_INFO.get(chapter, _fallback_info(chapter))
    season, episode, kind = _chapter_numbers(chapter)

    durations: list[float] | None = None
    duration_s: float | None = None
    audio_path = chapter_dir / f"audio_manifest_{chapter}.json"
    if audio_path.is_file():
        try:
            manif = json.loads(audio_path.read_text(encoding="utf-8"))
            chunks = manif.get("chunks", [])
            durations = [max(c["en"]["duration_s"], c["hi"]["duration_s"])
                         for c in chunks
                         if "en" in c and "hi" in c]
            duration_s = round(sum(durations), 1) if durations else None
            if durations and len(durations) != len(script):
                durations = None  # stale manifest: no timestamp chapters
        except (json.JSONDecodeError, KeyError, TypeError, OSError):
            durations = None

    ep_tag = f"S{season}E{episode}" if kind == "chapter" else "Intro"
    yt_title = f"{SERIES_HI} | {info['topic_hi']}"
    yt_title_en = f"{SERIES_EN} | {info['topic_en']}"
    if len(yt_title) > YT_TITLE_MAX:  # never ship an over-long default title
        yt_title = f"{SERIES_HI} | {ep_tag}"
    if len(yt_title_en) > YT_TITLE_MAX:
        yt_title_en = f"{SERIES_EN} | {ep_tag}"

    chapters = _segment_chapters(script, durations, info)
    chapter_lines = "\n".join(f"{r['start']} {r['title_hi']}" for r in chapters)
    chapter_lines_en = "\n".join(f"{r['start']} {r['title_en']}" for r in chapters)

    yt_desc_parts = [
        f"{info['blurb_hi']}",
        "",
        f"कथा: काव्या • {len(script)} खंड • {FORMAT_HI}",
        f"स्रोत: {SOURCE_CREDIT_HI}",
        "",
        "इस वीडियो में हिंदी और English दोनों ऑडियो ट्रैक हैं — "
        "प्लेयर में ऑडियो ट्रैक बदलकर भाषा चुनें।",
        "",
        MUSIC_CREDIT,
    ]
    if chapter_lines:
        yt_desc_parts += ["", "अध्याय (Chapters):", chapter_lines]
    yt_desc_parts += ["", f"#{' #'.join(['रामायण', 'Ramayana', 'BalaKanda' if season == 1 else 'Introduction', 'Kavya'])}"]
    yt_desc = "\n".join(yt_desc_parts)

    yt_desc_en_parts = [
        f"{info['blurb_en']}",
        "",
        f"Narrated by {NARRATOR} • {len(script)} segments • {FORMAT_EN}",
        f"Source: {SOURCE_CREDIT_EN}",
        "",
        "This video carries both Hindi and English audio tracks — "
        "switch audio tracks in the player to change language.",
        "",
        MUSIC_CREDIT,
    ]
    if chapter_lines_en:
        yt_desc_en_parts += ["", "Chapters:", chapter_lines_en]
    yt_desc_en = "\n".join(yt_desc_en_parts)

    tags = list(BASE_TAGS)
    if season == 1:
        tags.append("ayodhya")
    if kind == "intro":
        tags.append("ramayana introduction")

    if kind == "intro":
        sp_title_hi = f"{info['topic_hi']} [Hindi]"
        sp_title_en = f"{info['topic_en']} [English]"
    else:
        sp_title_hi = f"अध्याय {episode}: {info['topic_hi']} [Hindi]"
        sp_title_en = f"Chapter {episode}: {info['topic_en']} [English]"
    sp_desc_hi = "\n".join([
        f"{info['blurb_hi']}",
        "",
        f"कथा: काव्या • {FORMAT_HI}",
        f"स्रोत: {SOURCE_CREDIT_HI}",
        f"यह कड़ी हिंदी में है; अंग्रेज़ी रूप अलग एपिसोड में उपलब्ध है "
        f"(S{season}E{episode} [English])।",
    ])
    sp_desc_en = "\n".join([
        f"{info['blurb_en']}",
        "",
        f"Narrated by {NARRATOR} • {FORMAT_EN}",
        f"Source: {SOURCE_CREDIT_EN}",
        f"This episode is in English; the Hindi telling is a separate "
        f"episode (S{season}E{episode} [Hindi]).",
    ])

    limits = _check_limits(yt_title, yt_desc, tags)
    limits["youtube_localized_title_chars"] = len(yt_title_en)
    limits["youtube_localized_title_ok"] = len(yt_title_en) <= YT_TITLE_MAX
    limits["youtube_localized_description_chars"] = len(yt_desc_en)
    limits["youtube_localized_description_ok"] = len(yt_desc_en) <= YT_DESC_MAX

    return {
        "chapter": chapter,
        "series": {"title_en": SERIES_EN, "title_hi": SERIES_HI},
        "season": season,
        "episode": episode,
        "kind": kind,
        "assets": {
            "video_dual": f"video_{chapter}_dual.mp4",
            "audio_en": f"audio_track_{chapter}_en.wav",
            "audio_hi": f"audio_track_{chapter}_hi.wav",
            "duration_s": duration_s,
            "durations_timed": durations is not None,
        },
        "youtube": {
            "how": ("Upload video_dual once. Set default language Hindi, "
                    "default audio Hindi; add English as an additional audio "
                    "track (use the audio_en WAV), then paste the localized "
                    "English title/description."),
            "upload_file": f"video_{chapter}_dual.mp4",
            "default_language": "hi",
            "default_audio": "hi",
            "title": yt_title,
            "description": yt_desc,
            "tags": tags,
            "category": CATEGORY,
            "playlist": PLAYLIST_HI,
            "audience": "general — not made for kids",
            "chapters": chapters,
            "additional_audio_tracks": [
                {"language": "hi", "file": f"audio_track_{chapter}_hi.wav",
                 "role": "default"},
                {"language": "en", "file": f"audio_track_{chapter}_en.wav",
                 "role": "additional"},
            ],
            "captions": ("Upload Hindi + English subtitles from "
                         "hindi/english_narration_<ch>.txt once timed files "
                         "exist."),
            "localized": {
                "en": {"title": yt_title_en, "description": yt_desc_en,
                       "playlist": PLAYLIST_EN},
            },
        },
        "spotify": {
            "strategy": ("Two monolingual episodes in ONE show (one file = "
                         "one language). Same season/episode numbers; "
                         "language suffix in the title."),
            "show": {"title_en": SERIES_EN, "title_hi": SERIES_HI},
            "episodes": {
                "hi": {
                    "upload_file": f"audio_track_{chapter}_hi.wav",
                    "title": sp_title_hi,
                    "description": sp_desc_hi,
                    "season": season, "episode": episode,
                    "language": "hi", "episode_type": "full",
                    "explicit": False,
                    "artwork": "show-level cover (per-episode art optional)",
                },
                "en": {
                    "upload_file": f"audio_track_{chapter}_en.wav",
                    "title": sp_title_en,
                    "description": sp_desc_en,
                    "season": season, "episode": episode,
                    "language": "en", "episode_type": "full",
                    "explicit": False,
                    "artwork": "show-level cover (per-episode art optional)",
                },
            },
        },
        "limits_check": limits,
    }


def write_metadata(myth_root: Path, chapter: str) -> tuple[int, Path]:
    meta = build_metadata(myth_root, chapter)
    chapter_dir = assert_inside(myth_root, Path("outputs") / chapter)
    out = chapter_dir / f"upload_metadata_{chapter}.json"
    out.write_text(json.dumps(meta, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    bad = [k for k, v in meta["limits_check"].items() if k.endswith("_ok") and not v]
    if bad:
        print(f"metadata limits FAILED ({', '.join(bad)}); file kept: {out}",
              file=sys.stderr)
        return 1, out
    print(f"wrote {out}")
    return 0, out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build upload metadata for a chapter")
    ap.add_argument("--mythology", default="mythologies/ramayana_dutt")
    ap.add_argument("--chapter", default="")
    args = ap.parse_args(argv)
    if not args.chapter:
        print("nothing to do: give --chapter", file=sys.stderr)
        return 2
    try:
        myth_root = resolve_mythology_root(args.mythology)
    except SystemExit as e:
        print(e.code, file=sys.stderr)
        return 2
    try:
        rc, _ = write_metadata(myth_root, args.chapter)
        return rc
    except SystemExit as e:
        print(e.code, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
