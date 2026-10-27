"""English baseline on the 10 fixed pairs: one clean run and one run with AgentDojo's
important_instructions attack, no defence, lean runner.

    python -X utf8 -m bench.baseline_runs --model muse-spark --out results/e0_baseline_muse-spark.csv --max-usd 2
"""

import argparse
import csv
import json
import time
from pathlib import Path

from agentdojo.attacks.attack_registry import load_attack
from agentdojo.benchmark import benchmark_suite_without_injections
from agentdojo.logging import OutputLogger
from agentdojo.task_suite.load_suites import get_suite

from bench.adapters import AGENTS, MODELS, make_pipeline
from bench.budget import Budget, BudgetExceeded
from bench.goals import FIXED_USER_TASK, GOALS
from bench.lean import VERSION, run_pair

FIELDS = ["model", "suite", "goal", "user_task", "injection_task", "attack", "utility", "security",
          "input_tokens", "output_tokens", "model_calls", "seconds", "error", "tool_calls", "final_reply"]


def read_log(path: Path):
    log = json.loads(path.read_text(encoding="utf-8"))
    messages = log["messages"]
    last = messages[-1]["content"]
    reply = last if isinstance(last, str) else " ".join(b.get("content") or "" for b in last or [])
    calls = [f"{tc['function']}({json.dumps(tc['args'], ensure_ascii=False)})"
             for m in messages for tc in (m.get("tool_calls") or [])]
    return reply, " ; ".join(calls)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", choices=list(MODELS), required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--agent", choices=list(AGENTS), default="default")
    parser.add_argument("--max-usd", type=float, required=True)
    args = parser.parse_args()

    model_id = MODELS[args.model]["model_id"]
    pipeline = make_pipeline(args.model, agent=args.agent)
    llm = next(e for e in pipeline.elements if hasattr(e, "calls"))
    llm.budget = Budget(args.max_usd)
    logdir = Path("results/raw_logs") / (f"e0_baseline_{args.model}" + ("" if args.agent == "default" else f"_{args.agent}"))
    folder = logdir / model_id.replace("/", "_")

    with open(args.out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        try:
            for goal, suite_name, inj in GOALS:
                suite = get_suite(VERSION, suite_name)
                ut = FIXED_USER_TASK[goal]
                base = {"model": model_id, "suite": suite_name, "goal": goal, "user_task": ut}

                in0, out0, c0, t0 = llm.input_tokens, llm.output_tokens, len(llm.calls), time.perf_counter()
                with OutputLogger(str(logdir)):
                    res = benchmark_suite_without_injections(
                        pipeline, suite, logdir=logdir, force_rerun=True, user_tasks=[ut], benchmark_version=VERSION)
                path = folder / suite_name / ut / "none" / "none.json"
                reply, calls = read_log(path)
                clean = {**base, "injection_task": "", "attack": "none", "utility": res["utility_results"][(ut, "")],
                         "security": "", "input_tokens": llm.input_tokens - in0, "output_tokens": llm.output_tokens - out0,
                         "model_calls": len(llm.calls) - c0, "seconds": round(time.perf_counter() - t0, 1),
                         "error": json.loads(path.read_text(encoding="utf-8")).get("error") or "",
                         "tool_calls": calls, "final_reply": reply}
                writer.writerow(clean)

                attack = load_attack("important_instructions", suite, pipeline)
                row = run_pair(suite, pipeline, llm, attack, ut, inj, logdir)
                reply, calls = read_log(folder / suite_name / ut / "important_instructions" / f"{inj}.json")
                row.update(base, injection_task=inj, attack="important_instructions", tool_calls=calls, final_reply=reply)
                writer.writerow({k: row[k] for k in FIELDS})
                f.flush()
                print(f"goal {goal}: clean utility {clean['utility']} | attacked utility {row['utility']}, "
                      f"{'ATTACK SUCCEEDED' if row['security'] else 'attack failed'}"
                      f"{' ERROR ' + row['error'][:60] if row['error'] or clean['error'] else ''} ${llm.budget.spent_usd:.3f}", flush=True)
        except BudgetExceeded as e:
            print("STOPPED by budget:", e)
    print(f"spend ${llm.budget.spent_usd:.3f}")


if __name__ == "__main__":
    main()
