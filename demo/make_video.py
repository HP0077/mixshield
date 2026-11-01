"""Demo video built from code: results/video/mixshield_demo.mp4 (1920x1080, 30 fps, H.264 + AAC), no video editor.

One slide per row of docs/video_script.md, in order. The voice sets the timing: each slide lasts as long as its voice
file plus 0.4 s, with a 0.2 s crossfade between slides. Inputs are in video_input/ (git-ignored):
  voice/01..18 (.m4a, .mp3 or .wav), one file per row; the name starts with the row number.
  clips/run1.mp4, run2.mp4, run3.mp4, inspector.mp4, space.mp4: silent screen recordings, used as recorded.
Cards are shown still, from 1920x1080 copies of results/video/clean/ (made in results/video/clean_1080/). Clips are
only sped up, trimmed and scaled into the top 82% of the frame, never drawn on except for the labels. Labels and subtitles are text from the script: the labels must appear in it word for word, and
the subtitles are the voiceover sentences (up to 2 lines of 42 characters each, split at phrase breaks), timed by
word count and moved to the nearest pause in the voice.

--dry-run uses silent 3 s voice files and coloured, labelled frames for whatever is missing, to test the build before
anything is recorded. ffmpeg must be on PATH (or set the FFMPEG environment variable to its full path).

Run:  python -X utf8 -m demo.make_video [--dry-run]
"""

import json
import os
import re
import shutil
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from demo.practice_script import script_rows
from demo.storyboard import MUTED, ROOT, SCRIPT, TEXT, font

INPUT = ROOT / "video_input"
VOICE, CLIPS, BUILD = INPUT / "voice", INPUT / "clips", INPUT / "_build"
CLEAN, CLEAN_1080 = ROOT / "results" / "video" / "clean", ROOT / "results" / "video" / "clean_1080"
OUT = ROOT / "results" / "video" / "mixshield_demo.mp4"
SHEET = ROOT / "results" / "video" / "preview_sheet.png"
FFMPEG = os.environ.get("FFMPEG", "ffmpeg")

W, H, FPS = 1920, 1080, 30
BAND = round(0.82 * H)  # first pixel row of the subtitle band
TAIL, FADE = 0.4, 0.2  # silence after each voice file; crossfade between slides
INSET, INSET_TOP = 0.9, 96  # chart slides: scale, and top edge (below the labels, which end at y 88)
SUB_CHARS, SUB_MIN = 42, 1.5  # characters per subtitle line (2 lines at most); shortest time on screen
RATE = 48000
AUDIO_EXT = (".m4a", ".mp3", ".wav")
MAX_LENGTH = 180


def img(name, labels=(), secs=None, frac=None, inset=False):
    """inset: the image at 90%, moved down below the label (for the charts, whose axis text reaches the top left)."""
    return {"kind": "image", "src": name, "labels": list(labels), "secs": secs, "frac": frac, "inset": inset}


def clip(name, speed, anchor, labels=(), secs=None, cut_label=None):
    """anchor "end": if the clip is longer than its slot, keep its end (the result card); "start": keep its start."""
    return {"kind": "clip", "src": name, "speed": speed, "anchor": anchor, "labels": list(labels), "secs": secs,
            "frac": None, "cut_label": cut_label}


SIM, FAST2 = "SIMULATION", "2x, sped up"

