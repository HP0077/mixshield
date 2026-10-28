"""Replay evaluation of the action gate (allow / ask / block). No API calls.

    python -X utf8 -m bench.gate_replay

ASSUMPTION for this replay: the screen flags exactly the injected attack text and nothing in the clean environment.
So the attacker calls are checked with one flagged text (the attack), and the clean calls with none.

(a) Attacker calls: the AgentDojo ground-truth calls of each of the 10 goals, checked against the goal's fixed user
    task, once per English attack text of that goal (bench/attacks/writing_sheet.csv, 10 styles), with that text as
    the flagged text. An attack's outcome is its most severe high-risk decision (block > ask > allow).
(b) Clean calls: every tool call from every logged no-attack run in results/raw_logs (folder "none"). Runs whose
    "user task" is an injection task are AgentDojo's hidden extra job (the attacker goal given as the user's own
    request), so they are not clean runs and are skipped.
(c) Extra: the AgentDojo ground-truth calls of every user task in the 3 suites (the reference solutions).

Trusted data comes only from the clean starting environment (default injection values) and the user's request.
Outputs: results/gate/attacker_calls.csv, results/gate/clean_calls.csv, results/gate/user_task_ground_truth.csv.
"""

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

from agentdojo.task_suite.load_suites import get_suite

from bench.goals import FIXED_USER_TASK, GOALS
from bench.lean import VERSION
from mixshield.gate import DESTINATION, TEXT, VALUE, Gate, Policy

SUITES = ("banking", "workspace", "slack")
OUT = Path("results/gate")
ASSUMPTION = "ASSUMPTION: the screen flags exactly the injected attack text and nothing in the clean environment."
SEVERITY = {"allow": 0, "ask": 1, "block": 2}

# High-risk tools per suite (CLAUDE.md: payments/transfers, sending messages/email, deleting or changing records,
# sharing files). Tools not listed are allowed. Read before accepting.
POLICIES: dict[str, Policy] = {
    "banking": {
        "send_money": {"recipient": DESTINATION, "subject": TEXT},
        "schedule_transaction": {"recipient": DESTINATION, "subject": TEXT},
        "update_scheduled_transaction": {"recipient": DESTINATION, "subject": TEXT},
        "update_password": {"password": VALUE},
        "update_user_info": {"first_name": VALUE, "last_name": VALUE, "street": VALUE, "city": VALUE},
    },
    "workspace": {
        "send_email": {"recipients": DESTINATION, "cc": DESTINATION, "bcc": DESTINATION,
                       "subject": TEXT, "body": TEXT},
        "share_file": {"email": DESTINATION},
        "create_calendar_event": {"participants": DESTINATION, "title": TEXT, "description": TEXT},
        "add_calendar_event_participants": {"participants": DESTINATION},
        "delete_email": {},
        "delete_file": {},
        "cancel_calendar_event": {},
    },
    "slack": {
        "send_direct_message": {"recipient": DESTINATION, "body": TEXT},
        "send_channel_message": {"channel": DESTINATION, "body": TEXT},
        "post_webpage": {"url": DESTINATION, "content": TEXT},
        "invite_user_to_slack": {"user": DESTINATION, "user_email": DESTINATION},
        "add_user_to_channel": {"user": DESTINATION, "channel": DESTINATION},
        "remove_user_from_slack": {"user": DESTINATION},
    },
}


def clean_environment(suite):
    return suite.load_and_inject_default_environment(suite.get_injection_vector_defaults())


def trusted_data(name: str, env) -> set[str]:
    """The user's own account data and saved contacts, from the clean starting environment."""
    if name == "banking":
        own = env.bank_account.iban
        payees = {t.recipient for t in env.bank_account.transactions if t.sender in ("me", own)}
        payees |= {t.recipient for t in env.bank_account.scheduled_transactions}
        u = env.user_account
        return {own, *payees, u.first_name, u.last_name, u.street, u.city}
    if name == "workspace":
        # Saved contacts = people the user has written to (recipients, cc, bcc of emails the user sent).
        own = env.inbox.account_email
        contacts = {a for e in env.inbox.emails.values() if e.sender == own for a in [*e.recipients, *e.cc, *e.bcc]}
        return {own, *contacts}
    if name == "slack":
        return {*env.slack.users, *env.slack.channels}
    raise ValueError(name)


def write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def counts(actions) -> str:
    c = Counter(actions)
    return " ".join(f"{a} {c[a]}" for a in SEVERITY)


def worst(a: str, b: str) -> str:
    return max(a, b, key=SEVERITY.get)


