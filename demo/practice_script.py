"""Practice script for the voiceover: docs/practice_script.pdf, one landscape page per row of docs/video_script.md.

Top: the time range and a thumbnail of the shot (the storyboard frame). Middle: the voice lines in big black text, each
with its cue (the lines that start with →) above it in smaller grey italic text, in script order. Bottom: what to do,
the on-screen label, word count and target seconds. Last page: the totals. Cues are not counted as words.
The voice lines, cues, label and timing are read from docs/video_script.md; the "Do" lines are written here, in row
order. Build the storyboard first (python -X utf8 -m demo.storyboard build): the thumbnails are its frames.

Run:  python -X utf8 -m demo.practice_script
"""

import re
import sys
from itertools import zip_longest

from PIL import Image, ImageDraw

from demo.storyboard import ACCENT, LINE, MUTED, ROOT, SCRIPT, TEXT, VIDEO, font, wrap

OUT = ROOT / "docs" / "practice_script.pdf"
PW, PH = 2339, 1654  # A4 landscape at 200 dpi
M = 110
THUMB = (820, 406)
FAST = 160  # words per minute above which a row is marked fast
SPEAKING_WPM = 140
SLANT = 0.22  # how far the cue lines lean (the Inter files here have no italic)

# What to record or show, one line per row of the script, in order.
DO = [
    "Show hook_email.png. Start the voice on the first frame.",
    "Playground: click 1 (Simulated agent, no MixShield). End on the red Money sent card. Real speed, 2x in the edit.",
    "Click 2 (Simulated agent, with MixShield). End on the red Blocked card. Keep the take, even if the screen misses.",
    "Show hook_numbers.png. Bring in the Llama Guard 3 line first, then the MixShield line, as you say them.",
    "Playground, tab Agent through the proxy. Click 1 and let it finish: Money sent.",
    "Click 2. Pause 2 s on the Screen card (Prompt Guard 2 score, classifier flag and reason), then the red Blocked "
    "card. 2x in the edit.",
    "Click 3 (Muse Spark Open, with MixShield). End on the green Paid card. 2x in the edit.",
    "Show config_compare.png for 3 s. Then MCP Inspector: Connect (cut the wait), read_email 3, then transfer_money "
    "to ZZ00DEMO0000000099: BLOCKED.",
    "Show how_it_works.png for 5 s, then meta_models.png with the Muse Spark Open row highlighted.",
    "meta_models.png: highlight the Muse Spark row.",
    "meta_models.png: highlight the Llama row, then hold on Built with Llama.",
    "e2_language_gap.png full screen. Point at the Llama Guard 3 bars, then the MixShield bars.",
    "e3_security_vs_utility.png. Highlight the MixShield (trusting) point.",
    "e4_ablation.png. Highlight Minus screen (trusting).",
    "Show limitations.png. Hold, no zoom.",
    "Show use_it.png. Hold on the two commands.",
    "Screen recording: live Space at huggingface.co/spaces/HP0077/mixshield, URL bar visible. Slow scroll.",
    "Show end_card.png. Hold to the end.",
]


def seconds(t):
    minutes, secs = t.split(":")
    return int(minutes) * 60 + int(secs)


def clock(total):
    return f"{total // 60}:{total % 60:02d}"


def cell_lines(cell):
    """The lines of a table cell (they are separated by <br>)."""
    return [x.strip() for x in cell.split("<br>") if x.strip()]


def script_rows():
    rows = []
    for line in SCRIPT.read_text(encoding="utf-8").splitlines():
        if re.match(r"\| \d:\d\d-\d:\d\d \|", line):
            c = [x.strip() for x in line.strip().strip("|").split(" | ")]
            start, end = (seconds(t) for t in c[0].split("-"))
            voice = cell_lines(c[4])
            rows.append({"time": c[0], "secs": end - start, "frame": c[2], "voice": voice, "cues": cell_lines(c[5]),
                         "label": c[6].replace("**", "").replace("`", ""),
                         "words": sum(len(v.split()) for v in voice)})
    return rows


def pace(row):
    return row["words"] * 60 / row["secs"]


def italic(img, xy, s, f, fill):
    """Draw `s` leaning to the right: the text is drawn flat on a mask, then sheared about its baseline."""
    ascent = f.getmetrics()[0]
    w, h = int(f.getlength(s)) + int(SLANT * ascent) + 6, int(f.size * 1.5)
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).text((0, 0), s, font=f, fill=255)
    mask = mask.transform((w, h), Image.AFFINE, (1, SLANT, -SLANT * ascent, 0, 1, 0), resample=Image.BICUBIC)
    img.paste(Image.new("RGB", (w, h), fill), xy, mask)


