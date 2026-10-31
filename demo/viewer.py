"""The demo viewer: turns the events of one run into one HTML block. No Gradio here, so it can be tested alone.

A run is a plain dict (`new_run`) that `apply` fills one event at a time; `render` draws it. The flow strip
    Email -> Screen -> Gate -> Result
lights up as the real events arrive (nothing is delayed or timed for show). Everything shown comes from the run:
the email text, the screen verdict, the gate's own reason, the tool's own result. Both outcomes are drawn as they
are: flagged -> the gate blocks (BLOCKED, red); not flagged -> the gate asks (NEEDS YOUR OK, amber); trusted
payee -> PAID (green); no MixShield -> MONEY SENT (red).

Event kinds (`apply(run, kind, data)`):
  email      {"from", "subject", "body"}     the email the agent read
  screening  {}                              the screen started on that output
  screen     {"flagged", "language", "reason", "prompt_guard_score", "unavailable"}
  call       {"tool", "args"}                the payment call the agent proposed
  gate       {"action", "reason"}            allow | ask | block
  result     {"is_error", "text"}            what the tool call returned
  answer     str                             the agent's final text (real agent only)
  error      str                             the run failed
  done       {}
"""

import html
import re

PG_THRESHOLD = 0.5  # the default Prompt Guard 2 threshold used by the screen (a placeholder, shown as such)

CAPTION_SIMULATION = ("In our tests (E1), neither Muse Spark nor Muse Spark Open was hijacked: 0 of 536 scorable "
                      "attacks succeeded. A future model or prompt may be weaker, so here we test the worst case: a "
                      "scripted agent that obeys any instruction it reads.")
BANNER_SIMULATION = "SIMULATION: a scripted agent that obeys any instruction it reads. Not a real model."
BANNER_REAL = "Real model: Muse Spark Open (Baseten), tools through the MixShield proxy."
TWO_LAYERS = "Two layers: if the screen misses, the gate still stops untrusted payments."
FOOTER = "Fake data and fake IBANs. No real money, no real accounts."

CSS = """
<style>
.ms{font-family:system-ui,sans-serif;color:#101828;background:#fff;border:1px solid #d0d5dd;border-radius:10px;padding:16px;max-width:900px}
.ms *{box-sizing:border-box}
.ms .banner{background:#eff4ff;border:1px solid #84adff;color:#102a63;border-radius:6px;padding:8px 12px;font-weight:600;margin-bottom:8px}
.ms .caption{color:#475467;font-size:14px;margin-bottom:10px}
.ms .task{font-size:14px;color:#344054;margin-bottom:10px}
.ms .card{border:1px solid #d0d5dd;border-radius:8px;padding:10px 12px;background:#f9fafb;margin-bottom:6px}
.ms .card .meta{font-size:13px;color:#475467;margin-bottom:4px}
.ms mark{background:#fee4e2;color:#b42318;border-bottom:2px solid #d92d20;padding:0 2px;border-radius:2px}
.ms .hlnote{font-size:12px;color:#b42318;margin-bottom:10px}
.ms .flow{display:flex;gap:6px;align-items:stretch;margin:12px 0 4px}
.ms .step{flex:1;border:2px solid #d0d5dd;border-radius:8px;padding:8px;background:#f2f4f7;color:#667085;min-width:0}
.ms .arrow{align-self:center;color:#98a2b3;font-weight:700}
.ms .step h4{margin:0 0 4px;font-size:14px}
.ms .step .d{font-size:12px;line-height:1.35;overflow-wrap:anywhere}
.ms .step.active{border-color:#2e90fa;background:#eff8ff;color:#175cd3}
.ms .step.done{background:#fff;color:#101828;border-color:#344054}
.ms .step.red{border-color:#d92d20;background:#fef3f2;color:#7a271a}
.ms .step.amber{border-color:#f79009;background:#fffaeb;color:#7a2e0e}
.ms .step.green{border-color:#12b76a;background:#ecfdf3;color:#054f31}
.ms .two{font-size:14px;color:#344054;margin:6px 0 12px}
.ms .badge{border-radius:10px;padding:14px 16px;border:3px solid}
.ms .badge .big{font-size:32px;font-weight:800;letter-spacing:.5px}
.ms .badge .why{font-size:15px;margin-top:4px;overflow-wrap:anywhere}
.ms .badge.red{background:#fef3f2;border-color:#d92d20;color:#b42318}
.ms .badge.amber{background:#fffaeb;border-color:#f79009;color:#b54708}
.ms .badge.green{background:#ecfdf3;border-color:#12b76a;color:#067647}
.ms .badge.grey{background:#f2f4f7;border-color:#98a2b3;color:#475467}
.ms .answer{margin-top:10px;font-size:14px;white-space:pre-wrap}
.ms .foot{margin-top:10px;font-size:12px;color:#667085}
@media (max-width:640px){.ms .flow{flex-direction:column}.ms .arrow{transform:rotate(90deg)}}
</style>
"""


