"""Investigate goal 5: one lean attacked run with per-call tokens and tool output sizes.

    python -X utf8 -m bench.goal5_probe --max-usd 1
"""

import argparse
import json
from pathlib import Path

from agentdojo.attacks.attack_registry import load_attack
from agentdojo.task_suite.load_suites import get_suite

from bench.adapters import make_pipeline
from bench.budget import Budget, BudgetExceeded
from bench.lean import VERSION, run_pair


def text_of(message) -> str:
    c = message.get("content")
    return " ".join(b.get("content") or "" for b in c) if isinstance(c, list) else (c or "")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-usd", type=float, required=True)
    args = parser.parse_args()

    suite = get_suite(VERSION, "workspace")
    pipeline = make_pipeline("muse-spark-open")
    llm = next(e for e in pipeline.elements if hasattr(e, "calls"))
    llm.budget = Budget(args.max_usd)
    attack = load_attack("important_instructions", suite, pipeline)
    logdir = Path("results/raw_logs/goal5_probe")

    try:
        row = run_pair(suite, pipeline, llm, attack, "user_task_3", "injection_task_1", logdir)
    except BudgetExceeded as e:
        print("STOPPED by budget:", e)
        row = None
    print("per-call tokens (input, output):", llm.calls)
    print("result:", row)
    print(f"assumed spend ${llm.budget.spent_usd:.3f} (prices from bench/budget.py)")

    path = logdir / pipeline.name.replace("/", "_") / "workspace/user_task_3/important_instructions/injection_task_1.json"
    if path.exists():
        for i, m in enumerate(json.loads(path.read_text(encoding="utf-8"))["messages"]):
            calls = [(tc["function"], tc["args"]) for tc in (m.get("tool_calls") or [])]
            print(i, m["role"], f"{len(text_of(m))} chars", calls, (m.get("error") or "")[:80].replace("\n", " "))


if __name__ == "__main__":
    main()
