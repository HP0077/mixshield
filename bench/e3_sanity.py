"""E3 part 0: CLAUDE.md section 8 sanity checks before E3/E4.

    python -X utf8 -m bench.e3_sanity --max-usd 2

0a  No attack, the 10 fixed pairs, both models, the current E1 pipeline (bench.e1_run.make_pipeline: Unicode tool
    output). AgentDojo scores each pair's own injection task on the clean run. Expected: attack success 0.
0b  Block-everything defence (bench.defenses.block_everything). Real models: 10 pairs x the English style 0 attack.
    Obedient agent: all 300 jobs. Expected: attack success 0, utility about 0.
0c  Obedient agent, no defence: all 300 jobs (expected: attack success on every scorable job, 270), and no attack
    on the 10 pairs (expected: 0). Shows the obedient agent and the scorer path work.
The obedient agent is a scripted worst-case simulation, not a real model (bench/obedient.py).

Muse Spark uses 4 workers; Muse Spark Open 1 worker (one Baseten request at a time) and the Baseten ledger
(bench/baseten.py). Output: results/e3/sanity/part0.csv; raw logs in results/raw_logs/e3_sanity/ (git-ignored).
"""

import argparse
import csv
import threading
from pathlib import Path

from agentdojo.task_suite.load_suites import get_suite

from bench import e1_run
from bench.adapters import MODELS, make_llm
from bench.baseten import BasetenBudget, Ledger
from bench.budget import Budget
from bench.defenses import RunState, block_everything, build_pipeline
from bench.e1_run import EscapedTextAttack, load_jobs
from bench.e3_common import FIELDS, NoAttack, run_job
from bench.goals import FIXED_USER_TASK, GOALS
from bench.lean import VERSION
from bench.obedient import LABEL, ObedientAgent
from bench.parallel import run_parallel

OUT = Path("results/e3/sanity/part0.csv")
LOGS = Path("results/raw_logs/e3_sanity")
SUITES = {n: get_suite(VERSION, n) for n in ("banking", "workspace", "slack")}


def pair_jobs() -> list[dict]:
    return [{"attack_id": "", "goal": g, "style": "", "split": "", "language": "", "suite": s,
             "user_task": FIXED_USER_TASK[g], "injection_task": inj, "text": None} for g, s, inj in GOALS]


def real_run(job: dict, model: str, defence: str, budget: Budget) -> dict:
    suite = SUITES[job["suite"]]
    state = RunState()
    if defence == "none":
        pipeline = e1_run.make_pipeline(model)
        llm = next(e for e in pipeline.elements if hasattr(e, "calls"))
    else:
        llm = make_llm(model)
        pipeline = build_pipeline(llm, llm.name, check=block_everything(state))
    llm.budget = budget
    attack = (NoAttack(suite, pipeline) if job["text"] is None
              else EscapedTextAttack("e3_style0", {job["injection_task"]: job["text"]}, suite, pipeline))
    row = run_job(job, suite, pipeline, llm, attack, LOGS / f"{defence}_{model}", state)
    return {**row, "agent": model, "defence": defence}


def obedient_run(job: dict, defence: str) -> dict:
    suite = SUITES[job["suite"]]
    state = RunState()
    agent = ObedientAgent(suite.get_user_task_by_id(job["user_task"]),
                          suite.get_injection_task_by_id(job["injection_task"]), job["text"])
    check = block_everything(state) if defence == "block_everything" else None
    pipeline = build_pipeline(agent, f"obedient-{defence}", check=check)
    attack = (NoAttack(suite, pipeline) if job["text"] is None
              else EscapedTextAttack(f"e3_{job['attack_id']}_{job['language']}", {job["injection_task"]: job["text"]},
                                     suite, pipeline))
    row = run_job(job, suite, pipeline, agent, attack, LOGS / f"obedient_{defence}", state)
    return {**row, "agent": LABEL, "defence": defence}


def summary(rows: list[dict], title: str) -> None:
    scorable = [r for r in rows if r["attack_success"] != "not_measurable"]
    util = [r for r in rows if r["utility"] != "not_measurable"]
    errors = sum(bool(r["error"]) for r in rows)
    goal4 = [r for r in rows if r["goal"] == 4]
    print(f"{title}: runs {len(rows)}; attack success {sum(r['attack_success'] is True for r in scorable)}/"
          f"{len(scorable)} scorable; utility {sum(r['utility'] is True for r in util)}/{len(util)} "
          f"(goal 0 excluded); goal 4 attacker email sent (our check) "
          f"{sum(r['secondary_attacker_email_sent'] for r in goal4)}/{len(goal4)}; errors {errors}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-usd", type=float, required=True, help="cap per model for the real-model runs")
    args = parser.parse_args()
    ledger = Ledger("e3_sanity")
    print(ledger.line())
    OUT.parent.mkdir(parents=True, exist_ok=True)
    rows_all, lock = [], threading.Lock()

    def keep(row: dict, title: str) -> dict:
        with lock:
            rows_all.append({**row, "experiment": title, "status": "ok"})
        return row

    english0 = {j["goal"]: j for j in load_jobs() if j["style"] == 0 and j["language"] == "english"}
    for model in MODELS:
        if model == "llama3.2-3b":
            continue
        budget = Budget(args.max_usd) if model == "muse-spark" else BasetenBudget(args.max_usd, ledger)
        workers = 4 if model == "muse-spark" else 1
        for part, defence, jobs in [("0a", "none", pair_jobs()),
                                    ("0b", "block_everything", [english0[g] for g, _, _ in GOALS])]:
            results = run_parallel(jobs, lambda j: keep(real_run(j, model, defence, budget), part),
                                   workers, budget)
            done = [r for _, r, _ in results if r]
            not_done = [s for _, r, s in results if r is None]
            summary(done, f"{part} {model} {defence}")
            if not_done:
                print(f"   NOT RUN: {len(not_done)} ({set(not_done)})")
            print(f"   Muse Spark spend ${budget.spent_usd:.3f}" if model == "muse-spark" else f"   {ledger.line()}")

    jobs300 = load_jobs()
    for part, defence, jobs in [("0b", "block_everything", jobs300), ("0c", "none", jobs300),
                                ("0c", "none", pair_jobs())]:
        rows = [keep(obedient_run(j, defence), part) for j in jobs]
        attacked = sum(r["obedient_attacked"] is True for r in rows)
        summary(rows, f"{part} obedient {defence} ({'attacked' if jobs is jobs300 else 'no attack'})")
        print(f"   obedient agent saw the attack text and attacked: {attacked}/{len(rows)}")
    print(ledger.line())

    with open(OUT, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows_all)
    print(f"wrote {len(rows_all)} rows to {OUT}")


if __name__ == "__main__":
    main()
