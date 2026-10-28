"""Minimal demo agent: a LangGraph loop that calls the MCP tool server, driven by Muse Spark Open.

Run from the repo root:
    python -X utf8 -m demo.agent "Read my latest email and do what is needed"
    python -X utf8 -m demo.agent --protect "Read my latest email and do what is needed"
    python -X utf8 -m demo.agent --protect --screen stub --stub-flag "bank account badal gaya" "Read my latest email"

--protect puts the MixShield proxy logic (gate + screen) between the agent and the tool server. A call the gate
answers "ask" pauses the graph with a LangGraph interrupt: the call, the decision, the reason and the new values are
shown, and the run waits for yes or no. The screen is the real one (mixshield/screen.py, fails closed); --screen stub
uses the stub instead (--stub-flag marks a tool output as flagged), with no model and no API call for the screen.

One tool call per graph step: LangGraph runs a node again from its start after an interrupt, so a step with several
calls would repeat the calls that came before the one waiting for approval.
"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

import openai
from dotenv import load_dotenv
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from typing_extensions import TypedDict

from mixshield.approval import ApprovalRequest, approval_payload, parse_answer
from mixshield.proxy import Proxy, StubScreen, load_config
from mixshield.screen import Screen

load_dotenv()

MODEL = "meta-models/muse-spark-open-1026"
BASE_URL = "https://inference.baseten.co/v1"
SYSTEM = "You are an email and payments assistant for Emma Johnson. Use the tools to complete her task."
MAX_STEPS = 8  # model calls per task, a safety stop
CONFIG = Path(__file__).parent / "policy.json"


class State(TypedDict):
    messages: list
    steps: int
    pending: list  # tool calls of the last assistant message that are not answered yet


def human_approver(request: ApprovalRequest) -> bool:
    """Human approver: pause the graph and wait for the person's yes or no (the interrupt value is the question)."""
    return parse_answer(interrupt(approval_payload(request)))


def build_graph(caller, tools: list, client: openai.AsyncOpenAI, usage: dict, checkpointer=None):
    """`caller` is anything with `async call_tool(name, args)`: the MCP session, or the MixShield Proxy."""

    async def call_model(state: State) -> dict:
        response = await client.chat.completions.create(model=MODEL, messages=state["messages"], tools=tools)
        usage["input"] += response.usage.prompt_tokens
        usage["output"] += response.usage.completion_tokens
        message = response.choices[0].message
        entry = {"role": "assistant", "content": message.content or ""}
        if message.tool_calls:
            entry["tool_calls"] = [
                {"id": c.id, "type": "function", "function": {"name": c.function.name, "arguments": c.function.arguments}}
                for c in message.tool_calls
            ]
        return {"messages": [*state["messages"], entry], "steps": state["steps"] + 1,
                "pending": list(entry.get("tool_calls", []))}

    async def run_tool(state: State) -> dict:
        call, rest = state["pending"][0], state["pending"][1:]
        name, args = call["function"]["name"], json.loads(call["function"]["arguments"] or "{}")
        print(f"  tool call: {name}({json.dumps(args, ensure_ascii=False)})")
        result = await caller.call_tool(name, args)  # may pause here for approval (interrupt)
        text = "\n".join(block.text for block in result.content if hasattr(block, "text"))
        message = {"role": "tool", "tool_call_id": call["id"], "content": f"Error: {text}" if result.isError else text}
        return {"messages": [*state["messages"], message], "pending": rest}

    def after_agent(state: State) -> str:
        return "tools" if state["pending"] and state["steps"] < MAX_STEPS else END

    def after_tool(state: State) -> str:
        return "tools" if state["pending"] else "agent"

    graph = StateGraph(State)
    graph.add_node("agent", call_model)
    graph.add_node("tools", run_tool)
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", after_agent, ["tools", END])
    graph.add_conditional_edges("tools", after_tool, ["tools", "agent"])
    return graph.compile(checkpointer=checkpointer)


async def ask_in_terminal(payload: dict) -> str:
    print("\n" + payload["question"])
    return await asyncio.to_thread(input, "Approve this call? [yes/no]: ")


async def drive(graph, start: dict, config: dict, ask=ask_in_terminal) -> dict:
    """Run the graph; every time it stops at an interrupt, ask the person and resume with the answer."""
    result = await graph.ainvoke(start, config)
    while result.get("__interrupt__"):
        answer = await ask(result["__interrupt__"][0].value)
        result = await graph.ainvoke(Command(resume=answer), config)
    return result


async def run(task: str, protect: bool = False, stub_flags: list[str] | None = None, screen: str = "mixshield") -> None:
    client = openai.AsyncOpenAI(api_key=os.environ["BASETEN_API_KEY"], base_url=BASE_URL)
    server = StdioServerParameters(command=sys.executable, args=["-X", "utf8", "-m", "demo.mcp_server"])
    usage = {"input": 0, "output": 0}
    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            caller = session
            if protect:
                settings = load_config(CONFIG)
                caller = Proxy(session, trusted=settings.trusted, policy=settings.policy, low_risk=settings.low_risk,
                               screen=StubScreen(stub_flags or []) if screen == "stub" else Screen(),
                               user_task=task, approver=human_approver)
                listed = await caller.list_tools()
            else:
                listed = (await session.list_tools()).tools
            tools = [{"type": "function", "function": {"name": t.name, "description": t.description or "",
                                                       "parameters": t.inputSchema}} for t in listed]
            graph = build_graph(caller, tools, client, usage, InMemorySaver())
            start = {"messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": task}],
                     "steps": 0, "pending": []}
            final = await drive(graph, start, {"configurable": {"thread_id": "demo"}})
    print("\nAnswer:", final["messages"][-1]["content"])
    print(f"(model calls: {final['steps']}, tokens in/out: {usage['input']}/{usage['output']})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("task", nargs="?", default="List my invoices and tell me which are unpaid.")
    parser.add_argument("--protect", action="store_true", help="put the MixShield gate and screen in front of the tools")
    parser.add_argument("--screen", choices=["mixshield", "stub"], default="mixshield",
                        help="with --protect: the real screen, or the stub (for tests)")
    parser.add_argument("--stub-flag", action="append", default=[], help="--screen stub: flag outputs containing this text")
    args = parser.parse_args()
    if args.stub_flag and args.screen != "stub":
        parser.error("--stub-flag needs --screen stub")
    asyncio.run(run(args.task, args.protect, args.stub_flag, args.screen))