# One entry per row of the script. A slide with several parts lists them in order; the last one fills the rest.
PLAN = [
    [img("hook_email")],
    [clip("run1", 2, "end", [SIM, FAST2])],
    [clip("run2_replay", 2, "end", [SIM, "Recorded run (31 Oct), replayed", FAST2])],
    [img("hook_numbers", ["Test split"])],
    [clip("run1", 1, "start", [SIM, "Run 1: no MixShield"])],
    [clip("run2", 2, "end", ["SIMULATION + real MixShield screen and gate", FAST2, "live run"])],
    [clip("run3", 2, "end", ["Real model: Muse Spark Open", FAST2])],
    [img("config_compare", ["One config change"], secs=4.0),
     clip("inspector", 2, "end", ["MCP Inspector 2.12.0", FAST2], cut_label="Start-up cut")],
    [img("how_it_works", frac=2 / 3), img("meta_models", ["Muse Spark Open (open weights)"])],
    [img("meta_models", ["Muse Spark (Meta Model API)"])],
    [img("meta_models", ["Built with Llama"])],
    [img("e2_language_gap_169", ["Test split"], inset=True)],
    [img("e3_security_vs_utility_169", ["Attack success: SIMULATION"], inset=True)],
    [img("e4_ablation_169", ["Ablation, simulation, test split"], inset=True)],
    [img("limitations")],
    [img("use_it")],
    [clip("space", 1, "start", ["huggingface.co/spaces/HP0077/mixshield"])],  # the recording has no address bar
    [img("end_card")],
]
NAME_TAG, NAME_TAG_SECS = "MixShield · Huzaifa Pathan", 4.0
CARD_RIGHT = 1760  # right edge of the cards' content at 1080p


def ff(*args, quiet=True):
    cmd = [FFMPEG, "-hide_banner", "-y", *map(str, args)]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        sys.exit(f"ffmpeg failed:\n{' '.join(cmd)}\n{r.stderr[-3000:]}")
    return r.stderr if quiet else print(r.stderr)


def duration(path):
    """Length of a media file in seconds, read from ffmpeg's own report (no ffprobe needed)."""
    r = subprocess.run([FFMPEG, "-hide_banner", "-i", str(path)], capture_output=True, text=True, errors="replace")
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", r.stderr)
    if not m:
        sys.exit(f"Could not read the length of {path}")
    return int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3])


def check_labels():
    """Every label must be copied from the script, word for word (bold and code marks removed)."""
    plain = SCRIPT.read_text(encoding="utf-8").replace("**", "").replace("`", "")
    labels = {lab for slide in PLAN for seg in slide for lab in seg["labels"] + [seg.get("cut_label") or ""] if lab}
    missing = [lab for lab in sorted(labels) if lab not in plain]
    if missing:
        sys.exit(f"These labels are not in docs/video_script.md: {missing}")


# ---------- inputs ----------

def make_1080_copies():
    CLEAN_1080.mkdir(parents=True, exist_ok=True)
    for src in sorted(CLEAN.glob("*.png")):
        dst = CLEAN_1080 / src.name
        if not dst.exists():
            Image.open(src).convert("RGB").resize((W, H), Image.LANCZOS).save(dst)


def find_voice(n):
    files = [p for p in VOICE.glob(f"{n:02d}*") if p.suffix.lower() in AUDIO_EXT] if VOICE.exists() else []
    return sorted(files)[0] if files else None


def placeholder(text, color, path):
    im = Image.new("RGB", (W, H), color)
    d = ImageDraw.Draw(im)
    f = font(64, bold=True)
    d.text((W / 2, BAND / 2), text, font=f, fill="white", anchor="mm")
    d.text((W / 2, BAND / 2 + 80), "dry run: placeholder, not a recording", font=font(36), fill="white", anchor="mm")
    im.save(path)
    return path


def silent_wav(path, secs):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2), w.setsampwidth(2), w.setframerate(RATE)
        w.writeframes(bytes(4 * round(secs * RATE)))
    return path


def normalised_voice(src, dst):
    """Two-pass loudness normalisation (EBU R128, -16 LUFS) to 48 kHz stereo WAV, so every row sounds equally loud."""
    target = "I=-16:TP=-1.5:LRA=11"
    report = ff("-i", src, "-af", f"loudnorm={target}:print_format=json", "-f", "null", "-")
    m = json.loads(report[report.rindex("{"):report.rindex("}") + 1])
    measured = (f"measured_I={m['input_i']}:measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}:"
                f"measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true")
    ff("-i", src, "-af", f"loudnorm={target}:{measured},aresample={RATE}", "-ac", 2, "-c:a", "pcm_s16le", dst)
    return dst


