"""The three demo runs, as async functions that report what happens through `emit(kind, data)` (see viewer.py).

  simulate(protect=False)   scripted obedient agent straight to the tool server (no MixShield)
  simulate(protect=True)    the same agent through the MixShield proxy logic
  real_agent()              Muse Spark Open (a real model, via the LangGraph loop of demo/agent.py) through the proxy

The proxy here is the Proxy class of mixshield/proxy.py, the code that `mixshield proxy` runs, started inside this
process so that the Prompt Guard 2 model is loaded once and shared by all visitors. The `mixshield proxy` command
itself is shown in the Inspector clip (docs/demo_inspector.md).

`stream_run` runs a scenario in a thread and yields the run dict after every event, for a Gradio generator.
"""

import asyncio
import json
import os
import queue
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from demo import viewer
from demo.obedient_client import TASK, obey
from mixshield.proxy import Proxy, load_config

REPO = Path(__file__).resolve().parent.parent
CONFIG = Path(__file__).parent / "policy.json"
REAL_TASK = "Pay invoice INV-101"
TIMEOUT = 150  # seconds for one whole run
RUNS_DIR = REPO / "results" / "demo" / "runs"


def server_params() -> StdioServerParameters:
    return StdioServerParameters(command=sys.executable, args=["-X", "utf8", "-m", "demo.mcp_server"], cwd=str(REPO))


def email_of(result) -> dict | None:
    """The email dict if this tool result is one email (read_email with an id), else None."""
    for block in result.content:
        if hasattr(block, "text") and block.text.startswith("{"):
            try:
                data = json.loads(block.text)
            except ValueError:
                return None
            return data if isinstance(data, dict) and "body" in data else None
    return None


class DirectCaller:
    """No MixShield: passes calls straight to the tool server and reports them."""

    def __init__(self, session, emit) -> None:
        self.session, self.emit = session, emit

    async def list_tools(self):
        return (await self.session.list_tools()).tools

    async def call_tool(self, name, arguments):
        if name == "transfer_money":
            self.emit("call", {"tool": name, "args": arguments})
        result = await self.session.call_tool(name, arguments)
        mail = email_of(result)
        if mail:
            self.emit("email", mail)
        if name == "transfer_money":
            self.emit("result", {"is_error": bool(result.isError), "text": " ".join(
                b.text for b in result.content if hasattr(b, "text"))})
        return result


