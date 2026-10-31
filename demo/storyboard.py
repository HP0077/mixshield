"""Storyboard for the demo video: one 1920x1080 frame per row of docs/video_script.md, plus one PDF to flip through.

Two steps:
  python -X utf8 -m demo.storyboard shots   screenshots from the local playground (it must be running on URL), using
                                            "Replay a recorded run" only: no model is called, nothing is saved
  python -X utf8 -m demo.storyboard build   frames in results/video/storyboard/ and results/video/storyboard.pdf
                                            (build 16 04: only those frames, then the PDF again)

Each frame's caption is the row's on-screen text from docs/video_script.md, read from the file, so the storyboard
always matches the script. Screenshots need Playwright (pip install playwright) and Microsoft Edge.
"""

import json
import re
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "docs" / "video_script.md"
VIDEO = ROOT / "results" / "video"
SHOTS = VIDEO / "storyboard" / "shots"
OUT = VIDEO / "storyboard"
URL = "http://127.0.0.1:7860"
W, H = 1920, 1080
CONTENT_H = 950  # the frame above the caption band

# Same tokens as demo/viewer.py.
TEXT, MUTED, LINE, SURFACE = "#14171f", "#586070", "#e1e4ea", "#f7f8fa"
ACCENT, ACCENT_BG = "#2b55c4", "#eef2fc"
RED_BG, GREEN_BG = "#fef3f2", "#ecfdf3"
INTER = r"C:\Windows\Fonts\Inter-Regular-slnt=0.ttf"
INTER_BOLD = r"C:\Windows\Fonts\Inter-Bold-slnt=0.ttf"
MONO = r"C:\Windows\Fonts\consola.ttf"

# The three recorded runs replayed for the stills (see docs/demo_log.md, rows 30, 33 and 34).
RUNS = {"direct": "direct_20261031_113406.json", "simulated": "simulated_20261031_113101.json",
        "agent": "agent_20261031_113405.json"}

# One entry per script row, in order: (file name, source, corner tag). Source is a card or chart path, or a shot name.
FRAMES = [
    ("01_0000_hook_email", "results/video/hook_email.png", ""),
    ("02_0007_run1_money_sent", "shot:run1_result", "Recorded run"),
    ("03_0014_run2_blocked", "shot:run2_result", "Recorded run"),
    ("04_0018_hook_numbers", "results/video/hook_numbers.png", ""),
    ("05_0030_run1_playground", "shot:run1_top", "Recorded run"),
    ("06_0037_run2_screen_card", "shot:run2_steps", "Recorded run"),
    ("07_0055_run3_paid", "shot:run3_result", "Recorded run"),
    ("08_0102_inspector_config", "shot:inspector_diff", "Config files, side by side"),
    ("09_0115_how_it_works", "results/video/how_it_works.png", ""),
    ("10_0128_meta_models", "results/video/meta_models.png", ""),
    ("11_0137_meta_models_llama", "results/video/meta_models.png", ""),
    ("12_0145_e2_language_gap", "results/charts/e2_language_gap.png", ""),
    ("13_0205_e3_security_vs_utility", "results/charts/e3_security_vs_utility.png", ""),
    ("14_0222_e4_ablation", "results/charts/e4_ablation.png", ""),
    ("15_0230_limitations", "shot:limitations", "README text"),
    ("16_0235_use_it", "results/video/use_it.png", ""),
    ("17_0245_playground", "shot:playground_top", "Demo screenshot"),
    ("18_0253_end_card", "results/video/end_card.png", ""),
]


def font(size, bold=False, mono=False):
    return ImageFont.truetype(MONO if mono else INTER_BOLD if bold else INTER, size)


def script_rows():
    """(time, on-screen caption) for every timed row of the script, in order. Markdown marks are removed."""
    rows = []
    for line in SCRIPT.read_text(encoding="utf-8").splitlines():
        if re.match(r"\| \d:\d\d-\d:\d\d \|", line):
            cols = [c.strip() for c in line.strip().strip("|").split(" | ")]
            caption = cols[-1].replace("**", "").replace("`", "")
            rows.append((cols[0], caption))
    return rows


