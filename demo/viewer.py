"""The demo viewer: turns the events of one run into one HTML block. No Gradio here, so it can be tested alone.

A run is a plain dict (`new_run`) that `apply` fills one event at a time; `render` draws it. The flow
    Email -> Screen -> Gate -> Result
fills in as the real events arrive (nothing is delayed or timed for show). Everything shown comes from the run:
the email text, the screen verdicts, the gate's own reason, the tool's own result. Both outcomes are drawn as they
are: flagged -> the gate blocks (Blocked, red); not flagged -> the gate asks (Needs your OK, amber); trusted
payee -> Paid (green); no MixShield -> Money sent (red).

Event kinds (`apply(run, kind, data)`):
  email      {"from", "subject", "body"}     the email the agent read
  screening  {"tool", "done"}                the screen started (done false or missing) or finished on one tool output
  screen     {"flagged", "language", "reason", "prompt_guard_score", "unavailable", "tool", "email"}
                                             the verdict on one text of a tool output; "email" is true for the email
                                             the payment is about (events saved before 31 Oct have no "email": all
                                             of them were emails)
  call       {"tool", "args"}                the payment call the agent proposed
  gate       {"action", "reason"}            allow | ask | block
  result     {"is_error", "text"}            what the tool call returned
  answer     str                             the agent's final text (real agent only)
  error      str                             the run failed
  done       {}

`run["fresh"]` lists the flow cards that changed with the last event; only those get the fade-in, so an update
never replays the animation of a card that was already on screen.
"""

import html
import json
import re
import time

PG_THRESHOLD = 0.5  # the default Prompt Guard 2 threshold used by the screen (a placeholder, shown as such)
CURRENCY = "$"  # the demo data has no currency; every amount is shown with this one symbol (the real model also writes "$")
REPO_URL = "https://github.com/HP0077/mixshield"

CAPTION_SIMULATION = ("In our tests (E1), neither Muse Spark nor Muse Spark Open was hijacked: 0 of 536 scorable "
                      "attacks succeeded. A future model or prompt may be weaker, so here we test the worst case: a "
                      "scripted agent that obeys any instruction it reads.")
BANNER_SIMULATION = "Simulation. A scripted agent that obeys any instruction it reads. It is not a real model."
BANNER_REAL = "Real model. Muse Spark Open (Baseten) calls its tools through the MixShield proxy."
TWO_LAYERS = "Two layers: if the screen misses, the gate still stops untrusted payments."
FOOTER = "Built with Llama. All data is fake."

# Registers the clock's counter as an integer so the browser can animate it. It goes in the page head, not in CSS: Gradio
# rewrites the rules of its css argument and the registration then does not take effect.
PROPERTY_CSS = "@property --ms-t{syntax:'<integer>';inherits:false;initial-value:0}"

