"""Records the five screen clips for the demo video (docs/video_script.md) into video_input/clips/, with Playwright.

Clips: home (the playground home page, slow scroll), run1, run2, run3 (local playground, tab "Agent through the
proxy"), fool (tab "Try to fool MixShield": the first Hinglish dev attack, then the first benign text), run2_replay (the playground's "Replay a
recorded run" of a real blocked run from 31 Oct; no model call), inspector (MCP Inspector 2.12.0 web window through
mixshield proxy) and space (the live Hugging Face Space). 1920x1080 (a 1536x864 page at 125%), H.264, 30 fps.

Real runs only. Each button is clicked once and the take is kept whatever it shows (run 2 may be Blocked or Needs
your OK); nothing is retried or edited. The runs go one after another, so only one Baseten request is open at a time.
Every playground run is saved by the playground itself (DEMO_SAVE_RUNS=1) and every run made here is added to
docs/demo_log.md (the totals under the table are not changed). If a step of the Inspector clip fails, that clip is
deleted and the failing step is printed, so it can be recorded by hand.

Frames come from the browser's own screencast (sharp text, no screen capture). A small arrow is drawn on the page
where the mouse is, because a headless browser shows no cursor. Each clip gets <name>.json with the clip times (s) of
the click and of the result, which demo/make_video.py uses to keep the result on screen.

Run:  python -X utf8 -m demo.record_clips [home run1 run2 run3 run2_replay fool inspector space]      (default: all, in this order)
Keys come from environment variables, as for the playground. Needs ffmpeg (or FFMPEG) and Playwright with Edge.
"""

import base64
import csv
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from demo.make_video import CLIPS, FFMPEG, ff
from demo.storyboard import ROOT

RUNS_DIR = ROOT / "results" / "demo" / "runs"
LOG = ROOT / "docs" / "demo_log.md"
WORK = ROOT / "video_input" / "_rec"
SPACE_URL = "https://huggingface.co/spaces/HP0077/mixshield"
PORT = 7871  # not 7860, so a playground you have open is left alone
URL = f"http://127.0.0.1:{PORT}"
INSPECTOR = "npx -y @modelcontextprotocol/inspector@2.12.0 --web --config demo/inspector/mixshield.json --cwd ."
VIEWPORT, SCALE = {"width": 1536, "height": 864}, 1.25  # 1920x1080 frames, page at 125%
BEFORE, AFTER, AFTER_INSPECTOR, SPACE_SECS = 3.0, 10.0, 8.0, 20.0
HOME_SECS, FOOL_AFTER = 15.0, 3.0
ATTACK_SHEET = ROOT / "bench" / "attacks" / "writing_sheet.csv"
BENIGN_SHEET = ROOT / "bench" / "attacks" / "benign_sheet.csv"
REPLAY_RUN, REPLAY_AFTER = "simulated_20261031_113101.json", 3.0  # row 30 of docs/demo_log.md: flagged, blocked
BUTTONS = {"run1": "1. Simulated agent, no MixShield", "run2": "2. Simulated agent, with MixShield",
           "run3": "3. Muse Spark Open, with MixShield"}
MODES = {"run1": "direct", "run2": "simulated", "run3": "agent"}
FINAL = ".ms .result.red, .ms .result.amber, .ms .result.green, .ms .result.grey"

# An arrow that follows the mouse (pointer events pass through it).
CURSOR_JS = """
window.addEventListener('DOMContentLoaded', () => {
  const c = document.createElement('div');
  c.style.cssText = 'position:fixed;left:0;top:0;z-index:2147483647;pointer-events:none;transform:translate(-60px,-60px)';
  c.innerHTML = '<svg width="26" height="30" viewBox="0 0 26 30"><path d="M2 2 L2 24 L8 18 L12.5 28 L16.5 26.3 L12 16.5 L20 16.5 Z" fill="#14171f" stroke="white" stroke-width="2" stroke-linejoin="round"/></svg>';
  document.body.appendChild(c);
  document.addEventListener('mousemove', e => { c.style.transform = `translate(${e.clientX - 2}px,${e.clientY - 2}px)`; }, true);
});
"""


