"""Sanity check: with no attack, the attacker's goal must never be reached.

AgentDojo stores security=True for no-attack runs as a placeholder, so it cannot be
used for this check. Instead we replay each clean run's recorded tool calls on a fresh
environment and ask the goal's own scorer. A positive control (replaying the attack's
ground-truth steps) shows the check can say True.

Run from the repo root:
    python -X utf8 -m bench.check_clean_security results/e0_candidates.csv muse-spark-open [logdir]
"""

import csv
import json
import sys
from pathlib import Path

from agentdojo.functions_runtime import FunctionCall, FunctionsRuntime
from agentdojo.task_suite.load_suites import get_suite

from bench.adapters import MODELS
from bench.goals import GOALS, GOALS_V1

VERSION = "v1.2.2"
LOGDIR = Path(sys.argv[3] if len(sys.argv) > 3 else "results/raw_logs/e0_candidates")


def replay(suite, user_task, calls):
    """Run tool calls on a fresh environment; return (pre_env, post_env)."""
    env = suite.load_and_inject_default_environment({})
    env = user_task.init_environment(env) if user_task is not None else env
    pre = env.model_copy(deep=True)
    runtime = FunctionsRuntime(suite.tools)
    for call in calls:
        runtime.run_function(env, call.function, call.args)
    return pre, env


def main(csv_path: str) -> None:
    model_id = next(iter(MODELS.values()))["model_id"] if len(sys.argv) < 3 else MODELS[sys.argv[2]]["model_id"]
    # The first candidate file (e0_candidates.csv) used the original goal 5.
    goals = GOALS_V1 if "e0_candidates" in csv_path else GOALS
    goal_to_inj = {g: (suite, inj) for g, suite, inj in goals}
    rows = [r for r in csv.DictReader(open(csv_path, encoding="utf-8")) if r["attack"] == "none"]
    suites = {name: get_suite(VERSION, name) for name in ("banking", "workspace", "slack")}

    print("== Positive control: replaying each attack's own ground-truth steps")
    for goal, (suite_name, inj_id) in goal_to_inj.items():
        suite = suites[suite_name]
        inj = suite.injection_tasks[inj_id]
        env = suite.load_and_inject_default_environment({})
        calls = inj.ground_truth(env)
        pre, post = replay(suite, None, calls)
        ok = suite._check_task_result(inj, [], pre, post, calls)
        print(f"goal {goal} ({suite_name} {inj_id}): scorer says attack succeeded = {ok}")

    print("== Clean runs: did the attacker's goal get reached with no attack?")
    reached, mismatch = 0, 0
    for r in rows:
        suite_name, inj_id = goal_to_inj[int(r["goal"])]
        suite = suites[suite_name]
        user_task = suite.user_tasks[r["user_task"]]
        inj = suite.injection_tasks[inj_id]
        path = LOGDIR / model_id.replace("/", "_") / suite_name / r["user_task"] / "none" / "none.json"
        log = json.loads(path.read_text(encoding="utf-8"))
        messages = log["messages"]
        calls = [
            FunctionCall(function=tc["function"], args=tc["args"])
            for m in messages for tc in (m.get("tool_calls") or [])
        ]
        pre, post = replay(suite, user_task, calls)
        output = messages[-1]["content"] if messages[-1]["role"] == "assistant" else []
        attack_reached = suite._check_task_result(inj, output or [], pre, post, calls)
        utility_replay = suite._check_task_result(user_task, output or [], pre, post, calls)
        reached += attack_reached
        if utility_replay != log["utility"]:
            mismatch += 1
        print(f"goal {r['goal']} {suite_name} {r['user_task']}: attacker goal reached={attack_reached} "
              f"| replayed utility={utility_replay} logged utility={log['utility']}")
    print(f"SUMMARY: {len(rows)} clean runs, attacker goal reached in {reached}, "
          f"replay utility mismatches {mismatch}")


if __name__ == "__main__":
    main(sys.argv[1])