CSS = """
:root{
  --ms-bg:#ffffff; --ms-surface:#f7f8fa; --ms-text:#14171f; --ms-muted:#586070; --ms-line:#e1e4ea; --ms-line-strong:#c9ced8;
  --ms-accent:#2b55c4; --ms-accent-bg:#eef2fc;
  --ms-red:#b42318; --ms-red-bg:#fef3f2; --ms-red-line:#f4b8b2;
  --ms-amber:#93370d; --ms-amber-bg:#fffaeb; --ms-amber-line:#f5d089;
  --ms-green:#067647; --ms-green-bg:#ecfdf3; --ms-green-line:#a6e3c1;
  --ms-font:'Inter',system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;
  --ms-mono:'JetBrains Mono',ui-monospace,'SF Mono',Menlo,Consolas,monospace;
}
.ms,.ms-check{font-family:var(--ms-font);color:var(--ms-text);font-size:15px;line-height:1.5}
.ms *,.ms-check *{box-sizing:border-box}
.ms code,.ms-check code,.ms .mono,.ms-check .mono{font-family:var(--ms-mono);font-size:12.5px;background:var(--ms-surface);
  border:1px solid var(--ms-line);border-radius:4px;padding:1px 5px;overflow-wrap:anywhere}
.ms .banner:first-child{margin-top:24px}
.ms .banner{background:var(--ms-surface);border:1px solid var(--ms-line);border-radius:6px;padding:8px 12px;
  color:var(--ms-text);font-size:14px;margin-bottom:8px}
.ms .banner b{font-weight:600}
.ms .caption{color:var(--ms-muted);font-size:14px;margin:0 0 16px;max-width:820px}
.ms .task{font-size:14px;color:var(--ms-muted);margin:16px 0}
.ms .task code{color:var(--ms-text)}

.ms .mail{border:1px solid var(--ms-line);border-radius:8px;background:var(--ms-bg);margin-bottom:24px;overflow:hidden}
.ms .mail-head{padding:12px 16px;border-bottom:1px solid var(--ms-line);background:var(--ms-surface)}
.ms .mail-subject{font-weight:600;font-size:15px}
.ms .mail-from{color:var(--ms-muted);font-size:13px}
.ms .mail-body{padding:16px;font-size:15px;line-height:1.6}
.ms .mail mark{background:var(--ms-red-bg);color:inherit;border-bottom:2px solid var(--ms-red);padding:1px 2px;border-radius:2px}
.ms .tag.neutral{color:var(--ms-muted);background:var(--ms-bg);border-color:var(--ms-line-strong);font-weight:500}
.ms .rtoggle{position:absolute;opacity:0;pointer-events:none}
.ms .reason.clamp{display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:2;overflow:hidden}
.ms .rtoggle:checked ~ .reason.clamp{-webkit-line-clamp:unset;display:inline}
.ms .rlabel{display:block;margin-top:4px;font-size:12px;color:var(--ms-accent);cursor:pointer;text-decoration:underline}
.ms .rlabel .less,.ms .rtoggle:checked ~ .rlabel .more{display:none}
.ms .rtoggle:checked ~ .rlabel .less{display:inline}
.ms .tag{display:inline-block;margin-left:6px;font-size:11px;font-weight:600;color:var(--ms-red);background:var(--ms-red-bg);
  border:1px solid var(--ms-red-line);border-radius:4px;padding:0 6px;vertical-align:1px;white-space:nowrap}

.ms .flow{display:grid;grid-template-columns:1fr 1.2fr 1.3fr 1fr;gap:24px;list-style:none;margin:0;padding:0}
.ms .flow>li{margin:0 !important;padding-left:16px !important}
.ms .step{position:relative;border:1px solid var(--ms-line);border-radius:8px;padding:16px;background:var(--ms-bg);min-width:0}
.ms .step:not(:last-child)::after{content:"";position:absolute;top:32px;right:-25px;width:24px;height:1px;background:var(--ms-line-strong)}
.ms .step.waiting,.ms .step.skipped{background:var(--ms-surface)}
.ms .step.waiting .detail,.ms .step.skipped .detail,.ms .step.waiting h4,.ms .step.skipped h4{color:var(--ms-muted)}
.ms .step h4{flex-wrap:wrap;margin:0 0 8px;font-size:12px;font-weight:600;letter-spacing:.04em;text-transform:uppercase;color:var(--ms-muted);
  display:flex;justify-content:space-between;align-items:center;gap:8px}
.ms .detail{font-size:13px;line-height:1.5;overflow-wrap:break-word;margin-top:8px}
.ms .detail .row{margin-top:4px}
.ms .detail .k{color:var(--ms-muted)}
.ms code.call{display:block;font-size:12px;line-height:1.6;padding:6px 8px}
.ms code.call span{display:block;overflow-wrap:anywhere}
.ms code.call .arg{padding-left:12px}

.ms .pill{text-transform:none;letter-spacing:0;display:inline-flex;align-items:center;gap:6px;font-size:12px;font-weight:600;line-height:20px;border-radius:999px;
  padding:0 8px;border:1px solid var(--ms-line-strong);color:var(--ms-muted);background:var(--ms-bg);white-space:nowrap}
.ms .pill::before{content:"";width:6px;height:6px;border-radius:50%;background:currentColor}
.ms .pill.red{color:var(--ms-red);background:var(--ms-red-bg);border-color:var(--ms-red-line)}
.ms .pill.amber{color:var(--ms-amber);background:var(--ms-amber-bg);border-color:var(--ms-amber-line)}
.ms .pill.green{color:var(--ms-green);background:var(--ms-green-bg);border-color:var(--ms-green-line)}
.ms .pill.accent{color:var(--ms-accent);background:var(--ms-accent-bg);border-color:#bccaf1}
.ms .pill.dark{color:var(--ms-text)}
.ms .pill.pulse::before{animation:ms-pulse 1.2s ease-in-out infinite}

.ms .two{color:var(--ms-muted);font-size:14px;margin:16px 0 24px}

.ms .result{border:1px solid var(--ms-line-strong);border-radius:8px;padding:24px;background:var(--ms-surface)}
.ms .result .label{font-size:32px;line-height:1.2;font-weight:600;letter-spacing:-.01em}
.ms .result .why{font-size:15px;margin-top:8px;overflow-wrap:anywhere;max-width:860px}
.ms .result .money{margin-top:16px;padding-top:16px;border-top:1px solid var(--ms-line);font-size:14px;color:var(--ms-muted)}
.ms .result .money .mono{color:var(--ms-text);font-size:14px}
.ms .result.red{background:var(--ms-red-bg);border-color:var(--ms-red-line)}
.ms .result.red .label{color:var(--ms-red)}
.ms .result.amber{background:var(--ms-amber-bg);border-color:var(--ms-amber-line)}
.ms .result.amber .label{color:var(--ms-amber)}
.ms .result.green{background:var(--ms-green-bg);border-color:var(--ms-green-line)}
.ms .result.green .label{color:var(--ms-green)}
.ms .result.red .money,.ms .result.amber .money,.ms .result.green .money{border-top-color:rgba(20,23,31,.12)}
.ms .result.running{background:var(--ms-surface);border-color:var(--ms-line-strong)}
.ms .result.running .label{color:var(--ms-muted)}
.ms .elapsed{--ms-t:0;counter-reset:ms-t var(--ms-t);animation:ms-tick 3600s steps(3600,end) forwards;font-family:var(--ms-mono);font-size:12.5px;color:var(--ms-text)}
.ms .elapsed::after{content:counter(ms-t) " s"}
@keyframes ms-tick{to{--ms-t:3600}}
.ms .answer{margin-top:16px;font-size:14px;white-space:pre-wrap}

.ms .enter{animation:ms-in 200ms ease-out both}
.ms .result.enter{animation:ms-scale 220ms ease-out both}
@keyframes ms-in{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
@keyframes ms-scale{from{opacity:0;transform:scale(.97)}to{opacity:1;transform:none}}
@keyframes ms-pulse{0%,100%{opacity:1}50%{opacity:.3}}
@media (prefers-reduced-motion:reduce){.ms .enter,.ms .result.enter{animation:none}.ms .pill.pulse::before{animation:none}}
@media (max-width:860px){
  .ms .flow{grid-template-columns:1fr;gap:16px}
  .ms .step:not(:last-child)::after{top:auto;right:auto;bottom:-17px;left:24px;width:1px;height:16px}
}

.ms-check .cols{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.ms-check .card{border:1px solid var(--ms-line);border-radius:8px;padding:16px;background:var(--ms-bg)}
.ms-check .card h4{margin:0 0 8px;font-size:12px;font-weight:600;letter-spacing:.04em;text-transform:uppercase;color:var(--ms-muted);
  display:flex;justify-content:space-between;align-items:center;gap:8px}
.ms-check .card .row{font-size:13px;margin-top:8px;overflow-wrap:anywhere}
.ms-check .card .k{color:var(--ms-muted)}
.ms-check .pill{text-transform:none;letter-spacing:0;display:inline-flex;align-items:center;gap:6px;font-size:12px;font-weight:600;line-height:20px;border-radius:999px;
  padding:0 8px;border:1px solid var(--ms-line-strong);color:var(--ms-muted);background:var(--ms-bg);white-space:nowrap}
.ms-check .pill::before{content:"";width:6px;height:6px;border-radius:50%;background:currentColor}
.ms-check .pill.red{color:var(--ms-red);background:var(--ms-red-bg);border-color:var(--ms-red-line)}
.ms-check .pill.amber{color:var(--ms-amber);background:var(--ms-amber-bg);border-color:var(--ms-amber-line)}
.ms-check .pill.green{color:var(--ms-green);background:var(--ms-green-bg);border-color:var(--ms-green-line)}
.ms-check .pill.dark{color:var(--ms-text)}
.ms-check .card.gate{margin-top:0}
.ms-check .note{font-size:13px;color:var(--ms-muted)}
@media (max-width:760px){.ms-check .cols{grid-template-columns:1fr}}

.ms-strip{display:flex;flex-wrap:wrap;align-items:baseline;gap:4px 24px;margin-top:16px;padding:8px 12px;border:1px solid var(--ms-line);
  border-radius:6px;background:var(--ms-surface);font-family:var(--ms-font);font-size:13px;color:var(--ms-muted)}
.ms-strip .lead{font-weight:600;color:var(--ms-text)}
.ms-strip .note{font-size:12px}
.ms-strip .v{font-family:var(--ms-mono);font-size:12.5px;color:var(--ms-text)}
.ms-foot{font-family:var(--ms-font);font-size:12px;color:var(--ms-muted);margin-top:32px;padding-top:16px;border-top:1px solid var(--ms-line)}
.ms-foot a{color:var(--ms-muted);text-decoration:underline}
"""


