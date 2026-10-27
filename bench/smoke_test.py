"""Smoke test: run a tiny AgentDojo job with one model and print utility and security.

Run from the repo root:
    python -m bench.smoke_test --model muse-spark
    python -m bench.smoke_test --model muse-spark --attack
"""

import argparse
from pathlib import Path

from agentdojo.attacks.attack_registry import load_attack
from agentdojo.logging import OutputLogger
from agentdojo.benchmark import benchmark_suite_with_injections, benchmark_suite_without_injections
from agentdojo.task_suite.load_suites import get_suite

from bench.adapters import MODELS, make_pipeline

VERSION = "v1.2.2"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", choices=list(MODELS), required=True)
    parser.add_argument("--suite", default="banking")
    parser.add_argument("--user-task", default="user_task_0")
    parser.add_argument("--injection-task", default="injection_task_0")
    parser.add_argument("--attack", action="store_true", help="also run one attacked task")
    args = parser.parse_args()

    suite = get_suite(VERSION, args.suite)
    pipeline = make_pipeline(args.model)
    logdir = Path("results/raw_logs/smoke")

    with OutputLogger(str(logdir)):
        clean = benchmark_suite_without_injections(
            pipeline, suite, logdir=logdir, force_rerun=True,
            user_tasks=[args.user_task], benchmark_version=VERSION,
        )
    print("no injection, utility results:", clean["utility_results"])

    if args.attack:
        attack = load_attack("important_instructions", suite, pipeline)
        with OutputLogger(str(logdir)):
            attacked = benchmark_suite_with_injections(
                pipeline, suite, attack, logdir=logdir, force_rerun=True,
                user_tasks=[args.user_task], injection_tasks=[args.injection_task],
                benchmark_version=VERSION,
            )
        print("with injection, utility results:", attacked["utility_results"])
        print("with injection, security results (True = attack succeeded):", attacked["security_results"])


if __name__ == "__main__":
    main()