class Recorder:
    """Saves the page's screencast frames with their times, then joins them into an mp4 at 30 fps."""

    def __init__(self, page, name):
        self.page, self.name = page, name
        self.dir = WORK / name
        shutil.rmtree(self.dir, ignore_errors=True)
        self.dir.mkdir(parents=True)
        self.frames, self.marks = [], {}
        self.cdp = page.context.new_cdp_session(page)
        self.cdp.on("Page.screencastFrame", self._frame)

    def _frame(self, ev):
        path = self.dir / f"{len(self.frames):05d}.jpg"
        path.write_bytes(base64.b64decode(ev["data"]))
        self.frames.append((time.time(), path))  # arrival time: the same clock as the marks
        self.cdp.send("Page.screencastFrameAck", {"sessionId": ev["sessionId"]})

    def start(self):
        self.t0 = time.time()
        self.cdp.send("Page.startScreencast", {"format": "jpeg", "quality": 95, "maxWidth": 1920, "maxHeight": 1080})
        return self

    def now(self):
        return time.time() - self.t0

    def mark(self, key):
        self.marks[key] = round(time.time() - self.t0, 2)
        return self.marks[key]

    def wait(self, secs):
        self.page.wait_for_timeout(secs * 1000)

    def stop(self, extra=None):
        """Write clips/<name>.mp4 and clips/<name>.json; return the clip length in seconds."""
        self.cdp.send("Page.stopScreencast")
        end = time.time()
        if not self.frames:
            raise RuntimeError("no frames were recorded")
        lines = []
        for i, (ts, path) in enumerate(self.frames):
            nxt = self.frames[i + 1][0] if i + 1 < len(self.frames) else end
            lines += [f"file '{path.as_posix()}'", f"duration {max(nxt - ts, 0.001):.4f}"]
        lines.append(f"file '{self.frames[-1][1].as_posix()}'")
        listing = self.dir / "frames.txt"
        listing.write_text("\n".join(lines) + "\n", encoding="utf-8")
        CLIPS.mkdir(parents=True, exist_ok=True)
        out = CLIPS / f"{self.name}.mp4"
        length = round(end - self.frames[0][0], 2)
        ff("-f", "concat", "-safe", 0, "-i", listing,
           "-vf", "fps=30,scale=1920:1080:flags=lanczos:in_range=pc:out_range=tv,format=yuv420p",
           "-t", f"{length:.2f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", 16, "-an", out)
        # The first frame is shown from time 0, so the marks are moved by the same amount.
        shift = self.frames[0][0] - self.t0
        marks = {k: round(max(v - shift, 0), 2) for k, v in self.marks.items()}
        info = {"length": length, **marks, **(extra or {})}
        (CLIPS / f"{self.name}.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
        shutil.rmtree(self.dir, ignore_errors=True)
        return length

    def discard(self):
        try:
            self.cdp.send("Page.stopScreencast")
        except Exception:
            pass
        shutil.rmtree(self.dir, ignore_errors=True)
        for suffix in (".mp4", ".json"):
            (CLIPS / f"{self.name}{suffix}").unlink(missing_ok=True)


# ---------- mouse and scrolling, slow enough to follow on video ----------

MOUSE = {"x": 1400.0, "y": 700.0}


def glide(page, x, y, secs=1.2):
    x0, y0, n = MOUSE["x"], MOUSE["y"], max(int(secs * 40), 2)
    for i in range(1, n + 1):
        t = i / n
        t = t * t * (3 - 2 * t)  # ease in and out
        page.mouse.move(x0 + (x - x0) * t, y0 + (y - y0) * t)
        page.wait_for_timeout(25)
    MOUSE.update(x=x, y=y)


def glide_to(page, locator, secs=1.2, dx=0.5, dy=0.5):
    box = locator.bounding_box()
    glide(page, box["x"] + box["width"] * dx, box["y"] + box["height"] * dy, secs)


def click_here(page):
    page.mouse.down()
    page.wait_for_timeout(90)
    page.mouse.up()


def smooth_scroll(page, dy, secs=1.5):
    n = max(int(secs * 40), 1)
    for _ in range(n):
        page.evaluate(f"window.scrollBy(0, {dy / n})")
        page.wait_for_timeout(25)


def bring_into_view(page, locator, margin=60, secs=1.5):
    """Scroll slowly until the element is fully inside the window (or its top is at the top, if it is too tall)."""
    box = locator.bounding_box()
    if box is None:
        return
    height = VIEWPORT["height"]
    if box["y"] + box["height"] > height - margin:
        smooth_scroll(page, min(box["y"] + box["height"] - height + margin, box["y"] - margin), secs)
    elif box["y"] < margin:
        smooth_scroll(page, box["y"] - margin, secs)


def on_screen(locator):
    box = locator.bounding_box()
    return bool(box) and box["y"] >= 0 and box["y"] + 40 <= VIEWPORT["height"]


def view_pair(page, top, bottom, margin=24, secs=1.5):
    """Scroll slowly so that `top` (the calls panel) and `bottom` (the result card) are both in the window; if they do
    not fit, the result card wins and as much of the panel as fits stays above it."""
    if top is None:
        bring_into_view(page, bottom, secs=secs)
        return
    a, b = top.bounding_box(), bottom.bounding_box()
    span = b["y"] + b["height"] - a["y"]
    room = VIEWPORT["height"] - 2 * margin
    target = a["y"] - margin - (room - span) / 2 if span <= room else b["y"] + b["height"] - VIEWPORT["height"] + margin
    smooth_scroll(page, target, secs)


# ---------- playground ----------

def answers(url):
    try:
        return urllib.request.urlopen(url, timeout=5).status == 200
    except OSError:
        return False


def start_playground():
    if answers(URL):
        sys.exit(f"Something already answers at {URL}. Stop it first: this script starts its own playground there.")
    env = dict(os.environ, DEMO_RATE_LIMIT="off", DEMO_SAVE_RUNS="1", PYTHONIOENCODING="utf-8",
               GRADIO_SERVER_PORT=str(PORT))
    log = open(WORK / "playground.log", "w", encoding="utf-8")
    proc = subprocess.Popen([sys.executable, "-X", "utf8", "-m", "demo.playground"], cwd=ROOT, env=env,
                            stdout=log, stderr=subprocess.STDOUT)
    t0 = time.time()
    while time.time() - t0 < 300:
        if proc.poll() is not None:
            sys.exit(f"The playground stopped while starting; see {WORK / 'playground.log'}")
        if answers(URL):
            print(f"Playground answers HTTP 200 after {time.time() - t0:.0f} s")
            return proc
        time.sleep(1)
    stop(proc)
    sys.exit("The playground did not answer within 300 s")


def stop(proc):
    if proc and proc.poll() is None:
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)