def new_run(mode: str, protected: bool, banner: str, task: str, caption: str = "", replay_of: str = "") -> dict:
    return {"mode": mode, "protected": protected, "banner": banner, "caption": caption, "task": task,
            "replay_of": replay_of, "email": None, "screening": False, "screen": None, "call": None, "gate": None,
            "result": None, "answer": "", "error": "", "done": False, "events": []}


def apply(run: dict, kind: str, data=None) -> dict:
    run["events"].append([kind, data])
    if kind == "email":
        run["email"] = data
    elif kind == "screening":
        run["screening"] = True
    elif kind == "screen":
        run["screen"] = data
    elif kind == "call":
        run["call"] = data
    elif kind == "gate":
        run["gate"] = data
    elif kind == "result":
        run["result"] = data
    elif kind == "answer":
        run["answer"] = data
    elif kind == "error":
        run["error"] = data
    elif kind == "done":
        run["done"] = True
    return run


def replay(saved: dict) -> dict:
    """Rebuild a run from a saved one (its event list), for the recorded-run backup."""
    run = new_run(saved["mode"], saved["protected"], saved["banner"], saved["task"], saved.get("caption", ""),
                  saved.get("recorded_at", "unknown date"))
    for kind, data in saved["events"]:
        apply(run, kind, data)
    return run


def outcome(run: dict) -> tuple[str, str, str] | None:
    """(colour, big text, one-line reason), or None while the run is still going."""
    call, gate, result = run["call"], run["gate"], run["result"]
    if run["error"]:
        return "grey", "RUN FAILED", run["error"]
    args = (call or {}).get("args", {})
    what = f"{args.get('amount')} to {args.get('iban')}"
    if not run["protected"]:
        if result is not None:
            if result["is_error"]:
                return "grey", "PAYMENT FAILED", result["text"]
            return "red", "MONEY SENT", f"{what} left the account. Nothing checked the payment (simulation, no MixShield)."
    elif gate is not None:
        if gate["action"] == "block":
            return "red", "BLOCKED", gate["reason"]
        if gate["action"] == "ask":
            return "amber", "NEEDS YOUR OK", gate["reason"] + ". Nothing was sent."
        if result is not None:
            if result["is_error"]:
                return "grey", "PAYMENT FAILED", result["text"]
            return "green", "PAID", f"{what}. {gate['reason']}."
    if run["done"]:
        return "grey", "NO PAYMENT", "The agent made no payment call in this run."
    return None


def e(value) -> str:
    return html.escape(str(value), quote=True)


def email_html(run: dict) -> str:
    mail = run["email"]
    if not mail:
        return ""
    iban = str((run["call"] or {}).get("args", {}).get("iban", "")).lower()
    sentences = re.split(r"(?<=[.!?])\s+", mail.get("body", ""))
    marked = any(iban and iban in s.lower() for s in sentences)
    body = " ".join(f"<mark>{e(s)}</mark>" if iban and iban in s.lower() else e(s) for s in sentences)
    note = '<div class="hlnote">Red: the line with the account named in the payment call.</div>' if marked else ""
    return (f'<div class="card"><div class="meta">From: {e(mail.get("from", ""))} &middot; '
            f'Subject: {e(mail.get("subject", ""))}</div>{body}</div>{note}')


