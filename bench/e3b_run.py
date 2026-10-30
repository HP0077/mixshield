"""E3b: utility of a REAL agent (Muse Spark, muse-spark-1.3) with each defence, no attacks, all 77 user tasks of
banking, workspace and slack, 1 run each.

    python -X utf8 -m bench.e3b_run --max-usd 20 --configs none mixshield_strict mixshield_trusting \
        pg2_0.0006 lg3 pg2_0.5
    python -X utf8 -m bench.e3b_run --stats

Configs and defences are the same objects as in E3a (bench/e3_run.py CONFIGS, bench/defenses.py), with the gate fix of
30 Oct. Every config, "none" included, uses the same pipeline shape (bench.defenses.build_pipeline), so the defence is
the only difference. Scored by AgentDojo's own utility checks (run_task_without_injection_tasks).

Dev / test user tasks (fixed 30 Oct, before any E3b run): user_task_N is dev when N mod 10 is 0, 1 or 2. The choice
between the strict and the trusting approver is made on dev only (docs/pilot_results.md).

Muse Spark: 4 workers, one dollar cap shared by all configs (--max-usd). The MixShield screen: one Baseten request at
a time (bench/baseten.py lock) and the $65 Baseten total stop. Verdict cache: results/e3b/cache/ (E3b only).
Stops: dollar cap, Baseten stop, more than 5% of runs with an error, or more than 5% of screen verdicts unavailable.
Output: results/e3b/e3b_<config>.csv, results/e3b/events/<config>.jsonl, raw logs in results/raw_logs/e3b/.
"""

import argparse
import csv
import json
import threading
import time
from pathlib import Path

from agentdojo.benchmark import run_task_without_injection_tasks
from agentdojo.logging import OutputLogger

from bench.adapters import make_llm
from bench.budget import Budget, BudgetExceeded
from bench.defenses import RunState, build_pipeline
from bench.e3_common import summarise
from bench.e3_run import CONFIGS, SUITES, Detectors, defence_parts
from bench.lean import VERSION
from bench.parallel import run_parallel

OUT = Path("results/e3b")
LOGS = Path("results/raw_logs/e3b")
MODEL = "muse-spark"
E3B_CONFIGS = ["none", "mixshield_strict", "mixshield_trusting", "pg2_0.0006", "lg3", "pg2_0.5"]
MAX_RATE = 0.05
MIN_FOR_RATE = 20
FIELDS = ["config", "suite", "user_task", "split", "utility", "gate_allow", "gate_ask", "gate_block", "approved",
          "declined", "screened", "flagged", "screen_unavailable", "input_tokens", "output_tokens", "model_calls",
          "seconds", "error", "status", "tool_calls", "refused", "flag_reasons", "final_reply"]


def split_of_task(user_task: str) -> str:
    return "dev" if int(user_task.rsplit("_", 1)[1]) % 10 in (0, 1, 2) else "test"


def jobs() -> list[dict]:
    found = [{"suite": name, "user_task": ut, "split": split_of_task(ut)}
             for name, suite in SUITES.items() for ut in sorted(suite.user_tasks, key=lambda t: int(t.rsplit("_")[-1]))]
    assert len(found) == 77, len(found)
    return found


def one_run(job: dict, name: str, budget: Budget, detectors: Detectors) -> tuple[dict, list]:
    suite = SUITES[job["suite"]]
    state = RunState()
    llm = make_llm(MODEL)
    llm.budget = budget
    check, screen = defence_parts(CONFIGS[name], job["suite"], state, detectors)
    pipeline = build_pipeline(llm, f"{llm.name}-{name}", check=check, screen=screen)
    logdir = LOGS / name
    task = suite.get_user_task_by_id(job["user_task"])
    began = time.perf_counter()
    with OutputLogger(str(logdir)):
        utility, _ = run_task_without_injection_tasks(suite, pipeline, task, logdir, True, VERSION)
    path = logdir / pipeline.name.replace("/", "_") / job["suite"] / job["user_task"] / "none" / "none.json"
    log = json.loads(path.read_text(encoding="utf-8"))
    assert (log["suite_name"], log["user_task_id"]) == (job["suite"], job["user_task"]), f"log mix-up: {path}"
    messages = log["messages"]
    last = messages[-1]["content"]
    reply = last if isinstance(last, str) else " ".join(b.get("content") or "" for b in last or [])
    calls = [f"{tc['function']}({json.dumps(tc['args'], ensure_ascii=False)})"
             for m in messages for tc in (m.get("tool_calls") or [])]
    refused = [f"{m['tool_call']['function']}: {m['error'][:200]}" for m in messages
               if m["role"] == "tool" and m.get("error")]
    reasons = [f"{e['tool']}: {e['reason'][:150]}" for e in state.events if e["kind"] == "screen" and e["flagged"]]
    row = {**job, "config": name, "utility": utility, **summarise(state.events),
           "input_tokens": llm.input_tokens, "output_tokens": llm.output_tokens, "model_calls": len(llm.calls),
           "seconds": round(time.perf_counter() - began, 1), "error": log.get("error") or "",
           "tool_calls": " ; ".join(calls), "refused": " ; ".join(refused), "flag_reasons": " ; ".join(reasons),
           "final_reply": reply[:2000]}
    return row, state.events


