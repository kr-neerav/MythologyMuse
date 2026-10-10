#!/usr/bin/env python3
"""MythologyMuse — video build stage (explicit trigger; outside run_chapter).

Reads a chapter's ``av_mapping_<chapter>.json`` (script segment -> slide
images) plus the per-language TTS WAVs from ``generate_audio_gemini.py``
(``audio_<lang>/chunk_*.wav``) and assembles one MP4 per language with the
system ffmpeg binary (stdlib subprocess only — no new dependencies).

Timing rule: each audio chunk sets the hold duration, and a chunk carrying
several images splits its time by the mapping's panel shares (even split
in v1), so every mapped slide stays on screen (the av-map guarantee that
each slide is used exactly once is kept on screen, never cut). Every
segment carries its cue on the timeline (``start_s``/``end_s`` seconds)
plus the image prompt behind the still (``muse_prompt``), so the manifest
reads as a cue sheet: which slide is up when, and what is in it. Motion comes from ``--motion`` and the join from
``--transition`` (see --help; default is a calm Ken Burns drift — slow
pull-outs and low pans that never crop the frame, light sway and grain,
holds over 8s renewed into fresh shots, text-heavy discussion shots held
still — joined by cross-dissolves).

Reads (under <mythology>/outputs/<chapter>/):
    av_mapping_<chapter>.json
    audio_<lang>/chunk_*.wav (+ audio_manifest_<chapter>.json when present)
    studio_images/slide_*_final.jpg
Writes:
    video_<chapter>_<lang>.mp4
    video_manifest_<chapter>.json  (per-lang segments, motion, durations, cmd)

Usage:
    python3 tools/build_video.py --chapter Book_1_Bala_Kanda_Chapter_1 --dry-run
    python3 tools/build_video.py --chapter Book_1_Bala_Kanda_Chapter_1 --lang hi
    python3 tools/build_video.py --chapter Book_1_Bala_Kanda_Chapter_1 --lang both --motion static --transition cut

Exit codes (match the stage contract):
    0  success (every requested language has an MP4)
    1  ffmpeg failed (best-effort output kept, error on stderr)
    2  bad invocation / missing inputs
"""

from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import subprocess
import sys
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from muse_client import assert_inside, resolve_mythology_root  # noqa: E402

FPS_DEFAULT = 30
SIZE_DEFAULT = (1920, 1080)
XFADE_DEFAULT_S = 0.5
# zoompan drifts smoothly only from an oversized plate (downsampled to --size).
PLATE_W, PLATE_H = 3840, 2160

MOTIONS = ("kenburns", "static")
TRANSITIONS = ("xfade", "cut")


def parse_size(text: str) -> tuple[int, int]:
    try:
        w, h = text.lower().split("x")
        w_i, h_i = int(w), int(h)
    except ValueError:
        raise SystemExit(f"bad --size {text!r} (expected WxH, e.g. 1920x1080)")
    if w_i < 160 or h_i < 160 or w_i > 7680 or h_i > 4320:
        raise SystemExit(f"bad --size {text!r} (sane range 160..7680)")
    return w_i, h_i


def wav_duration_s(path: Path) -> float:
    with wave.open(str(path), "rb") as w:
        rate = w.getframerate() or 24000
        return w.getnframes() / float(rate)


def frames_for(duration_s: float, fps: int) -> int:
    return max(2, round(duration_s * fps))


def split_durations(chunk_s: float, n_images: int) -> list[float]:
    """Even split of one audio chunk over its images (order preserved)."""
    if n_images <= 0:
        return []
    each = chunk_s / n_images
    return [each] * n_images


def clamp_xfade(want_s: float, seg_durs: list[float]) -> float:
    """Keep a dissolve shorter than the segments it overlaps."""
    if len(seg_durs) < 2 or not seg_durs:
        return 0.0
    return max(0.0, min(want_s, 0.4 * min(seg_durs)))


def xfade_offsets(seg_durs: list[float], fade_s: float) -> list[float]:
    """Cumulative xfade offsets: o_1 = d_0 - t, o_k = o_{k-1} + d_k - t."""
    offsets: list[float] = []
    acc = seg_durs[0] if seg_durs else 0.0
    for d in seg_durs[1:]:
        offsets.append(acc - fade_s)
        acc = acc - fade_s + d
    return offsets


