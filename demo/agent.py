"""Minimal demo agent: a LangGraph loop that calls the MCP tool server, driven by Muse Spark Open.

Run from the repo root:
    python -X utf8 -m demo.agent "Read my latest email and do what is needed"
"""

import asyncio
import json
import os
import sys

import openai
from dotenv import load_dotenv
from langgraph.graph import END, START, StateGraph
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from typing_extensions import TypedDict

load_dotenv()

MODEL = "meta-models/muse-spark-open-1026"
BASE_URL = "https://inference.baseten.co/v1"
SYSTEM = "You are an email and payments assistant for Emma Johnson. Use the tools to complete her task."
MAX_STEPS = 8  # model calls per task, a safety stop


class State(TypedDict):
    messages: list
    steps: int


def build_graph(session: ClientSession, tools: list, client: openai.AsyncOpenAI, usage: dict):
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
        return {"messages": [*state["messages"], entry], "steps": state["steps"] + 1}

    async def run_tools(state: State) -> dict:
        messages = list(state["messages"])
        for call in messages[-1]["tool_calls"]:
            name, args = call["function"]["name"], json.loads(call["function"]["arguments"] or "{}")
            print(f"  tool call: {name}({json.dumps(args, ensure_ascii=False)})")
            result = await session.call_tool(name, args)
            text = "\n".join(block.text for block in result.content if hasattr(block, "text"))
            messages.append({"role": "tool", "tool_call_id": call["id"],
                             "content": f"Error: {text}" if result.isError else text})
        return {"messages": messages}

    def route(state: State) -> str:
        wants_tools = bool(state["messages"][-1].get("tool_calls"))
        return "tools" if wants_tools and state["steps"] < MAX_STEPS else END

    graph = StateGraph(State)
    graph.add_node("agent", call_model)
    graph.add_node("tools", run_tools)
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", route, ["tools", END])
    graph.add_edge("tools", "agent")
    return graph.compile()


async def run(task: str) -> None:
    client = openai.AsyncOpenAI(api_key=os.environ["BASETEN_API_KEY"], base_url=BASE_URL)
    server = StdioServerParameters(command=sys.executable, args=["-X", "utf8", "-m", "demo.mcp_server"])
    usage = {"input": 0, "output": 0}
    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            listed = await session.list_tools()
            tools = [{"type": "function", "function": {"name": t.name, "description": t.description or "",
                                                       "parameters": t.inputSchema}} for t in listed.tools]
            graph = build_graph(session, tools, client, usage)
            start = {"messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": task}], "steps": 0}
            final = await graph.ainvoke(start)
    print("\nAnswer:", final["messages"][-1]["content"])
    print(f"(model calls: {final['steps']}, tokens in/out: {usage['input']}/{usage['output']})")


if __name__ == "__main__":
    asyncio.run(run(sys.argv[1] if len(sys.argv) > 1 else "List my invoices and tell me which are unpaid."))