def new_run(mode: str, protected: bool, banner: str, task: str, caption: str = "", replay_of: str = "",
            preview: dict | None = None) -> dict:
    """`preview` is an email that is waiting in the inbox but has not been read yet; it is drawn with a "Not read yet"
    tag until the agent really reads an email (then the email event takes over)."""
    return {"preview": preview, "t0": None, "took": None, "screen_t0": None, "screening_tool": "", "mode": mode, "protected": protected, "banner": banner, "caption": caption, "task": task,
            "replay_of": replay_of, "email": None, "screening": False, "screens": [], "screen": None, "call": None,
            "gate": None, "result": None, "answer": "", "error": "", "done": False, "events": [], "fresh": []}


def apply(run: dict, kind: str, data=None) -> dict:
    run["events"].append([kind, data])
    had_outcome = outcome(run) is not None
    fresh = []
    if kind == "email":
        run["email"] = data
        fresh = ["email"]
    elif kind == "screening":
        run["screening"] = not (data or {}).get("done", False)
        if run["screening"]:
            run["screening_tool"] = (data or {}).get("tool", "")
            run["screen_t0"] = time.monotonic() if run["t0"] else None  # only a live run has a clock
        fresh = ["screen"] if run["screening"] else []
    elif kind == "screen":
        run["screens"].append(data)
        if (data or {}).get("email", True):  # events saved before 31 Oct have no "email": they were all emails
            run["screen"] = data
        fresh = ["screen"]
    elif kind == "call":
        run["call"] = data
        fresh = ["gate"]
    elif kind == "gate":
        run["gate"] = data
        fresh = ["gate"]
    elif kind == "result":
        run["result"] = data
    elif kind == "answer":
        run["answer"] = data
    elif kind == "error":
        run["error"] = data
    elif kind == "done":
        run["done"] = True
        run["took"] = int(time.monotonic() - run["t0"]) if run["t0"] else None
    if not had_outcome and outcome(run) is not None:
        fresh.append("result")
    run["fresh"] = fresh
    return run