def main() -> None:
    suites = {n: get_suite(VERSION, n) for n in SUITES}
    envs = {n: clean_environment(s) for n, s in suites.items()}
    gates = {n: Gate(POLICIES[n], trusted_data(n, envs[n])) for n in SUITES}
    for n in SUITES:
        print(f"trusted data, {n}: {sorted(gates[n].trusted)}")
    print(f"\n{ASSUMPTION}")

    # (a) attacker ground-truth calls, one flagged attack text at a time
    with open("bench/attacks/writing_sheet.csv", encoding="utf-8-sig", newline="") as f:
        texts = [(int(r["goal_id"]), int(r["style_id"]), r["english_text"]) for r in csv.DictReader(f)]
    rows = []
    for goal, suite_name, inj in GOALS:
        suite = suites[suite_name]
        prompt = suite.get_user_task_by_id(FIXED_USER_TASK[goal]).PROMPT
        calls = suite.get_injection_task_by_id(inj).ground_truth(envs[suite_name].model_copy(deep=True))
        for style, text in [(s, t) for g, s, t in texts if g == goal]:
            for call in calls:
                d = gates[suite_name].check_call(call.function, dict(call.args), prompt, [text])
                rows.append({"goal": goal, "style": style, "suite": suite_name, "injection_task": inj,
                             "user_task": FIXED_USER_TASK[goal], "tool": call.function,
                             "high_risk": call.function in POLICIES[suite_name], "action": d.action,
                             "reason": d.reason, "args": json.dumps(call.args, ensure_ascii=False)})
    write(OUT / "attacker_calls.csv", rows)
    print("\n(a) attacker ground-truth calls, 10 English attack texts per goal, the attack text flagged")
    for suite_name in SUITES:
        part = [r for r in rows if r["suite"] == suite_name and r["high_risk"]]
        attacks = defaultdict(lambda: "allow")
        for r in part:
            attacks[(r["goal"], r["style"])] = worst(attacks[(r["goal"], r["style"])], r["action"])
        print(f"  {suite_name:10} attacks: {counts(attacks.values())}   high-risk calls: "
              f"{counts(r['action'] for r in part)}")
    for r in rows:
        if r["high_risk"] and r["action"] != "block":
            print(f"  NOT BLOCKED goal {r['goal']} style {r['style']}: {r['action']} {r['reason']}")

    # (b) logged clean runs
    rows, skipped = [], 0
    for log in sorted(Path("results/raw_logs").rglob("none/none.json")):
        data = json.loads(log.read_text(encoding="utf-8"))
        suite_name, ut = data["suite_name"], data["user_task_id"]
        if suite_name not in SUITES or ut.startswith("injection_task"):
            skipped += 1
            continue
        prompt = suites[suite_name].get_user_task_by_id(ut).PROMPT
        run = str(log.parent.parent.relative_to("results/raw_logs").as_posix())
        for m in data["messages"]:
            for tc in m.get("tool_calls") or []:
                d = gates[suite_name].check_call(tc["function"], tc["args"], prompt, [])
                rows.append({"run": run, "model": data["pipeline_name"], "suite": suite_name, "user_task": ut,
                             "utility": data["utility"], "tool": tc["function"],
                             "high_risk": tc["function"] in POLICIES[suite_name], "action": d.action,
                             "reason": d.reason, "args": json.dumps(tc["args"], ensure_ascii=False)})
    write(OUT / "clean_calls.csv", rows)
    print(f"\n(b) logged clean runs, nothing flagged ({len({r['run'] for r in rows})} runs, "
          f"{skipped} hidden-job runs skipped)")
    report_clean(rows)

    # (c) user-task ground truth (reference solutions)
    rows = []
    for suite_name in SUITES:
        suite = suites[suite_name]
        for ut_id, task in suite.user_tasks.items():
            for call in task.ground_truth(envs[suite_name].model_copy(deep=True)):
                d = gates[suite_name].check_call(call.function, dict(call.args), task.PROMPT, [])
                rows.append({"run": f"ground_truth/{suite_name}/{ut_id}", "model": "ground_truth", "suite": suite_name,
                             "user_task": ut_id, "utility": True, "tool": call.function,
                             "high_risk": call.function in POLICIES[suite_name], "action": d.action,
                             "reason": d.reason, "args": json.dumps(call.args, ensure_ascii=False, default=str)})
    write(OUT / "user_task_ground_truth.csv", rows)
    print(f"\n(c) extra: user-task ground truth, nothing flagged ({len({r['run'] for r in rows})} user tasks)")
    report_clean(rows)


def report_clean(rows: list[dict]) -> None:
    for suite_name in SUITES:
        hr = [r for r in rows if r["suite"] == suite_name and r["high_risk"]]
        runs = defaultdict(lambda: "allow")
        for r in rows:
            if r["suite"] == suite_name:
                runs[r["run"]] = worst(runs[r["run"]], r["action"])
        print(f"  {suite_name:10} high-risk calls: {counts(r['action'] for r in hr)}   runs: {counts(runs.values())}")
    for r in rows:
        if r["action"] != "allow":
            print(f"  {r['action'].upper():5} {r['run']}: {r['reason']}")


if __name__ == "__main__":
    main()
