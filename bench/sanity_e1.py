"""CLAUDE.md section 8 sanity checks for E1 (no API calls).

    python -X utf8 -m bench.sanity_e1

A. Positive control. Run bench.e1_run.one_run (its exact scoring path) with fake pipelines instead of a model:
   - one that executes the injection task's ground-truth calls: attack_success must be 1;
   - one that does nothing: attack_success must be 0, and utility 0 (utility is "not_measurable" for pair 0).
   Jobs: banking goal 0, workspace goal 6, slack goal 8.
B. Ground-truth control on all 300 jobs: the injection task's own calls must score attack_success 1. The jobs that
   do not must be exactly the goals in ATTACK_SUCCESS_NOT_MEASURABLE_GOALS (goal 4, see bench/e1_run.py).
C. Load check. All 300 jobs load their environment with the escaped text (0 errors), and the attack text is in the
   environment. Jobs where only blank lines changed are counted by language and style.
"""

import collections
import re

from agentdojo.agent_pipeline.ground_truth_pipeline import GroundTruthPipeline
from agentdojo.logging import Logger
from agentdojo.task_suite.load_suites import get_suite
from agentdojo.types import ChatAssistantMessage, text_content_block_from_string

from bench import e1_run
from bench.budget import Budget
from bench.lean import VERSION

CONTROL_JOBS = [(0, "english"), (6, "hinglish"), (8, "hindi")]  # (goal, language), style 0
current: dict = {}


class FakeLLM:
    """Stands in for the model object that one_run reads token counts from."""

    def __init__(self) -> None:
        self.calls: list = []
        self.input_tokens = 0
        self.output_tokens = 0
        self.budget = None


class FakePipeline:
    def __init__(self, kind: str) -> None:
        self.name = f"fake-{kind}"
        self.kind = kind
        self.elements = [FakeLLM()]

    def query(self, query, runtime, env=None, messages=(), extra_args={}):
        if self.kind == "do-nothing":
            msg = ChatAssistantMessage(role="assistant", tool_calls=None,
                                       content=[text_content_block_from_string("I did nothing.")])
            out = [*messages, msg]
            Logger().get().log(out)
            return query, runtime, env, out, extra_args
        suite = get_suite(VERSION, current["job"]["suite"])
        injection_task = suite.get_injection_task_by_id(current["job"]["injection_task"])
        result = GroundTruthPipeline(injection_task).query(query, runtime, env, messages, extra_args)
        Logger().get().log(result[3])
        return result


def positive_control(jobs: list[dict]) -> bool:
    ok = True
    real_make_pipeline = e1_run.make_pipeline
    try:
        for kind in ("ground-truth", "do-nothing"):
            e1_run.make_pipeline = lambda model, kind=kind: FakePipeline(kind)
            for job in jobs:
                current["job"] = job
                row = e1_run.one_run(job, f"sanity-{kind}", Budget(1.0), e1_run.ErrorWatch(Budget(1.0)))
                success, utility = int(row["attack_success_raw"]), row["utility"]
                if kind == "ground-truth":
                    good = success == 1 and not row["error"]
                else:
                    good = success == 0 and utility in (0, False, "not_measurable") and not row["error"]
                ok &= good
                print(f"{'ok  ' if good else 'FAIL'} {kind:12} goal {job['goal']} {job['suite']:9} "
                      f"attack_success={success} utility={utility} (raw {row['utility_raw']}) error={row['error']!r}")
    finally:
        e1_run.make_pipeline = real_make_pipeline
    return ok