# ---------- screenshots (Playwright, local playground, replay only) ----------

def replay(page, file_name):
    from demo import viewer
    label = viewer.run_label(json.loads((ROOT / "results" / "demo" / "runs" / file_name).read_text(encoding="utf-8")))
    box = page.get_by_label("Recorded run")
    box.click()
    box.fill(label)
    page.get_by_role("option", name=label).click()
    page.get_by_role("button", name="Replay", exact=True).click()
    # The previous run's final banner says "Nothing is running now" too: wait for this replay to start first.
    page.wait_for_selector("text=Replaying a recorded run", timeout=30_000)
    page.wait_for_selector("text=Nothing is running now", timeout=180_000)
    page.wait_for_timeout(800)  # let the last step's animation settle


def scroll_to(page, selector, block="center", nudge=0):
    page.locator(selector).first.evaluate(f"e => e.scrollIntoView({{block: '{block}'}})")
    if nudge:
        page.evaluate(f"window.scrollBy(0, {nudge})")
    page.wait_for_timeout(300)


def shots():
    from playwright.sync_api import sync_playwright
    SHOTS.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        # 1280x720 CSS pixels at 1.5x gives a 1920x1080 image with the page at a readable size.
        page = browser.new_page(viewport={"width": 1280, "height": 720}, device_scale_factor=1.5,
                                color_scheme="light")
        page.goto(URL)
        page.get_by_role("button", name="Replay", exact=True).wait_for(timeout=120_000)
        page.wait_for_timeout(1500)
        page.screenshot(path=SHOTS / "playground_top.png")

        replay(page, RUNS["direct"])
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(300)
        page.screenshot(path=SHOTS / "run1_top.png")
        scroll_to(page, ".ms .result")
        page.screenshot(path=SHOTS / "run1_result.png")

        replay(page, RUNS["simulated"])
        scroll_to(page, ".ms .mail", block="start", nudge=-24)  # the marked email and the four steps
        page.screenshot(path=SHOTS / "run2_steps.png")
        scroll_to(page, ".ms .step", block="start", nudge=-40)  # the steps and the Blocked card
        page.screenshot(path=SHOTS / "run2_result.png")

        replay(page, RUNS["agent"])
        scroll_to(page, ".ms .result")
        page.screenshot(path=SHOTS / "run3_result.png")
        browser.close()
    inspector_diff()
    limitations()
    print("Wrote", ", ".join(sorted(f.name for f in SHOTS.glob("*.png"))))


def inspector_diff():
    """demo/inspector/direct.json and mixshield.json side by side, changed lines marked. The args list is split one item
    per line so it fits; the values are the files' own."""
    left = json.loads((ROOT / "demo" / "inspector" / "direct.json").read_text(encoding="utf-8"))["mcpServers"]["invoices"]
    right = json.loads((ROOT / "demo" / "inspector" / "mixshield.json").read_text(encoding="utf-8"))["mcpServers"]["invoices"]

    def lines(server):
        out = [('"command": ' + json.dumps(server["command"]) + ",", True), ('"args": [', True)]
        out += [("    " + json.dumps(a) + ",", True) for a in server["args"]]
        out.append(("],", True))
        if "connectionTimeout" in server:
            out.append(('"connectionTimeout": ' + str(server["connectionTimeout"]), True))
        return out

    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    d.text((80, 70), "One config change in MCP Inspector", font=font(56, bold=True), fill=TEXT)
    for i, (title, server, bg) in enumerate((("demo/inspector/direct.json (before)", left, RED_BG),
                                             ("demo/inspector/mixshield.json (after)", right, GREEN_BG))):
        x = 80 + i * 900
        d.text((x, 190), title, font=font(30), fill=MUTED)
        d.rounded_rectangle((x, 240, x + 860, 1000), radius=12, fill=SURFACE, outline=LINE, width=2)
        y = 270
        for text, changed in lines(server):
            if changed:
                d.rectangle((x + 2, y - 4, x + 858, y + 38), fill=bg)
            d.text((x + 30, y), text, font=font(28, mono=True), fill=TEXT)
            y += 46
    img.save(SHOTS / "inspector_diff.png")