def kenburns_exprs(i: int, frames: int) -> tuple[str, str, str]:
    """Calm drift per shot: pull-out, pan left, pan right, plus sway.

    No push-ins: tightening the frame crops characters out, while a
    pull-out only ever reveals. Amplitudes stay small (~15% zoom, pans at
    a low 1.12 zoom) with a slow ~7s sway (plate coordinates, ~2x output
    pixels) so motion is felt, not noticed.
    """
    f = max(frames, 2)
    sway_x = f"(12*sin(2*PI*on/200))"
    sway_y = f"(8*cos(2*PI*on/260))"
    cx, cy = "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    if i % 3 == 0:  # pull out 1.15 -> 1.0, centered (reveals, never crops)
        return (f"max(1.15-0.15*on/{f},1.0)",
                f"{cx}+{sway_x}", f"{cy}+{sway_y}")
    if i % 3 == 1:  # pan left -> right at a low zoom
        return ("1.12", f"((iw-iw/zoom)*on/{f})+{sway_x}", f"{cy}+{sway_y}")
    # pan right -> left at a low zoom
    return ("1.12",
            f"((iw-iw/zoom)*(1-on/{f}))+{sway_x}", f"{cy}+{sway_y}")


def segment_chain(i: int, motion: str, duration_s: float,
                  width: int, height: int, fps: int) -> str:
    """ffmpeg -vf body turning still input [i:v] into a duration_s clip."""
    if motion == "static":
        pad = max(0.0, duration_s - 1.0 / fps)
        return (
            f"scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},setsar=1,fps={fps},format=yuv420p,"
            # stop_mode=clone: the default (add) pads with BLACK frames.
            f"tpad=stop=-1:stop_mode=clone:stop_duration={pad:.3f}"
        )
    z, x, y = kenburns_exprs(i, frames_for(duration_s, fps))
    return (
        f"scale={PLATE_W}:{PLATE_H}:force_original_aspect_ratio=increase,"
        f"crop={PLATE_W}:{PLATE_H},"
        f"zoompan=z='{z}':x='{x}':y='{y}':"
        f"d={frames_for(duration_s, fps)}:fps={fps}:s={width}x{height},"
        f"setsar=1,fps={fps},format=yuv420p,"
        f"noise=alls=3:allf=t"  # light animated grain, barely visible
    )


# Long holds go stale: cut them into renewed shots (same image, new move)
# the way documentaries do — a dissolve between two moves of one still
# reads as fresh motion, not a repeated slide.
MAX_SHOT_S = 8.0


def expand_shots(segments: list[dict],
                 max_shot_s: float = MAX_SHOT_S) -> list[dict]:
    """Split over-long screen segments into ~max_shot_s shots."""
    shots: list[dict] = []
    for s in segments:
        n = max(1, math.ceil(s["duration_s"] / max_shot_s))
        each = round(s["duration_s"] / n, 3)
        for k in range(n):
            shots.append({**s, "duration_s": each,
                          "shot": k + 1, "shots": n})
    return shots


def build_video_chain(seg_durs: list[float], motions: list[str],
                      transition: str, fade_s: float,
                      width: int, height: int, fps: int
                      ) -> tuple[str, float]:
    """Picture half of the graph: N stills joined into [vout].

    motions[i] picks the move for shot i, so text-heavy (discussion)
    shots can hold still while scenes drift.
    """
    n = len(seg_durs)
    parts = [f"[{i}:v]{segment_chain(i, motions[i], seg_durs[i], width, height, fps)}[v{i}]"
             for i in range(n)]
    vdur = sum(seg_durs)
    if transition == "xfade" and n > 1:
        fade = clamp_xfade(fade_s, seg_durs)
        if fade <= 0.0:  # degenerate sub-frame segments: hard cut instead
            transition = "cut"
        else:
            offs = xfade_offsets(seg_durs, fade)
            parts.append(f"[v0][v1]xfade=transition=fade:duration={fade:.3f}:"
                         f"offset={offs[0]:.3f}[x1]")
            for k in range(2, n):
                parts.append(f"[x{k - 1}][v{k}]"
                             f"xfade=transition=fade:duration={fade:.3f}:"
                             f"offset={offs[k - 1]:.3f}[x{k}]")
            vdur = sum(seg_durs) - fade * (n - 1)
            vcat = f"[x{n - 1}]"
    if transition == "cut" or n == 1:
        vcat = "".join(f"[v{i}]" for i in range(n))
        if n > 1:
            parts.append(f"{vcat}concat=n={n}:v=1:a=0[vcat]")
            vcat = "[vcat]"
    parts.append(f"{vcat}trim=0:{vdur:.3f},setpts=PTS-STARTPTS,"
                 f"fps={fps},format=yuv420p[vout]")
    return ";".join(parts), vdur


