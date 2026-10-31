"""Practice script for the voiceover: docs/practice_script.pdf, one landscape page per row of docs/video_script.md.

Top: the time range and a thumbnail of the shot (the storyboard frame). Middle: the exact voiceover, one sentence per
line. Bottom: what to do, the on-screen label, word count and target seconds. Last page: the totals.
The voiceover, label and timing are read from docs/video_script.md; the "Do" lines are written here, in row order.
Build the storyboard first (python -X utf8 -m demo.storyboard build): the thumbnails are its frames.

Run:  python -X utf8 -m demo.practice_script
"""

import re
import sys

from PIL import Image, ImageDraw

from demo.storyboard import ACCENT, LINE, MUTED, ROOT, SCRIPT, SURFACE, TEXT, VIDEO, font, wrap

OUT = ROOT / "docs" / "practice_script.pdf"
PW, PH = 2339, 1654  # A4 landscape at 200 dpi
M = 110
THUMB = (820, 406)
FAST = 160  # words per minute above which a row is marked fast
SPEAKING_WPM = 140

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


def script_rows():
    rows = []
    for line in SCRIPT.read_text(encoding="utf-8").splitlines():
        if re.match(r"\| \d:\d\d-\d:\d\d \|", line):
            c = [x.strip() for x in line.strip().strip("|").split(" | ")]
            start, end = (seconds(t) for t in c[0].split("-"))
            voice = c[4]
            rows.append({"time": c[0], "secs": end - start, "frame": c[2], "voice": voice,
                         "label": c[5].replace("**", "").replace("`", ""), "words": len(voice.split())})
    return rows


def sentences(voice):
    parts = re.split(r"(?<=[.?!])\s+(?=[A-Z])", voice)
    assert " ".join(parts) == voice
    return parts


def pace(row):
    return row["words"] * 60 / row["secs"]


def voice_block(d, voice, top, bottom):
    """The voiceover at the largest size that fits between `top` and `bottom`: one sentence per paragraph."""
    width = PW - 2 * M
    for size in range(100, 43, -4):
        f = font(size)
        paragraphs = [wrap(d, s, f, width) for s in sentences(voice)]
        height = sum(len(p) for p in paragraphs) * size * 1.3 + (len(paragraphs) - 1) * size * 0.4
        if height <= bottom - top:
            break
    y = top
    for p in paragraphs:
        for line in p:
            d.text((M, y), line, font=f, fill=TEXT)
            y += size * 1.3
        y += size * 0.4
    return y


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
    voice_block(d, row["voice"], 560, 1190)

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
           f"{fastest['secs']} s ({pace(fastest):.0f} words per minute)", font=font(50, bold=True),
           fill=TEXT)
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