def limitations():
    """The first two bullets of the README's "Limitations" section, as written there."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    section = readme.split("## Limitations", 1)[1].split("\n## ", 1)[0]
    bullets = [b.strip()[2:] for b in section.strip().splitlines() if b.startswith("- ")][:2]
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    d.text((160, 120), "Limitations", font=font(72, bold=True), fill=TEXT)
    y = 280
    for b in bullets:
        head, _, rest = b.partition("** ")
        head = head.replace("**", "")
        d.text((160, y), head, font=font(40, bold=True), fill=TEXT)
        y += 64
        for line in wrap(d, rest.replace("**", ""), font(34), 1600):
            d.text((160, y), line, font=font(34), fill=MUTED)
            y += 50
        y += 50
    d.text((160, 960), "From README.md, section \"Limitations\"", font=font(26), fill=MUTED)
    img.save(SHOTS / "limitations.png")


# ---------- frames and PDF ----------

def wrap(d, text, f, width):
    words, lines, cur = text.split(), [], ""
    for w in words:
        test = (cur + " " + w).strip()
        if d.textlength(test, font=f) <= width:
            cur = test
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def frame(source: Path, time: str, caption: str, tag: str) -> Image.Image:
    img = Image.new("RGB", (W, H), "white")
    src = Image.open(source)
    if src.mode in ("RGBA", "LA", "P"):
        src = src.convert("RGBA")
        bg = Image.new("RGBA", src.size, "white")
        src = Image.alpha_composite(bg, src).convert("RGB")
    scale = min(W / src.width, CONTENT_H / src.height)
    src = src.resize((round(src.width * scale), round(src.height * scale)), Image.LANCZOS)
    img.paste(src, ((W - src.width) // 2, (CONTENT_H - src.height) // 2))

    d = ImageDraw.Draw(img)
    d.line((0, CONTENT_H, W, CONTENT_H), fill=LINE, width=2)
    d.text((60, CONTENT_H + 22), time, font=font(24, bold=True), fill=ACCENT)
    for i, line in enumerate(wrap(d, caption, font(22), W - 280)[:4]):
        d.text((220, CONTENT_H + 22 + i * 30), line, font=font(22), fill=MUTED)
    if tag:
        f = font(22, bold=True)
        tw = d.textlength(tag, font=f)
        d.rounded_rectangle((W - 60 - tw - 32, 24, W - 60, 24 + 44), radius=8, fill=ACCENT_BG, outline=ACCENT, width=2)
        d.text((W - 60 - tw - 16, 33), tag, font=f, fill=ACCENT)
    return img


def build(only=()):
    """Build every frame, or only those whose name starts with one of `only` (e.g. "16"), then the PDF from all frames
    on disk."""
    rows = script_rows()
    if len(rows) != len(FRAMES):
        sys.exit(f"The script has {len(rows)} timed rows but FRAMES has {len(FRAMES)}: update FRAMES first.")
    OUT.mkdir(parents=True, exist_ok=True)
    built = 0
    for (name, source, tag), (time, caption) in zip(FRAMES, rows):
        if only and not name.startswith(tuple(only)):
            continue
        path = SHOTS / (source[5:] + ".png") if source.startswith("shot:") else ROOT / source
        frame(path, time, caption, tag).save(OUT / f"{name}.png")
        built += 1
    pages = [Image.open(OUT / f"{name}.png").convert("RGB") for name, _, _ in FRAMES]
    pages[0].save(VIDEO / "storyboard.pdf", save_all=True, append_images=pages[1:], resolution=144)
    print(f"Built {built} frame(s) in {OUT}; {VIDEO / 'storyboard.pdf'} has {len(pages)} pages")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "shots":
        shots()
    else:
        build(sys.argv[2:])  # build [frame number prefixes]