def music_bed_chain(music_idx: int, vdur: float, db: float,
                    label: str) -> str:
    """Loop-ready bed: trimmed to the picture, quiet, faded at both ends."""
    vol = 10.0 ** (db / 20.0)
    fade_d = min(4.0, vdur / 2.0)
    fade_st = max(0.0, vdur - fade_d)
    return (f"[{music_idx}:a]atrim=0:{vdur:.3f},volume={vol:.4f},"
            f"afade=t=in:st=0:d=2,afade=t=out:st={fade_st:.3f}:d={fade_d:.3f}"
            f"[{label}]")


def mix_chain(narr_label: str, bed_label: str, out_label: str) -> str:
    """Narration at full level with the quiet bed underneath (no renorm)."""
    return (f"[{narr_label}][{bed_label}]amix=inputs=2:duration=first:"
            f"dropout_transition=0:normalize=0[{out_label}]")


def build_audio_chain(first_input: int, count: int, vdur: float,
                      label: str) -> str:
    """Join `count` wav inputs into [label], padded/trimmed to the picture."""
    achain = "".join(f"[{first_input + k}:a]" for k in range(count))
    # NOTE: the generic concat filter (not aconcat — missing from some
    # ffmpeg builds, incl. this env's 8.1.1) joins the audio-only inputs.
    return (f"{achain}concat=n={count}:v=0:a=1,"
            f"apad,atrim=0:{vdur:.3f},asetpts=PTS-STARTPTS[{label}]")


def build_filter(seg_durs: list[float], motion: str, transition: str,
                 fade_s: float, width: int, height: int, fps: int,
                 n_audio: int) -> tuple[str, float]:
    """One -filter_complex joining N stills + M wavs. Returns (graph, vdur).

    Image inputs are 0..N-1 (single stills); audio inputs follow them.
    """
    vpart, vdur = build_video_chain(seg_durs, [motion] * len(seg_durs),
                                    transition, fade_s, width, height, fps)
    return ";".join([vpart, build_audio_chain(len(seg_durs), n_audio,
                                              vdur, "aout")]), vdur


def shot_motion(shot: dict, motion: str) -> str:
    """Per-shot move: text-heavy discussion shots hold still for readability,
    narration scenes use the requested --motion."""
    if motion == "kenburns" and shot.get("kind") == "discussion":
        return "static"
    return motion


def plan_shots(segments: list[dict], transition: str,
               fade_s: float) -> tuple[list[dict], float]:
    """Expand segments to shots, stretched so dissolves cost added time.

    Returns (shots, effective fade). Without the stretch each dissolve
    would shorten the video below the narration and cut the audio tail.
    """
    shots = expand_shots(segments)
    fade = 0.0
    if transition == "xfade" and len(shots) > 1:
        fade = clamp_xfade(fade_s, [s["duration_s"] for s in shots])
        if fade > 0:
            extra = fade * (len(shots) - 1) / len(shots)
            shots = [{**s, "duration_s": round(s["duration_s"] + extra, 3)}
                     for s in shots]
    return shots, fade