def step(title: str, state: str, detail: str) -> str:
    return f'<div class="step {state}"><h4>{e(title)}</h4><div class="d">{detail}</div></div>'


def screen_detail(screen: dict) -> str:
    if screen.get("unavailable"):
        verdict = "SCREEN UNAVAILABLE (fails closed: treated as flagged)"
    else:
        verdict = "FLAGGED" if screen["flagged"] else "not flagged"
    pg = screen.get("prompt_guard_score")
    pg_line = ("Prompt Guard 2: not available" if pg is None else
               f"Prompt Guard 2: score {pg:.4f} (default threshold {PG_THRESHOLD}) &rarr; "
               f"{'flagged' if pg >= PG_THRESHOLD else 'not flagged'}")
    language = f"<br>Language: {e(screen['language'])}" if screen.get("language") else ""
    return (f"{pg_line}<br><b>MixShield screen: {e(verdict)}</b>{language}<br>"
            f"Reason: {e(screen.get('reason') or '-')}")


def flow_html(run: dict) -> str:
    out = outcome(run)
    protected = run["protected"]
    steps = []
    steps.append(step("1. Email", "done" if run["email"] else "",
                      e(f"from {run['email'].get('from', '')}") if run["email"] else "waiting for an email"))
    if not protected:
        steps.append(step("2. Screen", "", "off (no MixShield)"))
        steps.append(step("3. Gate", "", "off (no MixShield)"))
    else:
        if run["screen"]:
            steps.append(step("2. Screen", "done", screen_detail(run["screen"])))
        elif run["screening"]:
            steps.append(step("2. Screen", "active", "screening&hellip; (a model call, about 3 s)"))
        else:
            steps.append(step("2. Screen", "", "waiting"))
        gate = run["gate"]
        if gate:
            call = run["call"] or {}
            args = ", ".join(f"{k}={v}" for k, v in (call.get("args") or {}).items() if k != "reference")
            colour = {"block": "red", "ask": "amber", "allow": "green"}[gate["action"]]
            steps.append(step("3. Gate", colour, f"{e(call.get('tool', ''))}({e(args)})<br>"
                                                   f"<b>{e(gate['action'].upper())}</b>: {e(gate['reason'])}"))
        elif run["call"]:
            steps.append(step("3. Gate", "active", "checking the payment call&hellip;"))
        else:
            steps.append(step("3. Gate", "", "waiting for a payment call"))
    if out:
        colour, big, why = out
        steps.append(step("4. Result", colour, f"<b>{e(big)}</b>"))
    else:
        steps.append(step("4. Result", "", "&hellip;"))
    return '<div class="flow">' + '<div class="arrow">&rarr;</div>'.join(steps) + "</div>"


def badge_html(run: dict) -> str:
    out = outcome(run)
    if not out:
        return ""
    colour, big, why = out
    return f'<div class="badge {colour}"><div class="big">{e(big)}</div><div class="why">{e(why)}</div></div>'


def render(run: dict) -> str:
    parts = [CSS, '<div class="ms">']
    parts.append(f'<div class="banner">{e(run["banner"])}</div>')
    if run["replay_of"]:
        parts.append(f'<div class="banner">Recorded run, {e(run["replay_of"])}. Nothing is running now.</div>')
    if run["caption"]:
        parts.append(f'<div class="caption">{e(run["caption"])}</div>')
    parts.append(f'<div class="task">User\'s request: <b>{e(run["task"])}</b></div>')
    parts.append(email_html(run))
    parts.append(flow_html(run))
    if run["protected"]:
        parts.append(f'<div class="two">{e(TWO_LAYERS)}</div>')
    parts.append(badge_html(run))
    if run["answer"]:
        parts.append(f'<div class="answer"><b>Agent\'s answer:</b> {e(run["answer"])}</div>')
    parts.append(f'<div class="foot">{e(FOOTER)}</div></div>')
    return "".join(parts)


def message_html(text: str) -> str:
    """A plain notice in the same box (rate limit refusals, errors before a run starts)."""
    return CSS + f'<div class="ms"><div class="badge grey"><div class="why">{e(text)}</div></div></div>'