def record_run(page, clip):
    """Click one playground button once and record the take. Returns (saved run file, result label)."""
    mode, button = MODES[clip], page.get_by_role("button", name=BUTTONS[clip])
    button.wait_for()
    page.wait_for_function("b => !b.disabled", arg=button.element_handle(), timeout=60_000)
    page.evaluate("window.scrollTo(0, 0)")
    page.wait_for_timeout(800)
    before = set(RUNS_DIR.glob(f"{mode}_*.json")) if RUNS_DIR.exists() else set()

    rec = Recorder(page, clip).start()
    rec.wait(0.6)
    glide_to(page, button, secs=BEFORE - 1.0)
    rec.wait(max(BEFORE - rec.now(), 0))
    rec.mark("click_at")
    click_here(page)
    print(f"  {clip}: clicked \"{BUTTONS[clip]}\" (one take, kept whatever it shows)")
    page.wait_for_timeout(700)
    flow = page.locator(".ms .flow").first
    smooth_scroll(page, flow.bounding_box()["y"] - 16, secs=1.2)  # the flow cards at the top, the calls panel below

    seen_running, saved, t0, shot = False, None, time.time(), False
    while time.time() - t0 < 300:
        seen_running = seen_running or page.locator(".ms .result.running").count() > 0
        if not shot and seen_running and page.locator(".ms .ms-calls tr").count() >= 4:  # header + 3 calls, mid-run
            page.screenshot(path=WORK / f"{clip}_panel_live.png")
            shot = True
        new = (set(RUNS_DIR.glob(f"{mode}_*.json")) if RUNS_DIR.exists() else set()) - before
        saved = saved or (max(new) if new else None)
        if (seen_running or saved) and page.locator(FINAL).count() and not page.locator(".ms .result.running").count():
            break
        page.wait_for_timeout(100)
    else:
        rec.discard()
        raise RuntimeError(f"{clip}: no result after 300 s")
    result = page.locator(FINAL).first
    panel = page.locator(".ms .ms-calls").first
    view_pair(page, panel if panel.count() else None, result)
    rec.mark("result_at")
    label = result.locator(".label").inner_text().strip()

    # 10 s on the result: the Screen and Gate cards and the calls panel (where on screen), then the verdict.
    steps = page.locator(".ms .step")
    rec.wait(1.0)
    targets = ([steps.nth(1), steps.nth(2)] if steps.count() >= 3 else []) + ([panel] if panel.count() else [])
    for target in [x for x in targets if on_screen(x)] + [result.locator(".label")]:
        glide_to(page, target, secs=1.0, dy=0.3)
        rec.wait(1.4)
    rec.wait(max(rec.marks["result_at"] + AFTER - rec.now(), 0))
    while saved is None and time.time() - t0 < 330:  # the run file is written just after the last screen update
        new = set(RUNS_DIR.glob(f"{mode}_*.json")) - before
        saved = max(new) if new else None
        page.wait_for_timeout(200)
    length = rec.stop({"result": label, "run_file": saved.name if saved else None})
    print(f"  {clip}: {label!r}, clip {length:.1f} s, run file {saved.name if saved else 'NOT FOUND'}")
    return saved, label