def shot_timeline(shots: list[dict], transition: str, fade: float
                ) -> list[dict]:
    """Stamp video-timeline start_s/end_s on each shot (in place).

    With xfade the joins overlap by fade_s (shared dissolves); with cut
    (or a single shot) segments run contiguously. Mirrors
    build_video_chain so the manifest cue sheet matches the picture.
    """
    if transition == "xfade" and len(shots) > 1 and fade > 0:
        starts = [0.0] + [round(o, 3) for o in
                          xfade_offsets([s["duration_s"] for s in shots], fade)]
    else:
        starts = []
        acc = 0.0
        for s in shots:
            starts.append(round(acc, 3))
            acc = round(acc + s["duration_s"], 3)
    for shot, st in zip(shots, starts):
        shot["start_s"] = round(st, 3)
        shot["end_s"] = round(st + shot["duration_s"], 3)
    return shots


def load_mapping(chapter_dir: Path, chapter: str) -> tuple[list | None, str]:
    path = chapter_dir / f"av_mapping_{chapter}.json"
    if not path.is_file():
        return None, (f"no av_mapping file: {path} "
                      f"(run av_map_stage.py first)")
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        return None, f"av_mapping unreadable: {e}"
    chunks = body.get("chunks") if isinstance(body, dict) else None
    if not chunks:
        return None, "av_mapping has no chunks"
    return chunks, ""


def resolve_audio(chapter_dir: Path, chapter: str, lang: str,
                  n_seg: int) -> tuple[list[dict] | None, list[str]]:
    """Map each script segment to its WAV + duration. Returns (tracks, errs)."""
    manifest_path = chapter_dir / f"audio_manifest_{chapter}.json"
    manifest: dict = {}
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            manifest = {}
    man_slot = {(c.get("index"), lang): c.get(lang, {})
                for c in manifest.get("chunks", [])
                if isinstance(c, dict)} if isinstance(manifest, dict) else {}
    width = max(3, len(str(n_seg)))
    tracks: list[dict] = []
    errs: list[str] = []
    for s in range(n_seg):
        idx = s + 1
        rel = f"audio_{lang}/chunk_{idx:0{width}d}.wav"
        wav = chapter_dir / rel
        slot = man_slot.get((idx, lang), {})
        duration = slot.get("duration_s") if slot.get("status") == "ok" else None
        if not wav.is_file():
            errs.append(f"missing audio: {rel} "
                        f"(run generate_audio_gemini.py --lang {lang} first)")
            continue
        try:
            probed = round(wav_duration_s(wav), 3)
        except (wave.Error, EOFError, OSError) as e:
            errs.append(f"unreadable audio {rel}: {e}")
            continue
        if duration is None:
            duration = probed
        if duration <= 0:
            errs.append(f"zero-duration audio: {rel}")
            continue
        tracks.append({"script_index": s, "file": rel,
                       "duration_s": round(float(duration), 3)})
    if errs:
        return None, errs
    return tracks, []


def plan_segments(chunks: list, tracks: list[dict], chapter_dir: Path,
                  skip_missing: bool = False
                  ) -> tuple[list[dict] | None, list[str]]:
    """Expand mapping chunks into per-image screen segments. Returns (segs, errs).

    Each segment is a cue-sheet row: ``start_s``/``end_s`` on the audio
    timeline (contiguous, covering the track) plus ``muse_prompt``/``title``
    naming what is in the still. Per-image weights come from the mapping's
    panel ``share`` values (even split when a chunk carries no panels).
    """
    by_script = {t["script_index"]: t for t in tracks}
    segments: list[dict] = []
    errs: list[str] = []
    cursor = 0.0
    for chunk in chunks:
        s = chunk.get("script_index")
        track = by_script.get(s)
        if track is None:
            errs.append(f"chunk {chunk.get('chunk')}: no audio for script_index {s}")
            continue
        names = list(chunk.get("images") or [])
        if skip_missing:
            names = [n for n in names if (chapter_dir / n).is_file()]
        else:
            missing = [n for n in names if not (chapter_dir / n).is_file()]
            if missing:
                errs.append(f"chunk {chunk.get('chunk')}: missing images: "
                            + ", ".join(missing))
                continue
        if not names:
            errs.append(f"chunk {chunk.get('chunk')}: no images to show "
                        f"(slide {chunk.get('slides')})")
            continue
        panel_list = [p for p in (chunk.get("panels") or [])
                      if isinstance(p, dict)]
        by_image = {p.get("image"): p for p in panel_list}
        panels = [by_image.get(n) or
                  (panel_list[i] if i < len(panel_list)
                   and panel_list[i].get("image") == n else None)
                  for i, n in enumerate(names)]
        weights = []
        for p in panels:
            w = (p or {}).get("share")
            weights.append(w if isinstance(w, (int, float)) and w > 0 else 1.0)
        total_w = sum(weights) or float(len(names))
        durs_so_far: list[float] = []
        for k, (name, p, w) in enumerate(zip(names, panels, weights)):
            if k == len(names) - 1:  # last image takes the remainder
                dur = round(track["duration_s"] - sum(durs_so_far), 3)
            else:
                dur = round(track["duration_s"] * w / total_w, 3)
            durs_so_far.append(dur)
            p = p or {}
            start = round(cursor, 3)
            slide = p.get("slide")
            if not isinstance(slide, int):
                m = re.search(r"slide_(\d+)_final\.jpg$", name or "")
                slide = int(m.group(1)) if m else None
            segments.append({
                "image": name,
                "slide": slide,
                "chunk": chunk.get("chunk"),
                "kind": chunk.get("kind"),
                "script_index": s,
                "audio_file": track["file"],
                "duration_s": dur,
                "start_s": start,
                "end_s": round(start + dur, 3),
                "title": p.get("title"),
                "muse_prompt": p.get("muse_prompt"),
            })
            cursor = round(cursor + dur, 3)
    if errs:
        return None, errs
    return segments, []