def read_wav(path):
    with wave.open(str(path), "rb") as w:
        return w.readframes(w.getnframes()), w.getnframes() / w.getframerate()


# ---------- subtitles ----------

# Names and phrases that a subtitle never splits (longest first). Numbers are single words, so never split.
KEEP = ["Llama Prompt Guard 2", "Muse Spark Open", "Prompt Guard 2", "Llama Guard 3", "Muse Spark", "Hugging Face",
        "MCP Inspector", "MCP server", "mixshield proxy", "AI agent", "explains why"]
STARTS_PHRASE = {"and", "but", "so", "while", "versus", "or"}
WEAK_START = {"in", "to", "of", "for", "at", "on", "from", "with", "that"}


def sentences(voice_lines):
    return [s for s in re.split(r"(?<=[.!?])\s+", " ".join(voice_lines)) if s]


def tokens(sentence):
    words, out, i = sentence.split(), [], 0
    while i < len(words):
        for name in KEEP:
            n = len(name.split())
            if " ".join(words[i:i + n]).rstrip(".,:;?!") == name:
                out.append(" ".join(words[i:i + n]))
                i += n
                break
        else:
            out.append(words[i])
            i += 1
    return out


def break_cost(before, after):
    """How bad a line or subtitle break between two words is: after a comma is best, before "and/but/so" next."""
    if before[-1] in ",:;.?!":
        cost = 0
    elif after.lower() in STARTS_PHRASE:
        cost = 1
    elif after.lower() in WEAK_START:
        cost = 2
    else:
        cost = 4
    if before.lower() in ("a", "an", "the", "of", "to") or after == "percent":
        cost += 6
    if after[-1] in ",:;" and before[-1] not in ",:;.?!":
        cost += 4  # one word left alone before a comma ("the agent / reads,")
    return cost


def two_lines(toks, chars=SUB_CHARS):
    """(cost, lines) for one subtitle of at most 2 lines of `chars` characters, or None if it does not fit."""
    one = " ".join(toks)
    if len(one) <= chars:
        return 0, [one]
    best = None
    for k in range(1, len(toks)):
        a, b = " ".join(toks[:k]), " ".join(toks[k:])
        if len(a) <= chars and len(b) <= chars:
            cost = break_cost(toks[k - 1], toks[k]) + abs(len(a) - len(b)) / 15
            if best is None or cost < best[0]:
                best = (cost, [a, b])
    return best


def subtitle_chunks(sentence, chars=SUB_CHARS):
    """A sentence as the fewest subtitles of at most 2 lines, split at natural phrase breaks: [(lines, words)]."""
    toks = tokens(sentence)
    n = len(toks)
    best = [(0, [])] + [None] * n
    for j in range(1, n + 1):
        for i in range(j):
            fit = two_lines(toks[i:j], chars)
            if best[i] is None or fit is None:
                continue
            # a break between two subtitles counts triple: the viewer loses the first half when it changes
            cost = best[i][0] + 10 + fit[0] + (3 * break_cost(toks[j - 1], toks[j]) if j < n else 0)
            if best[j] is None or cost < best[j][0]:
                best[j] = (cost, best[i][1] + [(fit[1], len(" ".join(toks[i:j]).split()))])
    if best[n] is None:
        sys.exit(f"Cannot fit this sentence into subtitles: {sentence}")
    return best[n][1]