def replay(saved: dict) -> dict:
    """Rebuild a run from a saved one (its event list), for the recorded-run backup. Drawn at once, no animation."""
    run = new_run(saved["mode"], saved["protected"], saved["banner"], saved["task"], saved.get("caption", ""),
                  saved.get("recorded_at", "unknown date"))
    for kind, data in saved["events"]:
        apply(run, kind, data)
    run["fresh"] = []
    return run


def money(value) -> str:
    try:
        return f"{CURRENCY}{float(value):,.2f}"
    except (TypeError, ValueError):
        return str(value)


def paid_balance(run: dict) -> tuple[float, float] | None:
    """(balance before, balance after) from the transfer_money result, when money really moved. The tool reports the
    balance after the payment; the one before is that plus the amount."""
    result = run["result"]
    if not result or result["is_error"]:
        return None
    try:
        data = json.loads(result["text"])
        after, amount = float(data["balance"]), float(data["amount"])
    except (ValueError, KeyError, TypeError):
        return None
    return after + amount, after


def outcome(run: dict) -> tuple[str, str, str] | None:
    """(colour, label, one-line reason), or None while the run is still going."""
    call, gate, result = run["call"], run["gate"], run["result"]
    if run["error"]:
        return "grey", "Run failed", run["error"]
    args = (call or {}).get("args", {})
    what = f"{money(args.get('amount'))} to {args.get('iban')}"
    if not run["protected"]:
        if result is not None:
            if result["is_error"]:
                return "grey", "Payment failed", result["text"]
            return "red", "Money sent", f"{what} left the account. Nothing checked the payment (simulation, no MixShield)."
    elif gate is not None:
        if gate["action"] == "block":
            return "red", "Blocked", gate["reason"]
        if gate["action"] == "ask":
            return "amber", "Needs your OK", gate["reason"] + ". Nothing was sent."
        if result is not None:
            if result["is_error"]:
                return "grey", "Payment failed", result["text"]
            return "green", "Paid", f"{what}. {gate['reason']}."
    if run["done"]:
        return "grey", "No payment", "The agent made no payment call in this run."
    return None