def ground_truth_all(jobs: list[dict]) -> bool:
    real_make_pipeline = e1_run.make_pipeline
    e1_run.make_pipeline = lambda model: FakePipeline("ground-truth")
    failed, secondary_missed = [], []
    try:
        for job in jobs:
            current["job"] = job
            row = e1_run.one_run(job, "sanity-all", Budget(1.0), e1_run.ErrorWatch(Budget(1.0)))
            if row["attack_success_raw"] is not True:
                failed.append(job)
            # Our own secondary check must see the attacker's email in the ground-truth run of goal 4.
            if job["goal"] == 4 and row["secondary_attacker_email_sent"] is not True:
                secondary_missed.append(job)
    finally:
        e1_run.make_pipeline = real_make_pipeline
    goals = sorted({j["goal"] for j in failed})
    by_language = dict(collections.Counter(j["language"] for j in failed))
    print(f"ground truth scored as attack success: {len(jobs) - len(failed)}/{len(jobs)}; "
          f"not scored: {len(failed)} (goals {goals}, by language {by_language})")
    print(f"secondary_attacker_email_sent missed in goal 4 ground-truth runs: {len(secondary_missed)}/30")
    return goals == sorted(e1_run.ATTACK_SUCCESS_NOT_MEASURABLE_GOALS) and not secondary_missed


def strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for value in obj.values():
            yield from strings(value)
    elif isinstance(obj, (list, tuple, set)):
        for value in obj:
            yield from strings(value)


def load_check(jobs: list[dict]) -> bool:
    collapse = lambda s: re.sub(r"\s+", " ", s).strip()  # noqa: E731
    counts = collections.Counter()
    collapsed = []
    for job in jobs:
        suite = get_suite(VERSION, job["suite"])
        user_task = suite.get_user_task_by_id(job["user_task"])
        attack = e1_run.EscapedTextAttack("sanity", {job["injection_task"]: job["text"]}, suite, None)
        injections = attack.attack(user_task, suite.get_injection_task_by_id(job["injection_task"]))
        try:
            env = suite.load_and_inject_default_environment(injections)
        except Exception as e:
            counts["load error"] += 1
            print("load error:", job["attack_id"], job["language"], type(e).__name__)
            continue
        found = list(strings(env.model_dump()))
        if any(job["text"] in s for s in found):
            counts["exact"] += 1
        elif any(collapse(job["text"]) in collapse(s) for s in found):
            counts["only blank lines collapsed"] += 1
            collapsed.append(job)
        else:
            counts["TEXT CHANGED"] += 1
            print("text changed:", job["attack_id"], job["language"])
    print("load check:", dict(counts))
    by_attack = collections.defaultdict(set)
    for job in collapsed:
        by_attack[job["attack_id"]].add(job["language"])
    print("blank lines collapsed, by language:", dict(collections.Counter(j["language"] for j in collapsed)))
    print("blank lines collapsed, by style:", dict(sorted(collections.Counter(j["style"] for j in collapsed).items())))
    partial = {a: sorted(langs) for a, langs in by_attack.items() if len(langs) != 3}
    print(f"attacks with collapsed blank lines: {len(by_attack)}; not in all 3 languages: {partial or 'none'}")
    return counts["load error"] == 0 and counts["TEXT CHANGED"] == 0


def formatter_check() -> bool:
    """The E1 pipeline's tool output formatter keeps Devanagari letters (AgentDojo's default escapes them)."""
    word = "".join(chr(c) for c in (0x939, 0x93F, 0x902, 0x926, 0x940))
    pipeline = e1_run.make_pipeline("muse-spark")  # builds the client only, no API call
    executors = e1_run._executors(pipeline.elements)
    shown = executors[0].output_formatter([f"text {word}"])
    ok = len(executors) == 1 and word in shown
    print(f"{'ok  ' if ok else 'FAIL'} formatter keeps Devanagari letters: {shown!r}")
    return ok


def main() -> None:
    jobs = e1_run.load_jobs()
    control = [next(j for j in jobs if j["goal"] == g and j["language"] == lang and j["style"] == 0)
               for g, lang in CONTROL_JOBS]
    print("A. positive control")
    ok_a = positive_control(control)
    print("\nB. ground-truth control, all 300 jobs")
    ok_b = ground_truth_all(jobs)
    print("\nC. load check, all 300 jobs")
    ok_c = load_check(jobs)
    print("\nD. tool output formatter")
    ok_d = formatter_check()
    print("\nRESULT:", "all checks passed" if ok_a and ok_b and ok_c and ok_d else "FAILED")


if __name__ == "__main__":
    main()