def build_ffmpeg_cmd(image_paths: list[Path], audio_paths: list[Path],
                     filter_graph: str, out_path: Path, fps: int,
                     music_path: Path | None = None,
                     audio_label: str = "aout") -> list[str]:
    cmd = ["ffmpeg", "-y"]
    for p in image_paths:
        cmd += ["-i", str(p)]
    for p in audio_paths:
        cmd += ["-i", str(p)]
    if music_path is not None:
        cmd += ["-stream_loop", "-1", "-i", str(music_path)]
    return cmd + [
        "-filter_complex", filter_graph,
        "-map", "[vout]", "-map", f"[{audio_label}]",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-r", str(fps), "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        str(out_path),
    ]


def resolve_music(music: str) -> tuple[Path | None, str]:
    """Locate the bed track. Returns (path, err); "" means no music."""
    if not music:
        return None, ""
    p = Path(music)
    if not p.is_absolute():
        from muse_client import PROJECT_ROOT  # noqa: E402
        p = PROJECT_ROOT / p
    if not p.is_file():
        return None, f"music file not found: {music}"
    return p, ""


def build_one(myth_root: Path, chapter: str, lang: str, motion: str,
              transition: str, fade_s: float, width: int, height: int,
              fps: int, dry_run: bool, skip_missing: bool,
              music: str = "", music_db: float = -14.0) -> int:
    chapter_dir = assert_inside(myth_root, Path("outputs") / chapter)
    if not chapter_dir.is_dir():
        print(f"! video: no chapter dir {chapter_dir}", file=sys.stderr)
        return 2
    music_path, music_err = resolve_music(music)
    if music_err:
        print(f"! video [{lang}]: {music_err}", file=sys.stderr)
        return 2
    chunks, err = load_mapping(chapter_dir, chapter)
    if chunks is None:
        print(f"! video: {err}", file=sys.stderr)
        return 2
    tracks, errs = resolve_audio(chapter_dir, chapter, lang, len(chunks))
    if tracks is None:
        for e in errs:
            print(f"! video [{lang}]: {e}", file=sys.stderr)
        return 2
    segments, errs = plan_segments(chunks, tracks, chapter_dir,
                                   skip_missing=skip_missing)
    if segments is None:
        for e in errs:
            print(f"! video [{lang}]: {e}", file=sys.stderr)
        return 2
    shots, fade = plan_shots(segments, transition, fade_s)
    shots = shot_timeline(shots, transition, fade)
    seg_durs = [s["duration_s"] for s in shots]
    motions = [shot_motion(s, motion) for s in shots]
    vpart, vdur = build_video_chain(seg_durs, motions, transition, fade,
                                    width, height, fps)
    audio_label = "aout"
    gparts = [vpart, build_audio_chain(len(shots), len(tracks), vdur, "aout")]
    if music_path is not None:
        gparts += [music_bed_chain(len(shots) + len(tracks), vdur, music_db,
                                   "mbed"),
                   mix_chain("aout", "mbed", "mix")]
        audio_label = "mix"
    graph = ";".join(gparts)
    out_path = chapter_dir / f"video_{chapter}_{lang}.mp4"
    entry = {
        "lang": lang, "motion": motion, "transition": transition,
        "fade_s": fade,
        "fps": fps, "size": [width, height],
        "segments": shots, "segment_count": len(shots),
        "audio_total_s": round(sum(s["duration_s"] for s in segments), 3),
        "video_total_s": round(vdur, 3),
        "video_file": out_path.name, "dry_run": dry_run,
    }
    if music_path is not None:
        entry["music"] = {"file": str(music_path), "db": music_db}
    if dry_run:
        print(f"video [{lang}]: dry-run plan {len(shots)} shots "
              f"over {len(segments)} segments, {vdur:.1f}s, no ffmpeg call")
    else:
        if shutil.which("ffmpeg") is None:
            print("! video: ffmpeg not found on PATH", file=sys.stderr)
            return 1
        cmd = build_ffmpeg_cmd(
            [chapter_dir / s["image"] for s in shots],
            [chapter_dir / t["file"] for t in tracks],
            graph, out_path, fps, music_path=music_path,
            audio_label=audio_label)
        entry["ffmpeg_cmd"] = cmd
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            tail = (proc.stderr or "").strip().splitlines()[-5:]
            for line in tail:
                print(f"! video ffmpeg: {line}", file=sys.stderr)
            return 1
        print(f"video [{lang}]: {len(shots)} shots over "
              f"{len(segments)} segments, {vdur:.1f}s -> {out_path.name}")
    manifest_path = chapter_dir / f"video_manifest_{chapter}.json"
    prev: dict = {}
    if manifest_path.is_file():
        try:
            prev = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            prev = {}
    videos = prev.get("videos", {}) if isinstance(prev, dict) else {}
    videos[lang] = entry
    manifest_path.write_text(json.dumps(
        {"chapter": chapter, "videos": videos},
        ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


def build(myth_root: Path, chapter: str, langs: list[str], **kwargs) -> int:
    seen = {build_one(myth_root, chapter, lang, **kwargs) for lang in langs}
    if 1 in seen:  # an ffmpeg failure outranks missing inputs
        return 1
    if 2 in seen:
        return 2
    return 0


def write_manifest_entry(chapter_dir: Path, chapter: str,
                         key: str, entry: dict) -> None:
    manifest_path = chapter_dir / f"video_manifest_{chapter}.json"
    prev: dict = {}
    if manifest_path.is_file():
        try:
            prev = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            prev = {}
    videos = prev.get("videos", {}) if isinstance(prev, dict) else {}
    videos[key] = entry
    manifest_path.write_text(json.dumps(
        {"chapter": chapter, "videos": videos},
        ensure_ascii=False, indent=2), encoding="utf-8")


def build_dual(myth_root: Path, chapter: str, motion: str, transition: str,
               fade_s: float, width: int, height: int, fps: int,
               dry_run: bool, skip_missing: bool,
               music: str = "", music_db: float = -14.0) -> int:
    """One MP4 carrying both narration tracks (eng + hin), same length.

    The picture is cut to the longer track; the shorter is padded with
    trailing silence so both run exactly the video length. The two padded
    full-length WAVs are also written for direct upload (e.g. YouTube's
    additional-audio-track slot). With --music the same quiet bed runs
    under both tracks, carrying the tail where narration has ended.
    """
    chapter_dir = assert_inside(myth_root, Path("outputs") / chapter)
    if not chapter_dir.is_dir():
        print(f"! video: no chapter dir {chapter_dir}", file=sys.stderr)
        return 2
    music_path, music_err = resolve_music(music)
    if music_err:
        print(f"! video [dual]: {music_err}", file=sys.stderr)
        return 2
    chunks, err = load_mapping(chapter_dir, chapter)
    if chunks is None:
        print(f"! video: {err}", file=sys.stderr)
        return 2
    tracks_en, errs = resolve_audio(chapter_dir, chapter, "en", len(chunks))
    tracks_hi, errs_hi = resolve_audio(chapter_dir, chapter, "hi", len(chunks))
    if tracks_en is None or tracks_hi is None:
        for e in (errs if tracks_en is None else errs_hi):
            print(f"! video [dual]: {e}", file=sys.stderr)
        return 2
    segs_en, errs = plan_segments(chunks, tracks_en, chapter_dir,
                                  skip_missing=skip_missing)
    segs_hi, errs_hi = plan_segments(chunks, tracks_hi, chapter_dir,
                                     skip_missing=skip_missing)
    if segs_en is None or segs_hi is None:
        for e in (errs if segs_en is None else errs_hi):
            print(f"! video [dual]: {e}", file=sys.stderr)
        return 2
    tot_en = round(sum(s["duration_s"] for s in segs_en), 3)
    tot_hi = round(sum(s["duration_s"] for s in segs_hi), 3)
    base_lang = "en" if tot_en >= tot_hi else "hi"
    shots, fade = plan_shots(segs_en if base_lang == "en" else segs_hi,
                             transition, fade_s)
    shots = shot_timeline(shots, transition, fade)
    seg_durs = [s["duration_s"] for s in shots]
    n = len(shots)
    motions = [shot_motion(s, motion) for s in shots]
    vpart, vdur = build_video_chain(seg_durs, motions, transition, fade,
                                    width, height, fps)
    me, mh = len(tracks_en), len(tracks_hi)
    # Final per-track labels, with or without the bed mixed in.
    nen_m, nhi_m, nen_w, nhi_w = "aen_m", "ahi_m", "aen_w", "ahi_w"
    gparts = [vpart,
              build_audio_chain(n, me, vdur, "aen"),
              build_audio_chain(n + me, mh, vdur, "ahi")]
    if music_path is not None:
        midx = n + me + mh
        gparts += [music_bed_chain(midx, vdur, music_db, "mbed"),
                   "[mbed]asplit[m1][m2]",
                   mix_chain("aen", "m1", "xen"),
                   mix_chain("ahi", "m2", "xhi")]
        nen_m, nhi_m, nen_w, nhi_w = "xen_m", "xhi_m", "xen_w", "xhi_w"
        gparts += [f"[xen]asplit[{nen_m}][{nen_w}]",
                   f"[xhi]asplit[{nhi_m}][{nhi_w}]"]
    else:
        gparts += ["[aen]asplit[aen_m][aen_w]",
                   "[ahi]asplit[ahi_m][ahi_w]"]
    graph = ";".join(gparts)
    out_path = chapter_dir / f"video_{chapter}_dual.mp4"
    track_en = chapter_dir / f"audio_track_{chapter}_en.wav"
    track_hi = chapter_dir / f"audio_track_{chapter}_hi.wav"
    entry = {
        "motion": motion, "transition": transition, "fade_s": fade,
        "fps": fps, "size": [width, height], "base_lang": base_lang,
        "segments": shots, "segment_count": n,
        "en_total_s": tot_en, "hi_total_s": tot_hi,
        "video_total_s": round(vdur, 3),
        "video_file": out_path.name,
        "track_files": {"en": track_en.name, "hi": track_hi.name},
        "dry_run": dry_run,
    }
    if music_path is not None:
        entry["music"] = {"file": str(music_path), "db": music_db}
    if dry_run:
        print(f"video [dual]: base {base_lang} (en {tot_en:.1f}s / "
              f"hi {tot_hi:.1f}s), {n} shots, {vdur:.1f}s, no ffmpeg call")
    else:
        if shutil.which("ffmpeg") is None:
            print("! video: ffmpeg not found on PATH", file=sys.stderr)
            return 1
        cmd = ["ffmpeg", "-y"]
        for s in shots:
            cmd += ["-i", str(chapter_dir / s["image"])]
        for t in tracks_en + tracks_hi:
            cmd += ["-i", str(chapter_dir / t["file"])]
        if music_path is not None:
            cmd += ["-stream_loop", "-1", "-i", str(music_path)]
        cmd += ["-filter_complex", graph,
                "-map", "[vout]", "-map", f"[{nen_m}]", "-map", f"[{nhi_m}]",
                "-metadata:s:a:0", "language=eng",
                "-metadata:s:a:1", "language=hin",
                "-c:v", "libx264", "-preset", "medium", "-crf", "20",
                "-r", str(fps), "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "192k",
                "-movflags", "+faststart", str(out_path),
                "-map", f"[{nen_w}]", "-c:a", "pcm_s16le", str(track_en),
                "-map", f"[{nhi_w}]", "-c:a", "pcm_s16le", str(track_hi)]
        entry["ffmpeg_cmd"] = cmd
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            tail = (proc.stderr or "").strip().splitlines()[-5:]
            for line in tail:
                print(f"! video ffmpeg: {line}", file=sys.stderr)
            return 1
        print(f"video [dual]: base {base_lang}, {n} shots, {vdur:.1f}s -> "
              f"{out_path.name} (+ full-length en/hi WAVs)")
    write_manifest_entry(chapter_dir, chapter, "dual", entry)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="MythologyMuse video build stage")
    ap.add_argument("--mythology", default="mythologies/ramayana_dutt")
    ap.add_argument("--chapter", default="")
    ap.add_argument("--lang", choices=("en", "hi", "both"), default="both",
                    help="which TTS audio track to cut the video to")
    ap.add_argument("--dual", action="store_true",
                    help="one MP4 carrying both tracks (eng+hin): picture "
                         "follows the longer narration, the shorter is "
                         "silence-padded to match, and both full-length "
                         "WAVs are written for upload (ignores --lang)")
    ap.add_argument("--motion", choices=MOTIONS, default="kenburns",
                    help="kenburns: slow zoom/pan drift (default); "
                         "static: plain hold")
    ap.add_argument("--transition", choices=TRANSITIONS, default="xfade",
                    help="xfade: cross-dissolve between images (default); "
                         "cut: hard cut")
    ap.add_argument("--xfade-s", type=float, default=XFADE_DEFAULT_S,
                    help="dissolve length in seconds (clamped below the "
                         "shortest segment)")
    ap.add_argument("--fps", type=int, default=FPS_DEFAULT)
    ap.add_argument("--size", default="1920x1080",
                    help="output WxH (images are center-cropped to fill)")
    ap.add_argument("--dry-run", action="store_true",
                    help="no ffmpeg: validate inputs + write the plan only")
    ap.add_argument("--skip-missing", action="store_true",
                    help="show a chunk's rendered images only instead of "
                         "failing on unrendered ones")
    ap.add_argument("--music", default="",
                    help="background bed (e.g. assets/music/meditation_"
                         "impromptu_01.mp3): looped, mixed quietly under "
                         "the narration, faded at both ends")
    ap.add_argument("--music-db", type=float, default=-14.0,
                    help="bed level in dB below full scale (default -14: "
                         "audible in silence, well under speech)")
    args = ap.parse_args(argv)
    if not args.chapter:
        print("nothing to do: give --chapter", file=sys.stderr)
        return 2
    # NOTE: no parse_chapter_id gate — like av-map, any chapter dir works,
    # so Book_0_Introduction and other non-Chapter_M ids build too.
    try:
        myth_root = resolve_mythology_root(args.mythology)
    except SystemExit as e:
        print(e.code, file=sys.stderr)
        return 2
    if args.fps < 1 or args.fps > 120:
        print(f"bad --fps {args.fps}", file=sys.stderr)
        return 2
    width, height = parse_size(args.size)
    if args.dual:
        return build_dual(myth_root, args.chapter, motion=args.motion,
                          transition=args.transition, fade_s=args.xfade_s,
                          width=width, height=height, fps=args.fps,
                          dry_run=args.dry_run,
                          skip_missing=args.skip_missing,
                          music=args.music, music_db=args.music_db)
    langs = ("en", "hi") if args.lang == "both" else (args.lang,)
    return build(myth_root, args.chapter, list(langs), motion=args.motion,
                 transition=args.transition, fade_s=args.xfade_s,
                 width=width, height=height, fps=args.fps,
                 dry_run=args.dry_run, skip_missing=args.skip_missing,
                 music=args.music, music_db=args.music_db)


if __name__ == "__main__":
    raise SystemExit(main())