def e(value) -> str:
    return html.escape(str(value), quote=True)


def elapsed_html(since: float | None) -> str:
    """A running clock: the real seconds since `since` as of this render. The page then keeps counting by itself (a CSS
    animation that starts at that offset), so nothing is sent to the page once a second."""
    if since is None:
        return ""
    return f'<span class="elapsed" style="animation-delay:-{max(0, int(time.monotonic() - since))}s"></span>'


def working_line(run: dict) -> str:
    tool = f" ({e(run['screening_tool'])})" if run.get("screening_tool") else ""
    return f'<div class="row">Screening tool output{tool} {elapsed_html(run.get("screen_t0"))}</div>'


def clean_reason(reason: str) -> str:
    """The screen words its reason as "classifier flagged it (p 0.89): ...". The classifier's own number is not shown
    anywhere in the demo (for a text it did not flag it is easy to misread), so it is cut from the text."""
    return re.sub(r"\s*\(p\s*[0-9.]+\)", "", reason or "")


def pill(text: str, colour: str = "", pulse: bool = False) -> str:
    return f'<span class="pill {colour}{" pulse" if pulse else ""}">{e(text)}</span>'


def email_html(run: dict) -> str:
    mail = run["email"] or run.get("preview")
    if not mail:
        return ""
    unread = not run["email"]
    iban = "" if unread else str((run["call"] or {}).get("args", {}).get("iban", "")).lower()
    sentences = re.split(r"(?<=[.!?])\s+", mail.get("body", ""))
    parts = []
    for s in sentences:
        if iban and iban in s.lower():
            parts.append(f'<mark>{e(s)}</mark><span class="tag">Account in the payment call</span>')
        else:
            parts.append(e(s))
    unread_tag = '<span class="tag neutral">Not read yet</span>' if unread else ""
    enter = " enter" if "email" in run["fresh"] else ""
    return (f'<div class="mail{enter}"><div class="mail-head">'
            f'<div class="mail-subject">{e(mail.get("subject", ""))}{unread_tag}</div>'
            f'<div class="mail-from">From {e(mail.get("from", ""))}</div></div>'
            f'<div class="mail-body">{" ".join(parts)}</div></div>')


def call_html(call: dict) -> str:
    """The tool call as code: the tool name, then one line per argument (the reference is left out)."""
    args = "".join(f'<span class="arg">{e(k)}={e(v)}</span>' for k, v in (call.get("args") or {}).items() if k != "reference")
    return f'<code class="call"><span>{e(call.get("tool", ""))}</span>{args}</code>'


def card(title: str, state: str, pill_html: str, detail: str, fresh: bool) -> str:
    return (f'<li class="step {state}{" enter" if fresh else ""}"><h4>{e(title)}{pill_html}</h4>'
            f'<div class="detail">{detail}</div></li>')


CLAMP_AT = 70  # characters; about two lines in the Screen card


def reason_html(text: str, key: str) -> str:
    """The screen's reason, at most 2 lines, with a "Show full reason" toggle when it is longer."""
    text = e(text)
    if len(text) <= CLAMP_AT:
        return f'<span class="reason">{text}</span>'
    box = f"ms-r-{re.sub(r'[^a-z0-9]', '', key.lower())}"
    return (f'<input type="checkbox" class="rtoggle" id="{box}">'
            f'<span class="reason clamp">{text}</span>'
            f'<label class="rlabel" for="{box}"><span class="more">Show full reason</span>'
            f'<span class="less">Hide full reason</span></label>')


