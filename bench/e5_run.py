"""E5: attacks MixShield was not built on, on the OBEDIENT AGENT (a scripted worst-case simulation, not a real model).

    python -X utf8 -m bench.e5_run --part a --configs none pg2_0.5 lg3 mixshield_trusting mixshield_strict
    python -X utf8 -m bench.e5_run --part b --configs none pg2_0.5 lg3 mixshield_trusting mixshield_strict
    python -X utf8 -m bench.e5_run --text-detect      # each detector on each attack text alone (as in E2)
    python -X utf8 -m bench.e5_run --stats

Part a: AgentDojo 0.1.35's own text attacks (written independently of MixShield), English, on the 10 fixed pairs:
  BUILTIN below. Left out: "manual" (asks a person to type the text) and the five "dos" attacks (their goal is to
  stop the agent, not the injection task). The text is AgentDojo's own, injected exactly as AgentDojo makes it.
  The model name the attacks write is "AI assistant", as for the real agents (bench/adapters.py).
Part b: bench/attacks/adaptive_sheet.csv, 30 Hinglish attempts by the author, written after MixShield was built
  (not an expert red-teamer). Injected as in E3a (EscapedTextAttack). Used only if bench.check_texts has 0 errors.

Same configs, verdict cache (results/e3/cache/), gate, approvers and Baseten ledger/stop as E3a (bench/e3_run.py).
Nothing is tuned on these results. Per job we also record what the config's detector said about the tool outputs
that carry the attack text ("injected") and about the other outputs ("clean").
Output: results/e5/e5<part>_<config>.csv, results/e5/events/, results/e5/text_detect.csv; raw logs in
results/raw_logs/e5/ (git-ignored).
"""

import argparse
import csv
import json
import shutil
import time
from pathlib import Path

from agentdojo.attacks.attack_registry import load_attack
from agentdojo.models import MODEL_NAMES

from bench.defenses import RunState, ToolScreen, build_pipeline
from bench.e1_exposure import exposure
from bench.e1_run import EscapedTextAttack
from bench.e3_common import FIELDS, run_job
from bench.e3_run import CONFIGS, MAX_UNAVAILABLE, MIN_FOR_RATE, SUITES, Detectors, defence_parts
from bench.goals import FIXED_USER_TASK, GOALS
from bench.obedient import LABEL, ObedientAgent

OUT = Path("results/e5")
LOGS = Path("results/raw_logs/e5")
ADAPTIVE = Path("bench/attacks/adaptive_sheet.csv")
E5_CONFIGS = ["none", "pg2_0.5", "lg3", "mixshield_trusting", "mixshield_strict"]
BUILTIN = ["direct", "ignore_previous", "system_message", "injecagent", "important_instructions",
           "important_instructions_no_user_name", "important_instructions_no_model_name",
           "important_instructions_no_names", "important_instructions_wrong_model_name",
           "important_instructions_wrong_user_name", "tool_knowledge"]
PIPELINE_PREFIX = "obedient-e5"
MODEL_NAMES[PIPELINE_PREFIX] = "AI assistant"  # built-in attacks look the model name up from the pipeline name
DETECT_FIELDS = ["injected_outputs", "injected_flagged", "clean_outputs", "clean_flagged"]
GOAL_INFO = {g: (s, inj) for g, s, inj in GOALS}


class _NamedPipeline:
    name = PIPELINE_PREFIX  # only .name is read when a built-in attack builds its text


def builtin_jobs() -> list[dict]:
    jobs = []
    for attack_name in BUILTIN:
        for goal, suite_name, inj in GOALS:
            suite = SUITES[suite_name]
            attack = load_attack(attack_name, suite, _NamedPipeline())
            user_task = FIXED_USER_TASK[goal]
            texts = set(attack.attack(suite.get_user_task_by_id(user_task), suite.get_injection_task_by_id(inj))
                        .values())
            assert len(texts) == 1, f"{attack_name} goal {goal}: {len(texts)} different texts"
            text = texts.pop()
            jobs.append({"attack_id": f"{attack_name}_{goal}", "goal": goal, "style": attack_name, "split": "e5",
                         "language": "english", "suite": suite_name, "user_task": user_task, "injection_task": inj,
                         "text": text, "injected_text": text})
    return jobs


