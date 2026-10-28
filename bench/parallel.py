"""Run lean agent runs in parallel (at most 4 at a time) with one shared dollar budget.

    python -X utf8 -m bench.parallel --model muse-spark-open --workers 4 --max-usd 0.5 \
        --out results/parallel_test_w4.csv

`run_parallel(jobs, run_one, workers, budget)` is the reusable part. `run_one(job)` runs in a worker thread and must
build its own pipeline (so token counts belong to one run) and attach the shared `budget` to the model object.

Two thread problems handled here:
  - Budget: one shared, locked running total (bench/budget.py). When the cap is passed, running calls finish, no new
    model call starts, and jobs not yet started are skipped. Status of each job is "ok", "stopped by budget" or
    "not started".
  - AgentDojo's logger stack is a ContextVar with a shared mutable default list. Threads that do not set it all push
    onto the same list, and one run can write its log into another run's file. Each worker sets its own empty stack.
The CLI test runs the 10 fixed pairs with no attack (clean utility only).
"""

import argparse
import csv
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

from agentdojo.benchmark import benchmark_suite_without_injections
from agentdojo.logging import LOGGER_STACK, OutputLogger
from agentdojo.task_suite.load_suites import get_suite

from bench.adapters import MODELS, make_pipeline
from bench.budget import Budget, BudgetExceeded
from bench.goals import FIXED_USER_TASK, GOALS
from bench.lean import VERSION

MAX_WORKERS = 4
FIELDS = ["goal", "suite", "user_task", "utility", "input_tokens", "output_tokens", "model_calls",
          "seconds", "error", "status"]


def run_parallel(jobs: list[Any], run_one: Callable[[Any], dict], workers: int,
                 budget: Budget) -> list[tuple[Any, dict | None, str]]:
    """Return (job, row or None, status) for every job, in job order."""
    if not 1 <= workers <= MAX_WORKERS:
        raise ValueError(f"workers must be 1 to {MAX_WORKERS}")

    def guarded(job):
        LOGGER_STACK.set([])  # this thread's own logger stack (see module docstring)
        if budget.exhausted:
            return job, None, "not started"
        try:
            return job, run_one(job), "ok"
        except BudgetExceeded:
            return job, None, "stopped by budget"

    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(guarded, jobs))


def clean_run(job: tuple[int, str, str], model: str, budget: Budget, logdir: Path) -> dict:
    goal, suite_name, user_task = job
    pipeline = make_pipeline(model)
    llm = next(e for e in pipeline.elements if hasattr(e, "calls"))
    llm.budget = budget
    suite = get_suite(VERSION, suite_name)
    start = time.perf_counter()
    with OutputLogger(str(logdir)):
        res = benchmark_suite_without_injections(
            pipeline, suite, logdir=logdir, force_rerun=True, user_tasks=[user_task], benchmark_version=VERSION)
    log = logdir / pipeline.name.replace("/", "_") / suite_name / user_task / "none" / "none.json"
    return {"goal": goal, "suite": suite_name, "user_task": user_task,
            "utility": res["utility_results"][(user_task, "")],
            "input_tokens": llm.input_tokens, "output_tokens": llm.output_tokens, "model_calls": len(llm.calls),
            "seconds": round(time.perf_counter() - start, 1),
            "error": json.loads(log.read_text(encoding="utf-8")).get("error") or ""}


def check_logs(logdir: Path, jobs: list[tuple[int, str, str]]) -> int:
    """Count logs whose content does not match their folder (the mix-up described above). Should be 0."""
    wrong = 0
    for _, suite_name, user_task in jobs:
        for log in logdir.rglob(f"{suite_name}/{user_task}/none/none.json"):
            data = json.loads(log.read_text(encoding="utf-8"))
            if data["suite_name"] != suite_name or data["user_task_id"] != user_task:
                wrong += 1
    return wrong


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", choices=list(MODELS), required=True)
    parser.add_argument("--workers", type=int, choices=range(1, MAX_WORKERS + 1), default=MAX_WORKERS)
    parser.add_argument("--max-usd", type=float, required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    budget = Budget(args.max_usd)
    logdir = Path("results/raw_logs") / f"parallel_test_w{args.workers}"
    jobs = [(goal, suite_name, FIXED_USER_TASK[goal]) for goal, suite_name, _ in GOALS]
    start = time.perf_counter()
    results = run_parallel(jobs, lambda job: clean_run(job, args.model, budget, logdir), args.workers, budget)
    total = time.perf_counter() - start

    with open(args.out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        for job, row, status in results:
            writer.writerow({**(row or {"goal": job[0], "suite": job[1], "user_task": job[2]}), "status": status})
            print(f"goal {job[0]}: {status}" + (f", utility {row['utility']}, {row['seconds']} s" if row else ""))
    done = [r for _, r, _ in results if r]
    print(f"\nworkers {args.workers}: total {total:.1f} s wall time for {len(done)}/{len(jobs)} runs; "
          f"sum of single-run times {sum(r['seconds'] for r in done):.1f} s")
    print(f"utility {sum(r['utility'] for r in done)}/{len(done)}; spend ${budget.spent_usd:.3f} "
          f"of ${args.max_usd:.2f} (prices from bench/budget.py)")
    print(f"logs that do not match their folder: {check_logs(logdir, jobs)}")


if __name__ == "__main__":
    main()