def speech_and_pauses(pcm):
    """(speech start, speech end, middles of pauses of 0.16 s or more), from 20 ms loudness windows."""
    x = np.frombuffer(pcm, dtype=np.int16).reshape(-1, 2).mean(axis=1)
    win = RATE // 50
    k = len(x) // win
    if k == 0:
        return 0.0, 0.0, []
    rms = np.sqrt(np.mean(x[:k * win].reshape(k, win) ** 2, axis=1))
    loud = 20 * np.log10(rms / 32768 + 1e-9) > -42
    if not loud.any():
        return 0.0, k * 0.02, []
    idx = np.flatnonzero(loud)
    pauses, run = [], 0
    for i in range(idx[0], idx[-1] + 1):
        if loud[i]:
            if run >= 8:
                pauses.append((i - run / 2) * 0.02)
            run = 0
        else:
            run += 1
    return idx[0] * 0.02, (idx[-1] + 1) * 0.02, pauses


def subtitle_edges(words, start, end, pauses, limit):
    """Start and end times of consecutive subtitles: the speech time is split by word count, each change moves to
    the nearest pause (< 1 s), the last one stays 0.5 s after the speech, and each one shows for SUB_MIN s or more
    (later subtitles move right, up to the end of the slide, then earlier ones move left)."""
    total, acc, edges = sum(words), 0, [start]
    for w in words[:-1]:
        acc += w
        t = start + (end - start) * acc / total
        near = [p for p in pauses if abs(p - t) < 1.0 and p > edges[-1]]
        edges.append(min(near, key=lambda p: abs(p - t)) if near else t)
    edges.append(min(end + 0.5, limit))
    for i in range(len(edges) - 1):
        edges[i + 1] = max(edges[i + 1], edges[i] + SUB_MIN)
    if edges[-1] > limit:
        edges[-1] = limit
        for i in range(len(edges) - 2, -1, -1):
            edges[i] = min(edges[i], edges[i + 1] - SUB_MIN)
        edges[0] = max(edges[0], 0.0)
    return edges


# ---------- overlays (small RGBA images placed on the video) ----------

