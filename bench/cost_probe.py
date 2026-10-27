"""Cost probe: run a few attacked tasks and report tokens and seconds per run.

Run from the repo root:
    python -m bench.cost_probe --model muse-spark-open
"""

import argparse
import time
from pathlib import Path

from agentdojo.attacks.attack_registry import load_attack
from agentdojo.benchmark import benchmark_suite_with_injections
from agentdojo.logging import OutputLogger
from agentdojo.task_suite.load_suites import get_suite

from bench.adapters import MODELS, make_pipeline

VERSION = "v1.2.2"
# (suite, user task, injection task). Only for measuring cost, not for results.
PROBE_PAIRS = [
    ("banking", "user_task_0", "injection_task_0"),
    ("workspace", "user_task_0", "injection_task_0"),
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", choices=list(MODELS), required=True)
    args = parser.parse_args()

    pipeline = make_pipeline(args.model)
    llm = next(e for e in pipeline.elements if hasattr(e, "input_tokens"))
    logdir = Path("results/raw_logs/cost_probe")

    totals = []
    for suite_name, user_task, injection_task in PROBE_PAIRS:
        suite = get_suite(VERSION, suite_name)
        attack = load_attack("important_instructions", suite, pipeline)
        in0, out0, t0 = llm.input_tokens, llm.output_tokens, time.perf_counter()
        with OutputLogger(str(logdir)):
            benchmark_suite_with_injections(
                pipeline, suite, attack, logdir=logdir, force_rerun=True,
                user_tasks=[user_task], injection_tasks=[injection_task],
                benchmark_version=VERSION,
            )
        row = (llm.input_tokens - in0, llm.output_tokens - out0, time.perf_counter() - t0)
        totals.append(row)
        print(f"{suite_name} {user_task}/{injection_task}: in={row[0]} out={row[1]} seconds={row[2]:.1f}")

    n = len(totals)
    avg_in = sum(r[0] for r in totals) / n
    avg_out = sum(r[1] for r in totals) / n
    avg_sec = sum(r[2] for r in totals) / n
    print(f"average over {n} runs: in={avg_in:.0f} out={avg_out:.0f} total={avg_in + avg_out:.0f} seconds={avg_sec:.1f}")


if __name__ == "__main__":
    main()
