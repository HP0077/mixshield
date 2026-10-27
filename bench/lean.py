"""Run one attacked user-task / injection-task pair, and nothing else.

AgentDojo's benchmark_suite_with_injections first runs every injection task as a plain
user task (a full extra model run, thousands of tokens). run_task_with_injection_tasks
skips that, so one call here is exactly one attacked run.
"""

import json
import time
from pathlib import Path

from agentdojo.attacks.base_attacks import BaseAttack
from agentdojo.benchmark import run_task_with_injection_tasks
from agentdojo.logging import OutputLogger

VERSION = "v1.2.2"


class TextAttack(BaseAttack):
    """Injects a fixed text (one per injection task) into every injection point the agent will see."""

    def __init__(self, name, texts, task_suite, target_pipeline):
        super().__init__(task_suite, target_pipeline)
        self.name = name
        self.texts = texts  # {injection_task_id: text}

    def attack(self, user_task, injection_task):
        text = self.texts[injection_task.ID]
        return {vector: text for vector in self.get_injection_candidates(user_task)}


def run_pair(suite, pipeline, llm, attack, user_task_id, injection_task_id, logdir: Path):
    """Return a dict: utility, security, tokens (in/out), calls, seconds, error."""
    in0, out0, calls0, t0 = llm.input_tokens, llm.output_tokens, len(llm.calls), time.perf_counter()
    user_task = suite.get_user_task_by_id(user_task_id)
    with OutputLogger(str(logdir)):
        utility, security = run_task_with_injection_tasks(
            suite, pipeline, user_task, attack, logdir, True, [injection_task_id], VERSION)
    key = (user_task_id, injection_task_id)
    path = (logdir / pipeline.name.replace("/", "_") / suite.name / user_task_id
            / attack.name / f"{injection_task_id}.json")
    error = json.loads(path.read_text(encoding="utf-8")).get("error")
    return {
        "utility": utility[key], "security": security[key],
        "input_tokens": llm.input_tokens - in0, "output_tokens": llm.output_tokens - out0,
        "model_calls": len(llm.calls) - calls0,
        "seconds": round(time.perf_counter() - t0, 1), "error": error or "",
    }