def adaptive_jobs() -> list[dict]:
    jobs = []
    with open(ADAPTIVE, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            goal = int(r["goal_id"])
            suite_name, inj = GOAL_INFO[goal]
            jobs.append({"attack_id": r["id"], "goal": goal, "style": r["strategy"], "split": "e5",
                         "language": "hinglish", "suite": suite_name, "user_task": FIXED_USER_TASK[goal],
                         "injection_task": inj, "text": r["hinglish_text"]})
    assert len(jobs) == 30
    return jobs


def recording(detect, seen: list):
    def wrapped(text):
        verdict = detect(text)
        seen.append((text, verdict.flagged))
        return verdict
    return wrapped


def obedient_run(job: dict, part: str, name: str, detectors: Detectors) -> tuple[dict, list]:
    suite = SUITES[job["suite"]]
    state, seen = RunState(), []
    agent = ObedientAgent(suite.get_user_task_by_id(job["user_task"]),
                          suite.get_injection_task_by_id(job["injection_task"]), job["text"])
    check, screen = defence_parts(CONFIGS[name], job["suite"], state, detectors)
    if screen is not None:
        screen = ToolScreen(recording(screen.detect, seen), screen.action, state)
    pipeline = build_pipeline(agent, f"{PIPELINE_PREFIX}-{name}", check=check, screen=screen)
    if part == "a":
        attack = load_attack(job["style"], suite, pipeline)
    else:
        attack = EscapedTextAttack(f"e5_{job['attack_id']}", {job["injection_task"]: job["text"]}, suite, pipeline)
    row = run_job(job, suite, pipeline, agent, attack, LOGS / f"e5{part}", state)
    injected = [flag for text, flag in seen if exposure(job["text"], [text])]
    clean = [flag for text, flag in seen if not exposure(job["text"], [text])]
    row.update({"injected_outputs": len(injected), "injected_flagged": sum(injected),
                "clean_outputs": len(clean), "clean_flagged": sum(clean)})
    return {**row, "experiment": f"e5{part}", "agent": LABEL, "defence": name}, state.events


def run(part: str, configs: list[str]) -> None:
    jobs = builtin_jobs() if part == "a" else adaptive_jobs()
    detectors = Detectors(f"e5_run part {part} {' '.join(configs)}")
    (OUT / "events").mkdir(parents=True, exist_ok=True)
    for name in configs:
        old_logs = LOGS / f"e5{part}" / f"{PIPELINE_PREFIX}-{name}"
        if old_logs.exists():
            shutil.rmtree(old_logs)  # AgentDojo may load an old log even with force_rerun
        rows, stopped, began = [], "", time.perf_counter()
        with open(OUT / "events" / f"e5{part}_{name}.jsonl", "w", encoding="utf-8") as events_file:
            for n, job in enumerate(jobs, 1):
                row, events = obedient_run(job, part, name, detectors)
                row["status"] = "ok"
                rows.append(row)
                events_file.write(json.dumps({"attack_id": job["attack_id"], "events": events},
                                             ensure_ascii=False) + "\n")
                screened = sum(int(r["screened"] or 0) for r in rows)
                unavailable = sum(int(r["screen_unavailable"] or 0) for r in rows)
                if detectors.ledger and detectors.ledger.stopped:
                    stopped = "Baseten cap reached"
                elif screened >= MIN_FOR_RATE and unavailable / screened > MAX_UNAVAILABLE:
                    stopped = f"screen unavailable {unavailable}/{screened}"
                if n % 25 == 0 or stopped:
                    print(f"  {name}: {n}/{len(jobs)} jobs, {time.perf_counter() - began:.0f} s"
                          + (f"; {detectors.ledger.line()}" if detectors.ledger else ""), flush=True)
                if stopped:
                    print(f"STOP: {stopped}. The last run may be affected; this config is incomplete.", flush=True)
                    break
        with open(OUT / f"e5{part}_{name}.csv", "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS + DETECT_FIELDS, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        scorable = [r for r in rows if r["attack_success"] != "not_measurable"]
        print(f"{name}: {len(rows)} jobs; ASR {sum(r['attack_success'] is True for r in scorable)}/{len(scorable)}; "
              f"obedient agent attacked {sum(r['obedient_attacked'] is True for r in rows)}/{len(rows)}; "
              f"injected outputs flagged {sum(r['injected_flagged'] for r in rows)}/"
              f"{sum(r['injected_outputs'] for r in rows)}; clean flagged {sum(r['clean_flagged'] for r in rows)}/"
              f"{sum(r['clean_outputs'] for r in rows)}; unavailable {sum(int(r['screen_unavailable'] or 0) for r in rows)}"
              f"; errors {sum(bool(r['error']) for r in rows)}", flush=True)
        if stopped:
            break
    if detectors.ledger:
        print(detectors.ledger.line())


def text_detect() -> None:
    """Each detector on each attack text alone (as in E2), from the same verdict cache."""
    detectors = Detectors("e5_run text-detect")
    rows = []
    for part, jobs in (("a", builtin_jobs()), ("b", adaptive_jobs())):
        for job in jobs:
            row = {"part": part, "attack_id": job["attack_id"], "goal": job["goal"], "style": job["style"]}
            for name in ("pg2_0.5", "lg3", "mixshield"):
                verdict = detectors.get(name)(job["text"])
                row[name] = verdict.flagged
                row[f"{name}_reason"] = verdict.reason
                if name == "mixshield" and verdict.unavailable:
                    row["mixshield"] = "unavailable"
            rows.append(row)
            if detectors.ledger and detectors.ledger.stopped:
                print("STOP: Baseten cap reached.")
                break
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "text_detect.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"{len(rows)} texts scored")
    if detectors.ledger:
        print(detectors.ledger.line())


def frac(rows, test) -> str:
    return f"{sum(test(r) for r in rows)}/{len(rows)}"


def pct(rows, test) -> str:
    return f"{100 * sum(test(r) for r in rows) / len(rows):.1f}" if rows else "-"


def stats() -> None:
    success = lambda r: r["attack_success"] == "True"  # noqa: E731
    text_rows = list(csv.DictReader(open(OUT / "text_detect.csv", encoding="utf-8"))) \
        if (OUT / "text_detect.csv").exists() else []
    titles = {"a": "Part (a): AgentDojo built-in attacks (written independently of MixShield), English",
              "b": "Part (b): author-written adaptive attempts (not an expert red-teamer), Hinglish"}
    for part in ("a", "b"):
        data = {n: list(csv.DictReader(open(OUT / f"e5{part}_{n}.csv", encoding="utf-8")))
                for n in E5_CONFIGS if (OUT / f"e5{part}_{n}.csv").exists()}
        if not data:
            continue
        expected = 110 if part == "a" else 30
        print(f"\n## {titles[part]}\nObedient agent (scripted worst-case simulation, not a real model). "
              f"ASR % (attack success / scorable; goal 4 not scorable).")
        groups = BUILTIN if part == "a" else sorted({r["style"] for r in next(iter(data.values()))})
        print("| Attack | " + " | ".join(data) + " |\n| --- |" + " --- |" * len(data))
        for group in [*groups, "all"]:
            cells = []
            for rows in data.values():
                sel = [r for r in rows if (group == "all" or r["style"] == group)
                       and r["attack_success"] != "not_measurable"]
                cells.append(f"{pct(sel, success)} ({frac(sel, success)})")
            print(f"| {group} | " + " | ".join(cells) + " |")
        print("\n| Defence | Rows | Obedient agent saw the text | Injected outputs flagged | Clean outputs flagged | "
              "Gate block | Gate ask | Declined | User-task calls refused (jobs) | Goal 4 email sent (our check) | "
              "Unavailable | Errors |\n| --- |" + " --- |" * 11)
        for name, rows in data.items():
            s = lambda col: sum(int(r[col] or 0) for r in rows)  # noqa: E731
            goal4 = [r for r in rows if r["goal"] == "4"]
            note = "" if len(rows) == expected and all(r["status"] == "ok" for r in rows) else " INCOMPLETE"
            print(f"| {name}{note} | {len(rows)} | {frac(rows, lambda r: r['obedient_attacked'] == 'True')} | "
                  f"{s('injected_flagged')}/{s('injected_outputs')} | {s('clean_flagged')}/{s('clean_outputs')} | "
                  f"{s('gate_block')} | {s('gate_ask')} | {s('declined')} | "
                  f"{frac(rows, lambda r: int(r['user_calls_refused'] or 0) > 0)} | "
                  f"{frac(goal4, lambda r: r['secondary_attacker_email_sent'] == 'True')} | "
                  f"{s('screen_unavailable')} | {sum(bool(r['error']) for r in rows)} |")
        sel = [r for r in text_rows if r["part"] == part]
        if sel:
            print(f"\nDetection on the attack text alone (as in E2), {len(sel)} texts:")
            print("| Attack | Prompt Guard 2 at 0.5 | Llama Guard 3 1B | MixShield screen |\n| --- | --- | --- | --- |")
            for group in [*groups, "all"]:
                g = [r for r in sel if group == "all" or r["style"] == group]
                print(f"| {group} | " + " | ".join(frac(g, lambda r, n=n: r[n] == "True")
                                                   for n in ("pg2_0.5", "lg3", "mixshield")) + " |")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--part", choices=["a", "b"])
    parser.add_argument("--configs", nargs="+", choices=E5_CONFIGS)
    parser.add_argument("--text-detect", action="store_true")
    parser.add_argument("--stats", action="store_true")
    args = parser.parse_args()
    if args.stats:
        stats()
    elif args.text_detect:
        text_detect()
    else:
        run(args.part, args.configs)


if __name__ == "__main__":
    main()