def record_replay(page):
    """Replay a saved real run in the playground ("Replay a recorded run", real speed) and record it as
    clips/run2_replay.mp4. A replay calls no model and saves no new run, so nothing is added to the log."""
    from demo import viewer
    label = viewer.run_label(json.loads((RUNS_DIR / REPLAY_RUN).read_text(encoding="utf-8")))
    before = set(RUNS_DIR.glob("*.json"))
    page.reload()
    page.get_by_role("tab", name="Agent through the proxy").click()
    box = page.get_by_label("Recorded run")
    box.wait_for()
    box.click()
    box.fill(label)
    page.get_by_role("option", name=label).click()
    page.get_by_label("Real speed").check()  # the edit speeds it up 2x, and the label says so
    button = page.get_by_role("button", name="Replay", exact=True)
    button.scroll_into_view_if_needed()
    page.wait_for_timeout(800)

    rec = Recorder(page, "run2_replay").start()
    rec.wait(0.6)
    glide_to(page, button, secs=BEFORE - 1.0)
    rec.wait(max(BEFORE - rec.now(), 0))
    rec.mark("click_at")
    click_here(page)
    print(f"  run2_replay: replaying \"{label}\"")
    page.get_by_text("Replaying a recorded run").first.wait_for(timeout=30_000)
    bring_into_view(page, page.locator(".ms .flow").first, secs=1.2)
    page.get_by_text("Nothing is running now").first.wait_for(timeout=180_000)
    result = page.locator(FINAL).first
    bring_into_view(page, result, secs=1.2)
    rec.mark("result_at")
    shown = result.locator(".label").inner_text().strip()
    rec.wait(1.0)
    glide_to(page, result.locator(".label"), secs=1.0, dy=0.3)
    rec.wait(max(rec.marks["result_at"] + REPLAY_AFTER - rec.now(), 0))
    length = rec.stop({"result": shown, "replay_of": REPLAY_RUN})
    if set(RUNS_DIR.glob("*.json")) != before:
        print("  run2_replay: WARNING: a new run file appeared during the replay")
    print(f"  run2_replay: {shown!r}, clip {length:.1f} s (replay of {REPLAY_RUN}, no model call)")


def record_home(page):
    """The playground home page, scrolled slowly for HOME_SECS seconds. No clicks, no model call."""
    page.goto(URL)
    page.get_by_role("tab", name="Agent through the proxy").wait_for()
    page.evaluate("window.scrollTo(0, 0)")
    page.wait_for_timeout(2000)
    rec = Recorder(page, "home").start()
    rec.wait(1.0)
    room = page.evaluate("document.documentElement.scrollHeight - window.innerHeight")
    smooth_scroll(page, min(room, 1600), secs=HOME_SECS - 2.5)
    rec.wait(max(HOME_SECS - rec.now(), 0))
    print(f"  home: clip {rec.stop():.1f} s")