class LiveProxy(Proxy):
    """The MixShield Proxy, plus a report of each step as it happens: the email arrives, the screen runs on every tool
    output and gives its verdicts, the payment call is proposed, the gate decides, the tool answers."""

    def __init__(self, *args, emit, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.emit = emit

    async def _screen_result(self, name, result):
        mail = email_of(result) if name == "read_email" else None
        if mail:
            self.emit("email", mail)
        self.emit("screening", {"tool": name})
        start = len(self.events)
        out = await super()._screen_result(name, result)
        for seen in (ev for ev in self.events[start:] if ev["action"] == "screened"):  # every text, not only emails
            self.emit("screen", {"flagged": seen["flagged"], "language": seen["language"], "reason": seen["reason"],
                                 "prompt_guard_score": seen["prompt_guard_score"], "tool": name,
                                 "email": bool(mail), "unavailable": seen["reason"].startswith("screen unavailable")})
        self.emit("screening", {"tool": name, "done": True})
        return out

    async def call_tool(self, name, arguments):
        if name != "transfer_money":
            return await super().call_tool(name, arguments)
        self.emit("call", {"tool": name, "args": arguments})
        start = len(self.events)
        result = await super().call_tool(name, arguments)
        gate = next((ev for ev in self.events[start:] if ev["action"] in ("allow", "ask", "block")), None)
        if gate:
            self.emit("gate", {"action": gate["action"], "reason": gate["reason"]})
            self.emit("result", {"is_error": bool(result.isError), "text": " ".join(
                b.text for b in result.content if hasattr(b, "text"))})
        return result


def make_proxy(session, emit, screen, task: str) -> LiveProxy:
    settings = load_config(CONFIG)
    return LiveProxy(session, trusted=settings.trusted, policy=settings.policy, low_risk=settings.low_risk,
                     screen=screen, user_task=task, approver=None, emit=emit)


async def simulate(emit, protect: bool, screen=None, task: str = TASK) -> None:
    async with stdio_client(server_params(), errlog=sys.stderr) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            caller = make_proxy(session, emit, screen, task) if protect else DirectCaller(session, emit)
            await caller.list_tools()
            await obey(caller, [], quiet=True)
    emit("done", {})


async def real_agent(emit, screen=None, task: str = REAL_TASK) -> None:
    import openai
    from langgraph.checkpoint.memory import InMemorySaver

    from demo.agent import BASE_URL, SYSTEM, build_graph, drive  # imports langgraph, loads .env

    client = openai.AsyncOpenAI(api_key=os.environ["BASETEN_API_KEY"], base_url=BASE_URL)
    usage = {"input": 0, "output": 0}
    async with stdio_client(server_params(), errlog=sys.stderr) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            proxy = make_proxy(session, emit, screen, task)
            listed = await proxy.list_tools()
            tools = [{"type": "function", "function": {"name": t.name, "description": t.description or "",
                                                       "parameters": t.inputSchema}} for t in listed]
            graph = build_graph(proxy, tools, client, usage, InMemorySaver())
            start = {"messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": task}],
                     "steps": 0, "pending": []}
            final = await drive(graph, start, {"configurable": {"thread_id": "viewer"}})
    emit("answer", final["messages"][-1]["content"])
    emit("done", {})


def stream_run(factory, run: dict):
    """Run `factory(emit)` (an async function) in a thread. Yields `run` after every event, ending with 'done'.
    A failure or a timeout becomes an 'error' event, shown as it is. Each event in run["events"] gets a third item: the
    seconds since the run started, taken when the event happened. A recorded run is replayed with these times."""
    events: queue.Queue = queue.Queue()
    start = time.monotonic()

    def emit(kind, data=None):
        events.put((kind, data, round(time.monotonic() - start, 3)))

    def work():
        try:
            asyncio.run(asyncio.wait_for(factory(emit), TIMEOUT))
        except BaseException as exc:  # shown to the visitor, never hidden
            emit("error", f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__)
            emit("done", {})

    threading.Thread(target=work, daemon=True).start()
    while True:
        kind, data, at = events.get()
        viewer.apply(run, kind, data)
        run["events"][-1].append(at)
        yield run
        if kind == "done":
            return


def play(saved: dict, times: list[float], factor: float, preview=None, sleep=time.sleep):
    """Replay a saved run: yields the run after the start and after each saved event, first waiting the recorded gap
    (the difference of the saved times, divided by `factor`). `times` comes from viewer.event_times."""
    run = viewer.new_run(saved["mode"], saved["protected"], saved["banner"], saved["task"], saved.get("caption", ""),
                         saved.get("recorded_at", "unknown date"), preview=preview)
    run["replay_speed"] = "2x speed" if factor == 2.0 else "real speed"
    yield run
    previous = 0.0
    for event, at in zip(saved["events"], times):
        sleep((at - previous) / factor)
        previous = at
        viewer.apply(run, event[0], event[1])
        yield run


def save_run(run: dict) -> Path | None:
    """Write the run's events to results/demo/runs/ (only when DEMO_SAVE_RUNS=1), for the recorded-run backup."""
    if os.environ.get("DEMO_SAVE_RUNS") != "1":
        return None
    now = datetime.now(timezone.utc)
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    path = RUNS_DIR / f"{run['mode']}_{now.strftime('%Y%m%d_%H%M%S')}.json"
    saved = {k: run[k] for k in ("mode", "protected", "banner", "caption", "task", "events")}
    saved["recorded_at"] = now.strftime("%Y-%m-%d %H:%M UTC")
    path.write_text(json.dumps(saved, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
