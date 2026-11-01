"""Burns subtitles into the hand-edited demo video: results/video/mixshield_final.mp4, plus an .srt next to it.

The words come from the "Final version" voiceover in docs/video_script.md, never from speech recognition.
faster-whisper (model "small", CPU, English) is used only to find when each word is spoken: the script words are lined
up with the recognised words (fuzzy match, so an accent or a misheard word does not matter), and a script word it did
not hear gets a time between its matched neighbours. In the subtitles only, spoken numbers are written as digits
(84%, under 70, 99.5%, 0 false alarms, 2 of 27); the script keeps the spoken words.
The look is the one in demo/make_video.py: bold white text on a dark rounded box in the bottom band, at most 2 lines of
38 characters, split at phrase breaks (never inside a number or a name), each subtitle shown for 1.5 s or more.

The .srt holds the subtitle times and lines. Fix the times in it by hand if needed, then burn it again with
--from-srt (no speech recognition then).

Run:  python -X utf8 -m demo.add_subtitles video_input/final_edit.mp4 [--rows 1-10] [--out results/video/mixshield_final.mp4]
      python -X utf8 -m demo.add_subtitles video_input/final_edit.mp4 --from-srt results/video/mixshield_final.srt
Needs ffmpeg (or FFMPEG) and faster-whisper (pip install -e ".[video]"; the model downloads once into HF_HOME).
"""

import argparse
import re
import shutil
import sys
from difflib import SequenceMatcher
from pathlib import Path

from PIL import Image

from demo.make_video import FFMPEG, H, SUB_MIN, W, duration, ff, subtitle_chunks, subtitle_png
from demo.practice_script import final_rows
from demo.storyboard import ROOT

OUT = ROOT / "results" / "video" / "mixshield_final.mp4"
WORK = ROOT / "video_input" / "_subs"
CHARS = 38  # characters per subtitle line
HOLD = 0.5  # a subtitle stays this long after its last word, unless the next one starts first
JOIN = "\x00"  # joins the words of a digit phrase, so a subtitle never splits it
# Spoken words -> subtitle text. Only in subtitles; the voiceover keeps the words.
DIGITS = [("eighty-four percent", "84%"), ("under seventy", "under 70"), ("ninety-nine point five", "99.5%"),
          ("zero false alarms", "0 false alarms"), ("two out of twenty-seven", "2 of 27")]
# Names in the voiceover, given to the recogniser as a hint.
HINT = "MixShield, Hinglish, Huzaifa, AgentDojo, MCP, Meta, Muse Spark Open, Llama Prompt Guard 2, Llama Guard, Hugging Face."


def norm(word):
    return re.sub(r"[^a-z0-9]", "", word.lower())


# ---------- script words and subtitle chunks ----------

def units(sentence):
    """The sentence as subtitle words: (text, number of spoken words). A digit phrase is one unit."""
    words, out, i = sentence.split(), [], 0
    while i < len(words):
        for spoken, shown in DIGITS:
            n = len(spoken.split())
            said = words[i:i + n]
            if [norm(w) for w in said] == [norm(w) for w in spoken.split()]:
                tail = re.search(r"[^\w%]*$", said[-1]).group(0)  # keep the punctuation after the phrase
                out.append((shown.replace(" ", JOIN) + tail, n))
                i += n
                break
        else:
            out.append((words[i], 1))
            i += 1
    return out


def script_cues(rows):
    """(spoken words, cues): every spoken word of the chosen rows in order, and for each subtitle its lines and the
    range of spoken words it covers."""
    spoken, cues = [], []
    for row in rows:
        for sentence in row["voice"]:
            parts = units(sentence)
            first = len(spoken)
            spoken += sentence.split()
            k = 0  # next unit
            for lines, _ in subtitle_chunks(" ".join(text for text, _ in parts), CHARS):
                n_units = len(" ".join(lines).split())
                count = sum(n for _, n in parts[k:k + n_units])
                cues.append({"lines": [line.replace(JOIN, " ") for line in lines], "from": first,
                             "to": first + count})
                first += count
                k += n_units
    return spoken, cues