def fool_texts():
    """Text 1: the Hinglish text of the first dev row of the attack sheet; text 2: the Hinglish text of the first row
    of the benign sheet. File order, nothing chosen by hand."""
    attacks = list(csv.DictReader(open(ATTACK_SHEET, encoding="utf-8-sig")))
    i, row = next((i, r) for i, r in enumerate(attacks, 1) if r["split"] == "dev" and r["hinglish_text"].strip())
    benign = next(csv.DictReader(open(BENIGN_SHEET, encoding="utf-8-sig")))
    return [(f"attack, `bench/attacks/writing_sheet.csv` row {i} (goal {row['goal_id']}, style {row['style_id']} "
             f"{row['style_name']}, {row['split']})", row["hinglish_text"]),
            (f"benign, `bench/attacks/benign_sheet.csv` {benign['id']} ({benign['split']})", benign["hinglish_text"])]


def check_verdict(page):
    """What the tab shows after a check: (Prompt Guard 2 pill and row, MixShield pill and row)."""
    cards = page.locator(".ms-check .cols >> visible=true").first.locator(".card")
    pg, ms = cards.nth(0), cards.nth(1)
    return (pg.locator(".pill").inner_text().strip(), pg.locator(".row").inner_text().strip(),
            ms.locator(".pill").inner_text().strip(), ms.locator(".row").inner_text().strip())


