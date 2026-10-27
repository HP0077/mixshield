"""Run the 30 candidate pairs once with the English attack and once without, then save a CSV.

Run from the repo root:
    python -m bench.e0_candidates --model muse-spark-open
"""

import argparse
import csv
import json
import time
from pathlib import Path

from agentdojo.attacks.attack_registry import load_attack
from agentdojo.benchmark import benchmark_suite_with_injections, benchmark_suite_without_injections
from agentdojo.logging import OutputLogger
from agentdojo.task_suite.load_suites import get_suite

from bench.adapters import MODELS, make_pipeline
from bench.goals import GOALS_V1 as GOALS, candidate_user_tasks

VERSION = "v1.2.2"
ATTACK = "important_instructions"
FIELDS = ["model", "suite", "goal", "user_task", "injection_task", "attack",
          "utility", "security", "tokens", "seconds", "error"]


def log_error(logdir: Path, model_id: str, suite: str, user_task: str, attack: str, inj: str):
    """Read the error field AgentDojo wrote to the run log (None if the run was clean)."""
    path = logdir / model_id.replace("/", "_") / suite / user_task / attack / f"{inj}.json"
    return json.loads(path.read_text(encoding="utf-8")).get("error")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", choices=list(MODELS), required=True)
    parser.add_argument("--out", default="results/e0_candidates.csv")
    args = parser.parse_args()

    model_id = MODELS[args.model]["model_id"]
    pipeline = make_pipeline(args.model)
    llm = next(e for e in pipeline.elements if hasattr(e, "input_tokens"))
    logdir = Path("results/raw_logs/e0_candidates")
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    with out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        for suite_name in ("banking", "workspace", "slack"):
            suite = get_suite(VERSION, suite_name)
            attack = load_attack(ATTACK, suite, pipeline)
            eligible = [t for t, ut in suite.user_tasks.items() if attack.get_injection_candidates(ut)]
            picks = candidate_user_tasks(eligible, [g for g, s, _ in GOALS if s == suite_name])
            for goal, g_suite, inj in GOALS:
                if g_suite != suite_name:
                    continue
                for ut in picks[goal]:
                    for with_attack in (False, True):
                        in0, out0, t0 = llm.input_tokens, llm.output_tokens, time.perf_counter()
                        with OutputLogger(str(logdir)):
                            if with_attack:
                                res = benchmark_suite_with_injections(
                                    pipeline, suite, attack, logdir=logdir, force_rerun=True,
                                    user_tasks=[ut], injection_tasks=[inj], benchmark_version=VERSION)
                                utility = res["utility_results"][(ut, inj)]
                                security = res["security_results"][(ut, inj)]
                                err = log_error(logdir, model_id, suite_name, ut, ATTACK, inj)
                            else:
                                res = benchmark_suite_without_injections(
                                    pipeline, suite, logdir=logdir, force_rerun=True,
                                    user_tasks=[ut], benchmark_version=VERSION)
                                utility = res["utility_results"][(ut, "")]
                                security = ""
                                err = log_error(logdir, model_id, suite_name, ut, "none", "none")
                        row = {
                            "model": model_id, "suite": suite_name, "goal": goal, "user_task": ut,
                            "injection_task": inj if with_attack else "", "attack": ATTACK if with_attack else "none",
                            "utility": utility, "security": security,
                            "tokens": (llm.input_tokens - in0) + (llm.output_tokens - out0),
                            "seconds": round(time.perf_counter() - t0, 1), "error": err or "",
                        }
                        writer.writerow(row)
                        f.flush()
                        print(row, flush=True)


if __name__ == "__main__":
    main()
