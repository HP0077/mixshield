"""Run own attack texts on the fixed pairs, several runs each, no defence, Muse Spark Open, lean runner.

    python -X utf8 -m bench.pilot_runs --texts bench/attacks/pilot_strong_hinglish.txt \
        --name pilot_strong --repeats 3 --out results/pilot_strong_hinglish.csv --max-usd 1
"""

import argparse
import csv
import json
from pathlib import Path

from agentdojo.task_suite.load_suites import get_suite

from bench.adapters import MODELS, make_pipeline
from bench.budget import Budget, BudgetExceeded
from bench.goals import FIXED_USER_TASK, GOALS
from bench.lean import VERSION, TextAttack, run_pair
from bench.pilot import FIELDS, load_texts


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--texts", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--repeats", type=int, required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--max-usd", type=float, required=True)
    parser.add_argument("--model", choices=list(MODELS), default="muse-spark-open")
    parser.add_argument("--skip-goals", type=int, nargs="*", default=[])
    args = parser.parse_args()

    pipeline = make_pipeline(args.model)
    llm = next(e for e in pipeline.elements if hasattr(e, "calls"))
    llm.budget = Budget(args.max_usd)
    logdir = Path("results/raw_logs") / args.name
    texts = load_texts(args.texts)
    goal_info = {g: (s, inj) for g, s, inj in GOALS}
    fields = ["run"] + FIELDS

    with open(args.out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        try:
            for goal, text in texts.items():
                if goal in args.skip_goals:
                    continue
                suite_name, inj = goal_info[goal]
                suite = get_suite(VERSION, suite_name)
                ut = FIXED_USER_TASK[goal]
                for run in range(1, args.repeats + 1):
                    attack = TextAttack(f"{args.name}_run{run}", {inj: text}, suite, pipeline)
                    row = run_pair(suite, pipeline, llm, attack, ut, inj, logdir)
                    log = logdir / pipeline.name.replace("/", "_") / suite_name / ut / attack.name / f"{inj}.json"
                    messages = json.loads(log.read_text(encoding="utf-8"))["messages"]
                    last = messages[-1]["content"]
                    reply = last if isinstance(last, str) else " ".join(b.get("content") or "" for b in last or [])
                    calls = [f"{tc['function']}({json.dumps(tc['args'], ensure_ascii=False)})"
                             for m in messages for tc in (m.get("tool_calls") or [])]
                    row.update(run=run, language=args.name, goal=goal, suite=suite_name, user_task=ut,
                               injection_task=inj, tool_calls=" ; ".join(calls), final_reply=reply)
                    writer.writerow({k: row[k] for k in fields})
                    f.flush()
                    print(f"goal {goal} run {run}: utility {row['utility']}, "
                          f"{'ATTACK SUCCEEDED' if row['security'] else 'attack failed'}"
                          f"{' ERROR ' + row['error'][:60] if row['error'] else ''} ${llm.budget.spent_usd:.3f}", flush=True)
        except BudgetExceeded as e:
            print("STOPPED by budget:", e)
    print(f"spend ${llm.budget.spent_usd:.3f}")


if __name__ == "__main__":
    main()