# ---------- timing ----------

def recognise(video):
    """[(word, start, end)] from faster-whisper, model "small" on CPU, English, word timestamps."""
    import subprocess

    import numpy as np
    from faster_whisper import WhisperModel
    # ffmpeg reads the audio (16 kHz mono), so faster-whisper's own decoder is not needed.
    pcm = subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-i", str(video), "-vn", "-ac", "1",
                          "-ar", "16000", "-f", "s16le", "-"], capture_output=True, check=True).stdout
    audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768
    model = WhisperModel("small", device="cpu", compute_type="int8")
    segments, _ = model.transcribe(audio, language="en", word_timestamps=True, initial_prompt=HINT)
    return [(w.word.strip(), w.start, w.end) for seg in segments for w in (seg.words or [])]


def align(script, heard):
    """For each script word, the index of the heard word it matches, or None. A weighted longest common subsequence:
    two words match when they are at least 70% alike."""
    a, b = [norm(w) for w in script], [norm(w) for w, _, _ in heard]
    sim = {}

    def like(x, y):
        if (x, y) not in sim:
            sim[(x, y)] = SequenceMatcher(None, x, y).ratio() if x and y else 0.0
        return sim[(x, y)]

    n, m = len(a), len(b)
    score = [[0.0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            best = max(score[i - 1][j], score[i][j - 1])
            s = like(a[i - 1], b[j - 1])
            if s >= 0.7:
                best = max(best, score[i - 1][j - 1] + s)
            score[i][j] = best
    match, i, j = [None] * n, n, m
    while i and j:
        s = like(a[i - 1], b[j - 1])
        if s >= 0.7 and abs(score[i][j] - (score[i - 1][j - 1] + s)) < 1e-9:
            match[i - 1] = j - 1
            i, j = i - 1, j - 1
        elif score[i - 1][j] >= score[i][j - 1]:
            i -= 1
        else:
            j -= 1
    return match


def word_times(script, heard, match):
    """(start, end) for every script word. Unheard words between two matched ones share the time between them;
    words before the first or after the last match get None."""
    times = [(heard[k][1], heard[k][2]) if k is not None else None for k in match]
    known = [i for i, t in enumerate(times) if t]
    for left, right in zip(known, known[1:]):
        gap = right - left
        if gap > 1:
            t0, t1 = times[left][1], times[right][0]
            step = (t1 - t0) / gap
            for k in range(1, gap):
                times[left + k] = (t0 + step * (k - 1), t0 + step * k)
    return times


def timed_cues(cues, times, end_of_video):
    out = []
    for cue in cues:
        span = [t for t in times[cue["from"]:cue["to"]] if t]
        if not span:
            print(f"  not heard, no subtitle: {' / '.join(cue['lines'])}")
            continue
        out.append({**cue, "start": span[0][0], "end": span[-1][1] + HOLD})
    for k, cue in enumerate(out):  # at least SUB_MIN s each, no overlap
        if k:
            cue["start"] = max(cue["start"], out[k - 1]["end"])
        cue["end"] = min(max(cue["end"], cue["start"] + SUB_MIN), end_of_video)
        if k + 1 < len(out):
            cue["end"] = min(cue["end"], max(out[k + 1]["start"], cue["start"] + SUB_MIN))
    return out


# ---------- .srt ----------

def stamp(t):
    ms = round(t * 1000)
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def unstamp(s):
    h, m, rest = s.strip().split(":")
    sec, ms = rest.split(",")
    return int(h) * 3600 + int(m) * 60 + int(sec) + int(ms) / 1000


def write_srt(cues, path):
    blocks = [f"{k}\n{stamp(c['start'])} --> {stamp(c['end'])}\n" + "\n".join(c["lines"])
              for k, c in enumerate(cues, 1)]
    path.write_text("\n\n".join(blocks) + "\n", encoding="utf-8")


def read_srt(path):
    cues = []
    for block in re.split(r"\n\s*\n", path.read_text(encoding="utf-8").strip()):
        lines = block.strip().splitlines()
        start, end = lines[1].split("-->")
        cues.append({"start": unstamp(start), "end": unstamp(end), "lines": lines[2:]})
    return cues


# ---------- burn ----------

def burn(video, cues, out):
    """Draw every subtitle as a full-frame transparent image and lay them over the video in one pass."""
    if WORK.exists():
        shutil.rmtree(WORK)
    WORK.mkdir(parents=True)
    blank = WORK / "blank.png"
    Image.new("RGBA", (W, H), (0, 0, 0, 0)).save(blank)
    listing, t = [], 0.0
    for k, cue in enumerate(cues):
        box, x, y = subtitle_png(cue["lines"], WORK / f"box_{k:03d}.png")
        frame = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        frame.paste(Image.open(box), (x, y))
        path = WORK / f"sub_{k:03d}.png"
        frame.save(path)
        if cue["start"] > t:
            listing += [f"file '{blank.as_posix()}'", f"duration {cue['start'] - t:.3f}"]
        listing += [f"file '{path.as_posix()}'", f"duration {cue['end'] - cue['start']:.3f}"]
        t = cue["end"]
    listing += [f"file '{blank.as_posix()}'", "duration 1.000", f"file '{blank.as_posix()}'"]
    (WORK / "subs.txt").write_text("\n".join(listing) + "\n", encoding="utf-8")
    out.parent.mkdir(parents=True, exist_ok=True)
    ff("-i", video, "-f", "concat", "-safe", 0, "-i", WORK / "subs.txt", "-filter_complex",
       f"[0:v]scale={W}:{H}:force_original_aspect_ratio=decrease:flags=lanczos,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,"
       f"fps=30,format=yuv420p[v];[1:v]format=rgba[s];[v][s]overlay=0:0:eof_action=pass,format=yuv420p[o]",
       "-map", "[o]", "-map", "0:a?", "-c:v", "libx264", "-preset", "veryfast", "-crf", 20, "-c:a", "copy",
       "-movflags", "+faststart", out)


def pick_rows(spec):
    rows = final_rows()
    if not spec:
        return rows
    wanted = set()
    for part in spec.split(","):
        a, _, b = part.partition("-")
        wanted.update(range(int(a), int(b or a) + 1))
    return [r for r in rows if r["n"] in wanted]


def main():
    ap = argparse.ArgumentParser(description="Burn the Final version subtitles into an edited video.")
    ap.add_argument("video", type=Path)
    ap.add_argument("--rows", help="rows of the Final version that are in this video, e.g. 1-10 or 8,10 (default: all)")
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--from-srt", type=Path, help="burn this .srt as it is (no speech recognition)")
    args = ap.parse_args()
    if not shutil.which(FFMPEG) and not Path(FFMPEG).exists():
        sys.exit("ffmpeg not found on PATH (or set FFMPEG to its full path).")
    if not args.video.exists():
        sys.exit(f"Video not found: {args.video}")
    srt = args.out.with_suffix(".srt")
    if args.from_srt:
        cues = read_srt(args.from_srt)
    else:
        spoken, cues = script_cues(pick_rows(args.rows))
        print(f"Script: {len(spoken)} words in {len(cues)} subtitles. Finding the spoken times (faster-whisper small)...")
        heard = recognise(args.video)
        match = align(spoken, heard)
        print(f"Heard {len(heard)} words; matched {sum(m is not None for m in match)} of {len(spoken)} script words.")
        cues = timed_cues(cues, word_times(spoken, heard, match), duration(args.video))
        write_srt(cues, srt)
        print(f"Subtitles: {srt}")
    burn(args.video, cues, args.out)
    print(f"Video: {args.out}")


if __name__ == "__main__":
    main()
