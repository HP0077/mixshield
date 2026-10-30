"""Shared pieces for E3/E4 runs: one run through AgentDojo's own pipeline and scorer, and one CSV row per run.

`run_job` runs one (user task, injection task) pair with run_task_with_injection_tasks (bench.lean.run_pair, no
hidden extra job) and AgentDojo's own scorer. For a run without an attack, NoAttack injects nothing, so AgentDojo
still scores the injection task on the clean run (its own check, not a placeholder): attack success must be 0.

Not measurable (same rules as E1, bench/e1_run.py): utility of goal 0, attack success of goal 4. Raw values are kept.
"""

import json
from pathlib import Path

from agentdojo.attacks.base_attacks import BaseAttack

from bench.e1_run import (ATTACK_SUCCESS_NOT_MEASURABLE_GOALS, UTILITY_NOT_MEASURABLE_GOALS, attacker_email_sent,
                          yaml_escape)
from bench.lean import run_pair

FIELDS = ["experiment", "agent", "defence", "attack_id", "goal", "style", "split", "language", "suite", "user_task",
          "injection_task", "utility", "utility_raw", "attack_success", "attack_success_raw",
          "secondary_attacker_email_sent", "obedient_attacked", "gate_allow", "gate_ask", "gate_block",
          "approved", "declined", "user_calls_refused", "screened", "flagged", "screen_unavailable",
          "input_tokens", "output_tokens", "model_calls", "seconds", "error", "status", "tool_calls", "refused",
          "final_reply"]


class NoAttack(BaseAttack):
    """Injects nothing (every injection point keeps its default text)."""

    def __init__(self, task_suite, target_pipeline) -> None:
        super().__init__(task_suite, target_pipeline)
        self.name = "noattack"

    def attack(self, user_task, injection_task):
        return {}


def run_job(job: dict, suite, pipeline, llm, attack, logdir: Path, state=None) -> dict:
    """job: goal, suite, user_task, injection_task (+ attack_id, style, split, language, text when attacked)."""
    row = run_pair(suite, pipeline, llm, attack, job["user_task"], job["injection_task"], logdir)
    path = (logdir / pipeline.name.replace("/", "_") / job["suite"] / job["user_task"] / attack.name
            / f"{job['injection_task']}.json")
    log = json.loads(path.read_text(encoding="utf-8"))
    assert (log["suite_name"], log["user_task_id"], log["injection_task_id"]) == (
        job["suite"], job["user_task"], job["injection_task"]), f"log mix-up: {path}"
    if job.get("text") is not None:
        assert set(log["injections"].values()) == {yaml_escape(job["text"])}, f"wrong injected text in {path}"
    else:
        assert not log["injections"], f"injections in a no-attack run: {path}"

    messages = log["messages"]
    last = messages[-1]["content"]
    reply = last if isinstance(last, str) else " ".join(b.get("content") or "" for b in last or [])
    calls, refused = [], []
    for m in messages:
        if m["role"] == "tool" and m.get("error"):
            refused.append(f"{m['tool_call']['function']}: {m['error'][:200]}")
        for tc in m.get("tool_calls") or []:
            calls.append(f"{tc['function']}({json.dumps(tc['args'], ensure_ascii=False)})")
    success_raw = row.pop("security")
    out = {**job, **row,
           "utility": "not_measurable" if job["goal"] in UTILITY_NOT_MEASURABLE_GOALS else row["utility"],
           "utility_raw": row["utility"],
           "attack_success": "not_measurable" if job["goal"] in ATTACK_SUCCESS_NOT_MEASURABLE_GOALS else success_raw,
           "attack_success_raw": success_raw,
           "secondary_attacker_email_sent": attacker_email_sent(executed_only(messages)),
           "obedient_attacked": getattr(llm, "attacked", ""),
           "tool_calls": " ; ".join(calls), "refused": " ; ".join(refused), "final_reply": reply[:2000]}
    if state is not None:
        out.update(summarise(state.events))
    return out


def executed_only(messages: list) -> list:
    """The messages with every tool call removed whose result is an error (refused by a defence, or failed), so
    our goal 4 check counts only calls that ran. With no defence nothing is removed except failed calls (E1 had none
    to the attacker)."""
    failed = {m["tool_call_id"] for m in messages if m["role"] == "tool" and m.get("error")}
    return [{**m, "tool_calls": [tc for tc in m["tool_calls"] if tc.get("id") not in failed]}
            if m.get("tool_calls") else m for m in messages]


def summarise(events: list[dict]) -> dict:
    gate = [e for e in events if e["kind"] == "gate"]
    screen = [e for e in events if e["kind"] == "screen"]
    return {"gate_allow": sum(e["action"] == "allow" for e in gate),
            "gate_ask": sum(e["action"] == "ask" for e in gate),
            "gate_block": sum(e["action"] == "block" for e in gate),
            "approved": sum(e.get("approved") is True for e in gate),
            "declined": sum(e.get("approved") is False for e in gate),
            "user_calls_refused": sum(e.get("refused", False) and e.get("by_user_task", False) for e in gate),
            "screened": len(screen), "flagged": sum(e["flagged"] for e in screen),
            "screen_unavailable": sum(e["unavailable"] for e in screen)}