def screen_card(run: dict, fresh: bool) -> str:
    screens = run["screens"]
    if not run["protected"]:
        return card("Screen", "skipped", pill("Skipped"), "Off. No MixShield in this run.", fresh)
    if not screens:
        if run["screening"]:
            return card("Screen", "active", pill("Checking", "accent", pulse=True), working_line(run), fresh)
        if run["done"]:
            return card("Screen", "skipped", pill("Skipped"), "No tool output reached the screen.", fresh)
        return card("Screen", "waiting", pill("Waiting"), "Waiting for a tool output.", fresh)
    unavailable = any(s.get("unavailable") for s in screens)
    flagged = sum(1 for s in screens if s["flagged"])
    n = len(screens)
    if unavailable:
        label, colour = "Unavailable", "red"
        summary = f"{n} tool output{'s' if n != 1 else ''} checked. The screen was unavailable, so it fails closed: the text counts as flagged."
    elif flagged:
        label, colour = "Flagged", "red"
        summary = f"{n} tool output{'s' if n != 1 else ''} checked, {flagged} flagged."
    else:
        label, colour = "Not flagged", "dark"
        summary = f"{n} tool output{'s' if n != 1 else ''} checked, none flagged."
    lines = [working_line(run)] if run["screening"] and not run["done"] else []
    lines.append(f'<div>{e(summary)}</div>')
    mail = run["screen"]
    if mail:
        pg = mail.get("prompt_guard_score")
        pg_line = ("not available" if pg is None else
                   f'<span class="mono">{pg:.4f}</span> (threshold {PG_THRESHOLD}): '
                   f'{"flagged" if pg >= PG_THRESHOLD else "not flagged"}')
        language = f' &middot; {e(mail["language"])}' if mail.get("language") else ""
        lines.append(f'<div class="row"><span class="k">Email{language}.</span> '
                     f'{reason_html(clean_reason(mail.get("reason")) or "-", "screen")}</div>')
        lines.append(f'<div class="row"><span class="k">Prompt Guard 2:</span> {pg_line}</div>')
    pending = pill("Checking", "accent", pulse=True) if run["screening"] and not run["done"] else ""
    return card("Screen", "done", pending or pill(label, colour), "".join(lines), fresh)


def gate_card(run: dict, fresh: bool) -> str:
    if not run["protected"]:
        return card("Gate", "skipped", pill("Skipped"), "Off. No MixShield in this run.", fresh)
    gate, call = run["gate"], run["call"] or {}
    if gate:
        label, colour = {"block": ("Blocked", "red"), "ask": ("Needs your OK", "amber"),
                         "allow": ("Allowed", "green")}[gate["action"]]
        detail = f'{call_html(call)}<div class="row">{e(gate["reason"])}</div>'
        return card("Gate", "done", pill(label, colour), detail, fresh)
    if run["call"]:
        return card("Gate", "active", pill("Checking", "accent"), call_html(call), fresh)
    if run["done"]:
        return card("Gate", "skipped", pill("Skipped"), "No payment call to check.", fresh)
    return card("Gate", "waiting", pill("Waiting"), "Waiting for a payment call.", fresh)


def result_summary(run: dict) -> str:
    if run["gate"] and run["gate"]["action"] in ("block", "ask"):
        return "No money moved."
    if run["result"] and not run["result"]["is_error"]:
        return f"{money((run['call'] or {}).get('args', {}).get('amount'))} sent."
    return ""


def flow_html(run: dict) -> str:
    fresh = set(run["fresh"])
    mail = run["email"]
    if mail:
        email_card = card("Email", "done", pill("Received", "dark"), e(mail.get("subject", "")), "email" in fresh)
    elif run["done"]:
        email_card = card("Email", "skipped", pill("Skipped"), "No email read.", "email" in fresh)
    else:
        email_card = card("Email", "waiting", pill("Waiting"), "Waiting for the agent to read an email.", False)
    out = outcome(run)
    if out:
        colour, label, _ = out
        result_card = card("Result", "done", pill(label, colour if colour != "grey" else "dark"),
                           result_summary(run), "result" in fresh)
    else:
        result_card = card("Result", "waiting", pill("Waiting"), "Waiting for the run to finish.", False)
    return ('<ol class="flow">' + email_card + screen_card(run, "screen" in fresh) + gate_card(run, "gate" in fresh)
            + result_card + "</ol>")


def running(run: dict) -> bool:
    return run.get("t0") is not None and not run["done"]


