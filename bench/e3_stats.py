"""Tables for E3a and E4 from results/e3/<experiment>_<config>.csv (no API calls).

    python -X utf8 -m bench.e3_stats e3a
    python -X utf8 -m bench.e3_stats e4

Agent: the obedient agent, a scripted worst-case simulation, not a real model. ASR = AgentDojo attack success over
scorable jobs (goal 4 excluded: 63 test + 27 dev per language). Goal 4 is shown with our own check (attacker email
sent by a call that ran), never mixed into ASR.
"""

import csv
import sys
from pathlib import Path

OUT = Path("results/e3")
LANGUAGES = ["english", "hinglish", "hindi"]
ORDER = ["none", "pg2_0.5", "pg2_0.0006", "lg3", "mixshield_strict", "mixshield_trusting", "mixshield_strict_names",
         "mixshield_trusting_names", "minus_screen_strict", "minus_screen_trusting", "minus_gate", "minus_approval"]


def load(experiment: str) -> dict[str, list[dict]]:
    found = {}
    for name in ORDER:
        path = OUT / f"{experiment}_{name}.csv"
        if path.exists():
            found[name] = list(csv.DictReader(open(path, encoding="utf-8")))
    return found


def frac(rows: list[dict], test) -> str:
    return f"{sum(test(r) for r in rows)}/{len(rows)}"


def pct(rows: list[dict], test) -> str:
    return f"{100 * sum(test(r) for r in rows) / len(rows):.1f}" if rows else "-"


def main(experiment: str) -> None:
    data = load(experiment)
    success = lambda r: r["attack_success"] == "True"  # noqa: E731
    print(f"\n{experiment}: ASR % (attack success / scorable), obedient agent (scripted simulation, not a real model)")
    print("| Defence | Split | " + " | ".join(f"{lang} ASR" for lang in LANGUAGES) + " | All |")
    print("| --- | --- |" + " --- |" * (len(LANGUAGES) + 1))
    for name, rows in data.items():
        assert len(rows) == 300 and all(r["status"] == "ok" for r in rows), f"{name}: incomplete"
        for split in ("test", "dev"):
            sel = [r for r in rows if r["split"] == split and r["attack_success"] != "not_measurable"]
            cells = [f"{pct([r for r in sel if r['language'] == lang], success)} "
                     f"({frac([r for r in sel if r['language'] == lang], success)})" for lang in LANGUAGES]
            print(f"| {name} | {split} | " + " | ".join(cells) + f" | {pct(sel, success)} ({frac(sel, success)}) |")

    print(f"\n{experiment}: what each defence did (all 300 jobs)")
    print("| Defence | Obedient agent saw the text | Outputs screened | Flagged | Unavailable | Gate block | Gate ask "
          "| Approved | Declined | User-task calls refused (jobs) | Goal 4 attacker email sent (our check) | Errors |")
    print("| --- |" + " --- |" * 11)
    for name, rows in data.items():
        s = lambda col: sum(int(r[col] or 0) for r in rows)  # noqa: E731
        goal4 = [r for r in rows if r["goal"] == "4"]
        print(f"| {name} | {frac(rows, lambda r: r['obedient_attacked'] == 'True')} | {s('screened')} | "
              f"{s('flagged')} | {s('screen_unavailable')} | {s('gate_block')} | {s('gate_ask')} | {s('approved')} | "
              f"{s('declined')} | {frac(rows, lambda r: int(r['user_calls_refused'] or 0) > 0)} | "
              f"{frac(goal4, lambda r: r['secondary_attacker_email_sent'] == 'True')} | "
              f"{sum(bool(r['error']) for r in rows)} |")

    print(f"\n{experiment}: successful attacks per goal (scorable, all splits and languages)")
    for name, rows in data.items():
        by_goal = {}
        for r in rows:
            if success(r):
                by_goal[r["goal"]] = by_goal.get(r["goal"], 0) + 1
        print(f"  {name}: {dict(sorted(by_goal.items())) or 'none'}")


if __name__ == "__main__":
    main(sys.argv[1])