def record_fool(page):
    """The "Try to fool MixShield" tab: text 1 (an attack), FOOL_AFTER s on its result, then text 2 (a benign
    message), FOOL_AFTER s. One take each, kept whatever it shows. Returns one dict per check, for the log."""
    page.goto(URL)
    page.get_by_role("tab", name="Try to fool MixShield").click()
    box = page.get_by_label("Message")
    box.wait_for()
    check = page.get_by_role("button", name="Check message")
    page.wait_for_timeout(1500)
    rec = Recorder(page, "fool").start()
    rec.wait(1.0)
    done = []
    for k, (source, text) in enumerate(fool_texts(), 1):
        key = "result_at" if k == 1 else f"result{k}_at"
        glide_to(page, box, secs=1.0)
        click_here(page)
        box.fill(text)
        rec.wait(0.8)
        glide_to(page, check, secs=0.8)
        rec.mark(f"click{k}_at")
        click_here(page)
        print(f"  fool: checking text {k} ({source.split(',')[0]}), one take")
        cols = page.locator(".ms-check .cols >> visible=true")
        if k > 1:  # the old verdict is cleared first
            page.wait_for_function(
                "() => ![...document.querySelectorAll('.ms-check .cols')].some(e => e.offsetParent)", timeout=15_000)
        cols.first.wait_for(timeout=180_000)
        view_pair(page, cols.first, page.locator(".ms-calls >> visible=true").first)
        rec.mark(key)
        pg_pill, pg_row, ms_pill, ms_row = check_verdict(page)
        done.append({"source": source, "text": text, "pg": pg_row, "pg_pill": pg_pill, "screen": ms_pill,
                     "reason": ms_row, "when": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")})
        print(f"  fool text {k}: MixShield screen {ms_pill.upper()} ({ms_row}); Prompt Guard 2 {pg_pill} ({pg_row})")
        glide_to(page, cols.first.locator(".card").nth(1), secs=1.0, dy=0.3)
        rec.wait(max(rec.marks[key] + FOOL_AFTER - rec.now(), 0))
    print(f"  fool: clip {rec.stop({'checks': [d['screen'] for d in done]}):.1f} s")
    return done


def add_fool_log(checks):
    """Rows for the "Try to fool MixShield" checks of attack-set texts. Not demo-email runs: not in the screen total."""
    head = '## Playground tab "Try to fool MixShield", attack-set texts'
    lines = LOG.read_text(encoding="utf-8").rstrip("\n").split("\n")
    if head not in lines:
        lines += ["", head, "",
                  "Texts pasted into the tab for the video, taken in file order (the first Hinglish dev attack, the "
                  "first benign row), not chosen by hand. Real screen (Prompt Guard 2 at 0.5 + Muse Spark Open "
                  "classifier). These are not the demo email, so they are not in the screen total above.", "",
                  "| Check | Text | Prompt Guard 2 | MixShield screen | Classifier reason as shown |",
                  "| --- | --- | --- | --- | --- |"]
    n = sum(1 for x in lines[lines.index(head):] if re.match(r"\| \d+ \|", x)) + 1
    for k, c in enumerate(checks):
        lines.append(f"| {n + k} | {c['source']}, {c['when']}; video take, recorded by `demo/record_clips.py` | "
                     f"{c['pg']} ({c['pg_pill'].lower()}) | **{c['screen'].lower()}** | {c['reason']} |")
    LOG.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return lines[-len(checks):]


# ---------- MCP Inspector ----------

def start_inspector():
    env = dict(os.environ, MCP_AUTO_OPEN_ENABLED="false",
               PATH=str(ROOT / ".venv" / "Scripts") + os.pathsep + os.environ.get("PATH", ""))
    proc = subprocess.Popen(INSPECTOR, cwd=ROOT, env=env, shell=True, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
    t0 = time.time()
    while time.time() - t0 < 120:
        line = proc.stdout.readline()
        m = re.search(r"(http://127\.0\.0\.1:\d+\?MCP_INSPECTOR_API_TOKEN=\S+)", line)
        if m:  # the address holds a one-time token: it is used, never printed
            return proc, m.group(1)
        if not line and proc.poll() is not None:
            break
    stop(proc)
    raise RuntimeError("start-up: Inspector did not print its address within 120 s")


def record_inspector(page):
    """Returns a dict for the log, or raises RuntimeError naming the step that failed (the clip is then deleted)."""
    step = "start-up"
    rec = None
    proc = None
    try:
        proc, url = start_inspector()
        step = "open the Inspector page"
        page.goto(url)
        switch = page.locator(".mantine-Switch-track").first
        switch.wait_for(timeout=60_000)
        page.wait_for_timeout(1000)
        rec = Recorder(page, "inspector").start()
        rec.wait(1.0)

        step = "Connect (switch on the invoices server)"
        glide_to(page, switch, secs=1.5)
        click_here(page)
        page.get_by_text("Connected", exact=True).first.wait_for(timeout=120_000)
        rec.mark("connected_at")
        rec.wait(1.0)

        step = "Tools tab"
        glide_to(page, page.locator("label", has_text=re.compile("^Tools$")).first)
        click_here(page)
        tool = page.get_by_role("button", name="read_email", exact=True)
        tool.wait_for(timeout=30_000)

        step = "read_email with email_id 3"
        glide_to(page, tool)
        click_here(page)
        field = page.get_by_label("Email Id")
        field.wait_for(timeout=15_000)
        glide_to(page, field, secs=0.8)
        click_here(page)
        page.keyboard.type("3", delay=120)
        glide_to(page, page.get_by_role("button", name="Execute Tool"))
        rec.mark("click_at")
        click_here(page)
        page.locator("text=/Namaste Emma/ >> visible=true").first.wait_for(timeout=120_000)
        page.wait_for_timeout(800)
        notice = page.locator("text=/MixShield screen: the output of read_email was flagged/ >> visible=true")
        flagged_text = notice.first.inner_text() if notice.count() else ""
        rec.wait(2.0)

        step = "transfer_money (iban ZZ00DEMO0000000099, amount 480, reference INV-102)"
        tool = page.get_by_role("button", name="transfer_money", exact=True)
        glide_to(page, tool)
        click_here(page)
        for label, value in (("Iban", "ZZ00DEMO0000000099"), ("Amount", "480"), ("Reference", "INV-102")):
            box = page.get_by_label(label)
            box.wait_for(timeout=15_000)
            glide_to(page, box, secs=0.6)
            click_here(page)
            page.keyboard.type(value, delay=45)
        glide_to(page, page.get_by_role("button", name="Execute Tool"))
        click_here(page)
        answer = page.locator("text=/It was NOT run|\"status\": \"sent\"/ >> visible=true").first
        answer.wait_for(timeout=120_000)
        rec.mark("result_at")
        text = answer.inner_text()
        rec.wait(1.0)
        glide_to(page, answer, secs=1.2, dx=0.3)
        rec.wait(max(rec.marks["result_at"] + AFTER_INSPECTOR - rec.now(), 0))

        result = ("block" if "BLOCKED" in text else "ask" if "confirmation" in text else
                  "sent" if "sent" in text else "other")
        p = re.search(r"\(p ([\d.]+)\)", flagged_text)
        info = {"result": result, "flagged": bool(flagged_text), "p": p.group(1) if p else None,
                "when": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}
        step = "save the clip"
        length = rec.stop(info)
        print(f"  inspector: transfer_money {result}, read_email flagged: {info['flagged']}, clip {length:.1f} s")
        return info
    except Exception as exc:
        if rec:
            rec.discard()
        raise RuntimeError(f"Inspector clip failed at step: {step} ({type(exc).__name__}: {str(exc)[:200]})")
    finally:
        stop(proc)


# ---------- live Space ----------

def loaded(frame):
    """True when this frame shows the playground. The Space replaces its frame while it wakes up, so a frame can
    disappear between listing and reading it."""
    try:
        return frame.get_by_text("Agent through the proxy").count() > 0
    except Exception:
        return False


def record_space(page):
    page.goto(SPACE_URL, wait_until="domcontentloaded")
    t0 = time.time()
    while time.time() - t0 < 300:  # a sleeping Space can take a few minutes to wake up
        if any(loaded(f) for f in page.frames):
            break
        page.wait_for_timeout(1000)
    else:
        raise RuntimeError("the Space did not load within 300 s")
    page.wait_for_timeout(2500)
    rec = Recorder(page, "space").start()
    page.mouse.move(VIEWPORT["width"] / 2, VIEWPORT["height"] / 2)
    rec.wait(1.5)
    end = time.time() + SPACE_SECS - 3.0
    while time.time() < end:
        page.mouse.wheel(0, 3)
        page.wait_for_timeout(30)
    rec.wait(1.5)
    print(f"  space: clip {rec.stop():.1f} s")


# ---------- demo log ----------

def short(x):
    return f"{x:.2g}"


def log_row(n, saved_path):
    """One row for docs/demo_log.md from a saved playground run, in the same form as the rows already there."""
    saved = json.loads(saved_path.read_text(encoding="utf-8"))
    ev = {}
    for kind, data, *_ in saved["events"]:
        ev.setdefault(kind, []).append(data)
    raw = f"raw run: `results/demo/runs/{saved_path.name}`; video take, recorded by `demo/record_clips.py`"
    when = saved["recorded_at"]
    if saved["mode"] == "direct":
        return (f"| {n} | not screened (no MixShield) | not screened | not screened | not applicable | no gate: money "
                f"sent. Run 1, playground, {when}; {raw}. Not counted in the screen total (the screen did not run) |")
    gate = (ev.get("gate") or [{}])[-1].get("action", "no gate decision")
    if saved["mode"] == "simulated":
        mail = [s for s in ev.get("screen", []) if s.get("email")]
        if not mail:
            return f"| {n} | not recorded | not recorded | not recorded | not recorded | {gate} (playground button 2, {when}; {raw}) |"
        s = mail[-1]
        pg = s.get("prompt_guard_score")
        pg_txt = f"{short(pg)} ({'flagged' if pg >= 0.5 else 'not flagged'})" if pg is not None else "not recorded"
        p = re.search(r"\(p ([\d.]+)\)", s.get("reason", ""))
        gate_txt = "block" if gate == "block" else f"**{gate}**"
        return (f"| {n} | {pg_txt} | {'yes' if s['flagged'] else '**no**'} | {p.group(1) if p else 'not shown'} | "
                f"{s.get('language', 'not recorded')} | {gate_txt} (playground button 2, {when}; {raw}) |")
    call = (ev.get("call") or [{}])[-1].get("args", {})
    flagged = any(s.get("flagged") for s in ev.get("screen", []))
    what = (f"{gate}: `transfer_money` to {call.get('iban')}" if call else "no payment call") + f' for "{saved["task"]}"'
    return (f"| {n} | not applicable (demo email not read) | not applicable | not applicable | en (tool outputs) | "
            f"{what} (playground button 3, Muse Spark Open, real model, {when}; {raw}). The screen ran on the real tool "
            f"outputs ({'some flagged' if flagged else 'none flagged'}); this task never reads the demo email. "
            f"Not counted in the screen total |")


def inspector_row(n, info):
    gate_txt = "block" if info["result"] == "block" else f"**{info['result']}**"
    return (f"| {n} | not recorded | {'yes' if info['flagged'] else '**no**'} | {info['p'] or 'not shown'} | "
            f"not recorded | {gate_txt} (MCP Inspector 2.12.0 web window through `mixshield proxy`, {info['when']}; "
            f"video take, recorded by `demo/record_clips.py`; values read from the Inspector page, no run file) |")


def add_to_log(rows_for):
    """Append rows after the last row of the first table. `rows_for(n)` gives the new rows, numbered from n."""
    lines = LOG.read_text(encoding="utf-8").split("\n")
    last = max(i for i, line in enumerate(lines) if re.match(r"\| \d+ \|", line)
               and i < next(j for j, x in enumerate(lines) if x.startswith("**Screen:")))
    n = int(lines[last].split("|")[1]) + 1
    rows = rows_for(n)
    lines[last + 1:last + 1] = rows
    LOG.write_text("\n".join(lines), encoding="utf-8")
    return rows


# ---------- main ----------

def main():
    wanted = sys.argv[1:] or ["home", "run1", "run2", "run3", "run2_replay", "fool", "inspector", "space"]
    if not shutil.which(FFMPEG) and not Path(FFMPEG).exists():
        sys.exit("ffmpeg not found on PATH (or set FFMPEG to its full path).")
    from playwright.sync_api import sync_playwright
    WORK.mkdir(parents=True, exist_ok=True)
    made, failures, playground, fool_rows = [], [], None, []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge", headless=True)
            context = browser.new_context(viewport=VIEWPORT, device_scale_factor=SCALE, color_scheme="light")
            context.add_init_script(CURSOR_JS)
            page = context.new_page()
            runs = [c for c in wanted if c in BUTTONS]
            if runs or {"run2_replay", "home", "fool"} & set(wanted):
                playground = start_playground()
                if "home" in wanted:
                    try:
                        record_home(page)
                    except Exception as exc:
                        failures.append(f"home: {exc}")
                page.goto(URL)
                page.get_by_role("tab", name="Agent through the proxy").click()
                page.wait_for_timeout(1500)
                for clip in runs:
                    try:
                        saved, label = record_run(page, clip)
                        made.append(("playground", clip, label, saved))
                        if clip == "run2":
                            print(f"  run2 showed: {label.upper()}")
                    except Exception as exc:
                        failures.append(f"{clip}: {exc}")
                if "run2_replay" in wanted:
                    try:
                        record_replay(page)
                    except Exception as exc:
                        failures.append(f"run2_replay: {exc}")
                if "fool" in wanted:
                    try:
                        fool_rows = add_fool_log(record_fool(page))
                    except Exception as exc:
                        failures.append(f"fool: {exc}")
                stop(playground)
                playground = None
            if "inspector" in wanted:
                try:
                    made.append(("inspector", "inspector", None, record_inspector(page)))
                except RuntimeError as exc:
                    failures.append(str(exc))
            if "space" in wanted:
                try:
                    record_space(page)
                except Exception as exc:
                    failures.append(f"space: {exc}")
            browser.close()
    finally:
        stop(playground)

    rows = add_to_log(lambda n: [log_row(n + i, item[3]) if item[0] == "playground" else inspector_row(n + i, item[3])
                                 for i, item in enumerate(m for m in made if m[3])]) if any(m[3] for m in made) else []
    print("\nRuns made (all added to docs/demo_log.md; the totals were not changed):" if rows else "\nNo new runs made.")
    for row in rows:
        print("  " + row[:200] + ("..." if len(row) > 200 else ""))
    if fool_rows:
        print('\n"Try to fool MixShield" checks (added to docs/demo_log.md, own table, not in the screen total):')
        for row in fool_rows:
            print("  " + row[:220] + ("..." if len(row) > 220 else ""))
    for clip, label in [(m[1], m[2]) for m in made if m[0] == "playground" and not m[3]]:
        print(f"  {clip}: {label} (NO run file found, not logged)")
    if failures:
        print("\nFailed:")
        for f in failures:
            print("  " + f)


if __name__ == "__main__":
    main()