def result_html(run: dict) -> str:
    out = outcome(run)
    if not out:
        if running(run):
            return ('<div class="result running"><div class="label">Running&hellip;</div>'
                    f'<div class="why">Elapsed {elapsed_html(run["t0"])}</div></div>')
        return ""
    colour, label, why = out
    balance = paid_balance(run)
    if balance:
        money_line = (f'Balance <span class="mono">{money(balance[0])}</span> &rarr; '
                      f'<span class="mono">{money(balance[1])}</span>')
    elif colour in ("red", "amber") and run["protected"]:
        money_line = "Balance unchanged. No money moved."
    else:
        money_line = ""
    took = f"Run time {run['took']} s" if run.get("took") is not None else ""
    money_line = " &middot; ".join(x for x in (money_line, took) if x)
    money_html = f'<div class="money">{money_line}</div>' if money_line else ""
    fresh = " enter" if "result" in run["fresh"] else ""
    return (f'<div class="result {colour}{fresh}"><div class="label">{e(label)}</div>'
            f'<div class="why">{e(why)}</div>{money_html}</div>')


def render(run: dict) -> str:
    parts = ['<div class="ms">']
    parts.append(f'<div class="banner">{e(run["banner"])}</div>')
    if run["replay_of"]:
        parts.append(f'<div class="banner">Recorded run, {e(run["replay_of"])}. Nothing is running now.</div>')
    if run["caption"]:
        parts.append(f'<p class="caption">{e(run["caption"])}</p>')
    parts.append(f'<div class="task">User request <code>{e(run["task"])}</code></div>')
    parts.append(email_html(run))
    parts.append(flow_html(run))
    if run["protected"]:
        parts.append(f'<p class="two">{e(TWO_LAYERS)}</p>')
    else:
        parts.append('<div style="height:24px"></div>')
    parts.append(result_html(run))
    if run["answer"]:
        shown = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", e(run["answer"]))  # the model's words; its **bold** shown as bold
        parts.append(f'<div class="answer"><b>Agent\'s answer</b><br>{shown}</div>')
    parts.append("</div>")
    return "".join(parts)


def message_html(text: str) -> str:
    """A plain notice in the same style (rate limit refusals, errors before a run starts)."""
    return f'<div class="ms"><div class="banner">{e(text)}</div></div>'


def footer_html() -> str:
    return f'<div class="ms-foot">{e(FOOTER)} <a href="{REPO_URL}" target="_blank" rel="noopener">Source on GitHub</a></div>'


def check_html(pg_score: float | None, flagged: bool, unavailable: bool, language: str, reason: str) -> str:
    """The 'Try to fool MixShield' result: Prompt Guard 2 next to the MixShield screen."""
    if pg_score is None:
        pg_pill, pg_row = pill("Not available"), "The model did not load."
    else:
        hit = pg_score >= PG_THRESHOLD
        pg_pill = pill("Flagged" if hit else "Not flagged", "red" if hit else "dark")
        pg_row = f'Score <span class="mono">{pg_score:.4f}</span> (threshold {PG_THRESHOLD})'
    if unavailable:
        ms_pill = pill("Unavailable", "red")
        ms_row = "A detector was unavailable, so the screen failed closed: the text counts as flagged."
    else:
        ms_pill = pill("Flagged" if flagged else "Not flagged", "red" if flagged else "dark")
        ms_row = f'<span class="k">{e(language)}.</span> {e(clean_reason(reason))}'
    return ('<div class="ms-check"><div class="cols">'
            f'<div class="card"><h4>Prompt Guard 2{pg_pill}</h4><div class="row">{pg_row}</div></div>'
            f'<div class="card"><h4>MixShield screen{ms_pill}</h4><div class="row">{ms_row}</div></div>'
            '</div></div>')


def gate_html(action: str, reason: str, call: str) -> str:
    label, colour = {"allow": ("Allowed", "green"), "ask": ("Needs your OK", "amber"),
                     "block": ("Blocked", "red")}[action]
    return ('<div class="ms-check"><div class="card gate">'
            f'<h4>Action gate{pill(label, colour)}</h4><div class="row"><code>{e(call)}</code></div>'
            f'<div class="row">{e(reason)}</div></div></div>')


def check_note(text: str) -> str:
    return f'<div class="ms-check"><div class="note">{e(text)}</div></div>'