def label_png(text, path):
    """Bold 30 px white text on a dark rounded box, 12 px padding: readable on a phone."""
    f, pad = font(30, bold=True), 12
    tw = ImageDraw.Draw(Image.new("RGBA", (1, 1))).textlength(text, font=f)
    im = Image.new("RGBA", (int(tw) + 2 * (pad + 4), 36 + 2 * pad), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((0, 0, im.width - 1, im.height - 1), radius=12, fill=(20, 23, 31, 215))
    d.text((pad + 4, im.height / 2), text, font=f, fill="white", anchor="lm")
    im.save(path)
    return path, 32, 28


def name_tag_png(path):
    f = font(28, bold=True)
    tw = ImageDraw.Draw(Image.new("RGBA", (1, 1))).textlength(NAME_TAG, font=f)
    im = Image.new("RGBA", (int(tw) + 4, 44), (0, 0, 0, 0))
    ImageDraw.Draw(im).text((0, 22), NAME_TAG, font=f, fill=MUTED, anchor="lm")
    im.save(path)
    return path, CARD_RIGHT - im.width, 54 - im.height // 2  # top right, level with the labels


def subtitle_png(lines, path):
    """White bold text on a rounded black box at 75% opacity, centred in the empty bottom band."""
    f, line_h, pad = font(52, bold=True), 64, 16
    d0 = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    width = max(d0.textlength(line, font=f) for line in lines)
    im = Image.new("RGBA", (int(width) + 2 * 22, line_h * len(lines) + 2 * pad), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((0, 0, im.width - 1, im.height - 1), radius=14, fill=(0, 0, 0, 191))
    for i, line in enumerate(lines):
        d.text((im.width / 2, pad + line_h * i + line_h / 2), line, font=f, fill="white", anchor="mm")
    im.save(path)
    return path, (W - im.width) // 2, BAND + (H - BAND - im.height) // 2


# ---------- slides ----------

def segment_slots(slide, length):
    """(start, length) of each part of a slide."""
    slots, t = [], 0.0
    for i, seg in enumerate(slide):
        if i == len(slide) - 1:
            n = length - t
        else:
            n = min(seg["secs"], length / 2) if seg["secs"] else seg["frac"] * length
        slots.append((t, min(n, length - t)))
        t += n
    return slots


def base_chain(seg, start, n, k, inputs, notes, dry):
    """Input arguments and the filter for one part of a slide; output label [b{k}]."""
    if seg["kind"] == "image":
        inputs += ["-loop", 1, "-framerate", FPS, "-t", f"{n:.3f}", "-i", CLEAN_1080 / f"{seg['src']}.png"]
        i = inputs.count("-i") - 1
        inset = (f"scale={round(W * INSET) // 2 * 2}:-2:flags=lanczos,pad={W}:{H}:(ow-iw)/2:{INSET_TOP}:color=white,"
                 if seg.get("inset") else "")
        return f"[{i}:v]{inset}format=yuv420p,setsar=1[b{k}]"
    path = CLIPS / f"{seg['src']}.mp4"
    if not path.exists():
        if not dry:
            sys.exit(f"Missing clip: {path}")
        ph = placeholder(f"MISSING CLIP: {seg['src']}.mp4 ({seg['speed']}x, keep {seg['anchor']})",
                         "#7a1f3d" if seg["speed"] == 2 else "#1f4f7a", BUILD / f"ph_{seg['src']}_{k}.png")
        inputs += ["-loop", 1, "-framerate", FPS, "-t", f"{n:.3f}", "-i", ph]
        i = inputs.count("-i") - 1
        notes.append(f"{seg['src']}.mp4 missing: placeholder")
        return f"[{i}:v]format=yuv420p,setsar=1[b{k}]"
    info = json.loads(path.with_suffix(".json").read_text(encoding="utf-8")) if path.with_suffix(".json").exists() else {}
    src_len, speed = duration(path), seg["speed"]
    need = n * speed  # seconds of recording the slot needs
    if src_len <= need:  # too short: all of it, then the last frame with a slow push-in
        skip, play = 0.0, src_len / speed
    elif seg["anchor"] == "start":  # from just before the click
        skip, play = min(max(info.get("click_at", 1.0) - 1.0, 0.0), src_len - need), n
    else:  # end 3 s after the result appears (or later, if the slot needs more), else at the very end
        end = min(src_len, max(info["result_at"] + 3 * speed, need)) if "result_at" in info else src_len
        skip, play = end - need, n
    if skip > 0.05 and seg.get("cut_label"):
        seg = {**seg, "labels": seg["labels"] + [seg["cut_label"]]}
    notes.append(f"{seg['src']}.mp4 at {speed}x: {src_len / speed:.1f} s of clip for a {n:.1f} s slot"
                 + (f" (recording {skip:.1f}-{skip + play * speed:.1f} s)" if play >= n else
                    f"  WARNING: clip is shorter, last frame frozen for {n - play:.1f} s"))
    inputs += ["-ss", f"{skip:.3f}", "-i", path]
    i = inputs.count("-i") - 1
    h = BAND - BAND % 2
    fit = (f"scale={W}:{h}:force_original_aspect_ratio=decrease:flags=lanczos,"
           f"pad={W}:{H}:(ow-iw)/2:({h}-ih)/2:color=white,format=yuv420p,setsar=1")
    played = (f"[{i}:v]setpts=(PTS-STARTPTS)/{speed},fps={FPS},{fit},"
              f"trim=duration={play:.3f},setpts=PTS-STARTPTS")
    frozen = n - play
    if frozen < 0.05:
        return played + f"[b{k}]", seg
    last = BUILD / f"last_{seg['src']}_{k}.png"
    ff("-sseof", "-0.5", "-i", path, "-update", 1, "-q:v", 1, last)
    inputs += ["-loop", 1, "-framerate", FPS, "-t", f"{frozen:.3f}", "-i", last]
    j = inputs.count("-i") - 1
    frames = max(round(frozen * FPS) - 1, 1)
    # The push-in (100% to 102%) is computed on a 2x copy, so it moves smoothly instead of in whole pixels.
    push = (f"[{j}:v]scale={2 * W}:{2 * H}:flags=lanczos,zoompan=z='1+0.02*on/{frames}':x='iw/2-iw/zoom/2':"
            f"y='ih/2-ih/zoom/2':d=1:s={W}x{H}:fps={FPS},{fit}")
    return f"{played}[p{k}];{push}[f{k}];[p{k}][f{k}]concat=n=2:v=1:a=0[b{k}]", seg


def render_slide(n_slide, slide, length, extra, subs, dry):
    """Write slide n as a silent video of `length` + `extra` seconds (the extra is eaten by the crossfade)."""
    total = length + extra
    slots = segment_slots(slide, length)
    slots[-1] = (slots[-1][0], slots[-1][1] + extra)
    inputs, chains, notes, overlays = [], [], [], []
    for k, (seg, (t0, n)) in enumerate(zip(slide, slots)):
        chain = base_chain(seg, t0, n, k, inputs, notes, dry)
        if isinstance(chain, tuple):
            chain, seg = chain
        chains.append(chain)
        if seg["labels"]:
            overlays.append((*label_png(" · ".join(seg["labels"]), BUILD / f"lab_{n_slide:02d}_{k}.png"), t0, t0 + n))
    if n_slide == 1:
        overlays.append((*name_tag_png(BUILD / "name_tag.png"), 0, NAME_TAG_SECS))
    for j, (lines, a, b) in enumerate(subs):
        overlays.append((*subtitle_png(lines, BUILD / f"sub_{n_slide:02d}_{j}.png"), a, b))

    if len(chains) > 1:
        chains.append("".join(f"[b{k}]" for k in range(len(chains))) + f"concat=n={len(chains)}:v=1:a=0[v0]")
        last = "v0"
    else:
        chains[0] = chains[0].replace("[b0]", "[v0]")
        last = "v0"
    for j, (path, x, y, a, b) in enumerate(overlays):
        inputs += ["-i", path]
        i = inputs.count("-i") - 1
        chains.append(f"[{last}][{i}:v]overlay=x={x}:y={y}:enable='between(t,{a:.3f},{b:.3f})'[v{j + 1}]")
        last = f"v{j + 1}"
    out = BUILD / f"slide_{n_slide:02d}.mp4"
    ff(*inputs, "-filter_complex", ";".join(chains), "-map", f"[{last}]", "-t", f"{total:.3f}", "-r", FPS,
       "-c:v", "libx264", "-preset", "veryfast", "-crf", 12, "-pix_fmt", "yuv420p", "-an", out)
    return out, notes


# ---------- whole video ----------

def contact_sheet(starts, lengths):
    thumbs = []
    for n, (s, d) in enumerate(zip(starts, lengths), 1):
        p = BUILD / f"thumb_{n:02d}.png"
        ff("-ss", f"{s + d * 0.6:.3f}", "-i", OUT, "-frames:v", 1, "-vf", "scale=640:360", p)
        thumbs.append(p)
    cols, tw, th, cap = 3, 640, 360, 44
    rows = -(-len(thumbs) // cols)
    sheet = Image.new("RGB", (cols * tw + (cols + 1) * 16, rows * (th + cap) + (rows + 1) * 16), "#e1e4ea")
    d = ImageDraw.Draw(sheet)
    for n, (p, s) in enumerate(zip(thumbs, starts)):
        x, y = 16 + (n % cols) * (tw + 16), 16 + (n // cols) * (th + cap + 16)
        sheet.paste(Image.open(p), (x, y + cap))
        d.text((x, y + cap / 2), f"{n + 1:02d}   {clock(s)}", font=font(26, bold=True), fill=TEXT, anchor="lm")
    sheet.save(SHEET)


def clock(t):
    return f"{int(t // 60)}:{t % 60:04.1f}"


def main():
    dry = "--dry-run" in sys.argv[1:]
    if not shutil.which(FFMPEG) and not Path(FFMPEG).exists():
        sys.exit("ffmpeg not found on PATH (or set FFMPEG to its full path).")
    rows = script_rows()
    if len(rows) != len(PLAN):
        sys.exit(f"The script has {len(rows)} rows but the slide plan has {len(PLAN)}.")
    check_labels()
    make_1080_copies()
    if BUILD.exists():
        shutil.rmtree(BUILD)
    BUILD.mkdir(parents=True)

    voices, missing = [], []
    for n in range(1, len(PLAN) + 1):
        src = find_voice(n)
        if src is None:
            missing.append(f"{n:02d}")
            voices.append(silent_wav(BUILD / f"voice_{n:02d}.wav", 3.0))
        else:
            voices.append(normalised_voice(src, BUILD / f"voice_{n:02d}.wav"))
    if missing and not dry:
        sys.exit(f"Missing voice files in {VOICE}: {', '.join(missing)} (or use --dry-run)")

    audio, starts, lengths, slides, all_notes = bytearray(), [], [], [], []
    t = 0.0
    for n, (slide, row, wav) in enumerate(zip(PLAN, rows, voices), 1):
        pcm, secs = read_wav(wav)
        length = round((secs + TAIL) * FPS) / FPS
        pcm += bytes(4 * (round(length * RATE) - len(pcm) // 4))
        audio += pcm[:4 * round(length * RATE)]
        start, end, pauses = speech_and_pauses(pcm)
        chunks = [c for s in sentences(row["voice"]) for c in subtitle_chunks(s)]
        edges = subtitle_edges([w for _, w in chunks], start, min(end, secs), pauses, length)
        subs = [(lines, a, b) for (lines, _), a, b in zip(chunks, edges, edges[1:])]
        extra = FADE if n < len(PLAN) else 0.0
        path, notes = render_slide(n, slide, length, extra, subs, dry)
        if any(b - a < SUB_MIN - 0.01 for _, a, b in subs):
            notes.append(f"slide too short to show each of its {len(subs)} subtitles for {SUB_MIN} s")
        slides.append(path)
        starts.append(t)
        lengths.append(length)
        all_notes += [f"slide {n:02d}: {x}" for x in notes]
        print(f"  slide {n:02d}  start {clock(t)}  length {length:5.2f} s  {row['time']}", flush=True)
        t += length

    full_wav = BUILD / "voice_full.wav"
    with wave.open(str(full_wav), "wb") as w:
        w.setnchannels(2), w.setsampwidth(2), w.setframerate(RATE)
        w.writeframes(bytes(audio))

    inputs, chains, last = [], [], "0:v"
    for p in slides:
        inputs += ["-i", p]
    for k in range(1, len(slides)):
        out = f"x{k}"
        chains.append(f"[{last}][{k}:v]xfade=transition=fade:duration={FADE}:offset={starts[k]:.3f}[{out}]")
        last = out
    inputs += ["-i", full_wav]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    ff(*inputs, "-filter_complex", ";".join(chains), "-map", f"[{last}]", "-map", f"{len(slides)}:a",
       "-r", FPS, "-c:v", "libx264", "-preset", "veryfast", "-crf", 20, "-pix_fmt", "yuv420p",
       "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-t", f"{t:.3f}", OUT)
    contact_sheet(starts, lengths)

    for x in all_notes:
        print("  note:", x)
    print(f"\nTotal length: {clock(t)} ({t:.1f} s){'  DRY RUN' if dry else ''}")
    if t >= MAX_LENGTH:
        print(f"  TOO LONG: must be under 3:00. Cut words in the longest rows.")
    print(f"Video: {OUT}\nContact sheet: {SHEET}")


if __name__ == "__main__":
    main()