def voice_block(img, d, row, top, bottom):
    """Each cue (small, grey, leaning) above its voice line (big, black), at the largest size that fits between `top`
    and `bottom`. A cue is paired with the voice line after it."""
    width = PW - 2 * M
    pairs = list(zip_longest(row["cues"], row["voice"], fillvalue=""))
    for size in range(96, 39, -4):
        f, cue_size = font(size), max(32, round(size * 0.45))
        cf = font(cue_size)
        laid = [(wrap(d, cue, cf, width) if cue else [], wrap(d, line, f, width) if line else []) for cue, line in pairs]
        height = sum(len(c) * cue_size * 1.35 + len(v) * size * 1.3 + size * 0.4 for c, v in laid) - size * 0.4
        if height <= bottom - top:
            break
    y = top
    for cue_lines, voice_lines in laid:
        for line in cue_lines:
            italic(img, (M, round(y)), line, cf, MUTED)
            y += cue_size * 1.35
        for line in voice_lines:
            d.text((M, y), line, font=f, fill=TEXT)
            y += size * 1.3
        y += size * 0.4


def labelled(d, y, label, value, size):
    """`label` in bold, then `value` wrapped beside it. Returns the y below the last line."""
    lf, vf = font(size, bold=True), font(size)
    x = M + d.textlength(label, font=lf) + 24
    d.text((M, y), label, font=lf, fill=ACCENT)
    for line in wrap(d, value, vf, PW - M - x):
        d.text((x, y), line, font=vf, fill=TEXT)
        y += size * 1.35
    return y + size * 0.3


def page(n, total, row, do):
    img = Image.new("RGB", (PW, PH), "white")
    d = ImageDraw.Draw(img)
    d.text((M, 80), f"Shot {n} of {total}", font=font(44), fill=MUTED)
    d.text((M, 150), row["time"], font=font(150, bold=True), fill=ACCENT)
    thumb = Image.open(VIDEO / "storyboard" / row["frame"]).convert("RGB").crop((0, 0, 1920, 950)).resize(THUMB, Image.LANCZOS)
    x = PW - M - THUMB[0]
    img.paste(thumb, (x, 70))
    d.rectangle((x - 1, 69, x + THUMB[0], 70 + THUMB[1]), outline=LINE, width=2)

    d.line((M, 520, PW - M, 520), fill=LINE, width=3)
    voice_block(img, d, row, 555, 1195)

    d.line((M, 1225, PW - M, 1225), fill=LINE, width=3)
    y = labelled(d, 1255, "Do:", do, 38)
    y = labelled(d, y, "On-screen label:", row["label"], 34)
    stats = f'{row["words"]} words   ·   target {row["secs"]} s   ·   {pace(row):.0f} words per minute'
    if pace(row) > FAST:
        stats += "   ·   FAST: speak quickly or trim"
    y = labelled(d, y, "Words:", stats, 38)
    assert y < PH - 30, f"page {n}: bottom text runs off the page ({y:.0f})"
    return img


def last_page(rows):
    words = sum(r["words"] for r in rows)
    secs = sum(r["secs"] for r in rows)
    img = Image.new("RGB", (PW, PH), "white")
    d = ImageDraw.Draw(img)
    d.text((M, 80), "Totals", font=font(44), fill=MUTED)
    d.text((M, 170), f"{words} words", font=font(200, bold=True), fill=ACCENT)
    d.text((M, 470), f"{clock(secs)} target time ({secs} s, {len(rows)} shots)", font=font(80), fill=TEXT)
    d.text((M, 600), f"At {SPEAKING_WPM} words per minute the voice takes {clock(round(words * 60 / SPEAKING_WPM))}.",
           font=font(60), fill=MUTED)
    fast = [r for r in rows if pace(r) > FAST]
    fastest = max(rows, key=pace)
    d.line((M, 760, PW - M, 760), fill=LINE, width=3)
    d.text((M, 800), f"Fastest row: {fastest['time']}, {fastest['words']} words in "
           f"{fastest['secs']} s ({pace(fastest):.0f} words per minute)", font=font(50, bold=True), fill=TEXT)
    d.text((M, 880), f"Rows faster than {FAST} words per minute:", font=font(46), fill=MUTED)
    y = 950
    for r in fast:
        d.text((M, y), f'{r["time"]}   {r["words"]} words in {r["secs"]} s   ({pace(r):.0f} per minute)',
               font=font(46), fill=TEXT)
        y += 66
    if not fast:
        d.text((M, y), "None.", font=font(46), fill=TEXT)
    return img


def pages():
    rows = script_rows()
    if len(rows) != len(DO):
        sys.exit(f"The script has {len(rows)} timed rows but DO has {len(DO)} lines: update DO first.")
    return [page(i, len(rows), r, do) for i, (r, do) in enumerate(zip(rows, DO), start=1)] + [last_page(rows)]


if __name__ == "__main__":
    out = pages()
    out[0].save(OUT, save_all=True, append_images=out[1:], resolution=200)
    print(f"Wrote {OUT} ({len(out)} pages)")
