"""Clean (no attack) runs of chosen user tasks, with tokens and seconds. Muse Spark Open.

    python -X utf8 -m bench.clean_runs --suite banking --goal 5 \
        --user-tasks user_task_4 user_task_9 user_task_14 \
        --out results/e0_goal5_swap_candidates.csv --logdir results/raw_logs/goal5_swap --max-usd 0.5
"""

import argparse
import csv
import json
import time
from pathlib import Path

from agentdojo.benchmark import benchmark_suite_without_injections
from agentdojo.logging import OutputLogger
from agentdojo.task_suite.load_suites import get_suite

from bench.adapters import MODELS, make_pipeline
from bench.budget import Budget
from bench.lean import VERSION

FIELDS = ["model", "suite", "goal", "user_task", "injection_task", "attack",
          "utility", "security", "tokens", "seconds", "error"]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite", required=True)
    parser.add_argument("--goal", type=int, required=True)
    parser.add_argument("--user-tasks", nargs="+", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--logdir", required=True)
    parser.add_argument("--max-usd", type=float, required=True)
    args = parser.parse_args()

    model_id = MODELS["muse-spark-open"]["model_id"]
    pipeline = make_pipeline("muse-spark-open")
    llm = next(e for e in pipeline.elements if hasattr(e, "calls"))
    llm.budget = Budget(args.max_usd)
    suite = get_suite(VERSION, args.suite)
    logdir = Path(args.logdir)

    with open(args.out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        for ut in args.user_tasks:
            in0, out0, t0 = llm.input_tokens, llm.output_tokens, time.perf_counter()
            with OutputLogger(str(logdir)):
                res = benchmark_suite_without_injections(
                    pipeline, suite, logdir=logdir, force_rerun=True, user_tasks=[ut], benchmark_version=VERSION)
            log = logdir / model_id.replace("/", "_") / args.suite / ut / "none" / "none.json"
            err = json.loads(log.read_text(encoding="utf-8")).get("error")
            row = {"model": model_id, "suite": args.suite, "goal": args.goal, "user_task": ut,
                   "injection_task": "", "attack": "none", "utility": res["utility_results"][(ut, "")],
                   "security": "", "tokens": (llm.input_tokens - in0) + (llm.output_tokens - out0),
                   "seconds": round(time.perf_counter() - t0, 1), "error": err or ""}
            writer.writerow(row)
            f.flush()
            print(row, flush=True)
    print(f"spend ${llm.budget.spent_usd:.3f} (prices from bench/budget.py)")


if __name__ == "__main__":
    main()