def run_config(name: str, budget: Budget, detectors: Detectors) -> bool:
    """Returns False if the run must stop (nothing more is started)."""
    rows, lock = [], threading.Lock()
    events_file = open(OUT / "events" / f"{name}.jsonl", "w", encoding="utf-8")
    stop = {"why": ""}

    def run_and_keep(job):
        if stop["why"]:
            raise BudgetExceeded(stop["why"])  # not started; recorded as stopped
        row, events = one_run(job, name, budget, detectors)
        row["status"] = "ok"
        with lock:
            rows.append(row)
            events_file.write(json.dumps({"user_task": f"{job['suite']}/{job['user_task']}", "events": events},
                                         ensure_ascii=False) + "\n")
            events_file.flush()
            errors = sum(bool(r["error"]) for r in rows)
            screened = sum(r["screened"] for r in rows)
            unavailable = sum(r["screen_unavailable"] for r in rows)
            if detectors.ledger and detectors.ledger.stopped:
                stop["why"] = "Baseten $65 total stop"
            elif len(rows) >= MIN_FOR_RATE and errors / len(rows) > MAX_RATE:
                stop["why"] = f"error rate {errors}/{len(rows)}"
            elif screened >= MIN_FOR_RATE and unavailable / screened > MAX_RATE:
                stop["why"] = f"screen unavailable {unavailable}/{screened}"
            if stop["why"]:
                budget.exhausted = True
            baseten = f"; {detectors.ledger.line()}" if detectors.ledger else ""
            print(f"  {name} {len(rows):2}/77 {job['suite']:9} {job['user_task']:13} utility {str(row['utility']):5} "
                  f"ask {row['gate_ask']} block {row['gate_block']} declined {row['declined']} flagged {row['flagged']}"
                  f"{' ERROR ' + row['error'][:50] if row['error'] else ''}  Muse Spark ${budget.spent_usd:.2f}"
                  f"{baseten}", flush=True)
        return row

    results = run_parallel(jobs(), run_and_keep, 4, budget)
    events_file.close()
    with open(OUT / f"e3b_{name}.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        for job, row, status in results:
            writer.writerow(row or {**job, "config": name, "status": status})
    done = [r for _, r, _ in results if r]
    print(f"{name}: {len(done)}/77 runs; utility {sum(r['utility'] for r in done)}/{len(done)}; errors "
          f"{sum(bool(r['error']) for r in done)}{'; STOP: ' + stop['why'] if stop['why'] else ''}", flush=True)
    return len(done) == 77 and not budget.exhausted


def stats() -> None:
    data = {}
    for name in E3B_CONFIGS:
        path = OUT / f"e3b_{name}.csv"
        if path.exists():
            data[name] = list(csv.DictReader(open(path, encoding="utf-8")))
    base = {(r["suite"], r["user_task"]): r["utility"] == "True" for r in data.get("none", []) if r["status"] == "ok"}
    print("Agent: Muse Spark (real model), no attacks, 77 user tasks, 1 run.")
    print("| Defence | Utility dev (25) | Utility test (52) | Utility all | Lost vs none / gained | Runs with ask "
          "| Runs with block | Runs with a declined ask | Runs with a flagged output | Not run |")
    print("| --- |" + " --- |" * 9)
    for name, rows in data.items():
        ok = [r for r in rows if r["status"] == "ok"]
        u = lambda sel: f"{100 * sum(r['utility'] == 'True' for r in sel) / len(sel):.1f} ({sum(r['utility'] == 'True' for r in sel)}/{len(sel)})" if sel else "-"  # noqa: E731
        key = lambda r: (r["suite"], r["user_task"])  # noqa: E731
        lost = sum(base.get(key(r)) is True and r["utility"] != "True" for r in ok)
        gained = sum(base.get(key(r)) is False and r["utility"] == "True" for r in ok)
        n = lambda col: sum(int(r[col] or 0) > 0 for r in ok)  # noqa: E731
        print(f"| {name} | {u([r for r in ok if r['split'] == 'dev'])} | {u([r for r in ok if r['split'] == 'test'])} | "
              f"{u(ok)} | {lost} / {gained} | {n('gate_ask')} | {n('gate_block')} | {n('declined')} | {n('flagged')} | "
              f"{len(rows) - len(ok)} |")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-usd", type=float, help="Muse Spark dollar cap, shared by all configs")
    parser.add_argument("--configs", nargs="+", choices=E3B_CONFIGS, default=E3B_CONFIGS)
    parser.add_argument("--stats", action="store_true")
    args = parser.parse_args()
    if args.stats:
        return stats()
    assert args.max_usd, "--max-usd is required"
    (OUT / "events").mkdir(parents=True, exist_ok=True)
    budget = Budget(args.max_usd)
    detectors = Detectors(f"e3b_run {' '.join(args.configs)}", cache_dir=OUT / "cache")
    for name in args.configs:
        if not run_config(name, budget, detectors):
            print(f"stopped after {name}; configs not run: {args.configs[args.configs.index(name) + 1:]}")
            break
    print(f"Muse Spark spend ${budget.spent_usd:.2f} of ${args.max_usd:.2f}"
          + (f"; {detectors.ledger.line()}" if detectors.ledger else ""))
    stats()


if __name__ == "__main__":
    main()
