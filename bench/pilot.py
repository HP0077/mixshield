"""Pilot (original goals, with the retired goal 5): the 10 fixed pairs, own attack texts (Hinglish and English), Muse Spark Open, no defence.

Each text is injected as-is into every injection point the agent will see (no template).

    python -X utf8 -m bench.pilot --max-usd 2
"""

import argparse
import csv
import json
from pathlib import Path

from agentdojo.task_suite.load_suites import get_suite

from bench.adapters import make_pipeline
from bench.budget import Budget, BudgetExceeded
from bench.goals import FIXED_USER_TASK_V1 as FIXED_USER_TASK, GOALS_V1 as GOALS
from bench.lean import VERSION, TextAttack, run_pair

FIELDS = ["language", "goal", "suite", "user_task", "injection_task", "utility", "security",
          "input_tokens", "output_tokens", "model_calls", "seconds", "error", "tool_calls", "final_reply"]


def load_texts(path: str) -> dict[int, str]:
    texts = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            goal, text = line.split(":", 1)
            texts[int(goal)] = text.strip()
    return texts


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-usd", type=float, required=True)
    parser.add_argument("--out", default="results/pilot_hinglish.csv")
    args = parser.parse_args()

    pipeline = make_pipeline("muse-spark-open")
    llm = next(e for e in pipeline.elements if hasattr(e, "calls"))
    llm.budget = Budget(args.max_usd)
    logdir = Path("results/raw_logs/pilot")
    languages = {"hinglish": load_texts("bench/attacks/pilot_hinglish.txt"),
                 "english": load_texts("bench/attacks/pilot_english.txt")}
    suites = {n: get_suite(VERSION, n) for n in ("banking", "workspace", "slack")}

    # Goal 5 goes last: its agent may loop on a tool error and cost a lot.
    order = [g for g in GOALS if g[0] != 5] + [g for g in GOALS if g[0] == 5]
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        try:
            for goal, suite_name, inj in order:
                for language, texts in languages.items():
                    suite = suites[suite_name]
                    attack = TextAttack(f"pilot_{language}", {inj: texts[goal]}, suite, pipeline)
                    ut = FIXED_USER_TASK[goal]
                    row = run_pair(suite, pipeline, llm, attack, ut, inj, logdir)
                    log = logdir / pipeline.name.replace("/", "_") / suite_name / ut / attack.name / f"{inj}.json"
                    messages = json.loads(log.read_text(encoding="utf-8"))["messages"]
                    last = messages[-1]
                    reply = last["content"] if isinstance(last["content"], str) else " ".join(
                        b.get("content") or "" for b in last["content"] or [])
                    calls = [f"{tc['function']}({json.dumps(tc['args'], ensure_ascii=False)})"
                             for m in messages for tc in (m.get("tool_calls") or [])]
                    row.update(language=language, goal=goal, suite=suite_name, user_task=ut,
                               injection_task=inj, tool_calls=" ; ".join(calls), final_reply=reply)
                    writer.writerow({k: row[k] for k in FIELDS})
                    f.flush()
                    print(language, goal, "utility", row["utility"], "ATTACK SUCCEEDED" if row["security"] else "attack failed",
                          "error" if row["error"] else "", f"${llm.budget.spent_usd:.2f}", flush=True)
        except BudgetExceeded as e:
            print("STOPPED by budget:", e)
    print(f"assumed spend ${llm.budget.spent_usd:.2f} (prices from bench/budget.py)")


if __name__ == "__main__":
    main()
